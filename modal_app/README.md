# Modal Apps

This directory contains Modal-based applications for the My Weird Prompts podcast generation pipeline.

## Apps

### 1. `generate.py` - Simple Episode Generator

A minimal Modal app with a simple upload form for generating episodes.

**Features:**
- Simple file upload or URL input
- API key authentication
- GPU-accelerated TTS with Chatterbox
- Basic status tracking
- Cost: ~$0.10/episode

**Use when:** You need a quick, simple interface for generating episodes.

**Deploy:**
```bash
modal deploy modal_app/generate.py
```

---

### 2. `recording_app.py` - Full Recording Interface

A complete Modal app with full recording utility from the main application.

**Features:**
- **Audio Recording**: Record directly from browser with waveform visualization
- **Pause/Resume**: Pause and resume recording
- **Timer Display**: Shows recording duration
- **Retake**: Discard and re-record
- **File Upload**: Upload existing audio files
- **Multiple TTS Providers**: Local GPU, Fal, Replicate, Inworld, Segmind
- **Real-time Progress**: Live progress tracking with logs
- **Disambiguation Hints**: Provide technical terms for better transcription
- **Safe to Exit**: Generation continues on server

**Use when:** You want the complete recording experience with all features from the main app.

**Deploy:**
```bash
# Use deployment script (recommended - ensures consistent app updates)
./deploy-modal.sh

# Or deploy directly
modal deploy modal_app/recording_app.py
```

**App URL:** https://YOUR_MODAL_USERNAME--mwp-recording-app-web.modal.run

**Documentation:** See [docs/modal-recording-app-guide.md](../docs/modal-recording-app-guide.md)

---

## Comparison

| Feature | generate.py | recording_app.py |
|---------|--------------|------------------|
| Recording UI | ❌ | ✅ Full |
| Waveform Visualization | ❌ | ✅ |
| Pause/Resume | ❌ | ✅ |
| Timer Display | ❌ | ✅ |
| Retake Function | ❌ | ✅ |
| File Upload | ✅ | ✅ |
| URL Input | ✅ | ❌ |
| Multiple TTS Providers | ✅ | ✅ |
| Progress Tracking | ✅ | ✅ |
| Logs Display | ❌ | ✅ |
| Disambiguation Hints | ❌ | ✅ |
| Settings Panel | ❌ | ✅ |
| Complexity | Simple | Full |

## Choosing the Right App

### Use `generate.py` if:
- You only need to upload files (no recording)
- You want a minimal interface
- You're testing the Modal deployment
- You prefer a simple upload form

### Use `recording_app.py` if:
- You want to record audio directly in the browser
- You need pause/resume functionality
- You want waveform visualization
- You need the full recording experience
- You want to provide disambiguation hints
- You want detailed progress logs

## Common Setup

Both apps require the same Modal secrets:

1. **Database** (required for progress tracking):
   - `POSTGRES_URL` or `NEON_DATABASE_URL`

2. **Cloudflare R2** (required for file storage):
   - `CLOUDFLARE_ACCOUNT_ID`
   - `CF_R2_KEY_ID`
   - `CF_R2_ACCESS_KEY`
   - `R2_EPISODES_PUBLIC_URL`

3. **API Keys** (required for generation):
   - `GEMINI_API_KEY`
   - `FAL_KEY` (for cover art)

4. **Authentication** (optional):
   - `MWP_API_KEY` (if you want API key auth)

### Setting Up Secrets

In the Modal dashboard, create a secret named `mwp-secrets` with all the above environment variables.

Or use CLI:
```bash
modal secret create mwp-secrets \
  POSTGRES_URL="postgres://..." \
  CLOUDFLARE_ACCOUNT_ID="..." \
  CF_R2_KEY_ID="..." \
  CF_R2_ACCESS_KEY="..." \
  R2_EPISODES_PUBLIC_URL="https://..." \
  GEMINI_API_KEY="..." \
  FAL_KEY="..."
```

## Deployment

### Deploy Recording App (Recommended)

Use the deployment script to ensure consistent updates to the same app:

```bash
./deploy-modal.sh
```

This script:
- Checks if app already exists
- Deploys updates to existing `mwp-recording-app`
- Verifies deployment is accessible
- Reports final URL (always the same)

### Deploy Directly

You can also deploy directly:

```bash
modal deploy modal_app/recording_app.py
```

**Important:** The app is named `mwp-recording-app` in the code, so deployments will always update this specific app. The URL remains consistent: `https://YOUR_MODAL_USERNAME--mwp-recording-app-web.modal.run`

### Deploy Simple Generator

```bash
modal deploy modal_app/generate.py
```

This script:
- Checks if app already exists
- Deploys updates to the existing `mwp-recording-app`
- Verifies deployment is accessible
- Reports the final URL (always the same)

### Deploy Directly

You can also deploy directly:

```bash
modal deploy modal_app/recording_app.py
```

**Important:** The app is named `mwp-recording-app` in the code, so deployments will always update this specific app. The URL remains consistent: `https://YOUR_MODAL_USERNAME--mwp-recording-app-web.modal.run`

### Deploy Simple Generator

```bash
modal deploy modal_app/generate.py
```

### Test Locally

```bash
# Test generation function
modal run modal_app/generate.py --audio-url "https://..."

modal run modal_app/recording_app.py --audio-url "https://..."
```

### View Logs

```bash
# View all app logs
modal app logs mwp-pipeline

modal app logs mwp-recording-app
```

## Cost Comparison

| Provider | Cost/Episode | Time |
|----------|---------------|-------|
| Local GPU (Chatterbox) | ~$0.10 | 5-15 min |
| Fal AI | ~$2.00 | 3-8 min |
| Replicate | ~$1.50 | 5-10 min |
| Inworld | ~$0.50 | 8-15 min |
| Segmind | ~$0.30 | 10-20 min |

## Troubleshooting

### Common Issues

**"No API key configured"**
- Add `MWP_API_KEY` to Modal secrets or leave empty for dev mode

**"Database not configured"**
- Add `POSTGRES_URL` or `NEON_DATABASE_URL` to Modal secrets

**"Upload failed"**
- Check R2 credentials in Modal secrets

**"Recording not supported"**
- Use Chrome or Firefox on HTTPS

### Getting Help

- Check the Modal dashboard for function logs
- See [docs/modal-recording-app-guide.md](../docs/modal-recording-app-guide.md) for detailed guide
- Review Modal logs: `modal app logs <app-name>`

## Development

### Project Structure

```
modal_app/
├── __init__.py          # Package init
├── generate.py          # Simple generator app
├── recording_app.py     # Full recording interface app
├── setup_secrets.sh    # Helper script for setting secrets
└── README.md           # This file
```

### Adding a New App

1. Create a new Python file in `modal_app/`
2. Define a Modal app with `app = modal.App("app-name")`
3. Define images (web and/or GPU)
4. Create web endpoint with `@modal.asgi_app()`
5. Document in this README

## Related Documentation

- [Modal Deployment Guide](../docs/modal-deployment-guide.md)
- [Modal TTS Cost Analysis](../docs/2025-12-30-modal-tts-cost-analysis.md)
- [Recording App Guide](../docs/modal-recording-app-guide.md)
