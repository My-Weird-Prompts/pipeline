"""
Core generation module for the MWP podcast pipeline.

Contains the main generation logic:
- Transcription (audio → text)
- Episode planning (transcript → detailed outline)
- Script generation (prompt + context + plan → diarized script)
- Script review (script → edited/improved script)
- Metadata generation (script → title, description, etc.)
- Categorization (episode → category/subcategory)
- Tagging (episode → dynamic tags from taxonomy)
- Embeddings (episode → semantic embedding vector)
- Script parsing (diarized script → segments)
"""

# Transcription
from .transcription import transcribe_audio

# Episode Planning
from .episode_planning import EpisodePlan, run_episode_planning_agent

# Script generation
from .script_generation import (
    generate_script,
    transcribe_and_generate_script,
    run_planning_agent,
)

# Script review (Pass 1: fact-checking with grounding)
from .script_review import run_script_review_agent

# Script polish (Pass 2: flow, verbal tics, sign-off)
from .script_polish import run_script_polish_agent

# Metadata
from .metadata import generate_episode_metadata, categorize_episode

# Tagging
from .tagging import tag_episode, normalize_tag, load_tags_registry, save_tags_registry

# Embeddings
from .embeddings import (
    generate_episode_embedding,
    generate_query_embedding,
    cosine_similarity,
    find_similar_episodes,
    embedding_to_vector_string,
)

# Script parsing
from .script_parser import (
    parse_diarized_script,
    chunk_long_text,
    get_word_count,
    get_character_count,
    estimate_tts_cost,
)

__all__ = [
    # Transcription
    'transcribe_audio',

    # Episode Planning
    'EpisodePlan',
    'run_episode_planning_agent',

    # Script generation
    'generate_script',
    'transcribe_and_generate_script',
    'run_planning_agent',

    # Script review & polish
    'run_script_review_agent',
    'run_script_polish_agent',

    # Metadata
    'generate_episode_metadata',
    'categorize_episode',

    # Tagging
    'tag_episode',
    'normalize_tag',
    'load_tags_registry',
    'save_tags_registry',

    # Embeddings
    'generate_episode_embedding',
    'generate_query_embedding',
    'cosine_similarity',
    'find_similar_episodes',
    'embedding_to_vector_string',

    # Script parsing
    'parse_diarized_script',
    'chunk_long_text',
    'get_word_count',
    'get_character_count',
    'estimate_tts_cost',
]
