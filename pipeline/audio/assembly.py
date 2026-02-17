"""
Episode assembly module for the MWP podcast pipeline.

Handles:
- Episode concatenation (intro, dialogue, outro, etc.)
- Prompt audio processing
- Final episode loudness normalization
"""

import shutil
import subprocess
from pathlib import Path

from ..config.constants import (
    TARGET_LUFS,
    TARGET_TP,
    MP3_BITRATE,
    JINGLES_DIR,
    NORMALIZED_JINGLES_DIR,
)
from .processing import get_audio_duration, convert_to_wav


def process_prompt_audio(input_path: Path, output_path: Path) -> Path:
    """
    Convert the user's prompt audio to a consistent format for concatenation.

    Simple conversion without any processing that could risk losing audio.
    Just converts to WAV format with consistent sample rate for reliable concatenation.

    Args:
        input_path: Original prompt audio file
        output_path: Where to save the converted audio

    Returns:
        Path to converted audio file
    """
    print(f"Converting prompt audio: {input_path.name}")

    # Get duration for logging
    duration = get_audio_duration(input_path)
    if duration:
        print(f"  Duration: {duration:.1f}s")
    else:
        print("  Duration: unknown")

    # Convert to WAV
    result = convert_to_wav(input_path, output_path)
    print(f"  Converted to: {output_path.name}")
    return result


def concatenate_episode(
    dialogue_audio: Path,
    output_path: Path,
    user_prompt_audio: Path = None,
    intro_jingle: Path = None,
    disclaimer_audio: Path = None,
    outro_jingle: Path = None,
    prompt_intro_audio: Path = None,
    transition_audio: Path = None,
    llm_info_audio: Path = None,
    tts_info_audio: Path = None,
) -> Path:
    """
    Concatenate all episode audio with transitions.

    Order: intro + disclaimer + prompt_intro + user_prompt + transition + dialogue + llm_info + tts_info + outro

    - prompt_intro_audio: Prerecorded "Here's Daniel's prompt!" announcement
    - transition_audio: Whoosh sound after the prompt, before hosts discuss
    - llm_info_audio: Prerecorded snippet announcing the LLM used
    - tts_info_audio: Prerecorded snippet announcing the TTS engine

    OPTIMIZED: Uses pre-normalized show elements and applies single-pass loudness
    normalization only to the final concatenated output.

    Args:
        dialogue_audio: Path to the main dialogue audio
        output_path: Where to save the final episode
        user_prompt_audio: User's prompt recording
        intro_jingle: Intro music
        disclaimer_audio: AI-generated content disclaimer
        outro_jingle: Outro music
        prompt_intro_audio: "Here's Daniel's prompt!" announcement
        transition_audio: Whoosh transition after prompt
        llm_info_audio: LLM credit announcement
        tts_info_audio: TTS credit announcement

    Returns:
        Path to the final episode audio file
    """
    print("Assembling final episode...")

    audio_files = []
    labels = []  # For logging

    # Helper to check for pre-normalized version
    def get_audio_with_normalized(audio_path: Path) -> tuple[Path, bool]:
        if NORMALIZED_JINGLES_DIR and audio_path:
            normalized = NORMALIZED_JINGLES_DIR / audio_path.name
            if normalized.exists():
                return normalized, True
        return audio_path, False

    # Build component list
    if intro_jingle and intro_jingle.exists():
        path, is_norm = get_audio_with_normalized(intro_jingle)
        audio_files.append(path)
        labels.append("intro" + (" [pre-norm]" if is_norm else ""))

    if disclaimer_audio and disclaimer_audio.exists():
        path, is_norm = get_audio_with_normalized(disclaimer_audio)
        audio_files.append(path)
        labels.append("disclaimer" + (" [pre-norm]" if is_norm else ""))

    if prompt_intro_audio and prompt_intro_audio.exists():
        path, is_norm = get_audio_with_normalized(prompt_intro_audio)
        audio_files.append(path)
        labels.append("prompt-intro" + (" [pre-norm]" if is_norm else ""))

    if user_prompt_audio and user_prompt_audio.exists():
        audio_files.append(user_prompt_audio)
        labels.append("prompt")

    if transition_audio and transition_audio.exists():
        path, is_norm = get_audio_with_normalized(transition_audio)
        audio_files.append(path)
        labels.append("transition" + (" [pre-norm]" if is_norm else ""))

    audio_files.append(dialogue_audio)
    labels.append("dialogue")

    if llm_info_audio and llm_info_audio.exists():
        path, is_norm = get_audio_with_normalized(llm_info_audio)
        audio_files.append(path)
        labels.append("llm-info" + (" [pre-norm]" if is_norm else ""))

    if tts_info_audio and tts_info_audio.exists():
        path, is_norm = get_audio_with_normalized(tts_info_audio)
        audio_files.append(path)
        labels.append("tts-info" + (" [pre-norm]" if is_norm else ""))

    if outro_jingle and outro_jingle.exists():
        path, is_norm = get_audio_with_normalized(outro_jingle)
        audio_files.append(path)
        labels.append("outro" + (" [pre-norm]" if is_norm else ""))

    print(f"  Components: {', '.join(labels)}")

    # Create temp directory
    temp_dir = output_path.parent / "_temp_concat"
    temp_dir.mkdir(exist_ok=True)

    try:
        # Convert all files to consistent format for reliable concat
        print(f"  Preparing {len(audio_files)} audio segments...")
        prepared_files = []
        for i, (audio_file, label) in enumerate(zip(audio_files, labels)):
            prepared_path = temp_dir / f"prep_{i:02d}.wav"
            cmd = [
                "ffmpeg", "-y", "-i", str(audio_file),
                "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le",
                str(prepared_path)
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            prepared_files.append(prepared_path)

        # Create file list for concatenation
        filelist_path = temp_dir / "filelist.txt"
        with open(filelist_path, "w", encoding="utf-8") as f:
            for pf in prepared_files:
                f.write(f"file '{pf}'\n")

        # Concatenate all segments
        print("  Concatenating segments...")
        concat_path = temp_dir / "concatenated.wav"
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(filelist_path),
            "-c:a", "pcm_s16le",
            str(concat_path)
        ]
        subprocess.run(cmd, capture_output=True, check=True)

        # Single-pass loudness normalization + MP3 encoding
        print(f"  Normalizing to {TARGET_LUFS} LUFS and encoding MP3...")
        final_cmd = [
            "ffmpeg", "-y", "-i", str(concat_path),
            "-af", f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA=11",
            "-threads", "0",  # Use all available CPU threads
            "-c:a", "libmp3lame", "-b:a", MP3_BITRATE,
            "-progress", "pipe:1",
            str(output_path)
        ]

        # Stream progress output
        process = subprocess.Popen(
            final_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        last_time = ""
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line.startswith("out_time="):
                time_str = line.strip().split("=")[1]
                if time_str != last_time and time_str != "N/A":
                    time_parts = time_str.split(".")[0]
                    print(f"\r    Progress: {time_parts}", end="", flush=True)
                    last_time = time_str
        print()  # Newline after progress

        if process.returncode != 0:
            stderr = process.stderr.read()
            raise subprocess.CalledProcessError(process.returncode, final_cmd, stderr=stderr)

    finally:
        # Cleanup temp files
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

    print(f"  Episode saved: {output_path.name}")
    return output_path


def remove_silence_from_dialogue(
    input_path: Path,
    output_path: Path = None,
    silence_threshold_db: float = -50,
    min_silence_duration: float = 1.0,
) -> tuple[Path, dict]:
    """
    Remove extended silence from dialogue audio.

    This is a convenience wrapper around processing.remove_silence
    for backward compatibility.
    """
    from .processing import remove_silence
    return remove_silence(
        input_path=input_path,
        output_path=output_path,
        silence_threshold_db=silence_threshold_db,
        min_silence_duration=min_silence_duration,
    )


def normalize_audio_loudness(
    input_path: Path,
    output_path: Path,
    target_lufs: float = TARGET_LUFS,
) -> Path:
    """
    Normalize audio to target loudness.

    This is a convenience wrapper around processing.normalize_loudness
    for backward compatibility.
    """
    from .processing import normalize_loudness
    return normalize_loudness(
        input_path=input_path,
        output_path=output_path,
        target_lufs=target_lufs,
        target_tp=TARGET_TP,
    )
