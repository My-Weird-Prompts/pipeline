"""
Script Polish Agent (Pass 2) for the MWP podcast pipeline.

Performs a targeted second editing pass focused on:
- Removing verbal tics (overuse of "Exactly", "Absolutely", etc.)
- Cleaning up post-signoff content (no questions after goodbye)
- Improving conversational flow and natural pacing
- Final TTS compliance check

This runs AFTER the script review agent (Pass 1) which handles
fact-checking, plan adherence, and depth.

Output format: raw script (no JSON), validated by length.
"""

from ..llm.gemini import call_gemini
from ..config.models import SCRIPT_POLISH_MODEL


def run_script_polish_agent(script: str) -> tuple[str, dict]:
    """
    Run the script polish agent to clean up dialogue flow and verbal tics.

    This is a lightweight second pass that does NOT change facts or substance.
    It focuses purely on making the script sound natural when spoken aloud.

    Fail-open: If polish fails, returns the original script unchanged.

    Args:
        script: The reviewed podcast script (output of Pass 1)

    Returns:
        Tuple of (polished_script, polish_info_dict)
    """
    print("\n" + "=" * 60)
    print("SCRIPT POLISH AGENT: Polishing dialogue flow")
    print("=" * 60)

    from ..config.prompts import get_script_polish_prompt
    prompt = get_script_polish_prompt(script=script)

    try:
        polished = call_gemini(
            prompt=prompt,
            model=SCRIPT_POLISH_MODEL,
            max_tokens=10000,
            temperature=0.3,  # Low temperature — small targeted edits only
        )

        # Strip any preamble the model might add despite instructions
        polished = polished.strip()

        # Validate we got a script of reasonable length
        if not polished or len(polished) < 1000:
            print("  WARNING: Polish returned empty or too-short script")
            print("  Continuing with original script (fail-open)")
            return script, {"enabled": False, "error": "Empty or too-short response"}

        # Guard against the polish agent accidentally truncating the script
        original_words = len(script.split())
        polished_words = len(polished.split())
        shrinkage = (original_words - polished_words) / original_words if original_words > 0 else 0

        if shrinkage > 0.15:
            print(f"  WARNING: Polish removed too much content ({shrinkage:.0%} shorter)")
            print(f"  Original: {original_words} words, Polished: {polished_words} words")
            print("  Continuing with original script (fail-open)")
            return script, {"enabled": False, "error": f"Script shrunk by {shrinkage:.0%}, rejecting"}

        # Log results
        word_diff = polished_words - original_words
        diff_sign = "+" if word_diff >= 0 else ""
        print(f"  Word count: {original_words} -> {polished_words} ({diff_sign}{word_diff})")
        print("  Polish pass complete")

        polish_info = {
            "enabled": True,
            "word_count_original": original_words,
            "word_count_polished": polished_words,
        }

        return polished, polish_info

    except Exception as e:
        print(f"  ERROR in script polish: {e}")
        print("  Continuing with original script (fail-open)")
        return script, {"enabled": False, "error": str(e)}
