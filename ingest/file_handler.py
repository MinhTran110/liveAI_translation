"""Local file upload handler for video and audio formats."""

import logging
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"


def get_audio_duration_seconds(file_path: Path | str) -> float:
    """Estimate or measure audio duration in seconds."""
    path = Path(file_path)
    # 1. Try ffprobe if installed
    if shutil.which("ffprobe"):
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ]
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
            return round(float(out), 2)
        except Exception:
            pass

    # 2. Try wave module for .wav files
    if path.suffix.lower() == ".wav":
        try:
            import wave

            with wave.open(str(path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return round(frames / float(rate), 2)
        except Exception:
            pass

    # 3. Fallback: estimate based on file size (assuming ~128kbps = 16KB/s)
    try:
        size_bytes = path.stat().st_size
        return round(size_bytes / 16000.0, 2)
    except Exception:
        return 0.0


def extract_audio_from_video(video_path: Path, output_audio_path: Path) -> bool:
    """Extract audio track from video file into mp3 or wav using ffmpeg."""
    if shutil.which("ffmpeg"):
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "libmp3lame" if output_audio_path.suffix == ".mp3" else "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_audio_path),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            logger.warning("ffmpeg audio extraction failed: %s", e)

    return False


def process_uploaded_file(
    source_file_path: str | Path,
    original_filename: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Process an uploaded local audio or video file.

    Args:
        source_file_path: Local path to uploaded file.
        original_filename: Original name before saving.
        output_dir: Target directory for stored audio.

    Returns:
        Dict with keys: audio_path, title, duration, source_type
    """
    src_path = Path(source_file_path)
    target_dir = output_dir or UPLOADS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = original_filename or src_path.name
    stem = Path(filename).stem
    suffix = Path(filename).suffix.lower()

    video_extensions = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv"}
    audio_extensions = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}

    if suffix in video_extensions:
        # Extract audio track to .mp3
        extracted_audio = target_dir / f"{stem}_{int(time.time())}.mp3"
        success = extract_audio_from_video(src_path, extracted_audio)
        if success and extracted_audio.exists():
            final_audio_path = extracted_audio
        else:
            final_audio_path = src_path
    elif suffix in audio_extensions:
        dest = target_dir / f"{stem}_{int(time.time())}{suffix}"
        if src_path != dest:
            shutil.copy2(src_path, dest)
        final_audio_path = dest
    else:
        dest = target_dir / f"{stem}_{int(time.time())}{suffix}"
        if src_path != dest:
            shutil.copy2(src_path, dest)
        final_audio_path = dest

    duration = get_audio_duration_seconds(final_audio_path)

    return {
        "audio_path": str(final_audio_path),
        "title": stem.replace("_", " ").title(),
        "duration": duration,
        "source_type": "file",
    }
