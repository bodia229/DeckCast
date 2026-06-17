import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  Field,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaTv } from "react-icons/fa";

// Методы из main.py (Python-бэкенд плагина)
const startSrv = callable<[], { running: boolean; url: string }>("start");
const stopSrv = callable<[], { running: boolean }>("stop");
const getStatus = callable<[], { running: boolean; url: string | null; ip: string }>("status");
const listVideos = callable<[], { dir: string; videos: string[] }>("list_videos");

function Content() {
  const [running, setRunning] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [count, setCount] = useState(0);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    const s = await getStatus();
    setRunning(s.running);
    setUrl(s.running ? s.url : `http://${s.ip}:8777`);
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
        <PanelSectionRow>
          <Field label="Открой в браузере телефона" focusable={true}>
            {url}
          </Field>
        </PanelSectionRow>
      )}

      <PanelSectionRow>
        <Field label="Видео в папке">{String(count)}</Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <div style={{ fontSize: "12px", opacity: 0.6 }}>
          Телефон и Дек — в одной Wi-Fi сети. Звук идёт в наушники Деки, картинка — на телефон.
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
