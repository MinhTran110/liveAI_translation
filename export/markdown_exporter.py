"""Markdown notes exporter (MemoAI study and meeting style)."""

from typing import Any, Dict, List


def format_clock_timestamp(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    sec_int = int(round(seconds))
    mins = sec_int // 60
    secs = sec_int % 60
    hours = mins // 60
    mins = mins % 60
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def export_markdown(note_data: Dict[str, Any]) -> str:
    """Export note and segments as a beautiful Markdown document."""
    title = note_data.get("title", "Untitled Note")
    duration = note_data.get("duration", 0.0)
    created_at = note_data.get("created_at", "")
    source_url = note_data.get("source_url") or ""
    source_lang = note_data.get("source_lang", "auto").upper()
    target_lang = note_data.get("target_lang", "vi").upper()
    segments = note_data.get("segments", [])

    lines = [
        f"# {title}",
        "",
        "> **MemoAI Video Notes**  ",
        f"> **Thời lượng:** {format_clock_timestamp(duration)} | **Nguồn:** {source_lang} → **Đích:** {target_lang}  ",
    ]
    if created_at:
        lines.append(f"> **Thời gian tạo:** {created_at}  ")
    if source_url:
        lines.append(f"> **Link nguồn:** [{source_url}]({source_url})  ")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📝 Nội Dung Ghi Chú & Bản Dịch")
    lines.append("")

    current_speaker = None
    for seg in segments:
        speaker = seg.get("speaker", 0)
        start_fmt = format_clock_timestamp(seg.get("start", 0.0))
        end_fmt = format_clock_timestamp(seg.get("end", 0.0))
        orig_text = seg.get("text", "").strip()
        trans_text = seg.get("translation", "").strip() or orig_text

        # Distinct speaker header
        if speaker != current_speaker:
            current_speaker = speaker
            lines.append(f"### 👤 Người nói {speaker}")

        lines.append(f"**`[{start_fmt} - {end_fmt}]`**")
        lines.append(f"» **{trans_text}**  ")
        if orig_text and orig_text != trans_text:
            lines.append(f"*Gốc:* {orig_text}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"
