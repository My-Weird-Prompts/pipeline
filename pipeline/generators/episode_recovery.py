"""
Episode Recovery and Fault Tolerance Module

Provides mechanisms for:
1. Storing generated episodes in recoverable storage when publication fails
2. Sending error notifications for pipeline failures
3. Retrying failed operations with exponential backoff
4. Graceful degradation when non-critical components fail
"""

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Any

# Optional imports
try:
    import resend
    HAS_RESEND = True
except ImportError:
    HAS_RESEND = False

try:
    import boto3
    from botocore.exceptions import ClientError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


# Recovery storage configuration
# Uses R2 bucket for recoverable episodes that failed to publish
RECOVERY_BUCKET = os.environ.get("R2_RECOVERY_BUCKET", "mwp-episodes")
RECOVERY_PREFIX = "recovery/"  # Prefix for recovery files in bucket

# Local fallback directory if R2 is unavailable
LOCAL_RECOVERY_DIR = Path(os.environ.get("LOCAL_RECOVERY_DIR", "/working/recovery"))

# Notification configuration
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
RESEND_SENDER_EMAIL = os.environ.get("RESEND_SENDER_EMAIL", "")
RESEND_RECIPIENT = os.environ.get("RESEND_RECIPIENT", "")


class PipelineError(Exception):
    """Custom exception for pipeline errors with recovery context."""

    def __init__(self, message: str, stage: str, recoverable: bool = True,
                 recovery_path: str = None, job_id: str = None):
        super().__init__(message)
        self.stage = stage
        self.recoverable = recoverable
        self.recovery_path = recovery_path
        self.job_id = job_id
        self.timestamp = datetime.now().isoformat()


def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
    on_retry: Callable[[int, Exception], None] = None,
) -> Any:
    """
    Execute a function with exponential backoff retry logic.

    Args:
        func: Function to execute (no arguments - use lambda or partial)
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries
        backoff_factor: Multiplier for delay after each retry
        retryable_exceptions: Tuple of exception types to retry on
        on_retry: Optional callback(attempt, exception) called before each retry

    Returns:
        Result of successful function call

    Raises:
        Last exception if all retries fail
    """
    last_exception = None
    delay = initial_delay

    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e

            if attempt == max_retries:
                raise

            if on_retry:
                on_retry(attempt + 1, e)

            # Calculate next delay with exponential backoff
            time.sleep(delay)
            delay = min(delay * backoff_factor, max_delay)

    raise last_exception


def save_episode_for_recovery(
    episode_dir: Path,
    episode_path: Path,
    metadata: dict,
    cover_art_path: Optional[Path] = None,
    script: str = None,
    error_message: str = None,
    job_id: str = None,
) -> str:
    """
    Save a generated episode to recovery storage for manual retrieval.

    This is called when publication fails but the episode was successfully
    generated. The episode can be manually recovered and republished later.

    Args:
        episode_dir: Directory containing episode files
        episode_path: Path to the final MP3 file
        metadata: Episode metadata dictionary
        cover_art_path: Optional path to cover art image
        script: Episode script text
        error_message: Error message describing the failure
        job_id: Job ID for tracking

    Returns:
        Recovery location (R2 URL or local path)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    recovery_id = f"{job_id or 'unknown'}_{timestamp}"

    # Create recovery manifest
    manifest = {
        "recovery_id": recovery_id,
        "job_id": job_id,
        "timestamp": datetime.now().isoformat(),
        "error": error_message,
        "metadata": metadata,
        "files": {
            "audio": episode_path.name if episode_path and episode_path.exists() else None,
            "cover": cover_art_path.name if cover_art_path and cover_art_path.exists() else None,
            "script": "script.txt" if script else None,
        },
        "recovery_instructions": (
            "To recover this episode:\n"
            "1. Download the audio file and cover art from this recovery folder\n"
            "2. Use the metadata to manually create a blog post\n"
            "3. Run: modal run modal_app/recording_app.py --recover <recovery_id>"
        ),
    }

    recovery_path = None

    # Try R2 first
    if HAS_BOTO3:
        try:
            recovery_path = _save_to_r2_recovery(
                recovery_id, episode_path, cover_art_path, script, manifest
            )
            if recovery_path:
                print(f"  Episode saved to R2 recovery: {recovery_path}")
                return recovery_path
        except Exception as e:
            print(f"  Warning: R2 recovery save failed: {e}")

    # Fall back to local storage
    try:
        recovery_path = _save_to_local_recovery(
            recovery_id, episode_path, cover_art_path, script, manifest
        )
        print(f"  Episode saved to local recovery: {recovery_path}")
        return recovery_path
    except Exception as e:
        print(f"  Error: Local recovery save also failed: {e}")
        return None


def _save_to_r2_recovery(
    recovery_id: str,
    episode_path: Path,
    cover_art_path: Optional[Path],
    script: str,
    manifest: dict,
) -> Optional[str]:
    """Save episode files to R2 recovery prefix."""
    from pipeline.storage.r2 import get_r2_client, R2_EPISODES_BUCKET, R2_EPISODES_PUBLIC_URL

    client = get_r2_client()
    if not client:
        return None

    prefix = f"{RECOVERY_PREFIX}{recovery_id}/"

    # Upload audio
    if episode_path and episode_path.exists():
        client.upload_file(
            str(episode_path),
            R2_EPISODES_BUCKET,
            f"{prefix}{episode_path.name}",
            ExtraArgs={"ContentType": "audio/mpeg"},
        )

    # Upload cover art
    if cover_art_path and cover_art_path.exists():
        client.upload_file(
            str(cover_art_path),
            R2_EPISODES_BUCKET,
            f"{prefix}{cover_art_path.name}",
            ExtraArgs={"ContentType": "image/jpeg"},
        )

    # Upload script
    if script:
        client.put_object(
            Bucket=R2_EPISODES_BUCKET,
            Key=f"{prefix}script.txt",
            Body=script.encode("utf-8"),
            ContentType="text/plain",
        )

    # Upload manifest
    client.put_object(
        Bucket=R2_EPISODES_BUCKET,
        Key=f"{prefix}manifest.json",
        Body=json.dumps(manifest, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    return f"{R2_EPISODES_PUBLIC_URL}/{prefix}"


def _save_to_local_recovery(
    recovery_id: str,
    episode_path: Path,
    cover_art_path: Optional[Path],
    script: str,
    manifest: dict,
) -> str:
    """Save episode files to local recovery directory."""
    recovery_dir = LOCAL_RECOVERY_DIR / recovery_id
    recovery_dir.mkdir(parents=True, exist_ok=True)

    # Copy audio
    if episode_path and episode_path.exists():
        shutil.copy(episode_path, recovery_dir / episode_path.name)

    # Copy cover art
    if cover_art_path and cover_art_path.exists():
        shutil.copy(cover_art_path, recovery_dir / cover_art_path.name)

    # Save script
    if script:
        (recovery_dir / "script.txt").write_text(script, encoding="utf-8")

    # Save manifest
    (recovery_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    return str(recovery_dir)


def send_generation_started_notification(
    title: str,
    episode_number: int = None,
    job_id: str = None,
) -> bool:
    """
    Send a brief notification when episode generation starts.

    This is sent after the script is generated and we have a title,
    to let you know the pipeline is actively working.

    Args:
        title: Episode title
        episode_number: Optional episode number
        job_id: Job ID for tracking

    Returns:
        True if notification sent successfully
    """
    if not HAS_RESEND or not RESEND_API_KEY:
        print(f"  Warning: Resend not configured - start notification not sent")
        return False

    try:
        resend.api_key = RESEND_API_KEY

        episode_str = f"Episode {episode_number}: " if episode_number else ""

        html_content = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #0066cc;">🎬 Episode Generation In Progress</h2>

            <div style="background: #e7f3ff; border: 1px solid #0066cc; padding: 16px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0; font-size: 18px; color: #004085;">
                    <strong>{episode_str}{title}</strong>
                </p>
            </div>

            <p style="color: #666; font-size: 14px;">
                Script generated. Now generating cover art and TTS audio...
            </p>

            {f'<p style="color: #999; font-size: 12px;">Job ID: {job_id}</p>' if job_id else ''}
        </div>
        """

        resend.Emails.send({
            "from": f"MWP Generator <{RESEND_SENDER_EMAIL}>",
            "to": [RESEND_RECIPIENT],
            "subject": f"🎬 Generating: {title}",
            "html": html_content,
        })

        print(f"  ✉️ Generation started notification sent to {RESEND_RECIPIENT}")
        return True

    except Exception as e:
        print(f"  Warning: Failed to send start notification: {e}")
        return False


def send_error_notification(
    error_message: str,
    stage: str,
    job_id: str = None,
    recovery_path: str = None,
    metadata: dict = None,
    include_recovery_instructions: bool = True,
) -> bool:
    """
    Send email notification about pipeline failure.

    Args:
        error_message: Description of the error
        stage: Pipeline stage where error occurred
        job_id: Job ID for tracking
        recovery_path: Path to recovered episode files (if any)
        metadata: Episode metadata (title, description, etc.)
        include_recovery_instructions: Whether to include recovery steps

    Returns:
        True if notification sent successfully
    """
    if not HAS_RESEND or not RESEND_API_KEY:
        print(f"  Warning: Resend not configured - error notification not sent")
        return False

    try:
        resend.api_key = RESEND_API_KEY

        title = metadata.get("title", "Unknown Episode") if metadata else "Unknown Episode"

        # Build HTML email
        recovery_html = ""
        if recovery_path:
            recovery_html = f"""
            <div style="background: #d4edda; border: 1px solid #28a745; padding: 16px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #155724; margin-top: 0;">✅ Episode Saved for Recovery</h3>
                <p style="margin: 8px 0;"><strong>Recovery Location:</strong></p>
                <code style="background: #fff; padding: 8px; display: block; border-radius: 4px; word-break: break-all;">
                    {recovery_path}
                </code>
                {_get_recovery_instructions_html() if include_recovery_instructions else ""}
            </div>
            """

        html_content = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
            <h1 style="color: #dc3545;">⚠️ Episode Generation Failed</h1>

            <div style="background: #f8d7da; border: 1px solid #dc3545; padding: 16px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #721c24; margin-top: 0;">Error Details</h3>
                <p style="margin: 8px 0;"><strong>Stage:</strong> {stage}</p>
                <p style="margin: 8px 0;"><strong>Job ID:</strong> {job_id or "N/A"}</p>
                <p style="margin: 8px 0;"><strong>Episode:</strong> {title}</p>
                <p style="margin: 8px 0;"><strong>Error:</strong></p>
                <pre style="background: #fff; padding: 12px; border-radius: 4px; overflow-x: auto; white-space: pre-wrap;">{error_message}</pre>
            </div>

            {recovery_html}

            <p style="color: #666; font-size: 12px;">Generated by My Weird Prompts Pipeline on Modal</p>
        </div>
        """

        resend.Emails.send({
            "from": f"MWP Pipeline <{RESEND_SENDER_EMAIL}>",
            "to": [RESEND_RECIPIENT],
            "subject": f"⚠️ Pipeline Failed: {title} [{stage}]",
            "html": html_content,
        })

        print(f"  ✉️ Error notification sent to {RESEND_RECIPIENT}")
        return True

    except Exception as e:
        print(f"  Warning: Failed to send error notification: {e}")
        return False


def _get_recovery_instructions_html() -> str:
    """Get HTML recovery instructions."""
    return """
    <div style="margin-top: 16px;">
        <h4 style="color: #155724;">Recovery Steps:</h4>
        <ol style="color: #155724; padding-left: 20px;">
            <li>Download the audio file from the recovery location</li>
            <li>Check the manifest.json for episode metadata</li>
            <li>Manually upload to R2 if needed</li>
            <li>Insert episode into database using the manifest data</li>
            <li>Trigger Vercel deployment</li>
        </ol>
    </div>
    """


def send_success_notification_with_details(
    title: str,
    description: str,
    audio_url: str,
    cover_url: str = None,
    tts_cost: float = 0,
    modal_compute_cost: float = 0,
    segments_count: int = 0,
    generation_time_seconds: float = 0,
    warnings: list = None,
) -> bool:
    """
    Send detailed success notification with any warnings.

    This is an enhanced version of the basic success notification that
    includes generation statistics and any non-fatal warnings.
    """
    if not HAS_RESEND or not RESEND_API_KEY:
        print(f"  Warning: Resend not configured - notification not sent")
        return False

    try:
        resend.api_key = RESEND_API_KEY

        # Build warnings section if any
        warnings_html = ""
        if warnings:
            warnings_list = "".join(f"<li>{w}</li>" for w in warnings)
            warnings_html = f"""
            <div style="background: #fff3cd; border: 1px solid #ffc107; padding: 16px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #856404; margin-top: 0;">⚠️ Warnings</h3>
                <ul style="color: #856404; padding-left: 20px;">
                    {warnings_list}
                </ul>
            </div>
            """

        gen_time_str = f"{generation_time_seconds/60:.1f} minutes" if generation_time_seconds > 60 else f"{generation_time_seconds:.0f} seconds"

        html_content = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
            <h1 style="color: #28a745;">🎙️ Episode Published Successfully!</h1>

            <h2 style="color: #333;">{title}</h2>

            <p style="color: #666; line-height: 1.6;">{description}</p>

            <div style="background: #d4edda; border: 1px solid #28a745; padding: 16px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 8px 0;"><strong>🔊 Audio:</strong> <a href="{audio_url}" style="color: #155724;">Listen to episode</a></p>
                {f'<p style="margin: 8px 0;"><strong>🖼️ Cover:</strong> <a href="{cover_url}" style="color: #155724;">View cover art</a></p>' if cover_url else ''}
                <p style="margin: 8px 0;"><strong>📊 Segments:</strong> {segments_count}</p>
                <p style="margin: 8px 0;"><strong>⏱️ Generation Time:</strong> {gen_time_str}</p>
            </div>

            <div style="background: #e7f3ff; border: 1px solid #0066cc; padding: 16px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #004085; margin-top: 0;">💰 Cost Breakdown</h3>
                <p style="margin: 8px 0;"><strong>Modal Compute (GPU):</strong> ${modal_compute_cost:.4f}</p>
                <p style="margin: 8px 0;"><strong>TTS (if external):</strong> ${tts_cost:.4f}</p>
                <p style="margin: 8px 0; border-top: 1px solid #b8daff; padding-top: 8px;"><strong>Total Est. Cost:</strong> ${modal_compute_cost + tts_cost:.4f}</p>
            </div>

            {warnings_html}

            <p style="color: #999; font-size: 12px;">Generated by My Weird Prompts Pipeline on Modal</p>
        </div>
        """

        resend.Emails.send({
            "from": f"MWP Generator <{RESEND_SENDER_EMAIL}>",
            "to": [RESEND_RECIPIENT],
            "subject": f"🎙️ Published: {title}",
            "html": html_content,
        })

        print(f"  ✉️ Success notification sent to {RESEND_RECIPIENT}")
        return True

    except Exception as e:
        print(f"  Warning: Failed to send success notification: {e}")
        return False


class PipelineCheckpoint:
    """
    Manages checkpoints for pipeline stages to enable resumption.

    Saves intermediate results to disk so that if the pipeline fails
    at a later stage, earlier stages don't need to be re-run.
    """

    def __init__(self, episode_dir: Path, job_id: str = None):
        self.episode_dir = episode_dir
        self.job_id = job_id
        self.checkpoint_dir = episode_dir / "_checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.checkpoint_dir / "state.json"
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """Load checkpoint state from disk."""
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                return {}
        return {}

    def _save_state(self):
        """Save checkpoint state to disk."""
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def get(self, stage: str) -> Optional[dict]:
        """Get checkpoint data for a stage, or None if not checkpointed."""
        return self.state.get(stage)

    def set(self, stage: str, data: dict):
        """Set checkpoint data for a stage."""
        self.state[stage] = {
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }
        self._save_state()

    def is_completed(self, stage: str) -> bool:
        """Check if a stage has a valid checkpoint."""
        return stage in self.state and self.state[stage].get("data") is not None

    def clear(self, stage: str = None):
        """Clear checkpoint(s). If stage is None, clears all."""
        if stage:
            self.state.pop(stage, None)
        else:
            self.state = {}
        self._save_state()

    def cleanup(self):
        """Remove checkpoint directory after successful completion."""
        if self.checkpoint_dir.exists():
            shutil.rmtree(self.checkpoint_dir)


def get_default_cover_art_url() -> str:
    """Get URL for default cover art when generation fails."""
    return os.environ.get(
        "DEFAULT_COVER_ART_URL",
        "https://ai-files.myweirdprompts.com/images/default-podcast-cover.png"
    )


def deploy_with_retry(
    deploy_hook_url: str,
    title: str,
    max_retries: int = 3,
    initial_delay: float = 5.0,
) -> bool:
    """
    Trigger Vercel deployment with retry logic.

    Args:
        deploy_hook_url: Vercel deploy hook URL
        title: Episode title for logging
        max_retries: Maximum retry attempts
        initial_delay: Initial delay between retries

    Returns:
        True if deployment triggered successfully
    """
    import requests

    def attempt_deploy():
        response = requests.post(deploy_hook_url, timeout=30)
        if response.status_code not in (200, 201):
            raise Exception(f"Deploy hook returned status {response.status_code}")
        return True

    def on_retry(attempt, error):
        print(f"  Vercel deploy attempt {attempt} failed: {error}, retrying...")

    try:
        return retry_with_backoff(
            attempt_deploy,
            max_retries=max_retries,
            initial_delay=initial_delay,
            on_retry=on_retry,
        )
    except requests.exceptions.Timeout:
        print("  Deploy hook timed out - deployment may still be triggered")
        return True  # Optimistic
    except Exception as e:
        print(f"  Vercel deployment failed after {max_retries} attempts: {e}")
        return False


class GracefulDegradation:
    """
    Tracks graceful degradation decisions and warnings.

    Use this to collect warnings about non-critical failures
    that were handled gracefully, so they can be reported.
    """

    def __init__(self):
        self.warnings = []
        self.degraded_features = []

    def add_warning(self, message: str):
        """Add a warning message."""
        self.warnings.append(message)
        print(f"  ⚠️ {message}")

    def mark_degraded(self, feature: str, reason: str):
        """Mark a feature as degraded with reason."""
        self.degraded_features.append({"feature": feature, "reason": reason})
        self.add_warning(f"{feature}: {reason}")

    def has_warnings(self) -> bool:
        """Check if any warnings were recorded."""
        return len(self.warnings) > 0

    def get_summary(self) -> dict:
        """Get summary of all degradations."""
        return {
            "warnings": self.warnings,
            "degraded_features": self.degraded_features,
            "count": len(self.warnings),
        }
