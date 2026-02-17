"""
Script parsing utilities for the MWP podcast pipeline.

Parses diarized podcast scripts into segments for TTS processing.
"""

import re
from ..config.constants import (
    HOST_NAME,
    CO_HOST_NAME,
    MAX_CHARS_PER_TTS_REQUEST,
)


def parse_diarized_script(script: str) -> list[dict]:
    """
    Parse a diarized script into a list of speaker segments.
    Handles two speakers: HOST_NAME (Corn) and CO_HOST_NAME (Herman).

    Args:
        script: The diarized script text

    Returns:
        List of dicts with 'speaker' and 'text' keys
    """
    segments = []
    pattern = rf'^({HOST_NAME}|{CO_HOST_NAME}):\s*(.+?)(?=^(?:{HOST_NAME}|{CO_HOST_NAME}):|\Z)'

    matches = re.findall(pattern, script, re.MULTILINE | re.DOTALL)

    for speaker, text in matches:
        text = text.strip()
        if text:
            segments.append({
                'speaker': speaker,
                'text': text,
            })

    # Fallback: line-by-line parsing
    if not segments:
        print("Using fallback line-by-line parsing...")
        for line in script.split('\n'):
            line = line.strip()
            if line.startswith(f"{HOST_NAME}:"):
                text = line[len(f"{HOST_NAME}:"):].strip()
                if text:
                    segments.append({'speaker': HOST_NAME, 'text': text})
            elif line.startswith(f"{CO_HOST_NAME}:"):
                text = line[len(f"{CO_HOST_NAME}:"):].strip()
                if text:
                    segments.append({'speaker': CO_HOST_NAME, 'text': text})

    print(f"Parsed {len(segments)} dialogue segments")
    return segments


def chunk_long_text(text: str, max_chars: int = MAX_CHARS_PER_TTS_REQUEST) -> list[str]:
    """
    Split long text into chunks at sentence boundaries to avoid TTS output limits.

    Chatterbox has a ~40 second audio output limit. This function splits long
    segments into smaller chunks that will stay well under that limit.

    Args:
        text: Text to potentially chunk
        max_chars: Maximum characters per chunk (default 250 for ~30 sec audio)

    Returns:
        List of text chunks (may be single item if text is short enough)
    """
    if len(text) <= max_chars:
        return [text]

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if current_chunk and len(current_chunk) + len(sentence) + 1 > max_chars:
            chunks.append(current_chunk.strip())
            current_chunk = sentence
        else:
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk.strip())

    # Handle edge case: a single sentence longer than max_chars
    final_chunks = []
    for chunk in chunks:
        if len(chunk) > max_chars * 1.5:
            # Try splitting on comma or semicolon as fallback
            parts = re.split(r'(?<=[,;])\s+', chunk)
            sub_chunk = ""
            for part in parts:
                if sub_chunk and len(sub_chunk) + len(part) + 1 > max_chars:
                    final_chunks.append(sub_chunk.strip())
                    sub_chunk = part
                else:
                    if sub_chunk:
                        sub_chunk += " " + part
                    else:
                        sub_chunk = part
            if sub_chunk:
                final_chunks.append(sub_chunk.strip())
        else:
            final_chunks.append(chunk)

    return final_chunks


def get_word_count(script: str) -> int:
    """Get the word count of a script."""
    return len(script.split())


def get_character_count(script: str) -> int:
    """Get the character count of a script."""
    return len(script)


def estimate_tts_cost(script: str, cost_per_1k_chars: float = 0.025) -> float:
    """
    Estimate TTS cost for a script.

    Args:
        script: The script text
        cost_per_1k_chars: Cost per 1000 characters (default $0.025)

    Returns:
        Estimated cost in USD
    """
    return (len(script) / 1000) * cost_per_1k_chars
