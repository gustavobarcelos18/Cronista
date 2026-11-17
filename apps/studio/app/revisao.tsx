"use client";

import { useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8000";

type MediaFile = { id: number; name: string; ordinal: number; size_bytes: number };
type Session = { id: number; project: string; folder: string; files: MediaFile[] };
type Segment = {
  start_s: number;
  end_s: number;
  classe: string;
  score: number;
  razoes: string[];
  markers: string[];
  features: Record<string, number>;
};

function fmt(total: number): string {
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return (await res.json()) as T;
}

export default function Revisao() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [media, setMedia] = useState<MediaFile | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    getJson<Session[]>("/sessions")
      .then(setSessions)
      .catch(() => setError("Engine fora do ar. Rode `cronista api`."));
  }, []);

  function pick(file: MediaFile) {
    setMedia(file);
    setSegments([]);
    getJson<Segment[]>(`/media/${file.id}/segments`)
      .then(setSegments)
      .catch((e: Error) => setError(e.message));
  }

  function seek(seconds: number) {
    if (video.current) {
      video.current.currentTime = seconds;
      void video.current.play();
    }
  }

  return (
    <main style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 16, padding: 16 }}>
      <aside>
        <h1>Cronista Studio</h1>
        {error && <p role="alert">{error}</p>}
        {sessions.map((s) => (
          <section key={s.id}>
            <h3>
              {s.project} · sessão {s.id}
            </h3>
            <ul>
              {s.files.map((f) => (
                <li key={f.id}>
                  <button onClick={() => pick(f)} aria-pressed={media?.id === f.id}>
                    {f.name}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </aside>
      <section>
        {media ? (
          <>
            <video
              ref={video}
              src={`${API}/media/${media.id}/video`}
              controls
              style={{ width: "100%", maxHeight: "50vh", background: "#000" }}
            />
            <h2>Segmentos ({segments.length})</h2>
            <ol>
              {segments.map((g) => (
                <li key={g.start_s}>
                  <button onClick={() => seek(g.start_s)}>
                    {fmt(g.start_s)}–{fmt(g.end_s)}
                  </button>{" "}
                  <strong>{g.classe}</strong> nota {g.score.toFixed(2)}
                  {g.razoes.length > 0 && <small> · {g.razoes.join("; ")}</small>}
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p>Escolha um arquivo à esquerda.</p>
        )}
      </section>
    </main>
  );
}
