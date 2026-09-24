import json
import logging
import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple
import urllib.request

from transcribe.base import TranscriptSegment

logger = logging.getLogger(__name__)


def clean_youtube_url(url: str) -> str:
    """Normalize YouTube URL to single video URL, stripping playlist & tracking query params."""
    if not url:
        return url
    match = re.search(r"(?:v=|\/shorts\/|youtu\.be\/)([a-zA-Z0-9_-]{11})", url)
    if match:
        video_id = match.group(1)
        return f"https://www.youtube.com/watch?v={video_id}"
    return url


def get_js_runtime_config():
    """Detect available JS runtime (Node, Deno, Bun, QuickJS) and patch yt-dlp."""
    try:
        import yt_dlp.utils._jsruntime as _jsr
        if hasattr(_jsr, "NodeJsRuntime"):
            _jsr.NodeJsRuntime.MIN_SUPPORTED_VERSION = (16, 0, 0)
    except Exception:
        pass

    for runtime in ["node", "deno", "bun", "quickjs"]:
        path = shutil.which(runtime)
        if not path and runtime == "node":
            if os.path.exists("/usr/bin/node"):
                path = "/usr/bin/node"
            elif os.path.exists("/usr/bin/nodejs"):
                path = "/usr/bin/nodejs"
        if path:
            return {"js_runtimes": {runtime: {"path": path}}}, ["--js-runtimes", f"{runtime}:{path}"]
    return {}, []


def merge_sentence_segments(
    segments: List[TranscriptSegment],
    max_gap: float = 1.5,
    max_len: int = 140,
) -> List[TranscriptSegment]:
    """Merge short spoken/lyric fragments into grammatically coherent sentences for translation."""
    if not segments:
        return []
    merged: List[TranscriptSegment] = []
    curr: Optional[TranscriptSegment] = None
    enders = {".", "!", "?", "。", "！", "？", "…"}

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        if curr is None:
            curr = TranscriptSegment(
                speaker=seg.speaker,
                text=text,
                start=seg.start,
                end=seg.end,
                confidence=seg.confidence,
            )
            continue

        prev_has_ender = any(curr.text.endswith(e) for e in enders)
        gap = seg.start - curr.end
        can_merge = (
            seg.speaker == curr.speaker
            and not prev_has_ender
            and gap <= max_gap
            and (len(curr.text) + len(text)) <= max_len
        )

        if can_merge:
            is_cjk = any("\u3000" <= c <= "\u9fff" for c in curr.text[-1] + text[0])
            sep = "" if is_cjk else " "
            curr.text = curr.text + sep + text
            curr.end = max(curr.end, seg.end)
        else:
            merged.append(curr)
            curr = TranscriptSegment(
                speaker=seg.speaker,
                text=text,
                start=seg.start,
                end=seg.end,
                confidence=seg.confidence,
            )
    if curr:
        merged.append(curr)
    return merged


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
                content_lines = lines[idx + 1 :]
                cleaned_lines = []
                for cl in content_lines:
                    c = re.sub(r"<[^>]+>", "", cl)
                    c = c.replace("&nbsp;", " ").replace("&amp;", "&").strip()
                    if c and not c.startswith("Kind:") and not c.startswith("Language:"):
                        cleaned_lines.append(c)

                if not cleaned_lines:
                    continue

                # Handle YouTube rolling 2-line auto-caption window (line 0 is often previous line)
                if len(cleaned_lines) == 2 and last_text and (cleaned_lines[0] in last_text or last_text in cleaned_lines[0]):
                    clean = cleaned_lines[1]
                else:
                    clean = " ".join(cleaned_lines).strip()

                if not clean or clean == last_text:
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

    url = clean_youtube_url(url)
    ydl_dict, _ = get_js_runtime_config()
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        **ydl_dict,
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
    candidates.extend(["ja", "en", "vi", "ko", "zh-CN", "zh-TW", "fr", "de", "es"])

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

    # Prefer json3 for discrete word timings & avoiding rolling duplicates, then vtt
    json3_entry = next((s for s in lang_sub_entries if s.get("ext") == "json3"), None)
    vtt_entry = next((s for s in lang_sub_entries if s.get("ext") == "vtt"), None)

    if json3_entry:
        try:
            req = urllib.request.Request(json3_entry["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                json_data = json.loads(resp.read().decode("utf-8", errors="replace"))
                segments = parse_json3_subtitles(json_data)
                if segments:
                    segments = merge_sentence_segments(segments)
                    logger.info("Parsed %d subtitle segments from YouTube JSON3.", len(segments))
                    return segments, metadata
        except Exception as e:
            logger.warning("Failed to fetch/parse YouTube JSON3 subtitles: %s", e)

    if vtt_entry:
        try:
            req = urllib.request.Request(vtt_entry["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                vtt_text = resp.read().decode("utf-8", errors="replace")
                segments = parse_vtt_subtitles(vtt_text)
                if segments:
                    segments = merge_sentence_segments(segments)
                    logger.info("Parsed %d subtitle segments from YouTube VTT.", len(segments))
                    return segments, metadata
        except Exception as e:
            logger.warning("Failed to fetch/parse YouTube VTT subtitles: %s", e)

    return None, metadata
