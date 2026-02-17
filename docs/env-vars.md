# Environment Variables Reference

All environment variables used by the MWP pipeline. Variables marked **Required** must be set for the pipeline to function. Others are optional with sensible defaults.

## Core API Keys

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Google Gemini API key for all LLM operations |
| `FAL_KEY` | Yes | Fal AI API key for cover art generation |

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
| `WEBHOOK_SECRET` | Yes | Secret for `X-Webhook-Secret` header on the `/webhook/generate` endpoint |

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
| `WASABI_BUCKET` | No | Wasabi bucket name (default: `myweirdprompts`) |
| `WASABI_REGION` | No | Wasabi region (default: `eu-central-2`) |
| `WASABI_ENDPOINT` | No | Wasabi endpoint URL (default: `https://s3.eu-central-2.wasabisys.com`) |

## Model Overrides

All LLM models default to `google/gemini-3-flash-preview` and can be overridden:

| Variable | Default | Description |
|----------|---------|-------------|
| `TRANSCRIPTION_MODEL` | `google/gemini-3-flash-preview` | Audio transcription model |
| `PLANNING_MODEL` | `google/gemini-3-flash-preview` | Episode planning model |
| `SCRIPT_MODEL` | `google/gemini-3-flash-preview` | Script generation model |
| `METADATA_MODEL` | `google/gemini-3-flash-preview` | Metadata extraction model |
| `EPISODE_PLANNING_MODEL` | `google/gemini-3-flash-preview` | Episode planning agent model |
| `SCRIPT_REVIEW_MODEL` | `google/gemini-3-flash-preview` | Script review (Pass 1) model |
| `SCRIPT_POLISH_MODEL` | `google/gemini-3-flash-preview` | Script polish (Pass 2) model |

## Pipeline Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_COVER_ART_URL` | (built-in) | Fallback cover art URL if generation fails |
| `LOCAL_RECOVERY_DIR` | `/working/recovery` | Local directory for episode recovery files |
| `R2_RECOVERY_BUCKET` | `mwp-episodes` | R2 bucket for recovery storage |

## Modal Secrets

When deploying to Modal, secrets are configured as Modal secret groups rather than `.env` files:

- **`mwp-secrets`**: All required keys (Gemini, Fal, R2, Postgres, Resend, webhook secret)
- **`mwp-secrets-vercel`**: Vercel deploy hook URL (separate group for isolation)

See [setup.md](setup.md) for Modal secret creation commands.
