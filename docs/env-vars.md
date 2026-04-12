# Environment Variables Reference

All environment variables used by the MWP pipeline. Variables marked **Required** must be set for the pipeline to function. Others are optional with sensible defaults.

## Core API Keys

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for all LLM operations (script, review, metadata, planning) |
| `FAL_KEY` | Yes | Fal AI API key for cover art generation |
| `TAVILY_API_KEY` | No | Tavily API key for web search during grounding stage |

## Database

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_URL` | Yes | PostgreSQL connection string (must have pgvector extension) |

## Cloudflare R2 Storage

| Variable | Required | Description |
|----------|----------|-------------|
| `CLOUDFLARE_ACCOUNT_ID` | Yes | Cloudflare account ID for R2 endpoint URL |
| `CF_R2_KEY_ID` | Yes | R2 API token access key ID |
| `CF_R2_ACCESS_KEY` | Yes | R2 API token secret access key |
| `R2_EPISODES_PUBLIC_URL` | Yes | Public URL base for the episodes R2 bucket |
| `R2_IMAGES_PUBLIC_URL` | No | Public URL base for the images R2 bucket |

## Authentication

| Variable | Required | Description |
|----------|----------|-------------|
| `WEBHOOK_SECRET` | Yes | Secret for `X-Webhook-Secret` header on webhook endpoints |

## Email Notifications (Resend)

| Variable | Required | Description |
|----------|----------|-------------|
| `RESEND_API_KEY` | No | Resend API key for email notifications |
| `RESEND_SENDER_EMAIL` | No | Sender email address (must be verified in Resend) |
| `RESEND_RECIPIENT` | No | Recipient email for pipeline notifications |

## Vercel Deployment

| Variable | Required | Description |
|----------|----------|-------------|
| `VERCEL_DEPLOY_HOOK` | No | Vercel deploy hook URL to trigger website rebuild |

## Publication Webhook

| Variable | Required | Description |
|----------|----------|-------------|
| `PUBLICATION_WEBHOOK_URL_PROD` | No | Production webhook URL for post-publish notifications |
| `PUBLICATION_WEBHOOK_URL_TEST` | No | Test webhook URL for development |
| `PUBLICATION_WEBHOOK_SECRET` | No | Secret sent in webhook request headers |
| `WEBHOOK_TEST_MODE` | No | Set to `true` to use test webhook URL |
| `WEBHOOK_TIMEOUT` | No | Webhook request timeout in seconds (default: `10`) |

## Wasabi Archival Storage

| Variable | Required | Description |
|----------|----------|-------------|
| `WASABI_ACCESS_KEY` | No | Wasabi S3 access key |
| `WASABI_SECRET_KEY` | No | Wasabi S3 secret key |
| `WASABI_BUCKET` | No | Wasabi bucket name |
| `WASABI_REGION` | No | Wasabi region |
| `WASABI_ENDPOINT` | No | Wasabi endpoint URL |

## Social Media

| Variable | Required | Description |
|----------|----------|-------------|
| `BLUESKY_HANDLE` | No | Bluesky account handle for auto-posting |
| `BLUESKY_PASSWORD` | No | Bluesky app password |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token for channel posting |
| `TELEGRAM_CHANNEL_ID` | No | Telegram channel to post to |
| `TWITTER_API_KEY` | No | X/Twitter API key |
| `TWITTER_API_SECRET` | No | X/Twitter API secret |
| `TWITTER_ACCESS_TOKEN` | No | X/Twitter access token |
| `TWITTER_ACCESS_SECRET` | No | X/Twitter access token secret |

## Model Overrides

All LLM models default to Anthropic Claude (Sonnet 4.6 for core stages, Haiku 4.5 for utility) and can be overridden:

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRIPT_MODEL` | `claude-sonnet-4-6` | Script generation model |
| `REVIEW_MODEL` | `claude-sonnet-4-6` | Script review (Pass 1) model |
| `PLANNING_MODEL` | `claude-haiku-4-5-20251001` | Episode planning model |
| `METADATA_MODEL` | `claude-haiku-4-5-20251001` | Metadata extraction model |
| `TAGGING_MODEL` | `claude-haiku-4-5-20251001` | Episode tagging model |

## Pipeline Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TTS_WORKERS` | `3` | Number of parallel TTS GPU workers |
| `TTS_GPU` | `A10G` | GPU type for TTS workers |
| `GPU_PROVIDER` | `modal` | GPU provider (`modal` or `runpod`) |
| `DEFAULT_COVER_ART_URL` | (built-in) | Fallback cover art URL if generation fails |
| `LOCAL_RECOVERY_DIR` | `/working/recovery` | Local directory for episode recovery files |
| `LANGSMITH_API_KEY` | (none) | Optional LangSmith tracing key |

## Modal Secrets

When deploying to Modal, secrets are configured as Modal secret groups rather than `.env` files:

- **`mwp-secrets`**: All required keys (Anthropic, Fal, R2, Postgres, Resend, webhook secret, social media)
- **`mwp-secrets-vercel`**: Vercel deploy hook URL (separate group for isolation)
- **`mwp-secrets-gdrive`**: Google Drive service account for pre-production guide uploads

See [setup.md](setup.md) for Modal secret creation commands.
