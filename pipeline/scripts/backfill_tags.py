#!/usr/bin/env python3
"""
Backfill Tags - Replace Generic Tags

Re-generates tags for episodes that have generic/blacklisted tags
(ai-generated, podcast, technology, etc.) using the improved tagging system.

The tagging system now has:
1. A blacklist of generic tags that are rejected
2. A curated taxonomy with synonyms
3. Semantic duplicate detection

Usage:
    # Dry run (show what would be updated)
    python backfill_tags.py --dry-run

    # Update all episodes with generic tags
    python backfill_tags.py

    # Update specific episodes by slug
    python backfill_tags.py --slugs "episode-1,episode-2"

    # Limit to N episodes
    python backfill_tags.py --limit 10
"""

import argparse
import os
import sys
from pathlib import Path

# Add parent directories to path for imports
SCRIPT_DIR = Path(__file__).parent
PIPELINE_DIR = SCRIPT_DIR.parent
REPO_ROOT = PIPELINE_DIR.parent

# Add repo root so 'pipeline' package is importable
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv()

from pipeline.database.postgres import (
    get_episodes_needing_metadata,
    update_episode_metadata,
    get_all_episodes,
    get_connection,
)
from pipeline.core.tagging import (
    tag_episode,
    BLACKLISTED_TAGS,
    load_tags_registry,
    save_tags_registry,
)


def has_generic_tags(tags: list) -> bool:
    """Check if episode has any blacklisted generic tags."""
    if not tags:
        return True  # No tags = needs regeneration

    for tag in tags:
        if tag.lower() in BLACKLISTED_TAGS:
            return True
    return False


def get_episodes_with_generic_tags(
    slugs: list = None,
    limit: int = None,
    force_all: bool = False,
) -> list:
    """
    Get episodes that have generic/blacklisted tags.

    Args:
        slugs: Optional list of specific slugs to check
        limit: Maximum number of episodes to return
        force_all: If True, regenerate tags for ALL episodes (not just those with generic tags)

    Returns:
        List of episode dicts
    """
    if force_all:
        # Get all episodes
        episodes = get_all_episodes()
    else:
        # Use the helper that checks for generic tags
        episodes = get_episodes_needing_metadata(
            check_tags=True,
            check_category=False,
            check_embedding=False,
            limit=limit,
        )

    # Filter by slugs if specified
    if slugs:
        episodes = [e for e in episodes if e.get("slug") in slugs]

    # Apply limit
    if limit and not force_all:
        episodes = episodes[:limit]
    elif limit and force_all:
        episodes = episodes[:limit]

    return episodes


def regenerate_tags(episode: dict, registry: dict) -> tuple[list, bool]:
    """
    Regenerate tags for an episode.

    Args:
        episode: Episode dict with title, description
        registry: Tags registry dict

    Returns:
        Tuple of (new_tags, success)
    """
    title = episode.get("title", "")
    description = episode.get("description", "") or episode.get("show_notes", "")

    if not title:
        return [], False

    try:
        # Use existing tagging system
        from pipeline.core.tagging import generate_episode_tags

        new_tags = generate_episode_tags(title, description, registry)
        return new_tags, len(new_tags) > 0
    except Exception as e:
        print(f"  Error generating tags: {e}")
        return [], False


def main():
    parser = argparse.ArgumentParser(
        description="Regenerate tags for episodes with generic/blacklisted tags",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )

    parser.add_argument(
        "--slugs",
        type=str,
        help="Comma-separated list of episode slugs to update",
    )

    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of episodes to process",
    )

    parser.add_argument(
        "--force-all",
        action="store_true",
        help="Regenerate tags for ALL episodes (not just those with generic tags)",
    )

    args = parser.parse_args()

    # Check database connection
    postgres_url = os.environ.get("POSTGRES_URL") or os.environ.get("NEON_DATABASE_URL")
    if not postgres_url:
        print("Error: POSTGRES_URL environment variable not set")
        sys.exit(1)

    print("=" * 60)
    print("Tag Backfill - Replace Generic Tags")
    print("=" * 60)
    print(f"Dry run: {args.dry_run}")
    print(f"Force all: {args.force_all}")
    print(f"Blacklisted tags: {', '.join(sorted(BLACKLISTED_TAGS))}")
    print()

    # Parse slugs if provided
    slugs = None
    if args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",")]
        print(f"Filtering to slugs: {slugs}")

    # Load tags registry
    registry = load_tags_registry()
    print(f"Tags registry: {len(registry.get('tags', []))} tags loaded")
    print()

    # Get episodes to update
    episodes = get_episodes_with_generic_tags(
        slugs=slugs,
        limit=args.limit,
        force_all=args.force_all,
    )

    print(f"Found {len(episodes)} episodes to process")
    print()

    if not episodes:
        print("No episodes need tag updates.")
        return

    if args.dry_run:
        print("DRY RUN - No changes will be made")
        print("-" * 40)
        for ep in episodes:
            current_tags = ep.get("tags") or []
            generic_found = [t for t in current_tags if t.lower() in BLACKLISTED_TAGS]
            print(f"  {ep['slug']}")
            print(f"    Title: {ep['title'][:50]}...")
            print(f"    Current tags: {current_tags}")
            if generic_found:
                print(f"    Generic tags found: {generic_found}")
            print()
        return

    # Process episodes
    success_count = 0
    fail_count = 0
    skip_count = 0

    for i, episode in enumerate(episodes, 1):
        slug = episode.get("slug")
        current_tags = episode.get("tags") or []

        print(f"[{i}/{len(episodes)}] {slug}")
        print(f"  Title: {episode['title'][:60]}...")
        print(f"  Current tags: {current_tags}")

        # Check if it actually needs updating
        if not args.force_all and not has_generic_tags(current_tags):
            print(f"  → Skipping (no generic tags)")
            skip_count += 1
            continue

        # Generate new tags
        new_tags, success = regenerate_tags(episode, registry)

        if success and new_tags:
            print(f"  New tags: {new_tags}")

            # Update database
            if update_episode_metadata(slug, tags=new_tags):
                print(f"  ✓ Database updated")
                success_count += 1
            else:
                print(f"  ✗ Database update failed")
                fail_count += 1
        else:
            print(f"  ✗ Failed to generate tags")
            fail_count += 1

        print()

    # Save updated registry
    save_tags_registry(registry)
    print("Tags registry saved.")
    print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total processed: {len(episodes)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Skipped: {skip_count}")


if __name__ == "__main__":
    main()
