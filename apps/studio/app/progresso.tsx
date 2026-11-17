"use client";

import type { ProgressOut } from "@cronista/contracts";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8000";

/** Progresso dos jobs da sessão por SSE; a conexão fecha sozinha quando não resta job ativo. */
export default function Progresso({ sessionId }: { sessionId: number }) {
  const [p, setP] = useState<ProgressOut | null>(null);

  useEffect(() => {
    const source = new EventSource(`${API}/sessions/${sessionId}/progress/stream`);
    source.addEventListener("progress", (e) => setP(JSON.parse((e as MessageEvent<string>).data) as ProgressOut));
    source.addEventListener("end", () => source.close());
    source.onerror = () => source.close();
    return () => source.close();
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
