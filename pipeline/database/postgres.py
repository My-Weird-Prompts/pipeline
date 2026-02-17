"""
PostgreSQL Database Operations

Neon PostgreSQL database for episode metadata and content.
"""

import os
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


@dataclass
class Episode:
    """Episode data structure for database operations."""
    slug: str
    title: str
    description: str
    pub_date: datetime
    hero_image: Optional[str] = None
    podcast_audio_url: Optional[str] = None
    podcast_duration: Optional[str] = None
    tags: Optional[list] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    transcript: Optional[str] = None
    prompt: Optional[str] = None
    prompt_summary: Optional[str] = None
    prompt_transcript: Optional[str] = None
    prompt_redacted: Optional[str] = None
    context: Optional[str] = None
    response: Optional[str] = None
    show_notes: Optional[str] = None
    pipeline_version: Optional[str] = None
    tts_engine: Optional[str] = None
    tts_model: Optional[str] = None
    excerpt: Optional[str] = None
    og_image: Optional[str] = None
    instagram_image: Optional[str] = None
    llm_model: Optional[str] = None
    transcript_url: Optional[str] = None
    pdf_url: Optional[str] = None  # Pre-generated PDF transcript URL
    peaks_url: Optional[str] = None  # Waveform peaks JSON URL for instant rendering
    embedding: Optional[list] = None  # Semantic embedding (768 floats from Gemini)
    season: int = 2  # Season number (1 = episodes 1-175, 2 = episodes 176+)


def get_connection():
    """
    Get a database connection with retry for Neon cold starts.

    Retries once after 2s on OperationalError/InterfaceError (2 total attempts).

    Returns:
        psycopg2 connection or None if not available
    """
    if not HAS_PSYCOPG2:
        print("Warning: psycopg2 not available")
        return None

    postgres_url = os.environ.get("POSTGRES_URL")
    if not postgres_url:
        print("Warning: POSTGRES_URL not set")
        return None

    import time

    last_err = None
    for attempt in range(2):
        try:
            return psycopg2.connect(postgres_url)
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last_err = e
            if attempt == 0:
                print(f"  Database connection retry (Neon cold start?): {e}")
                time.sleep(2)

    print(f"Warning: Database connection failed after retry: {last_err}")
    return None


def episode_exists(slug: str) -> bool:
    """
    Check if an episode with the given slug exists.

    Args:
        slug: Episode slug to check

    Returns:
        True if episode exists, False otherwise
    """
    conn = get_connection()
    if not conn:
        return False

    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM episodes WHERE slug = %s", (slug,))
        exists = cur.fetchone() is not None
        cur.close()
        conn.close()
        return exists
    except Exception as e:
        print(f"Error checking episode existence: {e}")
        return False


def get_next_episode_number() -> int:
    """
    Get the next episode number.

    Returns:
        Next sequential episode number
    """
    conn = get_connection()
    if not conn:
        return 1

    try:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(episode_number), 0) + 1 FROM episodes")
        next_num = cur.fetchone()[0]
        cur.close()
        conn.close()
        return next_num
    except Exception as e:
        print(f"Error getting next episode number: {e}")
        return 1


def insert_episode(episode: Episode) -> bool:
    """
    Insert an episode into the database.

    Args:
        episode: Episode dataclass with all episode data

    Returns:
        True if successful, False otherwise
    """
    conn = get_connection()
    if not conn:
        return False

    try:
        print(f"  Inserting episode into database: {episode.slug}")
        cur = conn.cursor()

        # Check if episode already exists
        cur.execute("SELECT id FROM episodes WHERE slug = %s", (episode.slug,))
        if cur.fetchone():
            print(f"  Episode already exists in database, skipping insert")
            conn.close()
            return True

        # Get the next episode number
        cur.execute("SELECT COALESCE(MAX(episode_number), 0) + 1 FROM episodes")
        next_episode_number = cur.fetchone()[0]
        print(f"  Assigning episode number: {next_episode_number}")

        cur.execute("""
            INSERT INTO episodes (
                slug, title, description, excerpt, pub_date, hero_image,
                podcast_audio_url, podcast_duration, tags, category, subcategory, ai_generated,
                transcript, prompt, prompt_summary, prompt_transcript, prompt_redacted,
                context, response, show_notes, pipeline_version, tts_engine, tts_model, episode_number,
                og_image, instagram_image, llm_model, transcript_url, pdf_url, peaks_url, season
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            episode.slug,
            episode.title,
            episode.description,
            episode.excerpt,
            episode.pub_date,
            episode.hero_image,
            episode.podcast_audio_url,
            episode.podcast_duration,
            episode.tags,
            episode.category,
            episode.subcategory,
            True,  # ai_generated
            episode.transcript,
            episode.prompt,
            episode.prompt_summary,
            episode.prompt_transcript,
            episode.prompt_redacted,
            episode.context,
            episode.response,
            episode.show_notes,
            episode.pipeline_version,
            episode.tts_engine,
            episode.tts_model,
            next_episode_number,
            episode.og_image,
            episode.instagram_image,
            episode.llm_model,
            episode.transcript_url,
            episode.pdf_url,
            episode.peaks_url,
            episode.season,
        ))

        conn.commit()
        cur.close()
        conn.close()
        print(f"  Episode inserted into database successfully")
        return True
    except Exception as e:
        print(f"Warning: Database insert failed: {e}")
        return False


def delete_episode(slug: str) -> bool:
    """
    Delete an episode from the database.

    Args:
        slug: Episode slug to delete

    Returns:
        True if successful, False otherwise
    """
    conn = get_connection()
    if not conn:
        return False

    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM episodes WHERE slug = %s RETURNING id", (slug,))
        deleted = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return deleted is not None
    except Exception as e:
        print(f"Error deleting episode: {e}")
        return False


def get_episode(slug: str) -> Optional[dict]:
    """
    Get an episode by slug.

    Args:
        slug: Episode slug

    Returns:
        Episode dict or None if not found
    """
    conn = get_connection()
    if not conn:
        return None

    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM episodes WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if not row:
            return None

        # Get column names
        columns = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        return dict(zip(columns, row))
    except Exception as e:
        print(f"Error getting episode: {e}")
        return None


def get_latest_episodes(limit: int = 10) -> list:
    """
    Get the latest episodes.

    Args:
        limit: Maximum number of episodes to return

    Returns:
        List of episode dicts
    """
    conn = get_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM episodes ORDER BY pub_date DESC LIMIT %s",
            (limit,)
        )
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"Error getting latest episodes: {e}")
        return []


def get_all_episodes() -> list:
    """
    Get all episodes from the database.

    Returns:
        List of episode dicts
    """
    conn = get_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM episodes ORDER BY episode_number ASC")
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"Error getting all episodes: {e}")
        return []


def get_episodes_needing_metadata(
    check_tags: bool = True,
    check_category: bool = True,
    check_embedding: bool = True,
    limit: int = None,
    offset: int = 0,
) -> list:
    """
    Get episodes that need metadata updates (tags, category, or embedding).

    Args:
        check_tags: Include episodes missing tags
        check_category: Include episodes missing category
        check_embedding: Include episodes missing embedding
        limit: Maximum number to return
        offset: Skip first N results

    Returns:
        List of episode dicts needing updates
    """
    conn = get_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor()

        # Build WHERE clause for missing metadata
        # Tags column is a PostgreSQL array, use array operators
        conditions = []
        if check_tags:
            conditions.append("""(
                tags IS NULL
                OR cardinality(tags) = 0
                OR 'ai-generated' = ANY(tags)
                OR 'podcast' = ANY(tags)
                OR 'technology' = ANY(tags)
                OR 'ArtificialIntelligence' = ANY(tags)
                OR 'MachineLearning' = ANY(tags)
                OR 'Data' = ANY(tags)
                OR 'GPU' = ANY(tags)
                OR 'Python' = ANY(tags)
                OR 'Programming' = ANY(tags)
                OR 'Api' = ANY(tags)
                OR 'Workflow' = ANY(tags)
                OR 'Voice' = ANY(tags)
                OR 'Prompt' = ANY(tags)
                OR 'Cloud' = ANY(tags)
                OR 'LLM' = ANY(tags)
            )""")
        if check_category:
            conditions.append("category IS NULL")
        if check_embedding:
            conditions.append("embedding IS NULL")

        if not conditions:
            return []

        where_clause = " OR ".join(conditions)

        query = f"""
            SELECT * FROM episodes
            WHERE {where_clause}
            ORDER BY episode_number ASC
        """

        if limit:
            query += f" LIMIT {limit}"
        if offset:
            query += f" OFFSET {offset}"

        cur.execute(query)
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"Error getting episodes needing metadata: {e}")
        return []


def update_episode_metadata(
    slug: str,
    tags: list = None,
    category: str = None,
    subcategory: str = None,
    embedding: list = None,
) -> bool:
    """
    Update episode metadata (tags, category, subcategory, embedding).

    Only updates fields that are provided (not None).

    Args:
        slug: Episode slug
        tags: List of tag IDs
        category: Category ID
        subcategory: Subcategory ID
        embedding: Embedding vector (list of floats)

    Returns:
        True if successful
    """
    conn = get_connection()
    if not conn:
        return False

    try:
        cur = conn.cursor()

        # Build SET clause dynamically
        updates = []
        params = []

        if tags is not None:
            # Tags column is PostgreSQL array, not JSON
            updates.append("tags = %s")
            params.append(tags)  # psycopg2 handles list->array conversion

        if category is not None:
            updates.append("category = %s")
            params.append(category)

        if subcategory is not None:
            updates.append("subcategory = %s")
            params.append(subcategory)

        if embedding is not None:
            # pgvector: cast list to vector string format '[1,2,3,...]'
            vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
            updates.append("embedding = %s::vector")
            params.append(vec_str)

        if not updates:
            return True  # Nothing to update

        # Add updated_at timestamp
        updates.append("updated_at = NOW()")

        set_clause = ", ".join(updates)
        params.append(slug)

        cur.execute(
            f"UPDATE episodes SET {set_clause} WHERE slug = %s",
            params
        )

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating episode metadata: {e}")
        return False


def get_episode_count() -> int:
    """
    Get total number of episodes in database.

    Returns:
        Episode count
    """
    conn = get_connection()
    if not conn:
        return 0

    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM episodes")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        print(f"Error getting episode count: {e}")
        return 0


def get_categories_taxonomy() -> dict:
    """
    Get the full category taxonomy from the database.

    Returns the same structure as categories.json:
    {"categories": [{"id": ..., "name": ..., "description": ..., "color": ..., "subcategories": [...]}]}

    Returns:
        Dict with categories list, or None if unavailable
    """
    conn = get_connection()
    if not conn:
        return None

    try:
        cur = conn.cursor()

        # Fetch categories ordered by sort_order
        cur.execute("SELECT id, name, description, color FROM categories ORDER BY sort_order ASC")
        cat_rows = cur.fetchall()

        # Fetch all subcategories ordered by sort_order
        cur.execute("SELECT id, category_id, name, description FROM subcategories ORDER BY sort_order ASC")
        sub_rows = cur.fetchall()

        cur.close()
        conn.close()

        # Group subcategories by category_id
        subs_by_cat = {}
        for sub_id, cat_id, sub_name, sub_desc in sub_rows:
            subs_by_cat.setdefault(cat_id, []).append({
                "id": sub_id,
                "name": sub_name,
                "description": sub_desc,
            })

        categories = []
        for cat_id, cat_name, cat_desc, cat_color in cat_rows:
            categories.append({
                "id": cat_id,
                "name": cat_name,
                "description": cat_desc,
                "color": cat_color or "#6b7280",
                "subcategories": subs_by_cat.get(cat_id, []),
            })

        return {"categories": categories}
    except Exception as e:
        print(f"Error getting categories taxonomy: {e}")
        return None


def get_episodes_with_embeddings() -> list[tuple[str, list]]:
    """
    Get all episodes with their embeddings for similarity search.

    Returns:
        List of (slug, embedding) tuples
    """
    conn = get_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT slug, embedding::text FROM episodes WHERE embedding IS NOT NULL"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        results = []
        for slug, embedding_str in rows:
            if embedding_str:
                # pgvector returns '[1,2,3,...]' string format
                embedding = [float(x) for x in embedding_str.strip("[]").split(",")]
                results.append((slug, embedding))

        return results
    except Exception as e:
        print(f"Error getting episodes with embeddings: {e}")
        return []


def find_similar_episodes_by_vector(
    query_embedding: list[float],
    top_k: int = 5,
    threshold: float = 0.5,
    exclude_slug: str = None,
) -> list[dict]:
    """
    Find similar episodes using pgvector cosine similarity search.

    Uses HNSW index for fast approximate nearest neighbor search.
    This replaces client-side cosine similarity computation.

    Args:
        query_embedding: Query embedding vector (768 dimensions)
        top_k: Maximum number of results
        threshold: Minimum cosine similarity (0-1)
        exclude_slug: Optional slug to exclude from results

    Returns:
        List of dicts with slug, title, episode_number, description, similarity_score
    """
    conn = get_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor()

        # pgvector cosine distance: <=> returns distance (0=identical, 2=opposite)
        # Convert to similarity: 1 - distance
        vec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        if exclude_slug:
            cur.execute("""
                SELECT slug, title, episode_number, description,
                       1 - (embedding <=> %s::vector) as similarity
                FROM episodes
                WHERE embedding IS NOT NULL
                  AND slug <> %s
                  AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (vec_str, exclude_slug, vec_str, threshold, vec_str, top_k))
        else:
            cur.execute("""
                SELECT slug, title, episode_number, description,
                       1 - (embedding <=> %s::vector) as similarity
                FROM episodes
                WHERE embedding IS NOT NULL
                  AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (vec_str, vec_str, threshold, vec_str, top_k))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        return [
            {
                "slug": row[0],
                "title": row[1],
                "episode_number": row[2],
                "description": (row[3] or "")[:200],
                "similarity_score": round(float(row[4]), 3),
            }
            for row in rows
        ]
    except Exception as e:
        print(f"Error finding similar episodes: {e}")
        return []
