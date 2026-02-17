#!/usr/bin/env python3
"""
Generate pre-recorded audio snippets for the podcast.

This script uses Fal AI (Chatterbox) to generate short audio clips
that are reused across episodes:
- AI disclaimer
- LLM info (Gemini Flash 3)
- TTS info (Chatterbox)

Usage:
    source .venv/bin/activate
    python pipeline/scripts/generate_snippets.py
"""

import os
import subprocess
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load environment
load_dotenv(".env.production")

# Fal AI client
import fal_client

# Larry's voice sample URL
LARRY_VOICE_URL = "https://ai-files.myweirdprompts.com/voices/larry/clip-Larry-2025_12_08.wav"

# Output directory
OUTPUT_DIR = Path(__file__).parent.parent / "show-elements" / "mixed"

# Snippets to generate
SNIPPETS = {
    "disclaimer": "This episode was generated using artificial intelligence. Please verify facts.",
    "llm-info-gemini-flash-3": "This episode was generated using Gemini Flash 3.",
    "tts-info-chatterbox": "Text to speech engine was Chatterbox.",
}


def synthesize_with_fal(text: str, output_path: Path) -> Path:
    """
    Synthesize speech using Chatterbox on Fal AI.

    Args:
        text: Text to synthesize
        output_path: Where to save the MP3 file

    Returns:
        Path to the generated audio file
    """
    print(f"  Generating: {text[:50]}...")

    # Run Fal AI prediction
    result = fal_client.subscribe(
        "fal-ai/chatterbox/text-to-speech",
        arguments={
            "text": text,
            "audio_url": LARRY_VOICE_URL,
            "exaggeration": 0.5,
            "cfg": 0.5,
            "temperature": 0.7,
        }
    )

    # Extract audio URL from result
    audio_url = result.get("audio", {}).get("url")
    if not audio_url:
        raise RuntimeError(f"Unexpected Fal AI response format: {result}")

    # Download the output
    response = requests.get(audio_url)
    response.raise_for_status()

    # Fal AI returns WAV, convert to MP3
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(response.content)
        tmp_path = Path(tmp.name)

    # Convert to MP3
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(tmp_path),
        "-c:a", "libmp3lame", "-b:a", "96k",
        str(output_path)
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    tmp_path.unlink()

    print(f"  Saved: {output_path.name}")
    return output_path


def main():
    """Generate all audio snippets."""
    print("=" * 60)
    print("Generating Audio Snippets with Fal AI (Chatterbox)")
    print("=" * 60)
    print()

    # Check FAL_KEY
    fal_key = os.environ.get("FAL_KEY")
    if not fal_key:
        print("ERROR: FAL_KEY not set in environment")
        return 1

    print(f"Using Larry voice: {LARRY_VOICE_URL}")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    generated = []
    for name, text in SNIPPETS.items():
        output_path = OUTPUT_DIR / f"{name}.mp3"
        print(f"[{name}]")
        synthesize_with_fal(text, output_path)
        generated.append(output_path)
        print()

    print("=" * 60)
    print("Generated snippets:")
    for path in generated:
        print(f"  - {path}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    exit(main())
