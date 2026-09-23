"""Modern always-on-top desktop subtitle overlay with flat styling, TrueType fonts, and LED VU meter."""

from datetime import datetime
import logging
import queue
import threading
import time
from typing import Callable, Optional

from ui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_RED,
    BACKGROUND_COLOR,
    BORDER_COLOR,
    BUTTON_ACTIVE,
    BUTTON_BG,
    BUTTON_HOVER,
    BUTTON_TEXT,
    CONTAINER_COLOR,
    FONT_SIZE_ORIGINAL,
    FONT_SIZE_SPEAKER,
    FONT_SIZE_TIMESTAMP,
    FONT_SIZE_TRANSLATED,
    HEADER_BG,
    ORIGINAL_TEXT_COLOR,
    STATUS_TEXT_COLOR,
    SUB_BAR_BG,
    TEXT_COLOR,
    TIMESTAMP_COLOR,
    TRANSLATED_TEXT_COLOR,
    get_mono_font_family,
    get_speaker_color,
    get_ui_font_family,
)

logger = logging.getLogger(__name__)

LANGUAGES = [
    ("vi", "Tiếng Việt"),
    ("en", "English"),
    ("ja", "日本語"),
    ("zh", "中文"),
    ("ko", "한국어"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("ru", "Русский"),
]


class TerminalWindow:
    """Always-on-top modern subtitle window for live audio translation."""

    def __init__(
        self,
        title: str = "Live AI Translation Subtitles",
        width: int = 760,
        height: int = 500,
        always_on_top: bool = True,
        status_info: str = "Đang lắng nghe...",
        target_language: str = "vi",
        on_language_change: Optional[Callable[[str], None]] = None,
        audio_volume_provider: Optional[Callable[[], float]] = None,
    ):
        self.window_title = title
        self.width = width
        self.height = height
        self.always_on_top = always_on_top
        self.status_info = status_info
        self.target_language = target_language
        self.on_language_change = on_language_change
        self.audio_volume_provider = audio_volume_provider

        self._queue: queue.Queue = queue.Queue()
        self._root = None
        self._text_area = None
        self._status_var = None
        self._topmost_var = None
        self._opacity_var = None
        self._opacity_label = None
        self._font_size_label = None
        self._count_label = None
        self._vu_canvas = None
        self._pause_btn = None
        self._pin_btn = None
        self._font_size = FONT_SIZE_TRANSLATED
        self._is_paused = False
        self._is_closed = False
        self._speaker_tag_counter = 0
        self._subtitle_count = 0

        self.ui_font = "DejaVu Sans"
        self.mono_font = "DejaVu Sans Mono"

    def start_in_thread(self) -> threading.Thread:
        """Start Tkinter window in a dedicated background thread."""
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread

    def _create_flat_button(
        self,
        parent,
        text: str,
        command: Callable,
        padx: int = 8,
        pady: int = 3,
        bg: str = BUTTON_BG,
        fg: str = BUTTON_TEXT,
    ):
        """Create a modern flat button with responsive hover effects."""
        import tkinter as tk

        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=BUTTON_HOVER,
            activeforeground="#ffffff",
            bd=0,
            relief=tk.FLAT,
            padx=padx,
            pady=pady,
            cursor="hand2",
            font=(self.ui_font, 9),
            highlightthickness=0,
        )

        def on_enter(e):
            if btn.cget("state") != "disabled":
                btn.configure(bg=BUTTON_HOVER)

        def on_leave(e):
            if btn.cget("state") != "disabled":
                btn.configure(bg=bg)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        return btn

    def run(self) -> None:
        """Create and run Tkinter window main loop."""
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            logger.warning("Tkinter is not available. Falling back to console rendering.")
            self._run_fallback_loop()
            return

        try:
            self._root = tk.Tk()
        except Exception as e:
            logger.warning("Could not initialize Tkinter display (%s). Falling back to console renderer.", e)
            self._run_fallback_loop()
            return

        # Resolve clean system TrueType fonts
        self.ui_font = get_ui_font_family(self._root)
        self.mono_font = get_mono_font_family(self._root)

        self._root.title(self.window_title)
        self._root.geometry(f"{self.width}x{self.height}")
        self._root.configure(bg=BACKGROUND_COLOR)

        # Apply dark ttk styling
        style = ttk.Style(self._root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Flat dark scrollbar style
        style.configure(
            "Dark.Vertical.TScrollbar",
            gripcount=0,
            background="#21262d",
            darkcolor="#21262d",
            lightcolor="#21262d",
            troughcolor="#0d1117",
            bordercolor="#161b22",
            arrowcolor="#8b949e",
            arrowsize=10,
            width=10,
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", "#388bfd"), ("pressed", "#1f6feb")],
            arrowcolor=[("active", "#58a6ff")],
        )

        # Dark Combobox style
        style.configure(
            "Dark.TCombobox",
            fieldbackground="#21262d",
            background="#21262d",
            foreground="#ffffff",
            darkcolor="#30363d",
            lightcolor="#30363d",
            arrowcolor="#58a6ff",
            bordercolor="#30363d",
            selectbackground="#1f6feb",
            selectforeground="#ffffff",
            padding=3,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", "#21262d")],
            selectbackground=[("readonly", "#21262d")],
        )

        # Configure window attributes
        try:
            self._root.wm_attributes("-topmost", self.always_on_top)
            self._root.wm_attributes("-alpha", 0.95)
        except Exception:
            pass

        # 1. Top Control Header (Dark deck)
        header_frame = tk.Frame(self._root, bg=HEADER_BG, padx=12, pady=6)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        # App Brand & Status
        brand_frame = tk.Frame(header_frame, bg=HEADER_BG)
        brand_frame.pack(side=tk.LEFT)

        self._status_dot = tk.Label(
            brand_frame,
            text="●",
            bg=HEADER_BG,
            fg=ACCENT_GREEN,
            font=(self.ui_font, 11),
        )
        self._status_dot.pack(side=tk.LEFT, padx=(0, 4))

        title_lbl = tk.Label(
            brand_frame,
            text="LIVE TRANSLATE",
            bg=HEADER_BG,
            fg="#ffffff",
            font=(self.ui_font, 10, "bold"),
        )
        title_lbl.pack(side=tk.LEFT, padx=(0, 8))

        self._status_var = tk.StringVar(value=self.status_info)
        status_lbl = tk.Label(
            brand_frame,
            textvariable=self._status_var,
            bg=HEADER_BG,
            fg=STATUS_TEXT_COLOR,
            font=(self.ui_font, 9),
        )
        status_lbl.pack(side=tk.LEFT)

        # Center: LED Audio VU Meter
        vu_frame = tk.Frame(header_frame, bg=HEADER_BG)
        vu_frame.pack(side=tk.LEFT, padx=(20, 0))

        vu_label = tk.Label(
            vu_frame,
            text="AUDIO",
            bg=HEADER_BG,
            fg="#8b949e",
            font=(self.mono_font, 8, "bold"),
        )
        vu_label.pack(side=tk.LEFT, padx=(0, 5))

        self._vu_canvas = tk.Canvas(
            vu_frame,
            width=76,
            height=12,
            bg="#0d1117",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
        )
        self._vu_canvas.pack(side=tk.LEFT)

        # Right-side Toolbar Controls
        tools_frame = tk.Frame(header_frame, bg=HEADER_BG)
        tools_frame.pack(side=tk.RIGHT)

        # Target Language combobox
        lang_icon = tk.Label(
            tools_frame,
            text="🌐",
            bg=HEADER_BG,
            fg="#8b949e",
            font=(self.ui_font, 9),
        )
        lang_icon.pack(side=tk.LEFT, padx=(0, 2))

        # Format combobox values: "Tiếng Việt (vi)"
        lang_display_map = {code: f"{name} ({code})" for code, name in LANGUAGES}
        reverse_map = {f"{name} ({code})": code for code, name in LANGUAGES}
        current_disp = lang_display_map.get(self.target_language, f"({self.target_language})")

        self._lang_var = tk.StringVar(value=current_disp)
        lang_dropdown = ttk.Combobox(
            tools_frame,
            textvariable=self._lang_var,
            values=[lang_display_map[code] for code, _ in LANGUAGES],
            width=13,
            state="readonly",
            style="Dark.TCombobox",
            font=(self.ui_font, 9),
        )
        lang_dropdown.pack(side=tk.LEFT, padx=(0, 8))

        def on_combobox_select(event=None):
            disp = self._lang_var.get()
            code = reverse_map.get(disp, disp)
            self._handle_lang_change(code)

        lang_dropdown.bind("<<ComboboxSelected>>", on_combobox_select)

        # Pin Button
        pin_text = "📌 Đã ghim" if self.always_on_top else "📌 Ghim"
        self._pin_btn = self._create_flat_button(
            tools_frame,
            text=pin_text,
            command=self._toggle_topmost,
            padx=7,
            pady=2,
        )
        self._pin_btn.pack(side=tk.LEFT, padx=(0, 4))

        # Pause / Resume Button
        self._pause_btn = self._create_flat_button(
            tools_frame,
            text="⏸ Tạm dừng",
            command=self._toggle_pause,
            padx=7,
            pady=2,
        )
        self._pause_btn.pack(side=tk.LEFT, padx=(0, 4))

        # Clear Button
        clear_btn = self._create_flat_button(
            tools_frame,
            text="🗑 Xóa",
            command=self.clear,
            padx=7,
            pady=2,
        )
        clear_btn.pack(side=tk.LEFT)

        # 2. Secondary Utility Bar (Opacity & Font scaling)
        sub_bar = tk.Frame(self._root, bg=SUB_BAR_BG, padx=12, pady=3)
        sub_bar.pack(side=tk.TOP, fill=tk.X)

        # Left: Opacity slider
        opacity_lbl = tk.Label(
            sub_bar,
            text="Độ mờ:",
            bg=SUB_BAR_BG,
            fg="#8b949e",
            font=(self.ui_font, 8),
        )
        opacity_lbl.pack(side=tk.LEFT, padx=(0, 4))

        self._opacity_var = tk.DoubleVar(value=0.95)
        opacity_slider = tk.Scale(
            sub_bar,
            from_=0.4,
            to=1.0,
            resolution=0.01,
            orient=tk.HORIZONTAL,
            variable=self._opacity_var,
            command=self._update_opacity,
            showvalue=0,
            length=75,
            bg=SUB_BAR_BG,
            fg="#8b949e",
            troughcolor="#21262d",
            activebackground=ACCENT_BLUE,
            highlightthickness=0,
            bd=0,
            sliderrelief=tk.FLAT,
        )
        opacity_slider.pack(side=tk.LEFT)

        self._opacity_label = tk.Label(
            sub_bar,
            text="95%",
            bg=SUB_BAR_BG,
            fg="#6e7681",
            font=(self.mono_font, 8),
            width=4,
            anchor="w",
        )
        self._opacity_label.pack(side=tk.LEFT, padx=(3, 10))

        # Subtitle counter
        self._count_label = tk.Label(
            sub_bar,
            text="0 câu đã dịch",
            bg=SUB_BAR_BG,
            fg="#6e7681",
            font=(self.ui_font, 8),
        )
        self._count_label.pack(side=tk.LEFT)

        # Right: Font size controls
        font_box = tk.Frame(sub_bar, bg=SUB_BAR_BG)
        font_box.pack(side=tk.RIGHT)

        font_lbl = tk.Label(
            font_box,
            text="Cỡ chữ:",
            bg=SUB_BAR_BG,
            fg="#8b949e",
            font=(self.ui_font, 8),
        )
        font_lbl.pack(side=tk.LEFT, padx=(0, 4))

        font_down_btn = self._create_flat_button(
            font_box,
            text="－",
            command=self._decrease_font,
            padx=4,
            pady=0,
            bg="#161b22",
        )
        font_down_btn.pack(side=tk.LEFT)

        self._font_size_label = tk.Label(
            font_box,
            text=f"{self._font_size}pt",
            bg=SUB_BAR_BG,
            fg="#c9d1d9",
            font=(self.mono_font, 8),
            width=5,
            anchor="center",
        )
        self._font_size_label.pack(side=tk.LEFT, padx=2)

        font_up_btn = self._create_flat_button(
            font_box,
            text="＋",
            command=self._increase_font,
            padx=4,
            pady=0,
            bg="#161b22",
        )
        font_up_btn.pack(side=tk.LEFT)

        # 3. Content Frame with modern dark scrollbar
        content_frame = tk.Frame(self._root, bg=BACKGROUND_COLOR, padx=10, pady=6)
        content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._text_area = tk.Text(
            content_frame,
            wrap=tk.WORD,
            bg=CONTAINER_COLOR,
            fg=TEXT_COLOR,
            insertbackground="#ffffff",
            selectbackground="#1f6feb",
            selectforeground="#ffffff",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            padx=16,
            pady=12,
            font=(self.ui_font, self._font_size),
            spacing1=2,
            spacing3=4,
        )

        scrollbar = ttk.Scrollbar(
            content_frame,
            orient="vertical",
            command=self._text_area.yview,
            style="Dark.Vertical.TScrollbar",
        )
        self._text_area.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure Subtitle Display Tags
        self._text_area.tag_configure(
            "timestamp",
            foreground=TIMESTAMP_COLOR,
            font=(self.mono_font, FONT_SIZE_TIMESTAMP),
        )
        self._text_area.tag_configure(
            "original",
            foreground=ORIGINAL_TEXT_COLOR,
            font=(self.ui_font, FONT_SIZE_ORIGINAL, "italic"),
            lmargin1=16,
            lmargin2=16,
            spacing1=2,
            spacing3=2,
        )
        self._text_area.tag_configure(
            "translated",
            foreground=TRANSLATED_TEXT_COLOR,
            font=(self.ui_font, self._font_size, "bold"),
            lmargin1=16,
            lmargin2=16,
            spacing1=4,
            spacing3=6,
        )
        self._text_area.tag_configure(
            "divider",
            foreground="#21262d",
            font=(self.mono_font, 6),
            spacing1=2,
            spacing3=6,
        )

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Schedule event loops
        self._root.after(40, self._process_queue)
        self._root.after(80, self._update_vu_meter)
        self._root.mainloop()

    def _handle_lang_change(self, new_lang: str) -> None:
        """Handle target language selection."""
        self.target_language = new_lang
        if self.on_language_change:
            self.on_language_change(new_lang)
        self.set_status(f"Dịch sang: {new_lang.upper()}")

    def _update_opacity(self, val: str) -> None:
        """Update window transparency and indicator label."""
        if self._root:
            try:
                op_val = float(val)
                self._root.wm_attributes("-alpha", op_val)
                if self._opacity_label:
                    self._opacity_label.config(text=f"{int(round(op_val * 100))}%")
            except Exception:
                pass

    def _toggle_pause(self) -> None:
        """Toggle subtitle rendering pause state."""
        self._is_paused = not self._is_paused
        if self._is_paused:
            if self._pause_btn:
                self._pause_btn.config(text="▶ Tiếp tục", fg=ACCENT_AMBER)
            if self._status_dot:
                self._status_dot.config(fg=ACCENT_AMBER)
            self.set_status("Đã tạm dừng")
        else:
            if self._pause_btn:
                self._pause_btn.config(text="⏸ Tạm dừng", fg=BUTTON_TEXT)
            if self._status_dot:
                self._status_dot.config(fg=ACCENT_GREEN)
            self.set_status("Đang lắng nghe...")

    def _increase_font(self) -> None:
        """Increase subtitle font size."""
        self._font_size = min(24, self._font_size + 1)
        if self._font_size_label:
            self._font_size_label.config(text=f"{self._font_size}pt")
        if self._text_area:
            self._text_area.tag_configure("translated", font=(self.ui_font, self._font_size, "bold"))

    def _decrease_font(self) -> None:
        """Decrease subtitle font size."""
        self._font_size = max(10, self._font_size - 1)
        if self._font_size_label:
            self._font_size_label.config(text=f"{self._font_size}pt")
        if self._text_area:
            self._text_area.tag_configure("translated", font=(self.ui_font, self._font_size, "bold"))

    def _update_vu_meter(self) -> None:
        """Draw modern multi-segment LED meter on canvas."""
        if self._vu_canvas and self.audio_volume_provider:
            try:
                vol = max(0.0, min(1.0, self.audio_volume_provider()))
                self._vu_canvas.delete("all")

                total_segments = 8
                seg_w = 7
                gap = 2
                active_segments = int(round(vol * total_segments))
                if vol > 0.01 and active_segments == 0:
                    active_segments = 1

                for i in range(total_segments):
                    x0 = 4 + i * (seg_w + gap)
                    x1 = x0 + seg_w
                    y0 = 2
                    y1 = 10

                    if i < active_segments:
                        if i < 5:
                            color = ACCENT_GREEN
                        elif i < 7:
                            color = ACCENT_AMBER
                        else:
                            color = ACCENT_RED
                    else:
                        color = "#21262d"

                    self._vu_canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
            except Exception:
                pass

        if not self._is_closed and self._root:
            self._root.after(80, self._update_vu_meter)

    def _toggle_topmost(self) -> None:
        """Toggle window always-on-top state."""
        self.always_on_top = not self.always_on_top
        if self._root:
            try:
                self._root.wm_attributes("-topmost", self.always_on_top)
            except Exception:
                pass
        if self._pin_btn:
            if self.always_on_top:
                self._pin_btn.config(text="📌 Đã ghim", fg=ACCENT_BLUE)
            else:
                self._pin_btn.config(text="📌 Ghim", fg=BUTTON_TEXT)

    def _on_close(self) -> None:
        """Handle window close event."""
        self.close()

    def close(self) -> None:
        """Close window and stop processing loops."""
        self._is_closed = True
        if self._root:
            try:
                self._root.destroy()
            except Exception:
                pass

    def set_status(self, text: str) -> None:
        """Update header status message."""
        self.status_info = text
        if self._status_var and self._root:
            self._root.after(0, lambda: self._status_var.set(text))

    def render(self, speaker: Optional[int | str], original_text: str, translated_text: str) -> None:
        """Post a subtitle item to be displayed on the terminal window (thread-safe)."""
        if self._is_paused or self._is_closed:
            return
        self._queue.put((speaker, original_text, translated_text, datetime.now()))

    def _process_queue(self) -> None:
        """Poll queued subtitle events and append them to the text widget."""
        while not self._queue.empty():
            try:
                speaker, orig, trans, timestamp = self._queue.get_nowait()
                self._insert_subtitle(speaker, orig, trans, timestamp)
                self._queue.task_done()
            except queue.Empty:
                break

        if not self._is_closed and self._root:
            self._root.after(40, self._process_queue)

    def _insert_subtitle(
        self,
        speaker: Optional[int | str],
        orig: str,
        trans: str,
        timestamp: datetime,
    ) -> None:
        """Format and insert a clean dialogue card into Tkinter text widget."""
        if not self._text_area:
            return

        spk_str = f"Speaker {speaker}" if isinstance(speaker, int) else str(speaker or "Speaker")
        time_str = timestamp.strftime("%H:%M:%S")

        # Dynamic tag for speaker color
        spk_color = get_speaker_color(speaker)
        spk_bullet_tag = f"spk_bullet_{self._speaker_tag_counter}"
        spk_name_tag = f"spk_name_{self._speaker_tag_counter}"
        self._speaker_tag_counter += 1

        self._text_area.tag_configure(
            spk_bullet_tag,
            foreground=spk_color,
            font=(self.ui_font, FONT_SIZE_SPEAKER, "bold"),
        )
        self._text_area.tag_configure(
            spk_name_tag,
            foreground=spk_color,
            font=(self.ui_font, FONT_SIZE_SPEAKER, "bold"),
        )

        # 1. Speaker Header: "● Speaker 0    14:35:10"
        self._text_area.insert("end", "● ", spk_bullet_tag)
        self._text_area.insert("end", f"{spk_str}   ", spk_name_tag)
        self._text_area.insert("end", f"{time_str}\n", "timestamp")

        # 2. Original Spoken Transcript (subtle, indented)
        if orig:
            self._text_area.insert("end", f"{orig}\n", "original")

        # 3. Translated Text (prominent, high contrast white, bold)
        if trans:
            self._text_area.insert("end", f"💬 {trans}\n", "translated")

        # 4. Subtle divider line
        self._text_area.insert("end", "─" * 48 + "\n\n", "divider")

        # Increment count
        self._subtitle_count += 1
        if self._count_label:
            self._count_label.config(text=f"{self._subtitle_count} câu đã dịch")

        # Auto-scroll to end
        self._text_area.see("end")

    def clear(self) -> None:
        """Clear subtitle display."""
        if self._text_area:
            self._text_area.delete("1.0", "end")
        self._subtitle_count = 0
        if self._count_label:
            self._count_label.config(text="0 câu đã dịch")

    def _run_fallback_loop(self) -> None:
        """Headless console fallback loop when Tkinter/GUI display is unavailable."""
        try:
            from rich.console import Console

            console = Console()
        except ImportError:
            console = None

        logger.info("Running live translation in headless console mode.")
        while not self._is_closed:
            try:
                speaker, orig, trans, timestamp = self._queue.get(timeout=0.5)
                time_str = timestamp.strftime("[%H:%M:%S]")
                spk_str = f"Speaker {speaker}" if isinstance(speaker, int) else str(speaker or "Speaker")
                color = get_speaker_color(speaker)

                if console:
                    console.print(f"[dim]{time_str}[/dim] [bold {color}]● {spk_str}[/bold {color}]")
                    if orig:
                        console.print(f"  [dim italic]{orig}[/dim italic]")
                    if trans:
                        console.print(f"  [bold white]💬 {trans}[/bold white]")
                    console.print("[dim]──────────────────────────────────────────────[/dim]")
                else:
                    print(f"{time_str} ● {spk_str}")
                    if orig:
                        print(f"   {orig}")
                    if trans:
                        print(f"   💬 {trans}")
                    print("-" * 48)
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                break

