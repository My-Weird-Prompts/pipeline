#!/usr/bin/env python3
"""
Backend Maintenance Script for MWP Podcast

Unified script for periodic backend maintenance tasks:
- Tagging: Generate and apply tags to episodes
- Categorization: Assign categories/subcategories to episodes
- Embeddings: Generate semantic embeddings for similarity search
- Index Refresh: Update the episode index cache in R2

Usage:
    # Run all maintenance tasks (dry-run)
    python backend_maintenance.py --dry-run

    # Run all maintenance tasks
    python backend_maintenance.py

    # Run specific tasks
    python backend_maintenance.py --tags --embeddings

    # Force re-process all episodes (not just missing)
    python backend_maintenance.py --force

    # Limit to N episodes
    python backend_maintenance.py --limit 10

    # Resume from offset
    python backend_maintenance.py --offset 50

    # Only refresh the episode index
    python backend_maintenance.py --index-only
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add pipeline to path
SCRIPT_DIR = Path(__file__).parent
PIPELINE_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PIPELINE_ROOT.parent))

from pipeline.core import (
    tag_episode,
    generate_episode_embedding,
    categorize_episode,
)
from pipeline.core.tagging import BLACKLISTED_TAGS
from pipeline.database.postgres import (
    get_episodes_needing_metadata,
    update_episode_metadata,
    get_episode_count,
    get_all_episodes,
)


# Progress file for resumability
PROGRESS_FILE = PIPELINE_ROOT / "output" / "maintenance_progress.json"

# Rate limiting (seconds between API calls)
RATE_LIMIT_DELAY = 0.5


def load_progress() -> dict:
    """Load progress state from file."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"processed": [], "errors": [], "last_run": None}


def save_progress(state: dict):
    """Save progress state to file."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_run"] = datetime.now().isoformat()
    with open(PROGRESS_FILE, "w") as f:
        json.dump(state, f, indent=2)


def process_episode(
    episode: dict,
    do_tags: bool = True,
    do_category: bool = True,
    do_embedding: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Process a single episode for metadata updates.

    Args:
        episode: Episode dict from database
        do_tags: Generate tags
        do_category: Assign category
        do_embedding: Generate embedding
        force: Force re-process even if data exists
        dry_run: Don't actually update database

    Returns:
        Result dict with success status and updates
    """
    slug = episode["slug"]
    title = episode.get("title", "")
    description = episode.get("description", "")

    result = {
        "slug": slug,
        "title": title,
        "success": True,
        "updates": {},
        "errors": [],
    }

    print(f"\nProcessing: {slug}")
    print(f"  Title: {title[:60]}..." if len(title) > 60 else f"  Title: {title}")

    # Check what needs updating
    existing_tags = episode.get("tags") or []
    existing_category = episode.get("category")
    existing_embedding = episode.get("embedding")

    # INCREMENTAL TAG LOGIC:
    # 1. Filter out any generic/blacklisted tags from existing tags
    # 2. Only regenerate if we have fewer than 3 good tags
    # 3. Merge new tags with existing good ones (don't overwrite)
    good_existing_tags = [t for t in existing_tags if t not in BLACKLISTED_TAGS]
    has_bad_tags = len(good_existing_tags) < len(existing_tags)
    needs_more_tags = len(good_existing_tags) < 3

    needs_tags = do_tags and (
        force or not existing_tags or has_bad_tags or needs_more_tags
    )
    needs_category = do_category and (force or not existing_category)
    needs_embedding = do_embedding and (force or not existing_embedding)

    # Generate tags (incremental)
    if needs_tags:
        try:
            new_tags = tag_episode(title, description, save_registry=not dry_run)

            if force:
                # Force mode: completely replace tags
                final_tags = new_tags
            else:
                # Incremental mode: merge with existing good tags
                # Priority: existing good tags first, then fill with new tags up to 3
                final_tags = good_existing_tags.copy()
                for tag in new_tags:
                    if tag not in final_tags and len(final_tags) < 3:
                        final_tags.append(tag)

            result["updates"]["tags"] = final_tags[:3]
            if has_bad_tags:
                removed = [t for t in existing_tags if t in BLACKLISTED_TAGS]
                print(f"  Tags: {final_tags[:3]} (removed generic: {removed})")
            else:
                print(f"  Tags: {final_tags[:3]}")
        except Exception as e:
            result["errors"].append(f"Tags: {e}")
            print(f"  Tags ERROR: {e}")

    # Generate category
    if needs_category:
        try:
            cat_result = categorize_episode(title, description)
            if cat_result.get("category"):
                result["updates"]["category"] = cat_result["category"]
                result["updates"]["subcategory"] = cat_result.get("subcategory")
                print(f"  Category: {cat_result['category']} > {cat_result.get('subcategory')}")
        except Exception as e:
            result["errors"].append(f"Category: {e}")
            print(f"  Category ERROR: {e}")

    # Generate embedding
    if needs_embedding:
        try:
            embedding = generate_episode_embedding(
                title,
                description,
                transcript=episode.get("transcript", "")[:4000] if episode.get("transcript") else None,
            )
            if embedding:
                result["updates"]["embedding"] = embedding
                print(f"  Embedding: {len(embedding)} dimensions")
        except Exception as e:
            result["errors"].append(f"Embedding: {e}")
            print(f"  Embedding ERROR: {e}")

    # Update database
    if not dry_run and result["updates"]:
        try:
            success = update_episode_metadata(
                slug=slug,
                tags=result["updates"].get("tags"),
                category=result["updates"].get("category"),
                subcategory=result["updates"].get("subcategory"),
                embedding=result["updates"].get("embedding"),
            )
            if not success:
                result["errors"].append("Database update failed")
                result["success"] = False
        except Exception as e:
            result["errors"].append(f"Database: {e}")
            result["success"] = False
            print(f"  Database ERROR: {e}")

    if result["errors"]:
        result["success"] = False

    return result


def refresh_episode_index():
    """Refresh the episode index cache in R2."""
    print("\n" + "=" * 60)
    print("Refreshing Episode Index")
    print("=" * 60)

    try:
        from pipeline.generators.episode_memory import build_episode_index, upload_index_to_r2

        index = build_episode_index()
        if index:
            print(f"  Built index with {index.total_episodes} episodes")
            upload_index_to_r2(index)
            print("  Uploaded to R2")
            return True
        else:
            print("  Failed to build index")
            return False
    except Exception as e:
        print(f"  Error refreshing index: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="MWP Backend Maintenance - Tagging, Categorization, Embeddings"
    )

    # Task selection
    parser.add_argument(
        "--tags", action="store_true",
        help="Generate tags for episodes"
    )
    parser.add_argument(
        "--categories", action="store_true",
        help="Generate categories for episodes"
    )
    parser.add_argument(
        "--embeddings", action="store_true",
        help="Generate embeddings for episodes"
    )
    parser.add_argument(
        "--index-only", action="store_true",
        help="Only refresh the episode index (skip other tasks)"
    )

    # Processing options
    parser.add_argument(
        "--force", action="store_true",
        help="Force re-process all episodes (not just missing)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit to N episodes"
    )
    parser.add_argument(
        "--offset", type=int, default=0,
        help="Skip first N episodes"
    )

    args = parser.parse_args()

    # If no specific tasks selected, do all
    do_all = not (args.tags or args.categories or args.embeddings or args.index_only)
    do_tags = args.tags or do_all
    do_categories = args.categories or do_all
    do_embeddings = args.embeddings or do_all

    print("=" * 60)
    print("MWP Backend Maintenance")
    print("=" * 60)
    print(f"Tasks: tags={do_tags}, categories={do_categories}, embeddings={do_embeddings}")
    print(f"Options: force={args.force}, dry_run={args.dry_run}")
    print(f"Limit: {args.limit or 'all'}, Offset: {args.offset}")

    # Index-only mode
    if args.index_only:
        refresh_episode_index()
        return

    # Get episodes needing updates
    print("\nFetching episodes...")
    if args.force:
        episodes = get_all_episodes()
    else:
        episodes = get_episodes_needing_metadata(
            check_tags=do_tags,
            check_category=do_categories,
            check_embedding=do_embeddings,
            limit=args.limit,
            offset=args.offset,
        )

    total = len(episodes)
    total_in_db = get_episode_count()

    if not episodes:
        print(f"No episodes need updating (total in database: {total_in_db})")
        if do_all or args.force:
            refresh_episode_index()
        return

    print(f"Found {total} episodes to process (total in database: {total_in_db})")

    if args.dry_run:
        print("\n[DRY RUN] No changes will be made")

    # Load progress
    progress = load_progress()
    processed_slugs = set(progress.get("processed", []))

    # Process episodes
    results = {"success": 0, "failed": 0, "skipped": 0}
    start_time = time.time()

    for i, episode in enumerate(episodes, 1):
        slug = episode["slug"]

        # Skip already processed (for resumability)
        if slug in processed_slugs and not args.force:
            results["skipped"] += 1
            continue

        print(f"\n[{i}/{total}]", end="")

        result = process_episode(
            episode,
            do_tags=do_tags,
            do_category=do_categories,
            do_embedding=do_embeddings,
            force=args.force,
            dry_run=args.dry_run,
        )

        if result["success"]:
            results["success"] += 1
            if not args.dry_run:
                progress["processed"].append(slug)
        else:
            results["failed"] += 1
            progress["errors"].append({
                "slug": slug,
                "errors": result["errors"],
                "timestamp": datetime.now().isoformat(),
            })

        # Save progress periodically
        if i % 10 == 0 and not args.dry_run:
            save_progress(progress)

        # Rate limiting
        time.sleep(RATE_LIMIT_DELAY)

    # Final save
    if not args.dry_run:
        save_progress(progress)

    # Summary
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Processed: {results['success']} success, {results['failed']} failed, {results['skipped']} skipped")
    print(f"Time: {elapsed:.1f}s ({elapsed/max(results['success'],1):.2f}s per episode)")

    # Refresh episode index after processing
    if (do_all or args.force) and not args.dry_run:
        refresh_episode_index()

    print("\nDone!")


if __name__ == "__main__":
    main()
