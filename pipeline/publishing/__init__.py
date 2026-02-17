"""
Publishing module for the MWP podcast pipeline.

Handles:
- Storage (R2, Wasabi uploads)
- Database persistence
- Notifications (email, webhooks)
- Cover art generation
"""

# Storage (flattened location)
from ..storage import (
    # R2
    get_r2_client,
    upload_to_r2,
    upload_episode_audio,
    upload_episode_cover,
    upload_og_image,
    upload_instagram_image,
    upload_episode_transcript,
    R2_EPISODES_BUCKET,
    R2_IMAGES_BUCKET,
    R2_EPISODES_PUBLIC_URL,
    # Wasabi
    get_wasabi_client,
    upload_to_wasabi,
    WASABI_BUCKET,
)

# Database (flattened location)
from ..database import (
    Episode,
    get_connection,
    episode_exists,
    get_next_episode_number,
    insert_episode,
    delete_episode,
    get_episode,
    get_latest_episodes,
    update_episode_metadata,
)

# Webhooks (publication notifications)
try:
    from ..webhooks.publication_webhook import (
        notify_publication,
        notify_publication_async,
    )
except ImportError:
    notify_publication = None
    notify_publication_async = None

# Cover art and OG image generation
from ..generators.generate_og_image import (
    generate_og_image,
    generate_instagram_image,
)

# Legacy exports for backward compatibility
# These will be removed after recording_app.py is updated
try:
    from ..generators.generate_episode import (
        publish_episode,
        generate_cover_art,
        insert_episode_to_database,
        upload_episode_to_wasabi,
    )
except ImportError:
    publish_episode = None
    generate_cover_art = None
    insert_episode_to_database = None
    upload_episode_to_wasabi = None

__all__ = [
    # Storage - R2
    'get_r2_client',
    'upload_to_r2',
    'upload_episode_audio',
    'upload_episode_cover',
    'upload_og_image',
    'upload_instagram_image',
    'upload_episode_transcript',
    'R2_EPISODES_BUCKET',
    'R2_IMAGES_BUCKET',
    'R2_EPISODES_PUBLIC_URL',
    # Storage - Wasabi
    'get_wasabi_client',
    'upload_to_wasabi',
    'WASABI_BUCKET',
    # Database
    'Episode',
    'get_connection',
    'episode_exists',
    'get_next_episode_number',
    'insert_episode',
    'delete_episode',
    'get_episode',
    'get_latest_episodes',
    'update_episode_metadata',
    # Webhooks
    'notify_publication',
    'notify_publication_async',
    # Image generation
    'generate_og_image',
    'generate_instagram_image',
    # Legacy (backward compat)
    'publish_episode',
    'generate_cover_art',
    'insert_episode_to_database',
    'upload_episode_to_wasabi',
]
