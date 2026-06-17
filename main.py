import os
import socket
import subprocess

import decky

PLUGIN_DIR = decky.DECKY_PLUGIN_DIR
SERVER = os.path.join(PLUGIN_DIR, "bin", "server.py")
FFMPEG = os.path.join(PLUGIN_DIR, "bin", "ffmpeg")  # положи сюда статический ffmpeg
VIDEO_DIR = "/home/deck/Videos"
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts")


class Plugin:
    proc = None

    async def _main(self):
        decky.logger.info("DeckCast загружен")

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
        return env

    # ── методы для фронтенда ───────────────────────────────────────
    async def start(self):
        if not (Plugin.proc and Plugin.proc.poll() is None):
            Plugin.proc = subprocess.Popen(
                ["python3", SERVER],
                env=self._env(),
                cwd=os.path.join(PLUGIN_DIR, "bin"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return {"running": True, "url": f"http://{self._ip()}:8777"}

    async def stop(self):
        self._kill()
        return {"running": False}

    async def status(self):
        running = Plugin.proc is not None and Plugin.proc.poll() is None
        ip = self._ip()
        return {"running": running, "url": f"http://{ip}:8777" if running else None, "ip": ip}

    async def list_videos(self):
        try:
            vids = [n for n in sorted(os.listdir(VIDEO_DIR)) if n.lower().endswith(VIDEO_EXTS)]
        except Exception:
            vids = []
        return {"dir": VIDEO_DIR, "videos": vids}
