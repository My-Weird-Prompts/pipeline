"""
Audio processing functions for the MWP podcast pipeline.

Contains:
- Silence detection and removal
- Loudness normalization (EBU R128)
- Audio format conversion
- Duration utilities
"""

import json
import shutil
import subprocess
from pathlib import Path

from ..config.constants import (
    TARGET_LUFS,
    TARGET_TP,
    SILENCE_THRESHOLD_DB,
    SILENCE_MIN_DURATION,
)


def get_audio_duration(audio_path: Path) -> float | None:
    """
    Get the duration of an audio file in seconds.

    Args:
        audio_path: Path to audio file

    Returns:
        Duration in seconds, or None if unable to determine
    """
    probe_cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)
    ]
    result = subprocess.run(probe_cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return None


def get_audio_duration_formatted(audio_path: Path) -> str:
    """
    Get the duration of an audio file formatted as HH:MM:SS.

    Args:
        audio_path: Path to audio file

    Returns:
        Formatted duration string
    """
    duration = get_audio_duration(audio_path)
    if duration is None:
        return "00:00:00"

    hours = int(duration // 3600)
    minutes = int((duration % 3600) // 60)
    seconds = int(duration % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def remove_silence(
    input_path: Path,
    output_path: Path = None,
    silence_threshold_db: float = SILENCE_THRESHOLD_DB,
    min_silence_duration: float = SILENCE_MIN_DURATION,
) -> tuple[Path, dict]:
    """
    Remove extended silence from audio using FFmpeg's silenceremove filter.

    This catches failed TTS segments that produced silent audio files, or any
    unexpected gaps in the concatenated dialogue. Short pauses in natural speech
    are preserved (they're typically < 1 second and not total silence).

    Args:
        input_path: Input audio file
        output_path: Output file path (defaults to input_path with _cleaned suffix)
        silence_threshold_db: Audio below this dB is considered silence (default -50dB)
        min_silence_duration: Silence must exceed this duration to be removed (default 1.0s)

    Returns:
        Tuple of (Path to cleaned audio, stats dict with silence_removed_seconds)
    """
    if output_path is None:
        output_path = input_path.with_stem(input_path.stem + "_cleaned")

    print(f"  Checking audio for silence (threshold: {silence_threshold_db}dB, min duration: {min_silence_duration}s)...")

    # Get original duration
    original_duration = get_audio_duration(input_path) or 0

    # First, detect silence to report what we're removing
    detect_cmd = [
        "ffmpeg", "-i", str(input_path),
        "-af", f"silencedetect=noise={silence_threshold_db}dB:d={min_silence_duration}",
        "-f", "null", "-"
    ]
    detect_result = subprocess.run(detect_cmd, capture_output=True, text=True)

    # Parse silence detection output
    silence_periods = []
    for line in detect_result.stderr.split('\n'):
        if 'silence_start:' in line:
            try:
                start = float(line.split('silence_start:')[1].strip().split()[0])
                silence_periods.append({'start': start})
            except (IndexError, ValueError):
                pass
        elif 'silence_end:' in line and silence_periods:
            try:
                after_end = line.split('silence_end:')[1].strip()
                if '|' in after_end:
                    end_part, duration_part = after_end.split('|')
                    end = float(end_part.strip())
                    duration = float(duration_part.split(':')[1].strip())
                else:
                    end = float(after_end.split()[0])
                    duration = end - silence_periods[-1].get('start', end)
                silence_periods[-1]['end'] = end
                silence_periods[-1]['duration'] = duration
            except (IndexError, ValueError):
                pass

    total_silence = sum(p.get('duration', 0) for p in silence_periods)

    if not silence_periods:
        print(f"    No extended silence detected - audio is clean")
        shutil.copy(input_path, output_path)
        return output_path, {
            'silence_removed_seconds': 0,
            'silence_periods': 0,
            'original_duration': original_duration
        }

    print(f"    Found {len(silence_periods)} silence period(s) totaling {total_silence:.1f}s - removing...")
    for i, period in enumerate(silence_periods):
        print(f"      [{i+1}] {period.get('start', 0):.1f}s - {period.get('end', 0):.1f}s ({period.get('duration', 0):.1f}s)")

    # Remove silence using silenceremove filter
    remove_cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", (
            f"silenceremove="
            f"start_periods=1:start_duration={min_silence_duration}:start_threshold={silence_threshold_db}dB:"
            f"stop_periods=-1:stop_duration={min_silence_duration}:stop_threshold={silence_threshold_db}dB"
        ),
        "-c:a", "libmp3lame", "-b:a", "96k",
        str(output_path)
    ]

    result = subprocess.run(remove_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    Warning: Silence removal failed, using original audio")
        print(f"    Error: {result.stderr[:200]}")
        shutil.copy(input_path, output_path)
        return output_path, {
            'silence_removed_seconds': 0,
            'silence_periods': 0,
            'original_duration': original_duration,
            'error': result.stderr
        }

    # Get new duration
    new_duration = get_audio_duration(output_path) or 0
    removed_seconds = original_duration - new_duration

    # Safeguard: if we removed more than 50% of the audio, something went wrong
    if new_duration < original_duration * 0.5:
        print(f"    Warning: Silence removal was too aggressive ({original_duration:.1f}s → {new_duration:.1f}s)")
        print(f"    Keeping original audio to avoid losing content")
        output_path.unlink()
        shutil.copy(input_path, output_path)
        return output_path, {
            'silence_removed_seconds': 0,
            'silence_periods': len(silence_periods),
            'original_duration': original_duration,
            'new_duration': original_duration,
            'warning': 'Silence removal too aggressive, kept original'
        }

    print(f"    Removed {removed_seconds:.1f}s of silence ({original_duration:.1f}s → {new_duration:.1f}s)")

    return output_path, {
        'silence_removed_seconds': removed_seconds,
        'silence_periods': len(silence_periods),
        'original_duration': original_duration,
        'new_duration': new_duration,
    }


def normalize_loudness(
    input_path: Path,
    output_path: Path,
    target_lufs: float = TARGET_LUFS,
    target_tp: float = TARGET_TP,
) -> Path:
    """
    Normalize audio to target loudness using EBU R128 two-pass loudnorm filter.

    Args:
        input_path: Input audio file
        output_path: Output normalized audio file
        target_lufs: Target integrated loudness (default -16 LUFS for podcasts)
        target_tp: Target true peak (default -1.5 dB)

    Returns:
        Path to normalized audio
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # First pass: analyze loudness
    analyze_cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", f"loudnorm=I={target_lufs}:TP={target_tp}:LRA=11:print_format=json",
        "-f", "null", "-"
    ]
    result = subprocess.run(analyze_cmd, capture_output=True, text=True)

    # Parse loudness stats from stderr
    stats = None
    try:
        json_start = result.stderr.rfind('{')
        json_end = result.stderr.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            stats_json = result.stderr[json_start:json_end]
            stats = json.loads(stats_json)
    except json.JSONDecodeError:
        pass

    # Second pass: apply normalization with measured values
    if stats:
        normalize_cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", (
                f"loudnorm=I={target_lufs}:TP={target_tp}:LRA=11:"
                f"measured_I={stats.get('input_i', -24)}:"
                f"measured_TP={stats.get('input_tp', -2)}:"
                f"measured_LRA={stats.get('input_lra', 7)}:"
                f"measured_thresh={stats.get('input_thresh', -34)}:"
                f"offset={stats.get('target_offset', 0)}:"
                f"linear=true:print_format=summary"
            ),
            "-ar", "44100", "-ac", "1",
            str(output_path)
        ]
    else:
        # Single-pass fallback
        print("    Warning: Could not parse loudness stats, using single-pass normalization")
        normalize_cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", f"loudnorm=I={target_lufs}:TP={target_tp}:LRA=11",
            "-ar", "44100", "-ac", "1",
            str(output_path)
        ]

    subprocess.run(normalize_cmd, capture_output=True, check=True)
    return output_path


def convert_to_wav(input_path: Path, output_path: Path) -> Path:
    """
    Convert audio to WAV format with consistent sample rate for concatenation.

    Args:
        input_path: Original audio file
        output_path: Where to save the converted audio

    Returns:
        Path to converted audio file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    convert_cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1",
        str(output_path)
    ]
    result = subprocess.run(convert_cmd, capture_output=True)

    if result.returncode != 0:
        raise RuntimeError(f"Failed to convert audio: {input_path}")

    if not output_path.exists():
        raise RuntimeError(f"Output file not created: {output_path}")

    if output_path.stat().st_size < 1000:
        raise RuntimeError(f"Output file suspiciously small ({output_path.stat().st_size} bytes): {output_path}")

    return output_path


def convert_to_mp3(input_path: Path, output_path: Path, bitrate: str = "96k") -> Path:
    """
    Convert audio to MP3 format.

    Args:
        input_path: Original audio file
        output_path: Where to save the converted audio
        bitrate: MP3 bitrate (default 96k)

    Returns:
        Path to converted audio file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    convert_cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c:a", "libmp3lame", "-b:a", bitrate,
        str(output_path)
    ]
    result = subprocess.run(convert_cmd, capture_output=True, check=True)
    return output_path


def get_file_hash(file_path: Path) -> str:
    """Get MD5 hash of a file for cache invalidation."""
    import hashlib
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hasher.update(chunk)
    return hasher.hexdigest()
