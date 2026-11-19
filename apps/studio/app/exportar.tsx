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
  const running = status?.state === "running";

  useEffect(() => {
    let alive = true;
    const poll = () =>
      getJson<ExportStatus>(`/sessions/${sessionId}/export${query}`)
        .then((s) => alive && setStatus(s))
        .catch((e: Error) => alive && setStatus({ state: "error", message: e.message }));
    void poll();
    if (!running) return () => void (alive = false);
    const timer = setInterval(() => void poll(), 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [sessionId, query, running]);

  async function start() {
    try {
      setStatus(await send<ExportStatus>(`/sessions/${sessionId}/export${query}`));
    } catch (e) {
      // 409 = já há uma exportação rodando: o corpo traz o estado dela.
      if (e instanceof ApiError && e.status === 409 && e.body) setStatus(e.body as ExportStatus);
      else setStatus({ state: "error", message: e instanceof Error ? e.message : "erro ao exportar" });
    }
  }

  return (
    <section>
      <h2>Exportar para o Resolve{serie && " · vídeo da série"}</h2>
      <button disabled={running} onClick={() => void start()}>
        {running ? "Exportando…" : "Re-exportar montagem"}
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
