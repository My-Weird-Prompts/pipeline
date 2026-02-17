"""
MWP Episode Generator - Webhook API

A Modal-based webhook API for generating podcast episodes from audio URLs.
The web recording UI has been removed for security - use Fillout or another
form builder to submit audio via the /webhook/generate endpoint.

Usage:
    modal deploy modal_app/recording_app.py

Web Endpoints:
    GET / - API info
    POST /webhook/generate - Generate episode (requires X-Webhook-Secret header)
    GET /status/{job_id} - Check job status
    GET /health - Health check

For the archived web UI version, see: recording_app_with_ui.py.archive
"""

import os
import sys
import json
import uuid
import hmac
import hashlib
import time
from pathlib import Path
from datetime import datetime

import modal

# ============================================================================
# MODAL APP DEFINITION
# ============================================================================

app = modal.App("mwp-recording-app")

# Modal GPU pricing (per second) - used to calculate compute costs
# Source: https://modal.com/pricing
MODAL_GPU_RATES = {
    "T4": 0.000164,      # ~$0.59/hr
    "A10G": 0.000306,    # ~$1.10/hr
    "L4": 0.000222,      # ~$0.80/hr
    "A100": 0.001012,    # ~$3.64/hr (40GB)
}
CURRENT_GPU = "T4"  # Must match gpu= in @app.function decorator

# GPU image for generation
pipeline_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git", "curl")
    .pip_install("ffmpeg-normalize>=1.28.0")
    # PyTorch with CUDA support
    .pip_install("torch>=2.0.0", "torchaudio>=2.0.0")
    # Chatterbox TTS
    .pip_install("chatterbox-tts>=0.1.6")
    # Core dependencies
    .pip_install(
        "google-genai>=0.5.0",
        "fal-client>=0.5.0",
        "psycopg2-binary>=2.9.9",
        "boto3>=1.34.0",
        "pydub>=0.25.1",
        "Pillow>=10.2.0",
        "requests>=2.31.0",
        "httpx>=0.27.0",
        "python-dotenv>=1.0.0",
        "resend>=2.0.0",
        "reportlab>=4.0.0",  # PDF transcript generation
    )
    # Mount local code directories
    .add_local_dir("pipeline", remote_path="/app/pipeline")
    .add_local_dir("config", remote_path="/app/config")
    .add_local_dir("system-prompts", remote_path="/app/system-prompts")
)

# Lightweight image for web endpoints (no GPU needed)
web_image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "fastapi>=0.109.0",
    "python-multipart>=0.0.6",
    "boto3>=1.34.0",
    "psycopg2-binary>=2.9.9",
)

# Secrets from Modal dashboard
secrets = modal.Secret.from_name("mwp-secrets")
vercel_secret = modal.Secret.from_name("mwp-secrets-vercel")

# Volume for intermediate files
volume = modal.Volume.from_name("mwp-working-files", create_if_missing=True)

# Parallel TTS configuration
# Trade-off: fewer workers = slightly longer per episode, but:
# - Less model loading overhead (cost savings)
# - More concurrent episodes before hitting GPU limits
# - concurrency_limit ensures graceful queueing under load
TTS_WORKERS = 2  # Number of parallel GPU workers per episode
TTS_GPU = "T4"   # GPU type for TTS workers (cheapest option)


# ============================================================================
# PARALLEL TTS WORKER
# ============================================================================


@app.function(
    image=pipeline_image,
    secrets=[secrets],
    volumes={"/working": volume},
    gpu=TTS_GPU,
    timeout=900,  # 15 min per batch (more segments per worker now)
    max_containers=6,  # Max 6 workers total = 3 concurrent episodes (3×2)
)
def tts_worker(batch: list[dict], output_dir: str) -> list[dict]:
    """
    Process a batch of TTS segments on a single GPU worker.

    Each worker loads the model once and processes multiple segments,
    amortizing the model loading cost across segments.

    Args:
        batch: List of dicts with segment_idx, speaker, text
        output_dir: Directory to save output files (on shared volume)

    Returns:
        List of result dicts with segment_idx, path, success, etc.
    """
    import sys
    sys.path.insert(0, "/app")

    from pipeline.tts.chatterbox import (
        get_chatterbox_model,
        get_voice_conditionals,
        VOICE_CONDITIONALS_URLS,
    )
    from pathlib import Path
    import subprocess
    import torchaudio

    # Pre-load model and conditionals once for this worker
    print(f"[TTS Worker] Loading model and conditionals for {len(batch)} segments...")
    model = get_chatterbox_model()

    # Pre-load all voice conditionals we'll need
    voices_needed = set(seg["speaker"].lower() for seg in batch)
    for voice in voices_needed:
        voice_name = voice if voice in VOICE_CONDITIONALS_URLS else "herman"
        get_voice_conditionals(voice_name)

    print(f"[TTS Worker] Model ready, processing {len(batch)} segments...")

    results = []
    output_path_base = Path(output_dir)
    output_path_base.mkdir(parents=True, exist_ok=True)

    for seg in batch:
        idx = seg["segment_idx"]
        speaker = seg["speaker"].lower()
        text = seg["text"]

        output_path = output_path_base / f"segment_{idx:04d}_{speaker}.mp3"

        try:
            # Check if already exists (checkpoint)
            if output_path.exists():
                results.append({
                    "segment_idx": idx,
                    "path": str(output_path),
                    "chars": len(text),
                    "success": True,
                    "from_checkpoint": True,
                })
                print(f"  [{idx}] Checkpoint exists")
                continue

            # Use correct voice
            voice_name = speaker if speaker in VOICE_CONDITIONALS_URLS else "herman"
            conds = get_voice_conditionals(voice_name)
            model.conds = conds

            # Generate audio
            wav = model.generate(text)

            # Save as WAV first
            wav_output = output_path.with_suffix(".wav")
            torchaudio.save(str(wav_output), wav.cpu(), model.sr)

            # Convert to MP3
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(wav_output), "-codec:a", "libmp3lame",
                 "-b:a", "96k", str(output_path)],
                check=True, capture_output=True,
            )
            wav_output.unlink()

            results.append({
                "segment_idx": idx,
                "path": str(output_path),
                "chars": len(text),
                "success": True,
                "from_checkpoint": False,
            })
            print(f"  [{idx}] Generated: {text[:40]}...")

        except Exception as e:
            results.append({
                "segment_idx": idx,
                "path": None,
                "chars": len(text),
                "success": False,
                "error": str(e),
                "from_checkpoint": False,
            })
            print(f"  [{idx}] FAILED: {e}")

    # Commit volume changes so orchestrator can see the files
    volume.commit()
    print(f"[TTS Worker] Complete: {sum(1 for r in results if r['success'])}/{len(batch)} succeeded, volume committed")
    return results


def generate_dialogue_audio_parallel(
    segments: list,
    episode_dir: Path,
    num_workers: int = TTS_WORKERS,
    progress_callback=None,
) -> tuple:
    """
    Generate dialogue audio using parallel TTS workers.

    Distributes segments across multiple GPU workers for parallel processing.
    Each worker loads the model once and processes its batch of segments.

    Args:
        segments: List of dicts with 'speaker' and 'text' keys
        episode_dir: Directory to save segment audio files
        num_workers: Number of parallel workers (default: TTS_WORKERS)
        progress_callback: Optional callback (not used in parallel mode)

    Returns:
        Tuple of (dialogue_path, stats)
    """
    import subprocess
    import re

    # Chatterbox has a ~40 second audio output limit. Split long segments
    # into chunks at sentence boundaries to avoid cutoffs.
    MAX_CHARS_PER_TTS = 250  # ~30 seconds of audio at normal speech rate

    def chunk_long_text(text: str, max_chars: int = MAX_CHARS_PER_TTS) -> list[str]:
        """Split long text into chunks at sentence boundaries."""
        if len(text) <= max_chars:
            return [text]

        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = ""

        for sentence in sentences:
            if current_chunk and len(current_chunk) + len(sentence) + 1 > max_chars:
                chunks.append(current_chunk.strip())
                current_chunk = sentence
            else:
                current_chunk = (current_chunk + " " + sentence).strip() if current_chunk else sentence

        if current_chunk:
            chunks.append(current_chunk.strip())

        # Handle edge case: single sentence longer than max_chars
        final_chunks = []
        for chunk in chunks:
            if len(chunk) > max_chars * 1.5:
                parts = re.split(r'(?<=[,;])\s+', chunk)
                sub_chunk = ""
                for part in parts:
                    if sub_chunk and len(sub_chunk) + len(part) + 1 > max_chars:
                        final_chunks.append(sub_chunk.strip())
                        sub_chunk = part
                    else:
                        sub_chunk = (sub_chunk + " " + part).strip() if sub_chunk else part
                if sub_chunk:
                    final_chunks.append(sub_chunk.strip())
            else:
                final_chunks.append(chunk)

        return final_chunks

    # Use shared volume for TTS segments (workers mount volume at /working)
    # Episode name is the last component of episode_dir
    episode_name = episode_dir.name
    segments_dir = Path(f"/working/tts_segments_{episode_name}")
    segments_dir.mkdir(parents=True, exist_ok=True)

    # Expand segments by chunking long texts to avoid Chatterbox output cutoffs
    segment_data = []
    chunked_count = 0
    for i, seg in enumerate(segments):
        chunks = chunk_long_text(seg["text"])
        if len(chunks) > 1:
            chunked_count += 1
            print(f"  Segment {i+1} ({seg['speaker']}): {len(seg['text'])} chars -> split into {len(chunks)} chunks")
        for chunk_idx, chunk_text in enumerate(chunks):
            segment_data.append({
                "segment_idx": len(segment_data),
                "speaker": seg["speaker"],
                "text": chunk_text,
                "original_idx": i,
                "chunk_idx": chunk_idx,
            })

    if chunked_count > 0:
        print(f"  Chunked {chunked_count} long segments into {len(segment_data)} total TTS segments")

    # Split into batches for workers
    batch_size = max(1, len(segment_data) // num_workers)
    batches = []
    for i in range(0, len(segment_data), batch_size):
        batches.append(segment_data[i:i + batch_size])

    # Limit to num_workers batches (merge last batches if needed)
    while len(batches) > num_workers:
        batches[-2].extend(batches[-1])
        batches.pop()

    print(f"\n[Parallel TTS] Distributing {len(segment_data)} TTS segments across {len(batches)} workers")
    print(f"  Output dir: {segments_dir}")
    for i, batch in enumerate(batches):
        print(f"  Worker {i+1}: {len(batch)} segments")

    # Launch parallel workers using Modal's .map()
    output_dir = str(segments_dir)
    start_time = time.time()

    # Use starmap to pass batch and output_dir to each worker
    results_lists = list(tts_worker.starmap(
        [(batch, output_dir) for batch in batches]
    ))

    elapsed = time.time() - start_time
    print(f"\n[Parallel TTS] All workers complete in {elapsed:.1f}s")

    # Reload volume to see files written by workers
    volume.reload()
    print(f"  Volume reloaded, checking for segment files...")

    # Flatten results and sort by segment_idx
    all_results = []
    for results in results_lists:
        all_results.extend(results)
    all_results.sort(key=lambda r: r["segment_idx"])

    # Validate all segments succeeded
    failed = [r for r in all_results if not r["success"]]
    if failed:
        failure_rate = len(failed) / len(all_results) if all_results else 1.0
        print(f"  WARNING: {len(failed)}/{len(all_results)} segments failed ({failure_rate:.0%})!")
        for r in failed[:5]:
            print(f"    Segment {r['segment_idx']}: {r.get('error', 'unknown')}")
        # Abort if more than 20% of segments failed
        MAX_FAILURE_RATE = 0.20
        if failure_rate > MAX_FAILURE_RATE:
            raise RuntimeError(
                f"TTS failure rate too high: {len(failed)}/{len(all_results)} segments failed ({failure_rate:.0%}). "
                f"Max allowed: {MAX_FAILURE_RATE:.0%}. Aborting to prevent short episode."
            )

    # Collect segment files in order
    segment_files = []
    total_chars = 0
    missing_files = []
    for result in all_results:
        if result["success"] and result["path"]:
            seg_path = Path(result["path"])
            if seg_path.exists():
                segment_files.append(seg_path)
                total_chars += result["chars"]
            else:
                missing_files.append(result["segment_idx"])

    if missing_files:
        print(f"  WARNING: {len(missing_files)} segment files missing: {missing_files[:10]}")

    if not segment_files:
        raise RuntimeError("No valid segment files to concatenate!")

    # Concatenate all segments
    print(f"Concatenating {len(segment_files)} segments...")
    dialogue_path = episode_dir / "dialogue.mp3"

    concat_file = segments_dir / "concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for segment_file in segment_files:
            f.write(f"file '{segment_file.absolute()}'\n")

    # Run ffmpeg with visible error output
    result = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
         "-codec:a", "libmp3lame", "-b:a", "96k", str(dialogue_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"FFmpeg stderr: {result.stderr}")
        print(f"FFmpeg stdout: {result.stdout}")
        print(f"Concat file contents (first 20 lines):")
        with open(concat_file, "r") as f:
            for i, line in enumerate(f):
                if i >= 20:
                    break
                print(f"  {line.rstrip()}")
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)

    # Commit volume changes so files are visible
    volume.commit()

    stats = {
        "engine": "chatterbox-parallel",
        "total_chars": total_chars,
        "parallel_workers": len(batches),
        "parallel_time_seconds": elapsed,
        "cost_usd": 0.0,
        "segments_original": len(segments),  # Original dialogue turns
        "segments_total": len(segment_data),  # After chunking (may be larger)
        "segments_succeeded": len(segment_files),
        "segments_failed": len(failed),
        "segments_chunked": chunked_count,  # How many were split
    }

    return dialogue_path, stats


# ============================================================================
# PROGRESS TRACKING
# ============================================================================


def update_progress(job_id: str, stage: str, current: int, total: int, message: str):
    """Update job progress in Neon database."""
    if not job_id:
        print(f"  [{stage}] {message} ({current}/{total})")
        return

    try:
        import psycopg2

        postgres_url = os.environ.get("POSTGRES_URL") or os.environ.get(
            "NEON_DATABASE_URL"
        )
        if not postgres_url:
            return

        stages = [
            "transcription",
            "metadata",
            "cover_art",
            "tts",
            "assembly",
            "publish",
        ]
        stage_idx = stages.index(stage) if stage in stages else 0
        stage_weight = 100 / len(stages)
        overall = int(
            stage_idx * stage_weight + (current / max(total, 1)) * stage_weight
        )

        conn = psycopg2.connect(postgres_url)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE jobs SET
                    current_step = %s,
                    progress_percent = %s,
                    status = 'running'
                WHERE job_id = %s
            """,
                (message, overall, job_id),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"  Warning: Failed to update progress: {e}")


def _update_job_status(job_id: str | None, status: str, step: str, *, progress: int | None = None):
    """Update job status in the database. Fails silently on errors."""
    if not job_id:
        return
    try:
        import psycopg2
        postgres_url = os.environ.get("POSTGRES_URL") or os.environ.get("NEON_DATABASE_URL")
        if not postgres_url:
            return
        conn = psycopg2.connect(postgres_url)
        try:
            cur = conn.cursor()
            sets = ["status = %s", "current_step = %s"]
            params: list = [status, step]
            if progress is not None:
                sets.append("progress_percent = %s")
                params.append(progress)
            if status in ('completed', 'failed'):
                sets.append("completed_at = NOW()")
            if status == 'running':
                sets.append("started_at = NOW()")
            where = "job_id = %s"
            params.append(job_id)
            if status == 'running':
                where += " AND status = 'queued'"
            cur.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE {where}", params)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"  Warning: Failed to update job status: {e}")


# ============================================================================
# SHARED FINALIZATION (used by both generation pipelines)
# ============================================================================


def _finalize_episode(
    *,
    episode_dir,
    episode_path,
    episode_name,
    metadata,
    script,
    segments,
    cover_art_paths,
    tts_stats,
    job_id,
    prompt_transcript,
    llm_model,
    generation_start_time,
    degradation,
    pipeline_label="standard",
):
    """
    Shared post-TTS finalization: duration check, peaks, categorize, tag,
    embed, publish, cost logging, Wasabi backup, Vercel deploy, job status.

    Returns a result dict (success or failure).
    """
    import psycopg2
    import subprocess as _sp

    from episode_recovery import (
        save_episode_for_recovery,
        send_error_notification,
        deploy_with_retry,
    )
    from pipeline.core import (
        categorize_episode,
        tag_episode,
        generate_episode_embedding,
    )
    from pipeline.publishing import publish_episode

    # --- Duration validation ---
    MIN_EPISODE_DURATION_SECONDS = 600  # 10 minutes
    try:
        probe_result = _sp.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(episode_path)],
            capture_output=True, text=True, timeout=30,
        )
        episode_duration_seconds = float(probe_result.stdout.strip())
        duration_str = f"{int(episode_duration_seconds // 60)}:{int(episode_duration_seconds % 60):02d}"
        print(f"  Episode duration: {duration_str}")

        if episode_duration_seconds < MIN_EPISODE_DURATION_SECONDS:
            min_str = f"{int(MIN_EPISODE_DURATION_SECONDS // 60)}:{int(MIN_EPISODE_DURATION_SECONDS % 60):02d}"
            error_msg = (
                f"Episode duration ({duration_str}) is below minimum ({min_str}). "
                f"TTS stats: {tts_stats.get('segments_succeeded', '?')}/{tts_stats.get('segments_total', '?')} segments succeeded, "
                f"{tts_stats.get('segments_failed', '?')} failed. "
                f"This indicates a generation failure."
            )
            print(f"  ERROR: {error_msg}")

            recovery_path = save_episode_for_recovery(
                episode_dir=episode_dir,
                episode_path=episode_path,
                metadata=metadata,
                cover_art_path=None,
                script=script,
                error_message=error_msg,
                job_id=job_id,
            )
            send_error_notification(
                error_message=error_msg,
                stage="duration_check",
                job_id=job_id,
                recovery_path=recovery_path,
                metadata=metadata,
            )
            return {
                "success": False,
                "error": error_msg,
                "recovery_path": recovery_path,
                "episode_name": episode_name,
                "title": metadata.get("title"),
                "duration": duration_str,
                "recoverable": False,
                "message": "Episode too short - generation likely failed. NOT published.",
            }
    except Exception as e:
        MIN_EPISODE_FILE_SIZE = 3 * 1024 * 1024  # 3MB minimum
        file_size = episode_path.stat().st_size if episode_path.exists() else 0
        if file_size < MIN_EPISODE_FILE_SIZE:
            raise RuntimeError(
                f"Duration check failed ({e}) and episode file is suspiciously small "
                f"({file_size / 1024 / 1024:.1f}MB, minimum {MIN_EPISODE_FILE_SIZE / 1024 / 1024:.0f}MB). "
                f"Refusing to publish."
            )
        print(f"  Warning: ffprobe failed ({e}), but file size OK ({file_size / 1024 / 1024:.1f}MB). Proceeding.")

    # --- Waveform peaks (fail-open) ---
    peaks_url = None
    try:
        from pipeline.generators.waveform_peaks import extract_peaks
        from pipeline.storage.r2 import upload_episode_peaks
        peaks_json = extract_peaks(episode_path)
        peaks_url = upload_episode_peaks(episode_name, peaks_json)
        print(f"  Waveform peaks: {peaks_url}")
    except Exception as e:
        print(f"  Warning: Peaks generation failed (non-fatal): {e}")

    # --- Categorize, tag, embed ---
    category_result = categorize_episode(
        title=metadata.get("title", ""), description=metadata.get("description", "")
    )

    tags = tag_episode(
        title=metadata.get("title", ""),
        description=metadata.get("description", ""),
        save_registry=True,
    )
    metadata['tags'] = tags
    print(f"  Tags: {tags}")

    embedding = generate_episode_embedding(
        title=metadata.get("title", ""),
        description=metadata.get("description", ""),
        transcript=script[:4000] if script else None,
    )
    metadata['embedding'] = embedding

    # --- Publish (with recovery on failure) ---
    print("\nPublishing episode...")
    update_progress(job_id, "publish", 0, 100, "Publishing to R2...")

    publish_result = None
    publish_error = None

    try:
        publish_result = publish_episode(
            episode_dir=episode_dir,
            episode_path=episode_path,
            metadata=metadata,
            cover_art_paths=cover_art_paths,
            script=script,
            prompt_transcript=prompt_transcript,
            category=category_result.get("category"),
            subcategory=category_result.get("subcategory"),
            tts_engine="chatterbox-local",
            llm_model=llm_model,
            peaks_url=peaks_url,
        )

        if not publish_result or not publish_result.get("audio_url"):
            raise RuntimeError("Publication failed: no audio URL returned")

        update_progress(job_id, "publish", 100, 100, "Published!")

    except Exception as e:
        publish_error = str(e)
        print(f"\n  ERROR: Publication failed: {e}")
        update_progress(job_id, "publish", 50, 100, f"Publication failed: {str(e)[:50]}")

        print("\n  Saving episode for recovery...")
        recovery_path = save_episode_for_recovery(
            episode_dir=episode_dir,
            episode_path=episode_path,
            metadata=metadata,
            cover_art_path=cover_art_paths[0] if cover_art_paths else None,
            script=script,
            error_message=str(e),
            job_id=job_id,
        )
        send_error_notification(
            error_message=str(e),
            stage="publish",
            job_id=job_id,
            recovery_path=recovery_path,
            metadata=metadata,
        )

        _update_job_status(job_id, 'failed', f"Failed at publish. Recovery: {recovery_path}")

        return {
            "success": False,
            "error": publish_error,
            "recovery_path": recovery_path,
            "episode_name": episode_name,
            "title": metadata.get("title"),
            "recoverable": True,
            "message": "Episode generated but publication failed. See recovery_path for saved files.",
        }

    # --- Cost calculation + logging ---
    generation_time = time.time() - generation_start_time
    tts_parallel_time = tts_stats.get('parallel_time_seconds', 0)
    tts_num_workers = tts_stats.get('parallel_workers', 1)
    tts_gpu_cost = tts_parallel_time * tts_num_workers * MODAL_GPU_RATES.get(TTS_GPU, 0.000164)
    orchestrator_cost = generation_time * 0.000012
    modal_compute_cost = tts_gpu_cost + orchestrator_cost

    print(f"\n{'=' * 60}")
    print(f"Episode published successfully!{' (' + pipeline_label + ')' if pipeline_label != 'standard' else ''}")
    print(f"Title: {metadata.get('title')}")
    print(f"Audio URL: {publish_result.get('audio_url')}")
    print(f"TTS Workers: {tts_num_workers} x {TTS_GPU}")
    print(f"TTS Time: {tts_parallel_time:.1f}s (wall clock)")
    print(f"Modal Compute: ${modal_compute_cost:.4f} (TTS: ${tts_gpu_cost:.4f}, orchestrator: ${orchestrator_cost:.4f})")
    print(f"Total Generation Time: {generation_time/60:.1f} minutes")
    if degradation.has_warnings():
        print(f"Warnings: {len(degradation.warnings)}")
        for w in degradation.warnings:
            print(f"  - {w}")
    print(f"{'=' * 60}\n")

    # --- Wasabi backup ---
    try:
        from pipeline.storage.wasabi import upload_episode as upload_episode_wasabi
        wasabi_url = upload_episode_wasabi(episode_dir, episode_path)
        if wasabi_url:
            print(f"  Episode backed up to Wasabi: {wasabi_url}")
    except Exception as e:
        print(f"  Warning: Wasabi episode backup skipped: {e}")

    # --- Vercel deployment ---
    vercel_hook = os.environ.get("VERCEL_DEPLOY_HOOK")
    if vercel_hook:
        print("Triggering Vercel deployment...")
        deploy_success = deploy_with_retry(
            deploy_hook_url=vercel_hook,
            title=metadata.get("title", "Untitled Episode"),
            max_retries=3,
            initial_delay=5.0,
        )
        if deploy_success:
            print("  Vercel deployment triggered successfully")
        else:
            print("  Warning: Vercel deployment failed - site may need manual rebuild")
    else:
        print("  Warning: VERCEL_DEPLOY_HOOK not set - skipping deployment")

    # --- Update job status to completed ---
    _update_job_status(job_id, 'completed', 'Episode published successfully', progress=100)

    # --- Return success ---
    result = {
        "success": True,
        "episode_name": episode_name,
        "title": metadata.get("title"),
        "description": metadata.get("description"),
        "audio_url": publish_result.get("audio_url"),
        "cover_url": publish_result.get("cover_url"),
        "slug": publish_result.get("slug"),
        "tts_engine": tts_stats.get("engine"),
        "tts_cost_usd": tts_stats.get("cost_usd", 0),
        "tts_workers": tts_num_workers,
        "tts_parallel_time_seconds": tts_parallel_time,
        "modal_compute_cost_usd": modal_compute_cost,
        "modal_gpu": TTS_GPU,
        "segments_count": len(segments),
        "generation_time_seconds": generation_time,
        "warnings": degradation.warnings if degradation.has_warnings() else [],
    }
    if pipeline_label != "standard":
        result["pipeline"] = pipeline_label
    return result


# ============================================================================
# MAIN GENERATION FUNCTION
# ============================================================================


@app.function(
    image=pipeline_image,
    secrets=[secrets, vercel_secret],
    volumes={"/working": volume},
    # No GPU needed - TTS runs in parallel workers with their own GPUs
    timeout=1800,  # 30 min - parallel TTS should complete in ~10-15 min
    retries=1,
    max_containers=3,  # Max 3 concurrent episode generations (jobs queue when limit reached)
)
def generate_episode(
    audio_url: str,
    job_id: str = None,
    sender_type: str = "daniel",
    sender_name: str = None,
    sender_description: str = None,
    attachment_url: str = None,
) -> dict:
    """
    Generate a complete podcast episode from an audio prompt URL.

    Pipeline: transcribe → plan → generate script → review (Pass 1) → polish (Pass 2) → TTS → assemble → publish

    Args:
        audio_url: URL to the audio file (typically R2)
        job_id: Optional job ID for progress tracking
        sender_type: Who sent the prompt ("daniel", "hannah", or "other")
        sender_name: Name of sender (for "other" type)
        sender_description: Brief description of sender (for "other" type)
        attachment_url: Optional URL to an attachment file

    Returns:
        dict with episode data (slug, urls, metadata, costs)
    """
    import requests
    import psycopg2

    # Track generation start time for metrics
    generation_start_time = time.time()

    # Update job status from 'queued' to 'running' now that we've been dequeued
    _update_job_status(job_id, 'running', 'Starting generation...')

    # Add pipeline to path
    sys.path.insert(0, "/app")
    sys.path.insert(0, "/app/pipeline/generators")

    # Import recovery and fault tolerance utilities
    from episode_recovery import (
        save_episode_for_recovery,
        send_error_notification,
        send_success_notification_with_details,
        send_generation_started_notification,
        deploy_with_retry,
        GracefulDegradation,
        PipelineCheckpoint,
        get_default_cover_art_url,
    )

    # Initialize graceful degradation tracker for collecting warnings
    degradation = GracefulDegradation()
    metadata = None

    try:
        # Create working directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        episode_name = f"episode_{timestamp}"
        working_dir = Path(f"/working/{job_id or episode_name}")
        working_dir.mkdir(parents=True, exist_ok=True)

        # Download audio from URL (with timeout, size validation, and retry)
        print(f"Downloading audio from {audio_url[:60]}...")
        audio_path = working_dir / "input_audio.mp3"

        from pipeline.generators.episode_recovery import retry_with_backoff

        def _download_audio():
            r = requests.get(audio_url, timeout=120)
            r.raise_for_status()
            return r

        try:
            response = retry_with_backoff(
                _download_audio,
                max_retries=1,
                initial_delay=3.0,
                retryable_exceptions=(
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                ),
                on_retry=lambda attempt, e: print(f"  Audio download retry {attempt}: {e}"),
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Audio download timed out after 120s: {audio_url[:80]}")
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"Audio download failed ({e.response.status_code}): {audio_url[:80]}")
        audio_size = len(response.content)
        if audio_size < 1000:
            raise RuntimeError(f"Audio file too small ({audio_size} bytes) - likely not a valid recording")
        with open(audio_path, "wb") as f:
            f.write(response.content)
        print(f"Audio downloaded: {audio_size} bytes")

        # Import from modular pipeline structure
        from pipeline.core import (
            transcribe_and_generate_script,
            parse_diarized_script,
            generate_episode_metadata,
            categorize_episode,
        )
        from pipeline.audio import (
            concatenate_episode,
            process_prompt_audio,
        )
        from pipeline.publishing import (
            publish_episode,
            generate_cover_art,
        )
        from pipeline.config import (
            EPISODES_DIR,
            VOICE_SAMPLES,
            JINGLES_DIR,
            DISCLAIMER_PATH,
            PROMPT_INTRO_PATH,
            TRANSITION_WHOOSH_PATH,
            LLM_INFO_PATH,
            TTS_INFO_PATH,
        )
        # Note: TTS prewarm happens in parallel workers, not here

        # Create episode directory
        episode_dir = EPISODES_DIR / episode_name
        episode_dir.mkdir(parents=True, exist_ok=True)

        # Build sender context for script generation
        sender_context = {
            "type": sender_type or "daniel",
            "name": sender_name,
            "description": sender_description,
        }

        # Download attachment if present
        attachment_path = None
        attachment_content = None
        if attachment_url:
            try:
                print(f"Downloading attachment from {attachment_url[:60]}...")

                def _download_attachment():
                    r = requests.get(attachment_url, timeout=60)
                    r.raise_for_status()
                    return r

                attachment_response = retry_with_backoff(
                    _download_attachment,
                    max_retries=1,
                    initial_delay=3.0,
                    retryable_exceptions=(
                        requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                    ),
                    on_retry=lambda attempt, e: print(f"  Attachment download retry {attempt}: {e}"),
                )
                attachment_filename = attachment_url.split("/")[-1]
                attachment_path = working_dir / f"attachment_{attachment_filename}"
                with open(attachment_path, "wb") as f:
                    f.write(attachment_response.content)
                print(f"  Attachment downloaded: {len(attachment_response.content)} bytes")

                # For text-based attachments, read content for context
                if attachment_path.suffix.lower() in [".txt", ".md", ".json", ".csv"]:
                    try:
                        attachment_content = attachment_path.read_text(encoding="utf-8")[:10000]  # Limit to 10k chars
                    except Exception:
                        pass
            except Exception as e:
                print(f"  Warning: Failed to download attachment: {e}")

        # Format sender for logging
        if sender_type == "hannah":
            sender_display = "Hannah (special guest episode)"
        elif sender_type == "other":
            sender_display = f"{sender_name or 'Guest'}"
            if sender_description:
                sender_display += f" ({sender_description})"
        else:
            sender_display = "Daniel (default)"

        print(f"\n{'=' * 60}")
        print(f"Generating podcast episode: {episode_name}")
        print(f"TTS: Local Chatterbox (GPU)")
        print(f"Sender: {sender_display}")
        if attachment_url:
            print(f"Attachment: {attachment_url.split('/')[-1]}")
        print(f"{'=' * 60}\n")

        # Step 1: Transcribe and generate script
        print("Step 1: Transcribing audio and generating script...")
        update_progress(job_id, "transcription", 0, 100, "Transcribing audio...")

        processed_prompt_path = episode_dir / "prompt_processed.wav"
        process_prompt_audio(audio_path, processed_prompt_path)

        script, transcript, pipeline_info = transcribe_and_generate_script(
            audio_path,
            sender_context=sender_context,
            attachment_content=attachment_content,
        )
        script_word_count = len(script.split()) if script else 0
        print(f"  Script generated: {len(script)} chars, {script_word_count} words")

        # Validate script length before burning GPU compute on TTS
        MIN_SCRIPT_WORDS = 2000  # A proper episode script should be 3000-6000 words
        if script_word_count < MIN_SCRIPT_WORDS:
            raise RuntimeError(
                f"Script too short ({script_word_count} words, minimum {MIN_SCRIPT_WORDS}). "
                f"LLM may have returned a truncated or refused response. Aborting before TTS."
            )

        with open(episode_dir / "script.txt", "w", encoding="utf-8") as f:
            f.write(script)
        with open(episode_dir / "transcript.txt", "w", encoding="utf-8") as f:
            f.write(transcript or "")

        update_progress(job_id, "transcription", 100, 100, "Script ready")

        # Step 2: Parse script
        print("\nStep 2: Parsing script into segments...")
        segments = parse_diarized_script(script)
        print(f"  Parsed {len(segments)} dialogue segments")

        # Validate segment count - a proper episode should have 30+ dialogue turns
        MIN_SEGMENTS = 10
        if len(segments) < MIN_SEGMENTS:
            raise RuntimeError(
                f"Too few dialogue segments ({len(segments)}, minimum {MIN_SEGMENTS}). "
                f"Script may not have matched expected SPEAKER: text format. Aborting before TTS."
            )

        with open(episode_dir / "segments.json", "w", encoding="utf-8") as f:
            json.dump(segments, f, indent=2, ensure_ascii=False)

        # Step 3: Generate metadata
        print("\nStep 3: Generating metadata...")
        update_progress(job_id, "metadata", 0, 100, "Generating metadata...")
        metadata = generate_episode_metadata(script)
        print(f"  Title: {metadata.get('title', 'Untitled')}")
        update_progress(job_id, "metadata", 100, 100, "Metadata ready")

        # Send "generation started" notification now that we have a title
        send_generation_started_notification(
            title=metadata.get("title", "Untitled Episode"),
            job_id=job_id,
        )

        # Backup prompt to Wasabi (prompts/mmdd/episode-slug.mp3)
        episode_slug = metadata.get("slug", episode_name)
        try:
            from pipeline.storage import backup_prompt_to_wasabi
            backup_url = backup_prompt_to_wasabi(audio_path, episode_slug)
            if backup_url:
                print(f"  Prompt backed up: {backup_url}")
        except Exception as e:
            print(f"  Warning: Prompt backup skipped: {e}")

        # Step 4: Generate cover art (with graceful degradation)
        print("\nStep 4: Generating cover art...")
        update_progress(job_id, "cover_art", 0, 100, "Generating cover art...")
        cover_art_paths = []
        if metadata.get("image_prompt"):
            try:
                cover_art_paths = generate_cover_art(
                    metadata["image_prompt"], episode_dir, num_variants=1
                )
                print(f"  Cover art generated: {len(cover_art_paths)} image(s)")
            except Exception as e:
                # Cover art is non-critical - log warning and continue
                degradation.mark_degraded(
                    "Cover Art",
                    f"Generation failed ({str(e)[:100]}), using default"
                )
                cover_art_paths = []  # Will use default cover
        update_progress(job_id, "cover_art", 100, 100, "Cover art ready")

        # Step 5: Generate dialogue audio (TTS) - PARALLEL
        print("\nStep 5: Generating dialogue audio (parallel)...")
        update_progress(job_id, "tts", 0, len(segments), f"Starting parallel TTS ({TTS_WORKERS} workers)...")

        # Use parallel TTS for speed (parallel workers for faster TTS)
        dialogue_audio_path, tts_stats = generate_dialogue_audio_parallel(
            segments, episode_dir, num_workers=TTS_WORKERS
        )

        print(f"  Dialogue audio generated: {dialogue_audio_path}")
        print(f"  Parallel TTS time: {tts_stats.get('parallel_time_seconds', 0):.1f}s with {tts_stats.get('parallel_workers', 1)} workers")
        update_progress(job_id, "tts", len(segments), len(segments), "TTS complete")

        # Step 6: Assemble final episode
        print("\nStep 6: Assembling final episode...")
        update_progress(job_id, "assembly", 0, 100, "Assembling episode...")

        episode_path = episode_dir / f"{episode_name}.mp3"
        intro_jingle = JINGLES_DIR / "mixed-intro.mp3"
        outro_jingle = JINGLES_DIR / "mixed-outro.mp3"

        concatenate_episode(
            dialogue_audio=dialogue_audio_path,
            output_path=episode_path,
            user_prompt_audio=processed_prompt_path,
            intro_jingle=intro_jingle if intro_jingle.exists() else None,
            disclaimer_audio=DISCLAIMER_PATH if DISCLAIMER_PATH.exists() else None,
            outro_jingle=outro_jingle if outro_jingle.exists() else None,
            prompt_intro_audio=PROMPT_INTRO_PATH if PROMPT_INTRO_PATH.exists() else None,
            transition_audio=TRANSITION_WHOOSH_PATH
            if TRANSITION_WHOOSH_PATH.exists()
            else None,
            llm_info_audio=LLM_INFO_PATH if LLM_INFO_PATH.exists() else None,
            tts_info_audio=TTS_INFO_PATH if TTS_INFO_PATH.exists() else None,
        )
        print(f"  Final episode: {episode_path}")
        update_progress(job_id, "assembly", 100, 100, "Episode assembled")

        # Steps 6.5+: Finalize (duration check, peaks, categorize, tag, embed,
        # publish, cost logging, Wasabi backup, Vercel deploy, job status)
        return _finalize_episode(
            episode_dir=episode_dir,
            episode_path=episode_path,
            episode_name=episode_name,
            metadata=metadata,
            script=script,
            segments=segments,
            cover_art_paths=cover_art_paths,
            tts_stats=tts_stats,
            job_id=job_id,
            prompt_transcript=transcript,
            llm_model=os.environ.get("SCRIPT_MODEL", "gemini-3-flash-preview"),
            generation_start_time=generation_start_time,
            degradation=degradation,
        )

    except Exception as e:
        import traceback
        error_msg = f"Pipeline crashed: {str(e)[:500]}"
        print(f"\n{'!' * 60}")
        print(f"  FATAL ERROR: {error_msg}")
        traceback.print_exc()
        print(f"{'!' * 60}\n")

        # Send error notification
        try:
            send_error_notification(
                error_message=error_msg,
                stage="pipeline_crash",
                job_id=job_id,
                metadata=metadata if metadata else {"audio_url": audio_url},
            )
        except Exception:
            print("  Warning: Could not send error notification")

        # Mark job as failed (prevent zombie jobs)
        _update_job_status(job_id, 'failed', f"Crashed: {str(e)[:200]}")

        return {
            "success": False,
            "error": error_msg,
            "episode_name": None,
            "recoverable": False,
            "message": "Pipeline crashed unexpectedly. Error notification sent.",
        }



# ============================================================================
# MANUAL SCRIPT PIPELINE (skip transcription/generation, go straight to TTS)
# ============================================================================


@app.function(
    image=pipeline_image,
    secrets=[secrets, vercel_secret],
    volumes={"/working": volume},
    timeout=1800,  # 30 min
    retries=1,
    max_containers=3,
)
def generate_episode_from_script(
    script: str,
    job_id: str = None,
    metadata_overrides: dict = None,
    prompt_transcript: str = None,
) -> dict:
    """
    Generate a podcast episode from a pre-written script.

    Skips: audio download, transcription, research, planning, script generation,
    review, and polish. Jumps straight to: parse → metadata → cover art →
    parallel TTS → assemble → publish.

    Assembly skips prompt audio, prompt intro, and transition whoosh since
    there is no original voice prompt.

    Args:
        script: Pre-written diarized script (CORN: ... / HERMAN: ...)
        job_id: Optional job ID for progress tracking
        metadata_overrides: Optional dict to override generated metadata
            (title, slug, description, etc.)
        prompt_transcript: Optional summary of why this episode exists
            (replaces the transcribed prompt in the DB)

    Returns:
        dict with episode data (slug, urls, metadata, costs)
    """
    import psycopg2

    generation_start_time = time.time()

    _update_job_status(job_id, 'running', 'Starting manual script pipeline...')

    sys.path.insert(0, "/app")
    sys.path.insert(0, "/app/pipeline/generators")

    from episode_recovery import (
        save_episode_for_recovery,
        send_error_notification,
        send_generation_started_notification,
        deploy_with_retry,
        GracefulDegradation,
    )

    degradation = GracefulDegradation()
    metadata = None

    try:
        # Validate script
        script_word_count = len(script.split())
        MIN_SCRIPT_WORDS = 2000
        if script_word_count < MIN_SCRIPT_WORDS:
            raise RuntimeError(
                f"Script too short ({script_word_count} words, minimum {MIN_SCRIPT_WORDS})."
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        episode_name = f"episode_{timestamp}"
        working_dir = Path(f"/working/{job_id or episode_name}")
        working_dir.mkdir(parents=True, exist_ok=True)

        from pipeline.core import (
            parse_diarized_script,
            generate_episode_metadata,
            categorize_episode,
            tag_episode,
            generate_episode_embedding,
        )
        from pipeline.audio import concatenate_episode
        from pipeline.publishing import publish_episode, generate_cover_art
        from pipeline.config import (
            EPISODES_DIR,
            JINGLES_DIR,
            DISCLAIMER_PATH,
            LLM_INFO_PATH,
            TTS_INFO_PATH,
        )

        episode_dir = EPISODES_DIR / episode_name
        episode_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'=' * 60}")
        print(f"Manual Script Pipeline: {episode_name}")
        print(f"Script: {script_word_count} words")
        print(f"{'=' * 60}\n")

        # Save script to disk
        with open(episode_dir / "script.txt", "w", encoding="utf-8") as f:
            f.write(script)

        # Step 1: Parse script into segments
        print("Step 1: Parsing script into segments...")
        update_progress(job_id, "transcription", 0, 100, "Parsing script...")
        segments = parse_diarized_script(script)
        print(f"  Parsed {len(segments)} dialogue segments")

        MIN_SEGMENTS = 10
        if len(segments) < MIN_SEGMENTS:
            raise RuntimeError(
                f"Too few dialogue segments ({len(segments)}, minimum {MIN_SEGMENTS}). "
                f"Script may not match expected SPEAKER: text format."
            )

        with open(episode_dir / "segments.json", "w", encoding="utf-8") as f:
            json.dump(segments, f, indent=2, ensure_ascii=False)

        update_progress(job_id, "transcription", 100, 100, "Script parsed")

        # Step 2: Generate metadata
        print("\nStep 2: Generating metadata...")
        update_progress(job_id, "metadata", 0, 100, "Generating metadata...")
        metadata = generate_episode_metadata(script)

        # Apply metadata overrides
        if metadata_overrides:
            for key, value in metadata_overrides.items():
                if value is not None:
                    metadata[key] = value
                    print(f"  Override: {key} = {value}")

        print(f"  Title: {metadata.get('title', 'Untitled')}")
        update_progress(job_id, "metadata", 100, 100, "Metadata ready")

        send_generation_started_notification(
            title=metadata.get("title", "Untitled Episode"),
            job_id=job_id,
        )

        episode_slug = metadata.get("slug", episode_name)

        # Step 3: Generate cover art
        print("\nStep 3: Generating cover art...")
        update_progress(job_id, "cover_art", 0, 100, "Generating cover art...")
        cover_art_paths = []
        if metadata.get("image_prompt"):
            try:
                cover_art_paths = generate_cover_art(
                    metadata["image_prompt"], episode_dir, num_variants=1
                )
                print(f"  Cover art generated: {len(cover_art_paths)} image(s)")
            except Exception as e:
                degradation.mark_degraded(
                    "Cover Art",
                    f"Generation failed ({str(e)[:100]}), using default"
                )
                cover_art_paths = []
        update_progress(job_id, "cover_art", 100, 100, "Cover art ready")

        # Step 4: Parallel TTS
        print("\nStep 4: Generating dialogue audio (parallel)...")
        update_progress(job_id, "tts", 0, len(segments), f"Starting parallel TTS ({TTS_WORKERS} workers)...")

        dialogue_audio_path, tts_stats = generate_dialogue_audio_parallel(
            segments, episode_dir, num_workers=TTS_WORKERS
        )

        print(f"  Dialogue audio generated: {dialogue_audio_path}")
        print(f"  Parallel TTS time: {tts_stats.get('parallel_time_seconds', 0):.1f}s with {tts_stats.get('parallel_workers', 1)} workers")
        update_progress(job_id, "tts", len(segments), len(segments), "TTS complete")

        # Step 5: Assemble episode (no prompt audio, no prompt intro, no transition)
        print("\nStep 5: Assembling final episode...")
        update_progress(job_id, "assembly", 0, 100, "Assembling episode...")

        episode_path = episode_dir / f"{episode_name}.mp3"
        intro_jingle = JINGLES_DIR / "mixed-intro.mp3"
        outro_jingle = JINGLES_DIR / "mixed-outro.mp3"

        concatenate_episode(
            dialogue_audio=dialogue_audio_path,
            output_path=episode_path,
            user_prompt_audio=None,         # No prompt audio
            intro_jingle=intro_jingle if intro_jingle.exists() else None,
            disclaimer_audio=DISCLAIMER_PATH if DISCLAIMER_PATH.exists() else None,
            outro_jingle=outro_jingle if outro_jingle.exists() else None,
            prompt_intro_audio=None,        # No "Here's Daniel's prompt!"
            transition_audio=None,          # No whoosh transition
            llm_info_audio=LLM_INFO_PATH if LLM_INFO_PATH.exists() else None,
            tts_info_audio=TTS_INFO_PATH if TTS_INFO_PATH.exists() else None,
        )
        print(f"  Final episode: {episode_path}")
        update_progress(job_id, "assembly", 100, 100, "Episode assembled")

        # Steps 5.5+: Finalize (duration check, peaks, categorize, tag, embed,
        # publish, cost logging, Wasabi backup, Vercel deploy, job status)
        return _finalize_episode(
            episode_dir=episode_dir,
            episode_path=episode_path,
            episode_name=episode_name,
            metadata=metadata,
            script=script,
            segments=segments,
            cover_art_paths=cover_art_paths,
            tts_stats=tts_stats,
            job_id=job_id,
            prompt_transcript=prompt_transcript or "Manual script episode",
            llm_model="manual-script",
            generation_start_time=generation_start_time,
            degradation=degradation,
            pipeline_label="manual-script",
        )

    except Exception as e:
        import traceback
        error_msg = f"Manual script pipeline crashed: {str(e)[:500]}"
        print(f"\n{'!' * 60}")
        print(f"  FATAL ERROR: {error_msg}")
        traceback.print_exc()
        print(f"{'!' * 60}\n")

        try:
            send_error_notification(
                error_message=error_msg,
                stage="pipeline_crash",
                job_id=job_id,
                metadata=metadata if metadata else {"pipeline": "manual-script"},
            )
        except Exception:
            print("  Warning: Could not send error notification")

        _update_job_status(job_id, 'failed', f"Crashed: {str(e)[:200]}")

        return {
            "success": False,
            "error": error_msg,
            "episode_name": None,
            "recoverable": False,
            "message": "Manual script pipeline crashed. Error notification sent.",
        }


# ============================================================================
# BACKEND MAINTENANCE JOB
# ============================================================================


@app.function(
    image=pipeline_image,
    secrets=[secrets],
    timeout=3600,  # 1 hour max for large backfills
)
def run_maintenance_job(
    job_id: str,
    do_tags: bool = True,
    do_categories: bool = True,
    do_embeddings: bool = True,
    force: bool = False,
    limit: int = None,
    offset: int = 0,
    dry_run: bool = False,
):
    """
    Background job for running backend maintenance tasks.

    Processes episodes that need tagging, categorization, or embeddings.
    """
    import time

    # Add pipeline to path
    sys.path.insert(0, "/app")

    from pipeline.core import tag_episode, generate_episode_embedding, categorize_episode
    from pipeline.database import (
        get_episodes_needing_metadata,
        update_episode_metadata,
        get_episode_count,
        get_all_episodes,
    )

    print(f"\n{'='*60}")
    print(f"Backend Maintenance Job: {job_id}")
    print(f"{'='*60}")
    print(f"Tasks: tags={do_tags}, categories={do_categories}, embeddings={do_embeddings}")
    print(f"Options: force={force}, limit={limit}, offset={offset}, dry_run={dry_run}")

    # Get episodes to process
    if force:
        episodes = get_all_episodes()
    else:
        episodes = get_episodes_needing_metadata(
            check_tags=do_tags,
            check_category=do_categories,
            check_embedding=do_embeddings,
            limit=limit,
            offset=offset,
        )

    total = len(episodes)
    total_in_db = get_episode_count()

    print(f"\nFound {total} episodes to process (total in database: {total_in_db})")

    if not episodes:
        print("No episodes need updating")
        return {"success": True, "processed": 0, "total": total_in_db}

    # Process episodes
    results = {"success": 0, "failed": 0, "errors": []}
    start_time = time.time()

    for i, episode in enumerate(episodes, 1):
        slug = episode["slug"]
        title = episode.get("title", "")
        description = episode.get("description", "")

        print(f"\n[{i}/{total}] {slug}")
        updates = {}
        errors = []

        # Check what needs updating
        existing_tags = episode.get("tags")
        existing_category = episode.get("category")
        existing_embedding = episode.get("embedding")

        needs_tags = do_tags and (
            force or not existing_tags or existing_tags == ["podcast", "ai-generated"]
        )
        needs_category = do_categories and (force or not existing_category)
        needs_embedding = do_embeddings and (force or not existing_embedding)

        # Generate tags
        if needs_tags:
            try:
                tags = tag_episode(title, description, save_registry=not dry_run)
                updates["tags"] = tags
                print(f"  Tags: {tags}")
            except Exception as e:
                errors.append(f"Tags: {e}")
                print(f"  Tags ERROR: {e}")

        # Generate category
        if needs_category:
            try:
                cat_result = categorize_episode(title, description)
                if cat_result.get("category"):
                    updates["category"] = cat_result["category"]
                    updates["subcategory"] = cat_result.get("subcategory")
                    print(f"  Category: {cat_result['category']}")
            except Exception as e:
                errors.append(f"Category: {e}")
                print(f"  Category ERROR: {e}")

        # Generate embedding
        if needs_embedding:
            try:
                embedding = generate_episode_embedding(
                    title, description,
                    transcript=episode.get("transcript", "")[:4000] if episode.get("transcript") else None,
                )
                if embedding:
                    updates["embedding"] = embedding
                    print(f"  Embedding: {len(embedding)} dimensions")
            except Exception as e:
                errors.append(f"Embedding: {e}")
                print(f"  Embedding ERROR: {e}")

        # Update database
        if not dry_run and updates:
            try:
                success = update_episode_metadata(
                    slug=slug,
                    tags=updates.get("tags"),
                    category=updates.get("category"),
                    subcategory=updates.get("subcategory"),
                    embedding=updates.get("embedding"),
                )
                if success:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    errors.append("Database update failed")
            except Exception as e:
                results["failed"] += 1
                errors.append(f"Database: {e}")
        elif dry_run:
            results["success"] += 1
        else:
            results["success"] += 1

        if errors:
            results["errors"].append({"slug": slug, "errors": errors})

        # Rate limiting
        time.sleep(0.5)

    elapsed = time.time() - start_time

    print(f"\n{'='*60}")
    print(f"Maintenance Complete")
    print(f"{'='*60}")
    print(f"Processed: {results['success']} success, {results['failed']} failed")
    print(f"Time: {elapsed:.1f}s")

    return {
        "success": True,
        "job_id": job_id,
        "processed": results["success"],
        "failed": results["failed"],
        "errors": results["errors"][:10],  # Limit error details
        "elapsed_seconds": elapsed,
    }


# ============================================================================
# WEBHOOK API (for Fillout and other form builders)
# ============================================================================


@app.function(image=web_image, secrets=[secrets])
@modal.asgi_app()
def web():
    """Webhook-only API for episode generation (no web UI)."""
    from fastapi import FastAPI, Request, HTTPException

    api = FastAPI(title="MWP Episode Generator API", docs_url="/docs")

    @api.get("/")
    async def root():
        """API info."""
        return {
            "service": "MWP Episode Generator",
            "version": "2.2.0",
            "endpoints": {
                "POST /webhook/generate": "Generate episode from audio URL (requires X-Webhook-Secret header)",
                "POST /webhook/generate-from-script": "Generate episode from pre-written script (requires X-Webhook-Secret header)",
                "GET /status/{job_id}": "Check job status",
                "GET /jobs": "View running and recent jobs",
                "GET /health": "Health check",
            },
            "docs": "/docs",
        }

    @api.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "ok", "service": "mwp-recording-app"}

    @api.get("/jobs")
    async def jobs_status():
        """Get current running, queued, and recent jobs with queue status."""
        import psycopg2

        MAX_CONCURRENT = 3  # Must match concurrency_limit on generate_episode

        postgres_url = os.environ.get("POSTGRES_URL")
        if not postgres_url:
            return {
                "status": "unknown",
                "message": "Database not configured",
            }

        try:
            conn = psycopg2.connect(postgres_url)
            cur = conn.cursor()

            # Get running jobs
            cur.execute("""
                SELECT job_id, current_step, progress_percent, created_at, started_at
                FROM jobs
                WHERE status = 'running'
                AND created_at > NOW() - INTERVAL '2 hours'
                ORDER BY started_at ASC NULLS LAST, created_at ASC
            """)
            running = cur.fetchall()

            # Get queued jobs (waiting to be processed)
            cur.execute("""
                SELECT job_id, current_step, created_at,
                       ROW_NUMBER() OVER (ORDER BY created_at ASC) as queue_position
                FROM jobs
                WHERE status = 'queued'
                AND created_at > NOW() - INTERVAL '2 hours'
                ORDER BY created_at ASC
            """)
            queued = cur.fetchall()

            # Get recent completed jobs
            cur.execute("""
                SELECT job_id, current_step, completed_at
                FROM jobs
                WHERE status = 'completed'
                AND completed_at > NOW() - INTERVAL '1 hour'
                ORDER BY completed_at DESC
                LIMIT 5
            """)
            recent = cur.fetchall()

            # Get recent failed jobs
            cur.execute("""
                SELECT job_id, current_step, completed_at
                FROM jobs
                WHERE status = 'failed'
                AND completed_at > NOW() - INTERVAL '2 hours'
                ORDER BY completed_at DESC
                LIMIT 3
            """)
            failed = cur.fetchall()

            conn.close()

            available_slots = max(0, MAX_CONCURRENT - len(running))

            return {
                "status": "ok",
                "capacity": {
                    "max_concurrent": MAX_CONCURRENT,
                    "running": len(running),
                    "queued": len(queued),
                    "available_slots": available_slots,
                },
                "running_jobs": [
                    {
                        "job_id": r[0],
                        "step": r[1],
                        "progress": r[2],
                        "created_at": str(r[3]),
                        "started_at": str(r[4]) if r[4] else None,
                    }
                    for r in running
                ],
                "queued_jobs": [
                    {
                        "job_id": q[0],
                        "step": q[1],
                        "created_at": str(q[2]),
                        "queue_position": q[3],
                    }
                    for q in queued
                ],
                "recent_completed": [
                    {"job_id": r[0], "step": r[1], "completed": str(r[2])}
                    for r in recent
                ],
                "recent_failed": [
                    {"job_id": r[0], "step": r[1], "completed": str(r[2])}
                    for r in failed
                ],
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }

    @api.get("/status/{job_id}")
    async def get_status(job_id: str):
        """Get job status from database, including queue position for queued jobs."""
        postgres_url = os.environ.get("POSTGRES_URL")
        if not postgres_url:
            return {
                "job_id": job_id,
                "status": "unknown",
                "message": "Database not configured",
            }

        try:
            import psycopg2

            conn = psycopg2.connect(postgres_url)
            cur = conn.cursor()

            # Get job details
            cur.execute(
                """
                SELECT status, current_step, progress_percent, created_at, completed_at, started_at
                FROM jobs WHERE job_id = %s
            """,
                (job_id,),
            )
            row = cur.fetchone()

            if not row:
                conn.close()
                return {"job_id": job_id, "status": "not_found"}

            status = row[0]
            result = {
                "job_id": job_id,
                "status": status,
                "current_step": row[1],
                "progress_percent": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
                "completed_at": row[4].isoformat() if row[4] else None,
                "started_at": row[5].isoformat() if row[5] else None,
            }

            # If queued, calculate queue position
            if status == "queued":
                cur.execute(
                    """
                    SELECT COUNT(*) + 1 as position
                    FROM jobs
                    WHERE status = 'queued'
                    AND created_at < (SELECT created_at FROM jobs WHERE job_id = %s)
                    """,
                    (job_id,),
                )
                pos_row = cur.fetchone()
                result["queue_position"] = pos_row[0] if pos_row else 1

                # Also get running count for context
                cur.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'")
                running_row = cur.fetchone()
                result["jobs_ahead"] = (running_row[0] if running_row else 0) + result["queue_position"] - 1

            conn.close()
            return result

        except Exception as e:
            return {"job_id": job_id, "status": "error", "message": str(e)}

    @api.post("/webhook/test")
    async def webhook_test(request: Request):
        """
        Test endpoint to inspect webhook payloads without triggering generation.

        Use this to see exactly what Fillout sends, then configure /webhook/generate accordingly.
        No authentication required for testing.
        """
        try:
            body = await request.json()
        except Exception:
            body = None

        # Log headers and body
        headers_dict = dict(request.headers)

        # Try to extract audio URL using same logic as generate endpoint
        audio_url = None
        extraction_method = None

        if body:
            if "audio_url" in body:
                value = body["audio_url"]
                if isinstance(value, str) and value.startswith("http"):
                    audio_url = value
                    extraction_method = "direct audio_url field (string)"
                elif isinstance(value, dict) and "url" in value:
                    audio_url = value["url"]
                    extraction_method = "audio_url.url (Fillout object format)"
            elif "responses" in body and isinstance(body["responses"], list):
                for response in body["responses"]:
                    if response.get("type") in ["voice_recording", "file_upload", "audio"]:
                        value = response.get("value")
                        if isinstance(value, str) and value.startswith("http"):
                            audio_url = value
                            extraction_method = f"responses[].value (type={response.get('type')})"
                            break
                        elif isinstance(value, dict) and "url" in value:
                            audio_url = value["url"]
                            extraction_method = f"responses[].value.url (type={response.get('type')})"
                            break
                        elif isinstance(value, list) and len(value) > 0:
                            first_file = value[0]
                            if isinstance(first_file, str):
                                audio_url = first_file
                                extraction_method = f"responses[].value[0] (type={response.get('type')})"
                            elif isinstance(first_file, dict) and "url" in first_file:
                                audio_url = first_file["url"]
                                extraction_method = f"responses[].value[0].url (type={response.get('type')})"
                            break
            elif "data" in body and isinstance(body["data"], dict):
                data = body["data"]
                for field_name in ["audio_url", "voice_recording", "audio", "recording", "file"]:
                    if field_name in data:
                        value = data[field_name]
                        if isinstance(value, str) and value.startswith("http"):
                            audio_url = value
                            extraction_method = f"data.{field_name}"
                            break
                        elif isinstance(value, dict) and "url" in value:
                            audio_url = value["url"]
                            extraction_method = f"data.{field_name}.url"
                            break

        return {
            "test_result": "success",
            "message": "Payload received and parsed (no episode generated)",
            "audio_url_found": audio_url,
            "extraction_method": extraction_method,
            "webhook_secret_header_present": "X-Webhook-Secret" in headers_dict,
            "content_type": headers_dict.get("content-type"),
            "payload_keys": list(body.keys()) if body else None,
            "full_payload": body,
            "headers": {k: v for k, v in headers_dict.items() if k.lower() not in ["authorization", "x-webhook-secret"]},
        }

    @api.post("/webhook/generate")
    async def webhook_generate(request: Request):
        """
        Webhook endpoint for external form builders like Fillout.

        Authentication: Requires X-Webhook-Secret header matching WEBHOOK_SECRET env var.

        Accepts JSON payload with:
        - audio_url: Direct URL to audio file (required)
        - sender: Sender info object with type/name/description (optional)
        - attachment_url: URL to attachment file (optional)

        Example Fillout setup:
        1. Create a form with a voice recording field
        2. Add a webhook integration pointing to this URL
        3. Set the X-Webhook-Secret header to your secret
        4. Map the voice recording URL to the audio_url field
        """
        # Validate webhook secret
        webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
        if not webhook_secret:
            raise HTTPException(
                status_code=500,
                detail="WEBHOOK_SECRET not configured. Add it to Modal secrets."
            )

        request_secret = request.headers.get("X-Webhook-Secret", "")
        if not hmac.compare_digest(request_secret, webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

        # Parse request body
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        # Extract audio URL - support various payload formats
        audio_url = None

        # Direct audio_url field (string or object with url)
        if "audio_url" in body:
            value = body["audio_url"]
            if isinstance(value, str) and value.startswith("http"):
                audio_url = value
            elif isinstance(value, dict) and "url" in value:
                audio_url = value["url"]

        # Fillout format: responses array with voice recording
        elif "responses" in body and isinstance(body["responses"], list):
            for response in body["responses"]:
                # Look for voice recording or file upload fields
                if response.get("type") in ["voice_recording", "file_upload", "audio"]:
                    value = response.get("value")
                    if isinstance(value, str) and value.startswith("http"):
                        audio_url = value
                        break
                    elif isinstance(value, dict) and "url" in value:
                        audio_url = value["url"]
                        break
                    elif isinstance(value, list) and len(value) > 0:
                        first_file = value[0]
                        if isinstance(first_file, str):
                            audio_url = first_file
                        elif isinstance(first_file, dict) and "url" in first_file:
                            audio_url = first_file["url"]
                        break

        # Fillout simplified format: data object
        elif "data" in body and isinstance(body["data"], dict):
            data = body["data"]
            for field_name in ["audio_url", "voice_recording", "audio", "recording", "file"]:
                if field_name in data:
                    value = data[field_name]
                    if isinstance(value, str) and value.startswith("http"):
                        audio_url = value
                        break
                    elif isinstance(value, dict) and "url" in value:
                        audio_url = value["url"]
                        break

        if not audio_url:
            raise HTTPException(
                status_code=400,
                detail="No audio URL found in payload. Expected 'audio_url' field or Fillout voice recording."
            )

        # Extract sender information
        sender_data = body.get("sender", {})
        if isinstance(sender_data, str):
            # Simple string format - treat as sender type
            sender_data = {"type": sender_data}
        sender_type = sender_data.get("type", "daniel")
        sender_name = sender_data.get("name")
        sender_description = sender_data.get("description")

        # Extract attachment URL if present
        attachment_url = body.get("attachment_url")

        # Generate job ID
        job_id = str(uuid.uuid4())[:8]

        # Record job in database for tracking
        postgres_url = os.environ.get("POSTGRES_URL")
        if postgres_url:
            try:
                import psycopg2
                conn = psycopg2.connect(postgres_url)
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO jobs (
                        job_id, status, current_step, progress_percent, created_at,
                        audio_url, tts_provider,
                        sender_type, sender_name, sender_description, attachment_url
                    )
                    VALUES (%s, 'queued', 'Waiting in queue...', 0, NOW(), %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (job_id) DO NOTHING
                    """,
                    (job_id, audio_url, "local",
                     sender_type, sender_name, sender_description, attachment_url)
                )
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Warning: Failed to create job record: {e}")

        # Check current queue status before spawning
        running_count = 0
        queued_count = 0
        if postgres_url:
            try:
                conn = psycopg2.connect(postgres_url)
                cur = conn.cursor()
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'running') as running,
                        COUNT(*) FILTER (WHERE status = 'queued') as queued
                    FROM jobs
                    WHERE created_at > NOW() - INTERVAL '2 hours'
                """)
                row = cur.fetchone()
                running_count = row[0] or 0
                queued_count = row[1] or 0  # Includes the job we just inserted
                conn.close()
            except Exception:
                pass

        # Spawn generation (Modal queues if concurrency_limit=3 is reached)
        generate_episode.spawn(
            audio_url=audio_url,
            job_id=job_id,
            sender_type=sender_type,
            sender_name=sender_name,
            sender_description=sender_description,
            attachment_url=attachment_url,
        )

        # Determine if this job will run immediately or be queued
        max_concurrent = 3
        will_queue = running_count >= max_concurrent

        return {
            "success": True,
            "job_id": job_id,
            "status": "queued" if will_queue else "started",
            "queue_position": queued_count if will_queue else 0,
            "capacity": {
                "max_concurrent": max_concurrent,
                "running": running_count,
                "queued": queued_count,
                "available_slots": max(0, max_concurrent - running_count),
            },
            "audio_url": audio_url,
            "sender_type": sender_type,
            "has_attachment": attachment_url is not None,
            "message": f"Episode generation {'queued (position {})'.format(queued_count) if will_queue else 'started'}.",
            "status_url": f"/status/{job_id}",
        }

    @api.post("/webhook/generate-from-script")
    async def webhook_generate_from_script(request: Request):
        """
        Generate episode from a pre-written script (skips transcription/generation).

        Authentication: Requires X-Webhook-Secret header matching WEBHOOK_SECRET env var.

        Accepts JSON payload with:
        - script: Pre-written diarized script (CORN: ... / HERMAN: ...) (required)
        - metadata: Optional dict of metadata overrides (title, slug, description, etc.)
        - prompt_transcript: Optional summary of why this episode exists
        """
        # Validate webhook secret
        webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
        if not webhook_secret:
            raise HTTPException(
                status_code=500,
                detail="WEBHOOK_SECRET not configured. Add it to Modal secrets."
            )

        request_secret = request.headers.get("X-Webhook-Secret", "")
        if not hmac.compare_digest(request_secret, webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

        # Parse request body
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        # Extract script (required)
        script = body.get("script")
        if not script or not isinstance(script, str):
            raise HTTPException(
                status_code=400,
                detail="Missing or invalid 'script' field. Must be a non-empty string."
            )

        script_word_count = len(script.split())
        if script_word_count < 2000:
            raise HTTPException(
                status_code=400,
                detail=f"Script too short ({script_word_count} words, minimum 2000)."
            )

        # Extract optional params
        metadata_overrides = body.get("metadata", {})
        if not isinstance(metadata_overrides, dict):
            metadata_overrides = {}
        prompt_transcript = body.get("prompt_transcript", "")

        # Generate job ID
        job_id = str(uuid.uuid4())[:8]

        # Record job in database
        postgres_url = os.environ.get("POSTGRES_URL")
        if postgres_url:
            try:
                import psycopg2
                conn = psycopg2.connect(postgres_url)
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO jobs (
                        job_id, status, current_step, progress_percent, created_at,
                        audio_url, tts_provider, sender_type
                    )
                    VALUES (%s, 'queued', 'Waiting in queue (manual script)...', 0, NOW(), %s, %s, %s)
                    ON CONFLICT (job_id) DO NOTHING
                    """,
                    (job_id, "manual-script", "local", "daniel")
                )
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Warning: Failed to create job record: {e}")

        # Spawn generation
        generate_episode_from_script.spawn(
            script=script,
            job_id=job_id,
            metadata_overrides=metadata_overrides if metadata_overrides else None,
            prompt_transcript=prompt_transcript or None,
        )

        return {
            "success": True,
            "job_id": job_id,
            "status": "started",
            "pipeline": "manual-script",
            "script_word_count": script_word_count,
            "has_metadata_overrides": bool(metadata_overrides),
            "message": "Manual script episode generation started.",
            "status_url": f"/status/{job_id}",
        }

    @api.post("/admin/maintenance")
    async def run_maintenance(request: Request):
        """
        Run backend maintenance tasks: tagging, categorization, embeddings.

        Authentication: Requires X-Webhook-Secret header matching WEBHOOK_SECRET env var.

        Accepts JSON payload with:
        - tags: bool - Generate tags for episodes (default: true)
        - categories: bool - Generate categories for episodes (default: true)
        - embeddings: bool - Generate embeddings for episodes (default: true)
        - force: bool - Force re-process all episodes (default: false)
        - limit: int - Maximum episodes to process (default: all)
        - offset: int - Skip first N episodes (default: 0)
        - dry_run: bool - Show what would be done without making changes (default: false)

        Returns job_id for tracking progress.
        """
        # Validate webhook secret
        webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
        if not webhook_secret:
            raise HTTPException(
                status_code=500,
                detail="WEBHOOK_SECRET not configured. Add it to Modal secrets."
            )

        request_secret = request.headers.get("X-Webhook-Secret", "")
        if not hmac.compare_digest(request_secret, webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

        # Parse request body
        try:
            body = await request.json()
        except Exception:
            body = {}

        # Extract parameters
        do_tags = body.get("tags", True)
        do_categories = body.get("categories", True)
        do_embeddings = body.get("embeddings", True)
        force = body.get("force", False)
        limit = body.get("limit", None)
        offset = body.get("offset", 0)
        dry_run = body.get("dry_run", False)

        # Generate job ID
        job_id = f"maint-{str(uuid.uuid4())[:8]}"

        # Start maintenance job in background
        run_maintenance_job.spawn(
            job_id=job_id,
            do_tags=do_tags,
            do_categories=do_categories,
            do_embeddings=do_embeddings,
            force=force,
            limit=limit,
            offset=offset,
            dry_run=dry_run,
        )

        return {
            "success": True,
            "job_id": job_id,
            "status": "started",
            "tasks": {
                "tags": do_tags,
                "categories": do_categories,
                "embeddings": do_embeddings,
            },
            "options": {
                "force": force,
                "limit": limit,
                "offset": offset,
                "dry_run": dry_run,
            },
            "message": "Backend maintenance started.",
        }

    return api


# ============================================================================
# CLI ENTRY POINT
# ============================================================================


@app.local_entrypoint()
def main(
    audio_url: str = None,
    job_id: str = None,
    sender_type: str = "daniel",
    sender_name: str = None,
    attachment_url: str = None,
):
    """
    CLI entry point for testing.

    Usage:
        modal run modal_app/recording_app.py --audio-url "https://..."

    Sender Types:
        --sender-type daniel  Default sender (Daniel)
        --sender-type hannah  Hannah (special guest episode)
        --sender-type other   External guest (use --sender-name)
    """
    if not audio_url:
        print("Error: Must provide --audio-url")
        print("Example: modal run modal_app/recording_app.py --audio-url 'https://...'")
        print("\nSender Types:")
        print("  --sender-type daniel  Default sender")
        print("  --sender-type hannah  Hannah (special guest)")
        print("  --sender-type other   External guest (use --sender-name)")
        return

    print(f"Starting episode generation...")
    print(f"  Audio URL: {audio_url[:60]}...")
    print(f"  Sender: {sender_type}{' (' + sender_name + ')' if sender_name else ''}")
    if attachment_url:
        print(f"  Attachment: {attachment_url[:60]}...")
    print(f"  Job ID: {job_id or '(none)'}")
    print()

    result = generate_episode.remote(
        audio_url=audio_url,
        job_id=job_id,
        sender_type=sender_type,
        sender_name=sender_name,
        attachment_url=attachment_url,
    )

    print("\n" + "=" * 60)
    print("RESULT:")
    print(json.dumps(result, indent=2))
    print("=" * 60)
