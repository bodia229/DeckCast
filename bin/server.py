#!/usr/bin/env python3
"""
DeckCast — стримит видео с Steam Deck на телефон по локальной сети + пульт.
Телефон: поиск по YouTube, выбор видео, перемотка, пауза, громкость.
Картинка на телефоне, звук — в наушниках Деки.

Зависимости: ffmpeg (обязательно) + yt-dlp (поиск/ссылки) + стандартная библиотека.
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


# ─────────────────────────── YouTube ───────────────────────────
def yt_search(query):
    """Поиск по YouTube через yt-dlp. Возвращает список карточек видео."""
    out = subprocess.run(
        [YTDLP, f"ytsearch15:{query}", "--flat-playlist", "-J", "--no-warnings"],
        capture_output=True, text=True, timeout=45,
    )
    if not out.stdout.strip():
        raise RuntimeError(out.stderr.strip()[:160] or "пустой ответ yt-dlp")
    data = json.loads(out.stdout)
    res = []
    for e in data.get("entries", []):
        vid = e.get("id")
        if not vid:
            continue
        res.append({
            "id": vid,
            "title": e.get("title") or vid,
            "channel": e.get("channel") or e.get("uploader") or "",
            "duration": e.get("duration"),
            "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
        })
    return res


def yt_info(url):
    """Заголовок и длительность ролика (для шкалы перемотки)."""
    out = subprocess.run(
        [YTDLP, "--no-warnings", "--print", "%(title)s", "--print", "%(duration)s", url],
        capture_output=True, text=True, timeout=45,
    )
    lines = out.stdout.splitlines()
    title = lines[0] if lines else ""
    dur = None
    if len(lines) > 1:
        try:
            dur = float(lines[1])
        except ValueError:
            dur = None
    return {"title": title, "duration": dur}


# ─────────────────────────── ffmpeg ───────────────────────────
def _ss_prefix(ss):
    return ["-ss", f"{ss:.3f}"] if ss and ss > 0 else []


def _net_input(link, ss):
    """Сетевой источник: перемотка + переподключение + чтение в реальном времени."""
    return _ss_prefix(ss) + ["-reconnect", "1", "-reconnect_streamed", "1",
                             "-reconnect_delay_max", "5", "-re", "-i", link]


def resolve_source(file_name, url, ss):
    """Возвращает (input_args, audio_spec, video_spec) для ffmpeg."""
    if url:
        fmt = "bv*[height<=?720]+ba/b[height<=?720]/b"
        try:
            out = subprocess.run([YTDLP, "-f", fmt, "-g", url],
                                 capture_output=True, text=True, timeout=45)
        except FileNotFoundError:
            raise RuntimeError("yt-dlp не найден — нажми «Установить компоненты»")
        links = [l for l in out.stdout.splitlines() if l.strip()]
        if not links:
            raise RuntimeError("yt-dlp не разобрал ссылку: " + (out.stderr.strip()[:160] or "?"))
        if len(links) >= 2:
            return (_net_input(links[0], ss) + _net_input(links[1], ss), "1:a", "0:v")
        return (_net_input(links[0], ss), "0:a?", "0:v")

    path = os.path.join(VIDEO_DIR, file_name)
    if not file_name or os.path.dirname(os.path.realpath(path)) != os.path.realpath(VIDEO_DIR):
        raise RuntimeError("bad file")
    if not os.path.isfile(path):
        raise RuntimeError("no such video")
    return (_ss_prefix(ss) + ["-re", "-i", path], "0:a?", "0:v")


def build_ffmpeg_cmd(input_args, a_spec, v_spec, delay_ms, vol):
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning"] + input_args
    # --- Звук на Дек (задержка для синхрона + громкость) ---
    cmd += ["-map", a_spec]
    af = []
    if delay_ms > 0:
        af.append(f"adelay={delay_ms}:all=1")
    if vol is not None and abs(vol - 1.0) > 0.01:
        af.append(f"volume={vol:.2f}")
    if af:
        cmd += ["-filter:a", ",".join(af)]
    cmd += ["-f", "pulse", SINK_LABEL]
    # --- Видео на телефон ---
    cmd += [
        "-map", v_spec,
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", "-g", "30", "-b:v", "6M",
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

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
        if route == "/search":
            q = qs.get("q", [""])[0]
            if not q:
                return self._send_json({"results": []})
            try:
                return self._send_json({"results": yt_search(q)})
            except Exception as e:
                return self._send_json({"results": [], "error": str(e)[:160]}, 200)
        if route == "/info":
            u = qs.get("url", [""])[0]
            try:
                return self._send_json(yt_info(u))
            except Exception as e:
                return self._send_json({"title": "", "duration": None, "error": str(e)[:160]}, 200)
        if route == "/stream":
            return self._do_stream(qs)
        self.send_error(404)

    def _do_stream(self, qs):
        name = qs.get("file", [""])[0]
        url = qs.get("url", [""])[0]
        delay_ms = int(float(qs.get("delay", ["1500"])[0]))
        try:
            ss = float(qs.get("ss", ["0"])[0])
        except ValueError:
            ss = 0.0
        try:
            vol = float(qs.get("vol", ["1"])[0])
        except ValueError:
            vol = 1.0

        try:
            input_args, a_spec, v_spec = resolve_source(name, url, ss)
        except RuntimeError as e:
            self.send_error(400, str(e))
            return

        cmd = build_ffmpeg_cmd(input_args, a_spec, v_spec, delay_ms, vol)
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
