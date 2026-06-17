import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaTv } from "react-icons/fa";
import QRCode from "react-qr-code";

// Методы из main.py (Python-бэкенд плагина)
const startSrv = callable<[], { running: boolean; url: string | null; needs_setup: boolean }>("start");
const stopSrv = callable<[], { running: boolean }>("stop");
const getStatus = callable<[], { running: boolean; url: string | null; ip: string; ffmpeg: boolean; ytdlp: boolean }>("status");
const setupDeps = callable<[], { ffmpeg: boolean; ytdlp: boolean; error: string | null }>("setup");

function Content() {
  const [running, setRunning] = useState(false);
  const [url, setUrl] = useState<string>("");
  const [ffmpeg, setFfmpeg] = useState(true);
  const [ytdlp, setYtdlp] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>("");

  const refresh = async () => {
    const s = await getStatus();
    setRunning(s.running);
    setUrl(s.url ?? `http://${s.ip}:8777`);
    setFfmpeg(s.ffmpeg);
    setYtdlp(s.ytdlp);
  };

  useEffect(() => {
    refresh();
  }, []);

  const toggle = async () => {
    setBusy(true);
    setMsg("");
    try {
      if (running) {
        await stopSrv();
      } else {
        const r = await startSrv();
        if (r.needs_setup) setMsg("Сначала установи компоненты ⬇");
      }
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const install = async () => {
    setBusy(true);
    setMsg("Скачиваю ffmpeg и yt-dlp… (это разово, ~1–2 мин)");
    try {
      const r = await setupDeps();
      setFfmpeg(r.ffmpeg);
      setYtdlp(r.ytdlp);
      setMsg(r.error ? "Ошибка: " + r.error : "Готово ✓ компоненты установлены");
    } catch (e) {
      setMsg("Не удалось скачать. Есть ли интернет на Деке?");
    } finally {
      setBusy(false);
    }
  };

  const needSetup = !ffmpeg || !ytdlp;

  return (
    <PanelSection title="DeckCast — второй экран">
      {needSetup && (
        <>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy} onClick={install}>
              ⬇ Установить компоненты
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ fontSize: "12px", opacity: 0.7, width: "100%" }}>
              ffmpeg: {ffmpeg ? "✓" : "—"} · yt-dlp: {ytdlp ? "✓" : "—"} (нужен для ссылок)
            </div>
          </PanelSectionRow>
        </>
      )}

      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy || !ffmpeg} onClick={toggle}>
          {running ? "■ Остановить" : "▶ Запустить стрим"}
        </ButtonItem>
      </PanelSectionRow>

      {msg && (
        <PanelSectionRow>
          <div style={{ fontSize: "13px", opacity: 0.85, width: "100%" }}>{msg}</div>
        </PanelSectionRow>
      )}

      {running && url && (
        <>
          <PanelSectionRow>
            <div style={{ width: "100%", textAlign: "center", padding: "6px 0 2px" }}>
              <div style={{ fontSize: "12px", opacity: 0.6, marginBottom: "6px" }}>
                Наведи камеру телефона:
              </div>
              <div style={{ background: "#fff", padding: "10px", borderRadius: "10px", display: "inline-block" }}>
                <QRCode value={url} size={148} />
              </div>
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <div
              style={{
                width: "100%",
                textAlign: "center",
                fontSize: "16px",
                fontWeight: 600,
                wordBreak: "break-all",
                padding: "2px 0 6px",
              }}
            >
              {url}
            </div>
          </PanelSectionRow>
        </>
      )}

      <PanelSectionRow>
        <div style={{ fontSize: "12px", opacity: 0.55, width: "100%" }}>
          Телефон и Дек — в одной Wi-Fi. Звук в наушниках Деки, картинка на телефоне.
          Ссылку (YouTube) вставляешь на самой странице телефона.
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => ({
  name: "DeckCast",
  titleView: <div className={staticClasses.Title}>DeckCast</div>,
  content: <Content />,
  icon: <FaTv />,
  onDismount() {},
}));
