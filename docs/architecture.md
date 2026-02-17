# Pipeline Architecture

The MWP episode generation pipeline transforms a voice recording into a fully produced podcast episode. This document describes the complete 16-step flow.

## Pipeline Flow

### Step 1: Download Audio

The pipeline receives an audio URL via the webhook API. The audio file is downloaded with a 120-second timeout and must be at least 1KB (to reject empty/corrupt files).

### Step 2: Transcribe

The voice prompt is transcribed using Gemini's multimodal capabilities. The audio is sent directly to the model — no separate STT service needed.

### Step 3: Plan Episode

An episode planning agent analyzes the transcript and generates a structured outline. This agent has access to Google Search grounding for research. It determines:
- Key topics and subtopics to cover
- Relevant facts, statistics, or background
- Suggested structure and flow
- Whether the topic needs technical depth or a lighter approach

### Step 4: Generate Script

The main script generation step produces a full dialogue between the two AI hosts (Corn and Herman). The prompt includes:
- The episode plan from Step 3
- Character descriptions and dynamics
- Recent episode memory (last 3 episodes for cross-references)
- Sender context (who sent the prompt)
- Target word count (3000-4500 words for 20-30 minute episodes)

The script uses Google Search grounding for factual accuracy.

### Step 5: Review Script (Pass 1)

**Script Review** (`pipeline/core/script_review.py`) uses Gemini with Google Search grounding to:
- Fact-check claims and statistics
- Verify the script follows the episode plan
- Ensure sufficient depth on each subtopic
- Flag any inaccuracies for correction

This pass **fails open** — if anything goes wrong, the original script is returned unchanged. A **shrinkage guard** rejects the output if the script shrinks by more than 15%.

### Step 6: Polish Script (Pass 2)

**Script Polish** (`pipeline/core/script_polish.py`) uses Gemini (without grounding) to:
- Improve conversational flow
- Remove verbal tics (e.g., overuse of "Exactly!")
- Clean up sign-off sections
- Ensure TTS compliance (no problematic characters or formatting)

This pass also **fails open** with a **shrinkage guard** (rejects if script shrinks >20%).

Both editing passes return raw script text only (no JSON wrapping) to eliminate truncation risk.

### Step 7: Validate Script

Safety checks before proceeding to TTS:
- **Minimum 2000 words** (prevents short/truncated episodes)
- **Minimum 10 dialogue segments** (prevents degenerate scripts)

### Step 8: Generate Metadata

Gemini generates episode metadata from the script:
- Title
- Description
- Short excerpt (for social media)
- SEO-optimized slug
- Image generation prompt (for cover art)
- Show notes (blog-style article)
- Prompt summary

### Step 9: Generate Cover Art

Fal AI (Flux Schnell model) generates cover art from the image prompt. This step has **graceful degradation** — if image generation fails, a default cover is used and the episode still publishes.

### Step 10: Parallel TTS

The script is parsed into individual dialogue segments and distributed across 2 parallel GPU workers (T4 instances). Each worker:
1. Loads the Chatterbox TTS model once
2. Downloads pre-computed voice conditionals from R2
3. Processes its assigned segments sequentially
4. Returns the generated audio segments

A **TTS failure rate check** aborts the episode if more than 20% of segments fail synthesis.

### Step 11: Assemble Episode

Audio segments are assembled in order with show elements:
1. Mixed intro jingle
2. Prompt intro ("Daniel sent us this prompt...")
3. Recorded voice prompt audio
4. Transition whoosh
5. All dialogue segments
6. LLM info disclaimer
7. TTS info disclaimer
8. General disclaimer
9. Mixed outro jingle

The assembled audio is normalized to EBU R128 podcast standards (-16 LUFS) and encoded as 96kbps MP3.

### Step 12: Duration Check

A safety gate rejects episodes shorter than 10 minutes using ffprobe. If ffprobe fails, it falls back to a file size check (minimum 3MB). This catches issues like mass TTS failures or aggressive silence removal.

### Step 13: Waveform Peaks

Waveform peak data is extracted for the web audio player visualization. This step is **fail-open** — the episode publishes even if peak extraction fails.

### Step 14: Categorize, Tag, and Embed

- **Categories**: The episode is assigned to a category/subcategory from a predefined taxonomy
- **Tags**: Dynamic tags are generated based on episode content
- **Embeddings**: A 768-dimensional vector embedding is generated and stored via pgvector for similarity search

### Step 15: Publish

The episode is published to multiple destinations:
- **R2**: Audio file, cover art, OG image, Instagram image, PDF transcript, peaks JSON, text transcript
- **PostgreSQL**: Full episode record with metadata, tags, embeddings
- **Recovery**: If publication fails, the episode is saved to a recovery folder for manual retrieval

### Step 16: Post-Publish

After successful publication:
- **Wasabi backup**: Audio and images archived to S3-compatible backup storage
- **Vercel deploy**: Website rebuild triggered via deploy hook
- **Publication webhook**: Full episode payload sent to external systems (e.g., n8n for syndication to Telegram, Twitter/X, Substack)
- **Email notification**: Success/failure notification with cost breakdown

## Two-Pass Editing Design

The two-pass editing pipeline replaced an earlier single-pass verification agent that used a different LLM provider. The two-pass approach provides:

1. **Separation of concerns**: Pass 1 handles factual accuracy, Pass 2 handles style/flow
2. **Fail-open safety**: Each pass independently fails gracefully
3. **Shrinkage guards**: Prevents the editing passes from accidentally truncating content
4. **Raw output**: No JSON wrapping eliminates parsing failures and truncation risks

## TTS Architecture

### Voice Conditionals

Voice embeddings are pre-computed once and cached in object storage. At generation time, the TTS engine downloads these embeddings instead of processing raw voice samples — saving ~5-10 seconds per segment.

### Parallel Workers

TTS is the most time-consuming step. Segments are split across 2 T4 GPU workers:
- 80 segments / 2 workers = 40 segments each
- Each worker loads the model once, processes all its segments
- Maximum 6 worker containers total (supports 3 concurrent episodes)

### Segment Chunking

Long dialogue lines are split into chunks of ~250 characters to reduce TTS hallucinations. Splits occur at sentence boundaries where possible.
