#!/usr/bin/env python3
"""
Re-encode existing episode audio from 192kbps to 96kbps MP3.

Downloads each episode MP3 from R2, re-encodes at 96kbps with loudness
normalization preserved, and uploads back — overwriting the original.

Expected savings: ~50% reduction in audio storage.

Usage:
    python pipeline/scripts/backfill_compress_audio.py              # compress all episodes
    python pipeline/scripts/backfill_compress_audio.py --dry-run    # preview sizes without uploading
    python pipeline/scripts/backfill_compress_audio.py --limit 10   # process first 10 only
"""

import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config

# Load .env.production
ENV_FILE = Path(__file__).parent.parent.parent / ".env.production"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

# R2 configuration
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
R2_ENDPOINT = f"https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"
R2_BUCKET = "mwp-episodes"
TARGET_BITRATE = "96k"
MAX_WORKERS = 4
DOWNLOAD_TIMEOUT = 120


def get_r2_client():
    access_key_id = os.environ.get("CF_R2_KEY_ID") or os.environ.get("CF_R2-KEY_ID")
    secret_access_key = os.environ.get("CF_R2_ACCESS_KEY")
    if not access_key_id or not secret_access_key:
        print("ERROR: CF_R2_KEY_ID / CF_R2_ACCESS_KEY not set")
        sys.exit(1)
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        region_name="auto",
    )


def list_audio_keys(client):
    """List all MP3 files under audio/ prefix."""
    keys = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix="audio/"):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".mp3"):
                keys.append({"key": obj["Key"], "size": obj["Size"]})
    return keys


def get_bitrate(file_path: str) -> int:
    """Get the bitrate of an audio file in kbps."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=bit_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, timeout=30,
        )
        return int(result.stdout.strip()) // 1000
    except Exception:
        return 0


def compress_episode(client, key: str, original_size: int, dry_run: bool) -> dict:
    """Download, re-encode at 96k, upload back."""
    slug = key.removeprefix("audio/").removesuffix(".mp3")

    with tempfile.TemporaryDirectory() as tmpdir:
        original_path = os.path.join(tmpdir, "original.mp3")
        compressed_path = os.path.join(tmpdir, "compressed.mp3")

        # Download
        try:
            client.download_file(R2_BUCKET, key, original_path)
        except Exception as e:
            return {"key": key, "error": f"download failed: {e}"}

        # Check current bitrate — skip if already <= 96kbps
        bitrate = get_bitrate(original_path)
        if 0 < bitrate <= 100:
            return {"key": key, "skipped": True, "reason": f"already {bitrate}kbps"}

        # Re-encode with loudness normalization preserved
        cmd = [
            "ffmpeg", "-y", "-i", original_path,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:a", "libmp3lame", "-b:a", TARGET_BITRATE,
            compressed_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return {"key": key, "error": f"ffmpeg failed: {result.stderr[:200]}"}

        new_size = os.path.getsize(compressed_path)
        saved = original_size - new_size

        if dry_run:
            return {
                "key": key,
                "original_mb": original_size / (1024 * 1024),
                "new_mb": new_size / (1024 * 1024),
                "saved_mb": saved / (1024 * 1024),
                "dry_run": True,
            }

        # Upload back (overwrite original)
        try:
            client.upload_file(
                compressed_path, R2_BUCKET, key,
                ExtraArgs={"ContentType": "audio/mpeg"},
            )
        except Exception as e:
            return {"key": key, "error": f"upload failed: {e}"}

        return {
            "key": key,
            "original_mb": original_size / (1024 * 1024),
            "new_mb": new_size / (1024 * 1024),
            "saved_mb": saved / (1024 * 1024),
        }


def main():
    dry_run = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        limit = int(sys.argv[idx + 1])

    client = get_r2_client()

    print("Listing audio files in R2...")
    audio_files = list_audio_keys(client)
    print(f"  Found {len(audio_files)} MP3 files")

    total_current = sum(f["size"] for f in audio_files)
    print(f"  Total size: {total_current / (1024 * 1024):.0f} MB ({total_current / (1024 * 1024 * 1024):.2f} GB)")

    if limit:
        audio_files = audio_files[:limit]
        print(f"  Processing first {limit} files only")

    if dry_run:
        print("\n[DRY RUN] Will preview compression without uploading\n")
    else:
        print(f"\nRe-encoding {len(audio_files)} files at {TARGET_BITRATE} ({MAX_WORKERS} workers)...\n")

    total_saved = 0
    total_original = 0
    total_new = 0
    processed = 0
    skipped = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(compress_episode, client, f["key"], f["size"], dry_run): f["key"]
            for f in audio_files
        }
        for future in as_completed(futures):
            result = future.result()
            processed += 1

            if "error" in result:
                errors += 1
                print(f"  ERROR {result['key']}: {result['error']}")
            elif result.get("skipped"):
                skipped += 1
                print(f"  SKIP {result['key']}: {result['reason']}")
            else:
                total_original += result["original_mb"]
                total_new += result["new_mb"]
                total_saved += result["saved_mb"]
                pct = (result["saved_mb"] / result["original_mb"] * 100) if result["original_mb"] > 0 else 0
                prefix = "[DRY]" if result.get("dry_run") else "  OK "
                print(
                    f"  {prefix} {result['key']}: "
                    f"{result['original_mb']:.1f}MB -> {result['new_mb']:.1f}MB "
                    f"(saved {result['saved_mb']:.1f}MB / {pct:.0f}%)"
                )

            if processed % 50 == 0:
                print(f"\n  --- Progress: {processed}/{len(audio_files)}, "
                      f"saved so far: {total_saved:.0f}MB ---\n")

    print(f"\n{'='*60}")
    print(f"Total processed: {processed} (skipped: {skipped}, errors: {errors})")
    print(f"Original:   {total_original:.0f} MB")
    print(f"Compressed: {total_new:.0f} MB")
    print(f"Saved:      {total_saved:.0f} MB ({total_saved / 1024:.2f} GB)")
    if total_original > 0:
        print(f"Reduction:  {total_saved / total_original * 100:.0f}%")


if __name__ == "__main__":
    main()
