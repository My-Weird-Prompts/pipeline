"""
Model configuration for the MWP podcast pipeline.

Configurable LLM model names with environment variable overrides.
"""

import os

# =============================================================================
# LLM MODELS (Gemini)
# =============================================================================

# All models configurable via environment variables
TRANSCRIPTION_MODEL = os.environ.get("TRANSCRIPTION_MODEL", "google/gemini-3-flash-preview")
PLANNING_MODEL = os.environ.get("PLANNING_MODEL", "google/gemini-3-flash-preview")
SCRIPT_MODEL = os.environ.get("SCRIPT_MODEL", "google/gemini-3-flash-preview")
METADATA_MODEL = os.environ.get("METADATA_MODEL", "google/gemini-3-flash-preview")

# Episode planning agent
EPISODE_PLANNING_MODEL = os.environ.get("EPISODE_PLANNING_MODEL", "google/gemini-3-flash-preview")

# Script review agent - with grounding
SCRIPT_REVIEW_MODEL = os.environ.get("SCRIPT_REVIEW_MODEL", "google/gemini-3-flash-preview")

# Fallback model for direct Gemini API calls
GEMINI_MODEL = "gemini-3-flash-preview"

# Script polish agent - flow/style edits (no grounding needed)
SCRIPT_POLISH_MODEL = os.environ.get("SCRIPT_POLISH_MODEL", "google/gemini-3-flash-preview")

# =============================================================================
# IMAGE GENERATION
# =============================================================================

# Fal AI model for cover art
IMAGE_MODEL = "fal-ai/flux/schnell"

# =============================================================================
# API KEYS (loaded from environment)
# =============================================================================

def get_gemini_api_key() -> str | None:
    """Get Gemini API key from environment."""
    return os.environ.get("GEMINI_API_KEY")


def get_fal_api_key() -> str | None:
    """Get Fal AI API key from environment."""
    return os.environ.get("FAL_KEY")
