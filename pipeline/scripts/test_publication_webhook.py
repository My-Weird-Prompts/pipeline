#!/usr/bin/env python3
"""
Test Publication Webhook

Sends a test webhook payload to the configured test endpoint using real episode
data from the database. This allows testing n8n workflows and other integrations
with production-like payloads.

Usage:
    # Send last episode to test endpoint
    python pipeline/scripts/test_publication_webhook.py

    # Send specific episode by slug
    python pipeline/scripts/test_publication_webhook.py --slug "my-episode-slug"

    # Send to production endpoint (use with caution!)
    python pipeline/scripts/test_publication_webhook.py --prod

    # Dry run - print payload without sending
    python pipeline/scripts/test_publication_webhook.py --dry-run

Environment:
    POSTGRES_URL - Database connection string (required)
    PUBLICATION_WEBHOOK_SECRET - Optional webhook secret for authentication

Test URL: (configure via PUBLICATION_WEBHOOK_URL_TEST env var)
Prod URL: (configure via PUBLICATION_WEBHOOK_URL_PROD env var)
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

from pipeline.database.postgres import get_latest_episodes, get_episode


# Webhook URLs
WEBHOOK_URL_TEST = ""
WEBHOOK_URL_PROD = ""

# Optional secret
WEBHOOK_SECRET = os.environ.get("PUBLICATION_WEBHOOK_SECRET", "")

# Timeout
WEBHOOK_TIMEOUT = 30


def format_duration(duration_str: str) -> str:
    """Ensure duration is in MM:SS or HH:MM:SS format."""
    if not duration_str:
        return "00:00"
    return duration_str


def build_payload(episode: dict) -> dict:
    """
    Build the publication webhook payload from an episode dict.

    This matches the format sent by pipeline/webhooks/publication_webhook.py
    """
    slug = episode.get('slug', '')
    episode_number = episode.get('episode_number')

    # Build episode URL
    episode_url = f"https://myweirdprompts.com/episode/{slug}" if slug else ""

    # Get pub_date in ISO format
    pub_date = episode.get('pub_date')
    if pub_date:
        if isinstance(pub_date, datetime):
            pub_date = pub_date.isoformat() + "Z" if pub_date.tzinfo is None else pub_date.isoformat()
        else:
            pub_date = str(pub_date)
    else:
        pub_date = datetime.now(timezone.utc).isoformat()

    payload = {
        "event": "episode.published",
        "timestamp": datetime.now(timezone.utc).isoformat(),

        # Core episode identification and URLs
        "episode": {
            "slug": slug,
            "episode_number": episode_number,
            "title": episode.get('title', 'Untitled Episode'),
            "description": episode.get('description', ''),
            "excerpt": episode.get('excerpt', ''),
            "episode_url": episode_url,
            "audio_url": episode.get('podcast_audio_url', ''),
            "duration": format_duration(episode.get('podcast_duration', '')),
            "pub_date": pub_date,
        },

        # All image assets for different platforms
        "images": {
            "cover": episode.get('hero_image', ''),
            "og_image": episode.get('og_image') or episode.get('hero_image', ''),
            "instagram": episode.get('instagram_image', ''),
        },

        # Categorization and discovery
        "metadata": {
            "tags": episode.get('tags') or [],
            "category": episode.get('category', ''),
            "subcategory": episode.get('subcategory', ''),
        },

        # Full content for platforms that need it (Substack, etc.)
        "content": {
            "prompt_transcript": episode.get('prompt_transcript', ''),
            "prompt_summary": episode.get('prompt_summary', ''),
            "ai_response": episode.get('response') or episode.get('transcript', ''),
            "show_notes": episode.get('show_notes', ''),
            "transcript_url": episode.get('transcript_url', ''),
        },

        # Production metadata (for analytics/debugging)
        "production": {
            "tts_engine": episode.get('tts_engine', ''),
            "tts_model": episode.get('tts_model', ''),
            "llm_model": episode.get('llm_model', ''),
            "pipeline_version": episode.get('pipeline_version', ''),
            "generation_time_seconds": None,
            "tts_cost_usd": None,
            "segments_count": None,
        },
    }

    return payload


def send_webhook(payload: dict, url: str) -> dict:
    """Send the webhook payload to the specified URL."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "MWP-Backend/1.0 (Test Script)",
    }

    if WEBHOOK_SECRET:
        headers["X-Webhook-Secret"] = WEBHOOK_SECRET

    try:
        print(f"Sending to: {url}")
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=WEBHOOK_TIMEOUT,
        )

        if 200 <= response.status_code < 300:
            print(f"Success: {response.status_code}")
            return {
                "success": True,
                "status_code": response.status_code,
                "response": response.text[:500] if response.text else None,
            }
        else:
            print(f"Failed: {response.status_code} - {response.text[:200]}")
            return {
                "success": False,
                "status_code": response.status_code,
                "error": response.text[:500],
            }

    except requests.exceptions.Timeout:
        print(f"Timeout after {WEBHOOK_TIMEOUT}s")
        return {"success": False, "error": f"Timeout after {WEBHOOK_TIMEOUT}s"}
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Send test publication webhook with real episode data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--slug",
        help="Episode slug to send (default: latest episode)"
    )
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Send to production webhook URL (use with caution!)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payload without sending"
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the payload JSON"
    )

    args = parser.parse_args()

    # Get episode from database
    if args.slug:
        print(f"Fetching episode: {args.slug}")
        episode = get_episode(args.slug)
        if not episode:
            print(f"Error: Episode not found: {args.slug}")
            sys.exit(1)
    else:
        print("Fetching latest episode...")
        episodes = get_latest_episodes(1)
        if not episodes:
            print("Error: No episodes found in database")
            print("Make sure POSTGRES_URL environment variable is set")
            sys.exit(1)
        episode = episodes[0]

    # Build payload
    payload = build_payload(episode)

    print(f"\nEpisode: {payload['episode']['title']}")
    print(f"Slug: {payload['episode']['slug']}")
    print(f"Episode #: {payload['episode']['episode_number']}")
    print(f"Duration: {payload['episode']['duration']}")

    # Content summary
    ai_response = payload['content']['ai_response']
    show_notes = payload['content']['show_notes']
    print(f"\nContent lengths:")
    print(f"  - ai_response: {len(ai_response)} chars")
    print(f"  - show_notes: {len(show_notes)} chars")
    print(f"  - prompt_transcript: {len(payload['content']['prompt_transcript'])} chars")

    if args.dry_run or args.pretty:
        print("\n--- Payload ---")
        print(json.dumps(payload, indent=2, default=str))

    if args.dry_run:
        print("\n[Dry run - not sending]")
        return

    # Select URL
    url = WEBHOOK_URL_PROD if args.prod else WEBHOOK_URL_TEST
    mode = "PRODUCTION" if args.prod else "TEST"
    print(f"\nMode: {mode}")

    if args.prod:
        confirm = input("Are you sure you want to send to PRODUCTION? (yes/no): ")
        if confirm.lower() != "yes":
            print("Cancelled")
            return

    # Send
    print()
    result = send_webhook(payload, url)

    print(f"\nResult: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
