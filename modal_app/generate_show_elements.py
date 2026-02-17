"""
Generate show elements using Chatterbox on Modal.

Uses Daniel's voice for announcements.

Usage:
    modal run modal_app/generate_show_elements.py
"""

import os
import tempfile
from pathlib import Path

import modal

app = modal.App("mwp-show-elements")

# GPU image with Chatterbox
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "torch>=2.0.0",
        "torchaudio>=2.0.0",
        "chatterbox-tts>=0.1.6",
        "boto3>=1.34.0",
        "requests>=2.31.0",
    )
)

secrets = modal.Secret.from_name("mwp-secrets")

# Daniel's voice sample URL
DANIEL_VOICE_URL = "https://ai-files.myweirdprompts.com/voices/daniel/daniel-1min.wav"

# Show elements to generate
SHOW_ELEMENTS = {
    "prompt-intro-daniel": "Here's Daniel's prompt!",
    "llm-info-gemini-flash-3": "This episode was generated using Gemini Flash three.",
    "tts-info-chatterbox": "Text to speech was provided by Chatterbox.",
}


@app.function(
    image=image,
    secrets=[secrets],
    gpu="T4",  # T4 sufficient for Chatterbox
    timeout=600,
)
def generate_elements():
    """Generate all show elements using Daniel's voice."""
    import torch
    import torchaudio
    import requests
    import subprocess
    import boto3
    from huggingface_hub import login
    from chatterbox.tts import ChatterboxTTS

    # Authenticate with Hugging Face
    hf_token = os.environ.get("HF_TOKEN")
    if hf_token:
        login(token=hf_token)
        print("Authenticated with Hugging Face")

    # Load Chatterbox
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Chatterbox on {device}...")
    model = ChatterboxTTS.from_pretrained(device=device)
    print("Model loaded!")

    # Download Daniel's voice sample
    print(f"Downloading voice sample from {DANIEL_VOICE_URL}...")
    response = requests.get(DANIEL_VOICE_URL)
    response.raise_for_status()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(response.content)
        voice_path = f.name
    print(f"Voice sample saved to {voice_path}")

    # Set up S3 client for R2
    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['CLOUDFLARE_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["CF_R2_KEY_ID"],
        aws_secret_access_key=os.environ["CF_R2_ACCESS_KEY"],
    )
    bucket = "myweirdprompts-episodes"

    results = {}

    for name, text in SHOW_ELEMENTS.items():
        print(f"\nGenerating: {name}")
        print(f"  Text: {text}")

        # Generate audio
        wav = model.generate(
            text,
            audio_prompt_path=voice_path,
            exaggeration=0.3,  # Slightly less exaggerated for announcements
            cfg_weight=0.5,
            temperature=0.6,
        )

        # Save as WAV
        wav_path = f"/tmp/{name}.wav"
        torchaudio.save(wav_path, wav.cpu(), model.sr)

        # Convert to MP3
        mp3_path = f"/tmp/{name}.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", wav_path,
            "-codec:a", "libmp3lame", "-b:a", "96k",
            mp3_path
        ], check=True, capture_output=True)

        # Get duration
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            mp3_path
        ], capture_output=True, text=True)
        duration = float(result.stdout.strip()) if result.stdout.strip() else 0

        print(f"  Duration: {duration:.2f}s")

        # Upload to R2
        r2_key = f"show-elements/{name}.mp3"
        with open(mp3_path, "rb") as f:
            s3.put_object(
                Bucket=bucket,
                Key=r2_key,
                Body=f.read(),
                ContentType="audio/mpeg",
            )

        public_url = f"https://ai-files.myweirdprompts.com/{r2_key}"
        print(f"  Uploaded to: {public_url}")

        results[name] = {
            "url": public_url,
            "duration": duration,
        }

        # Clean up temp files
        os.unlink(wav_path)
        os.unlink(mp3_path)

    # Clean up voice sample
    os.unlink(voice_path)

    print("\n" + "=" * 60)
    print("GENERATED SHOW ELEMENTS:")
    for name, info in results.items():
        print(f"  {name}: {info['url']} ({info['duration']:.2f}s)")
    print("=" * 60)

    return results


@app.local_entrypoint()
def main():
    """Run the show element generator."""
    print("Starting show element generation on Modal...")
    results = generate_elements.remote()
    print("\nDone! Generated elements:")
    for name, info in results.items():
        print(f"  {name}: {info['url']}")
