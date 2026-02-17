#!/usr/bin/env python3
"""
Pre-compute voice conditionals for Chatterbox TTS.

This script generates cached voice embeddings (.pt files) that can be loaded
instantly at runtime, eliminating the need to process voice samples for every
TTS generation.

Usage:
    # Run locally with GPU
    python pipeline/scripts/precompute_voice_conditionals.py

    # Upload to R2 after generation
    python pipeline/scripts/precompute_voice_conditionals.py --upload

The generated .pt files should be uploaded to R2 at:
    https://ai-files.myweirdprompts.com/voices/{voice_name}/{voice_name}_conds.pt
"""

import argparse
import os
import sys
from pathlib import Path

# Add pipeline to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def download_voice_sample(voice_name: str, url: str, output_dir: Path) -> Path:
    """Download voice sample WAV file."""
    import requests

    output_path = output_dir / f"{voice_name}.wav"
    if output_path.exists():
        print(f"  Using cached: {output_path}")
        return output_path

    print(f"  Downloading {url}...")
    response = requests.get(url)
    response.raise_for_status()
    output_path.write_bytes(response.content)
    print(f"  Saved to: {output_path}")
    return output_path


def precompute_conditionals(voice_name: str, wav_path: Path, output_dir: Path) -> Path:
    """Pre-compute and save voice conditionals."""
    import torch
    from chatterbox.tts import ChatterboxTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\nLoading Chatterbox on {device}...")
    model = ChatterboxTTS.from_pretrained(device=device)

    print(f"Computing conditionals for {voice_name}...")
    model.prepare_conditionals(str(wav_path), exaggeration=0.5)

    # Save the conditionals
    output_path = output_dir / f"{voice_name}_conds.pt"
    model.conds.save(output_path)
    print(f"Saved conditionals to: {output_path}")

    # Verify we can load it back
    from chatterbox.tts import Conditionals
    loaded = Conditionals.load(output_path, map_location=device)
    print(f"Verified: conditionals can be loaded back")

    return output_path


def upload_to_r2(local_path: Path, voice_name: str):
    """Upload conditionals file to R2."""
    import boto3

    # R2 credentials from environment
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    access_key = os.environ.get("CF_R2_KEY_ID")
    secret_key = os.environ.get("CF_R2_ACCESS_KEY")

    if not all([account_id, access_key, secret_key]):
        print("ERROR: Missing R2 credentials. Set CLOUDFLARE_ACCOUNT_ID, CF_R2_KEY_ID, CF_R2_ACCESS_KEY")
        return None

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    bucket = "ai-files"
    key = f"voices/{voice_name}/{voice_name}_conds.pt"

    print(f"Uploading to R2: {key}...")
    s3.upload_file(str(local_path), bucket, key)

    public_url = f"https://ai-files.myweirdprompts.com/{key}"
    print(f"Uploaded: {public_url}")
    return public_url


def main():
    parser = argparse.ArgumentParser(description="Pre-compute voice conditionals for Chatterbox")
    parser.add_argument("--upload", action="store_true", help="Upload to R2 after generation")
    parser.add_argument("--output-dir", type=Path, default=Path("./voice_conditionals"),
                        help="Output directory for conditionals")
    args = parser.parse_args()

    # Voice samples (same as in chatterbox.py)
    voices = {
        "corn": "https://ai-files.myweirdprompts.com/voices/corn/corn-1min.wav",
        "herman": "https://ai-files.myweirdprompts.com/voices/herman/herman-1min.wav",
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    for voice_name, voice_url in voices.items():
        print(f"\n{'='*60}")
        print(f"Processing voice: {voice_name}")
        print(f"{'='*60}")

        # Download voice sample
        wav_path = download_voice_sample(voice_name, voice_url, args.output_dir)

        # Pre-compute conditionals
        conds_path = precompute_conditionals(voice_name, wav_path, args.output_dir)
        results[voice_name] = conds_path

        # Upload if requested
        if args.upload:
            upload_to_r2(conds_path, voice_name)

    print(f"\n{'='*60}")
    print("COMPLETE")
    print(f"{'='*60}")
    print("\nGenerated conditionals:")
    for voice_name, path in results.items():
        size_kb = path.stat().st_size / 1024
        print(f"  {voice_name}: {path} ({size_kb:.1f} KB)")

    if not args.upload:
        print("\nTo upload to R2, run with --upload flag")
        print("Or manually upload to: https://ai-files.myweirdprompts.com/voices/{voice}/{voice}_conds.pt")


if __name__ == "__main__":
    main()
