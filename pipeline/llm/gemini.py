"""
Google Gemini LLM provider.

Direct integration with Google's Gemini API for:
- Text generation
- Multimodal (audio + text) generation
- Google Search grounding for real-time information
"""

import os
from pathlib import Path

from google import genai
from google.genai import types

from ..config.models import SCRIPT_MODEL, get_gemini_api_key


def get_gemini_client(api_key: str = None) -> genai.Client:
    """
    Create a Gemini client with SDK-level retry on transient HTTP errors.

    Retries on 408/429/500/502/503/504 with exponential backoff (2 attempts).
    """
    api_key = api_key or get_gemini_api_key()
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set.")
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=120_000,
            retry_options=types.HttpRetryOptions(
                attempts=3,
                initial_delay=2.0,
                max_delay=15.0,
            ),
        ),
    )


# MIME type mapping for audio files
AUDIO_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}


def call_gemini(
    prompt: str,
    model: str = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    enable_grounding: bool = False,
) -> str:
    """
    Call Google Gemini API for text generation.

    Args:
        prompt: Text prompt for generation
        model: Gemini model ID (defaults to SCRIPT_MODEL, strips google/ prefix)
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature
        enable_grounding: Enable Google Search grounding for real-time information

    Returns:
        Generated text content
    """
    model = model or SCRIPT_MODEL
    # Strip google/ prefix if present for direct Gemini API
    if model.startswith("google/"):
        model = model.replace("google/", "")

    client = get_gemini_client()

    # Configure tools (Google Search grounding if enabled)
    tools = None
    if enable_grounding:
        tools = [types.Tool(google_search=types.GoogleSearch())]
        print("  [Grounding] Google Search enabled for real-time information")

    response = client.models.generate_content(
        model=model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
        ),
    )

    return response.text


def call_gemini_with_audio(
    audio_path: Path,
    prompt: str,
    model: str = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    enable_grounding: bool = False,
) -> str:
    """
    Call Google Gemini API with audio input (multimodal).

    This passes the raw audio binary to Gemini for true multimodal understanding,
    allowing the model to perceive tone, emphasis, context, and intent directly
    from the audio rather than relying on a transcript.

    Args:
        audio_path: Path to audio file
        prompt: Text prompt to accompany the audio
        model: Gemini model ID (defaults to SCRIPT_MODEL, strips google/ prefix)
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature
        enable_grounding: Enable Google Search grounding for real-time information

    Returns:
        Generated text content
    """
    model = model or SCRIPT_MODEL
    # Strip google/ prefix if present for direct Gemini API
    if model.startswith("google/"):
        model = model.replace("google/", "")

    # Read audio file as binary
    audio_path = Path(audio_path)
    with open(audio_path, "rb") as f:
        audio_data = f.read()

    # Determine MIME type from file extension
    ext = audio_path.suffix.lower()
    mime_type = AUDIO_MIME_TYPES.get(ext, "audio/mpeg")

    client = get_gemini_client()

    # Configure tools (Google Search grounding if enabled)
    tools = None
    if enable_grounding:
        tools = [types.Tool(google_search=types.GoogleSearch())]
        print("  [Grounding] Google Search enabled for real-time information")

    response = client.models.generate_content(
        model=model,
        contents=[
            prompt,
            types.Part.from_bytes(data=audio_data, mime_type=mime_type)
        ],
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
        ),
    )

    return response.text
