#!/usr/bin/env python3
"""
Backfill Wasabi S3 bucket with episode audio files from R2.

This script was created on 2026-02-15 to do a one-time backfill of ~600 episodes
that were missing from the Wasabi archival backup. As of that date, the Modal
pipeline (recording_app.py) now automatically backs up each new episode to Wasabi
after publication, so this script should no longer be needed for routine use.

It can still be useful if:
  - Episodes were missed due to Wasabi credential issues or transient failures
  - You need to re-sync after a bulk import or recovery operation

Usage:
    python pipeline/scripts/backfill_wasabi.py              # sync missing episodes
    python pipeline/scripts/backfill_wasabi.py --dry-run    # preview what would sync
    python pipeline/scripts/backfill_wasabi.py --force      # re-sync ALL episodes (overwrite existing)
    python pipeline/scripts/backfill_wasabi.py --flatten-only  # flatten nested keys only

Target structure: episodes/<slug>.mp3 (flat, no subdirectories)
"""

import os
import sys
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import psycopg2
import requests

# Load .env.production
ENV_FILE = Path(__file__).parent.parent.parent / ".env.production"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

# Configuration
WASABI_ENDPOINT = os.environ.get("WASABI_ENDPOINT", "https://s3.eu-central-2.wasabisys.com")
WASABI_REGION = os.environ.get("WASABI_REGION", "eu-central-2")
WASABI_BUCKET = os.environ.get("WASABI_BUCKET", "myweirdprompts")
WASABI_ACCESS_KEY = os.environ.get("WASABI_ACCESS_KEY")
WASABI_SECRET_KEY = os.environ.get("WASABI_SECRET_KEY")
POSTGRES_URL = os.environ.get("POSTGRES_URL")

MAX_WORKERS = 4
DOWNLOAD_TIMEOUT = 120


def get_wasabi_client():
    return boto3.client(
        "s3",
        endpoint_url=WASABI_ENDPOINT,
        aws_access_key_id=WASABI_ACCESS_KEY,
        aws_secret_access_key=WASABI_SECRET_KEY,
        region_name=WASABI_REGION,
    )


def list_all_wasabi_keys(client):
    """List all keys under episodes/ prefix."""
    keys = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=WASABI_BUCKET, Prefix="episodes/"):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def get_episodes_from_db():
    """Get all episodes with audio URLs from database."""
    conn = psycopg2.connect(POSTGRES_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT slug, podcast_audio_url, episode_number
                FROM episodes
                WHERE podcast_audio_url IS NOT NULL
                ORDER BY episode_number
            """)
            return cur.fetchall()
    finally:
        conn.close()


def flatten_existing(client, existing_keys, dry_run=False):
    """
    Move nested files (episodes/slug/file.mp3) to flat (episodes/file.mp3).
    Delete the nested originals after copying.
    Returns set of flat keys after flattening.
    """
    flat_keys = set()
    nested_to_delete = []

    for key in existing_keys:
        parts = key.removeprefix("episodes/").split("/")
        if len(parts) == 1:
            # Already flat: episodes/file.mp3
            flat_keys.add(key)
        elif len(parts) == 2:
            # Nested: episodes/slug/file.mp3 -> episodes/file.mp3
            filename = parts[1]
            flat_key = f"episodes/{filename}"
            if flat_key in flat_keys:
                # Flat version already exists, just delete the nested one
                nested_to_delete.append(key)
            else:
                # Need to copy then delete
                flat_keys.add(flat_key)
                if not dry_run:
                    try:
                        client.copy_object(
                            Bucket=WASABI_BUCKET,
                            CopySource={"Bucket": WASABI_BUCKET, "Key": key},
                            Key=flat_key,
                        )
                        nested_to_delete.append(key)
                        print(f"  FLATTEN {key} -> {flat_key}")
                    except Exception as e:
                        print(f"  FAIL flatten {key}: {e}")
                else:
                    nested_to_delete.append(key)
                    print(f"  [DRY] FLATTEN {key} -> {flat_key}")

    # Delete nested originals
    if nested_to_delete:
        if not dry_run:
            for key in nested_to_delete:
                try:
                    client.delete_object(Bucket=WASABI_BUCKET, Key=key)
                except Exception as e:
                    print(f"  FAIL delete {key}: {e}")
            print(f"  Deleted {len(nested_to_delete)} nested files")
        else:
            print(f"  [DRY] Would delete {len(nested_to_delete)} nested files")

    return flat_keys


def sync_episode(client, slug, audio_url, episode_number):
    """Download from R2 public URL and upload to Wasabi as flat file."""
    filename = audio_url.rstrip("/").split("/")[-1]
    wasabi_key = f"episodes/{filename}"

    try:
        resp = requests.get(audio_url, timeout=DOWNLOAD_TIMEOUT, stream=True)
        resp.raise_for_status()

        content_length = int(resp.headers.get("content-length", 0))
        if content_length < 1024:
            print(f"  SKIP #{episode_number} {slug}: too small ({content_length}B)")
            return False

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                tmp.write(chunk)
            tmp.flush()
            file_size = os.path.getsize(tmp.name)

            client.upload_file(
                tmp.name,
                WASABI_BUCKET,
                wasabi_key,
                ExtraArgs={"ContentType": "audio/mpeg"},
            )

        size_mb = file_size / (1024 * 1024)
        print(f"  OK #{episode_number} {slug} ({size_mb:.1f}MB)")
        return True

    except Exception as e:
        print(f"  FAIL #{episode_number} {slug}: {e}")
        return False


def main():
    dry_run = "--dry-run" in sys.argv
    flatten_only = "--flatten-only" in sys.argv
    force = "--force" in sys.argv

    if not WASABI_ACCESS_KEY or not WASABI_SECRET_KEY:
        print("ERROR: WASABI_ACCESS_KEY/WASABI_SECRET_KEY not set")
        sys.exit(1)
    if not POSTGRES_URL:
        print("ERROR: POSTGRES_URL not set")
        sys.exit(1)

    print("Connecting to Wasabi...")
    client = get_wasabi_client()

    print("Listing existing Wasabi files...")
    existing_keys = list_all_wasabi_keys(client)
    print(f"  Found {len(existing_keys)} files total")

    # Count nested vs flat
    nested = [k for k in existing_keys if k.removeprefix("episodes/").count("/") > 0]
    flat = [k for k in existing_keys if k.removeprefix("episodes/").count("/") == 0]
    print(f"  Flat: {len(flat)}, Nested: {len(nested)}")

    if nested:
        print(f"\nFlattening {len(nested)} nested files...")
        flat_keys = flatten_existing(client, existing_keys, dry_run=dry_run)
        print(f"  After flatten: {len(flat_keys)} flat files")
    else:
        flat_keys = set(existing_keys)
        print("  All files already flat")

    if flatten_only:
        print("\nDone (flatten only).")
        return

    # Build set of filenames already in Wasabi
    existing_filenames = set()
    for key in flat_keys:
        filename = key.removeprefix("episodes/")
        existing_filenames.add(filename)

    print("\nQuerying database for episodes...")
    episodes = get_episodes_from_db()
    print(f"  Found {len(episodes)} episodes in database")

    # Find episodes to sync
    if force:
        # Re-sync everything (e.g. after recompression)
        missing = [(slug, audio_url, ep_num) for slug, audio_url, ep_num in episodes]
        print(f"\n[FORCE] Re-syncing all {len(missing)} episodes (overwriting existing)")
    else:
        missing = []
        for slug, audio_url, ep_num in episodes:
            filename = audio_url.rstrip("/").split("/")[-1]
            if filename not in existing_filenames:
                missing.append((slug, audio_url, ep_num))
        print(f"\n{len(missing)} episodes missing from Wasabi")

    if not missing:
        print("Nothing to do!")
        return

    if dry_run:
        print("\n[DRY RUN] Would sync:")
        for slug, audio_url, ep_num in missing[:20]:
            print(f"  #{ep_num}: {slug}")
        if len(missing) > 20:
            print(f"  ... and {len(missing) - 20} more")
        return

    print(f"\nSyncing {len(missing)} episodes ({MAX_WORKERS} parallel workers)...\n")

    success = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(sync_episode, client, slug, audio_url, ep_num): slug
            for slug, audio_url, ep_num in missing
        }
        for future in as_completed(futures):
            if future.result():
                success += 1
            else:
                failed += 1

    print(f"\nDone! Synced: {success}, Failed: {failed}, Already existed: {len(existing_filenames)}")


if __name__ == "__main__":
    main()
