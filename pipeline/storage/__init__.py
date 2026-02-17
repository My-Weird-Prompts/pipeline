"""
Storage module for the MWP podcast pipeline.

Provides access to:
- Cloudflare R2 (primary storage for episodes, images)
- Wasabi (archival backup storage)
"""

from .r2 import (
    get_r2_client,
    upload_to_r2,
    upload_episode_audio,
    upload_episode_cover,
    upload_og_image,
    upload_instagram_image,
    upload_episode_transcript,
    list_bucket_contents,
    delete_from_r2,
    R2_EPISODES_BUCKET,
    R2_IMAGES_BUCKET,
    R2_ENDPOINT,
    R2_EPISODES_PUBLIC_URL,
    R2_IMAGES_PUBLIC_URL,
)

from .wasabi import (
    get_client as get_wasabi_client,
    upload_file as upload_to_wasabi,
    backup_prompt as backup_prompt_to_wasabi,
    WASABI_BUCKET,
    WASABI_REGION,
    WASABI_ENDPOINT,
)

__all__ = [
    # R2
    'get_r2_client',
    'upload_to_r2',
    'upload_episode_audio',
    'upload_episode_cover',
    'upload_og_image',
    'upload_instagram_image',
    'upload_episode_transcript',
    'list_bucket_contents',
    'delete_from_r2',
    'R2_EPISODES_BUCKET',
    'R2_IMAGES_BUCKET',
    'R2_ENDPOINT',
    'R2_EPISODES_PUBLIC_URL',
    'R2_IMAGES_PUBLIC_URL',
    # Wasabi
    'get_wasabi_client',
    'upload_to_wasabi',
    'backup_prompt_to_wasabi',
    'WASABI_BUCKET',
    'WASABI_REGION',
    'WASABI_ENDPOINT',
]
