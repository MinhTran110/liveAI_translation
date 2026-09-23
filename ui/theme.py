"""Terminal color scheme, modern dark theme palettes, and font resolution."""

from typing import List, Optional

# Modern Dark Theme Colors (VS Code / GitHub Dark inspired)
BACKGROUND_COLOR = "#0d1117"     # Deep canvas background
CONTAINER_COLOR = "#161b22"      # Card & subtitle panel background
HEADER_BG = "#161b22"            # Top control deck background
SUB_BAR_BG = "#0d1117"           # Utility sub-bar background
BORDER_COLOR = "#30363d"         # Subtle borders and dividers

# Interactive Widget Colors
BUTTON_BG = "#21262d"            # Flat button default background
BUTTON_HOVER = "#30363d"         # Flat button hover background
BUTTON_ACTIVE = "#1f6feb"        # Flat button pressed / active background
BUTTON_TEXT = "#e6edf3"          # Button text color
BUTTON_BORDER = "#30363d"

# Text Styling
TEXT_COLOR = "#c9d1d9"           # General body text
ORIGINAL_TEXT_COLOR = "#8b949e"  # Dimmed secondary color for spoken original text
TRANSLATED_TEXT_COLOR = "#ffffff"# Ultra-crisp high-contrast white for translated subtitles
TIMESTAMP_COLOR = "#6e7681"      # Subtle muted timestamp
STATUS_TEXT_COLOR = "#8b949e"

# Accent Colors
ACCENT_BLUE = "#58a6ff"          # Brand & primary accent
ACCENT_GREEN = "#3fb950"         # Audio signal active / live status
ACCENT_AMBER = "#d29922"         # Paused / warning state
ACCENT_RED = "#ff7b72"           # Error / audio clipping

# Distinct, high-contrast speaker color palette for diarization
SPEAKER_PALETTE: List[str] = [
    "#58a6ff",  # Speaker 0: Electric Cyan/Blue
    "#3fb950",  # Speaker 1: Mint Green
    "#f0883e",  # Speaker 2: Vibrant Tangerine Orange
    "#d2a8ff",  # Speaker 3: Soft Violet Lavender
    "#f778ba",  # Speaker 4: Rose Pink
    "#2dd4bf",  # Speaker 5: Aqua Teal
    "#e3b341",  # Speaker 6: Warm Amber Yellow
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
        hash_val = sum(ord(c) for c in str(speaker_id))
        return SPEAKER_PALETTE[hash_val % len(SPEAKER_PALETTE)]


# Font sizing defaults
FONT_SIZE_TIMESTAMP = 9
FONT_SIZE_SPEAKER = 10
FONT_SIZE_ORIGINAL = 10
FONT_SIZE_TRANSLATED = 13


def ensure_x11_truetype_fonts() -> None:
    """Ensure TrueType fonts (like Arial) are indexed and registered in X11 font path."""
    import os
    import platform
    import shutil
    import subprocess
    from pathlib import Path

    if platform.system() != "Linux" or not os.getenv("DISPLAY"):
        return

    user_font_dir = Path.home() / ".fonts" / "msttcorefonts"
    sys_font_dir = Path("/usr/share/fonts/truetype/msttcorefonts")

    try:
        if sys_font_dir.exists() and not (user_font_dir / "fonts.dir").exists():
            user_font_dir.mkdir(parents=True, exist_ok=True)
            for ttf in sys_font_dir.glob("*.ttf"):
                dest = user_font_dir / ttf.name
                if not dest.exists():
                    try:
                        dest.symlink_to(ttf)
                    except Exception:
                        shutil.copy2(ttf, dest)
            if shutil.which("mkfontscale"):
                subprocess.run(["mkfontscale", str(user_font_dir)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if shutil.which("mkfontdir"):
                subprocess.run(["mkfontdir", str(user_font_dir)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if user_font_dir.exists() and shutil.which("xset"):
            subprocess.run(["xset", "+fp", str(user_font_dir)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["xset", "fp", "rehash"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def get_ui_font_family(root=None) -> str:
    """Find the best available TrueType font for subtitles and UI, strictly prioritizing Arial."""
    ensure_x11_truetype_fonts()
    candidates = [
        "Arial",
        "Nimbus Sans L",
        "Helvetica",
        "Liberation Sans",
        "DejaVu Sans",
        "Ubuntu",
        "Segoe UI",
        "sans-serif",
    ]
    if root is not None:
        try:
            import tkinter.font as tkfont

            available = {f.lower(): f for f in tkfont.families(root)}
            for cand in candidates:
                if cand.lower() in available:
                    return available[cand.lower()]
        except Exception:
            pass
    return "Arial"


def get_mono_font_family(root=None) -> str:
    """Find the best available font for code, badges, and meters, strictly prioritizing Arial."""
    ensure_x11_truetype_fonts()
    candidates = [
        "Arial",
        "Nimbus Mono L",
        "Nimbus Sans L",
        "Liberation Mono",
        "DejaVu Sans Mono",
        "Consolas",
        "monospace",
    ]
    if root is not None:
        try:
            import tkinter.font as tkfont

            available = {f.lower(): f for f in tkfont.families(root)}
            for cand in candidates:
                if cand.lower() in available:
                    return available[cand.lower()]
        except Exception:
            pass
    return "Arial"


