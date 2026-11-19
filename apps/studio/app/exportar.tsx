"use client";

import type { ExportStatus } from "@cronista/contracts";
import { useEffect, useState } from "react";
import { ApiError, getJson, send } from "../lib/api";

export default function Exportar({
  sessionId,
  serie = false,
}: {
  sessionId: number;
  /** Vídeo da série: `sessionId` é a sessão âncora e a montagem cobre o projeto inteiro. */
  serie?: boolean;
}) {
  const query = serie ? "?serie=true" : "";
  const [status, setStatus] = useState<ExportStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const running = status?.state === "running";
  const initial = status === null;
  const path = `/sessions/${sessionId}/export${query}`;

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await getJson<ExportStatus>(path);
        if (!alive) return;
        setStatus(next);
        if (next.state === "running" && running) timer = setTimeout(poll, 2000);
      } catch (e) {
        if (alive) setStatus({ state: "error", message: e instanceof Error ? e.message : "Erro ao consultar a exportação." });
      }
    }
    if (running || initial) void poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [path, running, initial]);

  async function start() {
    setStarting(true);
    try {
      setStatus(await send<ExportStatus>(path));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setStatus({ state: "running" });
      else setStatus({ state: "error", message: e instanceof Error ? e.message : "erro ao exportar" });
    } finally {
      setStarting(false);
    }
  }

  return (
    <section>
      <h2>Exportar para o Resolve{serie && " · vídeo da série"}</h2>
      <button disabled={starting || running || !status} onClick={() => void start()}>
        {running ? "Exportando…" : starting ? "Iniciando…" : "Re-exportar montagem"}
      </button>{" "}
      <small>Usa as decisões e o roteiro atuais; o que não mudou é reaproveitado.</small>
      {status && status.state !== "idle" && status.state !== "running" && (
        <p role={status.state === "error" ? "alert" : undefined}>
          {status.message}
          {status.version != null && ` · versão ${status.version}`}
          {status.directory && ` · ${status.directory}`}
        </p>
      )}
      <ul>
        {[...(status?.problems ?? []), ...(status?.warnings ?? [])].map((w) => (
          <li key={w}>
            <small>{w}</small>
          </li>
        ))}
      </ul>
    </section>
  );
}
