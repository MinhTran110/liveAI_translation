"""WebVTT Subtitle file exporter."""

from typing import Any, Dict, List


def format_vtt_timestamp(seconds: float) -> str:
    """Format float seconds to WebVTT timestamp: HH:MM:SS.mmm."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_sec = total_ms // 1000
    sec = total_sec % 60
    total_min = total_sec // 60
    mins = total_min % 60
    hours = total_min // 60
    return f"{hours:02d}:{mins:02d}:{sec:02d}.{ms:03d}"


def export_vtt(segments: List[Dict[str, Any]], bilingual: bool = True) -> str:
    """Convert segment list to standard WebVTT subtitle text."""
    lines = ["WEBVTT", ""]
    for idx, seg in enumerate(segments, start=1):
        start_str = format_vtt_timestamp(seg.get("start", 0.0))
        end_str = format_vtt_timestamp(seg.get("end", 0.0))
        speaker = seg.get("speaker", 0)
        orig_text = seg.get("text", "").strip()
        trans_text = seg.get("translation", "").strip() or orig_text

        lines.append(f"{idx}")
        lines.append(f"{start_str} --> {end_str}")
        lines.append(f"<v Speaker {speaker}>{trans_text}")
        if bilingual and orig_text and orig_text != trans_text:
            lines.append(f"({orig_text})")
        lines.append("")

    return "\n".join(lines).strip() + "\n"
