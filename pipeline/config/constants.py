"""
Constants and configuration for the MWP podcast pipeline.

All hardcoded values, paths, and URLs centralized here.
"""

import os
from pathlib import Path

# =============================================================================
# PATH CONFIGURATION
# =============================================================================

# Pipeline root: where the pipeline code lives
PIPELINE_ROOT = Path(__file__).parent.parent

# Project root: use /repo mount in Docker, otherwise derive from file path
DOCKER_REPO_MOUNT = Path("/repo")
if DOCKER_REPO_MOUNT.exists() and (DOCKER_REPO_MOUNT / ".git").exists():
    PROJECT_ROOT = DOCKER_REPO_MOUNT
else:
    PROJECT_ROOT = PIPELINE_ROOT.parent  # MWP-Backend root

# Frontend repo: use FRONTEND_REPO_PATH env var if set, otherwise try common locations
FRONTEND_REPO_PATH = os.environ.get("FRONTEND_REPO_PATH")
if FRONTEND_REPO_PATH:
    FRONTEND_ROOT = Path(FRONTEND_REPO_PATH)
elif Path("/frontend-repo").exists():
    FRONTEND_ROOT = Path("/frontend-repo")  # Docker mount
else:
    FRONTEND_ROOT = PIPELINE_ROOT.parent.parent / "My-Weird-Prompts"

# Output directories
OUTPUT_DIR = PIPELINE_ROOT / "output"
EPISODES_DIR = OUTPUT_DIR / "episodes"

# Show elements
JINGLES_DIR = PIPELINE_ROOT / "show-elements" / "mixed"
NORMALIZED_JINGLES_DIR = JINGLES_DIR / "normalized"

# Voice samples
VOICES_DIR = PROJECT_ROOT / "config" / "voices"

# Frontend paths (for blog publishing)
FRONTEND_PUBLIC = FRONTEND_ROOT / "code" / "frontend" / "public"
FRONTEND_AUDIO_DIR = FRONTEND_PUBLIC / "audio" / "episodes"
FRONTEND_IMAGES_DIR = FRONTEND_PUBLIC / "images" / "episodes"
FRONTEND_CONTENT_DIR = FRONTEND_ROOT / "code" / "frontend" / "src" / "content" / "blog"
FRONTEND_DATA_DIR = FRONTEND_ROOT / "code" / "frontend" / "src" / "data"

# Categories taxonomy file (monorepo path)
CATEGORIES_FILE = PROJECT_ROOT / "website" / "src" / "data" / "categories.json"

# Tags registry (in backend config, not frontend - allows dynamic updates)
TAGS_FILE = PIPELINE_ROOT / "config" / "tags.json"

# Queue directories
PROMPTS_TO_PROCESS_DIR = PROJECT_ROOT / "prompts" / "to-process"
PROMPTS_PROCESSED_DIR = PROJECT_ROOT / "prompts" / "processed"

# =============================================================================
# PODCAST IDENTITY
# =============================================================================

PODCAST_NAME = "My Weird Prompts"
PODCAST_SUBTITLE = "A Human-AI Podcast Collaboration"
PRODUCER_NAME = "Daniel Rosehill"
HOST_NAME = "Corn"
CO_HOST_NAME = "Herman"

# =============================================================================
# AUDIO ELEMENT PATHS
# =============================================================================

DISCLAIMER_PATH = JINGLES_DIR / "disclaimer.mp3"
PROMPT_INTRO_PATH = JINGLES_DIR / "prompt-intro-daniel.mp3"
TRANSITION_WHOOSH_PATH = JINGLES_DIR / "transition-whoosh.mp3"
LLM_INFO_PATH = JINGLES_DIR / "llm-info-gemini-flash-3.mp3"
TTS_INFO_PATH = JINGLES_DIR / "tts-info-chatterbox.mp3"

# Show element URLs on R2 (for Modal deployment where local files aren't available)
SHOW_ELEMENT_URLS = {
    "disclaimer": "https://ai-files.myweirdprompts.com/show-elements/disclaimer.mp3",
    "prompt-intro-daniel": "https://ai-files.myweirdprompts.com/show-elements/prompt-intro-daniel.mp3",
    "transition-whoosh": "https://ai-files.myweirdprompts.com/show-elements/transition-whoosh.mp3",
    "llm-info-gemini-flash-3": "https://ai-files.myweirdprompts.com/show-elements/llm-info-gemini-flash-3.mp3",
    "tts-info-chatterbox": "https://ai-files.myweirdprompts.com/show-elements/tts-info-chatterbox.mp3",
}

# =============================================================================
# VOICE SAMPLES
# =============================================================================

# Voice sample URLs on R2 CDN
# NOTE: Shorter samples (~1 min) work better for Chatterbox TTS and reduce hallucinations
VOICE_SAMPLE_URLS = {
    "Corn": "https://ai-files.myweirdprompts.com/voices/corn/corn-1min.wav",
    "Herman": "https://ai-files.myweirdprompts.com/voices/herman/herman-1min.wav",
    "Daniel": "https://ai-files.myweirdprompts.com/voices/daniel/daniel-1min.wav",
}

# Voice samples mapping (speaker name -> URL)
VOICE_SAMPLES = {
    HOST_NAME: VOICE_SAMPLE_URLS["Corn"],
    CO_HOST_NAME: VOICE_SAMPLE_URLS["Herman"],
}

# =============================================================================
# EPISODE LENGTH TARGETS
# =============================================================================

# Target episode length (20-30 minutes at ~150 words per minute)
MIN_WORD_COUNT = 3000   # ~20 minutes of dialogue
MAX_WORD_COUNT = 4500   # ~30 minutes of dialogue
TARGET_WORD_COUNT = 3750  # ~25 minutes (default target)

# =============================================================================
# AUDIO PROCESSING
# =============================================================================

# Audio normalization (EBU R128 podcast standard)
TARGET_LUFS = -16
TARGET_TP = -1.5  # True peak ceiling

# MP3 encoding bitrate (96k is transparent for speech, ~50% smaller than 192k)
MP3_BITRATE = "96k"

# Silence removal
SILENCE_THRESHOLD_DB = -50
SILENCE_MIN_DURATION = 1.0  # seconds

# TTS chunking - shorter segments reduce hallucinations
MAX_CHARS_PER_TTS_REQUEST = 250

# =============================================================================
# EXTERNAL SERVICES
# =============================================================================

# Wasabi (S3-compatible archival storage)
WASABI_BUCKET = os.environ.get("WASABI_BUCKET", "myweirdprompts")
WASABI_REGION = os.environ.get("WASABI_REGION", "eu-central-2")
WASABI_ENDPOINT = os.environ.get("WASABI_ENDPOINT", "https://s3.eu-central-2.wasabisys.com")

# =============================================================================
# PIPELINE VERSION
# =============================================================================

PIPELINE_VERSION = "V4"

# Ensure output directories exist
EPISODES_DIR.mkdir(parents=True, exist_ok=True)
