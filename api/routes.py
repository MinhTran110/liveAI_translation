"""FastAPI API routes for video ingestion, transcription, translation, and export."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from storage.db import (
    create_note,
    add_segments,
    get_notes,
    get_note,
    update_segment_translation,
    delete_note,
)
from ingest.youtube_downloader import download_youtube_audio
from ingest.file_handler import process_uploaded_file, UPLOADS_DIR
from transcribe.deepgram_client import DeepgramPreRecordedTranscriber
from transcribe.local_whisper import LocalWhisperFileTranscriber
from translate.llm_translator import LLMTranslator
from export.srt_exporter import export_srt
from export.vtt_exporter import export_vtt
from export.markdown_exporter import export_markdown

logger = logging.getLogger(__name__)


def create_router():
    """Create and return FastAPI APIRouter."""
    from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
    from pydantic import BaseModel

    router = APIRouter()

    class ProcessRequest(BaseModel):
        source_type: str = "youtube"  # 'youtube' or 'file'
        url: Optional[str] = None
        file_path: Optional[str] = None
        source_lang: str = "auto"
        target_lang: str = "vi"
        engine: str = "deepgram"  # 'deepgram' or 'local'

    class SegmentUpdateRequest(BaseModel):
        translation: str

    @router.post("/upload")
    async def upload_file(file: UploadFile = File(...)):
        """Upload a local video or audio file to server storage."""
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        dest_path = UPLOADS_DIR / file.filename
        try:
            content = await file.read()
            with open(dest_path, "wb") as f:
                f.write(content)

            file_info = process_uploaded_file(dest_path, original_filename=file.filename)
            return {"status": "success", "file_info": file_info}
        except Exception as e:
            logger.error("File upload failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/process")
    async def process_media(req: ProcessRequest):
        """Execute full pipeline: Ingest -> Transcribe -> Translate -> Store in SQLite."""
        try:
            raw_segments = None
            title = "Untitled Note"
            duration = 0.0
            audio_path = None

            # 1. Ingest
            if req.source_type == "youtube":
                if not req.url:
                    raise HTTPException(status_code=400, detail="Missing YouTube URL.")
                from ingest.youtube_downloader import clean_youtube_url
                req.url = clean_youtube_url(req.url)

                # If engine is 'youtube_sub' or 'auto', attempt extracting YouTube native subtitles first
                if req.engine in ("youtube_sub", "auto", ""):
                    from transcribe.youtube_subtitles import fetch_youtube_subtitles
                    subs, meta = fetch_youtube_subtitles(req.url, preferred_lang=req.source_lang)
                    if subs:
                        raw_segments = subs
                        title = meta.get("title", f"YouTube Video ({meta.get('video_id')})")
                        duration = meta.get("duration", 0.0)
                        logger.info("Using native YouTube subtitles (%d segments).", len(subs))

                # If no subtitles found or user explicitly requested ASR engine, download audio
                if not raw_segments:
                    ingest_info = download_youtube_audio(req.url)
                    audio_path = ingest_info["audio_path"]
                    title = ingest_info.get("title", title)
                    duration = ingest_info.get("duration", duration)
            else:
                if not req.file_path:
                    raise HTTPException(status_code=400, detail="Missing uploaded file path.")
                ingest_info = process_uploaded_file(req.file_path)
                audio_path = ingest_info["audio_path"]
                title = ingest_info.get("title", "Untitled Note")
                duration = ingest_info.get("duration", 0.0)

            # 2. Transcribe via ASR if not extracted from YouTube subtitles
            if not raw_segments:
                if req.engine == "deepgram" and os.getenv("DEEPGRAM_API_KEY", "").strip():
                    transcriber = DeepgramPreRecordedTranscriber()
                else:
                    transcriber = LocalWhisperFileTranscriber()

                raw_segments = transcriber.transcribe_file(
                    audio_path,
                    source_lang=req.source_lang,
                )

            # 3. Contextual Translation
            translator = LLMTranslator(
                target_language=req.target_lang,
                source_language=req.source_lang,
            )
            translated_segments = translator.translate_segments(
                raw_segments,
                target_lang=req.target_lang,
                source_lang=req.source_lang,
            )

            # 4. Save to SQLite
            note_id = create_note(
                title=title,
                source_type=req.source_type,
                source_url=req.url,
                file_path=audio_path,
                duration=duration,
                source_lang=req.source_lang,
                target_lang=req.target_lang,
                status="completed",
            )

            add_segments(note_id, translated_segments)
            saved_note = get_note(note_id)
            return saved_note

        except HTTPException:
            raise
        except Exception as e:
            logger.error("Media processing pipeline error: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Processing failed: {e}")

    @router.get("/notes")
    async def list_notes():
        """Retrieve list of all processed notes."""
        return get_notes()

    @router.get("/notes/{note_id}")
    async def retrieve_note(note_id: int):
        """Retrieve a single note with its segments."""
        note = get_note(note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        return note

    @router.put("/segments/{segment_id}")
    async def update_segment(segment_id: int, payload: SegmentUpdateRequest):
        """Update translation text for a segment manually."""
        success = update_segment_translation(segment_id, payload.translation)
        if not success:
            raise HTTPException(status_code=404, detail="Segment not found")
        return {"status": "success", "segment_id": segment_id, "translation": payload.translation}

    @router.delete("/notes/{note_id}")
    async def remove_note(note_id: int):
        """Delete note and all associated segments."""
        success = delete_note(note_id)
        if not success:
            raise HTTPException(status_code=404, detail="Note not found")
        return {"status": "success", "deleted_id": note_id}

    @router.get("/export/{note_id}")
    async def export_note(note_id: int, format: str = Query("srt", pattern="^(srt|vtt|markdown|md)$")):
        """Export note to SRT, VTT, or Markdown."""
        note = get_note(note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")

        title = "".join(c for c in note.get("title", "note") if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        fmt = format.lower()

        if fmt == "srt":
            content = export_srt(note["segments"])
            media_type = "text/plain; charset=utf-8"
            filename = f"{title}.srt"
        elif fmt == "vtt":
            content = export_vtt(note["segments"])
            media_type = "text/vtt; charset=utf-8"
            filename = f"{title}.vtt"
        else:
            content = export_markdown(note)
            media_type = "text/markdown; charset=utf-8"
            filename = f"{title}.md"

        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
