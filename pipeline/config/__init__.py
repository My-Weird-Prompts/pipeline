"""
Configuration module for MWP podcast pipeline.

Centralizes all constants, paths, and configuration values.
"""

from .constants import *
from .models import *

__all__ = [
    # Podcast identity
    'PODCAST_NAME',
    'PODCAST_SUBTITLE',
    'PRODUCER_NAME',
    'HOST_NAME',
    'CO_HOST_NAME',

    # Paths
    'PIPELINE_ROOT',
    'PROJECT_ROOT',
    'EPISODES_DIR',
    'JINGLES_DIR',

    # Audio elements
    'DISCLAIMER_PATH',
    'PROMPT_INTRO_PATH',
    'TRANSITION_WHOOSH_PATH',
    'LLM_INFO_PATH',
    'TTS_INFO_PATH',

    # Voice samples
    'VOICE_SAMPLE_URLS',
    'VOICE_SAMPLES',

    # Episode length
    'MIN_WORD_COUNT',
    'MAX_WORD_COUNT',
    'TARGET_WORD_COUNT',

    # Models
    'TRANSCRIPTION_MODEL',
    'PLANNING_MODEL',
    'SCRIPT_MODEL',
    'METADATA_MODEL',
]
