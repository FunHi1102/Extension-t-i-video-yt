import json
import os
import shutil
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import imageio_ffmpeg
import yt_dlp

HOST = "127.0.0.1"
PORT = 8765
DOWNLOAD_DIR = Path.home() / "Downloads"
FFMPEG_PATH = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


class _QuietLogger:
    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


def _extract_formats(url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "logger": _QuietLogger(),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    best_audio_size = 0
    for f in info.get("formats", []):
        if f.get("vcodec") == "none" and f.get("acodec") != "none":
            size = f.get("filesize") or f.get("filesize_approx") or 0
            if size > best_audio_size:
                best_audio_size = size

    by_height: dict[int, dict] = {}
    for f in info.get("formats", []):
        height = f.get("height")
        vcodec = f.get("vcodec")
        if not height or not vcodec or vcodec == "none":
            continue
        size = f.get("filesize") or f.get("filesize_approx") or 0
        fps = f.get("fps") or 30
        has_audio = f.get("acodec") != "none"
        est_size = size if has_audio else (size + best_audio_size if size else 0)

        existing = by_height.get(height)
        if not existing or est_size > existing["filesize"]:
            by_height[height] = {
                "id": f"bestvideo[height={height}]+bestaudio/best[height={height}]",
                "height": height,
                "fps": fps,
                "label": f"{height}p{f' {int(fps)}fps' if fps > 30 else ''} (MP4)",
                "filesize": est_size,
            }

    formats = [by_height[h] for h in sorted(by_height.keys(), reverse=True)]
    formats.append(
        {
            "id": "bestaudio/best",
            "height": 0,
            "fps": 0,
            "label": "Audio Only (M4A / Best)",
            "filesize": best_audio_size,
        }
    )

    return {
        "title": info.get("title", "YouTube Video"),
        "uploader": info.get("uploader", ""),
        "thumbnail": info.get("thumbnail", ""),
        "formats": formats,
    }


def _run_download(job_id: str, url: str, format_id: str) -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    is_audio = format_id == "bestaudio/best"
    final_path = ""

    def progress_hook(d: dict) -> None:
        nonlocal final_path
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            pct = (downloaded / total * 100.0) if total > 0 else 0.0
            with JOBS_LOCK:
                JOBS[job_id]["state"] = "downloading"
                JOBS[job_id]["progress"] = pct
        elif status == "finished":
            final_path = d.get("filename", final_path)
            with JOBS_LOCK:
                JOBS[job_id]["state"] = "merging"
                JOBS[job_id]["progress"] = 99.0

    def postprocessor_hook(d: dict) -> None:
        nonlocal final_path
        if d.get("status") == "finished":
            info = d.get("info_dict") or {}
            if info.get("filepath"):
                final_path = info["filepath"]

    ydl_opts = {
        "format": format_id,
        "outtmpl": str(DOWNLOAD_DIR / "%(title)s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": FFMPEG_PATH,
        "logger": _QuietLogger(),
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
    }
    if not is_audio:
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not final_path:
                final_path = ydl.prepare_filename(info)
        with JOBS_LOCK:
            JOBS[job_id]["state"] = "done"
            JOBS[job_id]["progress"] = 100.0
            JOBS[job_id]["filepath"] = final_path
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["state"] = "error"
            JOBS[job_id]["error"] = str(exc)


class BridgeHandler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send_json(204, {})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/health":
            self._send_json(200, {"status": "ok"})
            return

        if parsed.path == "/formats":
            url = (params.get("url") or [""])[0]
            if not url:
                self._send_json(400, {"error": "Missing url parameter"})
                return
            try:
                self._send_json(200, _extract_formats(url))
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return

        if parsed.path == "/status":
            job_id = (params.get("job_id") or [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
            if not job:
                self._send_json(404, {"error": "Job not found"})
                return
            self._send_json(200, job)
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/download":
            self._send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "Invalid JSON body"})
            return

        url = payload.get("url", "")
        format_id = payload.get("format_id", "")
        if not url or not format_id:
            self._send_json(400, {"error": "Missing url or format_id"})
            return

        job_id = str(uuid.uuid4())
        with JOBS_LOCK:
            JOBS[job_id] = {
                "state": "downloading",
                "progress": 0.0,
                "filepath": "",
                "error": "",
            }

        thread = threading.Thread(
            target=_run_download, args=(job_id, url, format_id), daemon=True
        )
        thread.start()
        self._send_json(202, {"job_id": job_id})

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), BridgeHandler).serve_forever()
