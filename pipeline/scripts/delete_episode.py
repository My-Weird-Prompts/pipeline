#!/usr/bin/env python3
"""
Delete episode(s) from the database and R2 storage.

Usage:
    # Delete by slug
    python delete_episode.py israel-border-shapes-geometry

    # Delete multiple episodes
    python delete_episode.py israel-border-shapes-geometry mrna-vaccine-scientific-legacy

    # Dry run (show what would be deleted)
    python delete_episode.py --dry-run israel-border-shapes-geometry

    # Show prompts for regeneration after deletion
    python delete_episode.py --show-prompts israel-border-shapes-geometry
"""

import os
import sys
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from pipeline.database.postgres import delete_episode, get_episode
from pipeline.storage.r2 import (
    delete_from_r2,
    R2_EPISODES_BUCKET,
    R2_IMAGES_BUCKET,
)


def delete_episode_fully(slug: str, dry_run: bool = False) -> dict:
    """
    Delete an episode from database and all associated R2 files.

    Args:
        slug: Episode slug to delete
        dry_run: If True, only print what would be deleted

    Returns:
        Dict with deletion results and episode info (including prompt_transcript)
    """
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Deleting episode: {slug}")

    # Check episode exists
    episode = get_episode(slug)
    if not episode:
        print(f"Episode not found: {slug}")
        return {"found": False, "slug": slug}

    result = {
        "found": True,
        "slug": slug,
        "title": episode.get("title"),
        "episode_number": episode.get("episode_number"),
        "duration": episode.get("podcast_duration"),
        "prompt_transcript": episode.get("prompt_transcript"),
        "deleted": False,
    }

    print(f"  Found episode: {episode.get('title', 'No title')}")
    print(f"  Episode number: {episode.get('episode_number', 'N/A')}")
    print(f"  Duration: {episode.get('podcast_duration', 'N/A')}")

    # R2 files to delete
    r2_files = [
        (R2_EPISODES_BUCKET, f"audio/{slug}.mp3"),
        (R2_EPISODES_BUCKET, f"transcripts/{slug}.txt"),
        (R2_EPISODES_BUCKET, f"pdfs/{slug}.pdf"),
        (R2_IMAGES_BUCKET, f"covers/{slug}.png"),
        (R2_IMAGES_BUCKET, f"covers/{slug}.jpg"),
        (R2_IMAGES_BUCKET, f"covers/{slug}.webp"),
        (R2_IMAGES_BUCKET, f"og/{slug}.png"),
        (R2_IMAGES_BUCKET, f"og/{slug}.jpg"),
        (R2_IMAGES_BUCKET, f"instagram/{slug}.png"),
        (R2_IMAGES_BUCKET, f"instagram/{slug}.jpg"),
    ]

    if dry_run:
        print("\n  Would delete from R2:")
        for bucket, key in r2_files:
            print(f"    - {bucket}/{key}")
        print("\n  Would delete from database")
        return result

    # Delete R2 files (ignore errors for missing files)
    print("\n  Deleting R2 files...")
    for bucket, key in r2_files:
        try:
            delete_from_r2(bucket, key)
            print(f"    ✓ {key}")
        except Exception as e:
            # Silently ignore missing files
            pass

    # Delete from database
    print("\n  Deleting from database...")
    if delete_episode(slug):
        print(f"  ✓ Episode '{slug}' deleted from database")
        result["deleted"] = True
    else:
        print(f"  ✗ Failed to delete from database")

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Delete episode(s) completely")
    parser.add_argument("slugs", nargs="+", help="Episode slug(s) to delete")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    parser.add_argument("--show-prompts", action="store_true",
                       help="Show prompt transcripts for regeneration")

    args = parser.parse_args()

    results = []
    for slug in args.slugs:
        print(f"\n{'='*60}")
        result = delete_episode_fully(slug, dry_run=args.dry_run)
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    deleted = [r for r in results if r.get("deleted")]
    not_found = [r["slug"] for r in results if not r.get("found")]

    if args.dry_run:
        found = [r for r in results if r.get("found")]
        print(f"[DRY RUN] Would delete {len(found)} episode(s)")
    else:
        print(f"Deleted {len(deleted)} episode(s)")

    if not_found:
        print(f"Not found: {', '.join(not_found)}")

    # Show prompts for regeneration
    if args.show_prompts or True:  # Always show prompts
        prompts_found = [r for r in results if r.get("found") and r.get("prompt_transcript")]
        if prompts_found:
            print(f"\n{'='*60}")
            print("PROMPT TRANSCRIPTS (for regeneration)")
            print(f"{'='*60}")
            for r in prompts_found:
                print(f"\n--- {r['slug']} ---")
                print(f"Title: {r.get('title', 'Unknown')}")
                print(f"Duration: {r.get('duration', 'Unknown')}")
                print(f"\nPrompt:")
                print(r["prompt_transcript"])
                print()

    sys.exit(0 if all(r.get("deleted") or r.get("found") == False for r in results) else 1)
