#!/usr/bin/env python3
"""
Upload pre-generated audio snippets to Cloudflare R2.

These are stored at ai-files.myweirdprompts.com/show-elements/

Usage:
    source .venv/bin/activate
    python pipeline/scripts/upload_snippets_to_r2.py
"""

import os
from pathlib import Path

import boto3
from botocore.config import Config
from dotenv import load_dotenv

# Load environment
load_dotenv(".env.production")

# R2 Configuration
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
R2_ENDPOINT = f"https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"

# The bucket for ai-files.myweirdprompts.com
# This is where voice samples are stored, so we'll add show-elements here too
AI_FILES_BUCKET = "mwp-public-files-other"

# Public URL base
AI_FILES_PUBLIC_URL = "https://ai-files.myweirdprompts.com"

# Show elements directory
SHOW_ELEMENTS_DIR = Path(__file__).parent.parent / "show-elements" / "mixed"

# Files to upload
SNIPPET_FILES = [
    "disclaimer.mp3",
    "llm-info-gemini-flash-3.mp3",
    "tts-info-chatterbox.mp3",
]


def get_r2_client():
    """Get a configured boto3 S3 client for Cloudflare R2."""
    access_key_id = os.environ.get("CF_R2_KEY_ID")
    secret_access_key = os.environ.get("CF_R2_ACCESS_KEY")

    if not access_key_id or not secret_access_key:
        raise ValueError("R2 credentials not configured (CF_R2_KEY_ID, CF_R2_ACCESS_KEY)")

    config = Config(
        signature_version='s3v4',
        retries={'max_attempts': 3, 'mode': 'standard'}
    )

    return boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        config=config,
        region_name='auto',
    )


def upload_snippet(client, file_path: Path, key: str) -> str:
    """Upload a file to R2 and return the public URL."""
    print(f"  Uploading: {file_path.name} -> {key}")

    client.upload_file(
        str(file_path),
        AI_FILES_BUCKET,
        key,
        ExtraArgs={'ContentType': 'audio/mpeg'}
    )

    public_url = f"{AI_FILES_PUBLIC_URL}/{key}"
    print(f"  URL: {public_url}")
    return public_url


def main():
    """Upload all audio snippets to R2."""
    print("=" * 60)
    print("Uploading Audio Snippets to Cloudflare R2")
    print("=" * 60)
    print()
    print(f"Bucket: {AI_FILES_BUCKET}")
    print(f"Public URL: {AI_FILES_PUBLIC_URL}")
    print()

    client = get_r2_client()

    uploaded = []
    for filename in SNIPPET_FILES:
        file_path = SHOW_ELEMENTS_DIR / filename
        if not file_path.exists():
            print(f"  WARNING: File not found: {file_path}")
            continue

        key = f"show-elements/{filename}"
        url = upload_snippet(client, file_path, key)
        uploaded.append((filename, url))
        print()

    print("=" * 60)
    print("Uploaded snippets:")
    for filename, url in uploaded:
        print(f"  {filename}: {url}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    exit(main())
