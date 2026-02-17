"""
Embeddings module for the MWP podcast pipeline.

Generates semantic embeddings for episodes using Google Gemini's text-embedding-004 model.
Embeddings enable semantic similarity search for related episode discovery.
"""

import os
from typing import Optional

from ..config.models import get_gemini_api_key
from ..llm.gemini import get_gemini_client


# Gemini embedding model (text-embedding-004 deprecated Jan 2026)
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768  # Default for gemini-embedding-001


def generate_embedding(
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
    title: str = None,
) -> Optional[list[float]]:
    """
    Generate an embedding vector for the given text using Gemini.

    Args:
        text: The text to embed (e.g., episode title + description)
        task_type: The embedding task type:
            - RETRIEVAL_DOCUMENT: For documents to be retrieved (default)
            - RETRIEVAL_QUERY: For search queries
            - SEMANTIC_SIMILARITY: For comparing text similarity
            - CLASSIFICATION: For text classification
        title: Optional title for the document (improves embedding quality)

    Returns:
        List of floats (768 dimensions) or None on error
    """
    api_key = get_gemini_api_key()
    if not api_key:
        print("  Warning: GEMINI_API_KEY not set, skipping embedding generation")
        return None

    if not text or not text.strip():
        print("  Warning: Empty text provided for embedding")
        return None

    try:
        client = get_gemini_client(api_key)

        # Combine title and text if title provided
        content = text
        if title:
            content = f"{title}\n\n{text}"

        # Truncate if too long (Gemini has token limits)
        # Approximate: 4 chars per token, 2048 token limit for embeddings
        max_chars = 8000
        if len(content) > max_chars:
            content = content[:max_chars]

        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=content,
            config={
                "task_type": task_type,
                "output_dimensionality": EMBEDDING_DIMENSIONS,
            }
        )

        # Extract embedding vector
        if result and result.embeddings:
            embedding = result.embeddings[0].values
            return list(embedding)

        print("  Warning: No embedding returned from Gemini")
        return None

    except Exception as e:
        print(f"  Warning: Embedding generation failed: {e}")
        return None


def generate_episode_embedding(
    title: str,
    description: str,
    transcript: str = None,
) -> Optional[list[float]]:
    """
    Generate an embedding for an episode.

    Combines title, description, and optionally transcript excerpt
    for a comprehensive semantic representation.

    Args:
        title: Episode title
        description: Episode description/summary
        transcript: Optional transcript (first portion used)

    Returns:
        List of floats (768 dimensions) or None on error
    """
    print("Generating episode embedding...")

    # Build content for embedding
    # Prioritize title and description, add transcript excerpt if space allows
    content_parts = [description]

    if transcript:
        # Take first ~2000 chars of transcript for additional context
        transcript_excerpt = transcript[:2000]
        content_parts.append(transcript_excerpt)

    content = "\n\n".join(content_parts)

    embedding = generate_embedding(
        text=content,
        task_type="RETRIEVAL_DOCUMENT",
        title=title,
    )

    if embedding:
        print(f"  Embedding generated: {len(embedding)} dimensions")
    else:
        print("  Warning: Failed to generate embedding")

    return embedding


def generate_query_embedding(query: str) -> Optional[list[float]]:
    """
    Generate an embedding for a search query.

    Uses RETRIEVAL_QUERY task type for optimal search performance.

    Args:
        query: Search query text

    Returns:
        List of floats (768 dimensions) or None on error
    """
    return generate_embedding(
        text=query,
        task_type="RETRIEVAL_QUERY",
    )


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Calculate cosine similarity between two vectors.

    Args:
        vec_a: First vector
        vec_b: Second vector

    Returns:
        Similarity score between -1 and 1 (1 = identical)
    """
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    magnitude_a = sum(a * a for a in vec_a) ** 0.5
    magnitude_b = sum(b * b for b in vec_b) ** 0.5

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


def find_similar_episodes(
    query_embedding: list[float],
    episode_embeddings: list[tuple[str, list[float]]],
    top_k: int = 5,
    threshold: float = 0.5,
) -> list[tuple[str, float]]:
    """
    Find episodes most similar to a query embedding.

    Args:
        query_embedding: The query embedding vector
        episode_embeddings: List of (episode_slug, embedding) tuples
        top_k: Maximum number of results to return
        threshold: Minimum similarity score (0-1)

    Returns:
        List of (episode_slug, similarity_score) tuples, sorted by score descending
    """
    results = []

    for slug, embedding in episode_embeddings:
        if embedding:
            score = cosine_similarity(query_embedding, embedding)
            if score >= threshold:
                results.append((slug, score))

    # Sort by similarity score descending
    results.sort(key=lambda x: x[1], reverse=True)

    return results[:top_k]


def embedding_to_vector_string(embedding: list[float]) -> str:
    """
    Convert embedding to pgvector string format for database storage.

    Args:
        embedding: List of floats

    Returns:
        pgvector string format '[1,2,3,...]'
    """
    return "[" + ",".join(str(x) for x in embedding) + "]"
