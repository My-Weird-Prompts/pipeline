"""
Tagging module for the MWP podcast pipeline.

Generates and validates tags for episodes using LLM with a controlled taxonomy.
Tags are dynamically managed - new tags can be added but are validated against
existing tags to avoid duplicates and synonyms.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config.constants import TAGS_FILE
from ..config.models import METADATA_MODEL
from ..llm import call_gemini, extract_json_from_response

# Blacklist of generic tags that should never be used
# These provide no value - every episode is AI-generated, every episode is a podcast,
# and topics like "machine learning" or "data" are too broad for an AI podcast
BLACKLISTED_TAGS = {
    # Meta/format tags (every episode is these)
    "ai-generated", "podcast", "technology", "discussion", "conversation",
    "episode", "show", "audio", "talk", "chat", "ai", "tech",
    # Overly broad tech tags (not specific enough for an AI podcast)
    "artificialintelligence", "artificial-intelligence", "machinelearning", "machine-learning",
    "data", "gpu", "cloud", "python", "programming", "api", "workflow", "voice", "prompt",
    "gpt", "chatgpt", "llm", "model", "models", "neural-network", "neural-networks",
    "deep-learning", "deeplearning", "ml", "nlp", "natural-language-processing",
    # Single-word too-generic terms
    "learning", "training", "inference", "generation", "processing",
}


def normalize_tag(tag: str) -> str:
    """
    Normalize a tag to standard form.

    - Lowercase
    - Replace spaces with hyphens
    - Remove special characters except hyphens
    - Strip leading/trailing hyphens
    - Collapse multiple hyphens

    Examples:
        "AI Models" -> "ai-models"
        "Text to Speech" -> "text-to-speech"
        "LLM's & ML" -> "llms-ml"
    """
    # Lowercase
    tag = tag.lower().strip()
    # Replace spaces and underscores with hyphens
    tag = re.sub(r'[\s_]+', '-', tag)
    # Remove special characters except hyphens and alphanumerics
    tag = re.sub(r'[^a-z0-9-]', '', tag)
    # Collapse multiple hyphens
    tag = re.sub(r'-+', '-', tag)
    # Strip leading/trailing hyphens
    tag = tag.strip('-')
    return tag


def load_tags_registry(tags_file: Path = None) -> dict:
    """
    Load the tags registry from tags.json.

    Creates an empty registry if file doesn't exist.

    Args:
        tags_file: Optional path to tags.json (defaults to TAGS_FILE)

    Returns:
        Dict with registry structure
    """
    tags_path = tags_file or TAGS_FILE

    if not tags_path.exists():
        return {
            "version": "1.0.0",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "tags": []
        }

    with open(tags_path, 'r') as f:
        return json.load(f)


def save_tags_registry(registry: dict, tags_file: Path = None) -> bool:
    """
    Save the tags registry back to tags.json.

    Updates last_updated timestamp.

    Args:
        registry: The tags registry dict
        tags_file: Optional path to tags.json (defaults to TAGS_FILE)

    Returns:
        True if saved successfully
    """
    tags_path = tags_file or TAGS_FILE

    registry["last_updated"] = datetime.now(timezone.utc).isoformat()

    # Ensure directory exists
    tags_path.parent.mkdir(parents=True, exist_ok=True)

    with open(tags_path, 'w') as f:
        json.dump(registry, f, indent=2)

    return True


def find_tag_match(proposed_tag: str, registry: dict) -> tuple[Optional[str], str]:
    """
    Check if proposed tag matches an existing tag.

    Checks:
    1. Exact ID match
    2. Synonym match

    Args:
        proposed_tag: The normalized proposed tag
        registry: The tags registry

    Returns:
        (matched_tag_id, match_type) or (None, "no_match")
    """
    normalized = normalize_tag(proposed_tag)

    for tag in registry.get("tags", []):
        # Exact ID match
        if tag["id"] == normalized:
            return (tag["id"], "exact")

        # Check synonyms
        synonyms = [normalize_tag(s) for s in tag.get("synonyms", [])]
        if normalized in synonyms:
            return (tag["id"], "synonym")

    return (None, "no_match")


def check_semantic_duplicates(
    proposed_tag: str,
    existing_tags: list[dict],
) -> Optional[str]:
    """
    Use LLM to check if proposed tag is semantically similar to existing tags.

    Args:
        proposed_tag: The proposed tag (normalized)
        existing_tags: List of existing tag dicts from registry

    Returns:
        Matched tag ID if duplicate found, None otherwise
    """
    if not existing_tags:
        return None

    # Build existing tags list for prompt
    existing_list = [f"- {t['id']}: {t['name']}" for t in existing_tags[:50]]  # Limit context
    existing_str = "\n".join(existing_list)

    prompt = f"""You are checking if a proposed tag is a semantic duplicate of existing tags.

Proposed tag: "{proposed_tag}"

Existing tags:
{existing_str}

Is the proposed tag semantically equivalent to (meaning the same thing as) any existing tag?
Consider: synonyms, abbreviations, alternative phrasings, singular/plural forms.

Return JSON:
{{
  "is_duplicate": true/false,
  "matched_tag_id": "tag-id" or null,
  "reason": "brief explanation"
}}"""

    try:
        result_text = call_gemini(
            prompt=prompt,
            model=METADATA_MODEL,
            max_tokens=512,  # Gemini 2.5 uses thinking tokens that count against this
            temperature=0.1,
        )

        result = extract_json_from_response(result_text)
        if result and result.get("is_duplicate") and result.get("matched_tag_id"):
            return result["matched_tag_id"]

    except Exception as e:
        print(f"  Warning: Semantic duplicate check failed: {e}")

    return None


def add_tag_to_registry(
    tag_id: str,
    tag_name: str,
    registry: dict,
    synonyms: list[str] = None
) -> dict:
    """
    Add a new tag to the registry.

    Args:
        tag_id: Normalized tag ID
        tag_name: Human-readable name
        registry: The tags registry
        synonyms: Optional list of synonyms

    Returns:
        The new tag entry
    """
    new_tag = {
        "id": tag_id,
        "name": tag_name,
        "synonyms": synonyms or [],
        "usage_count": 0
    }

    registry["tags"].append(new_tag)
    return new_tag


def increment_tag_usage(tag_id: str, registry: dict) -> None:
    """
    Increment the usage count for a tag.

    Args:
        tag_id: The tag ID to increment
        registry: The tags registry
    """
    for tag in registry.get("tags", []):
        if tag["id"] == tag_id:
            tag["usage_count"] = tag.get("usage_count", 0) + 1
            break


def generate_episode_tags(
    title: str,
    description: str,
    registry: dict
) -> list[str]:
    """
    Generate 3 tags for an episode using Gemini.

    Steps:
    1. Call LLM with title + description + existing tags context
    2. Receive 3 proposed tags
    3. For each proposed tag:
       a. Normalize it
       b. Check for exact/synonym match -> use existing tag
       c. Check for semantic duplicate -> use existing tag
       d. If truly new -> add to registry
    4. Increment usage_count for each used tag
    5. Return list of validated tag IDs

    Args:
        title: Episode title
        description: Episode description
        registry: The tags registry

    Returns:
        List of 3 tag IDs
    """
    # Build existing tags context
    existing_tags = registry.get("tags", [])
    if existing_tags:
        # Sort by usage count (most popular first)
        sorted_tags = sorted(existing_tags, key=lambda t: t.get("usage_count", 0), reverse=True)
        existing_list = [f"- {t['id']}" for t in sorted_tags[:30]]  # Limit context
        existing_str = "\n".join(existing_list)
    else:
        existing_str = "(no existing tags yet)"

    prompt = f"""You are a podcast content tagger for "My Weird Prompts", a podcast about AI, technology, networking, and related topics.

Given an episode's title and description, generate exactly 3 relevant tags that capture the main topics.

EXISTING TAGS (prefer these if they fit well):
{existing_str}

RULES:
1. Generate exactly 3 tags
2. Tags should be specific but not too narrow
3. PREFER existing tags if they fit the content well
4. For new tags: use lowercase, hyphenated format (e.g., "model-collapse", "prompt-injection")
5. Avoid overly generic tags like "ai", "technology", "podcast", "discussion"
6. Focus on the specific TOPIC being discussed, not the format
7. Each tag should represent a distinct topic (don't repeat similar concepts)

Episode Title: {title}
Episode Description: {description}

Return JSON:
{{
  "tags": ["tag-one", "tag-two", "tag-three"],
  "reasoning": "Brief explanation of why these tags were chosen"
}}"""

    try:
        result_text = call_gemini(
            prompt=prompt,
            model=METADATA_MODEL,
            max_tokens=2048,  # Gemini 3 flash uses many thinking tokens (~500+)
            temperature=0.3,
        )

        result = extract_json_from_response(result_text)
        if not result or "tags" not in result:
            print("  Warning: Failed to extract tags from LLM response")
            return []

        proposed_tags = result.get("tags", [])[:3]  # Limit to 3

    except Exception as e:
        print(f"  Warning: Tag generation failed: {e}")
        return []

    # Validate and process each proposed tag
    validated_tags = []
    for proposed in proposed_tags:
        normalized = normalize_tag(proposed)
        if not normalized:
            continue

        # Skip blacklisted generic tags
        if normalized in BLACKLISTED_TAGS:
            print(f"    Tag '{normalized}' -> SKIPPED (blacklisted generic tag)")
            continue

        # Check for exact/synonym match
        matched_id, match_type = find_tag_match(normalized, registry)

        if matched_id:
            # Use existing tag
            validated_tags.append(matched_id)
            increment_tag_usage(matched_id, registry)
            print(f"    Tag '{normalized}' -> existing '{matched_id}' ({match_type})")
        else:
            # Check for semantic duplicate
            semantic_match = check_semantic_duplicates(normalized, existing_tags)

            if semantic_match:
                # Use semantically similar existing tag
                validated_tags.append(semantic_match)
                increment_tag_usage(semantic_match, registry)
                print(f"    Tag '{normalized}' -> existing '{semantic_match}' (semantic)")
            else:
                # Add as new tag
                # Create a human-readable name from the normalized form
                display_name = normalized.replace('-', ' ').title()
                add_tag_to_registry(normalized, display_name, registry)
                increment_tag_usage(normalized, registry)
                validated_tags.append(normalized)
                print(f"    Tag '{normalized}' -> NEW tag added")

    return validated_tags


def tag_episode(
    title: str,
    description: str,
    tags_file: Path = None,
    save_registry: bool = True
) -> list[str]:
    """
    Main entry point for tagging an episode.

    Parallel to categorize_episode() - same interface pattern.

    Args:
        title: Episode title
        description: Episode description
        tags_file: Optional path to tags.json
        save_registry: Whether to save registry updates (default True)

    Returns:
        List of 3 tag IDs
    """
    print("Generating episode tags...")

    # Load registry
    registry = load_tags_registry(tags_file)

    # Generate and validate tags
    tags = generate_episode_tags(title, description, registry)

    # If we got fewer than 3 tags, that's fine - don't pad with generic fallbacks
    # Generic tags like "ai-generated", "podcast", "technology" provide no value
    # Better to have 1-2 good tags than 3 generic ones

    # Save updated registry
    if save_registry and tags:
        save_tags_registry(registry, tags_file)

    print(f"  Tags: {tags}")
    return tags[:3]  # Ensure max 3
