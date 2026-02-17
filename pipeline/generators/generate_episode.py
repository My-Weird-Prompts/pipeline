"""
Legacy Episode Generator — Production Functions Only

This file is kept for backward compatibility. The following functions are still
imported by pipeline/publishing/__init__.py and used in the production pipeline:

- publish_episode()       — Upload to R2/Cloudinary, insert DB, trigger Vercel
- generate_cover_art()    — Generate cover art via Fal AI
- insert_episode_to_database() — Insert episode into Neon PostgreSQL
- upload_episode_to_wasabi()   — Backup episode to Wasabi S3

All other functions (TTS, transcription, script generation, CLI, audio processing)
have been removed — their production equivalents live in the modular pipeline
under pipeline/core/, pipeline/tts/, pipeline/audio/, etc.

Environment:
    GEMINI_API_KEY - Required for metadata/categorization calls in publish_episode
    FAL_KEY        - For cover art generation (Fal AI)
    POSTGRES_URL   - For database inserts
    WASABI_*       - For Wasabi S3 backup
"""

import concurrent.futures
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# Optional: Cloudinary for CDN hosting (deprecated fallback — R2 is primary)
try:
    import cloudinary
    import cloudinary.uploader
    HAS_CLOUDINARY = True
except ImportError:
    HAS_CLOUDINARY = False

# R2 Storage (primary CDN)
try:
    from pipeline.storage.r2 import (
        upload_episode_audio,
        upload_episode_cover,
        upload_og_image as upload_og_image_r2,
        upload_instagram_image as upload_instagram_image_r2,
        upload_episode_transcript,
        R2_EPISODES_PUBLIC_URL,
        R2_IMAGES_PUBLIC_URL,
    )
    HAS_R2 = bool(R2_EPISODES_PUBLIC_URL and R2_IMAGES_PUBLIC_URL)
except ImportError:
    HAS_R2 = False
    upload_episode_transcript = None
    upload_instagram_image_r2 = None

# OG and Instagram image generation
try:
    from generate_og_image import generate_og_image, generate_instagram_image_with_cover, generate_og_image_branded
    HAS_OG_IMAGE_GEN = True
except ImportError:
    HAS_OG_IMAGE_GEN = False
    generate_og_image = None
    generate_instagram_image_with_cover = None
    generate_og_image_branded = None

# Optional: psycopg2 for Neon database
try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

# Optional: boto3 for Wasabi (S3-compatible) storage
try:
    import boto3
    from botocore.exceptions import ClientError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

# Optional: Fal AI for image generation
try:
    import fal_client
    HAS_FAL = True
except ImportError:
    HAS_FAL = False

# Modular pipeline imports (preferred over legacy implementations)
try:
    from ..pipeline.storage import wasabi as pipeline_wasabi
    from ..pipeline.database import postgres as pipeline_db
    from ..pipeline.database import Episode as EpisodeModel
    from ..pipeline.steps import audio as pipeline_audio
    HAS_PIPELINE = True
except ImportError:
    HAS_PIPELINE = False

# Load environment variables
load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

PIPELINE_ROOT = Path(__file__).parent.parent

# Project root: use /repo mount in Docker, otherwise derive from file path
DOCKER_REPO_MOUNT = Path("/repo")
if DOCKER_REPO_MOUNT.exists() and (DOCKER_REPO_MOUNT / ".git").exists():
    PROJECT_ROOT = DOCKER_REPO_MOUNT
else:
    PROJECT_ROOT = PIPELINE_ROOT.parent

# Frontend repo (for blog post creation)
FRONTEND_REPO_PATH = os.environ.get("FRONTEND_REPO_PATH")
if FRONTEND_REPO_PATH:
    FRONTEND_ROOT = Path(FRONTEND_REPO_PATH)
elif Path("/frontend-repo").exists():
    FRONTEND_ROOT = Path("/frontend-repo")
else:
    FRONTEND_ROOT = PIPELINE_ROOT.parent.parent / "My-Weird-Prompts"

FRONTEND_PUBLIC = FRONTEND_ROOT / "code" / "frontend" / "public"
FRONTEND_CONTENT_DIR = FRONTEND_ROOT / "code" / "frontend" / "src" / "content" / "blog"

# Wasabi configuration
WASABI_BUCKET = os.environ.get("WASABI_BUCKET", "myweirdprompts")
WASABI_REGION = os.environ.get("WASABI_REGION", "eu-central-2")
WASABI_ENDPOINT = os.environ.get("WASABI_ENDPOINT", "https://s3.eu-central-2.wasabisys.com")

# Podcast metadata
PODCAST_NAME = "My Weird Prompts"
HOST_NAME = "Corn"
CO_HOST_NAME = "Herman"

# TTS provider detection for publish_episode
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "local")

# Pipeline version tracking
PIPELINE_VERSION = "V4"

# Gemini API key (used by categorize_episode in publish path)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


# =============================================================================
# COVER ART GENERATION
# =============================================================================


def _generate_single_cover_art(args: tuple) -> tuple[int, Path | None, Exception | None]:
    """
    Task function for parallel cover art generation using Fal AI (Nano Banana Pro).

    Args:
        args: Tuple of (variant_index, enhanced_prompt, images_dir)

    Returns:
        Tuple of (variant_index, output_path or None, error or None)
    """
    import urllib.request
    i, enhanced_prompt, images_dir = args

    try:
        if not HAS_FAL:
            raise RuntimeError("fal-client not installed. Run: pip install fal-client")

        # Ensure FAL_KEY is set
        fal_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
        if not fal_key:
            raise RuntimeError("FAL_KEY or FAL_API_KEY not set in environment")
        os.environ["FAL_KEY"] = fal_key

        result = fal_client.subscribe(
            "fal-ai/nano-banana-pro",
            arguments={
                "prompt": enhanced_prompt,
                "aspect_ratio": "1:1",
                "output_format": "png",
                "resolution": "2K",
            }
        )

        images = result.get("images", [])
        if not images:
            raise RuntimeError(f"No images returned from Fal AI: {result}")

        image_url = images[0].get("url")
        if not image_url:
            raise RuntimeError(f"No URL in Fal AI response: {result}")

        output_path = images_dir / f"cover_{i+1}.png"
        urllib.request.urlretrieve(image_url, str(output_path))
        return (i, output_path, None)
    except Exception as e:
        return (i, None, e)


def generate_cover_art(image_prompt: str, episode_dir: Path, num_variants: int = 1) -> list[Path]:
    """
    Generate episode cover art using Fal AI (Nano Banana Pro).

    Args:
        image_prompt: Prompt describing the desired cover art
        episode_dir: Episode directory to save images in
        num_variants: Number of cover art variants to generate (default 1)

    Returns:
        List of paths to generated images (may be empty if all failed)
    """
    print(f"Generating {num_variants} cover art variant(s) with Fal AI (Nano Banana Pro 1:1)...")

    enhanced_prompt = f"""Professional podcast episode cover art, modern clean design, visually striking, suitable for podcast platforms, square format. IMPORTANT: Do NOT include any text, words, letters, numbers, typography, titles, labels, or writing of any kind. No signs, no logos with text, no speech bubbles. Also do NOT include any animals, cartoon characters, donkeys, sloths, or podcast hosts - focus purely on abstract or symbolic imagery representing the topic. Theme: {image_prompt}"""

    images_dir = episode_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    tasks = [(i, enhanced_prompt, images_dir) for i in range(num_variants)]

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_variants) as executor:
        futures = {executor.submit(_generate_single_cover_art, task): task[0] for task in tasks}

        for future in concurrent.futures.as_completed(futures):
            idx, output_path, error = future.result()
            if error:
                print(f"  Cover art {idx+1}/{num_variants}: FAILED - {error}")
            else:
                print(f"  Cover art {idx+1}/{num_variants}: saved")
                results[idx] = output_path

    generated_paths = [results[i] for i in sorted(results.keys())]
    return generated_paths


# =============================================================================
# AUDIO HELPERS
# =============================================================================


def get_audio_duration_formatted(audio_path: Path) -> str:
    """Get audio duration in HH:MM:SS format for podcast feeds."""
    if HAS_PIPELINE:
        return pipeline_audio.get_duration_formatted(audio_path)

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True
        )
        seconds = float(result.stdout.strip())
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
    except Exception:
        return "0:00"


# =============================================================================
# CDN HELPERS (Cloudinary fallback)
# =============================================================================


def init_cloudinary():
    """Initialize Cloudinary configuration from environment variables."""
    if not HAS_CLOUDINARY:
        return False

    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    api_key = os.environ.get("CLOUDINARY_API_KEY")
    api_secret = os.environ.get("CLOUDINARY_API_SECRET")

    if not all([cloud_name, api_key, api_secret]):
        print("Warning: Cloudinary credentials not fully configured")
        return False

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True
    )
    return True


def upload_to_cloudinary(file_path: Path, resource_type: str = "auto", folder: str = "my-weird-prompts/episodes", public_id: str = None) -> dict | None:
    """Upload a file to Cloudinary CDN (fallback when R2 is unavailable)."""
    if not HAS_CLOUDINARY:
        print("Warning: Cloudinary not available")
        return None

    if not init_cloudinary():
        return None

    effective_public_id = public_id or file_path.stem

    try:
        print(f"  Uploading to Cloudinary: {file_path.name} (as {effective_public_id})")
        result = cloudinary.uploader.upload(
            str(file_path),
            resource_type=resource_type,
            folder=folder,
            public_id=effective_public_id,
            overwrite=True,
        )
        print(f"  Uploaded: {result.get('secure_url', 'unknown')[:60]}...")
        return result
    except Exception as e:
        print(f"Warning: Cloudinary upload failed: {e}")
        return None


# =============================================================================
# DATABASE
# =============================================================================


def insert_episode_to_database(
    slug: str,
    title: str,
    description: str,
    pub_date: datetime,
    hero_image: str = None,
    podcast_audio_url: str = None,
    podcast_duration: str = None,
    tags: list = None,
    category: str = None,
    subcategory: str = None,
    transcript: str = None,
    prompt: str = None,
    prompt_summary: str = None,
    prompt_transcript: str = None,
    prompt_redacted: str = None,
    context: str = None,
    response: str = None,
    show_notes: str = None,
    pipeline_version: str = None,
    tts_engine: str = None,
    tts_model: str = None,
    excerpt: str = None,
    og_image: str = None,
    instagram_image: str = None,
    llm_model: str = None,
    transcript_url: str = None,
    peaks_url: str = None,
) -> bool:
    """
    Insert episode into Neon PostgreSQL database.

    Returns:
        True if successful, False otherwise
    """
    if HAS_PIPELINE:
        episode = EpisodeModel(
            slug=slug,
            title=title,
            description=description,
            pub_date=pub_date,
            hero_image=hero_image,
            podcast_audio_url=podcast_audio_url,
            podcast_duration=podcast_duration,
            tags=tags,
            category=category,
            subcategory=subcategory,
            transcript=transcript,
            prompt=prompt,
            prompt_summary=prompt_summary,
            prompt_transcript=prompt_transcript,
            prompt_redacted=prompt_redacted,
            context=context,
            response=response,
            show_notes=show_notes,
            pipeline_version=pipeline_version,
            tts_engine=tts_engine,
            tts_model=tts_model,
            excerpt=excerpt,
            og_image=og_image,
            instagram_image=instagram_image,
            llm_model=llm_model,
            transcript_url=transcript_url,
            peaks_url=peaks_url,
        )
        return pipeline_db.insert_episode(episode)

    if not HAS_PSYCOPG2:
        print("Warning: psycopg2 not available, skipping database insert")
        return False

    postgres_url = os.environ.get("POSTGRES_URL")
    if not postgres_url:
        print("Warning: POSTGRES_URL not set, skipping database insert")
        return False

    try:
        print(f"  Inserting episode into database: {slug}")
        conn = psycopg2.connect(postgres_url)
        cur = conn.cursor()

        cur.execute("SELECT id FROM episodes WHERE slug = %s", (slug,))
        if cur.fetchone():
            print(f"  Episode already exists in database, skipping insert")
            conn.close()
            return True

        cur.execute("SELECT COALESCE(MAX(episode_number), 0) + 1 FROM episodes")
        next_episode_number = cur.fetchone()[0]
        print(f"  Assigning episode number: {next_episode_number}")

        cur.execute("""
            INSERT INTO episodes (
                slug, title, description, excerpt, pub_date, hero_image,
                podcast_audio_url, podcast_duration, tags, category, subcategory, ai_generated,
                transcript, prompt, prompt_summary, prompt_transcript, prompt_redacted,
                context, response, show_notes, pipeline_version, tts_engine, tts_model, episode_number,
                og_image, instagram_image, llm_model, transcript_url
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            slug,
            title,
            description,
            excerpt,
            pub_date,
            hero_image,
            podcast_audio_url,
            podcast_duration,
            tags,
            category,
            subcategory,
            True,
            transcript,
            prompt,
            prompt_summary,
            prompt_transcript,
            prompt_redacted,
            context,
            response,
            show_notes,
            pipeline_version,
            tts_engine,
            tts_model,
            next_episode_number,
            og_image,
            instagram_image,
            llm_model,
            transcript_url,
        ))

        conn.commit()
        cur.close()
        conn.close()
        print(f"  Episode inserted into database successfully")
        return True
    except Exception as e:
        print(f"Warning: Database insert failed: {e}")
        return False


# =============================================================================
# BLOG POST CREATION
# =============================================================================


def create_blog_post(
    episode_name: str,
    metadata: dict,
    audio_url: str,
    audio_duration: str,
    cover_image_url: str = None,
    transcript: str = None,
    show_notes: str = None,
    category: str = None,
    subcategory: str = None,
) -> Path:
    """
    Create a blog post markdown file for the episode.

    Returns:
        Path to the created markdown file
    """
    FRONTEND_CONTENT_DIR.mkdir(parents=True, exist_ok=True)

    slug = metadata.get('episode_slug') or metadata.get('slug')
    if not slug:
        slug = episode_name.lower().replace("_", "-").replace(" ", "-")
        slug = re.sub(r'[^a-z0-9-]', '', slug)

    pub_date = datetime.now().strftime("%Y-%m-%d")

    title = metadata.get('title', episode_name)
    description = metadata.get('description', '')

    tags = metadata.get('tags', [])

    category_lines = ""
    if category:
        category_lines += f'category: "{category}"\n'
    if subcategory:
        category_lines += f'subcategory: "{subcategory}"\n'

    frontmatter = f'''---
title: "{title}"
description: "{description}"
pubDate: "{pub_date}"
heroImage: "{cover_image_url or '/images/default-podcast-cover.png'}"
tags: {json.dumps(tags)}
{category_lines}podcastAudioUrl: "{audio_url}"
podcastDuration: "{audio_duration}"
aiGenerated: true
episodeType: "full"
---

'''

    content = frontmatter

    if show_notes:
        content += f"{show_notes}\n\n"
        content += "---\n\n"

    content += f"## Overview\n\n"
    content += f"{description}\n\n"
    content += "*This episode was generated by AI hosts Corn and Herman discussing a prompt from Daniel Rosehill.*\n\n"

    if transcript:
        content += "## Transcript\n\n"
        content += "<details>\n<summary>Click to expand full transcript</summary>\n\n"
        content += transcript[:10000]
        if len(transcript) > 10000:
            content += "\n\n*[Transcript truncated]*"
        content += "\n\n</details>\n"

    post_path = FRONTEND_CONTENT_DIR / f"{pub_date}-{slug}.md"
    with open(post_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Blog post created: {post_path.name}")
    return post_path


def deploy_blog_to_vercel(blog_path: Path, title: str, max_retries: int = 3) -> bool:
    """
    Trigger Vercel deployment via deploy hook with retry logic.

    Note: The blog_path parameter is kept for backward compatibility but
    is no longer used — Astro reads episode data from the database.
    """
    deploy_hook_url = os.environ.get("VERCEL_DEPLOY_HOOK")

    if not deploy_hook_url:
        print(f"  Warning: VERCEL_DEPLOY_HOOK not set - skipping deployment for '{title}'")
        print("  Episode is in database, manually trigger Vercel deploy to publish")
        return False

    print(f"Triggering Vercel deployment for: {title}")

    delay = 5.0
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(deploy_hook_url, timeout=30)

            if response.status_code in (200, 201):
                print("  Vercel deployment triggered successfully")
                return True
            else:
                last_error = f"Deploy hook returned status {response.status_code}"
                print(f"  Attempt {attempt + 1}/{max_retries + 1}: {last_error}")

        except requests.exceptions.Timeout:
            print("  Deploy hook timed out - deployment may still be triggered")
            return True

        except Exception as e:
            last_error = str(e)
            print(f"  Attempt {attempt + 1}/{max_retries + 1}: {last_error}")

        if attempt < max_retries:
            import time
            print(f"  Retrying in {delay:.0f}s...")
            time.sleep(delay)
            delay = min(delay * 2, 30)

    print(f"  Warning: Deployment failed after {max_retries + 1} attempts: {last_error}")
    return False


# =============================================================================
# PUBLISH EPISODE (main orchestrator)
# =============================================================================


def publish_episode(
    episode_dir: Path,
    episode_path: Path,
    metadata: dict,
    cover_art_paths: list[Path] = None,
    script: str = None,
    prompt_transcript: str = None,
    category: str = None,
    subcategory: str = None,
    og_image_path: Path = None,
    instagram_image_path: Path = None,
    tts_engine: str = None,
    tts_model: str = None,
    llm_model: str = None,
    peaks_url: str = None,
) -> dict:
    """
    Publish an episode: upload to R2 (or Cloudinary fallback), insert DB, trigger Vercel.

    Uploads audio, cover art, OG image, and Instagram image in parallel.
    Uses Cloudflare R2 as primary CDN, with Cloudinary as fallback.

    Returns:
        Dict with published URLs and paths
    """
    print("\nStep 5: Publishing episode...")
    print("PROGRESS: Publishing to blog...")

    result = {
        'audio_url': None,
        'cover_url': None,
        'og_image_url': None,
        'instagram_image_url': None,
        'blog_post': None,
    }

    duration = get_audio_duration_formatted(episode_path)

    episode_slug = metadata.get('episode_slug') or metadata.get('slug')
    if not episode_slug:
        episode_slug = episode_dir.name.lower().replace("_", "-").replace(" ", "-")
        episode_slug = re.sub(r'[^a-z0-9-]', '', episode_slug)

    use_r2 = HAS_R2

    if use_r2:
        print("  Using Cloudflare R2 for uploads...")

        def upload_audio():
            return upload_episode_audio(episode_path, episode_slug)

        def upload_cover():
            if cover_art_paths and cover_art_paths[0].exists():
                return upload_episode_cover(cover_art_paths[0], episode_slug)
            return None

        def upload_og():
            if og_image_path and og_image_path.exists():
                return upload_og_image_r2(og_image_path, episode_slug)
            return None

        def upload_instagram():
            if instagram_image_path and instagram_image_path.exists() and upload_instagram_image_r2:
                return upload_instagram_image_r2(instagram_image_path, episode_slug)
            return None

        print("  Uploading audio, cover art, OG image, and Instagram image in parallel...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            audio_future = executor.submit(upload_audio)
            cover_future = executor.submit(upload_cover)
            og_future = executor.submit(upload_og)
            instagram_future = executor.submit(upload_instagram)

            result['audio_url'] = audio_future.result()
            result['cover_url'] = cover_future.result()
            result['og_image_url'] = og_future.result()
            result['instagram_image_url'] = instagram_future.result()

        if upload_episode_transcript:
            result['transcript_url'] = upload_episode_transcript(
                episode_slug=episode_slug,
                prompt_transcript=prompt_transcript,
                response_transcript=script,
            )

    elif HAS_CLOUDINARY:
        print("  Using Cloudinary for uploads (R2 not configured)...")

        def upload_audio():
            return upload_to_cloudinary(
                episode_path,
                resource_type="video",
                folder="my-weird-prompts/episodes/audio",
                public_id=f"audio_{episode_slug}"
            )

        def upload_cover():
            if cover_art_paths and cover_art_paths[0].exists():
                return upload_to_cloudinary(
                    cover_art_paths[0],
                    resource_type="image",
                    folder="my-weird-prompts/episodes/covers",
                    public_id=f"cover_{episode_slug}"
                )
            return None

        def upload_og_image():
            if og_image_path and og_image_path.exists():
                return upload_to_cloudinary(
                    og_image_path,
                    resource_type="image",
                    folder="my-weird-prompts/episodes/og-images",
                    public_id=f"og_{episode_slug}"
                )
            return None

        print("  Uploading audio, cover art, and OG image in parallel...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            audio_future = executor.submit(upload_audio)
            cover_future = executor.submit(upload_cover)
            og_future = executor.submit(upload_og_image)

            audio_result = audio_future.result()
            cover_result = cover_future.result()
            og_result = og_future.result()

        if audio_result:
            result['audio_url'] = audio_result.get('secure_url')
        if cover_result:
            result['cover_url'] = cover_result.get('secure_url')
        if og_result:
            result['og_image_url'] = og_result.get('secure_url')

    else:
        print("  Warning: No CDN configured (R2 or Cloudinary) - skipping uploads")

    if result['audio_url']:
        blog_path = create_blog_post(
            episode_name=episode_dir.name,
            metadata=metadata,
            audio_url=result['audio_url'],
            audio_duration=duration,
            cover_image_url=result['cover_url'],
            transcript=script,
            show_notes=metadata.get('show_notes'),
            category=category,
            subcategory=subcategory,
        )
        result['blog_post'] = str(blog_path)

        deploy_result = deploy_blog_to_vercel(blog_path, metadata.get('title', 'New Episode'))
        result['deployed'] = deploy_result

        slug = metadata.get('episode_slug') or metadata.get('slug')
        if not slug:
            slug = episode_dir.name.lower().replace("_", "-").replace(" ", "-")
            slug = re.sub(r'[^a-z0-9-]', '', slug)

        try:
            published_slug_file = episode_dir / "metadata" / "published_slug.txt"
            published_slug_file.parent.mkdir(parents=True, exist_ok=True)
            published_slug_file.write_text(slug)
        except Exception as e:
            print(f"  Warning: Could not save published slug marker: {e}")

        effective_tts_engine = tts_engine or ("inworld" if TTS_PROVIDER == "inworld" else "chatterbox-fal")
        effective_tts_model = tts_model or metadata.get('tts_model')
        effective_llm_model = llm_model or metadata.get('llm_model')

        insert_episode_to_database(
            slug=slug,
            title=metadata.get('title', 'Untitled Episode'),
            description=metadata.get('description', ''),
            excerpt=metadata.get('excerpt'),
            pub_date=datetime.now(),
            hero_image=result.get('cover_url'),
            podcast_audio_url=result.get('audio_url'),
            podcast_duration=duration,
            tags=metadata.get('tags', []),
            category=category,
            subcategory=subcategory,
            transcript=script,
            prompt=metadata.get('prompt'),
            prompt_summary=metadata.get('prompt_summary'),
            prompt_transcript=prompt_transcript,
            prompt_redacted=prompt_transcript,
            context=metadata.get('context'),
            response=metadata.get('response'),
            show_notes=metadata.get('show_notes'),
            pipeline_version=PIPELINE_VERSION,
            tts_engine=effective_tts_engine,
            tts_model=effective_tts_model,
            og_image=result.get('og_image_url'),
            instagram_image=result.get('instagram_image_url'),
            llm_model=effective_llm_model,
            transcript_url=result.get('transcript_url'),
            peaks_url=peaks_url,
        )
    else:
        print("Warning: Skipping blog post creation - no audio URL")

    return result


# =============================================================================
# WASABI BACKUP
# =============================================================================


def get_wasabi_client():
    """Get a configured boto3 S3 client for Wasabi."""
    if HAS_PIPELINE:
        return pipeline_wasabi.get_client()

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


def upload_episode_to_wasabi(episode_dir: Path, episode_path: Path) -> str | None:
    """
    Upload the episode MP3 to Wasabi S3-compatible storage.

    Returns:
        S3 URL of the uploaded episode, or None if upload failed
    """
    if HAS_PIPELINE:
        try:
            return pipeline_wasabi.upload_episode(episode_dir, episode_path)
        except Exception as e:
            print(f"Warning: Wasabi backup failed (non-critical): {e}")
            return None

    client = get_wasabi_client()
    if not client:
        return None

    try:
        s3_key = f"episodes/{episode_dir.name}/{episode_path.name}"

        print(f"Uploading episode to Wasabi: s3://{WASABI_BUCKET}/{s3_key}")
        client.upload_file(
            str(episode_path),
            WASABI_BUCKET,
            s3_key,
            ExtraArgs={
                'ContentType': 'audio/mpeg',
            }
        )

        wasabi_url = f"{WASABI_ENDPOINT}/{WASABI_BUCKET}/{s3_key}"
        print(f"  Episode uploaded to Wasabi successfully")
        return wasabi_url

    except ClientError as e:
        print(f"Warning: Failed to upload episode to Wasabi: {e}")
        return None
    except Exception as e:
        print(f"Warning: Unexpected error uploading to Wasabi: {e}")
        return None
