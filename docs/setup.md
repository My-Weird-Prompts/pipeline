# Setup Guide

End-to-end instructions for deploying the MWP pipeline.

## Prerequisites

- Python 3.11+
- [Modal](https://modal.com) account
- API keys for Google Gemini, Fal AI
- PostgreSQL database with pgvector extension (e.g., [Neon](https://neon.tech))
- Cloudflare R2 bucket (or any S3-compatible storage)

## 1. Install Modal CLI

```bash
pip install modal
modal setup
```

Follow the prompts to authenticate with your Modal account.

## 2. Set Up PostgreSQL

Create a PostgreSQL database with the pgvector extension. If using Neon:

1. Create a project at [neon.tech](https://neon.tech)
2. Enable the pgvector extension:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
3. Create the episodes table (the pipeline will auto-create it on first run, but you can also create it manually — see `pipeline/database/postgres.py` for the schema)

## 3. Set Up R2 Storage

Create two Cloudflare R2 buckets:
- `mwp-episodes` — for audio, transcripts, PDFs, peaks
- `mwd-images` — for cover art, OG images, Instagram images

Set up public access (R2.dev URLs or custom domain) so the files are publicly accessible.

Generate R2 API credentials:
1. Go to Cloudflare Dashboard > R2 > Manage R2 API Tokens
2. Create a token with read/write access to both buckets
3. Note the Access Key ID and Secret Access Key

## 4. Get API Keys

### Google Gemini
1. Go to [Google AI Studio](https://aistudio.google.com)
2. Create an API key
3. The pipeline uses Gemini for transcription, planning, script generation, review, polish, and metadata

### Fal AI
1. Sign up at [fal.ai](https://fal.ai)
2. Create an API key
3. Used for cover art generation (Flux Schnell model)

### Resend (Optional)
1. Sign up at [resend.com](https://resend.com)
2. Create an API key and verify your sending domain
3. Used for pipeline success/failure email notifications

## 5. Configure Modal Secrets

Create a Modal secret group called `mwp-secrets`:

```bash
modal secret create mwp-secrets \
  POSTGRES_URL="postgresql://..." \
  CLOUDFLARE_ACCOUNT_ID="your-account-id" \
  CF_R2_KEY_ID="your-r2-key-id" \
  CF_R2_ACCESS_KEY="your-r2-access-key" \
  R2_EPISODES_PUBLIC_URL="https://your-episodes-domain.com" \
  R2_IMAGES_PUBLIC_URL="https://your-images-domain.com" \
  GEMINI_API_KEY="your-gemini-key" \
  FAL_KEY="your-fal-key" \
  WEBHOOK_SECRET="your-webhook-secret" \
  RESEND_API_KEY="your-resend-key" \
  RESEND_SENDER_EMAIL="notifications@yourdomain.com" \
  RESEND_RECIPIENT="you@yourdomain.com"
```

If you use a Vercel deploy hook, create a second secret group:

```bash
modal secret create mwp-secrets-vercel \
  VERCEL_DEPLOY_HOOK="https://api.vercel.com/v1/integrations/deploy/..."
```

## 6. Add Voice Samples

See [config/voices/README.md](../config/voices/README.md) for instructions on adding voice samples.

At minimum, you need:
- A ~1 minute WAV recording for each host
- Uploaded to your R2 bucket or accessible via URL
- Referenced in `pipeline/config/constants.py` under `VOICE_SAMPLE_URLS`

For faster TTS, pre-compute voice conditionals:
```bash
python pipeline/scripts/precompute_voice_conditionals.py --upload
```

## 7. Upload Show Elements

The pipeline uses pre-recorded audio snippets (intro jingle, outro, disclaimers, etc.) stored in R2. Upload your show elements:

```bash
python pipeline/scripts/upload_snippets_to_r2.py
```

Or update `SHOW_ELEMENT_URLS` in `pipeline/config/constants.py` to point to your own audio assets.

## 8. Deploy

```bash
# Deploy to Modal
modal deploy modal_app/recording_app.py

# Or use the deploy script
./deploy.sh
```

The webhook API will be available at:
```
https://YOUR_MODAL_USERNAME--mwp-recording-app-web.modal.run
```

## 9. Test

```bash
# Health check
curl https://YOUR_MODAL_USERNAME--mwp-recording-app-web.modal.run/health

# Test webhook (no generation)
curl -X POST https://YOUR_MODAL_USERNAME--mwp-recording-app-web.modal.run/webhook/test \
  -H "Content-Type: application/json" \
  -d '{"audio_url": "https://example.com/test.mp3"}'

# Generate an episode
curl -X POST https://YOUR_MODAL_USERNAME--mwp-recording-app-web.modal.run/webhook/generate \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: YOUR_SECRET" \
  -d '{"audio_url": "https://your-audio-file.mp3"}'
```

## Local Development

For local testing without deploying:

```bash
# Serve locally (hot-reload)
modal serve modal_app/recording_app.py
```

This creates a temporary URL you can use for testing.
