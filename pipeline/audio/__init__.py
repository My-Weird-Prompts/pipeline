"""
Audio processing module for the MWP podcast pipeline.

Contains:
- Audio processing (normalization, silence removal, format conversion)
- Episode assembly (concatenation)

Note: TTS is handled by pipeline.tts module (Chatterbox on Modal GPU).
"""

# Audio processing functions
from .processing import (
    get_audio_duration,
    get_audio_duration_formatted,
    remove_silence,
    normalize_loudness,
    convert_to_wav,
    convert_to_mp3,
    get_file_hash,
)

# Episode assembly functions
from .assembly import (
    concatenate_episode,
    process_prompt_audio,
    remove_silence_from_dialogue,
    normalize_audio_loudness,
)

# Script parsing (from core module)
from ..core.script_parser import (
    parse_diarized_script,
    chunk_long_text,
)

__all__ = [
    # Audio processing
    'get_audio_duration',
    'get_audio_duration_formatted',
    'remove_silence',
    'normalize_loudness',
    'convert_to_wav',
    'convert_to_mp3',
    'get_file_hash',

    # Episode assembly
    'concatenate_episode',
    'process_prompt_audio',
    'remove_silence_from_dialogue',
    'normalize_audio_loudness',

    # Script parsing (convenience re-export)
    'parse_diarized_script',
    'chunk_long_text',
]
