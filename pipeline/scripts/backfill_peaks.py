#!/usr/bin/env python3
"""
Backfill Waveform Peaks

Downloads episode audio from R2, extracts waveform peaks, uploads the
peaks JSON, and updates the database.

Usage:
    # Generate for episodes without peaks URLs
    python pipeline/scripts/backfill_peaks.py

    # Dry run (show what would be generated)
    python pipeline/scripts/backfill_peaks.py --dry-run

    # Force regenerate all peaks
    python pipeline/scripts/backfill_peaks.py --force

    # Limit to N episodes
    python pipeline/scripts/backfill_peaks.py --limit 10

Environment Variables:
    POSTGRES_URL - Database connection string
    CF_R2_KEY_ID / CF_R2_ACCESS_KEY - R2 credentials
    R2_EPISODES_PUBLIC_URL - Public URL for episodes bucket
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

# Add pipeline to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

try:
    import psycopg2
except ImportError:
    print("Error: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Error: requests not installed. Run: pip install requests")
    sys.exit(1)

from generators.waveform_peaks import extract_peaks
from storage.r2 import upload_episode_peaks


def get_connection():
    """Get database connection."""
    postgres_url = os.environ.get("POSTGRES_URL")
    if not postgres_url:
        print("Error: POSTGRES_URL environment variable required")
        sys.exit(1)
    return psycopg2.connect(postgres_url)


def get_episodes_needing_peaks(conn, force=False, limit=None):
    """Get episodes that need peaks generation."""
    cur = conn.cursor()

    condition = "1=1" if force else "peaks_url IS NULL"

    query = f"""
        SELECT slug, title, episode_number, podcast_audio_url
        FROM episodes
        WHERE {condition}
          AND podcast_audio_url IS NOT NULL
        ORDER BY episode_number DESC
    """

    if limit:
        query += f" LIMIT {limit}"

    cur.execute(query)
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    cur.close()

    return [dict(zip(columns, row)) for row in rows]


def update_peaks_url(conn, slug, peaks_url):
    """Update episode with peaks URL."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE episodes SET peaks_url = %s, updated_at = NOW() WHERE slug = %s",
        (peaks_url, slug)
    )
    conn.commit()
    cur.close()


def process_episode(episode):
    """Download audio, extract peaks, upload JSON."""
    audio_url = episode['podcast_audio_url']

    # Download audio to temp file
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        print(f"  Downloading audio...")
        resp = requests.get(audio_url, timeout=120)
        resp.raise_for_status()

        if len(resp.content) < 1024:
            raise Exception(f"Audio too small: {len(resp.content)} bytes")

        tmp_path.write_bytes(resp.content)
        print(f"  Downloaded {len(resp.content) / 1024 / 1024:.1f} MB")

        # Extract peaks
        print(f"  Extracting peaks...")
        peaks_json = extract_peaks(tmp_path)
        print(f"  Peaks: {len(peaks_json) / 1024:.1f} KB")

        # Upload to R2
        peaks_url = upload_episode_peaks(episode['slug'], peaks_json)
        if not peaks_url:
            raise Exception("Peaks upload failed")

        return peaks_url

    finally:
        tmp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Backfill waveform peaks')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be generated')
    parser.add_argument('--force', action='store_true', help='Regenerate all peaks')
    parser.add_argument('--limit', type=int, help='Limit to N episodes')
    args = parser.parse_args()

    print("Backfill Waveform Peaks")
    print("=======================")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"Force regenerate: {'YES' if args.force else 'NO'}")
    if args.limit:
        print(f"Limit: {args.limit} episodes")
    print("")

    conn = get_connection()
    episodes = get_episodes_needing_peaks(conn, force=args.force, limit=args.limit)

    print(f"Found {len(episodes)} episodes needing peaks generation")

    if not episodes:
        print("Nothing to do.")
        return

    if args.dry_run:
        print("\nEpisodes that would be processed:")
        for ep in episodes:
            print(f"  - #{ep.get('episode_number')}: {ep['title']} ({ep['slug']})")
        return

    success = 0
    failed = 0

    for ep in episodes:
        print(f"\nProcessing #{ep.get('episode_number')}: {ep['title']}")

        try:
            peaks_url = process_episode(ep)
            update_peaks_url(conn, ep['slug'], peaks_url)
            print(f"  Done: {peaks_url}")
            success += 1
        except Exception as e:
            print(f"  Failed: {e}")
            failed += 1

    conn.close()

    print("\n=======================")
    print(f"Complete: {success} succeeded, {failed} failed")


if __name__ == "__main__":
    main()
