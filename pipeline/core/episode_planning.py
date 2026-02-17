"""
Episode Planning Agent for the MWP podcast pipeline.

Creates detailed episode outlines before script generation to provide
the script writer with a concrete roadmap including:
- Segment-by-segment breakdown with specific points to cover
- Key facts and data to incorporate
- Misconceptions to address
- Cross-episode references
- Tone and pacing guidance
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..llm.gemini import call_gemini
from ..llm.utils import extract_json_from_response
from ..config.models import EPISODE_PLANNING_MODEL
from ..config.prompts import get_episode_planning_prompt


@dataclass
class EpisodePlan:
    """Structured episode plan from the planning agent."""

    topic_summary: str = ""
    target_length: str = "medium"  # "short"|"medium"|"long"
    segments: list[dict] = field(default_factory=list)
    facts_to_include: list[str] = field(default_factory=list)
    misconceptions_to_address: list[str] = field(default_factory=list)
    ad_break_placement: str = ""
    transitions: list[str] = field(default_factory=list)
    related_episodes: list[dict] = field(default_factory=list)
    tone_guidance: str = ""

    def to_prompt_string(self) -> str:
        """Format the plan for inclusion in the script generation prompt."""
        lines = []
        lines.append("## EPISODE PLAN (follow this outline)")
        lines.append("")

        if self.topic_summary:
            lines.append(f"**Topic**: {self.topic_summary}")
            lines.append("")

        if self.target_length:
            length_map = {
                "short": "3000-3300 words (20-22 minutes)",
                "medium": "3300-3750 words (22-25 minutes)",
                "long": "3750+ words (25+ minutes)",
            }
            lines.append(f"**Target Length**: {length_map.get(self.target_length, self.target_length)}")
            lines.append("")

        if self.segments:
            lines.append("### Segment Outline")
            for seg in self.segments:
                name = seg.get("name", "unknown")
                duration = seg.get("duration_guidance", "")
                lines.append(f"\n**{name.upper()}** ({duration})")

                if seg.get("points"):
                    lines.append("Points to cover:")
                    for point in seg["points"]:
                        lines.append(f"- {point}")

                if seg.get("questions_to_address"):
                    lines.append("Questions to address:")
                    for q in seg["questions_to_address"]:
                        lines.append(f"- {q}")

                if seg.get("examples"):
                    lines.append("Examples/case studies:")
                    for ex in seg["examples"]:
                        lines.append(f"- {ex}")

                if seg.get("notes"):
                    lines.append(f"Notes: {seg['notes']}")

                if seg.get("placement_context"):
                    lines.append(f"Context: {seg['placement_context']}")
            lines.append("")

        if self.facts_to_include:
            lines.append("### Key Facts to Include")
            for fact in self.facts_to_include:
                lines.append(f"- {fact}")
            lines.append("")

        if self.misconceptions_to_address:
            lines.append("### Misconceptions to Address")
            for misc in self.misconceptions_to_address:
                lines.append(f"- {misc}")
            lines.append("")

        if self.related_episodes:
            lines.append("### Episodes to Reference")
            for ep in self.related_episodes:
                ep_num = ep.get("episode_number", "?")
                title = ep.get("title", "")
                connection = ep.get("connection", "")
                lines.append(f"- Episode {ep_num}: {title} - {connection}")
            lines.append("")

        if self.transitions:
            lines.append("### Suggested Transitions")
            for trans in self.transitions:
                lines.append(f"- {trans}")
            lines.append("")

        if self.tone_guidance:
            lines.append(f"### Tone Guidance\n{self.tone_guidance}")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict) -> "EpisodePlan":
        """Create an EpisodePlan from a dictionary (parsed JSON)."""
        # Extract ad_break_placement from segments if present
        ad_placement = data.get("ad_break_placement", "")
        if not ad_placement:
            for seg in data.get("segments", []):
                if seg.get("name") == "ad_break" and seg.get("placement_context"):
                    ad_placement = seg["placement_context"]
                    break

        return cls(
            topic_summary=data.get("topic_summary", ""),
            target_length=data.get("target_length", "medium"),
            segments=data.get("segments", []),
            facts_to_include=data.get("facts_to_include", []),
            misconceptions_to_address=data.get("misconceptions_to_address", []),
            ad_break_placement=ad_placement,
            transitions=data.get("transitions", []),
            related_episodes=data.get("related_episodes", []),
            tone_guidance=data.get("tone_guidance", ""),
        )


def run_episode_planning_agent(
    transcript: str,
    episode_context: str = None,
) -> Optional[EpisodePlan]:
    """
    Run the episode planning agent to generate a detailed episode outline.

    Uses a fast Gemini model to analyze the transcript and produce
    a structured plan for the script generation agent.

    Fail-open: If planning fails, returns None and the pipeline continues
    without a plan (the script generator has worked without plans before).

    Args:
        transcript: The transcribed user prompt
        episode_context: Optional episode memory context for cross-references

    Returns:
        EpisodePlan if successful, None if planning fails
    """
    print("\n" + "=" * 60)
    print("EPISODE PLANNING AGENT: Creating episode outline")
    print("=" * 60)

    current_date = datetime.now().strftime("%B %d, %Y")

    prompt = get_episode_planning_prompt(
        transcript=transcript,
        episode_context=episode_context,
        current_date=current_date,
    )

    try:
        response = call_gemini(
            prompt=prompt,
            model=EPISODE_PLANNING_MODEL,
            max_tokens=2000,
            temperature=0.5,
        )

        plan_data = extract_json_from_response(response)

        if plan_data is None:
            print("  WARNING: Failed to extract JSON from planning response")
            print("  Continuing without episode plan (fail-open)")
            return None

        plan = EpisodePlan.from_dict(plan_data)

        # Log the plan summary
        print(f"  Topic: {plan.topic_summary[:80]}..." if len(plan.topic_summary) > 80 else f"  Topic: {plan.topic_summary}")
        print(f"  Target length: {plan.target_length}")
        print(f"  Segments: {len(plan.segments)}")
        print(f"  Facts to include: {len(plan.facts_to_include)}")
        print(f"  Misconceptions to bust: {len(plan.misconceptions_to_address)}")
        if plan.related_episodes:
            print(f"  Cross-references: {len(plan.related_episodes)} past episodes")

        return plan

    except Exception as e:
        print(f"  ERROR in episode planning: {e}")
        print("  Continuing without episode plan (fail-open)")
        return None
