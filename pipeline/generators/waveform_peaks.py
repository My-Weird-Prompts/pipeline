"""
Waveform Peak Extraction

Extracts waveform peak data from audio files for instant waveform rendering
on the website. Produces a small JSON file (~10-15KB) that wavesurfer.js
can use to render the waveform without downloading the full audio.
"""

import json
import struct
import subprocess
from pathlib import Path
from typing import Optional


NUM_PEAKS = 2000  # Number of peak samples for the waveform display


def extract_peaks(audio_path: Path, num_peaks: int = NUM_PEAKS) -> bytes:
    """
    Extract waveform peaks from an audio file using ffmpeg.

    Decodes audio to raw mono float32 samples, then downsamples to
    the target number of peaks by taking the max absolute value in
    each window.

    Args:
        audio_path: Path to the audio file (MP3, WAV, etc.)
        num_peaks: Number of peak values to extract

    Returns:
        JSON bytes containing peaks array and duration
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Get duration first via ffprobe
    duration = _get_duration(audio_path)
    if duration <= 0:
        raise ValueError(f"Invalid audio duration: {duration}")

    # Decode to raw mono float32 at 8kHz (fast, sufficient for peaks)
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error",
            "-i", str(audio_path),
            "-ac", "1",          # mono
            "-ar", "8000",       # 8kHz sample rate
            "-f", "f32le",       # raw float32 little-endian
            "pipe:1",
        ],
        capture_output=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[:200]}")

    raw_bytes = result.stdout
    if len(raw_bytes) < 4:
        raise ValueError("ffmpeg produced no audio data")

    # Parse raw float32 samples
    num_samples = len(raw_bytes) // 4
    samples = struct.unpack(f"<{num_samples}f", raw_bytes)

    # Downsample to target number of peaks
    peaks = _downsample_peaks(samples, num_peaks)

    payload = {
        "peaks": peaks,
        "duration": round(duration, 2),
    }

    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _get_duration(audio_path: Path) -> float:
    """Get audio duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return float(result.stdout.strip())


def _downsample_peaks(samples: tuple, num_peaks: int) -> list:
    """
    Downsample raw audio samples to a fixed number of peaks.

    Takes the max absolute value in each window for a clean waveform display.
    Values are normalized to [0.0, 1.0].
    """
    num_samples = len(samples)
    if num_samples <= num_peaks:
        # Fewer samples than peaks — just normalize
        max_val = max(abs(s) for s in samples) or 1.0
        return [round(abs(s) / max_val, 4) for s in samples]

    window_size = num_samples / num_peaks
    peaks = []

    for i in range(num_peaks):
        start = int(i * window_size)
        end = int((i + 1) * window_size)
        end = min(end, num_samples)
        if start >= end:
            peaks.append(0.0)
            continue
        window_max = max(abs(samples[j]) for j in range(start, end))
        peaks.append(window_max)

    # Normalize to [0, 1]
    max_peak = max(peaks) if peaks else 1.0
    if max_peak > 0:
        peaks = [round(p / max_peak, 4) for p in peaks]

    return peaks
