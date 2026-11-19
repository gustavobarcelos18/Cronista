"use client";

import type {
  DecisionIn,
  EventOut,
  MediaFileOut,
  SegmentOut,
  SessionOut,
  WaveformOut,
} from "@cronista/contracts";
import { Fragment, useEffect, useRef, useState } from "react";
import { API, ApiError, getJson, send } from "../lib/api";
import Ajuste from "./ajuste";
import Acabamento from "./acabamento";
import Aprendizado from "./aprendizado";
import Embalagem from "./embalagem";
import Exportar from "./exportar";
import Feedback from "./feedback";
import Painel from "./painel";
import Progresso from "./progresso";
import Roteiro from "./roteiro";
import Waveform from "./waveform";

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


export default function Revisao() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [media, setMedia] = useState<MediaFile | null>(null);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [segments, setSegments] = useState<Segment[] | null>(null);
  const [events, setEvents] = useState<EventOut[]>([]);
  const [wave, setWave] = useState<WaveformOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mediaErrors, setMediaErrors] = useState<string[]>([]);
  const [loadingSegments, setLoadingSegments] = useState(false);
  const [pending, setPending] = useState<number[]>([]);
  const selection = useRef<AbortController | null>(null);
  const [decisaoVersao, setDecisaoVersao] = useState(0);
  const [serie, setSerie] = useState(false);
  const [ajustando, setAjustando] = useState<number | null>(null); // start_s do trecho em ajuste
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    let alive = true;
    getJson<Session[]>("/sessions")
      .then((rows) => alive && setSessions(rows))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
      selection.current?.abort();
    };
  }, []);

  function pick(file: MediaFile, session: number, project: number) {
    selection.current?.abort();
    const request = new AbortController();
    selection.current = request;
    const { signal } = request;
    setMediaErrors([]);
    setLoadingSegments(true);
    setAjustando(null);
    setPending([]);
    setError(null);
    setMedia(file);
    setSessionId(session);
    setProjectId(project);
    setSegments(null);
    setEvents([]);
    setWave(null);
    function report(label: string, e: Error) {
      if (!signal.aborted) setMediaErrors((all) => [...all, `${label}: ${e.message}`]);
    }
    getJson<EventOut[]>(`/media/${file.id}/events`, signal)
      .then((rows) => !signal.aborted && setEvents(rows))
      .catch((e: Error) => report("Sinais", e));
    getJson<WaveformOut>(`/media/${file.id}/waveform`, signal)
      .then((value) => !signal.aborted && setWave(value))
      .catch((e: Error) => {
        if (!(e instanceof ApiError && e.status === 404)) report("Forma de onda", e);
      });
    getJson<Segment[]>(`/media/${file.id}/segments`, signal)
      .then((rows) => !signal.aborted && setSegments(rows))
      .catch((e: Error) => report("Segmentos", e))
      .finally(() => !signal.aborted && setLoadingSegments(false));
  }

  async function decide(g: Segment, body: DecisionIn) {
    if (!media || pending.includes(g.start_s)) return false;
    const request = selection.current;
    setPending((all) => [...all, g.start_s]);
    let updated: Segment;
    try {
      updated = await send<Segment>(`/media/${media.id}/segments/${g.start_s}/decision`, body);
    } catch (e) {
      if (!request?.signal.aborted) setError(e instanceof Error ? e.message : "Erro ao salvar a decisão.");
      return false;
    } finally {
      if (!request?.signal.aborted) setPending((all) => all.filter((start) => start !== g.start_s));
    }
    setDecisaoVersao((versao) => versao + 1);
    if (request?.signal.aborted) return false;
    setError(null);
    setSegments((all) => all?.map((x) => (x.start_s === g.start_s ? updated : x)) ?? null);
    return true;
  }

  // Vídeo da série: um só vídeo com todas as sessões do projeto, ancorado na última sessão dele.
  const projectSessions = (sessions ?? []).filter((s) => s.project_id === projectId);
  const serieDisponivel = projectId !== null && projectSessions.length > 1;
  const anchorId = serieDisponivel ? Math.max(...projectSessions.map((s) => s.id)) : null;
  const videoSessionId = serie && anchorId !== null ? anchorId : sessionId;
  const videoSerie = serie && anchorId !== null;

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
        {!!sessions?.length && <Painel revisao={decisaoVersao} />}
        {sessions?.map((s) => (
          <section key={s.id}>
            <h2>
              {s.project} · sessão {s.id}
            </h2>
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
            {wave && <Waveform wave={wave} segments={segments ?? []} onSeek={seek} />}
            {mediaErrors.map((message) => <p key={message} role="alert">{message}</p>)}
            <h2>{loadingSegments ? "Carregando segmentos…" : segments ? `Segmentos (${segments.length})` : "Segmentos indisponíveis"}</h2>
            <ol>
              {segments?.map((g) => (
                <li key={g.start_s}>
                  <button onClick={() => seek(g.adj_start_s ?? g.start_s)}>
                    {fmt(g.adj_start_s ?? g.start_s)}–{fmt(g.adj_end_s ?? g.end_s)}
                  </button>{" "}
                  <strong>{g.classe}</strong> nota {g.score.toFixed(2)}
                  {g.razoes.length > 0 && <small> · {g.razoes.join("; ")}</small>}
                  {g.decision && (
                    <em>
                      {" "}
                      [{g.decision}
                      {g.decision === "ajustado" && `, original ${fmt(g.start_s)}–${fmt(g.end_s)}`}]
                    </em>
                  )}{" "}
                  <button disabled={pending.includes(g.start_s)} onClick={() => void decide(g, { decision: "aceito" })}>Aceitar</button>
                  <button disabled={pending.includes(g.start_s)} onClick={() => void decide(g, { decision: "rejeitado" })}>Rejeitar</button>
                  <button disabled={pending.includes(g.start_s)} onClick={() => setAjustando(g.start_s)}>Ajustar</button>
                  {ajustando === g.start_s && (
                    <Ajuste
                      start={g.adj_start_s ?? g.start_s}
                      end={g.adj_end_s ?? g.end_s}
                      onCancel={() => setAjustando(null)}
                      onSubmit={(start, end) => {
                        void decide(g, { decision: "ajustado", start_s: start, end_s: end }).then((saved) => {
                          if (saved) setAjustando((current) => current === g.start_s ? null : current);
                        });
                      }}
                    />
                  )}
                  <Feedback mediaId={media.id} segStart={g.start_s} />
                  <SignalChips events={events.filter((e) => e.start_s < (g.adj_end_s ?? g.end_s) && e.end_s >= (g.adj_start_s ?? g.start_s))} />
                </li>
              ))}
            </ol>
            {serieDisponivel && (
              <label>
                <input type="checkbox" checked={serie} onChange={(e) => setSerie(e.target.checked)} /> Vídeo da
                série (todas as sessões do projeto, um alvo só; roteiro e embalagem ficam na sessão{" "}
                {anchorId})
              </label>
            )}
            {videoSessionId !== null && (
              // Um só pai com `key`: quando a sessão (ou o modo série) muda, os painéis remontam juntos.
              <Fragment key={`${videoSessionId}-${videoSerie}`}>
                <Roteiro sessionId={videoSessionId} />
                {projectId !== null && <Aprendizado key={projectId} projectId={projectId} revisao={decisaoVersao} />}
                {projectId !== null && (
                  <Acabamento sessionId={videoSessionId} projectId={projectId} serie={videoSerie} />
                )}
                <Embalagem sessionId={videoSessionId} />
                <Exportar sessionId={videoSessionId} serie={videoSerie} />
              </Fragment>
            )}
          </>
        ) : (
          error ? null : <p>{sessions === null ? "Carregando sessões…" : sessions.some((s) => s.files.length)
            ? "Escolha um arquivo à esquerda." : "Nenhum arquivo de gravação disponível para revisão."}</p>
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
