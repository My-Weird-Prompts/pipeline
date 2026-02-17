#!/usr/bin/env python3
"""
Lightweight Research Coordinator for MWP Pipeline

Analyzes prompts to determine if they reference current events, then relies
on Gemini's built-in Google Search grounding for real-time information.

Design Principles:
- Uses Gemini Flash for topic extraction and analysis
- Actual web search handled by Gemini grounding (enable_grounding=True)
- Fail-open: if analysis fails, continue anyway
- Returns structured context compatible with existing pipeline
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional

# Optional: Google Gemini
try:
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    types = None

try:
    from pipeline.llm.gemini import get_gemini_client
except ImportError:
    try:
        from ..llm.gemini import get_gemini_client
    except ImportError:
        get_gemini_client = None

# Environment
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

COORDINATOR_MODEL = os.environ.get("COORDINATOR_MODEL", "gemini-3-flash-preview")


@dataclass
class ResearchContext:
    """Structured research context for script generation."""
    summaries: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.summaries and not self.sources

    def to_dict(self) -> dict:
        """Convert to dict format expected by generate_script."""
        if self.is_empty():
            return None
        return {
            "summaries": self.summaries,
            "sources": self.sources,
            "queries": self.queries,
        }


class ResearchCoordinator:
    """
    Lightweight coordinator that analyzes prompts for current event references.

    The actual web search is handled by Gemini's built-in grounding feature
    (enable_grounding=True in script generation). This coordinator just:
    1. Analyzes if the prompt references current events
    2. Extracts key topics for logging/debugging
    3. Signals to the pipeline that grounding should be used
    """

    def __init__(self):
        # Initialize Gemini client for analysis (with SDK-level retry)
        if HAS_GEMINI and GEMINI_API_KEY and get_gemini_client:
            try:
                self.gemini_client = get_gemini_client(GEMINI_API_KEY)
            except Exception:
                self.gemini_client = None
        else:
            self.gemini_client = None

    def gather_context(self, transcript: str) -> ResearchContext:
        """
        Analyze transcript to determine if it references current events.

        Note: Actual web search is handled by Gemini's grounding feature
        in the script generation step, not here.

        Args:
            transcript: The transcribed user prompt

        Returns:
            ResearchContext with topics and analysis (no external search results)
        """
        print("  [Research Coordinator] Analyzing transcript...")
        context = ResearchContext()

        # Analyze transcript for current event references
        analysis = self._analyze_transcript(transcript)
        if not analysis:
            print("  [Research Coordinator] No analysis available")
            return context

        context.topics = analysis.get("topics", [])
        context.queries = analysis.get("queries", [])

        if analysis.get("needs_research", False):
            print(f"  [Research Coordinator] Current events detected: {', '.join(context.topics)}")
            print(f"  [Research Coordinator] Gemini grounding will fetch real-time info")
        else:
            print(f"  [Research Coordinator] General knowledge topic, grounding available if needed")

        return context

    def _analyze_transcript(self, transcript: str) -> Optional[dict]:
        """
        Use Gemini Flash to quickly analyze transcript and generate queries.

        Returns:
            Dict with needs_research, topics, queries, reasoning
        """
        if not self.gemini_client:
            print("  [Research Coordinator] Warning: No Gemini client, skipping analysis")
            return None

        prompt = f"""Analyze this podcast prompt and determine if it needs current web research.

PROMPT:
{transcript}

TASK:
1. Extract 1-3 key topics/entities mentioned
2. Determine if this needs CURRENT information (recent news, updates, specific facts)
3. If research IS needed, generate 1-2 focused search queries
4. If NOT needed (general knowledge, creative, hypothetical), skip research

OUTPUT (JSON only, no markdown):
{{
  "needs_research": true/false,
  "reasoning": "brief 1-sentence explanation",
  "topics": ["topic1", "topic2"],
  "queries": ["specific search query 1", "specific search query 2"]
}}

Only recommend research for genuinely current/factual topics. Skip for:
- General knowledge questions
- Creative or hypothetical prompts
- Historical topics
- Opinion-based discussions"""

        try:
            response = self.gemini_client.models.generate_content(
                model=COORDINATOR_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=300,
                ),
            )

            # Parse JSON from response
            text = response.text.strip()
            # Handle markdown code blocks
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            return json.loads(text)

        except Exception as e:
            print(f"  [Research Coordinator] Analysis error: {e}")
            return None

    def format_for_prompt(self, context: ResearchContext) -> str:
        """
        Format research context as a prompt section for script generator.

        This produces the same format as the existing research_section in generate_script.

        Args:
            context: ResearchContext object

        Returns:
            Formatted string for inclusion in prompt
        """
        if context.is_empty():
            return ""

        section = "\n\n## RESEARCH CONTEXT (use this for accuracy on current events)\n\n"

        if context.summaries:
            section += "### Key Findings:\n"
            for summary in context.summaries:
                section += f"{summary}\n\n"

        if context.sources:
            section += "### Sources (cite naturally in discussion):\n"
            for source in context.sources[:5]:
                section += f"- {source['title']}: {source['content'][:200]}...\n"

        section += "\nIMPORTANT: Use this research to ensure accuracy. Cite specific facts, dates, and details from the sources.\n"

        return section


def run_research_coordinator(transcript: str) -> dict:
    """
    Drop-in replacement for run_planning_agent().

    Provides the same return structure for compatibility with existing code:
    {
        "needs_search": bool,
        "search_queries": list,
        "reasoning": str,
        "research_context": dict or None
    }

    Args:
        transcript: The transcribed user prompt

    Returns:
        Dict compatible with existing pipeline expectations
    """
    coordinator = ResearchCoordinator()
    context = coordinator.gather_context(transcript)

    return {
        "needs_search": not context.is_empty(),
        "search_queries": context.queries,
        "reasoning": f"Topics: {', '.join(context.topics)}" if context.topics else "",
        "research_context": context.to_dict(),
    }


# Convenience function for direct use
def gather_research(transcript: str) -> Optional[dict]:
    """
    Simple interface: get research context for a transcript.

    Returns the research_context dict directly, or None if no research needed.
    """
    result = run_research_coordinator(transcript)
    return result.get("research_context")


if __name__ == "__main__":
    # Quick test
    import sys

    if len(sys.argv) > 1:
        test_transcript = " ".join(sys.argv[1:])
    else:
        test_transcript = "I was wondering about the latest developments in AI agents and how they're being used in production systems in 2025."

    print(f"Testing with: {test_transcript}\n")

    result = run_research_coordinator(test_transcript)
    print(f"\nResult:")
    print(f"  needs_search: {result['needs_search']}")
    print(f"  queries: {result['search_queries']}")
    print(f"  reasoning: {result['reasoning']}")

    if result['research_context']:
        ctx = result['research_context']
        print(f"  summaries: {len(ctx.get('summaries', []))}")
        print(f"  sources: {len(ctx.get('sources', []))}")
