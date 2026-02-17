"""
Script generation module for the MWP podcast pipeline.

Handles:
- Podcast script generation from transcript + audio
- Research integration (planning agent + web search)
- Two-pass editing pipeline:
  - Pass 1 (Review): Fact-checking with Google Search grounding, plan adherence, depth
  - Pass 2 (Polish): Flow, verbal tics, sign-off cleanup, TTS compliance
- Episode memory for cross-episode references
"""

from datetime import datetime
from pathlib import Path

from ..llm.gemini import call_gemini, call_gemini_with_audio
from ..llm.utils import extract_json_from_response
from ..config.models import PLANNING_MODEL, SCRIPT_MODEL
from ..config.prompts import get_script_prompt
from ..config.constants import MAX_WORD_COUNT
from .transcription import transcribe_audio
from .episode_planning import EpisodePlan, run_episode_planning_agent
from .script_review import run_script_review_agent
from .script_polish import run_script_polish_agent


def run_planning_agent(transcript: str) -> dict:
    """
    Planning agent that analyzes the prompt and decides if web search is needed.

    Uses a fast model to:
    1. Analyze if the prompt mentions current events, recent news, specific incidents
    2. Generate appropriate search queries if needed
    3. Compile research context for script generation

    Args:
        transcript: The transcribed user prompt

    Returns:
        Dict with 'needs_search', 'search_queries', 'research_context'
    """
    print("  Running planning agent...")

    planning_prompt = """You are a research planning agent for a podcast. Analyze this prompt and determine if it requires current information from the web.

USER'S PROMPT:
{transcript}

TASK:
1. Determine if this prompt mentions:
   - Recent news events, incidents, or developments
   - Specific dates, people in the news, or current affairs
   - Technical topics that may have recent updates
   - Anything that requires up-to-date information (not just general knowledge)

2. If web search IS needed, provide 1-3 specific search queries that would retrieve relevant, current information.

3. If web search is NOT needed (general knowledge, hypothetical questions, creative topics, historical facts), indicate that.

OUTPUT FORMAT (JSON only, no markdown):
{{
  "needs_search": true/false,
  "reasoning": "brief explanation of why search is/isn't needed",
  "search_queries": ["query 1", "query 2"] // empty array if needs_search is false
}}

Remember: Only recommend search for topics that genuinely require current information. General knowledge questions, creative prompts, and historical topics do NOT need search."""

    try:
        response = call_gemini(
            prompt=planning_prompt.format(transcript=transcript),
            model=PLANNING_MODEL,
            max_tokens=500,
            temperature=0.3,
        )

        plan = extract_json_from_response(response)
        if plan is None:
            print("  Warning: Failed to extract JSON from planning response")
            plan = {"needs_search": False, "search_queries": [], "reasoning": "Failed to parse"}
        else:
            print(f"  Planning result: needs_search={plan.get('needs_search', False)}")
            if plan.get("reasoning"):
                print(f"  Reasoning: {plan['reasoning'][:100]}...")

    except Exception as e:
        print(f"  Warning: Planning agent error: {e}")
        plan = {"needs_search": False, "search_queries": [], "reasoning": "Failed to parse"}

    # Note: Actual web search is handled by Gemini's grounding feature
    # in generate_script() with enable_grounding=True
    return {
        "needs_search": plan.get("needs_search", False),
        "search_queries": plan.get("search_queries", []),
        "reasoning": plan.get("reasoning", ""),
        "research_context": None,  # Grounding handles real-time search
    }


def generate_script(
    transcript: str,
    research_context: dict = None,
    audio_path: Path = None,
    episode_context: str = None,
    episode_plan: EpisodePlan = None,
    sender_context: dict = None,
    attachment_content: str = None,
) -> str:
    """
    Generate podcast dialogue script using Google Gemini API.

    When audio_path is provided, uses multimodal Gemini to pass the original
    audio recording directly to the model, enabling it to perceive tone,
    emphasis, context, and intent from the raw audio rather than just text.

    Args:
        transcript: Transcribed user prompt
        research_context: Optional research results from planning agent
        audio_path: Optional path to original audio file for multimodal understanding
        episode_context: Optional episode memory context for cross-episode references
        episode_plan: Optional detailed episode plan from planning agent
        sender_context: Optional sender info (type, name, description)
        attachment_content: Optional text content from an attachment

    Returns:
        Diarized podcast script
    """
    if audio_path:
        print(f"Generating script via Gemini multimodal ({SCRIPT_MODEL}) with audio input...")
    else:
        print(f"Generating script via Gemini ({SCRIPT_MODEL})...")

    # Build the prompt with research context if available
    research_section = ""
    if research_context:
        research_section = "\n\n## RESEARCH CONTEXT (use this for accuracy on current events)\n\n"

        if research_context.get("summaries"):
            research_section += "### Key Findings:\n"
            for summary in research_context["summaries"]:
                research_section += f"{summary}\n\n"

        if research_context.get("sources"):
            research_section += "### Sources (cite naturally in discussion):\n"
            for source in research_context["sources"][:5]:
                research_section += f"- {source['title']}: {source['content'][:200]}...\n"

        research_section += "\nIMPORTANT: Use this research to ensure accuracy. Cite specific facts, dates, and details from the sources. If discussing recent events, reference the current information provided above.\n"

    # Audio instruction for multimodal
    audio_instruction = ""
    if audio_path:
        audio_instruction = """

## AUDIO INPUT
Listen to the attached audio recording of the user's prompt. This is the original voice recording
from Daniel. Pay attention to tone, emphasis, and any nuances that might not be captured in the
transcript. Use this multimodal understanding to create a more contextually appropriate response.

"""

    # Generate current date context
    current_date = datetime.now()
    date_context = f"""

## CURRENT DATE CONTEXT (for your internal reference)

**Today's date is: {current_date.strftime('%B %d, %Y')}**

Your training data may suggest an earlier date, but this is incorrect. The current year is {current_date.year}.
Use this knowledge INTERNALLY to ensure accuracy, but DO NOT repeatedly mention the year in dialogue.

**IMPORTANT - Year Mentions:**
- Do NOT frequently say "in {current_date.year}" or "here in {current_date.year}" - this sounds unnatural
- Listeners know what year it is; constant year references are annoying
- Only mention the year when it's genuinely relevant (comparing to previous years, historical context)
- For current events, just discuss them naturally without date-stamping every statement
"""

    # Grounding instruction for web search
    grounding_instruction = """

## WEB SEARCH & URL GROUNDING (ENABLED - USE IT!)

You have Google Search access to fetch real-time information. USE IT PROACTIVELY.

**CRITICAL FOR CURRENT EVENTS:**
When the prompt mentions recent news, current events, specific incidents, protests, conflicts,
political developments, product launches, company news, or anything that could have happened
recently - you MUST use Google Search to verify the facts. DO NOT GUESS or rely on training data
for current events. Get the real information.

**Use grounding to:**
1. **Verify current events** - search for the specific event/incident mentioned
2. **Get accurate details** - names, dates, outcomes, current status
3. **Fetch URL content** - if URLs are mentioned, search for that content
4. **Check recent developments** - technology releases, policy changes, etc.

**DO NOT make assumptions about current events.** If you're unsure about something recent,
search for it. Wrong information about current events is worse than admitting uncertainty.
"""

    # Episode memory context
    episode_section = ""
    if episode_context:
        episode_section = f"\n\n{episode_context}"
        print("  [Episode Memory] Including episode context for cross-references")

    # Episode plan section
    plan_section = ""
    if episode_plan:
        plan_section = f"\n\n{episode_plan.to_prompt_string()}"
        print("  [Episode Planning] Including detailed episode plan in prompt")

    # Sender context section
    sender_section = ""
    if sender_context:
        sender_type = sender_context.get("type", "daniel")
        sender_name = sender_context.get("name")
        sender_description = sender_context.get("description")

        if sender_type == "hannah":
            sender_section = """

## SPECIAL EPISODE - GUEST PROMPT FROM HANNAH

**This is a special episode!** This prompt comes from Hannah, Daniel's wife. She lives in the same house as Corn, Herman, and Daniel.

**IMPORTANT ADJUSTMENTS:**
- In the opening, mention that this prompt comes from Hannah (not Daniel): "So Hannah sent us something interesting this week..." or "We got a prompt from Hannah..."
- Treat her with the same familiarity as Daniel - she's part of the household
- After the initial mention, focus on the content itself
- Don't over-emphasize that it's a "special episode" - just naturally note it's from Hannah
- Keep the same tone and quality as regular episodes
"""
            print("  [Sender Context] Special episode from Hannah")
        elif sender_type == "other" and sender_name:
            sender_section = f"""

## SPECIAL EPISODE - GUEST PROMPT

**This is a special episode!** This prompt comes from a guest sender: **{sender_name}**
{f'({sender_description})' if sender_description else ''}

**IMPORTANT ADJUSTMENTS:**
- In the opening, introduce this as a guest prompt: "We have a special prompt today from {sender_name}..." or "A listener named {sender_name} sent us this one..."
- Briefly welcome the guest contribution in a warm, inclusive way
- After the initial mention, focus on the content itself - don't repeatedly reference the guest
- Treat the prompt with the same depth and quality as regular episodes
- In the closing, thank {sender_name} for sending in the prompt
"""
            print(f"  [Sender Context] Guest prompt from {sender_name}")

    # Attachment content section
    attachment_section = ""
    if attachment_content:
        attachment_section = f"""

## ATTACHMENT CONTENT

The sender included an attachment with this prompt. Here is the content (use this as additional context):

---
{attachment_content[:8000]}
---

**Use this attachment content to inform your discussion where relevant.** Reference specific details from the attachment naturally in the conversation.
"""
        print(f"  [Attachment] Including {len(attachment_content)} chars of attachment content")

    # Build full prompt
    full_prompt = f"""{get_script_prompt()}{date_context}{grounding_instruction}{episode_section}{plan_section}{sender_section}{attachment_section}

## USER'S PROMPT TO DISCUSS:
{transcript}
{audio_instruction}{research_section}
Now generate the episode script (target: ~3750 words for 25 minutes, max 4500 words). Follow the episode plan outline if provided."""

    # Generate script
    if audio_path and Path(audio_path).exists():
        script = call_gemini_with_audio(
            audio_path=audio_path,
            prompt=full_prompt,
            model=SCRIPT_MODEL,
            max_tokens=8000,
            temperature=0.8,
            enable_grounding=True,
        )
    else:
        script = call_gemini(
            prompt=full_prompt,
            model=SCRIPT_MODEL,
            max_tokens=8000,
            temperature=0.8,
            enable_grounding=True,
        )

    word_count = len(script.split())
    char_count = len(script)
    estimated_tts_cost = (char_count / 1000) * 0.025
    print(f"  Generated script: ~{word_count} words, {char_count:,} chars (est. TTS cost: ${estimated_tts_cost:.2f})")

    if word_count > MAX_WORD_COUNT * 1.2:
        print(f"  WARNING: Script exceeds target ({word_count} > {MAX_WORD_COUNT}). Consider regenerating.")
    print(f"  Preview:\n{'-'*40}\n{script[:1500]}...\n{'-'*40}")

    return script


def transcribe_and_generate_script(
    audio_path: Path,
    use_planning: bool = True,
    use_review: bool = True,
    use_polish: bool = True,
    sender_context: dict = None,
    attachment_content: str = None,
) -> tuple[str, str, dict]:
    """
    Full pipeline: transcribe audio, plan, research, generate, review, polish.

    This is the main entry point that orchestrates:
    1. Audio transcription (Gemini multimodal)
    2. [Optional] Episode planning agent (detailed outline)
    3. Research coordinator (web search for current events)
    4. Episode memory (cross-episode references)
    5. Script generation (Gemini multimodal with original audio + plan)
    6. [Optional] Script review agent - Pass 1 (fact-checking with grounding)
    7. [Optional] Script polish agent - Pass 2 (flow, verbal tics, sign-off)

    Args:
        audio_path: Path to audio file
        use_planning: Whether to run episode planning agent
        use_review: Whether to run script review agent (Pass 1)
        use_polish: Whether to run script polish agent (Pass 2)
        sender_context: Optional sender info (type, name, description)
        attachment_content: Optional text content from an attachment

    Returns:
        Tuple of (script, transcript, pipeline_info)
    """
    pipeline_info = {}

    # Step 1: Transcribe audio
    transcript = transcribe_audio(audio_path)

    # Step 2: Fetch episode memory for cross-episode references (needed for planning)
    # Uses semantic search to find contextually relevant past episodes
    episode_context = None
    next_episode_number = 0
    related_episodes = []
    try:
        from ..generators.episode_memory import get_episode_memory_for_generation
        episode_context, next_episode_number, related_episodes = get_episode_memory_for_generation(transcript)
        if next_episode_number:
            print(f"  [Episode Memory] This will be Episode {next_episode_number}")
        if related_episodes:
            print(f"  [Episode Memory] Found {len(related_episodes)} semantically related episodes")
    except ImportError:
        print("  [Episode Memory] Module not available, skipping")
    except Exception as e:
        print(f"  [Episode Memory] Failed to load: {e}")

    # Step 3: Episode Planning Agent (creates detailed outline)
    episode_plan = None
    if use_planning:
        episode_plan = run_episode_planning_agent(
            transcript=transcript,
            episode_context=episode_context,
        )
        if episode_plan:
            pipeline_info["planning"] = {
                "enabled": True,
                "target_length": episode_plan.target_length,
                "segments_count": len(episode_plan.segments),
                "facts_count": len(episode_plan.facts_to_include),
            }
        else:
            pipeline_info["planning"] = {"enabled": False, "reason": "failed"}
    else:
        pipeline_info["planning"] = {"enabled": False, "reason": "disabled"}

    # Step 4: Run research coordinator (or fallback to planning agent)
    try:
        from ..generators.research_coordinator import run_research_coordinator
        planning_result = run_research_coordinator(transcript)
    except ImportError:
        planning_result = run_planning_agent(transcript)

    research_context = planning_result.get("research_context")

    # Step 5: Generate script with research context, episode plan, and original audio
    script = generate_script(
        transcript=transcript,
        research_context=research_context,
        audio_path=audio_path,
        episode_context=episode_context,
        episode_plan=episode_plan,
        sender_context=sender_context,
        attachment_content=attachment_content,
    )

    # Step 6: Script Review Agent - Pass 1 (fact-checking with grounding)
    if use_review:
        script, review_info = run_script_review_agent(
            script=script,
            transcript=transcript,
            episode_plan=episode_plan,
        )
        pipeline_info["review"] = review_info
    else:
        pipeline_info["review"] = {"enabled": False, "reason": "disabled"}

    # Step 7: Script Polish Agent - Pass 2 (flow, verbal tics, sign-off)
    if use_polish:
        script, polish_info = run_script_polish_agent(script)
        pipeline_info["polish"] = polish_info
    else:
        pipeline_info["polish"] = {"enabled": False, "reason": "disabled"}

    return script, transcript, pipeline_info
