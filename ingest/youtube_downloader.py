"""YouTube audio downloader using yt-dlp."""

import logging
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = Path(__file__).resolve().parent.parent / "downloads"


def sanitize_filename(name: str) -> str:
    """Clean filename of non-alphanumeric special characters."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip().replace(" ", "_")[:80]


def extract_youtube_id(url: str) -> Optional[str]:
    """Extract 11-character video ID from various YouTube URL formats."""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11})(?:[&?]|$)',
        r'(?:embed\/|v\/|shorts\/)([0-9A-Za-z_-]{11})',
        r'youtu\.be\/([0-9A-Za-z_-]{11})',
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def download_youtube_audio(url: str, output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Download audio track from a YouTube URL and convert to standardized audio.

    Args:
        url: Full YouTube video URL.
        output_dir: Directory where audio will be saved.

    Returns:
        Dict with keys: audio_path, title, duration, source_url
    """
    target_dir = output_dir or DOWNLOADS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    # Fast-path: Check if video was already downloaded in downloads folder
    vid_id = extract_youtube_id(url)
    if vid_id:
        for ext in ["mp3", "m4a", "webm", "opus", "wav", "aac"]:
            existing = target_dir / f"{vid_id}.{ext}"
            if existing.is_file() and existing.stat().st_size > 1000:
                logger.info("Using cached audio for %s: %s", vid_id, existing.name)
                from ingest.file_handler import get_audio_duration_seconds
                dur = get_audio_duration_seconds(existing)
                return {
                    "audio_path": str(existing),
                    "title": f"YouTube Video ({vid_id})",
                    "duration": dur,
                    "source_url": url,
                }

    import shutil
    has_ffmpeg = bool(shutil.which("ffmpeg"))

    # 1. Attempt using yt_dlp python module if installed
    try:
        import yt_dlp

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(target_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }

        # Only request ffmpeg conversion if ffmpeg binary exists
        if has_ffmpeg:
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get("id", "audio")
            title = info.get("title", f"YouTube Video ({video_id})")
            duration = float(info.get("duration", 0.0) or 0.0)

            # Locate downloaded audio file (.mp3, .m4a, .webm, .opus, etc.)
            candidate = None
            for ext in ["mp3", "m4a", "webm", "opus", "wav", "aac"]:
                f = target_dir / f"{video_id}.{ext}"
                if f.exists():
                    candidate = f
                    break

            if not candidate:
                matches = [f for f in target_dir.glob(f"{video_id}.*") if not f.name.endswith(".part")]
                if matches:
                    candidate = matches[0]

            if candidate and candidate.exists():
                return {
                    "audio_path": str(candidate),
                    "title": title,
                    "duration": duration,
                    "source_url": url,
                }
            raise FileNotFoundError(f"Could not find audio file for {video_id} in {target_dir}")

    except ImportError:
        logger.debug("yt-dlp Python package not installed. Attempting CLI fallback...")
    except Exception as e:
        logger.warning("yt-dlp library download failed: %s. Trying CLI...", e)

    # 2. Fallback: Check for yt-dlp CLI binary on system or local venv
    venv_cli = Path(__file__).resolve().parent.parent / "venv" / "bin" / "yt-dlp"
    cli_path = shutil.which("yt-dlp") or (str(venv_cli) if venv_cli.exists() else None)
    if cli_path:
        cmd = [
            cli_path,
            "-f", "bestaudio/best",
            "-o", str(target_dir / "%(id)s.%(ext)s"),
            "--print", "%(id)s|||%(title)s|||%(duration)s",
            url,
        ]
        if has_ffmpeg:
            cmd.extend(["-x", "--audio-format", "mp3"])

        try:
            res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True)
            output = res.stdout.strip().splitlines()[-1]
            vid_id, title, dur = output.split("|||")

            candidate = None
            for ext in ["mp3", "m4a", "webm", "opus", "wav", "aac"]:
                f = target_dir / f"{vid_id}.{ext}"
                if f.exists():
                    candidate = f
                    break

            if not candidate:
                matches = [f for f in target_dir.glob(f"{vid_id}.*") if not f.name.endswith(".part")]
                if matches:
                    candidate = matches[0]

            if candidate and candidate.exists():
                return {
                    "audio_path": str(candidate),
                    "title": title.strip(),
                    "duration": float(dur) if dur.replace(".", "", 1).isdigit() else 0.0,
                    "source_url": url,
                }
            raise FileNotFoundError(f"Downloaded audio file not found for {vid_id}")
        except Exception as e:
            logger.error("yt-dlp CLI execution failed: %s", e)
            raise RuntimeError(f"Failed to download YouTube audio: {e}")

    raise RuntimeError(
        "Neither yt-dlp Python package nor yt-dlp CLI is available. "
        "Install via: pip install yt-dlp"
    )
