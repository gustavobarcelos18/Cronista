"use client";

import type {
  DecisionIn,
  EventOut,
  MediaFileOut,
  SegmentOut,
  SessionOut,
  WaveformOut,
} from "@cronista/contracts";
import { useEffect, useRef, useState } from "react";
import Aprendizado from "./aprendizado";
import Exportar from "./exportar";
import Feedback from "./feedback";
import Painel from "./painel";
import Progresso from "./progresso";
import Roteiro from "./roteiro";

const API = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8000";

type MediaFile = MediaFileOut;
type Session = SessionOut;
type Segment = SegmentOut;

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
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [events, setEvents] = useState<EventOut[]>([]);
  const [wave, setWave] = useState<WaveformOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decisaoVersao, setDecisaoVersao] = useState(0);
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    getJson<Session[]>("/sessions")
      .then(setSessions)
      .catch(() => setError("Engine fora do ar. Rode `cronista api`."));
  }, []);

  function pick(file: MediaFile, session: number, project: number) {
    setMedia(file);
    setSessionId(session);
    setProjectId(project);
    setSegments([]);
    setEvents([]);
    setWave(null);
    getJson<EventOut[]>(`/media/${file.id}/events`)
      .then(setEvents)
      .catch(() => setEvents([]));
    getJson<WaveformOut>(`/media/${file.id}/waveform`)
      .then(setWave)
      .catch(() => setWave(null));
    getJson<Segment[]>(`/media/${file.id}/segments`)
      .then(setSegments)
      .catch((e: Error) => setError(e.message));
  }

  async function decide(g: Segment, body: DecisionIn) {
    if (!media) return;
    const res = await fetch(`${API}/media/${media.id}/segments/${g.start_s}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
      setError(typeof body?.detail === "string" ? body.detail : `decisão: ${res.status}`);
      return;
    }
    const updated = (await res.json()) as Segment;
    setSegments((all) => all.map((x) => (x.start_s === g.start_s ? updated : x)));
    setDecisaoVersao((versao) => versao + 1);
  }

  function adjust(g: Segment) {
    // Cancelar (null) ou deixar vazio não pode virar 0: aborta o ajuste inteiro.
    const askedStart = prompt("Novo início (s do arquivo)", String(g.adj_start_s ?? g.start_s));
    if (askedStart === null || askedStart.trim() === "") return;
    const askedEnd = prompt("Novo fim (s do arquivo)", String(g.adj_end_s ?? g.end_s));
    if (askedEnd === null || askedEnd.trim() === "") return;
    const start = Number(askedStart.replace(",", "."));
    const end = Number(askedEnd.replace(",", "."));
    if (Number.isFinite(start) && Number.isFinite(end)) {
      void decide(g, { decision: "ajustado", start_s: start, end_s: end });
    } else {
      setError("Ajuste cancelado: informe números em segundos.");
    }
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
        <Painel revisao={decisaoVersao} />
        {sessions.map((s) => (
          <section key={s.id}>
            <h3>
              {s.project} · sessão {s.id}
            </h3>
            <Progresso sessionId={s.id} />
            <ul>
              {s.files.map((f) => (
                <li key={f.id}>
                  <button onClick={() => pick(f, s.id, s.project_id)} aria-pressed={media?.id === f.id}>
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
            {wave && <Waveform wave={wave} segments={segments} onSeek={seek} />}
            <h2>Segmentos ({segments.length})</h2>
            <ol>
              {segments.map((g) => (
                <li key={g.start_s}>
                  <button onClick={() => seek(g.start_s)}>
                    {fmt(g.start_s)}–{fmt(g.end_s)}
                  </button>{" "}
                  <strong>{g.classe}</strong> nota {g.score.toFixed(2)}
                  {g.razoes.length > 0 && <small> · {g.razoes.join("; ")}</small>}
                  {g.decision && (
                    <em>
                      {" "}
                      [{g.decision}
                      {g.decision === "ajustado" && ` ${fmt(g.adj_start_s ?? 0)}–${fmt(g.adj_end_s ?? 0)}`}]
                    </em>
                  )}{" "}
                  <button onClick={() => void decide(g, { decision: "aceito" })}>Aceitar</button>
                  <button onClick={() => void decide(g, { decision: "rejeitado" })}>Rejeitar</button>
                  <button onClick={() => adjust(g)}>Ajustar</button>
                  <Feedback mediaId={media.id} segStart={g.start_s} />
                  <SignalChips events={events.filter((e) => e.start_s < g.end_s && e.end_s >= g.start_s)} />
                </li>
              ))}
            </ol>
            {sessionId !== null && <Roteiro key={sessionId} sessionId={sessionId} />}
            {projectId !== null && <Aprendizado key={projectId} projectId={projectId} />}
            {sessionId !== null && <Exportar key={sessionId} sessionId={sessionId} />}
          </>
        ) : (
          <p>Escolha um arquivo à esquerda.</p>
        )}
      </section>
    </main>
  );
}

function SignalChips({ events }: { events: EventOut[] }) {
  if (events.length === 0) return null;
  const counts = new Map<string, number>();
  for (const e of events) counts.set(e.kind, (counts.get(e.kind) ?? 0) + 1);
  return (
    <small>
      {" · sinais: "}
      {[...counts].map(([kind, n]) => `${kind}${n > 1 ? ` ×${n}` : ""}`).join(", ")}
    </small>
  );
}

const WAVE_H = 80;
const FLOOR_DB = -60;

function Waveform({
  wave,
  segments,
  onSeek,
}: {
  wave: WaveformOut;
  segments: Segment[];
  onSeek: (seconds: number) => void;
}) {
  const n = Math.max(wave.game.length, wave.mic.length, 1);
  const bar = (db: number) => Math.max(1, ((Math.min(0, Math.max(FLOOR_DB, db)) - FLOOR_DB) / -FLOOR_DB) * (WAVE_H / 2));
  const x = (seconds: number) => (seconds / Math.max(wave.duration_s, 1)) * n;
  return (
    <svg
      viewBox={`0 0 ${n} ${WAVE_H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Energia do áudio (jogo em cima, microfone embaixo)"
      style={{ width: "100%", height: WAVE_H, background: "#111", cursor: "pointer", display: "block" }}
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        onSeek(((e.clientX - r.left) / r.width) * wave.duration_s);
      }}
    >
      {segments.map((g) => (
        <rect
          key={g.start_s}
          x={x(g.start_s)}
          width={Math.max(x(g.end_s) - x(g.start_s), 0.5)}
          y={0}
          height={WAVE_H}
          fill={g.score >= 0.35 ? "#2a6" : "#555"}
          opacity={0.25}
        />
      ))}
      {wave.game.map((db, i) => (
        <rect key={`g${i}`} x={i} width={1} y={WAVE_H / 2 - bar(db)} height={bar(db)} fill="#6cf" />
      ))}
      {wave.mic.map((db, i) => (
        <rect key={`m${i}`} x={i} width={1} y={WAVE_H / 2} height={bar(db)} fill="#fc6" />
      ))}
    </svg>
  );
}
