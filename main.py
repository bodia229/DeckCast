import os
import ssl
import stat
import shutil
import socket
import asyncio
import tarfile
import tempfile
import subprocess
import urllib.request

import decky

PLUGIN_DIR = decky.DECKY_PLUGIN_DIR
BIN_DIR = os.path.join(PLUGIN_DIR, "bin")
SERVER = os.path.join(BIN_DIR, "server.py")
FFMPEG = os.path.join(BIN_DIR, "ffmpeg")
YTDLP = os.path.join(BIN_DIR, "yt-dlp")
VIDEO_DIR = "/home/deck/Videos"
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts")

# Steam Deck — x86_64. Берём готовые статические сборки.
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"


def _chmodx(path):
    st = os.stat(path)
    os.chmod(path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _ssl_context():
    # Проверку сертификата НЕ отключаем. На Деке окружение плагина не находит
    # CA-бандл по умолчанию (ssl: certificate_verify_failed) — явно указываем
    # на системный набор сертификатов SteamOS.
    for ca in (
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ca-certificates/extracted/tls-ca-bundle.pem",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ):
        if os.path.isfile(ca):
            try:
                return ssl.create_default_context(cafile=ca)
            except Exception:
                pass
    return ssl.create_default_context()


def _download(url, dest):
    ctx = _ssl_context()
    req = urllib.request.Request(url, headers={"User-Agent": "DeckCast"})
    with urllib.request.urlopen(req, timeout=180, context=ctx) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def _install_ffmpeg():
    """Скачиваем архив, достаём один бинарник ffmpeg в bin/."""
    fd, tmp = tempfile.mkstemp(suffix=".tar.xz")
    os.close(fd)
    try:
        _download(FFMPEG_URL, tmp)
        with tarfile.open(tmp, "r:xz") as tar:
            member = next(
                m for m in tar.getmembers()
                if m.isfile() and os.path.basename(m.name) == "ffmpeg"
            )
            with tar.extractfile(member) as src, open(FFMPEG, "wb") as out:
                shutil.copyfileobj(src, out)
        _chmodx(FFMPEG)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _install_ytdlp():
    _download(YTDLP_URL, YTDLP)
    _chmodx(YTDLP)


def _do_setup():
    """Качаем то, чего не хватает. Возвращаем статус + текст ошибки, если была."""
    os.makedirs(VIDEO_DIR, exist_ok=True)
    error = None
    try:
        if not os.path.isfile(FFMPEG):
            _install_ffmpeg()
    except Exception as e:
        error = f"ffmpeg: {e}"
    try:
        if not os.path.isfile(YTDLP):
            _install_ytdlp()
    except Exception as e:
        error = (error + " | " if error else "") + f"yt-dlp: {e}"
    return {
        "ffmpeg": os.path.isfile(FFMPEG),
        "ytdlp": os.path.isfile(YTDLP),
        "error": error,
    }


class Plugin:
    proc = None

    async def _main(self):
        decky.logger.info("DeckCast загружен")
        os.makedirs(VIDEO_DIR, exist_ok=True)

    async def _unload(self):
        decky.logger.info("DeckCast выгружается")
        self._kill()

    # ── вспомогательные ────────────────────────────────────────────
    def _kill(self):
        if Plugin.proc and Plugin.proc.poll() is None:
            Plugin.proc.terminate()
            try:
                Plugin.proc.wait(timeout=3)
            except Exception:
                Plugin.proc.kill()
        Plugin.proc = None

    def _ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()

    def _env(self):
        env = dict(os.environ)
        # Бэкенд плагина крутится от root — направляем звук в аудиосессию
        # пользователя deck (uid 1000), иначе ffmpeg не достучится до наушников.
        env["XDG_RUNTIME_DIR"] = "/run/user/1000"
        env["PULSE_SERVER"] = "unix:/run/user/1000/pulse/native"
        env["DECKCAST_VIDEO_DIR"] = VIDEO_DIR
        if os.path.isfile(FFMPEG):
            env["DECKCAST_FFMPEG"] = FFMPEG
        if os.path.isfile(YTDLP):
            env["DECKCAST_YTDLP"] = YTDLP
        return env

    # ── методы для фронтенда ───────────────────────────────────────
    async def deps_status(self):
        return {"ffmpeg": os.path.isfile(FFMPEG), "ytdlp": os.path.isfile(YTDLP)}

    async def setup(self):
        """Скачивает ffmpeg и yt-dlp в bin/ (то, чего не хватает)."""
        return await asyncio.to_thread(_do_setup)

    async def start(self):
        # без ffmpeg запускать бессмысленно
        if not os.path.isfile(FFMPEG):
            return {"running": False, "url": None, "needs_setup": True}
        if not (Plugin.proc and Plugin.proc.poll() is None):
            Plugin.proc = subprocess.Popen(
                ["python3", SERVER],
                env=self._env(),
                cwd=BIN_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return {"running": True, "url": f"http://{self._ip()}:8777", "needs_setup": False}

    async def stop(self):
        self._kill()
        return {"running": False}

    async def status(self):
        running = Plugin.proc is not None and Plugin.proc.poll() is None
        ip = self._ip()
        return {
            "running": running,
            "url": f"http://{ip}:8777" if running else None,
            "ip": ip,
            "ffmpeg": os.path.isfile(FFMPEG),
            "ytdlp": os.path.isfile(YTDLP),
        }

    async def list_videos(self):
        try:
            vids = [n for n in sorted(os.listdir(VIDEO_DIR)) if n.lower().endswith(VIDEO_EXTS)]
        except Exception:
            vids = []
        return {"dir": VIDEO_DIR, "videos": vids}
