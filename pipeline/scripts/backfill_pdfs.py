#!/usr/bin/env python3
"""
Backfill PDF Transcripts

Generates PDF transcripts for episodes that don't have them yet.

Usage:
    # Generate for episodes without PDF URLs
    python pipeline/scripts/backfill_pdfs.py

    # Dry run (show what would be generated)
    python pipeline/scripts/backfill_pdfs.py --dry-run

    # Force regenerate all PDFs
    python pipeline/scripts/backfill_pdfs.py --force

    # Limit to N episodes
    python pipeline/scripts/backfill_pdfs.py --limit 10

Environment Variables:
    POSTGRES_URL - Database connection string
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Add pipeline to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

# Import after path setup
try:
    import psycopg2
except ImportError:
    print("Error: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from generators.generate_pdf import generate_episode_pdf
from storage.r2 import upload_episode_pdf


def get_connection():
    """Get database connection."""
    postgres_url = os.environ.get("POSTGRES_URL")
    if not postgres_url:
        print("Error: POSTGRES_URL environment variable required")
        sys.exit(1)
    return psycopg2.connect(postgres_url)


def get_episodes_needing_pdf(conn, force=False, limit=None):
    """Get episodes that need PDF generation."""
    cur = conn.cursor()

    condition = "1=1" if force else "pdf_url IS NULL"

    query = f"""
        SELECT
            slug,
            title,
            description,
            episode_number,
            pub_date,
            podcast_duration,
            prompt_transcript,
            prompt_summary,
            transcript
        FROM episodes
        WHERE {condition}
          AND transcript IS NOT NULL
        ORDER BY episode_number DESC
    """

    if limit:
        query += f" LIMIT {limit}"

    cur.execute(query)
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    cur.close()

    return [dict(zip(columns, row)) for row in rows]


def update_pdf_url(conn, slug, pdf_url):
    """Update episode with PDF URL."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE episodes SET pdf_url = %s, updated_at = NOW() WHERE slug = %s",
        (pdf_url, slug)
    )
    conn.commit()
    cur.close()


def process_episode(episode):
    """Generate and upload PDF for an episode."""
    pub_date = episode.get('pub_date')
    if isinstance(pub_date, str):
        pub_date = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
    elif pub_date is None:
        pub_date = datetime.now()

    pdf_bytes = generate_episode_pdf(
        title=episode['title'],
        episode_number=episode.get('episode_number'),
        pub_date=pub_date,
        duration=episode.get('podcast_duration'),
        description=episode.get('description'),
        prompt_transcript=episode.get('prompt_transcript'),
        prompt_summary=episode.get('prompt_summary'),
        transcript=episode['transcript'],
        episode_url=f"https://myweirdprompts.com/episode/{episode['slug']}/",
    )

    if not pdf_bytes:
        raise Exception("PDF generation returned empty")

    pdf_url = upload_episode_pdf(episode['slug'], pdf_bytes)

    if not pdf_url:
        raise Exception("PDF upload failed")

    return pdf_url


def main():
    parser = argparse.ArgumentParser(description='Backfill PDF transcripts')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be generated')
    parser.add_argument('--force', action='store_true', help='Regenerate all PDFs')
    parser.add_argument('--limit', type=int, help='Limit to N episodes')
    args = parser.parse_args()

    print("Backfill PDF Transcripts")
    print("========================")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"Force regenerate: {'YES' if args.force else 'NO'}")
    if args.limit:
        print(f"Limit: {args.limit} episodes")
    print("")

    conn = get_connection()
    episodes = get_episodes_needing_pdf(conn, force=args.force, limit=args.limit)

    print(f"Found {len(episodes)} episodes needing PDF generation")

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
            pdf_url = process_episode(ep)
            update_pdf_url(conn, ep['slug'], pdf_url)
            print(f"  ✓ PDF uploaded: {pdf_url}")
            success += 1
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            failed += 1

    conn.close()

    print("\n========================")
    print(f"Complete: {success} succeeded, {failed} failed")


if __name__ == "__main__":
    main()
