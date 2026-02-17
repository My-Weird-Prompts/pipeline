#!/usr/bin/env python3
"""
Pre-normalize static show elements (intro, outro, disclaimer) to podcast standard loudness.

Run this once to create normalized versions of show elements.
This avoids redundant normalization on every episode generation.

Usage:
    python normalize_show_elements.py
"""

import subprocess
import json
from pathlib import Path

# Target loudness (EBU R128 podcast standard)
TARGET_LUFS = -16
TARGET_TP = -1.5

PIPELINE_ROOT = Path(__file__).parent.parent
SHOW_ELEMENTS_DIR = PIPELINE_ROOT / "show-elements" / "mixed"


def get_loudness_stats(audio_path: Path) -> dict | None:
    """Analyze audio file loudness using FFmpeg loudnorm filter."""
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-af", f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA=11:print_format=json",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    try:
        json_start = result.stderr.rfind('{')
        json_end = result.stderr.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            return json.loads(result.stderr[json_start:json_end])
    except json.JSONDecodeError:
        pass
    return None


def normalize_audio(input_path: Path, output_path: Path, stats: dict = None) -> bool:
    """
    Normalize audio to target loudness using two-pass loudnorm.

    Args:
        input_path: Source audio file
        output_path: Destination for normalized audio
        stats: Pre-analyzed loudness stats (optional, will analyze if not provided)

    Returns:
        True if successful, False otherwise
    """
    if stats is None:
        stats = get_loudness_stats(input_path)

    if stats:
        # Two-pass normalization with measured values
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", (
                f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA=11:"
                f"measured_I={stats.get('input_i', -24)}:"
                f"measured_TP={stats.get('input_tp', -2)}:"
                f"measured_LRA={stats.get('input_lra', 7)}:"
                f"measured_thresh={stats.get('input_thresh', -34)}:"
                f"offset={stats.get('target_offset', 0)}:"
                f"linear=true"
            ),
            "-c:a", "libmp3lame", "-b:a", "96k", "-ar", "44100",
            str(output_path)
        ]
    else:
        # Single-pass fallback
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA=11",
            "-c:a", "libmp3lame", "-b:a", "96k", "-ar", "44100",
            str(output_path)
        ]

    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def main():
    """Pre-normalize all show elements."""
    elements = [
        "mixed-intro.mp3",
        "mixed-outro.mp3",
        "disclaimer.mp3",
        "prompt-intro-larry.mp3",
        "transition-whoosh.mp3",
        "llm-info-gemini-flash-3.mp3",
        "tts-info-chatterbox.mp3",
    ]

    # Create normalized directory
    normalized_dir = SHOW_ELEMENTS_DIR / "normalized"
    normalized_dir.mkdir(exist_ok=True)

    print(f"Pre-normalizing show elements to {TARGET_LUFS} LUFS...")
    print(f"Output directory: {normalized_dir}\n")

    for element in elements:
        source = SHOW_ELEMENTS_DIR / element
        if not source.exists():
            print(f"  [SKIP] {element} - not found")
            continue

        output = normalized_dir / element

        # Analyze loudness
        print(f"  Analyzing {element}...")
        stats = get_loudness_stats(source)

        if stats:
            input_lufs = float(stats.get('input_i', -99))
            print(f"    Current loudness: {input_lufs:.1f} LUFS")

            # Skip if already at target (within 0.5 LUFS)
            if abs(input_lufs - TARGET_LUFS) < 0.5:
                print(f"    Already at target - copying as-is")
                import shutil
                shutil.copy(source, output)
                continue

        # Normalize
        print(f"    Normalizing to {TARGET_LUFS} LUFS...")
        if normalize_audio(source, output, stats):
            # Verify
            new_stats = get_loudness_stats(output)
            if new_stats:
                new_lufs = float(new_stats.get('input_i', -99))
                print(f"    Done: {new_lufs:.1f} LUFS -> {output.name}")
            else:
                print(f"    Done -> {output.name}")
        else:
            print(f"    [ERROR] Failed to normalize {element}")

    print(f"\nPre-normalized elements saved to: {normalized_dir}")
    print("The episode generator will automatically use these versions.")


if __name__ == "__main__":
    main()
