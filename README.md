# 🎬 All-in-One Media Downloader

<p align="center">
  <strong>A high-performance, self-hosted universal media extractor and downloader web application.</strong><br>
  Extract and archive videos, audio, carousels, and stories from YouTube, Instagram, Twitter/X, TikTok, and more.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React_18-20232A?style=for-the-badge&logo=react&logoColor=61DAFB" alt="React 18" />
  <img src="https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white" alt="Vite" />
  <img src="https://img.shields.io/badge/Bun-000000?style=for-the-badge&logo=bun&logoColor=white" alt="Bun" />
  <img src="https://img.shields.io/badge/uv-Astral-47209E?style=for-the-badge&logo=python&logoColor=white" alt="uv" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/TailwindCSS-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white" alt="Tailwind CSS" />
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="MIT License" />
</p>

---

## 📑 Table of Contents

1. [Features & Highlights](#-features--highlights)
2. [Architecture & Workflow](#-architecture--workflow)
3. [Supported Platforms & Capabilities](#-supported-platforms--capabilities)
4. [Quick Start (Docker)](#-quick-start-docker)
   - [Using Docker Compose (Recommended)](#using-docker-compose-recommended)
   - [Using Docker CLI](#using-docker-cli)
5. [Local Development](#-local-development)
   - [Prerequisites](#prerequisites)
   - [Single-Command Dev Launcher](#single-command-dev-launcher)
6. [Authentication & Cookies Guide](#-authentication--cookies-guide)
   - [Exporting Netscape Cookies](#1-exporting-netscape-cookies)
   - [Uploading via Web UI](#2-uploading-via-web-ui)
   - [Manual File Placement](#3-manual-file-placement)
7. [Configuration & Environment Variables](#-configuration--environment-variables)
8. [API Reference & Examples](#-api-reference--examples)
   - [Interactive Documentation](#interactive-documentation)
   - [Key Endpoints](#key-endpoints)
   - [cURL Walkthrough](#curl-walkthrough)
9. [Automated Storage Cleanup](#-automated-storage-cleanup)
10. [Testing & Quality](#-testing--quality)
11. [Legal & Fair Use Disclaimer](#-legal--fair-use-disclaimer)
12. [License](#-license)

---

## ✨ Features & Highlights

- **Two-Step Inspection & Preview**: Inspect URLs before downloading to verify media metadata, preview video/image thumbnails, choose video resolutions, or select audio-only extraction.
- **Smart Engine Routing**: Automatically dispatches URLs to **`yt-dlp`** or **`gallery-dl`** based on the platform and media type, with automatic fallback when an engine encounters GraphQL or stream changes.
- **Story & Carousel Item Selection**: Multi-photo posts, Instagram Stories, and TikTok photo galleries display individual slide selectors. Pick specific items or download all.
- **Automatic ZIP Packaging**: Multi-item albums and stories are packaged on-the-fly into clean `.zip` archives.
- **Real-Time Progress via SSE**: Stream live download percentage, transfer speed (MB/s), ETA, and FFmpeg remuxing status via Server-Sent Events (SSE).
- **Post-Processing with FFmpeg**: Automatic remuxing of split video/audio streams into universal MP4 containers, or lossless extraction of audio into MP3, M4A, or WAV with metadata tags.
- **In-App Cookie & Proxy Management**: Built-in Settings modal lets you upload or paste Netscape cookie files for authenticated platforms (e.g., Instagram Stories, private accounts, Twitter/X rate limits) and configure SOCKS5 proxies without restarting the server.
- **Zero Disk Bloat (Automatic TTL Cleaner)**: Background asynchronous cleaner continuously purges completed and abandoned download directories older than 60 minutes (configurable).
- **Single-Container Deployment**: Self-contained multi-stage Docker build packaging both the Vite React SPA and FastAPI backend into a single image.

---

## 🏗 Architecture & Workflow

The application operates on an asynchronous two-step pipeline coordinating `yt-dlp`, `gallery-dl`, and `ffmpeg`:

```mermaid
flowchart TD
    User([User / Browser])
    
    subgraph Frontend["Frontend SPA (React + Vite + Tailwind)"]
        UI_Input["Step 1: URL Input"]
        UI_Preview["Step 2: Preview, Quality & Item Selection"]
        UI_Progress["Step 3: Real-Time SSE Progress Bar"]
        UI_Settings["Settings Modal (Cookies & Proxy)"]
    end

    subgraph Backend["FastAPI Backend"]
        Router["Smart Classifier & Engine Router"]
        YTDLP["yt-dlp Service"]
        GALLERY["gallery-dl Service"]
        FFMPEG["FFmpeg Remux & Audio Transcoder"]
        ZIP["ZIP Packaging Service"]
        CLEANER["Periodic Background TTL Cleaner"]
        COOKIES["Cookie Manager (/app/cookies)"]
    end

    User -->|"Enters Media URL"| UI_Input
    UI_Input -->|"POST /api/inspect"| Router
    Router -->|"Probe Video/Audio"| YTDLP
    Router -->|"Probe Gallery/Story/Photos"| GALLERY
    YTDLP & GALLERY -->|"Normalized Metadata"| UI_Preview
    
    User -->|"Chooses Format & Hits Download"| UI_Preview
    UI_Preview -->|"POST /api/download"| Backend
    Backend -->|"Task Queued (task_id)"| UI_Progress
    
    UI_Progress -->|"GET /api/progress/{task_id} (SSE)"| Backend
    Backend -->|"Stream Download Progress"| YTDLP & GALLERY
    YTDLP & GALLERY -->|"Raw Streams"| FFMPEG
    FFMPEG -->|"Bundling (if multiple items)"| ZIP
    ZIP -->|"GET /api/files/{task_id}/{file}"| User

    COOKIES -.->|"Auth Injection"| YTDLP & GALLERY
    UI_Settings -->|"Upload Netscape Cookies"| COOKIES
    CLEANER -.->|"Purge expired tasks (>60m)"| Backend
```

---

## 🌐 Supported Platforms & Capabilities

| Platform | Supported Media Types | Primary Engine | Fallback Engine | Authentication / Cookies |
| :--- | :--- | :--- | :--- | :--- |
| **YouTube** | Videos (up to 4K/8K), Shorts, Playlists, Audio | `yt-dlp` | — | Optional (required for age-restricted or member videos) |
| **Instagram** | Stories & Highlights | `gallery-dl` | `yt-dlp` | **Required** (`instagram.txt`) |
| **Instagram** | Carousel Posts (Multi-image/video) | `gallery-dl` | `yt-dlp` | Recommended for private accounts |
| **Instagram** | Single Reels & Standard Posts | `yt-dlp` | `gallery-dl` | Recommended |
| **Twitter / X** | Videos & GIFs | `yt-dlp` | `gallery-dl` | Optional |
| **Twitter / X** | Multi-image posts (Original resolution) | `gallery-dl` | `yt-dlp` | Recommended (bypasses rate-limits) |
| **TikTok** | Watermark-free Videos & Audio | `yt-dlp` | `gallery-dl` | Optional |
| **TikTok** | Photo Slideshows | `gallery-dl` | `yt-dlp` | Optional |
| **Reddit** | Videos with Audio, Images, Galleries | `yt-dlp` | `gallery-dl` | Optional |
| **Generic URLs** | Direct MP4/WebM, Pinterest, Vimeo, etc. | Dynamic | Opposite | Automatic stream detection |

---

## 🚀 Quick Start (Docker)

### Using Docker Compose (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/all-in-one-downloader.git
   cd all-in-one-downloader
   ```

2. Start the container in detached mode:
   ```bash
   docker compose up -d
   ```

3. Open your browser and navigate to:
   ```text
   http://localhost:8000
   ```

*(Volumes for `./cookies` and `./downloads` are mounted automatically to preserve your uploaded session cookies and downloaded files).*

### Using Docker or Podman CLI

You can build and run the multi-stage image directly with Docker or Podman (base images use fully qualified image names to ensure seamless compatibility with Podman/Buildah without requiring search registry configurations):

```bash
# 1. Build the production image (Docker or Podman)
docker build -t all-in-one-downloader .
# or with Podman:
podman build -t all-in-one-downloader .

# 2. Run the container with mounted volumes
# Docker:
docker run -d \
  --name all-in-one-downloader \
  -p 8000:8000 \
  -v $(pwd)/cookies:/app/cookies \
  -v $(pwd)/downloads:/app/downloads \
  --restart unless-stopped \
  all-in-one-downloader

# Podman:
podman run -d \
  --name all-in-one-downloader \
  -p 8000:8000 \
  -v $(pwd)/cookies:/app/cookies:Z \
  -v $(pwd)/downloads:/app/downloads:Z \
  --restart unless-stopped \
  all-in-one-downloader
```

---

## 💻 Local Development

For developers working on backend endpoints or frontend React components, the project provides a unified launcher script with hot-reloading for both services.

### Prerequisites

- **Python**: `>= 3.12`
- **uv**: `>= 0.4.0` ([Astral uv installer](https://docs.astral.sh/uv/getting-started/installation/))
- **Bun**: `>= 1.1.0` ([Bun installer](https://bun.sh/))
- **FFmpeg**: System binary or the auto-bundled `pyffmpeg` dependency

### Single-Command Dev Launcher

Run the included development launcher:

```bash
chmod +x scripts/dev.sh
./scripts/dev.sh
```

The script will automatically:
1. Verify required runtime versions (`python3 >= 3.12`, `uv >= 0.4`, `bun >= 1.1`).
2. Run `uv sync` in `backend/` and `bun install` in `frontend/` if not already installed.
3. Start the FastAPI backend on `http://localhost:8000` with auto-reload.
4. Start the Vite React frontend on `http://localhost:5173` with HMR (Hot Module Replacement).
5. Intercept `Ctrl+C` to cleanly terminate all processes and child workers.

---

## 🔑 Authentication & Cookies Guide

Certain platforms (such as **Instagram Stories** and private accounts) restrict media access behind login walls. The application natively supports **Netscape HTTP Cookie format** files.

### 1. Exporting Netscape Cookies

1. Install a trusted browser extension such as [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) (Chrome) or [Cookie Quick Manager](https://addons.mozilla.org/en-US/firefox/addon/cookie-quick-manager/) (Firefox).
2. Log into your account on the target platform (e.g., `instagram.com` or `x.com`).
3. Open the extension and export the cookies in **Netscape format**.

### 2. Uploading via Web UI

1. Click the **Settings** button in the top-right corner of the web interface.
2. Select your platform tab (**Instagram**, **Twitter/X**, or **YouTube**).
3. Paste the text content directly or upload your `.txt` file.
4. Click **Save Cookies**. The server activates them immediately without requiring a restart.

### 3. Manual File Placement

If you are running the service via Docker or headless server, you can place exported cookie files directly into the `cookies/` directory:

- `cookies/instagram.txt`
- `cookies/twitter.txt`
- `cookies/youtube.txt`

When using Docker Compose, the `./cookies` directory is mounted into the container at `/app/cookies`.

---

## ⚙️ Configuration & Environment Variables

You can configure the application via environment variables or a `.env` file:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `STORAGE_TTL_MINUTES` | `60` | Lifespan in minutes for completed downloads before the background cleaner removes them. |
| `SOCKS5_PROXY` | *None* | Optional SOCKS5 proxy URL (e.g. `socks5://user:pass@127.0.0.1:1080`) applied to extraction tools. |
| `YOUTUBE_PLAYER_CLIENTS`| `default` | yt-dlp client preference order (e.g. `android,web,tv`). |
| `COOKIES_DIR` | `/app/cookies` (Docker) or `<repo>/cookies` | Path to directory where Netscape cookies are stored. |
| `DOWNLOADS_DIR` | `/app/downloads` (Docker) or `<repo>/downloads` | Temporary download directory for active tasks. |
| `BASE_DIR` | Repository Root | Base operational directory. |

---

## 📡 API Reference & Examples

### Interactive Documentation

FastAPI provides interactive API docs when the server is running:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### Key Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/inspect` | Inspect media URL, extract metadata, formats, and gallery items. |
| `POST` | `/api/download` | Queue an asynchronous download job. Returns a `task_id`. |
| `GET` | `/api/progress/{task_id}` | Server-Sent Events (SSE) stream for download progress. |
| `GET` | `/api/files/{task_id}/{filename}`| Download the finished media file or `.zip` bundle. |
| `GET` | `/api/settings/cookies/status` | Check existing cookies status across platforms. |
| `POST` | `/api/settings/cookies/{platform}` | Upload or update cookie content for a platform. |

### cURL Walkthrough

#### Step 1: Inspect Media URL
```bash
curl -X POST http://localhost:8000/api/inspect \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

*Example Response:*
```json
{
  "id": "dQw4w9WgXcQ",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "platform": "youtube",
  "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
  "uploader": "Rick Astley",
  "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
  "duration": 213,
  "media_type": "video",
  "formats": [
    {"format_id": "best", "label": "Original Quality (MP4/MKV)", "ext": "mp4"},
    {"format_id": "1080p", "label": "1080p Full HD", "ext": "mp4"}
  ]
}
```

#### Step 2: Queue Download Task
```bash
curl -X POST http://localhost:8000/api/download \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "format_id": "best",
    "extract_audio": false,
    "package_as_zip": false
  }'
```

*Example Response:*
```json
{
  "task_id": "task-7832-482a-bc91",
  "status": "queued"
}
```

#### Step 3: Stream Live Progress (SSE)
```bash
curl -N http://localhost:8000/api/progress/task-7832-482a-bc91
```

*Event Stream Output:*
```text
event: progress
data: {"status":"downloading","progress":45.2,"speed":"4.2MiB/s","eta":12}

event: postprocessing
data: {"status":"remuxing","message":"Remuxing streams with FFmpeg..."}

event: complete
data: {"status":"completed","download_url":"/api/files/task-7832-482a-bc91/Rick_Astley_Never_Gonna_Give_You_Up.mp4","filename":"Rick_Astley_Never_Gonna_Give_You_Up.mp4","file_size":34192011}
```

---

## 🧹 Automated Storage Cleanup

To ensure disk space is never permanently consumed:
- Every active download is isolated into its own `downloads/<task_id>/` directory.
- An asynchronous background cleaner executes every **10 minutes**.
- Any task directory with last modification time exceeding `STORAGE_TTL_MINUTES` (default: 60 minutes) is automatically deleted.

---

## 🧪 Testing & Quality

### Running Backend Tests
Backend unit and integration tests are executed using `pytest` managed by `uv`:

```bash
cd backend
uv run pytest
```

### Running Frontend Tests & Type Checking
Frontend type checking and bundle tests are run with `bun`:

```bash
cd frontend
bun run build
bun test
```

---

## ⚖️ Legal & Fair Use Disclaimer

This software is provided for **personal, private archival, and educational purposes only**.

- Please respect the intellectual property rights and copyrights of content creators and media owners.
- Downloading copyrighted material without authorization from the copyright holder may violate local laws and the Terms of Service of third-party platforms.
- The authors and maintainers of this repository assume no liability and are not responsible for any misuse of this software.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
