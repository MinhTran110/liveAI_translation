"""SRT Subtitle file exporter."""

from typing import Any, Dict, List


def format_srt_timestamp(seconds: float) -> str:
    """Format float seconds to SRT timestamp: HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_sec = total_ms // 1000
    sec = total_sec % 60
    total_min = total_sec // 60
    mins = total_min % 60
    hours = total_min // 60
    return f"{hours:02d}:{mins:02d}:{sec:02d},{ms:03d}"


def export_srt(segments: List[Dict[str, Any]], bilingual: bool = True) -> str:
    """Convert segment list to standard SRT subtitle text.

    Args:
        segments: List of segment dicts with start, end, speaker, text, translation.
        bilingual: If True, include both translated and original text.

    Returns:
        Formatted SRT file content string.
    """
    entries = []
    for idx, seg in enumerate(segments, start=1):
        start_str = format_srt_timestamp(seg.get("start", 0.0))
        end_str = format_srt_timestamp(seg.get("end", 0.0))
        speaker = seg.get("speaker", 0)
        orig_text = seg.get("text", "").strip()
        trans_text = seg.get("translation", "").strip() or orig_text

        if bilingual and orig_text and orig_text != trans_text:
            content = f"[Speaker {speaker}] {trans_text}\n({orig_text})"
        else:
            content = f"[Speaker {speaker}] {trans_text}"

        entry = f"{idx}\n{start_str} --> {end_str}\n{content}\n"
        entries.append(entry)

    return "\n".join(entries).strip() + "\n"
