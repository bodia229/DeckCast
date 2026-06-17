#!/usr/bin/env python3
"""
DeckCast — стримит видео с Steam Deck на телефон по локальной сети.
Источник: либо файл из папки, либо ссылка (YouTube и т.п. через yt-dlp).
Звук играет в наушниках Дека, картинка уходит на телефон в браузер.

Зависимости: ffmpeg (обязательно) + yt-dlp (для ссылок) + стандартная библиотека Python.
"""

import os
import sys
import json
import socket
import shutil
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ─────────────────────────── Настройки ───────────────────────────
PORT = 8777
VIDEO_DIR = os.path.expanduser(os.environ.get("DECKCAST_VIDEO_DIR", "~/Videos"))
FFMPEG = os.environ.get("DECKCAST_FFMPEG", "ffmpeg")
YTDLP = os.environ.get("DECKCAST_YTDLP", "yt-dlp")
SINK_LABEL = "DeckCast"

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts")
# ──────────────────────────────────────────────────────────────────


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def list_videos():
    if not os.path.isdir(VIDEO_DIR):
        return []
    return [n for n in sorted(os.listdir(VIDEO_DIR)) if n.lower().endswith(VIDEO_EXTS)]


def _net_input(link):
    """Сетевой источник: переподключение при обрыве + чтение в реальном времени."""
    return ["-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5", "-re", "-i", link]


def resolve_source(file_name, url):
    """
    Возвращает (input_args, audio_spec, video_spec) для ffmpeg.
    - file_name: имя файла в VIDEO_DIR
    - url: ссылка (YouTube и др.), разбирается через yt-dlp
    """
    if url:
        # формат: видео<=720p + аудио, либо готовый муксированный поток
        fmt = "bv*[height<=?720]+ba/b[height<=?720]/b"
        try:
            out = subprocess.run([YTDLP, "-f", fmt, "-g", url],
                                 capture_output=True, text=True, timeout=40)
        except FileNotFoundError:
            raise RuntimeError("yt-dlp не найден — положи его в bin/ (см. README)")
        links = [l for l in out.stdout.splitlines() if l.strip()]
        if not links:
            raise RuntimeError("yt-dlp не разобрал ссылку: " + (out.stderr.strip()[:180] or "?"))
        if len(links) >= 2:
            # отдельные потоки: первый — видео, второй — аудио
            return (_net_input(links[0]) + _net_input(links[1]), "1:a", "0:v")
        return (_net_input(links[0]), "0:a?", "0:v")

    # локальный файл
    path = os.path.join(VIDEO_DIR, file_name)
    if not file_name or os.path.dirname(os.path.realpath(path)) != os.path.realpath(VIDEO_DIR):
        raise RuntimeError("bad file")
    if not os.path.isfile(path):
        raise RuntimeError("no such video")
    return (["-re", "-i", path], "0:a?", "0:v")


def build_ffmpeg_cmd(input_args, a_spec, v_spec, delay_ms):
    """
    Один ffmpeg: звук -> наушники Дека (с задержкой для синхрона),
    видео -> поток MPEG-TS на телефон.
    """
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning"] + input_args
    # --- Звук на Дек ---
    cmd += ["-map", a_spec]
    if delay_ms > 0:
        cmd += ["-filter:a", f"adelay={delay_ms}:all=1"]
    cmd += ["-f", "pulse", SINK_LABEL]
    # --- Видео на телефон ---
    cmd += [
        "-map", v_spec,
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", "-g", "30", "-b:v", "6M",
        # Аппаратное кодирование (легче для CPU): заменить строку выше на h264_vaapi
        "-f", "mpegts", "pipe:1",
    ]
    return cmd


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send_file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if route in ("/", "/index.html"):
            return self._send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
        if route == "/mpegts.js":
            return self._send_file(os.path.join(WEB_DIR, "mpegts.js"), "application/javascript")
        if route == "/list":
            return self._send_json({"videos": list_videos()})
        if route == "/stream":
            return self._do_stream(qs)
        self.send_error(404)

    def _do_stream(self, qs):
        name = qs.get("file", [""])[0]
        url = qs.get("url", [""])[0]
        delay_ms = int(qs.get("delay", ["1500"])[0])
        try:
            input_args, a_spec, v_spec = resolve_source(name, url)
        except RuntimeError as e:
            self.send_error(400, str(e))
            return

        cmd = build_ffmpeg_cmd(input_args, a_spec, v_spec, delay_ms)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=sys.stderr)
        self.send_response(200)
        self.send_header("Content-Type", "video/mp2t")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()


def main():
    if shutil.which(FFMPEG) is None and not os.path.isfile(FFMPEG):
        print(f"[!] ffmpeg не найден ('{FFMPEG}'). См. README.")
    if not os.path.isfile(os.path.join(WEB_DIR, "mpegts.js")):
        print("[!] web/mpegts.js не найден — телефон не проиграет видео.")

    ip = lan_ip()
    print("=" * 50)
    print("  DeckCast запущен!")
    print(f"  Видео из папки: {VIDEO_DIR}")
    print(f"  На телефоне открой:  http://{ip}:{PORT}")
    print("  Ctrl+C — остановить")
    print("=" * 50)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлено.")
