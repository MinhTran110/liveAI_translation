# MemoAI — Video Translate & Notes (Linux Edition)

MemoAI là ứng dụng dịch video & ghi chú thông minh chuyên biệt cho môi trường Linux. Ứng dụng hỗ trợ trích xuất âm thanh từ YouTube và file local, nhận diện giọng nói (ASR) phân tách người nói (Diarization), dịch ngữ cảnh qua AI sang tiếng Việt, cho phép chỉnh sửa trực tiếp từng câu dịch trên giao diện Web hiện đại và xuất file phụ đề (`.srt`, `.vtt`) hoặc ghi chú học tập (`.md`).

---

## ✨ Tính năng nổi bật

- 📺 **Đa dạng nguồn đầu vào**:
  - Dán trực tiếp liên kết YouTube (tự động nhận diện và trích xuất âm thanh qua `yt-dlp`).
  - Tải lên file video/audio từ máy tính (`.mp4`, `.mkv`, `.webm`, `.mp3`, `.wav`, `.m4a`, `.flac`, `.opus`).
  - **Không phụ thuộc vào `ffmpeg` hệ thống**: Tự động nhận diện và xử lý luồng âm thanh native (`.webm`, `.m4a`) chất lượng cao mà không bị lỗi thiếu công cụ.
  - Cơ chế **Cache video ID thông minh**: Tự động tái sử dụng âm thanh đã tải để tiết kiệm băng thông và thời gian xử lý.

- 🎙️ **Công nghệ nhận diện giọng nói kép (Dual ASR Engines)**:
  - **Local Faster-Whisper (Khuyến nghị, Ngoại tuyến 100%)**: Chạy trực tiếp trên CPU/GPU Linux, hoàn toàn miễn phí, nhận diện toàn bộ nội dung từ giây đầu tiên đến phút cuối cùng (kể cả video dài 18 phút hay nhiều giờ).
  - **Cloud Deepgram (Nova-2)**: Phân tách người nói (Speaker Diarization) và ngắt câu tự nhiên theo lượt phát biểu (Utterances).
  - **Tự động chuyển tiếp thông minh**: Nếu người dùng chưa cấu hình `DEEPGRAM_API_KEY`, hệ thống tự động kích hoạt Faster-Whisper cục bộ để đảm bảo nhận diện 100% nội dung thực tế của video.

- 🌐 **Dịch thuật ngữ cảnh thông minh**:
  - Dịch hội thoại mượt mà sang tiếng Việt, ghi nhớ ngữ cảnh lượt nói trước để dịch đại từ nhân xưng tự nhiên.
  - Hỗ trợ LLM cao cấp (Claude 3.5 Haiku, GPT-4o-mini) hoặc dịch miễn phí qua Google Translate API (không cần API key).

- ✍️ **Giao diện Web hiện đại (Font Arial, Dark Mode)**:
  - Bố cục trực quan, font chữ **Arial** dễ đọc, các nút thao tác rõ ràng.
  - Mỗi phân đoạn đều có ô textarea cho phép **sửa tay trực tiếp câu dịch**.
  - **Autosave tự động**: Mọi chỉnh sửa được tự động lưu ngay vào cơ sở dữ liệu SQLite sau 500ms ngừng gõ.

- 📤 **Xuất dữ liệu một chạm**:
  - **Phụ đề `.srt`**: Chuẩn timestamp mili-giây, định dạng song ngữ (tiếng Việt + tiếng gốc) hoặc đơn ngữ.
  - **Phụ đề `.vtt`**: Chuẩn WebVTT cho các trình phát HTML5.
  - **Ghi chú `.md`**: Tài liệu Markdown phân theo từng Người nói (Speaker) kèm mốc thời gian học tập.

---

## 📁 Cấu trúc thư mục

```
video-translate-notes/
│
├── .env                          # Biến môi trường (DEEPGRAM_API_KEY, ANTHROPIC_API_KEY,...)
├── .gitignore                    # Bỏ qua DB, media tải về, môi trường ảo venv
├── requirements.txt              # Danh sách thư viện Python
├── config.py                     # Quản lý cấu hình & biến môi trường
├── main.py                       # Server FastAPI / Web UI (kèm zero-dependency fallback)
│
├── ingest/                       # Tiếp nhận dữ liệu đầu vào
│   ├── __init__.py
│   ├── youtube_downloader.py     # Tải audio YouTube không cần ffmpeg + cache ID
│   └── file_handler.py           # Xử lý file video/audio local tải lên
│
├── transcribe/                   # ASR + Diarization
│   ├── __init__.py
│   ├── base.py                   # Dataclass TranscriptSegment
│   ├── deepgram_client.py        # Deepgram Nova-2 (tự fallback sang Local Whisper nếu thiếu key)
│   ├── local_whisper.py          # Faster-Whisper chạy offline trên CPU/GPU
│   └── model_selector.py         # Quét phần cứng Linux (/proc/cpuinfo, /proc/meminfo)
│
├── translate/
│   ├── __init__.py
│   └── llm_translator.py         # Dịch ngữ cảnh AI & fallback miễn phí
│
├── export/                       # Xuất dữ liệu
│   ├── __init__.py
│   ├── srt_exporter.py           # Xuất phụ đề .srt chuẩn timestamp
│   ├── vtt_exporter.py           # Xuất phụ đề .vtt (WebVTT)
│   └── markdown_exporter.py      # Xuất ghi chú .md phân loại theo Speaker
│
├── storage/                      # Cơ sở dữ liệu SQLite
│   ├── __init__.py
│   ├── db.py                     # CRUD Note & Segments, cập nhật bản dịch
│   └── models.py                 # Dataclass Note, Segment
│
├── api/                          # FastAPI endpoints
│   ├── __init__.py
│   └── routes.py                 # /api/upload, /api/process, /api/notes, /api/export
│
├── web/                          # Giao diện người dùng Web UI
│   ├── index.html                # Tab YouTube/Upload, thư viện Note, bảng segment
│   ├── style.css                 # Dark theme hiện đại, font Arial dễ nhìn
│   └── app.js                    # Fetch API, render bảng segment, chỉnh sửa câu dịch & autosave
│
└── tests/
    └── test_translate_segments.py # Unit tests kiểm tra toàn bộ luồng xử lý
```

---

## 🚀 Hướng dẫn cài đặt & Chạy trên Linux

> ⚠️ **Lưu ý quan trọng**: Không sử dụng môi trường `base` của Anaconda để tránh lỗi xung đột binary C-extension. Hãy tắt Conda trước khi chạy.

### 1. Tắt Anaconda (nếu đang bật)
```bash
conda deactivate
```

### 2. Thiết lập môi trường ảo Python 3 (Khuyến nghị)
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Cấu hình file `.env`
Sao chép `.env.example` thành `.env`:
```bash
cp .env.example .env
```
Mở `.env` và nhập API key (nếu muốn dùng Deepgram Cloud hoặc Claude/OpenAI):
```env
DEEPGRAM_API_KEY=your_deepgram_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```
*(Nếu không có bất kỳ API Key nào, hệ thống vẫn hoạt động 100% bằng Faster-Whisper cục bộ và dịch thuật Google Translate tự động).*

### 4. Khởi động ứng dụng
```bash
python3 main.py
```
> **Mẹo tiện lợi**: File `main.py` có cơ chế tự động chuyển tiếp vào `venv/bin/python3`. Bạn chỉ cần chạy `python3 main.py`, server sẽ tự khởi động mà không cần gõ lệnh kích hoạt môi trường thủ công!

Mở trình duyệt tại:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)** (hoặc `http://localhost:8000`)

Nếu chỉ muốn kiểm tra thông số phần cứng máy Linux:
```bash
python3 main.py --scan-only
```

---

## 🧪 Chạy Kiểm thử (Unit Tests)

```bash
python3 -m pytest tests/test_translate_segments.py -v
```

Kiểm tra tự động:
- Khởi tạo SQLite DB & CRUD Note/Segment
- Xuất phụ đề SRT và WebVTT
- Xuất ghi chú Markdown có phân chia Speaker
- Phân tích cú pháp Diarization từ Deepgram API
- Dịch ngữ cảnh hội thoại đa lượt