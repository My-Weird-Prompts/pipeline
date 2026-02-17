"""
LLM provider abstraction for the MWP podcast pipeline.

Primary provider: Google Gemini
"""

from .gemini import call_gemini, call_gemini_with_audio
from .utils import extract_json_from_response

__all__ = [
    'call_gemini',
    'call_gemini_with_audio',
    'extract_json_from_response',
]
