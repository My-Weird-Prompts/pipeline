# Voice Samples

This directory holds voice samples for the Chatterbox TTS engine. Voice samples are not included in the repository for privacy reasons.

## Directory Structure

```
config/voices/
  corn/           # Corn (main host) voice samples
  herman/         # Herman (co-host) voice samples
```

## Adding Your Own Voice Samples

1. Record a 1-minute WAV clip of each speaker (mono, 22050 Hz is ideal)
2. Place the files in the appropriate subdirectory:
   - `config/voices/corn/corn-1min.wav`
   - `config/voices/herman/herman-1min.wav`
3. Update `VOICE_SAMPLE_URLS` in `pipeline/config/constants.py` to point to your hosted files, or use local paths

## Pre-computing Voice Conditionals

For faster TTS, you can pre-compute voice embeddings:

```bash
python pipeline/scripts/precompute_voice_conditionals.py --upload
```

This generates `.pt` files that skip the voice processing step during generation, saving ~5-10 seconds per TTS segment.

## Tips

- Shorter samples (~1 minute) work better with Chatterbox TTS and reduce hallucinations
- Use clean, clear speech with minimal background noise
- Mono audio is preferred over stereo
