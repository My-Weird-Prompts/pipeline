"""
Audio transcription module for the MWP podcast pipeline.

Uses Google Gemini API for multimodal transcription.
"""

import os
from pathlib import Path

from google.genai import types

from ..config.models import TRANSCRIPTION_MODEL, get_gemini_api_key
from ..config.prompts import TRANSCRIPTION_PROMPT
from ..llm.gemini import get_gemini_client


# MIME type mapping for audio files
AUDIO_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}


def transcribe_audio(audio_path: Path) -> str:
    """
    Transcribe audio using Google Gemini API directly with multimodal capabilities.
    Leverages audio understanding to extract clean prompts, context, and intent.

    Args:
        audio_path: Path to audio file

    Returns:
        Clean transcribed text without filler words
    """
    print(f"Transcribing audio with Gemini multimodal analysis: {audio_path.name}")

    api_key = get_gemini_api_key()
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set.")

    # Check for disambiguation hints (user-provided terms to help with transcription)
    disambiguation_hints = os.environ.get("DISAMBIGUATION_HINTS", "").strip()
    hints_section = ""
    if disambiguation_hints:
        print(f"  Using disambiguation hints: {disambiguation_hints}")
        hints_section = f"""
**IMPORTANT - DISAMBIGUATION HINTS:**
The following technical terms, names, or acronyms may appear in the audio. Use these exact spellings:
{disambiguation_hints}

"""

    # Enhanced prompt that leverages audio multimodal capabilities
    transcription_prompt = f"""You are analyzing an audio recording of someone speaking a prompt or question for an AI podcast.
{hints_section}
Your task is to:
1. **Listen to the audio** and understand the speaker's tone, intent, urgency, and context
2. **Generate a CLEAN version** of what they're asking - remove filler words (um, uh, like, you know), false starts, and repetitions
3. **Preserve the core meaning** and intent while making it clear and concise
4. **Maintain natural language** - don't make it overly formal, just cleaned up

The speaker often provides:
- A main prompt/question (what they want discussed)
- Additional context or background information
- Sometimes references to previous topics or current events

Output ONLY the cleaned transcript - the essential question/prompt without the speech disfluencies.

Example:
- Raw audio: "Um, so like, I was wondering, you know, about, uh, how AI models, like, how do they actually, um, handle like, you know, multimodal inputs and stuff?"
- Your output: "I was wondering about how AI models handle multimodal inputs."

Now process the audio and provide the cleaned transcript:"""

    try:
        client = get_gemini_client(api_key)

        # Read audio file
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        # Determine MIME type from file extension
        ext = audio_path.suffix.lower()
        mime_type = AUDIO_MIME_TYPES.get(ext, "audio/wav")

        # Extract model name for Gemini (remove google/ prefix if present)
        gemini_model = TRANSCRIPTION_MODEL
        if gemini_model.startswith("google/"):
            gemini_model = gemini_model.replace("google/", "")

        print(f"  Using Gemini model: {gemini_model}")

        # Call Gemini with audio
        response = client.models.generate_content(
            model=gemini_model,
            contents=[
                transcription_prompt,
                types.Part.from_bytes(data=audio_data, mime_type=mime_type)
            ]
        )

        transcript = response.text.strip()
        print(f"  ✓ Transcribed and cleaned: {len(transcript)} characters")
        print(f"  Preview: {transcript[:200]}...")

        return transcript

    except Exception as e:
        print(f"  ⚠️  Gemini transcription failed: {e}")
        raise ValueError(f"Transcription failed. Check GEMINI_API_KEY and try again. Error: {e}")
