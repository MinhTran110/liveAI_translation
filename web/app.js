/**
 * MemoAI Web Frontend Application (Linux Edition)
 */

let currentNoteId = null;
let uploadedFilePath = null;

// Determine API Base URL (supports file:// opening and custom port/origin)
const API_BASE = (window.location.protocol === "file:" || !window.location.host)
  ? "http://127.0.0.1:8000"
  : "";

function formatError(err) {
  const msg = err ? (err.message || String(err)) : "Lỗi không xác định";
  if (msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("Load failed")) {
    return "Không thể kết nối đến máy chủ MemoAI (Failed to fetch). Hãy chắc chắn bạn đã chạy lệnh 'python3 main.py' trong terminal và server đang chạy tại http://127.0.0.1:8000";
  }
  return msg;
}

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initDropzone();
  initActionButtons();
  loadNotesList();
});

// 1. Tab Switching
function initTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));

      tab.classList.add("active");
      const targetId = tab.dataset.tab;
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add("active");
    });
  });
}

// 2. File Upload Dropzone
function initDropzone() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const dropzoneText = document.getElementById("dropzoneText");

  if (!dropzone || !fileInput) return;

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.style.borderColor = "var(--accent-blue)";
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.style.borderColor = "var(--border-color)";
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.style.borderColor = "var(--border-color)";
    if (e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFileUpload(e.target.files[0]);
    }
  });
}

async function handleFileUpload(file) {
  const dropzoneText = document.getElementById("dropzoneText");
  dropzoneText.innerHTML = `Đang tải lên: <b>${file.name}</b> (${(file.size / (1024 * 1024)).toFixed(1)} MB)...`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`${API_BASE}/api/upload`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) throw new Error(`Upload failed (${res.status})`);
    const data = await res.json();
    uploadedFilePath = data.file_info.audio_path;
    dropzoneText.innerHTML = `✓ Đã sẵn sàng: <b>${file.name}</b><div class="subtext">Thời lượng ước tính: ${data.file_info.duration}s</div>`;
  } catch (err) {
    dropzoneText.innerHTML = `<span style="color: var(--accent-red)">Lỗi tải lên: ${formatError(err)}</span>`;
  }
}

// 3. Action Buttons & Processing
function initActionButtons() {
  const btnProcess = document.getElementById("btnProcess");
  const btnNewNote = document.getElementById("btnNewNote");
  const btnExportSrt = document.getElementById("btnExportSrt");
  const btnExportVtt = document.getElementById("btnExportVtt");
  const btnExportMd = document.getElementById("btnExportMd");
  const btnDeleteNote = document.getElementById("btnDeleteNote");

  btnProcess.addEventListener("click", runProcessingPipeline);

  btnNewNote.addEventListener("click", () => {
    document.getElementById("noteViewer").classList.add("hidden");
    document.getElementById("inputSection").classList.remove("hidden");
    document.querySelectorAll(".note-item").forEach((n) => n.classList.remove("active"));
    currentNoteId = null;
  });

  btnExportSrt.addEventListener("click", () => exportNote("srt"));
  btnExportVtt.addEventListener("click", () => exportNote("vtt"));
  btnExportMd.addEventListener("click", () => exportNote("markdown"));

  btnDeleteNote.addEventListener("click", async () => {
    if (!currentNoteId) return;
    if (!confirm("Bạn có chắc chắn muốn xóa ghi chú này không?")) return;

    try {
      const res = await fetch(`${API_BASE}/api/notes/${currentNoteId}`, { method: "DELETE" });
      if (res.ok) {
        currentNoteId = null;
        document.getElementById("noteViewer").classList.add("hidden");
        document.getElementById("inputSection").classList.remove("hidden");
        loadNotesList();
      }
    } catch (err) {
      alert("Lỗi xóa ghi chú: " + formatError(err));
    }
  });
}

async function runProcessingPipeline() {
  const activeTab = document.querySelector(".tab-btn.active").dataset.tab;
  const sourceLang = document.getElementById("sourceLang").value;
  const targetLang = document.getElementById("targetLang").value;
  const engine = document.getElementById("asrEngine").value;

  const payload = {
    source_lang: sourceLang,
    target_lang: targetLang,
    engine: engine,
  };

  if (activeTab === "youtubeTab") {
    const url = document.getElementById("ytUrl").value.trim();
    if (!url) {
      alert("Vui lòng nhập link YouTube!");
      return;
    }
    payload.source_type = "youtube";
    payload.url = url;
  } else {
    if (!uploadedFilePath) {
      alert("Vui lòng chọn hoặc tải lên file trước!");
      return;
    }
    payload.source_type = "file";
    payload.file_path = uploadedFilePath;
  }

  const progressBox = document.getElementById("progressBox");
  const progressText = document.getElementById("progressText");
  const btnProcess = document.getElementById("btnProcess");

  progressBox.classList.remove("hidden");
  btnProcess.disabled = true;
  if (payload.source_type === "youtube" && engine === "youtube_sub") {
    progressText.textContent = "⚡ Đang trích xuất phụ đề gốc / tự động từ YouTube & dịch thuật...";
  } else {
    progressText.textContent = "🎙️ Đang nhận diện giọng nói (ASR) & dịch thuật...";
  }

  try {
    const res = await fetch(`${API_BASE}/api/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Server error (${res.status})`);
    }

    const note = await res.json();
    progressBox.classList.add("hidden");
    btnProcess.disabled = false;

    // Load and select created note
    await loadNotesList();
    renderNoteDetail(note);
  } catch (err) {
    progressBox.classList.remove("hidden");
    btnProcess.disabled = false;
    progressText.innerHTML = `<span style="color: var(--accent-red)">Lỗi xử lý: ${formatError(err)}</span>`;
  }
}

// 4. Notes List Management
async function loadNotesList() {
  const container = document.getElementById("notesList");
  try {
    const res = await fetch(`${API_BASE}/api/notes`);
    if (!res.ok) throw new Error("Could not load notes");
    const notes = await res.json();

    if (notes.length === 0) {
      container.innerHTML = `<div class="empty-state">Chưa có ghi chú nào.<br>Hãy dán link YouTube hoặc tải file lên.</div>`;
      return;
    }

    container.innerHTML = "";
    notes.forEach((note) => {
      const item = document.createElement("div");
      item.className = `note-item ${note.id === currentNoteId ? "active" : ""}`;
      item.dataset.id = note.id;

      const durMin = Math.floor(note.duration / 60);
      const durSec = Math.floor(note.duration % 60);
      const durStr = `${durMin}:${durSec < 10 ? "0" : ""}${durSec}`;

      item.innerHTML = `
        <div class="note-item-title" title="${escapeHtml(note.title)}">${escapeHtml(note.title)}</div>
        <div class="note-item-meta">
          <span>${note.source_type.toUpperCase()} • ${durStr}</span>
          <span>${note.segment_count || 0} câu</span>
        </div>
      `;

      item.addEventListener("click", () => fetchNoteDetail(note.id));
      container.appendChild(item);
    });
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color: var(--accent-red)">Lỗi nạp thư viện: ${formatError(err)}</div>`;
  }
}

async function fetchNoteDetail(noteId) {
  try {
    const res = await fetch(`${API_BASE}/api/notes/${noteId}`);
    if (!res.ok) throw new Error("Note not found");
    const note = await res.json();
    renderNoteDetail(note);
  } catch (err) {
    alert("Không tải được ghi chú: " + formatError(err));
  }
}

// 5. Render Note & Segments
function renderNoteDetail(note) {
  currentNoteId = note.id;

  // Update active sidebar note
  document.querySelectorAll(".note-item").forEach((item) => {
    item.classList.toggle("active", parseInt(item.dataset.id) === note.id);
  });

  document.getElementById("inputSection").classList.add("hidden");
  const noteViewer = document.getElementById("noteViewer");
  noteViewer.classList.remove("hidden");

  document.getElementById("viewNoteTitle").textContent = note.title;

  const mins = Math.floor(note.duration / 60);
  const secs = Math.floor(note.duration % 60);
  const durStr = `${mins}:${secs < 10 ? "0" : ""}${secs}`;
  document.getElementById("viewNoteMeta").textContent =
    `Thời lượng: ${durStr} | Nguồn: ${note.source_lang.toUpperCase()} → ${note.target_lang.toUpperCase()} | ${note.created_at}`;

  const container = document.getElementById("segmentsContainer");
  container.innerHTML = "";

  (note.segments || []).forEach((seg) => {
    const card = document.createElement("div");
    card.className = "segment-card";

    const spkClass = `speaker-${seg.speaker % 4}`;
    const startStr = formatTime(seg.start);
    const endStr = formatTime(seg.end);

    card.innerHTML = `
      <div class="segment-header">
        <span class="speaker-badge ${spkClass}">Người nói ${seg.speaker}</span>
        <span class="segment-time">${startStr} - ${endStr}</span>
      </div>
      <div class="segment-original">${escapeHtml(seg.text)}</div>
      <textarea class="segment-translation-edit" data-id="${seg.id}" placeholder="Nhập bản dịch sửa tay...">${escapeHtml(seg.translation || "")}</textarea>
      <span class="save-indicator" id="save-${seg.id}">✓ Đã lưu</span>
    `;

    const textarea = card.querySelector(".segment-translation-edit");
    let saveTimeout = null;

    textarea.addEventListener("input", (e) => {
      clearTimeout(saveTimeout);
      saveTimeout = setTimeout(() => {
        saveSegmentTranslation(seg.id, e.target.value);
      }, 500);
    });

    container.appendChild(card);
  });
}

// 6. Save manual translation edit
async function saveSegmentTranslation(segmentId, text) {
  try {
    const res = await fetch(`${API_BASE}/api/segments/${segmentId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ translation: text }),
    });

    if (res.ok) {
      const indicator = document.getElementById(`save-${segmentId}`);
      if (indicator) {
        indicator.classList.add("visible");
        setTimeout(() => indicator.classList.remove("visible"), 1500);
      }
    }
  } catch (err) {
    console.error("Autosave error:", formatError(err));
  }
}

// 7. Export file
function exportNote(format) {
  if (!currentNoteId) return;
  window.location.href = `${API_BASE}/api/export/${currentNoteId}?format=${format}`;
}

// Utilities
function formatTime(seconds) {
  const s = Math.floor(seconds || 0);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec < 10 ? "0" : ""}${sec}`;
}

function escapeHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
