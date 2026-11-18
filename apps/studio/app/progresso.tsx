"use client";

import type { ProgressOut } from "@cronista/contracts";
import { useEffect, useState } from "react";
import { API } from "../lib/api";

const IDLE_RETRY_MS = 5000;
const MAX_RETRY_MS = 30000;

/** Progresso dos jobs da sessão por SSE; o engine fecha o stream sem job ativo e o painel reabre sozinho. */
export default function Progresso({ sessionId }: { sessionId: number }) {
  const [p, setP] = useState<ProgressOut | null>(null);

  useEffect(() => {
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    let alive = true;

    // O stream fecha quando não resta job ativo (`end`) e cai com o engine fora do ar (`onerror`): nos dois casos
    // reabre depois de um tempo, para um job iniciado depois (ou o engine que voltou) aparecer.
    const open = () => {
      source = new EventSource(`${API}/sessions/${sessionId}/progress/stream`);
      source.addEventListener("progress", (e) => {
        failures = 0;
        setP(JSON.parse((e as MessageEvent<string>).data) as ProgressOut);
      });
      source.addEventListener("end", () => retry(IDLE_RETRY_MS));
      source.onerror = () => {
        failures += 1;
        retry(Math.min(MAX_RETRY_MS, 1000 * 2 ** failures));
      };
    };
    const retry = (delay: number) => {
      source?.close();
      if (alive) timer = setTimeout(open, delay);
    };

    open();
    return () => {
      alive = false;
      clearTimeout(timer);
      source?.close();
    };
  }, [sessionId]);

  if (!p || p.total === 0) return null;
  return (
    <small>
      <progress value={p.done} max={p.total} />{" "}
      {p.done}/{p.total} etapas
      {p.running > 0 && p.current ? ` · ${p.current}` : ""}
      {p.failed > 0 ? ` · ${p.failed} com falha` : ""}
    </small>
  );
}
