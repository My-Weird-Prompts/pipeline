#!/usr/bin/env python3
"""
Backfill OG Images using Branded Template

Regenerates Open Graph images for existing episodes using the branded template
(og-default.png from brand kit) with episode title and number overlaid.

This creates consistent, on-brand social sharing previews.

Usage:
    # Dry run (show what would be updated)
    python backfill_og_images.py --dry-run

    # Update all episodes
    python backfill_og_images.py

    # Update specific episodes by slug
    python backfill_og_images.py --slugs "episode-1,episode-2"

    # Limit to N episodes
    python backfill_og_images.py --limit 10
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime

# Add parent directories to path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR.parent / "generators"))
sys.path.insert(0, str(SCRIPT_DIR.parent.parent))

from dotenv import load_dotenv
load_dotenv()

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    print("Error: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from generate_og_image import generate_og_image_branded, OG_WIDTH, OG_HEIGHT

try:
    from pipeline.storage.r2 import upload_og_image, get_r2_client
    HAS_R2 = True
except ImportError:
    HAS_R2 = False
    print("Warning: R2 storage not available")


def get_episodes_needing_update(
    cursor,
    slugs: list = None,
    limit: int = None,
    skip_existing: bool = True,
) -> list:
    """
    Get episodes that need OG image updates.

    Args:
        cursor: Database cursor
        slugs: Optional list of specific slugs to update
        limit: Maximum number of episodes to return
        skip_existing: Skip episodes that already have OG images (False = regenerate all)

    Returns:
        List of episode dicts with slug, title, hero_image, og_image, episode_number
    """
    query = """
        SELECT slug, title, hero_image, og_image, episode_number
        FROM episodes
        WHERE hero_image IS NOT NULL
    """
    params = []

    if slugs:
        placeholders = ",".join(["%s"] * len(slugs))
        query += f" AND slug IN ({placeholders})"
        params.extend(slugs)

    if skip_existing:
        # Only get episodes where OG image is missing
        query += " AND (og_image IS NULL OR og_image = '')"

    query += " ORDER BY episode_number ASC NULLS LAST, pub_date DESC"

    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query, params)
    columns = ["slug", "title", "hero_image", "og_image", "episode_number"]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def regenerate_og_image(
    episode: dict,
    output_dir: Path,
    upload_to_r2: bool = True,
) -> dict:
    """
    Regenerate OG image for an episode using the branded template.

    Args:
        episode: Episode dict with slug, title, hero_image
        output_dir: Directory to save generated image
        upload_to_r2: Whether to upload to R2

    Returns:
        Dict with success status and new URL
    """
    slug = episode["slug"]
    title = episode["title"]
    episode_number = episode.get("episode_number")

    result = {
        "slug": slug,
        "success": False,
        "og_url": None,
        "error": None,
    }

    try:
        # Generate OG image using branded template
        og_path = generate_og_image_branded(
            title=title,
            episode_number=episode_number,
            output_dir=output_dir,
            output_filename=f"{slug}-og.png",
        )

        if not og_path.exists():
            result["error"] = "OG image file not created"
            return result

        # Upload to R2 if available
        if upload_to_r2 and HAS_R2:
            og_url = upload_og_image(og_path, slug)
            if og_url:
                result["og_url"] = og_url
                result["success"] = True
            else:
                result["error"] = "R2 upload failed"
        else:
            result["og_url"] = str(og_path)
            result["success"] = True

    except Exception as e:
        result["error"] = str(e)

    return result


def update_episode_og_image(cursor, conn, slug: str, og_url: str) -> bool:
    """Update episode's OG image URL in database."""
    try:
        cursor.execute(
            "UPDATE episodes SET og_image = %s WHERE slug = %s",
            (og_url, slug)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"  Error updating database: {e}")
        conn.rollback()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Regenerate OG images from cover art for existing episodes",
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
        "--force",
        action="store_true",
        help="Regenerate even if OG image already exists",
    )

    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Don't upload to R2, just generate locally",
    )

    args = parser.parse_args()

    # Get database connection
    postgres_url = os.environ.get("POSTGRES_URL") or os.environ.get("NEON_DATABASE_URL")
    if not postgres_url:
        print("Error: POSTGRES_URL environment variable not set")
        sys.exit(1)

    print("=" * 60)
    print("OG Image Backfill - Cover Art Edition")
    print("=" * 60)
    print(f"Dry run: {args.dry_run}")
    print(f"Force regenerate: {args.force}")
    print(f"Upload to R2: {not args.no_upload and HAS_R2}")
    print()

    # Connect to database
    conn = psycopg2.connect(postgres_url)
    cursor = conn.cursor()

    # Parse slugs if provided
    slugs = None
    if args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",")]
        print(f"Filtering to slugs: {slugs}")

    # Get episodes to update
    episodes = get_episodes_needing_update(
        cursor,
        slugs=slugs,
        limit=args.limit,
        skip_existing=not args.force,
    )

    print(f"Found {len(episodes)} episodes to process")
    print()

    if not episodes:
        print("No episodes need OG image updates.")
        cursor.close()
        conn.close()
        return

    if args.dry_run:
        print("DRY RUN - No changes will be made")
        print("-" * 40)
        for ep in episodes:
            print(f"  {ep['slug']}: {ep['title'][:50]}...")
            print(f"    Cover: {ep['hero_image'][:60] if ep['hero_image'] else 'None'}...")
            print(f"    Current OG: {ep['og_image'][:60] if ep['og_image'] else 'None'}...")
        cursor.close()
        conn.close()
        return

    # Create temp directory for generated images
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        success_count = 0
        fail_count = 0

        for i, episode in enumerate(episodes, 1):
            print(f"[{i}/{len(episodes)}] {episode['slug']}")
            print(f"  Title: {episode['title'][:60]}...")

            result = regenerate_og_image(
                episode,
                output_dir=temp_path,
                upload_to_r2=not args.no_upload,
            )

            if result["success"]:
                print(f"  ✓ Generated: {result['og_url'][:60] if result['og_url'] else 'local'}...")

                # Update database
                if result["og_url"] and not args.no_upload:
                    if update_episode_og_image(cursor, conn, episode["slug"], result["og_url"]):
                        print(f"  ✓ Database updated")
                        success_count += 1
                    else:
                        fail_count += 1
                else:
                    success_count += 1
            else:
                print(f"  ✗ Failed: {result['error']}")
                fail_count += 1

            print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total processed: {len(episodes)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
