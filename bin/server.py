#!/usr/bin/env python3
"""
DeckCast — стримит видео с Steam Deck на телефон по локальной сети.
Звук видео играет в наушниках, подключённых к Деку (через PulseAudio/PipeWire),
а картинка уходит на телефон в браузер. Телефону приложение не нужно.

Запуск:  python3 server.py
Потом на телефоне открой адрес, который покажет скрипт (например http://192.168.x.x:8777)

Зависимости: только ffmpeg + стандартная библиотека Python (ничего не надо ставить через pip).
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
# Папка, откуда брать видео. Положи фильмы сюда (или поменяй путь).
VIDEO_DIR = os.path.expanduser(os.environ.get("DECKCAST_VIDEO_DIR", "~/Videos"))
# Путь к ffmpeg. Если ffmpeg не в системе — укажи путь к статическому бинарнику:
#   DECKCAST_FFMPEG=/home/deck/deckcast/ffmpeg python3 server.py
FFMPEG = os.environ.get("DECKCAST_FFMPEG", "ffmpeg")
# Имя аудио-выхода в логах PulseAudio (просто метка)
SINK_LABEL = "DeckCast"

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts")
# ──────────────────────────────────────────────────────────────────


def lan_ip():
    """Определяем локальный IP Дека, чтобы показать пользователю адрес."""
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
    out = []
    for name in sorted(os.listdir(VIDEO_DIR)):
        if name.lower().endswith(VIDEO_EXTS):
            out.append(name)
    return out


def build_ffmpeg_cmd(path, delay_ms):
    """
    Один процесс ffmpeg делает сразу две вещи:
      1) звук -> аудиовыход Дека (наушники) с задержкой delay_ms (для синхрона с телефоном)
      2) видео -> поток MPEG-TS, который мы отдаём телефону по HTTP
    """
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "warning",
        "-re",                      # читать в реальном времени (как плеер)
        "-i", path,
    ]
    # --- Аудио на Дек (наушники) ---
    cmd += ["-map", "0:a?"]
    if delay_ms > 0:
        # задержка звука, чтобы он совпал с картинкой на телефоне
        cmd += ["-filter:a", f"adelay={delay_ms}:all=1"]
    cmd += ["-f", "pulse", SINK_LABEL]
    # --- Видео на телефон (MPEG-TS в stdout) ---
    cmd += [
        "-map", "0:v",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", "-g", "30", "-b:v", "6M",
        # Хочешь аппаратное кодирование (легче для CPU)? Замени строку выше на:
        #   "-c:v", "h264_vaapi", "-vaapi_device", "/dev/dri/renderD128", ...
        "-f", "mpegts", "pipe:1",
    ]
    return cmd


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # тихо

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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if route == "/" or route == "/index.html":
            return self._send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")

        if route == "/mpegts.js":
            return self._send_file(os.path.join(WEB_DIR, "mpegts.js"), "application/javascript")

        if route == "/list":
            body = json.dumps({"videos": list_videos()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if route == "/stream":
            return self._do_stream(qs)

        self.send_error(404)

    def _do_stream(self, qs):
        name = (qs.get("file", [""])[0])
        delay_ms = int(qs.get("delay", ["1500"])[0])
        path = os.path.join(VIDEO_DIR, name)
        # защита от выхода за пределы папки
        if not name or os.path.dirname(os.path.realpath(path)) != os.path.realpath(VIDEO_DIR):
            self.send_error(400, "bad file")
            return
        if not os.path.isfile(path):
            self.send_error(404, "no such video")
            return

        cmd = build_ffmpeg_cmd(path, delay_ms)
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
            pass  # телефон закрыл вкладку
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()


def main():
    if shutil.which(FFMPEG) is None and not os.path.isfile(FFMPEG):
        print(f"[!] ffmpeg не найден ('{FFMPEG}'). Установи ffmpeg или укажи путь через DECKCAST_FFMPEG.")
        print("    На SteamOS проще всего положить рядом статический бинарник ffmpeg.")
    if not os.path.isfile(os.path.join(WEB_DIR, "mpegts.js")):
        print("[!] web/mpegts.js не найден — телефон не сможет проиграть видео.")
        print("    Запусти ./run.sh — он скачает библиотеку, либо скачай вручную (см. README).")

    ip = lan_ip()
    print("=" * 50)
    print("  DeckCast запущен!")
    print(f"  Видео берём из: {VIDEO_DIR}")
    print(f"  На телефоне открой:  http://{ip}:{PORT}")
    print("  (телефон и Дек должны быть в одной Wi-Fi сети)")
    print("  Ctrl+C — остановить")
    print("=" * 50)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлено.")
