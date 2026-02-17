#!/usr/bin/env python3
"""
Episode Memory System for My Weird Prompts

This module manages the podcast's episode history, enabling:
1. Cross-episode references ("As we discussed in episode 230...")
2. Topic continuity and callbacks
3. Avoiding repetition of recently covered topics
4. Semantic similarity search for finding related episodes (RAG)

The episode index is fetched from the RSS feed and can be cached in R2.
Episodes are numbered in reverse chronological order (newest = highest number).

Semantic Search:
- Uses Gemini text-embedding-004 for 768-dimensional embeddings
- Embeddings stored in PostgreSQL alongside episode data
- Cosine similarity search finds contextually relevant episodes

Storage Strategy:
- Episode index stored in R2 (not Modal volume) to keep Modal clean
- Index refreshed periodically (not every run)
- Lightweight JSON format for fast retrieval
"""

import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional
from pathlib import Path

# RSS feed URL
RSS_FEED_URL = "https://www.myweirdprompts.com/feed.xml"

# R2 configuration for episode index storage
R2_INDEX_URL = os.environ.get("R2_EPISODES_PUBLIC_URL", "").rstrip("/")
EPISODE_INDEX_FILENAME = "episode-index.json"


@dataclass
class EpisodeInfo:
    """Minimal episode information for context injection."""
    episode_number: int
    title: str
    slug: str
    pub_date: str
    description: str  # Short description (first 200 chars)
    topics: list[str]  # Extracted topic keywords


@dataclass
class EpisodeIndex:
    """Complete episode index for the podcast."""
    total_episodes: int
    last_updated: str
    show_description: str
    episodes: list[dict]  # List of EpisodeInfo as dicts


def parse_rss_feed(rss_content: str) -> EpisodeIndex:
    """
    Parse RSS feed XML and extract episode information.

    Episodes are numbered in reverse chronological order:
    - Most recent episode = highest number (total count)
    - Oldest episode = 1

    Args:
        rss_content: Raw XML content from RSS feed

    Returns:
        EpisodeIndex with all episodes
    """
    root = ET.fromstring(rss_content)
    channel = root.find("channel")

    # Get show description
    show_desc_elem = channel.find("description")
    show_description = ""
    if show_desc_elem is not None and show_desc_elem.text:
        show_description = show_desc_elem.text.strip()
        # Remove CDATA wrapper if present
        if show_description.startswith("<![CDATA["):
            show_description = show_description[9:-3]

    # Parse all episodes
    items = channel.findall("item")
    episodes = []

    for item in items:
        title_elem = item.find("title")
        title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Untitled"

        # Get link/slug
        link_elem = item.find("link")
        link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
        slug = link.split("/")[-2] if link and link.endswith("/") else link.split("/")[-1]

        # Get publication date
        pub_date_elem = item.find("pubDate")
        pub_date = pub_date_elem.text.strip() if pub_date_elem is not None and pub_date_elem.text else ""

        # Get description (truncate for memory efficiency)
        desc_elem = item.find("description")
        description = ""
        if desc_elem is not None and desc_elem.text:
            description = desc_elem.text.strip()
            if description.startswith("<![CDATA["):
                description = description[9:-3]
            # Truncate to first 300 chars for memory efficiency
            if len(description) > 300:
                description = description[:297] + "..."

        # Extract topic keywords from title
        topics = extract_topics(title)

        episodes.append({
            "title": title,
            "slug": slug,
            "pub_date": pub_date,
            "description": description,
            "topics": topics,
        })

    # Number episodes (most recent = highest number)
    total = len(episodes)
    for i, ep in enumerate(episodes):
        ep["episode_number"] = total - i

    return EpisodeIndex(
        total_episodes=total,
        last_updated=datetime.utcnow().isoformat(),
        show_description=show_description,
        episodes=episodes,
    )


def extract_topics(title: str) -> list[str]:
    """
    Extract topic keywords from episode title.

    Simple keyword extraction - can be enhanced with NLP if needed.
    """
    # Common words to filter out
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
        "be", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "shall", "can", "need",
        "dare", "ought", "used", "my", "weird", "prompts", "episode", "how",
        "why", "what", "when", "where", "who", "which", "this", "that",
        "these", "those", "its", "it", "we", "they", "you", "i", "he", "she",
    }

    # Extract words, filter stop words, keep meaningful ones
    words = title.lower().replace(":", " ").replace("-", " ").replace("'", "").split()
    topics = [w for w in words if w not in stop_words and len(w) > 2]

    return topics[:5]  # Limit to 5 topics per episode


def fetch_episode_index(force_refresh: bool = False) -> EpisodeIndex:
    """
    Fetch episode index, using cached version if available.

    Strategy:
    1. Try to load from R2 cache first (fast)
    2. If not found or force_refresh, fetch from RSS and update cache

    Args:
        force_refresh: Force refresh from RSS feed

    Returns:
        EpisodeIndex with all episodes
    """
    # Try cached version first (unless forcing refresh)
    if not force_refresh and R2_INDEX_URL:
        try:
            cache_url = f"{R2_INDEX_URL}/{EPISODE_INDEX_FILENAME}"
            response = requests.get(cache_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"  Loaded episode index from cache: {data['total_episodes']} episodes")
                return EpisodeIndex(**data)
        except Exception as e:
            print(f"  Cache miss or error: {e}")

    # Fetch fresh from RSS
    print(f"  Fetching episode index from RSS feed...")
    response = requests.get(RSS_FEED_URL, timeout=30)
    response.raise_for_status()

    index = parse_rss_feed(response.text)
    print(f"  Parsed {index.total_episodes} episodes from RSS feed")

    return index


def upload_episode_index(index: EpisodeIndex) -> Optional[str]:
    """
    Upload episode index to R2 for caching.

    Args:
        index: EpisodeIndex to upload

    Returns:
        URL of uploaded index, or None if upload failed
    """
    try:
        import boto3
        from botocore.config import Config

        # R2 configuration
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        access_key = os.environ.get("CF_R2_KEY_ID")
        secret_key = os.environ.get("CF_R2_ACCESS_KEY")
        bucket_name = os.environ.get("R2_EPISODES_BUCKET", "mwp-episodes")

        if not all([account_id, access_key, secret_key]):
            print("  R2 credentials not configured, skipping cache upload")
            return None

        # Create S3 client for R2
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
        )

        # Convert to JSON
        index_json = json.dumps(asdict(index), indent=2)

        # Upload
        s3.put_object(
            Bucket=bucket_name,
            Key=EPISODE_INDEX_FILENAME,
            Body=index_json.encode("utf-8"),
            ContentType="application/json",
        )

        url = f"{R2_INDEX_URL}/{EPISODE_INDEX_FILENAME}"
        print(f"  Uploaded episode index to R2: {url}")
        return url

    except Exception as e:
        print(f"  Failed to upload episode index: {e}")
        return None


def find_related_episodes(
    index: EpisodeIndex,
    transcript: str,
    max_results: int = 5,
) -> list[dict]:
    """
    Find episodes related to the current topic.

    Simple keyword matching - can be enhanced with embeddings later.

    Args:
        index: EpisodeIndex to search
        transcript: User's prompt transcript
        max_results: Maximum number of related episodes to return

    Returns:
        List of related episodes with relevance scores
    """
    # Extract keywords from transcript
    transcript_topics = set(extract_topics(transcript))

    if not transcript_topics:
        return []

    # Score each episode by topic overlap
    scored_episodes = []
    for ep in index.episodes:
        ep_topics = set(ep.get("topics", []))
        overlap = transcript_topics & ep_topics
        if overlap:
            scored_episodes.append({
                "episode_number": ep["episode_number"],
                "title": ep["title"],
                "slug": ep["slug"],
                "relevance_score": len(overlap),
                "matching_topics": list(overlap),
            })

    # Sort by relevance and return top results
    scored_episodes.sort(key=lambda x: x["relevance_score"], reverse=True)
    return scored_episodes[:max_results]


def find_semantically_related_episodes(
    transcript: str,
    top_k: int = 3,
    similarity_threshold: float = 0.5,
) -> list[dict]:
    """
    Find episodes semantically similar to the transcript using pgvector.

    Uses Gemini embeddings + pgvector HNSW index for fast similarity search
    directly in PostgreSQL, avoiding client-side cosine computation.

    Args:
        transcript: User's prompt transcript
        top_k: Maximum number of similar episodes to return
        similarity_threshold: Minimum cosine similarity score (0-1)

    Returns:
        List of episode dicts with:
            - episode_number: int
            - title: str
            - slug: str
            - description: str (truncated)
            - similarity_score: float
    """
    try:
        from ..core.embeddings import generate_query_embedding
        from ..database.postgres import find_similar_episodes_by_vector

        print(f"  Finding semantically related episodes...")

        # Generate query embedding from transcript
        query_embedding = generate_query_embedding(transcript)
        if not query_embedding:
            print("  Warning: Failed to generate query embedding")
            return []

        # Use pgvector HNSW index for fast similarity search
        results = find_similar_episodes_by_vector(
            query_embedding,
            top_k=top_k,
            threshold=similarity_threshold,
        )

        if not results:
            print("  No episodes met similarity threshold")
            return []

        for r in results:
            print(f"    Episode {r['episode_number']}: \"{r['title']}\" (score: {r['similarity_score']:.3f})")

        return results

    except Exception as e:
        print(f"  Warning: Semantic search failed: {e}")
        return []


def build_episode_context(
    index: EpisodeIndex,
    related_episodes: list[dict] = None,
) -> str:
    """
    Build episode context string for injection into script generation prompt.

    This provides the script generator with:
    1. Current episode number
    2. Semantically related past episodes (if found)
    3. Guidelines for episode references

    Args:
        index: EpisodeIndex with all episodes
        related_episodes: List of semantically related episodes from embedding search

    Returns:
        Formatted context string for prompt injection
    """
    next_episode_number = index.total_episodes + 1

    context_parts = [
        "## EPISODE CONTEXT",
        "",
        f"**This will be Episode {next_episode_number} of My Weird Prompts.**",
        "",
        f"The podcast has {index.total_episodes} published episodes available at:",
        "- Website: https://myweirdprompts.com",
        "- RSS Feed: https://www.myweirdprompts.com/feed.xml",
        "",
    ]

    # Add related episodes if we found any
    if related_episodes:
        context_parts.extend([
            "### Related Past Episodes",
            "",
            "The following episodes are semantically related to this prompt and may be",
            "referenced naturally in the conversation if relevant:",
            "",
        ])
        for ep in related_episodes:
            context_parts.append(
                f"- **Episode {ep['episode_number']}: \"{ep['title']}\"**"
            )
            if ep.get('description'):
                # Truncate description for context
                desc = ep['description'][:150]
                if len(ep['description']) > 150:
                    desc += "..."
                context_parts.append(f"  {desc}")
            context_parts.append("")

        context_parts.extend([
            "### Episode Reference Guidelines:",
            "",
            "You MAY reference these related episodes naturally when relevant, such as:",
            "- \"We actually covered something similar in episode X...\"",
            "- \"If you enjoyed this, check out episode X where we discussed...\"",
            "",
            "Keep references brief and natural - don't force them. Only reference",
            "an episode if it genuinely adds value to the current discussion.",
            "",
            "For topics NOT listed above, direct listeners to search the website:",
            "- \"Check out myweirdprompts.com to search our archive\"",
            "",
        ])
    else:
        # No related episodes found - use simplified context
        context_parts.extend([
            "### Episode Reference Policy:",
            "",
            "No closely related past episodes were found for this topic.",
            "",
            "If a topic might have been covered before, simply say:",
            "- \"We may have talked about something similar before - check out",
            "  myweirdprompts.com to search our archive\"",
            "",
        ])

    return "\n".join(context_parts)


def get_episode_memory_for_generation(
    transcript: str = None,
    use_semantic_search: bool = True,
    top_k: int = 3,
    similarity_threshold: float = 0.5,
) -> tuple[str, int, list[dict]]:
    """
    Main entry point for getting episode memory context for script generation.

    Performs semantic search using Gemini embeddings to find past episodes
    that are contextually relevant to the current prompt transcript.

    Args:
        transcript: User's prompt transcript for semantic search
        use_semantic_search: Whether to use embedding-based semantic search
        top_k: Maximum number of similar episodes to return
        similarity_threshold: Minimum cosine similarity score (0-1)

    Returns:
        Tuple of:
            - context_string: Formatted context for script generation prompt
            - next_episode_number: The episode number for this new episode
            - related_episodes: List of related episode dicts (for reference)
    """
    try:
        index = fetch_episode_index()
        next_episode = index.total_episodes + 1

        # Find semantically related episodes if transcript provided
        related_episodes = []
        if use_semantic_search and transcript:
            print("  Running semantic episode search...")
            related_episodes = find_semantically_related_episodes(
                transcript,
                top_k=top_k,
                similarity_threshold=similarity_threshold
            )
            if related_episodes:
                print(f"  Found {len(related_episodes)} related episodes")
            else:
                print("  No related episodes found above threshold")

        context = build_episode_context(index, related_episodes)
        return context, next_episode, related_episodes

    except Exception as e:
        print(f"  WARNING: Failed to load episode memory: {e}")
        # Return minimal context on failure - just direct to website
        fallback_context = """## EPISODE CONTEXT

**Episode Archive:** https://myweirdprompts.com

No semantically related episodes could be retrieved.
If a topic might have been covered before, direct listeners to search the website archive.
"""
        return fallback_context, 0, []


# CLI for testing and manual index refresh
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--refresh":
        print("Refreshing episode index from RSS feed...")
        index = fetch_episode_index(force_refresh=True)
        print(f"Total episodes: {index.total_episodes}")
        print(f"Show description: {index.show_description[:200]}...")
        print(f"\nMost recent episodes:")
        for ep in index.episodes[:5]:
            print(f"  {ep['episode_number']}: {ep['title']}")

        # Upload to R2
        url = upload_episode_index(index)
        if url:
            print(f"\nIndex cached at: {url}")

    elif len(sys.argv) > 1 and sys.argv[1] == "--search":
        # Semantic search test
        if len(sys.argv) < 3:
            print("Usage: python episode_memory.py --search \"your query here\"")
            sys.exit(1)

        query = " ".join(sys.argv[2:])
        print(f"Searching for episodes related to: \"{query}\"")
        print("-" * 60)

        results = find_semantically_related_episodes(query, top_k=5, similarity_threshold=0.4)

        if results:
            print(f"\nFound {len(results)} related episodes:\n")
            for r in results:
                print(f"Episode {r['episode_number']}: {r['title']}")
                print(f"  Similarity score: {r['similarity_score']}")
                if r.get('description'):
                    print(f"  {r['description'][:100]}...")
                print()
        else:
            print("\nNo related episodes found above threshold.")

    elif len(sys.argv) > 1 and sys.argv[1] == "--test-context":
        # Test full context generation
        if len(sys.argv) < 3:
            print("Usage: python episode_memory.py --test-context \"your prompt transcript\"")
            sys.exit(1)

        transcript = " ".join(sys.argv[2:])
        print(f"Testing context generation for: \"{transcript[:50]}...\"")
        print("-" * 60)

        context, episode_num, related = get_episode_memory_for_generation(transcript)

        print(f"\nNext episode number: {episode_num}")
        print(f"Related episodes found: {len(related)}")
        print("\n--- Generated Context ---\n")
        print(context)

    else:
        print("Usage: python episode_memory.py <command>")
        print()
        print("Commands:")
        print("  --refresh                        Fetch RSS feed and update R2 cache")
        print("  --search \"query\"                 Test semantic episode search")
        print("  --test-context \"transcript\"      Test full context generation")
