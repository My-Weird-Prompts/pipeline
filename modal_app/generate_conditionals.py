"""
One-time script to generate and upload voice conditionals to R2.

Run with:
    modal run modal_app/generate_conditionals.py
"""

import modal

app = modal.App("mwp-generate-conditionals")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("torch>=2.0.0", "torchaudio>=2.0.0")
    .pip_install("chatterbox-tts>=0.1.6")
    .pip_install("boto3>=1.34.0", "requests>=2.31.0")
)

secrets = modal.Secret.from_name("mwp-secrets")


@app.function(image=image, secrets=[secrets], gpu="T4", timeout=600)
def generate_and_upload_conditionals():
    """Generate voice conditionals and upload to R2."""
    import os
    import requests
    import torch
    import boto3
    from pathlib import Path
    from chatterbox.tts import ChatterboxTTS

    voices = {
        "corn": "https://ai-files.myweirdprompts.com/voices/corn/corn-1min.wav",
        "herman": "https://ai-files.myweirdprompts.com/voices/herman/herman-1min.wav",
    }

    # Set up R2 client
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    access_key = os.environ.get("CF_R2_KEY_ID")
    secret_key = os.environ.get("CF_R2_ACCESS_KEY")

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    # Load model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Chatterbox on {device}...")
    model = ChatterboxTTS.from_pretrained(device=device)
    print("Model loaded!")

    results = {}
    work_dir = Path("/tmp/voice_conditionals")
    work_dir.mkdir(exist_ok=True)

    for voice_name, voice_url in voices.items():
        print(f"\n{'='*60}")
        print(f"Processing: {voice_name}")
        print(f"{'='*60}")

        # Download voice sample
        print(f"  Downloading {voice_url}...")
        response = requests.get(voice_url)
        response.raise_for_status()
        wav_path = work_dir / f"{voice_name}.wav"
        wav_path.write_bytes(response.content)
        print(f"  Downloaded: {len(response.content)} bytes")

        # Generate conditionals
        print(f"  Computing conditionals...")
        model.prepare_conditionals(str(wav_path), exaggeration=0.5)

        # Save locally
        conds_path = work_dir / f"{voice_name}_conds.pt"
        model.conds.save(conds_path)
        size_kb = conds_path.stat().st_size / 1024
        print(f"  Saved: {conds_path} ({size_kb:.1f} KB)")

        # Upload to R2
        r2_key = f"voices/{voice_name}/{voice_name}_conds.pt"
        bucket = "mwp-public-files-other"  # ai-files.myweirdprompts.com
        print(f"  Uploading to R2: {bucket}/{r2_key}...")
        s3.upload_file(str(conds_path), bucket, r2_key)

        public_url = f"https://ai-files.myweirdprompts.com/{r2_key}"
        print(f"  Uploaded: {public_url}")
        results[voice_name] = public_url

    print(f"\n{'='*60}")
    print("COMPLETE!")
    print(f"{'='*60}")
    for voice, url in results.items():
        print(f"  {voice}: {url}")

    return results


@app.local_entrypoint()
def main():
    results = generate_and_upload_conditionals.remote()
    print("\nResults:", results)
