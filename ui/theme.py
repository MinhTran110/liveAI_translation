"""Terminal color scheme, fonts, and speaker diarization palette."""

from typing import Dict, List

# Primary terminal window colors
BACKGROUND_COLOR = "#181818"
CONTAINER_COLOR = "#1e1e1e"
TEXT_COLOR = "#cccccc"
HEADER_BG = "#252526"
STATUS_BG = "#0d1117"
BORDER_COLOR = "#333333"

# Subtitle text formatting
ORIGINAL_TEXT_COLOR = "#8b949e"  # Subtle/dimmed gray for source transcript
TRANSLATED_TEXT_COLOR = "#f0f6fc"  # Bright white for translated text
TIMESTAMP_COLOR = "#6e7681"

# Distinct speaker color palette for diarization
SPEAKER_PALETTE: List[str] = [
    "#58a6ff",  # Speaker 0: Cyan / Electric Blue
    "#3fb950",  # Speaker 1: Mint Green
    "#d29922",  # Speaker 2: Amber Yellow
    "#bc8cff",  # Speaker 3: Soft Purple
    "#f778ba",  # Speaker 4: Rose Pink
    "#2dd4bf",  # Speaker 5: Aqua Teal
    "#ff7b72",  # Speaker 6: Coral Red
    "#79c0ff",  # Speaker 7: Sky Blue
]


def get_speaker_color(speaker_id: int | str | None) -> str:
    """Retrieve distinct color for a given speaker ID."""
    if speaker_id is None:
        return SPEAKER_PALETTE[0]

    if isinstance(speaker_id, int):
        return SPEAKER_PALETTE[speaker_id % len(SPEAKER_PALETTE)]

    # Handle string identifiers like "Speaker 0" or names
    try:
        num = int("".join(filter(str.isdigit, str(speaker_id))))
        return SPEAKER_PALETTE[num % len(SPEAKER_PALETTE)]
    except ValueError:
        # Hash string for stable color mapping
        hash_val = sum(ord(c) for c in str(speaker_id))
        return SPEAKER_PALETTE[hash_val % len(SPEAKER_PALETTE)]


# Preferred monospace fonts across platforms
FONT_FAMILY = "Consolas, 'Courier New', 'JetBrains Mono', 'Fira Code', monospace"
FONT_SIZE_TIMESTAMP = 9
FONT_SIZE_SPEAKER = 10
FONT_SIZE_ORIGINAL = 10
FONT_SIZE_TRANSLATED = 12
