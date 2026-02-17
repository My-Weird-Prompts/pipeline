"""
Utility functions for LLM response processing.
"""

import json
import re


def extract_json_from_response(response: str) -> dict | None:
    """
    Extract JSON object from LLM response text.

    Handles common issues:
    - Markdown code blocks (```json ... ```)
    - Preamble text before JSON
    - Trailing text after JSON

    Args:
        response: Raw text response from LLM

    Returns:
        Parsed dict if JSON found, None otherwise
    """
    text = response.strip()

    # Handle markdown code blocks
    if "```" in text:
        # Extract content between code block markers
        parts = text.split("```")
        for part in parts[1::2]:  # Odd indices contain code block contents
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except json.JSONDecodeError:
                continue

    # Try to find JSON object in the text using regex
    # Match outermost { ... } allowing nested braces
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, text)

    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    # Last resort: try parsing the whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
