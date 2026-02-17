#!/usr/bin/env python3
"""
Publication Webhook for MWP Pipeline

Sends episode data to an external webhook when an episode is published.
Uses a placeholder URL by default, configurable via environment variable.

This enables external systems to be notified when new episodes are available,
with full episode metadata including audio URL, cover art, and transcript.
"""

import os
import json
from datetime import datetime
from typing import Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    requests = None


# Production and testing webhook URLs
PUBLICATION_WEBHOOK_URL_PROD = os.environ.get(
    "PUBLICATION_WEBHOOK_URL_PROD",
    ""
)
PUBLICATION_WEBHOOK_URL_TEST = os.environ.get(
    "PUBLICATION_WEBHOOK_URL_TEST",
    ""
)

# Use test mode if WEBHOOK_TEST_MODE is set to "true" or "1"
WEBHOOK_TEST_MODE = os.environ.get("WEBHOOK_TEST_MODE", "").lower() in ("true", "1", "yes")

# Select active webhook URL based on mode
PUBLICATION_WEBHOOK_URL = PUBLICATION_WEBHOOK_URL_TEST if WEBHOOK_TEST_MODE else PUBLICATION_WEBHOOK_URL_PROD

# Optional webhook secret for authentication
PUBLICATION_WEBHOOK_SECRET = os.environ.get("PUBLICATION_WEBHOOK_SECRET", "")

# Timeout for webhook requests (seconds)
WEBHOOK_TIMEOUT = int(os.environ.get("WEBHOOK_TIMEOUT", "10"))


def notify_publication(
    slug: str,
    title: str,
    description: str = "",
    episode_url: str = "",
    audio_url: str = "",
    cover_url: str = "",
    duration: str = "",
    tags: list[str] = None,
    category: str = "",
    subcategory: str = "",
    prompt_transcript: str = "",
    ai_response: str = "",
    pub_date: str = "",
    og_image: str = "",
    # Extended fields for full syndication support
    episode_number: int = None,
    excerpt: str = "",
    show_notes: str = "",
    prompt_summary: str = "",
    instagram_image: str = "",
    transcript_url: str = "",
    tts_engine: str = "",
    tts_model: str = "",
    llm_model: str = "",
    pipeline_version: str = "",
    generation_time_seconds: float = None,
    tts_cost_usd: float = None,
    segments_count: int = None,
    **extra_fields,
) -> dict:
    """
    Send episode publication notification to configured webhook.

    Sends a comprehensive payload with all episode data for downstream
    syndication to platforms like Telegram, Twitter/X, Substack, etc.

    Args:
        slug: Episode slug/identifier
        title: Episode title
        description: Episode description (full)
        episode_url: Public URL to episode page
        audio_url: Direct URL to audio file
        cover_url: URL to cover image
        duration: Episode duration (formatted string, e.g., "20:45")
        tags: List of tags/categories
        category: Primary category
        subcategory: Subcategory
        prompt_transcript: Original user prompt transcript
        ai_response: Full AI-generated dialogue script
        pub_date: Publication date (ISO format)
        og_image: OpenGraph image URL (1200x630)

        Extended fields:
        episode_number: Sequential episode number (e.g., 247)
        excerpt: Short teaser text (100-150 chars, good for tweets)
        show_notes: Blog-style article about the episode (good for Substack)
        prompt_summary: Condensed summary of what the user asked
        instagram_image: Instagram-optimized image URL (4:5 aspect)
        transcript_url: URL to combined transcript file (Podcasting 2.0)
        tts_engine: TTS engine used (e.g., "chatterbox-local")
        tts_model: Specific TTS model used
        llm_model: LLM model used for script generation
        pipeline_version: Generation pipeline version
        generation_time_seconds: How long generation took
        tts_cost_usd: TTS cost in USD
        segments_count: Number of audio segments

        **extra_fields: Any additional fields to include

    Returns:
        Dict with 'success', 'successful', 'total', and any error info
    """
    if not HAS_REQUESTS:
        print("  [Publication Webhook] Skipped: requests library not available")
        return {
            "success": False,
            "successful": 0,
            "total": 0,
            "skipped": True,
            "reason": "requests library not available",
        }

    if not PUBLICATION_WEBHOOK_URL:
        print("  [Publication Webhook] Skipped: No webhook URL configured")
        return {
            "success": False,
            "successful": 0,
            "total": 0,
            "skipped": True,
            "reason": "No webhook URL configured",
        }

    # Log which mode we're using
    mode = "TEST" if WEBHOOK_TEST_MODE else "PROD"
    print(f"  [Publication Webhook] Mode: {mode}")

    # Build comprehensive payload for downstream syndication
    payload = {
        "event": "episode.published",
        "timestamp": datetime.utcnow().isoformat() + "Z",

        # Core episode identification and URLs
        "episode": {
            "slug": slug,
            "episode_number": episode_number,
            "title": title,
            "description": description,
            "excerpt": excerpt,  # Short teaser, good for tweets
            "episode_url": episode_url,
            "audio_url": audio_url,
            "duration": duration,
            "pub_date": pub_date,
        },

        # All image assets for different platforms
        "images": {
            "cover": cover_url,
            "og_image": og_image or cover_url,  # 1200x630 for social sharing
            "instagram": instagram_image,  # 4:5 aspect ratio
        },

        # Categorization and discovery
        "metadata": {
            "tags": tags or [],
            "category": category,
            "subcategory": subcategory,
        },

        # Full content for platforms that need it (Substack, etc.)
        "content": {
            "prompt_transcript": prompt_transcript,  # What the user asked
            "prompt_summary": prompt_summary,  # Condensed version
            "ai_response": ai_response,  # Full dialogue script
            "show_notes": show_notes,  # Blog-style article
            "transcript_url": transcript_url,  # Podcasting 2.0 transcript
        },

        # Production metadata (for analytics/debugging)
        "production": {
            "tts_engine": tts_engine,
            "tts_model": tts_model,
            "llm_model": llm_model,
            "pipeline_version": pipeline_version,
            "generation_time_seconds": generation_time_seconds,
            "tts_cost_usd": tts_cost_usd,
            "segments_count": segments_count,
        },

        **extra_fields,
    }

    # Build headers
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "MWP-Backend/1.0",
    }

    if PUBLICATION_WEBHOOK_SECRET:
        headers["X-Webhook-Secret"] = PUBLICATION_WEBHOOK_SECRET

    # Send webhook (with retry on transient failures)
    try:
        from pipeline.generators.episode_recovery import retry_with_backoff
    except ImportError:
        retry_with_backoff = None

    class _WebhookServerError(Exception):
        """Raised on 5xx to trigger retry."""
        def __init__(self, response):
            self.response = response
            super().__init__(f"Server error {response.status_code}")

    def _send_webhook():
        r = requests.post(
            PUBLICATION_WEBHOOK_URL,
            json=payload,
            headers=headers,
            timeout=WEBHOOK_TIMEOUT,
        )
        if 500 <= r.status_code < 600:
            raise _WebhookServerError(r)
        return r

    try:
        print(f"  [Publication Webhook] Sending to {PUBLICATION_WEBHOOK_URL[:50]}...")

        if retry_with_backoff:
            response = retry_with_backoff(
                _send_webhook,
                max_retries=1,
                initial_delay=3.0,
                retryable_exceptions=(
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    _WebhookServerError,
                ),
                on_retry=lambda attempt, e: print(f"  [Publication Webhook] Retry {attempt}: {e}"),
            )
        else:
            response = _send_webhook()

        if response.status_code >= 200 and response.status_code < 300:
            print(f"  [Publication Webhook] Success: {response.status_code}")
            return {
                "success": True,
                "successful": 1,
                "total": 1,
                "status_code": response.status_code,
            }
        else:
            print(f"  [Publication Webhook] Failed: {response.status_code} - {response.text[:100]}")
            return {
                "success": False,
                "successful": 0,
                "total": 1,
                "status_code": response.status_code,
                "error": response.text[:200],
            }

    except _WebhookServerError as e:
        print(f"  [Publication Webhook] Server error after retries: {e.response.status_code}")
        return {
            "success": False,
            "successful": 0,
            "total": 1,
            "status_code": e.response.status_code,
            "error": e.response.text[:200],
        }
    except requests.exceptions.Timeout:
        print(f"  [Publication Webhook] Timeout after {WEBHOOK_TIMEOUT}s")
        return {
            "success": False,
            "successful": 0,
            "total": 1,
            "error": f"Timeout after {WEBHOOK_TIMEOUT}s",
        }
    except requests.exceptions.RequestException as e:
        print(f"  [Publication Webhook] Request error: {e}")
        return {
            "success": False,
            "successful": 0,
            "total": 1,
            "error": str(e),
        }
    except Exception as e:
        print(f"  [Publication Webhook] Unexpected error: {e}")
        return {
            "success": False,
            "successful": 0,
            "total": 1,
            "error": str(e),
        }


def notify_publication_async(
    **kwargs,
) -> None:
    """
    Fire-and-forget version that doesn't block on webhook response.

    Use this when you want to notify but don't care about the result.
    Spawns a thread to handle the request.
    """
    import threading

    def _send():
        try:
            notify_publication(**kwargs)
        except Exception as e:
            print(f"  [Publication Webhook] Async error: {e}")

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


if __name__ == "__main__":
    # Test the webhook with full payload
    print("Testing publication webhook...")
    print(f"URL: {PUBLICATION_WEBHOOK_URL}")
    print(f"Secret: {'configured' if PUBLICATION_WEBHOOK_SECRET else 'not configured'}")

    result = notify_publication(
        # Core episode data
        slug="test-episode-2025",
        episode_number=247,
        title="Test Episode: AI Explores the Meaning of Toast",
        description="In this episode, we dive deep into the philosophical implications of breakfast foods and their role in human consciousness.",
        excerpt="AI ponders toast. Chaos ensues.",
        episode_url="https://myweirdprompts.com/episode/test-episode-2025",
        audio_url="https://episodes.myweirdprompts.com/audio/test-episode-2025.mp3",
        duration="20:45",
        pub_date="2025-01-08T12:00:00Z",

        # Images
        cover_url="https://images.myweirdprompts.com/covers/test-episode-2025.png",
        og_image="https://images.myweirdprompts.com/og/test-episode-2025.png",
        instagram_image="https://images.myweirdprompts.com/instagram/test-episode-2025.png",

        # Metadata
        tags=["philosophy", "food", "ai-musings"],
        category="technology",
        subcategory="ai",

        # Content
        prompt_transcript="What does toast mean to you?",
        prompt_summary="User asks AI about the meaning of toast",
        ai_response="[Full dialogue script would go here...]",
        show_notes="# The Great Toast Debate\n\nIn episode 247, we tackle...",
        transcript_url="https://episodes.myweirdprompts.com/transcripts/test-episode-2025.txt",

        # Production metadata
        tts_engine="chatterbox-local",
        tts_model="chatterbox-regular",
        llm_model="gemini-3-flash-preview",
        pipeline_version="2.0",
        generation_time_seconds=245.5,
        tts_cost_usd=0.0,
        segments_count=24,
    )

    print(f"\nResult: {json.dumps(result, indent=2)}")
