"""Tkinter always-on-top terminal subtitle window with headless fallback."""

from datetime import datetime
import logging
import queue
import sys
import threading
from typing import Optional

from ui.theme import (
    BACKGROUND_COLOR,
    BORDER_COLOR,
    CONTAINER_COLOR,
    FONT_SIZE_ORIGINAL,
    FONT_SIZE_SPEAKER,
    FONT_SIZE_TIMESTAMP,
    FONT_SIZE_TRANSLATED,
    HEADER_BG,
    ORIGINAL_TEXT_COLOR,
    STATUS_BG,
    TEXT_COLOR,
    TRANSLATED_TEXT_COLOR,
    get_speaker_color,
)

logger = logging.getLogger(__name__)


class TerminalWindow:
    """Always-on-top Tkinter window styled like a terminal for real-time translation subtitles."""

    def __init__(
        self,
        title: str = "Live Voice Translate",
        width: int = 680,
        height: int = 420,
        always_on_top: bool = True,
        status_info: str = "Ready",
    ):
        self.window_title = title
        self.width = width
        self.height = height
        self.always_on_top = always_on_top
        self.status_info = status_info

        self._queue: queue.Queue = queue.Queue()
        self._root = None
        self._text_area = None
        self._status_var = None
        self._topmost_var = None
        self._is_paused = False
        self._is_closed = False
        self._speaker_tag_counter = 0

    def start_in_thread(self) -> threading.Thread:
        """Start Tkinter window in a dedicated background thread."""
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread

    def run(self) -> None:
        """Create and run Tkinter window main loop."""
        try:
            import tkinter as tk
            from tkinter import ttk, scrolledtext
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

        self._root.title(self.window_title)
        self._root.geometry(f"{self.width}x{self.height}")
        self._root.configure(bg=BACKGROUND_COLOR)

        # Configure always-on-top
        try:
            self._root.wm_attributes("-topmost", self.always_on_top)
        except Exception:
            pass

        # Top control header
        header_frame = tk.Frame(self._root, bg=HEADER_BG, height=36, padx=8, pady=4)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        title_lbl = tk.Label(
            header_frame,
            text=f"▶ {self.window_title}",
            bg=HEADER_BG,
            fg="#58a6ff",
            font=("Consolas", 10, "bold"),
        )
        title_lbl.pack(side=tk.LEFT)

        # Status indicator
        self._status_var = tk.StringVar(value=self.status_info)
        status_lbl = tk.Label(
            header_frame,
            textvariable=self._status_var,
            bg=HEADER_BG,
            fg="#8b949e",
            font=("Consolas", 9),
        )
        status_lbl.pack(side=tk.LEFT, padx=12)

        # Clear button
        clear_btn = tk.Button(
            header_frame,
            text="Clear",
            command=self.clear,
            bg="#21262d",
            fg="#c9d1d9",
            activebackground="#30363d",
            activeforeground="#ffffff",
            bd=0,
            padx=8,
            pady=2,
            font=("Consolas", 8),
        )
        clear_btn.pack(side=tk.RIGHT, padx=4)

        # Always-on-top toggle
        self._topmost_var = tk.BooleanVar(value=self.always_on_top)
        topmost_chk = tk.Checkbutton(
            header_frame,
            text="Pin Top",
            variable=self._topmost_var,
            command=self._toggle_topmost,
            bg=HEADER_BG,
            fg="#8b949e",
            selectcolor="#1e1e1e",
            activebackground=HEADER_BG,
            activeforeground="#ffffff",
            font=("Consolas", 8),
        )
        topmost_chk.pack(side=tk.RIGHT, padx=4)

        # Scrolled Text Subtitle Display
        content_frame = tk.Frame(self._root, bg=BACKGROUND_COLOR, padx=6, pady=6)
        content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._text_area = scrolledtext.ScrolledText(
            content_frame,
            wrap=tk.WORD,
            bg=CONTAINER_COLOR,
            fg=TEXT_COLOR,
            insertbackground="#ffffff",
            selectbackground="#264f78",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            padx=10,
            pady=8,
            font=("Consolas", FONT_SIZE_TRANSLATED),
        )
        self._text_area.pack(fill=tk.BOTH, expand=True)

        # Configure default text formatting tags
        self._text_area.tag_configure("timestamp", foreground="#6e7681", font=("Consolas", FONT_SIZE_TIMESTAMP))
        self._text_area.tag_configure(
            "original", foreground=ORIGINAL_TEXT_COLOR, font=("Consolas", FONT_SIZE_ORIGINAL, "italic")
        )
        self._text_area.tag_configure(
            "translated", foreground=TRANSLATED_TEXT_COLOR, font=("Consolas", FONT_SIZE_TRANSLATED, "bold")
        )
        self._text_area.tag_configure("divider", foreground="#30363d", font=("Consolas", 8))

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Schedule queue polling loop
        self._root.after(50, self._process_queue)
        self._root.mainloop()

    def _toggle_topmost(self) -> None:
        """Toggle window always-on-top state."""
        if self._root and self._topmost_var:
            state = self._topmost_var.get()
            self._root.wm_attributes("-topmost", state)

    def _on_close(self) -> None:
        """Handle window close event."""
        self._is_closed = True
        if self._root:
            self._root.destroy()

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
            self._root.after(50, self._process_queue)

    def _insert_subtitle(
        self,
        speaker: Optional[int | str],
        orig: str,
        trans: str,
        timestamp: datetime,
    ) -> None:
        """Format and insert subtitle entry into Tkinter text widget."""
        if not self._text_area:
            return

        spk_str = f"Speaker {speaker}" if isinstance(speaker, int) else str(speaker or "Speaker")
        time_str = timestamp.strftime("[%H:%M:%S] ")

        # Dynamic tag for speaker color
        spk_color = get_speaker_color(speaker)
        spk_tag = f"spk_{self._speaker_tag_counter}"
        self._speaker_tag_counter += 1
        self._text_area.tag_configure(
            spk_tag,
            foreground=spk_color,
            font=("Consolas", FONT_SIZE_SPEAKER, "bold"),
        )

        # Insert timestamp & speaker header
        self._text_area.insert("end", time_str, "timestamp")
        self._text_area.insert("end", f"[{spk_str}]\n", spk_tag)

        # Insert original spoken text (dimmed)
        if orig:
            self._text_area.insert("end", f"  {orig}\n", "original")

        # Insert translated text (prominent)
        if trans:
            self._text_area.insert("end", f"▶ {trans}\n", "translated")

        # Divider line
        self._text_area.insert("end", "─" * 60 + "\n\n", "divider")

        # Auto-scroll to end
        self._text_area.see("end")

    def clear(self) -> None:
        """Clear subtitle display."""
        if self._text_area:
            self._text_area.delete("1.0", "end")

    def _run_fallback_loop(self) -> None:
        """Headless console fallback loop when Tkinter/GUI display is unavailable."""
        try:
            from rich.console import Console

            console = Console()
        except ImportError:
            console = None

        logger.info("Running terminal window in headless console mode.")
        while not self._is_closed:
            try:
                speaker, orig, trans, timestamp = self._queue.get(timeout=0.5)
                time_str = timestamp.strftime("[%H:%M:%S]")
                spk_str = f"Speaker {speaker}" if isinstance(speaker, int) else str(speaker or "Speaker")
                color = get_speaker_color(speaker)

                if console:
                    console.print(f"[dim]{time_str}[/dim] [bold {color}][{spk_str}][/bold {color}]")
                    if orig:
                        console.print(f"  [dim italic]{orig}[/dim italic]")
                    if trans:
                        console.print(f"  [bold white]▶ {trans}[/bold white]")
                    console.print("[dim]──────────────────────────────────────────────[/dim]")
                else:
                    print(f"{time_str} [{spk_str}]")
                    if orig:
                        print(f"  {orig}")
                    if trans:
                        print(f"  ▶ {trans}")
                    print("-" * 50)
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                break
