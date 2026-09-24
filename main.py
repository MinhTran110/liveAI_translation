"""Main entry point for MemoAI Video Translate & Notes.
Starts the FastAPI server and serves the local web application.
"""

import argparse
import logging
import os
from pathlib import Path
import sys
from typing import Any, Optional

from config import load_config
from storage.db import init_db
from transcribe.model_selector import scan_system, suggest_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("memoai")

# Ensure required runtime directories exist
BASE_DIR = Path(__file__).resolve().parent

# Auto-switch to workspace virtual environment if available and not already in it
_venv_python = BASE_DIR / "venv" / "bin" / "python3"
if _venv_python.exists() and sys.executable != str(_venv_python.resolve()) and "MEMOAI_NO_REEXEC" not in os.environ:
    os.environ["MEMOAI_NO_REEXEC"] = "1"
    try:
        os.execv(str(_venv_python), [str(_venv_python)] + sys.argv)
    except Exception:
        pass

for sub in ["data", "uploads", "downloads", "web"]:
    (BASE_DIR / sub).mkdir(parents=True, exist_ok=True)

# Initialize SQLite database schema
init_db()


def create_fastapi_app():
    """Instantiate and configure the FastAPI application."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from api.routes import create_router

    app = FastAPI(
        title="MemoAI — Video Translate & Notes",
        description="Linux-optimized video/audio transcription, diarization, and notes translator.",
        version="2.0.0",
    )

    # Enable CORS for all origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static assets
    web_dir = BASE_DIR / "web"
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

    # Mount API routes
    app.include_router(create_router(), prefix="/api")

    # Serve index.html at root
    @app.get("/")
    async def serve_index():
        return FileResponse(str(web_dir / "index.html"))

    return app


def run_builtin_fallback_server(host: str, port: int):
    """Fallback standard HTTP server if FastAPI/Uvicorn is not yet installed."""
    import http.server
    import json
    import urllib.parse
    import email
    from storage.db import get_notes, get_note, delete_note, update_segment_translation
    from export.srt_exporter import export_srt
    from export.vtt_exporter import export_vtt
    from export.markdown_exporter import export_markdown

    class MemoAIHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(BASE_DIR / "web"), **kwargs)

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(200)
            self.end_headers()

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            params = urllib.parse.parse_qs(parsed.query)

            if path in ("", "/"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(BASE_DIR / "web" / "index.html", "rb") as f:
                    self.wfile.write(f.read())
                return

            if path.startswith("/static/"):
                filepath = BASE_DIR / "web" / path.replace("/static/", "")
                if filepath.is_file():
                    self.send_response(200)
                    if filepath.suffix == ".css":
                        self.send_header("Content-Type", "text/css")
                    elif filepath.suffix == ".js":
                        self.send_header("Content-Type", "application/javascript")
                    self.end_headers()
                    with open(filepath, "rb") as f:
                        self.wfile.write(f.read())
                    return

            if path == "/api/notes":
                notes = get_notes()
                self._send_json(notes)
                return

            if path.startswith("/api/notes/"):
                try:
                    nid = int(path.split("/")[-1])
                    note = get_note(nid)
                    if note:
                        self._send_json(note)
                    else:
                        self._send_error_json(404, "Note not found")
                except ValueError:
                    self._send_error_json(400, "Invalid note ID")
                return

            if path.startswith("/api/export/"):
                try:
                    nid = int(path.split("/")[-1])
                    note = get_note(nid)
                    if not note:
                        self._send_error_json(404, "Note not found")
                        return
                    fmt = params.get("format", ["srt"])[0].lower()
                    title = "".join(c for c in note.get("title", "note") if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")

                    if fmt == "vtt":
                        content = export_vtt(note["segments"]).encode("utf-8")
                        mtype = "text/vtt; charset=utf-8"
                        fname = f"{title}.vtt"
                    elif fmt in ("markdown", "md"):
                        content = export_markdown(note).encode("utf-8")
                        mtype = "text/markdown; charset=utf-8"
                        fname = f"{title}.md"
                    else:
                        content = export_srt(note["segments"]).encode("utf-8")
                        mtype = "text/plain; charset=utf-8"
                        fname = f"{title}.srt"

                    self.send_response(200)
                    self.send_header("Content-Type", mtype)
                    self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                    self.end_headers()
                    self.wfile.write(content)
                except Exception as e:
                    self._send_error_json(500, str(e))
                return

            super().do_GET()

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path == "/api/upload":
                try:
                    content_type = self.headers.get("Content-Type", "")
                    length = int(self.headers.get("Content-Length", 0))
                    body_bytes = self.rfile.read(length)

                    from ingest.file_handler import process_uploaded_file, UPLOADS_DIR
                    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

                    filename = "uploaded_file.mp3"
                    file_bytes = body_bytes

                    if "boundary=" in content_type:
                        msg = email.message_from_bytes(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8") + body_bytes)
                        for part in msg.walk():
                            fn = part.get_filename()
                            if fn:
                                filename = fn
                                payload = part.get_payload(decode=True)
                                if payload:
                                    file_bytes = payload
                                break

                    dest = UPLOADS_DIR / filename
                    with open(dest, "wb") as f:
                        f.write(file_bytes)

                    info = process_uploaded_file(dest, original_filename=filename)
                    self._send_json({"status": "success", "file_info": info})
                    return
                except Exception as e:
                    self._send_error_json(500, str(e))
                    return

            if path == "/api/process":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length).decode("utf-8"))

                    from ingest.youtube_downloader import download_youtube_audio
                    from ingest.file_handler import process_uploaded_file
                    from storage.db import create_note, add_segments
                    from transcribe.youtube_subtitles import fetch_youtube_subtitles
                    from transcribe.local_whisper import LocalWhisperFileTranscriber
                    from transcribe.deepgram_client import DeepgramPreRecordedTranscriber
                    from translate.llm_translator import LLMTranslator

                    source_type = body.get("source_type", "youtube")
                    url = body.get("url")
                    file_path = body.get("file_path")
                    source_lang = body.get("source_lang", "auto")
                    target_lang = body.get("target_lang", "vi")
                    engine = body.get("engine", "youtube_sub")

                    raw_segments = None
                    title = "Untitled Note"
                    duration = 0.0
                    audio_path = None

                    if source_type == "youtube":
                        if not url:
                            self._send_error_json(400, "Missing YouTube URL.")
                            return

                        if engine in ("youtube_sub", "auto", ""):
                            subs, meta = fetch_youtube_subtitles(url, preferred_lang=source_lang)
                            if subs:
                                raw_segments = subs
                                title = meta.get("title", f"YouTube Video ({meta.get('video_id')})")
                                duration = meta.get("duration", 0.0)
                                logger.info("Using native YouTube subtitles (%d segments).", len(subs))

                        if not raw_segments:
                            ingest_info = download_youtube_audio(url)
                            audio_path = ingest_info["audio_path"]
                            title = ingest_info.get("title", title)
                            duration = ingest_info.get("duration", duration)
                    else:
                        if not file_path:
                            self._send_error_json(400, "Missing file path.")
                            return
                        ingest_info = process_uploaded_file(file_path)
                        audio_path = ingest_info["audio_path"]
                        title = ingest_info.get("title", "Untitled Note")
                        duration = ingest_info.get("duration", 0.0)

                    if not raw_segments:
                        if engine == "deepgram" and os.getenv("DEEPGRAM_API_KEY", "").strip():
                            transcriber = DeepgramPreRecordedTranscriber()
                        else:
                            transcriber = LocalWhisperFileTranscriber()
                        raw_segments = transcriber.transcribe_file(audio_path, source_lang=source_lang)

                    translator = LLMTranslator(target_language=target_lang, source_language=source_lang)
                    trans_segments = translator.translate_segments(raw_segments, target_lang=target_lang, source_lang=source_lang)

                    nid = create_note(
                        title=title,
                        source_type=source_type,
                        source_url=url,
                        file_path=audio_path,
                        duration=duration,
                        source_lang=source_lang,
                        target_lang=target_lang,
                    )
                    add_segments(nid, trans_segments)
                    self._send_json(get_note(nid))
                    return
                except Exception as e:
                    logger.error("Processing error: %s", e)
                    self._send_error_json(500, str(e))
                    return

            self._send_error_json(404, "Endpoint not found")

        def do_PUT(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.startswith("/api/segments/"):
                try:
                    sid = int(parsed.path.split("/")[-1])
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    trans = body.get("translation", "")
                    update_segment_translation(sid, trans)
                    self._send_json({"status": "success", "id": sid, "translation": trans})
                    return
                except Exception as e:
                    self._send_error_json(500, str(e))
                    return

            self._send_error_json(404, "Endpoint not found")

        def do_DELETE(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.startswith("/api/notes/"):
                try:
                    nid = int(parsed.path.split("/")[-1])
                    delete_note(nid)
                    self._send_json({"status": "success", "id": nid})
                    return
                except Exception as e:
                    self._send_error_json(500, str(e))
                    return
            self._send_error_json(404, "Endpoint not found")

        def _send_json(self, data: Any):
            content = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _send_error_json(self, status: int, msg: str):
            content = json.dumps({"detail": msg}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    logger.info("Serving MemoAI Web UI on: http://%s:%d (built-in server)", host, port)
    server = http.server.ThreadingHTTPServer((host, port), MemoAIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped.")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="MemoAI Video Translate & Notes Server")
    parser.add_argument("--host", default=None, help="Server host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="Server port (default: 8000)")
    parser.add_argument("--scan-only", action="store_true", help="Print system hardware specs and exit.")
    args = parser.parse_args()

    config = load_config()
    host = args.host or config.host
    port = args.port or config.port

    print("\n" + "=" * 65)
    print("      MEMOAI — VIDEO TRANSLATE & NOTES (LINUX EDITION)       ")
    print("=" * 65 + "\n")

    logger.info("Scanning Linux hardware capabilities...")
    specs = scan_system(cache_path=config.models_cache_dir)
    rec = suggest_model(specs)

    logger.info(
        "Hardware: RAM=%.1fGB | CPU=%s (%d Cores) | Suggested ASR=%s",
        specs.ram_total_gb,
        specs.cpu_model,
        specs.cpu_physical_cores,
        rec.recommended_provider.upper(),
    )

    if args.scan_only:
        print("\nScan complete. Exiting (--scan-only specified).")
        return

    # Check for FastAPI & Uvicorn
    try:
        import uvicorn
        from fastapi import FastAPI

        logger.info("FastAPI & Uvicorn detected. Starting ASGI web server...")
        app = create_fastapi_app()
        display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        logger.info("Opening MemoAI at: http://%s:%d", display_host, port)
        uvicorn.run(app, host=host, port=port, log_level="info")
    except ImportError:
        logger.warning(
            "FastAPI or Uvicorn not installed in current environment. "
            "Running with built-in zero-dependency HTTP server."
        )
        display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        logger.info("Opening MemoAI at: http://%s:%d", display_host, port)
        run_builtin_fallback_server(host, port)


if __name__ == "__main__":
    main()
