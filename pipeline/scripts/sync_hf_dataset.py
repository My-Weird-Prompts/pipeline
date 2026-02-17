#!/usr/bin/env python3
"""
Sync MWP episodes to Hugging Face dataset.

Exports all episodes from the Neon PostgreSQL database to:
https://huggingface.co/datasets/My-Weird-Prompts/episodes

Usage:
    python pipeline/scripts/sync_hf_dataset.py

Requires:
    - POSTGRES_URL in .env or environment
    - HF_TOKEN in environment (or logged in via `huggingface-cli login`)
    - pip: psycopg2-binary datasets huggingface_hub
"""

import os
import sys
from datetime import datetime

from dotenv import load_dotenv

# Load secrets: .env.production has all keys, website/.env.local as fallback
project_root = os.path.join(os.path.dirname(__file__), "..", "..")
load_dotenv(os.path.join(project_root, ".env.production"))
load_dotenv(os.path.join(project_root, "website", ".env.local"))

import psycopg2
from datasets import Dataset, Features, Value, Sequence

HF_REPO = "My-Weird-Prompts/episodes"

# Fields to export (order matters for readability)
EXPORT_FIELDS = [
    "episode_number",
    "season",
    "title",
    "slug",
    "pub_date",
    "podcast_duration",
    "description",
    "excerpt",
    "prompt",
    "prompt_summary",
    "prompt_transcript",
    "context",
    "response",
    "transcript",
    "show_notes",
    "tags",
    "category",
    "subcategory",
    "podcast_audio_url",
    "llm_model",
    "tts_engine",
    "tts_model",
    "pipeline_version",
]

FEATURES = Features({
    "episode_number": Value("int32"),
    "season": Value("int32"),
    "title": Value("string"),
    "slug": Value("string"),
    "pub_date": Value("string"),
    "podcast_duration": Value("string"),
    "description": Value("string"),
    "excerpt": Value("string"),
    "prompt": Value("string"),
    "prompt_summary": Value("string"),
    "prompt_transcript": Value("string"),
    "context": Value("string"),
    "response": Value("string"),
    "transcript": Value("string"),
    "show_notes": Value("string"),
    "tags": Sequence(Value("string")),
    "category": Value("string"),
    "subcategory": Value("string"),
    "podcast_audio_url": Value("string"),
    "llm_model": Value("string"),
    "tts_engine": Value("string"),
    "tts_model": Value("string"),
    "pipeline_version": Value("string"),
})


def fetch_episodes() -> list[dict]:
    """Fetch all episodes from the database."""
    postgres_url = os.environ.get("POSTGRES_URL")
    if not postgres_url:
        print("Error: POSTGRES_URL not set")
        sys.exit(1)

    conn = psycopg2.connect(postgres_url)
    cur = conn.cursor()

    # Build SELECT for just the fields we need
    select_fields = ", ".join(EXPORT_FIELDS)
    cur.execute(f"SELECT {select_fields} FROM episodes ORDER BY episode_number ASC")
    rows = cur.fetchall()

    cur.close()
    conn.close()

    episodes = []
    for row in rows:
        ep = {}
        for i, field in enumerate(EXPORT_FIELDS):
            val = row[i]
            # Normalize nulls to empty strings (except int fields)
            if field in ("episode_number", "season"):
                ep[field] = int(val) if val is not None else 0
            elif field == "tags":
                ep[field] = list(val) if val else []
            elif field == "pub_date":
                ep[field] = val.isoformat() if isinstance(val, datetime) else str(val or "")
            else:
                ep[field] = str(val) if val is not None else ""
        episodes.append(ep)

    return episodes


def main():
    print(f"Fetching episodes from database...")
    episodes = fetch_episodes()
    print(f"  Found {len(episodes)} episodes")

    if not episodes:
        print("No episodes found, exiting")
        sys.exit(1)

    print(f"Building dataset...")
    ds = Dataset.from_list(episodes, features=FEATURES)
    print(f"  Dataset: {ds}")

    # Use HF_TOKEN from env if set, otherwise fall back to stored credentials
    token = os.environ.get("HF_TOKEN", None)

    print(f"Pushing to {HF_REPO}...")
    ds.push_to_hub(
        HF_REPO,
        token=token,
        commit_message=f"Sync {len(episodes)} episodes ({datetime.now().strftime('%Y-%m-%d')})",
    )
    print(f"  Done! https://huggingface.co/datasets/{HF_REPO}")


if __name__ == "__main__":
    main()
