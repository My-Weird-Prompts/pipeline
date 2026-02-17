"""
Chatterbox TTS module for the MWP podcast pipeline.

OPTIMIZATIONS:
- Pre-computed voice conditionals loaded from R2 (eliminates per-segment voice processing)
- Conditionals cached at module level for reuse across segments
- Parallel TTS generation supported via synthesize_segment() function

Uses regular Chatterbox (not Turbo) for local GPU-accelerated text-to-speech with voice cloning.
Regular Chatterbox has fewer hallucination issues with voice clones compared to Turbo.

Usage:
    from pipeline.tts import get_chatterbox_model, synthesize, generate_dialogue_audio

    # Prewarm (loads model + conditionals)
    prewarm_voice_samples()

    # Single segment (uses cached conditionals)
    result = synthesize(text, voice_name, output_path)

    # All dialogue segments
    dialogue_path, stats = generate_dialogue_audio(segments, episode_dir)
"""

import os
import subprocess
from pathlib import Path
from typing import Optional

import torch

# URLs for pre-computed voice conditionals on R2 CDN
# These are generated once using precompute_voice_conditionals.py and cached
VOICE_CONDITIONALS_URLS = {
    "corn": "https://ai-files.myweirdprompts.com/voices/corn/corn_conds.pt",
    "herman": "https://ai-files.myweirdprompts.com/voices/herman/herman_conds.pt",
}

# Fallback: voice sample URLs (only used if conditionals not available)
VOICE_SAMPLE_URLS = {
    "corn": "https://ai-files.myweirdprompts.com/voices/corn/corn-1min.wav",
    "herman": "https://ai-files.myweirdprompts.com/voices/herman/herman-1min.wav",
    "daniel": "https://ai-files.myweirdprompts.com/voices/daniel/daniel-1min.wav",
}

# Cache directory on Modal Volume
CACHE_DIR = Path("/working/voice_cache")

# Module-level caches
_chatterbox_model = None
_cached_conditionals = {}  # voice_name -> Conditionals object


def get_chatterbox_model():
    """
    Lazy-load the Chatterbox model (regular, not Turbo - fewer hallucinations).

    The model is cached at module level for reuse across multiple calls.
    Requires CUDA GPU.

    Returns:
        ChatterboxTTS model instance
    """
    global _chatterbox_model
    if _chatterbox_model is None:
        from chatterbox.tts import ChatterboxTTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading Chatterbox TTS on {device}...")
        _chatterbox_model = ChatterboxTTS.from_pretrained(device=device)
        print("Chatterbox TTS loaded successfully")
    return _chatterbox_model


def get_voice_conditionals(voice_name: str) -> "Conditionals":
    """
    Get cached voice conditionals for a voice.

    Loads pre-computed conditionals from R2, caching them for reuse.
    This eliminates the expensive voice embedding extraction that would
    otherwise happen on every generate() call.

    Args:
        voice_name: Name of the voice (e.g., "corn", "herman")

    Returns:
        Conditionals object ready for use with model.generate()
    """
    import requests
    from chatterbox.tts import Conditionals

    global _cached_conditionals

    voice_name = voice_name.lower()

    # Check in-memory cache
    if voice_name in _cached_conditionals:
        return _cached_conditionals[voice_name]

    # Check file cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{voice_name}_conds.pt"

    if cache_path.exists():
        print(f"  Loading cached conditionals for {voice_name}")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        conds = Conditionals.load(cache_path, map_location=device)
        _cached_conditionals[voice_name] = conds
        return conds

    # Download from R2
    url = VOICE_CONDITIONALS_URLS.get(voice_name)
    if url:
        print(f"  Downloading pre-computed conditionals for {voice_name}...")
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            cache_path.write_bytes(response.content)
            print(f"  Cached conditionals to: {cache_path}")

            device = "cuda" if torch.cuda.is_available() else "cpu"
            conds = Conditionals.load(cache_path, map_location=device)
            _cached_conditionals[voice_name] = conds
            return conds
        except Exception as e:
            print(f"  Warning: Failed to download conditionals: {e}")
            print(f"  Falling back to voice sample processing...")

    # Fallback: compute conditionals from voice sample (slow path)
    return _compute_conditionals_fallback(voice_name)


def _compute_conditionals_fallback(voice_name: str) -> "Conditionals":
    """
    Fallback: compute conditionals from voice sample.

    This is the slow path - only used if pre-computed conditionals
    are not available. Takes ~5-10 seconds per voice.
    """
    import requests

    voice_url = VOICE_SAMPLE_URLS.get(voice_name)
    if not voice_url:
        raise ValueError(f"Unknown voice: {voice_name}")

    # Download voice sample
    print(f"  Downloading voice sample for {voice_name} (fallback)...")
    response = requests.get(voice_url, timeout=30)
    response.raise_for_status()

    wav_path = CACHE_DIR / f"{voice_name}.wav"
    wav_path.write_bytes(response.content)

    # Compute conditionals
    print(f"  Computing conditionals for {voice_name} (this is slow!)...")
    model = get_chatterbox_model()
    model.prepare_conditionals(str(wav_path), exaggeration=0.5)

    # Cache for reuse
    conds = model.conds
    _cached_conditionals[voice_name] = conds

    # Save to file cache for future runs
    conds_path = CACHE_DIR / f"{voice_name}_conds.pt"
    conds.save(conds_path)
    print(f"  Saved computed conditionals to: {conds_path}")

    return conds


def prewarm_voice_samples():
    """
    Pre-load voice conditionals for all known voices.

    Call this at startup to avoid delays during first episode generation.
    With pre-computed conditionals, this is very fast (~1-2 seconds total).
    """
    print("Pre-warming voice conditionals cache...")
    for voice_name in VOICE_CONDITIONALS_URLS.keys():
        get_voice_conditionals(voice_name)
    print(f"Voice conditionals ready: {list(VOICE_CONDITIONALS_URLS.keys())}")


def synthesize(
    text: str,
    voice_name: str,
    output_path: Path,
    voice_sample_url: str = None,  # Deprecated, kept for compatibility
) -> dict:
    """
    Synthesize speech using local Chatterbox model with cached conditionals.

    Uses pre-computed voice conditionals for instant voice cloning
    (no per-segment voice processing overhead).

    Args:
        text: Text to synthesize
        voice_name: Name of the voice to use
        output_path: Where to save the output (will be saved as MP3)
        voice_sample_url: Deprecated, ignored (conditionals loaded from cache)

    Returns:
        dict with:
            - path: Path to the generated MP3 file
            - chars_processed: Number of characters synthesized
            - duration_seconds: Duration of the audio (if available)
            - cost_usd: Cost (always 0 for local TTS)
    """
    import torchaudio

    model = get_chatterbox_model()

    # Load cached conditionals (fast!) instead of processing audio (slow!)
    conds = get_voice_conditionals(voice_name)
    model.conds = conds

    # Generate audio WITHOUT audio_prompt_path (uses cached conds)
    wav = model.generate(text)

    # Save as WAV first
    wav_output = output_path.with_suffix(".wav")
    torchaudio.save(str(wav_output), wav.cpu(), model.sr)

    # Convert to MP3
    mp3_output = output_path.with_suffix(".mp3")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_output),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "96k",
            str(mp3_output),
        ],
        check=True,
        capture_output=True,
    )

    # Clean up WAV
    wav_output.unlink()

    # Get duration
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(mp3_output),
        ],
        capture_output=True,
        text=True,
    )
    duration = float(result.stdout.strip()) if result.stdout.strip() else None

    return {
        "path": mp3_output,
        "chars_processed": len(text),
        "duration_seconds": duration,
        "cost_usd": 0.0,
    }


def synthesize_segment(
    segment_idx: int,
    speaker: str,
    text: str,
    output_dir: str,
) -> dict:
    """
    Synthesize a single segment - designed for parallel execution.

    This function is self-contained and can be called from parallel workers.
    It handles model loading, conditional loading, and audio generation.

    Args:
        segment_idx: Index of the segment (for filename)
        speaker: Speaker name (voice to use)
        text: Text to synthesize
        output_dir: Directory to save the output

    Returns:
        dict with segment_idx, path, chars, duration, success
    """
    try:
        output_path = Path(output_dir) / f"segment_{segment_idx:04d}_{speaker.lower()}.mp3"

        # Check if already exists (checkpoint)
        if output_path.exists():
            return {
                "segment_idx": segment_idx,
                "path": str(output_path),
                "chars": len(text),
                "duration": None,
                "success": True,
                "from_checkpoint": True,
            }

        result = synthesize(text, speaker.lower(), output_path)

        return {
            "segment_idx": segment_idx,
            "path": str(result["path"]),
            "chars": result["chars_processed"],
            "duration": result["duration_seconds"],
            "success": True,
            "from_checkpoint": False,
        }
    except Exception as e:
        return {
            "segment_idx": segment_idx,
            "path": None,
            "chars": len(text),
            "duration": None,
            "success": False,
            "error": str(e),
            "from_checkpoint": False,
        }


def generate_dialogue_audio(
    segments: list,
    episode_dir: Path,
    progress_callback=None,
) -> tuple:
    """
    Generate audio for all dialogue segments using local Chatterbox.

    This is the sequential version - for parallel processing, use the
    Modal parallel TTS function instead.

    Args:
        segments: List of dicts with 'speaker' and 'text' keys
        episode_dir: Directory to save segment audio files
        progress_callback: Optional callback(current, total) for progress updates

    Returns:
        Tuple of (dialogue_path, stats) where:
            - dialogue_path: Path to concatenated dialogue MP3
            - stats: Dict with generation statistics
    """
    segments_dir = episode_dir / "_tts_segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    segment_files = []
    total_chars = 0

    for i, segment in enumerate(segments):
        speaker = segment["speaker"]
        text = segment["text"]

        output_path = segments_dir / f"segment_{i:04d}_{speaker.lower()}.mp3"

        if output_path.exists():
            print(f"  [{i + 1}/{len(segments)}] Using checkpoint: {output_path.name}")
        else:
            print(f"  [{i + 1}/{len(segments)}] {speaker}: {text[:50]}...")
            voice_name = speaker.lower()
            if voice_name not in VOICE_CONDITIONALS_URLS:
                voice_name = "herman"  # Fallback
            synthesize(text, voice_name, output_path)

        segment_files.append(output_path)
        total_chars += len(text)

        if progress_callback:
            progress_callback(i + 1, len(segments))

    # Concatenate all segments
    print("Concatenating segments...")
    dialogue_path = episode_dir / "dialogue.mp3"

    concat_file = segments_dir / "concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for segment_file in segment_files:
            f.write(f"file '{segment_file.absolute()}'\n")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "96k",
            str(dialogue_path),
        ],
        check=True,
        capture_output=True,
    )

    stats = {
        "engine": "chatterbox",
        "total_chars": total_chars,
        "chars_generated": total_chars,
        "chars_from_checkpoint": 0,
        "cost_usd": 0.0,
        "segments_total": len(segments),
        "segments_succeeded": len(segments),
        "segments_failed": 0,
    }

    return dialogue_path, stats


def clear_cache():
    """Clear the in-memory caches."""
    global _cached_conditionals, _chatterbox_model
    _cached_conditionals = {}
    _chatterbox_model = None
    print("TTS cache cleared")
