# MWP Pipeline

Open-source AI podcast episode generation pipeline powering [My Weird Prompts](https://myweirdprompts.com) — a human-AI collaboration podcast where Daniel sends voice prompts and AI hosts discuss them.

**From a voice recording to a fully produced podcast episode in ~15 minutes.**

## How It Works

1. A voice prompt is uploaded via webhook
2. The pipeline transcribes, researches, and generates a full dialogue script
3. Two editing passes fact-check and polish the script
4. Parallel GPU workers synthesize speech via Chatterbox TTS
5. Audio is assembled with intros, transitions, and disclaimers
6. The episode is published to object storage and a PostgreSQL database
7. A website rebuild is triggered and downstream webhooks fire

## Architecture

```
Voice Recording / Text Prompt
     |
     v
[Modal Webhook API]  ──────────────────────────────────
     |                                                  |
     v                                                  |
[Transcribe] ─> [Plan] ─> [Generate Script]            |
     |                          |                       |
     v                          v                       |
[Review Pass 1]          [Polish Pass 2]          [Cover Art]
  (fact-check +            (style/flow)          (Fal AI Flux)
   web grounding)              |                       |
     |                         v                       |
     └──────> [Validate] ─> [Metadata]                 |
                   |                                    |
                   v                                    |
            [Parallel TTS]  (3x A10G GPU workers)      |
                   |                                    |
                   v                                    |
            [Assemble Audio]  <─────────────────────────
                   |
                   v
            [Duration Check]  (>= 10 min)
                   |
                   v
            [Publish]  ─> R2 + PostgreSQL + Vercel + Webhook
```

See [docs/architecture.md](docs/architecture.md) for the full 16-step breakdown.

### LangGraph Pipeline

The script generation stage is a [LangGraph](https://github.com/langchain-ai/langgraph) StateGraph with four nodes:

```python
# pipeline/graph/pipeline.py

def build_pipeline() -> StateGraph:
    graph = StateGraph(PipelineState)

    graph.add_node("prompt_enhancement", prompt_enhancement)
    graph.add_node("grounding", grounding)
    graph.add_node("script_writer", script_writer)
    graph.add_node("review", review)

    graph.add_edge(START, "prompt_enhancement")
    graph.add_edge("prompt_enhancement", "grounding")
    graph.add_edge("grounding", "script_writer")
    graph.add_edge("script_writer", "review")
    graph.add_edge("review", END)

    return graph.compile()
```

State flows through the graph as a typed dict:

```python
# pipeline/graph/state.py

class PipelineState(TypedDict, total=False):
    # Inputs
    audio_path: str               # Local path to downloaded audio
    text_topic: str               # Text-only topic (alternative to audio)
    sender_context: str           # Who sent the prompt
    attachment_content: str       # Attached document content
    image_paths: list[str]        # Attached image paths
    host_notes: str               # Private production direction
    features: dict                # Feature flags
    hosts: list[str]              # Override default hosts
    context: str                  # Additional context
    episode_length: str           # "short", "standard", "extended"
    job_id: str                   # Tracking ID
    custom_system_prompt: str     # Override system prompt
    enable_review: bool           # Enable/disable review pass
    prompt_variant: str           # "default" or "organic"
    series_context: dict          # Series curriculum metadata

    # Enhancement outputs
    raw_transcript: str           # Original STT output
    transcript: str               # Cleaned transcript
    pipeline_info: dict           # Metadata accumulator

    # Grounding outputs
    search_context: str           # Web search results
    similar_episodes: str         # RAG-retrieved similar episodes
    episode_context: str          # Episode memory context
    episode_plan: str             # Structured episode outline
    research_context: str         # Deep research results

    # Script outputs
    script: str                   # Generated dialogue script
    script_model_id: str          # Model used for generation
    script_model_display: str     # Human-readable model name
```

### LLM Architecture

All LLM calls use the **Anthropic SDK** natively with always-on prompt caching:

| Stage | Model | Role |
|-------|-------|------|
| **Script Generation** | Claude Sonnet 4.6 | Main dialogue generation |
| **Script Review** | Claude Sonnet 4.6 | Fact-checking and compliance |
| **Grounding / Research** | Claude Sonnet 4.6 | Tool-calling web research agent |
| **Prompt Enhancement** | Claude Haiku 4.5 | Transcript cleanup, host_notes extraction |
| **Planning & Metadata** | Claude Haiku 4.5 | Episode planning, tagging, categorization |

Prompt caching is enabled automatically for system prompts (>1024 tokens), reducing costs significantly for repeated calls with the same instructions.

## Episode Types

The pipeline supports many episode formats beyond the standard voice-prompt-to-episode flow:

| Type | Description | Voices | Duration |
|------|-------------|--------|----------|
| **Standard** | Voice prompt discussion | Corn + Herman | ~25 min |
| **Custom** | Text topic (no audio) | Corn + Herman | ~25 min |
| **SITREP** | News briefing | Corn + Herman | ~25 min |
| **SITREP Flash** | Quick news update | Corn + Herman | ~15 min |
| **SITREP Panel** | News + panel discussion | 4 voices | ~30 min |
| **News Analysis** | Deep news analysis | Corn + Herman + Mindy | ~30 min |
| **Panel** | Multi-round panel | 4+ voices | ~45 min |
| **Debate** | Structured debate | Corn vs Herman + Dorothy | ~30 min |
| **Roundtable** | Extended discussion | 7 voices, 3 acts | ~60 min |
| **Council Report** | 6-lens LLM analysis | Corn + Herman report | ~30 min |
| **Geopol Forecast** | Geopolitical simulation | Corn + Herman | ~35 min |
| **Conspiracy Corner** | Hilbert pitches theories | Hilbert + Corn + Herman | ~30 min |
| **Weird AI Experiments** | AI behavior experiments | Corn + Herman | ~25 min |
| **AI Asks** | AI-pitched topics | Corn + Herman | ~25 min |
| **Interview** | Agent interview | Corn interviews agent | ~25 min |
| **Docs Walkthrough** | Documentation deep-dive | Corn + Herman | ~45 min |
| **Series Episode** | Multi-part curriculum | Corn + Herman | ~25 min |
| **From Script** | Pre-written script | Any voices | Varies |
| **Host Update** | Raw audio (no TTS) | Daniel | Varies |

## Tech Stack

- **LLM** — [Anthropic](https://anthropic.com) (Claude Sonnet 4.6 for generation, Haiku 4.5 for utility)
- **TTS** — [Chatterbox](https://github.com/resemble-ai/chatterbox) Regular with parallel GPU workers
- **GPU Compute** — [Modal](https://modal.com) (serverless, 3x A10G default)
- **Orchestration** — [LangGraph](https://github.com/langchain-ai/langgraph) multi-agent pipeline
- **Research** — [Tavily](https://tavily.com) web search + pgvector RAG
- **Database** — Neon (serverless Postgres with pgvector)
- **Storage** — Cloudflare R2 (primary), Wasabi (backup)
- **Frontend** — [Astro](https://astro.build) + Vercel
- **Image Generation** — Fal AI (Flux Schnell)
- **Email** — Resend (pipeline notifications)

## Project Structure

```
pipeline/
├── graph/             # LangGraph pipeline (state, nodes, runner)
├── llm/               # Anthropic LLM client (prompt caching, tool use)
├── config/            # Model routes, constants, configuration
├── core/              # Script generation, review, polish, parsing
├── research/          # Deep research agent (LangGraph ReAct)
├── audio/             # Assembly, processing, normalization, metadata
├── tts/               # Chatterbox TTS integration
├── generators/        # Episode memory, recovery, waveform peaks
├── database/          # PostgreSQL operations
├── storage/           # R2 and Wasabi storage clients
├── publishing/        # Publication orchestration
├── webhooks/          # Post-publish webhook dispatch
├── show-elements/     # Audio assets (intros, transitions, disclaimers)
├── agents/            # Agentic pipeline components
├── scripts/           # Utility scripts
└── social/            # Social media posting (Bluesky, Telegram, X)

modal_app/
├── serverless_gpu_app.py   # FastAPI webhook API + Modal deployment
├── app_config.py           # GPU, pricing, image, secret config
├── stages/                 # 40+ generation modules (one per episode type)
└── generate_conditionals.py # Pre-compute voice embeddings

config/
└── voices/            # Voice samples for TTS

docs/
├── architecture.md    # Full 16-step pipeline breakdown
├── webhook-api.md     # REST API reference
├── env-vars.md        # Environment variable reference
└── setup.md           # Development setup guide
```

## Cost Per Episode

With parallel TTS (3 workers, A10G GPU):

| Component | Cost |
|-----------|------|
| TTS GPU compute | ~$0.28 |
| LLM (Anthropic) | ~$0.05-0.15 |
| Cover art (Fal AI) | ~$0.01 |
| **Total** | **~$0.35-0.45** |

Wall clock time: ~15 minutes end-to-end.

## Documentation

- [Architecture](docs/architecture.md) — Full 16-step pipeline flow
- [Webhook API](docs/webhook-api.md) — REST endpoint reference
- [Environment Variables](docs/env-vars.md) — Configuration reference
- [Setup Guide](docs/setup.md) — Development environment setup
- [Contributing](CONTRIBUTING.md) — How to contribute

## Links

- [myweirdprompts.com](https://myweirdprompts.com) — Podcast website
- [My-Weird-Prompts on GitHub](https://github.com/My-Weird-Prompts) — GitHub organization
- [Episode dataset on Hugging Face](https://huggingface.co/datasets/My-Weird-Prompts/episodes) — Full episode archive
- [Zenodo archive](https://zenodo.org/communities/myweirdprompts) — DOI-referenced dataset

## License

MIT — see [LICENSE](LICENSE).
