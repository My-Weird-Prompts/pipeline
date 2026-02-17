"""
Metadata generation module for the MWP podcast pipeline.

Generates episode titles, descriptions, slugs, and categorization.
"""

import json
import re
from pathlib import Path

from ..config.constants import CATEGORIES_FILE
from ..config.models import METADATA_MODEL
from ..llm import call_gemini, extract_json_from_response


def generate_episode_metadata(script: str) -> dict:
    """
    Generate episode title, description, excerpt, blog post, slug, and image prompt using Gemini.

    Args:
        script: The podcast script text

    Returns:
        Dict with title, slug, excerpt, description, show_notes, image_prompt
    """
    print(f"Generating episode metadata via Gemini ({METADATA_MODEL})...")

    metadata_prompt = """Based on this podcast script, generate:

1. A catchy, engaging episode title (max 60 characters)
2. A URL-friendly slug (3-5 words, lowercase, hyphen-separated, no special characters). This should capture the episode's main topic. Examples: "ai-code-generation-future", "model-collapse-training-data", "llm-reasoning-limits"
3. A short excerpt for card previews (1-2 sentences, max 150 characters). This is a quick hook that appears on episode cards alongside the thumbnail.
4. A compelling episode description/overview for podcast platforms (2-3 sentences, ~150-200 words). This is a teaser that entices listeners.
5. A blog post article (~800-1200 words) written in third person that summarizes the episode's key topics and insights. This should read like a proper article that conveys the substance of the discussion, not just a teaser. Write it as if explaining to someone what Herman and Corn discussed in this episode. Include the main arguments, insights, examples, and takeaways. Use paragraphs and occasional subheadings for readability.
6. An image generation prompt for episode cover art. IMPORTANT: The image should be a creative visual representation of the TOPIC discussed, NOT the podcast hosts. Do NOT include any donkeys, sloths, animals, or podcast host characters. Focus entirely on abstract, symbolic, or literal imagery that represents the episode's subject matter (e.g., for an episode about AI benchmarks, show futuristic data visualizations, racing/competition imagery, or measuring instruments - NOT animals discussing benchmarks)

Output format (use exactly these labels):
TITLE: [your title here]
SLUG: [your slug here]
EXCERPT: [your excerpt here]
DESCRIPTION: [your description here]
BLOG_POST: [your blog post here]
IMAGE_PROMPT: [your image prompt here]

Script:
""" + script[:12000]  # Limit script length for context window

    result_text = call_gemini(
        prompt=metadata_prompt,
        model=METADATA_MODEL,
        max_tokens=4000,
        temperature=0.7,
    )

    title = ""
    slug = ""
    excerpt = ""
    description = ""
    blog_post = ""
    image_prompt = ""

    if "TITLE:" in result_text:
        title_start = result_text.index("TITLE:") + len("TITLE:")
        title_end = result_text.index("SLUG:") if "SLUG:" in result_text else (result_text.index("EXCERPT:") if "EXCERPT:" in result_text else len(result_text))
        title = result_text[title_start:title_end].strip()

    if "SLUG:" in result_text:
        slug_start = result_text.index("SLUG:") + len("SLUG:")
        slug_end = result_text.index("EXCERPT:") if "EXCERPT:" in result_text else (result_text.index("DESCRIPTION:") if "DESCRIPTION:" in result_text else len(result_text))
        slug = result_text[slug_start:slug_end].strip()
        # Sanitize slug: lowercase, only alphanumeric and hyphens
        slug = re.sub(r'[^a-z0-9-]', '', slug.lower().replace(' ', '-'))
        slug = re.sub(r'-+', '-', slug).strip('-')

    if "EXCERPT:" in result_text:
        excerpt_start = result_text.index("EXCERPT:") + len("EXCERPT:")
        excerpt_end = result_text.index("DESCRIPTION:") if "DESCRIPTION:" in result_text else len(result_text)
        excerpt = result_text[excerpt_start:excerpt_end].strip()
        if len(excerpt) > 150:
            excerpt = excerpt[:147] + "..."

    if "DESCRIPTION:" in result_text:
        desc_start = result_text.index("DESCRIPTION:") + len("DESCRIPTION:")
        desc_end = result_text.index("BLOG_POST:") if "BLOG_POST:" in result_text else len(result_text)
        description = result_text[desc_start:desc_end].strip()

    if "BLOG_POST:" in result_text:
        blog_start = result_text.index("BLOG_POST:") + len("BLOG_POST:")
        blog_end = result_text.index("IMAGE_PROMPT:") if "IMAGE_PROMPT:" in result_text else len(result_text)
        blog_post = result_text[blog_start:blog_end].strip()

    if "IMAGE_PROMPT:" in result_text:
        img_start = result_text.index("IMAGE_PROMPT:") + len("IMAGE_PROMPT:")
        image_prompt = result_text[img_start:].strip()

    return {
        'title': title,
        'slug': slug,
        'excerpt': excerpt,
        'description': description,
        'show_notes': blog_post,
        'image_prompt': image_prompt
    }


def _load_taxonomy(categories_file: Path = None) -> dict:
    """
    Load category taxonomy from DB first, falling back to JSON file.

    Returns:
        Taxonomy dict with 'categories' key, or None if unavailable.
    """
    # Try database first
    try:
        from ..database import get_categories_taxonomy
        taxonomy = get_categories_taxonomy()
        if taxonomy and taxonomy.get("categories"):
            print("  Loaded categories from database")
            return taxonomy
    except Exception as e:
        print(f"  Warning: DB category load failed: {e}")

    # Fall back to JSON file
    categories_path = categories_file or CATEGORIES_FILE
    if categories_path.exists():
        with open(categories_path) as f:
            print("  Loaded categories from JSON file (fallback)")
            return json.load(f)

    return None


def categorize_episode(title: str, description: str, categories_file: Path = None) -> dict:
    """
    Categorize an episode based on its title and description.

    Uses an LLM to assign a category and subcategory from the predefined taxonomy.
    Loads taxonomy from DB first, falling back to JSON file.

    Args:
        title: Episode title
        description: Episode description
        categories_file: Path to categories.json (defaults to CATEGORIES_FILE)

    Returns:
        Dict with 'category' and 'subcategory' keys
    """
    print("Categorizing episode...")

    taxonomy = _load_taxonomy(categories_file)
    if not taxonomy:
        print("  Warning: No category taxonomy available, skipping categorization")
        return {'category': None, 'subcategory': None}

    # Build taxonomy description for prompt
    taxonomy_text = "AVAILABLE CATEGORIES:\n\n"
    for category in taxonomy['categories']:
        taxonomy_text += f"## {category['name']} ({category['id']})\n"
        taxonomy_text += f"{category['description']}\n"
        taxonomy_text += "Subcategories:\n"
        for sub in category['subcategories']:
            taxonomy_text += f"  - {sub['name']} ({sub['id']}): {sub['description']}\n"
        taxonomy_text += "\n"

    system_prompt = f"""You are an expert content categorizer for a podcast covering technology, AI, networking, health, and geopolitical topics.
Your task is to assign exactly ONE category and ONE subcategory to an episode based on its title and description.

{taxonomy_text}

RULES:
1. Choose the MOST relevant category and subcategory
2. If multiple categories could apply, pick the PRIMARY focus
3. For AI-related content, distinguish between:
   - ai-core: Fundamental concepts about how AI works (transformers, attention, training)
   - local-ai: Running AI on personal hardware (GPUs, Ollama, Docker)
   - speech-audio: Voice/audio specific AI topics (STT, TTS, Whisper, microphones)
   - ai-applications: Using AI for creative/practical purposes (image generation, agents)
   - ai-safety: Security and ethical concerns (prompt injection, guardrails, bias)
4. For non-AI content, use appropriate categories:
   - networking-infra: Networks, VPNs, firewalls, cloud infrastructure
   - hardware-computing: Physical devices, displays, cameras, mobile
   - home-consumer: Smart home, e-commerce, parenting tech
   - health-wellness: Medical topics, mental health, baby development
   - geopolitics-world: International affairs, defense, regional issues
5. Return ONLY valid category and subcategory IDs from the list above
6. Output as JSON: {{"category": "category-id", "subcategory": "subcategory-id"}}"""

    full_prompt = f"""{system_prompt}

---

Categorize this podcast episode:

Title: {title}
Description: {description}

Return only the JSON with category and subcategory IDs."""

    try:
        result_text = call_gemini(
            prompt=full_prompt,
            model=METADATA_MODEL,
            max_tokens=100,
            temperature=0.1,
        )

        result = extract_json_from_response(result_text)
        if result is None:
            print(f"  Warning: Failed to extract JSON from categorization response")
            return {'category': None, 'subcategory': None}

        # Validate against taxonomy
        valid_category = any(c['id'] == result.get('category') for c in taxonomy['categories'])
        if valid_category:
            category = next(c for c in taxonomy['categories'] if c['id'] == result['category'])
            valid_subcategory = any(s['id'] == result.get('subcategory') for s in category['subcategories'])
        else:
            valid_subcategory = False

        if valid_category and valid_subcategory:
            category_name = category['name']
            subcategory_name = next(s['name'] for s in category['subcategories'] if s['id'] == result['subcategory'])
            print(f"  Category: {category_name} > {subcategory_name}")
            return result
        else:
            print(f"  Warning: Invalid category response: {result}")
            return {'category': None, 'subcategory': None}

    except Exception as e:
        print(f"  Warning: Categorization error: {e}")
        return {'category': None, 'subcategory': None}
