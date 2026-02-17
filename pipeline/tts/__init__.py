"""
TTS (Text-to-Speech) module for the MWP podcast pipeline.

OPTIMIZATIONS (January 2026):
- Pre-computed voice conditionals loaded from R2 (no per-segment voice processing)
- Parallel TTS generation via Modal workers
- ~4x faster generation with 4 parallel workers

Uses Chatterbox (regular, not Turbo - fewer hallucinations) for local
GPU-accelerated TTS with voice cloning.

Usage:
    from pipeline.tts import synthesize, generate_dialogue_audio

    # Pre-warm (loads model + cached conditionals)
    prewarm_voice_samples()

    # Generate single segment
    result = synthesize(text, voice_name, output_path)

    # Generate all dialogue (sequential)
    dialogue_path, stats = generate_dialogue_audio(segments, episode_dir)

For parallel TTS, use the Modal-specific generate_dialogue_audio_parallel()
function defined in modal_app/recording_app.py.
"""

from .chatterbox import (
    # Model management
    get_chatterbox_model,
    prewarm_voice_samples,
    clear_cache,
    # Voice conditionals (cached embeddings)
    get_voice_conditionals,
    VOICE_CONDITIONALS_URLS,
    VOICE_SAMPLE_URLS,
    CACHE_DIR,
    # Synthesis
    synthesize,
    synthesize_segment,
    generate_dialogue_audio,
)

__all__ = [
    # Model management
    "get_chatterbox_model",
    "prewarm_voice_samples",
    "clear_cache",
    # Voice conditionals
    "get_voice_conditionals",
    "VOICE_CONDITIONALS_URLS",
    "VOICE_SAMPLE_URLS",
    "CACHE_DIR",
    # Synthesis
    "synthesize",
    "synthesize_segment",
    "generate_dialogue_audio",
]
