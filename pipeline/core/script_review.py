"""
Script Review Agent (Pass 1) for the MWP podcast pipeline.

Performs a single-pass review and direct editing of generated scripts.
Uses Gemini with Google Search grounding to:
- Verify factual accuracy
- Ensure completeness vs the episode plan
- Improve depth, pacing, and engagement
- Fix TTS compliance issues

Output format: raw script (no JSON), validated by length.
"""

from typing import Optional

from ..llm.gemini import call_gemini
from ..config.models import SCRIPT_REVIEW_MODEL
from .episode_planning import EpisodePlan


def run_script_review_agent(
    script: str,
    transcript: str,
    episode_plan: Optional[EpisodePlan] = None,
) -> tuple[str, dict]:
    """
    Run the script review agent to review and directly edit the script.

    This agent performs a single-pass review with direct edits.
    It uses Gemini with Google Search grounding to verify facts and add
    missing information.

    Fail-open: If review fails, returns the original script unchanged.

    Args:
        script: The generated podcast script
        transcript: The original user prompt/transcript
        episode_plan: Optional episode plan to check adherence against

    Returns:
        Tuple of (edited_script, review_info_dict)
    """
    print("\n" + "=" * 60)
    print("SCRIPT REVIEW AGENT: Reviewing and editing script")
    print("=" * 60)

    from datetime import datetime
    from ..config.prompts import get_script_review_prompt

    current_date = datetime.now().strftime("%B %d, %Y")

    # Format episode plan for prompt if available
    episode_plan_str = None
    if episode_plan:
        episode_plan_str = episode_plan.to_prompt_string()

    prompt = get_script_review_prompt(
        script=script,
        transcript=transcript,
        episode_plan=episode_plan_str,
        current_date=current_date,
    )

    try:
        edited = call_gemini(
            prompt=prompt,
            model=SCRIPT_REVIEW_MODEL,
            max_tokens=10000,
            temperature=0.4,  # Lower temperature for consistent edits
            enable_grounding=True,  # Google Search for fact-checking
        )

        # Strip any preamble the model might add
        edited = edited.strip()

        # Validate we got a script of reasonable length
        if not edited or len(edited) < 1000:
            print("  WARNING: Review returned empty or too-short script")
            print("  Continuing with original script (fail-open)")
            return script, {"enabled": False, "error": "Empty or too-short response"}

        # Guard against truncation — review should not significantly shrink the script
        original_words = len(script.split())
        edited_words = len(edited.split())
        shrinkage = (original_words - edited_words) / original_words if original_words > 0 else 0

        if shrinkage > 0.20:
            print(f"  WARNING: Review removed too much content ({shrinkage:.0%} shorter)")
            print(f"  Original: {original_words} words, Edited: {edited_words} words")
            print("  Continuing with original script (fail-open)")
            return script, {"enabled": False, "error": f"Script shrunk by {shrinkage:.0%}, rejecting"}

        # Log results
        word_diff = edited_words - original_words
        diff_sign = "+" if word_diff >= 0 else ""
        print(f"  [Grounding] Google Search enabled for real-time information")
        print(f"  Word count: {original_words} -> {edited_words} ({diff_sign}{word_diff})")
        print("  Review pass complete")

        review_info = {
            "enabled": True,
            "word_count_original": original_words,
            "word_count_edited": edited_words,
        }

        return edited, review_info

    except Exception as e:
        print(f"  ERROR in script review: {e}")
        print("  Continuing with original script (fail-open)")
        return script, {"enabled": False, "error": str(e)}
