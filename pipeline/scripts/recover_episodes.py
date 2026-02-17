#!/usr/bin/env python3
"""
Recovery script to publish episodes that failed at the publication stage.

Usage:
    python recover_episodes.py                    # Publish all episodes in recovery folder
    python recover_episodes.py --recovery-id XXX  # Publish specific recovery ID
    python recover_episodes.py --dry-run          # Preview what would be published
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime

import boto3
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Add parent path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "generators"))

# R2 configuration
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
CF_R2_KEY_ID = os.environ.get("CF_R2_KEY_ID")
CF_R2_ACCESS_KEY = os.environ.get("CF_R2_ACCESS_KEY")
R2_EPISODES_BUCKET = "mwp-episodes"
R2_EPISODES_PUBLIC_URL = os.environ.get("R2_EPISODES_PUBLIC_URL", "https://episodes.myweirdprompts.com")


def get_r2_client():
    """Get R2 client for bucket operations."""
    if not all([CLOUDFLARE_ACCOUNT_ID, CF_R2_KEY_ID, CF_R2_ACCESS_KEY]):
        print("ERROR: Missing R2 credentials. Set CLOUDFLARE_ACCOUNT_ID, CF_R2_KEY_ID, CF_R2_ACCESS_KEY")
        return None

    return boto3.client(
        "s3",
        endpoint_url=f"https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=CF_R2_KEY_ID,
        aws_secret_access_key=CF_R2_ACCESS_KEY,
        region_name="auto",
    )


def list_recovery_episodes():
    """List all episodes in the recovery folder."""
    client = get_r2_client()
    if not client:
        return []

    response = client.list_objects_v2(
        Bucket=R2_EPISODES_BUCKET,
        Prefix="recovery/",
        Delimiter="/",
    )

    # Get unique recovery folders
    folders = []
    if "CommonPrefixes" in response:
        for prefix in response["CommonPrefixes"]:
            folder = prefix["Prefix"].rstrip("/")
            folders.append(folder)

    return folders


def get_recovery_manifest(recovery_path: str) -> dict:
    """Get the manifest for a recovery episode."""
    client = get_r2_client()
    if not client:
        return None

    try:
        response = client.get_object(
            Bucket=R2_EPISODES_BUCKET,
            Key=f"{recovery_path}/manifest.json",
        )
        return json.loads(response["Body"].read())
    except Exception as e:
        print(f"  Error reading manifest: {e}")
        return None


def download_recovery_file(recovery_path: str, filename: str, dest_path: Path):
    """Download a file from recovery storage."""
    client = get_r2_client()
    if not client:
        return False

    try:
        response = client.get_object(
            Bucket=R2_EPISODES_BUCKET,
            Key=f"{recovery_path}/{filename}",
        )
        with open(dest_path, "wb") as f:
            f.write(response["Body"].read())
        return True
    except Exception as e:
        print(f"  Error downloading {filename}: {e}")
        return False


def upload_to_r2(local_path: Path, key: str, content_type: str = None) -> str:
    """Upload a file to R2 and return the public URL."""
    client = get_r2_client()
    if not client:
        return None

    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type

    try:
        client.upload_file(
            str(local_path),
            R2_EPISODES_BUCKET,
            key,
            ExtraArgs=extra_args,
        )
        return f"{R2_EPISODES_PUBLIC_URL}/{key}"
    except Exception as e:
        print(f"  Error uploading {key}: {e}")
        return None


def recover_episode(recovery_path: str, dry_run: bool = False):
    """Recover and publish a single episode."""
    print(f"\n{'='*60}")
    print(f"Recovering: {recovery_path}")
    print("=" * 60)

    # Get manifest
    manifest = get_recovery_manifest(recovery_path)
    if not manifest:
        print("  ERROR: Could not load manifest")
        return False

    metadata = manifest.get("metadata", {})
    files = manifest.get("files", {})

    title = metadata.get("title", "Unknown")
    print(f"  Title: {title}")
    print(f"  Error: {manifest.get('error', 'Unknown')}")
    print(f"  Timestamp: {manifest.get('timestamp', 'Unknown')}")

    if dry_run:
        print("  [DRY RUN] Would publish this episode")
        return True

    # Create temp directory for downloads
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Generate slug from title
        slug = metadata.get("episode_slug") or metadata.get("slug")
        if not slug:
            import re
            slug = title.lower().replace(" ", "-")
            slug = re.sub(r"[^a-z0-9-]", "", slug)
            slug = re.sub(r"-+", "-", slug).strip("-")

        print(f"  Slug: {slug}")

        # Download and upload audio
        audio_filename = files.get("audio")
        if audio_filename:
            audio_path = tmpdir / audio_filename
            if download_recovery_file(recovery_path, audio_filename, audio_path):
                print(f"  Downloaded audio: {audio_filename}")
                audio_url = upload_to_r2(
                    audio_path,
                    f"audio/{slug}.mp3",
                    content_type="audio/mpeg",
                )
                if audio_url:
                    print(f"  Uploaded audio: {audio_url}")
                    metadata["audio_url"] = audio_url
                else:
                    print("  ERROR: Failed to upload audio")
                    return False
            else:
                print("  ERROR: Failed to download audio")
                return False
        else:
            print("  ERROR: No audio file in manifest")
            return False

        # Download and upload cover
        cover_filename = files.get("cover")
        if cover_filename:
            cover_path = tmpdir / cover_filename
            if download_recovery_file(recovery_path, cover_filename, cover_path):
                print(f"  Downloaded cover: {cover_filename}")
                cover_url = upload_to_r2(
                    cover_path,
                    f"covers/{slug}.png",
                    content_type="image/png",
                )
                if cover_url:
                    print(f"  Uploaded cover: {cover_url}")
                    metadata["cover_url"] = cover_url
            else:
                print("  Warning: Failed to download cover")

        # Download script
        script = None
        if files.get("script"):
            script_path = tmpdir / "script.txt"
            if download_recovery_file(recovery_path, "script.txt", script_path):
                script = script_path.read_text()
                print(f"  Downloaded script: {len(script)} chars")

        # Get audio duration
        try:
            import subprocess
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(tmpdir / audio_filename)],
                capture_output=True, text=True
            )
            duration_secs = float(result.stdout.strip())
            mins = int(duration_secs // 60)
            secs = int(duration_secs % 60)
            duration = f"{mins:02d}:{secs:02d}"
        except Exception:
            duration = "00:00"
        print(f"  Duration: {duration}")

        # Insert to database
        try:
            import psycopg2
            postgres_url = os.environ.get("POSTGRES_URL")
            if postgres_url:
                print("  Inserting to database...")
                conn = psycopg2.connect(postgres_url)
                cur = conn.cursor()

                # Insert episode
                cur.execute("""
                    INSERT INTO episodes (
                        slug, title, description, excerpt, pub_date,
                        hero_image, podcast_audio_url, podcast_duration,
                        tags, category, subcategory, transcript,
                        prompt, prompt_summary, prompt_transcript, prompt_redacted,
                        context, response, show_notes, pipeline_version,
                        tts_engine, tts_model, og_image, instagram_image, llm_model
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (slug) DO UPDATE SET
                        title = EXCLUDED.title,
                        podcast_audio_url = EXCLUDED.podcast_audio_url,
                        hero_image = EXCLUDED.hero_image
                """, (
                    slug, title, metadata.get("description", ""), metadata.get("excerpt"), datetime.now(),
                    metadata.get("cover_url"), metadata.get("audio_url"), duration,
                    metadata.get("tags", []), metadata.get("category"), metadata.get("subcategory"), script,
                    metadata.get("prompt"), metadata.get("prompt_summary"), metadata.get("prompt_transcript"), metadata.get("prompt_transcript"),
                    metadata.get("context"), metadata.get("response"), metadata.get("show_notes"), "V4-recovery",
                    "chatterbox-fal", metadata.get("tts_model"), metadata.get("og_image_url"), metadata.get("instagram_image_url"), metadata.get("llm_model")
                ))
                conn.commit()
                conn.close()
                print("  Database insert complete")
            else:
                print("  Warning: No POSTGRES_URL, skipping database insert")

        except Exception as db_error:
            print(f"  Warning: Database insert failed: {db_error}")

        # Trigger Vercel deploy hook
        try:
            import requests
            vercel_hook = os.environ.get("VERCEL_DEPLOY_HOOK")
            if vercel_hook:
                print("  Triggering Vercel deploy...")
                response = requests.post(vercel_hook)
                if response.status_code == 200:
                    print("  Vercel deploy triggered successfully")
                else:
                    print(f"  Warning: Vercel deploy returned {response.status_code}")
            else:
                print("  Warning: No VERCEL_DEPLOY_HOOK, skipping deploy")
        except Exception as e:
            print(f"  Warning: Vercel deploy failed: {e}")

    # Optionally delete recovery files after successful publication
    # (keeping them for now for safety)
    print(f"  SUCCESS: Episode recovered and published!")
    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Recover episodes from recovery storage")
    parser.add_argument("--recovery-id", help="Specific recovery ID to publish")
    parser.add_argument("--dry-run", action="store_true", help="Preview without publishing")
    parser.add_argument("--list", action="store_true", help="List all recovery episodes")
    args = parser.parse_args()

    if args.list:
        print("Recovery episodes:")
        folders = list_recovery_episodes()
        for folder in folders:
            manifest = get_recovery_manifest(folder)
            if manifest:
                title = manifest.get("metadata", {}).get("title", "Unknown")
                error = manifest.get("error", "Unknown")
                print(f"  {folder}")
                print(f"    Title: {title}")
                print(f"    Error: {error}")
        return

    if args.recovery_id:
        # Recover specific episode
        recovery_path = f"recovery/{args.recovery_id}"
        recover_episode(recovery_path, dry_run=args.dry_run)
    else:
        # Recover all episodes
        folders = list_recovery_episodes()
        print(f"Found {len(folders)} episodes to recover")

        for folder in folders:
            success = recover_episode(folder, dry_run=args.dry_run)
            if not success and not args.dry_run:
                print(f"  WARNING: Failed to recover {folder}")


if __name__ == "__main__":
    main()
