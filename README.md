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
Voice Recording
     |
     v
[Modal Webhook API]  ──────────────────────────────────
     |                                                  |
     v                                                  |
[Transcribe] ─> [Plan] ─> [Generate Script]            |
     |                          |                       |
     v                          v                       |
[Review Pass 1]          [Polish Pass 2]          [Cover Art]
  (Gemini +                (Gemini)              (Fal AI Flux)
   grounding)                  |                       |
     |                         v                       |
     └──────> [Validate] ─> [Metadata]                 |
                   |                                    |
                   v                                    |
            [Parallel TTS]  (2x T4 GPU workers)        |
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

## Quick Start

### Prerequisites

- [Modal](https://modal.com) account (serverless GPU compute)
- [Google AI Studio](https://aistudio.google.com) API key (Gemini)
- [Fal AI](https://fal.ai) API key (image generation)
- PostgreSQL database with [pgvector](https://github.com/pgvector/pgvector) extension
- [Cloudflare R2](https://www.cloudflare.com/r2/) bucket (S3-compatible storage)

### Setup

```bash
# Clone the repo
git clone https://github.com/My-Weird-Prompts/pipeline.git
cd pipeline

# Install Modal CLI
pip install modal
modal setup

# Configure secrets (see docs/setup.md for details)
cp .env.example .env
# Edit .env with your API keys and credentials

# Add your voice samples (see config/voices/README.md)
# Place WAV files in config/voices/corn/ and config/voices/herman/

# Deploy to Modal
modal deploy modal_app/recording_app.py
```

### Generate an Episode

```bash
curl -X POST "https://YOUR_MODAL_USERNAME--mwp-recording-app-web.modal.run/webhook/generate" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: YOUR_SECRET" \
  -d '{"audio_url": "https://your-audio-file.mp3"}'
```

See [docs/webhook-api.md](docs/webhook-api.md) for the full API reference.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Compute | [Modal](https://modal.com) (serverless GPU) |
| LLM | [Google Gemini](https://ai.google.dev/) (all text generation) |
| TTS | [Chatterbox](https://github.com/resemble-ai/chatterbox) (local, on GPU) |
| Image Gen | [Fal AI](https://fal.ai) (Flux Schnell) |
| Storage | [Cloudflare R2](https://www.cloudflare.com/r2/) (S3-compatible) |
| Database | PostgreSQL + [pgvector](https://github.com/pgvector/pgvector) |
| Audio | FFmpeg + pydub |

## Cost Per Episode

| Resource | Cost |
|----------|------|
| Modal GPU (2x T4, ~10 min) | ~$0.20 |
| Gemini API (all LLM calls) | ~$0.01 |
| Fal AI (cover art) | ~$0.01 |
| R2 Storage | Free egress |
| **Total** | **~$0.22** |

## Documentation

- [Architecture](docs/architecture.md) — Full 16-step pipeline flow
- [Setup Guide](docs/setup.md) — End-to-end deployment instructions
- [Environment Variables](docs/env-vars.md) — Complete env var reference
- [Webhook API](docs/webhook-api.md) — REST API reference

## Repository Structure

```
pipeline/           # Core generation logic
  core/             # Transcription, planning, script gen, review, polish, metadata
  llm/              # Gemini API wrappers
  tts/              # Chatterbox TTS engine
  audio/            # Audio processing and assembly
  storage/          # R2 and Wasabi storage clients
  database/         # PostgreSQL/pgvector operations
  publishing/       # Episode publication
  webhooks/         # Post-publish notification webhooks
  generators/       # Utility modules (OG images, PDFs, recovery)
  config/           # Models, prompts, constants, tags
  show-elements/    # Audio assets (intros, transitions, disclaimers)
modal_app/          # Modal deployment (webhook API + GPU functions)
config/voices/      # Voice samples for TTS (add your own)
docs/               # Documentation
deploy.sh           # Deployment script
```

## License

MIT License. See [LICENSE](LICENSE).

## Links

- [My Weird Prompts](https://myweirdprompts.com) — The podcast
- [My-Weird-Prompts GitHub Org](https://github.com/My-Weird-Prompts) — All MWP repos
