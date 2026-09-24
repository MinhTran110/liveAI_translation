"""YouTube native transcript and subtitle extractor (official and auto-captions)."""

import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.request

from transcribe.base import TranscriptSegment

logger = logging.getLogger(__name__)


def _vtt_time_to_seconds(time_str: str) -> float:
    """Convert WebVTT timestamp (HH:MM:SS.mmm or MM:SS.mmm) to seconds."""
    parts = time_str.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except Exception:
        return 0.0


def parse_vtt_subtitles(vtt_text: str) -> List[TranscriptSegment]:
    """Parse WebVTT content into a list of TranscriptSegment."""
    time_pat = re.compile(r"(\d+:\d+(?::\d+)?\.\d+)\s+-->\s+(\d+:\d+(?::\d+)?\.\d+)")
    blocks = vtt_text.strip().split("\n\n")
    segments: List[TranscriptSegment] = []
    last_text = ""
    speaker_toggle = 0
    last_end = 0.0

    for b in blocks:
        lines = [line.strip() for line in b.splitlines() if line.strip()]
        for idx, line in enumerate(lines):
            m = time_pat.search(line)
            if m:
                start = _vtt_time_to_seconds(m.group(1))
                end = _vtt_time_to_seconds(m.group(2))
                raw_content = " ".join(lines[idx + 1 :]).strip()
                # Clean html tags & entities
                clean = re.sub(r"<[^>]+>", "", raw_content)
                clean = clean.replace("&nbsp;", " ").replace("&amp;", "&").strip()

                if not clean or clean.startswith("Kind:") or clean.startswith("Language:"):
                    continue

                if clean == last_text:
                    continue

                # Estimate speaker turn if pause > 2.0s
                if (start - last_end) > 2.0 and last_end > 0:
                    speaker_toggle = 1 - speaker_toggle

                segments.append(
                    TranscriptSegment(
                        speaker=speaker_toggle,
                        text=clean,
                        start=round(start, 2),
                        end=round(end, 2),
                        confidence=1.0,
                    )
                )
                last_text = clean
                last_end = end
                break

    return segments


def parse_json3_subtitles(json3_dict: Dict[str, Any]) -> List[TranscriptSegment]:
    """Parse YouTube json3 format subtitles into TranscriptSegment list."""
    events = json3_dict.get("events", [])
    segments: List[TranscriptSegment] = []
    speaker_toggle = 0
    last_end = 0.0

    for ev in events:
        if "segs" not in ev:
            continue
        text = "".join(s.get("utf8", "") for s in ev["segs"]).replace("\n", " ").strip()
        if not text:
            continue

        start = float(ev.get("tStartMs", 0)) / 1000.0
        duration = float(ev.get("dDurationMs", 0)) / 1000.0
        end = start + duration

        if (start - last_end) > 2.0 and last_end > 0:
            speaker_toggle = 1 - speaker_toggle

        segments.append(
            TranscriptSegment(
                speaker=speaker_toggle,
                text=text,
                start=round(start, 2),
                end=round(end, 2),
                confidence=1.0,
            )
        )
        last_end = end

    return segments


def fetch_youtube_subtitles(
    url: str,
    preferred_lang: Optional[str] = None,
) -> Tuple[Optional[List[TranscriptSegment]], Dict[str, Any]]:
    """Fetch official or auto-generated subtitles directly from YouTube.

    Args:
        url: Full YouTube video URL.
        preferred_lang: Preferred subtitle language code (e.g. 'en', 'ja', 'vi', 'auto').

    Returns:
        Tuple of (List[TranscriptSegment] or None, metadata_dict)
    """
    try:
        import yt_dlp
    except ImportError:
        logger.debug("yt-dlp not installed, skipping YouTube subtitles extraction.")
        return None, {}

    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        logger.warning("Could not extract YouTube metadata: %s", e)
        return None, {}

    video_id = info.get("id", "video")
    title = info.get("title", f"YouTube Video ({video_id})")
    duration = float(info.get("duration", 0.0) or 0.0)
    video_lang = info.get("language")

    metadata = {
        "title": title,
        "duration": duration,
        "video_id": video_id,
        "detected_lang": video_lang or "en",
    }

    official_subs = info.get("subtitles", {})
    auto_subs = info.get("automatic_captions", {})

    target_lang = None
    lang_sub_entries = None
    is_official = False

    # Language priority search list
    candidates = []
    if preferred_lang and preferred_lang not in ("auto", "multi", ""):
        candidates.append(preferred_lang)
    if video_lang:
        candidates.append(video_lang)
    candidates.extend(["en", "ja", "vi", "ko", "zh-CN", "zh-TW", "fr", "de", "es"])

    # 1. Search in official manual subtitles first
    for cand in candidates:
        for k in official_subs:
            if k == cand or k.startswith(f"{cand}-") or cand in k:
                target_lang = k
                lang_sub_entries = official_subs[k]
                is_official = True
                break
        if lang_sub_entries:
            break

    # 2. If no official subs, search in automatic captions
    if not lang_sub_entries and auto_subs:
        for cand in candidates:
            for k in auto_subs:
                if k == cand or k.startswith(f"{cand}-") or cand in k:
                    target_lang = k
                    lang_sub_entries = auto_subs[k]
                    is_official = False
                    break
            if lang_sub_entries:
                break

    # 3. Fallback to any available language
    if not lang_sub_entries:
        if official_subs:
            target_lang = list(official_subs.keys())[0]
            lang_sub_entries = official_subs[target_lang]
            is_official = True
        elif auto_subs:
            target_lang = list(auto_subs.keys())[0]
            lang_sub_entries = auto_subs[target_lang]
            is_official = False

    if not lang_sub_entries:
        logger.info("No subtitles or captions found on YouTube for %s", video_id)
        return None, metadata

    metadata["subtitle_lang"] = target_lang
    metadata["is_official"] = is_official
    logger.info("Selected YouTube subtitle: lang=%s, official=%s", target_lang, is_official)

    # Prefer VTT format for clean sentence boundaries, then json3
    vtt_entry = next((s for s in lang_sub_entries if s.get("ext") == "vtt"), None)
    json3_entry = next((s for s in lang_sub_entries if s.get("ext") == "json3"), None)

    if vtt_entry:
        try:
            req = urllib.request.Request(vtt_entry["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                vtt_text = resp.read().decode("utf-8", errors="replace")
                segments = parse_vtt_subtitles(vtt_text)
                if segments:
                    logger.info("Parsed %d subtitle segments from YouTube VTT.", len(segments))
                    return segments, metadata
        except Exception as e:
            logger.warning("Failed to fetch/parse YouTube VTT subtitles: %s", e)

    if json3_entry:
        try:
            req = urllib.request.Request(json3_entry["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                json_data = json.loads(resp.read().decode("utf-8", errors="replace"))
                segments = parse_json3_subtitles(json_data)
                if segments:
                    logger.info("Parsed %d subtitle segments from YouTube JSON3.", len(segments))
                    return segments, metadata
        except Exception as e:
            logger.warning("Failed to fetch/parse YouTube JSON3 subtitles: %s", e)

    return None, metadata
