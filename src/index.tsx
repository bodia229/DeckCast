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
const startSrv = callable<[], { running: boolean; url: string }>("start");
const stopSrv = callable<[], { running: boolean }>("stop");
const getStatus = callable<[], { running: boolean; url: string | null; ip: string }>("status");
const listVideos = callable<[], { dir: string; videos: string[] }>("list_videos");

function Content() {
  const [running, setRunning] = useState(false);
  const [url, setUrl] = useState<string>("");
  const [count, setCount] = useState(0);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    const s = await getStatus();
    setRunning(s.running);
    setUrl(s.url ?? `http://${s.ip}:8777`);
    const v = await listVideos();
    setCount(v.videos.length);
  };

  useEffect(() => {
    refresh();
  }, []);

  const toggle = async () => {
    setBusy(true);
    try {
      if (running) await stopSrv();
      else await startSrv();
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title="DeckCast — второй экран">
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={toggle}>
          {running ? "■ Остановить" : "▶ Запустить стрим"}
        </ButtonItem>
      </PanelSectionRow>

      {running && url && (
        <>
          <PanelSectionRow>
            <div style={{ width: "100%", textAlign: "center", padding: "6px 0 2px" }}>
              <div style={{ fontSize: "12px", opacity: 0.6, marginBottom: "6px" }}>
                Наведи камеру телефона:
              </div>
              <div
                style={{
                  background: "#fff",
                  padding: "10px",
                  borderRadius: "10px",
                  display: "inline-block",
                }}
              >
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
        <div style={{ fontSize: "13px", opacity: 0.7, width: "100%" }}>
          Видео в папке: {count} · ссылку (YouTube) можно вставить на самой странице телефона
        </div>
      </PanelSectionRow>

      <PanelSectionRow>
        <div style={{ fontSize: "12px", opacity: 0.55, width: "100%" }}>
          Телефон и Дек — в одной Wi-Fi. Звук в наушниках Деки, картинка на телефоне.
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
