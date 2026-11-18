"use client";

import type {
  PackagingOut,
  PublishOut,
  ShortDecisionIn,
  ShortOut,
  ThumbnailOut,
} from "@cronista/contracts";
import { useCallback, useEffect, useState } from "react";
import { API, errorOf } from "../lib/api";

const ORIGINS: Record<string, string> = {
  sugerido: "sugestão",
  editado: "sugestão editada",
  proprio: "texto seu",
};

type Result = { data?: PackagingOut; error?: string };

function TitleRow({
  n,
  text,
  reason,
  chosen,
  onPick,
}: {
  n: number;
  text: string;
  reason: string | null | undefined;
  chosen: boolean;
  onPick: (n: number, edited: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState(text);
  const trimmed = draft.trim();
  return (
    <li aria-label={`Sugestão ${n}`}>
      <input
        aria-label={`Texto da sugestão ${n}`}
        value={draft}
        maxLength={100}
        onChange={(e) => setDraft(e.target.value)}
        size={60}
      />{" "}
      <small>
        {trimmed.length}/70{trimmed.length > 70 && " (o YouTube corta acima de 70)"}
      </small>{" "}
      <button disabled={trimmed === ""} onClick={() => void onPick(n, trimmed)}>
        {chosen ? "Escolhido" : "Usar"}
      </button>
      {reason && (
        <>
          {" "}
          <small>({reason})</small>
        </>
      )}
    </li>
  );
}

function Thumbnail({
  sessionId,
  item,
  onPick,
}: {
  sessionId: number;
  item: ThumbnailOut;
  onPick: (variation: number) => Promise<void>;
}) {
  return (
    <figure style={{ display: "inline-block", margin: "0 12px 12px 0", maxWidth: 320 }}>
      {/* A thumbnail vem do engine local; o next/image não ajuda e exigiria configurar o domínio. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`${API}/sessions/${sessionId}/packaging/thumbnails/${encodeURIComponent(item.file_name)}`}
        alt={`Variação ${item.variation}${item.text ? `: ${item.text}` : ""}`}
        width={320}
        style={{ outline: item.chosen ? "3px solid currentColor" : undefined }}
      />
      <figcaption>
        Variação {item.variation}
        {item.text ? ` · ${item.text}` : ""}{" "}
        <button disabled={item.chosen} onClick={() => void onPick(item.variation)}>
          {item.chosen ? "Escolhida" : "Escolher"}
        </button>
      </figcaption>
    </figure>
  );
}

function ShortRow({
  sessionId,
  short,
  onDecide,
}: {
  sessionId: number;
  short: ShortOut;
  onDecide: (key: string, decision: ShortDecisionIn["decision"]) => Promise<void>;
}) {
  return (
    <li aria-label={`Short ${short.key}`} style={{ marginBottom: 12 }}>
      {short.has_clip ? (
        <video
          controls
          preload="metadata"
          height={240}
          src={`${API}/sessions/${sessionId}/packaging/shorts/${encodeURIComponent(short.key)}/video`}
        />
      ) : (
        <p>
          <small>Sem MP4: rode `cronista shorts-render`.</small>
        </p>
      )}
      <div>
        {short.duration_s.toFixed(1)} s · nota {short.score.toFixed(2)} · <em>{short.decision}</em>{" "}
        <small>({short.reason})</small>
      </div>
      <button
        disabled={!short.has_clip || short.decision === "aprovado"}
        onClick={() => void onDecide(short.key, "aprovado")}
      >
        Aprovar
      </button>
      <button disabled={short.decision === "rejeitado"} onClick={() => void onDecide(short.key, "rejeitado")}>
        Rejeitar
      </button>
      {short.decision !== "pendente" && (
        <button onClick={() => void onDecide(short.key, "padrao")}>Voltar a pendente</button>
      )}
    </li>
  );
}

/** Embalagem (9D): título, thumbnail e Shorts do vídeo. Toda escolha é inserção; nada se apaga. */
export default function Embalagem({ sessionId }: { sessionId: number }) {
  const [data, setData] = useState<PackagingOut | null>(null);
  const [message, setMessage] = useState("");
  const [custom, setCustom] = useState("");
  const [published, setPublished] = useState<PublishOut | null>(null);

  const fetchPanel = useCallback(async (): Promise<Result> => {
    try {
      const res = await fetch(`${API}/sessions/${sessionId}/packaging`);
      if (res.ok) return { data: (await res.json()) as PackagingOut };
      return { error: await errorOf(res, "erro") };
    } catch {
      return { error: "Engine fora do ar." };
    }
  }, [sessionId]);

  const show = useCallback((r: Result) => {
    if (r.data) setData(r.data);
    setMessage(r.error ?? "");
  }, []);

  useEffect(() => {
    let alive = true;
    void fetchPanel().then((r) => alive && show(r));
    return () => void (alive = false);
  }, [fetchPanel, show]);

  async function post(path: string, body: unknown, failure: string) {
    try {
      const res = await fetch(`${API}/sessions/${sessionId}/packaging${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        setPublished(null); // a pasta de publicação gerada antes ficou desatualizada
        return (await res.json()) as unknown;
      }
      setMessage(await errorOf(res, failure));
    } catch {
      setMessage("Engine fora do ar.");
    }
    return null;
  }

  async function mutate(path: string, body: unknown, failure: string) {
    const out = await post(path, body, failure);
    if (out) show({ data: out as PackagingOut });
    return out !== null;
  }

  async function pickTitle(n: number, edited: string) {
    const original = data?.title.suggestions?.find((s) => s.n === n)?.text;
    await mutate(
      "/title",
      edited === original ? { suggestion: n } : { suggestion: n, text: edited },
      "Não registrou o título",
    );
  }

  async function publish() {
    const out = await post("/publish", {}, "Não montou a pasta");
    if (out) {
      setPublished(out as PublishOut);
      setMessage("");
    }
  }

  if (!data) {
    return (
      <section aria-label="Embalagem">
        <h3>Embalagem</h3>
        <p>{message || "Carregando…"}</p>
        {message && <button onClick={() => void fetchPanel().then(show)}>Tentar de novo</button>}
      </section>
    );
  }

  const suggestions = data.title.suggestions ?? [];
  const thumbnails = data.thumbnails ?? [];
  const shorts = data.shorts ?? [];
  const missing = data.missing ?? [];
  const thumbTexts = data.title.thumbnail_texts ?? [];

  return (
    <section aria-label="Embalagem">
      <h3>Embalagem</h3>

      <h4>Título</h4>
      {data.title.chosen ? (
        <p>
          <strong>{data.title.chosen}</strong>{" "}
          <small>({data.title.origin ? ORIGINS[data.title.origin] : ""})</small>
        </p>
      ) : (
        <p>
          <small>Ainda sem título escolhido.</small>
        </p>
      )}
      {suggestions.length === 0 ? (
        <p>
          <small>
            Sem sugestões: rode `cronista titulos`, depois /titular no Claude Code e `cronista
            titulos-import`. Você também pode escrever o seu abaixo.
          </small>
        </p>
      ) : (
        <ul>
          {suggestions.map((s) => (
            <TitleRow
              key={`${s.n}-${s.text}`}
              n={s.n}
              text={s.text}
              reason={s.reason}
              chosen={data.title.chosen === s.text}
              onPick={pickTitle}
            />
          ))}
        </ul>
      )}
      <p>
        <input
          aria-label="Título seu"
          placeholder="Título seu"
          value={custom}
          maxLength={100}
          size={60}
          onChange={(e) => setCustom(e.target.value)}
        />{" "}
        <button
          disabled={custom.trim() === ""}
          onClick={() => {
            void mutate("/title", { text: custom.trim() }, "Não registrou o título").then((ok) => {
              if (ok) setCustom("");
            });
          }}
        >
          Usar o meu
        </button>
      </p>

      <h4>Thumbnail</h4>
      {thumbnails.length === 0 ? (
        <p>
          <small>
            Sem variações: rode `cronista thumbnails` (texto sugerido: {thumbTexts.join(" · ") || "nenhum"}).
          </small>
        </p>
      ) : (
        <div>
          {thumbnails.map((t) => (
            <Thumbnail
              key={t.file_name}
              sessionId={sessionId}
              item={t}
              onPick={async (variation) => {
                await mutate("/thumbnail", { variation }, "Não registrou a thumbnail");
              }}
            />
          ))}
        </div>
      )}

      <h4>
        Shorts ({data.approved_shorts} aprovados; o plano pede {data.min_shorts})
      </h4>
      {shorts.length === 0 ? (
        <p>
          <small>Sem Shorts: rode `cronista shorts-render`.</small>
        </p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0 }}>
          {shorts.map((s) => (
            <ShortRow
              key={s.key}
              sessionId={sessionId}
              short={s}
              onDecide={async (key, decision) => {
                await mutate(`/shorts/${encodeURIComponent(key)}/decision`, { decision }, "Não registrou");
              }}
            />
          ))}
        </ul>
      )}

      <h4>Pasta de publicação</h4>
      <p>
        <button onClick={() => void publish()}>Montar pasta de publicação</button>{" "}
        <small>
          Copia título, thumbnail e Shorts aprovados e escreve o LEIA-ME.md. O vídeo do Resolve entra com
          `cronista pacote-publicacao --video`.
        </small>
      </p>
      {missing.length > 0 && (
        <ul>
          {missing.map((m) => (
            <li key={m}>
              <small>Falta: {m}</small>
            </li>
          ))}
        </ul>
      )}
      {published && (
        <p>
          {published.directory} · {published.files.join(", ")}
          {published.missing.map((m) => (
            <span key={m}>
              <br />
              <small>Falta: {m}</small>
            </span>
          ))}
        </p>
      )}
      {message && <p role="alert">{message}</p>}
    </section>
  );
}
