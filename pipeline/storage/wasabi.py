"""
Wasabi S3-Compatible Storage

Archival backup storage for podcast episodes.
Used as a secondary backup alongside R2.
"""

import os
from pathlib import Path
from typing import Optional

try:
    import boto3
    from botocore.exceptions import ClientError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

# Wasabi Configuration
WASABI_ENDPOINT = "https://s3.eu-central-2.wasabisys.com"
WASABI_REGION = "eu-central-2"
WASABI_BUCKET = os.environ.get("WASABI_BUCKET", "myweirdprompts")


def get_client():
    """
    Get a configured boto3 S3 client for Wasabi.

    Returns:
        boto3 S3 client or None if not configured
    """
    if not HAS_BOTO3:
        print("Warning: boto3 not installed - Wasabi upload unavailable")
        return None

    access_key = os.environ.get("WASABI_ACCESS_KEY")
    secret_key = os.environ.get("WASABI_SECRET_KEY")

    if not access_key or not secret_key:
        print("Warning: Wasabi credentials not configured")
        return None

    return boto3.client(
        's3',
        endpoint_url=WASABI_ENDPOINT,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=WASABI_REGION,
    )


def upload_file(
    file_path: Path,
    key: str,
    content_type: str = None,
    bucket: str = None,
) -> Optional[str]:
    """
    Upload a file to Wasabi S3.

    Args:
        file_path: Path to the file to upload
        key: S3 key (path within bucket)
        content_type: MIME type (auto-detected if not provided)
        bucket: Bucket name (defaults to WASABI_BUCKET)

    Returns:
        S3 URL of the uploaded file, or None if upload failed
    """
    client = get_client()
    if not client:
        return None

    bucket = bucket or WASABI_BUCKET

    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        return None

    # Auto-detect content type
    if content_type is None:
        ext = file_path.suffix.lower()
        content_type = {
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.json': 'application/json',
            '.txt': 'text/plain',
        }.get(ext, 'application/octet-stream')

    try:
        print(f"  Uploading to Wasabi: {file_path.name} -> {bucket}/{key}")
        client.upload_file(
            str(file_path),
            bucket,
            key,
            ExtraArgs={'ContentType': content_type}
        )

        url = f"{WASABI_ENDPOINT}/{bucket}/{key}"
        print(f"  Uploaded: {url[:70]}...")
        return url

    except ClientError as e:
        print(f"Warning: Wasabi upload failed: {e}")
        return None
    except Exception as e:
        print(f"Warning: Unexpected error uploading to Wasabi: {e}")
        return None


def upload_episode(episode_dir: Path, episode_path: Path) -> Optional[str]:
    """
    Upload a podcast episode MP3 to Wasabi for archival backup.

    Flat structure: episodes/<filename>.mp3

    Args:
        episode_dir: Directory containing episode files (used for naming)
        episode_path: Path to the final MP3 file

    Returns:
        S3 URL of the uploaded episode, or None if upload failed
    """
    key = f"episodes/{episode_path.name}"
    return upload_file(episode_path, key, content_type='audio/mpeg')


def upload_cover(episode_slug: str, cover_path: Path) -> Optional[str]:
    """
    Upload episode cover art to Wasabi for archival backup.

    Args:
        episode_slug: Episode identifier
        cover_path: Path to the cover image

    Returns:
        S3 URL of the uploaded cover, or None if upload failed
    """
    ext = cover_path.suffix.lower()
    key = f"covers/{episode_slug}{ext}"
    return upload_file(cover_path, key)


def backup_prompt(prompt_path: Path, episode_slug: str) -> Optional[str]:
    """
    Backup a prompt audio file to Wasabi with mmdd/episode-slug organization.

    Args:
        prompt_path: Path to the prompt audio file
        episode_slug: The episode slug from metadata generation

    Returns:
        S3 URL of the backed up prompt, or None if backup failed
    """
    from datetime import datetime

    # Get current date for folder structure (mmdd format)
    date_folder = datetime.now().strftime("%m%d")

    # Use episode slug for filename
    key = f"prompts/{date_folder}/{episode_slug}.mp3"
    return upload_file(prompt_path, key, content_type='audio/mpeg')


def list_objects(prefix: str = "", bucket: str = None) -> list:
    """
    List objects in the Wasabi bucket.

    Args:
        prefix: Optional prefix to filter results
        bucket: Bucket name (defaults to WASABI_BUCKET)

    Returns:
        List of object keys
    """
    client = get_client()
    if not client:
        return []

    bucket = bucket or WASABI_BUCKET

    try:
        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        return [obj['Key'] for obj in response.get('Contents', [])]
    except Exception as e:
        print(f"Error listing Wasabi bucket: {e}")
        return []
