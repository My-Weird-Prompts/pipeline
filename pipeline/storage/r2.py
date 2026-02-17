"""
Cloudflare R2 Storage Utility

S3-compatible object storage for podcast episodes and images.
Replaces Cloudinary for media hosting with zero egress fees.
"""

import os
from pathlib import Path
from typing import Optional
import mimetypes

try:
    import boto3
    from botocore.exceptions import ClientError
    from botocore.config import Config
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

# R2 Configuration
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
R2_ENDPOINT = f"https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"

# Bucket names
R2_EPISODES_BUCKET = "mwp-episodes"
R2_IMAGES_BUCKET = "mwd-images"

# Public URL bases (need to be configured in Cloudflare dashboard)
# These should be the public R2.dev URLs or custom domain URLs
R2_EPISODES_PUBLIC_URL = os.environ.get("R2_EPISODES_PUBLIC_URL", "")
R2_IMAGES_PUBLIC_URL = os.environ.get("R2_IMAGES_PUBLIC_URL", "")


def get_r2_client():
    """
    Get a configured boto3 S3 client for Cloudflare R2.

    Returns:
        boto3 S3 client or None if not configured
    """
    if not HAS_BOTO3:
        print("Warning: boto3 not installed - R2 upload unavailable")
        return None

    # Try both naming conventions for the key ID
    access_key_id = os.environ.get("CF_R2_KEY_ID") or os.environ.get("CF_R2-KEY_ID")
    secret_access_key = os.environ.get("CF_R2_ACCESS_KEY")

    if not access_key_id or not secret_access_key:
        print("Warning: R2 credentials not configured")
        print(f"  CF_R2_KEY_ID: {'set' if access_key_id else 'missing'}")
        print(f"  CF_R2_ACCESS_KEY: {'set' if secret_access_key else 'missing'}")
        return None

    # R2 requires specific config for S3 compatibility
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
        region_name='auto',  # R2 uses 'auto' for region
    )


def upload_to_r2(
    file_path: Path,
    bucket: str,
    key: str = None,
    content_type: str = None,
    public: bool = True,
) -> Optional[str]:
    """
    Upload a file to Cloudflare R2.

    Args:
        file_path: Path to the file to upload
        bucket: R2 bucket name (e.g., 'mwp-episodes' or 'mwp-images')
        key: S3 key (path within bucket). Defaults to filename.
        content_type: MIME type. Auto-detected if not provided.
        public: Whether the file should be publicly accessible

    Returns:
        Public URL of the uploaded file, or None if upload failed
    """
    client = get_r2_client()
    if not client:
        return None

    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        return None

    # Use filename as key if not specified
    if key is None:
        key = file_path.name

    # Auto-detect content type
    if content_type is None:
        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            # Default based on extension
            ext = file_path.suffix.lower()
            content_type = {
                '.mp3': 'audio/mpeg',
                '.wav': 'audio/wav',
                '.ogg': 'audio/ogg',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.webp': 'image/webp',
                '.gif': 'image/gif',
            }.get(ext, 'application/octet-stream')

    try:
        print(f"  Uploading to R2: {file_path.name} -> {bucket}/{key}")

        extra_args = {'ContentType': content_type}

        client.upload_file(
            str(file_path),
            bucket,
            key,
            ExtraArgs=extra_args,
        )

        # Construct public URL
        # This depends on how public access is configured in Cloudflare
        if bucket == R2_EPISODES_BUCKET and R2_EPISODES_PUBLIC_URL:
            public_url = f"{R2_EPISODES_PUBLIC_URL.rstrip('/')}/{key}"
        elif bucket == R2_IMAGES_BUCKET and R2_IMAGES_PUBLIC_URL:
            public_url = f"{R2_IMAGES_PUBLIC_URL.rstrip('/')}/{key}"
        else:
            # Fallback to R2 endpoint URL (won't work for public access without config)
            public_url = f"{R2_ENDPOINT}/{bucket}/{key}"

        print(f"  Uploaded: {public_url[:70]}...")
        return public_url

    except ClientError as e:
        print(f"Error: R2 upload failed: {e}")
        return None
    except Exception as e:
        print(f"Error: Unexpected error uploading to R2: {e}")
        return None


def upload_episode_audio(file_path: Path, episode_slug: str) -> Optional[str]:
    """
    Upload podcast episode audio to R2.

    Args:
        file_path: Path to the MP3 file
        episode_slug: Episode identifier for the key

    Returns:
        Public URL of the uploaded audio
    """
    key = f"audio/{episode_slug}.mp3"
    return upload_to_r2(
        file_path,
        bucket=R2_EPISODES_BUCKET,
        key=key,
        content_type='audio/mpeg',
    )


def upload_episode_cover(file_path: Path, episode_slug: str) -> Optional[str]:
    """
    Upload episode cover art to R2.

    Args:
        file_path: Path to the image file
        episode_slug: Episode identifier for the key

    Returns:
        Public URL of the uploaded image
    """
    ext = file_path.suffix.lower()
    key = f"covers/{episode_slug}{ext}"
    return upload_to_r2(
        file_path,
        bucket=R2_IMAGES_BUCKET,
        key=key,
    )


def upload_og_image(file_path: Path, episode_slug: str) -> Optional[str]:
    """
    Upload OpenGraph image to R2.

    Args:
        file_path: Path to the image file
        episode_slug: Episode identifier for the key

    Returns:
        Public URL of the uploaded image
    """
    ext = file_path.suffix.lower()
    key = f"og/{episode_slug}{ext}"
    return upload_to_r2(
        file_path,
        bucket=R2_IMAGES_BUCKET,
        key=key,
    )


def upload_instagram_image(file_path: Path, episode_slug: str) -> Optional[str]:
    """
    Upload Instagram image (4:5 aspect ratio) to R2.

    Args:
        file_path: Path to the image file
        episode_slug: Episode identifier for the key

    Returns:
        Public URL of the uploaded image
    """
    ext = file_path.suffix.lower()
    key = f"instagram/{episode_slug}{ext}"
    return upload_to_r2(
        file_path,
        bucket=R2_IMAGES_BUCKET,
        key=key,
    )


def upload_episode_transcript(
    episode_slug: str,
    prompt_transcript: str = None,
    response_transcript: str = None,
) -> Optional[str]:
    """
    Upload combined transcript to R2 for Podcasting 2.0 support.

    Combines the user's prompt transcript and AI response transcript
    into a single text file for podcast apps to display.

    Args:
        episode_slug: Episode identifier for the key
        prompt_transcript: User's original voice prompt transcript
        response_transcript: AI dialogue/response transcript

    Returns:
        Public URL of the uploaded transcript, or None if no data
    """
    # Need at least one transcript
    if not prompt_transcript and not response_transcript:
        return None

    # Build combined transcript
    parts = []
    if prompt_transcript:
        parts.append(f"[Prompt]\n{prompt_transcript.strip()}")
    if response_transcript:
        parts.append(f"[Response]\n{response_transcript.strip()}")

    transcript_text = "\n\n".join(parts)

    # Upload directly using put_object
    client = get_r2_client()
    if not client:
        return None

    key = f"transcripts/{episode_slug}.txt"

    try:
        print(f"  Uploading transcript to R2: {key}")
        client.put_object(
            Bucket=R2_EPISODES_BUCKET,
            Key=key,
            Body=transcript_text.encode('utf-8'),
            ContentType='text/plain; charset=utf-8',
        )

        public_url = f"{R2_EPISODES_PUBLIC_URL.rstrip('/')}/{key}"
        print(f"  Uploaded: {public_url[:70]}...")
        return public_url

    except Exception as e:
        print(f"Error uploading transcript: {e}")
        return None


def upload_episode_pdf(
    episode_slug: str,
    pdf_bytes: bytes,
) -> Optional[str]:
    """
    Upload episode PDF transcript to R2.

    Args:
        episode_slug: Episode identifier for the key
        pdf_bytes: PDF file content as bytes

    Returns:
        Public URL of the uploaded PDF
    """
    client = get_r2_client()
    if not client:
        return None

    key = f"pdfs/{episode_slug}.pdf"

    try:
        print(f"  Uploading PDF to R2: {key} ({len(pdf_bytes) / 1024:.1f} KB)")
        client.put_object(
            Bucket=R2_EPISODES_BUCKET,
            Key=key,
            Body=pdf_bytes,
            ContentType='application/pdf',
        )

        public_url = f"{R2_EPISODES_PUBLIC_URL.rstrip('/')}/{key}"
        print(f"  Uploaded: {public_url}")
        return public_url

    except Exception as e:
        print(f"Error uploading PDF: {e}")
        return None


def upload_episode_peaks(
    episode_slug: str,
    peaks_json: bytes,
) -> Optional[str]:
    """
    Upload waveform peaks JSON to R2.

    Args:
        episode_slug: Episode identifier for the key
        peaks_json: Peaks data as JSON bytes

    Returns:
        Public URL of the uploaded peaks file
    """
    client = get_r2_client()
    if not client:
        return None

    key = f"peaks/{episode_slug}.json"

    try:
        print(f"  Uploading peaks to R2: {key} ({len(peaks_json) / 1024:.1f} KB)")
        client.put_object(
            Bucket=R2_EPISODES_BUCKET,
            Key=key,
            Body=peaks_json,
            ContentType='application/json',
            CacheControl='public, max-age=31536000, immutable',
        )

        public_url = f"{R2_EPISODES_PUBLIC_URL.rstrip('/')}/{key}"
        print(f"  Uploaded: {public_url}")
        return public_url

    except Exception as e:
        print(f"Error uploading peaks: {e}")
        return None


def list_bucket_contents(bucket: str, prefix: str = "") -> list:
    """
    List contents of an R2 bucket.

    Args:
        bucket: Bucket name
        prefix: Optional prefix to filter results

    Returns:
        List of object keys
    """
    client = get_r2_client()
    if not client:
        return []

    try:
        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        return [obj['Key'] for obj in response.get('Contents', [])]
    except Exception as e:
        print(f"Error listing bucket: {e}")
        return []


def delete_from_r2(bucket: str, key: str) -> bool:
    """
    Delete an object from R2.

    Args:
        bucket: Bucket name
        key: Object key to delete

    Returns:
        True if deleted successfully
    """
    client = get_r2_client()
    if not client:
        return False

    try:
        client.delete_object(Bucket=bucket, Key=key)
        print(f"  Deleted: {bucket}/{key}")
        return True
    except Exception as e:
        print(f"Error deleting from R2: {e}")
        return False


# Quick test function
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print("Testing R2 connection...")
    client = get_r2_client()

    if client:
        print("R2 client created successfully")

        # Try to list buckets
        try:
            response = client.list_buckets()
            print(f"Available buckets: {[b['Name'] for b in response.get('Buckets', [])]}")
        except Exception as e:
            print(f"Could not list buckets: {e}")
    else:
        print("Failed to create R2 client")
