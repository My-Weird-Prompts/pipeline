"""
Database module for the MWP podcast pipeline.

Provides access to PostgreSQL (Neon) database for episode metadata.
"""

from .postgres import (
    # Data model
    Episode,
    # Connection
    get_connection,
    # Query operations
    episode_exists,
    get_next_episode_number,
    get_episode,
    get_latest_episodes,
    get_all_episodes,
    get_episodes_needing_metadata,
    get_episode_count,
    get_categories_taxonomy,
    # Write operations
    insert_episode,
    delete_episode,
    update_episode_metadata,
)

__all__ = [
    # Data model
    'Episode',
    # Connection
    'get_connection',
    # Query operations
    'episode_exists',
    'get_next_episode_number',
    'get_episode',
    'get_latest_episodes',
    'get_all_episodes',
    'get_episodes_needing_metadata',
    'get_episode_count',
    'get_categories_taxonomy',
    # Write operations
    'insert_episode',
    'delete_episode',
    'update_episode_metadata',
]
