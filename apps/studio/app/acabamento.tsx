"use client";

import type {
  EffectSettingOut,
  FinishDecisionIn,
  FinishingOut,
  FinishItemOut,
} from "@cronista/contracts";
import { useCallback, useEffect, useState } from "react";
import { API } from "../lib/api";

const MODES = [
  ["sugerir", "Só sugerir (marcador)"],
  ["editavel", "Editável no Resolve"],
  ["renderizado", "Renderizado pelo app"],
] as const;

const SOURCES: Record<EffectSettingOut["source"], string> = {
  padrao: "padrão",
  serie: "da série",
  criador: "ajuste seu",
};

function clock(seconds: number): string {
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function EffectRow({
  effect,
  onSave,
}: {
  effect: EffectSettingOut;
  onSave: (next: EffectSettingOut) => Promise<void>;
}) {
  const [mode, setMode] = useState(effect.mode);
  const [perMinute, setPerMinute] = useState(String(effect.max_per_minute));
  const [minScore, setMinScore] = useState(String(effect.min_score));
  const perMinuteValue = perMinute.trim() === "" ? NaN : Number(perMinute);
  const minScoreValue = minScore.trim() === "" ? NaN : Number(minScore);
  const valid =
    perMinuteValue >= 0 && perMinuteValue <= 60 && minScoreValue >= 0 && minScoreValue <= 1;
  const changed =
    mode !== effect.mode ||
    perMinuteValue !== effect.max_per_minute ||
    minScoreValue !== effect.min_score;

  return (
    <tr>
      <th scope="row">{effect.kind}</th>
      <td>
        <select
          aria-label={`Modo de ${effect.kind}`}
          value={mode}
          onChange={(e) => setMode(e.target.value as EffectSettingOut["mode"])}
        >
          {MODES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          aria-label={`Máximo por minuto de ${effect.kind}`}
          type="number"
          min={0}
          max={60}
          step={0.1}
          value={perMinute}
          onChange={(e) => setPerMinute(e.target.value)}
        />
      </td>
      <td>
        <input
          aria-label={`Nota mínima de ${effect.kind}`}
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={minScore}
          onChange={(e) => setMinScore(e.target.value)}
        />
      </td>
      <td>
        <small>{SOURCES[effect.source]}</small>{" "}
        <button
          disabled={!changed || !valid}
          title={valid ? undefined : "Máximo de 0 a 60 por minuto e nota de 0 a 1"}
          onClick={() =>
            void onSave({
              ...effect,
              mode,
              max_per_minute: perMinuteValue,
              min_score: minScoreValue,
            })
          }
        >
          Salvar
        </button>
      </td>
    </tr>
  );
}

type Result = { data?: FinishingOut; error?: string };

/** Acabamento (8E): política por efeito e prévia do que entra em cada momento. Tudo é inserção; nada se apaga. */
export default function Acabamento({
  sessionId,
  projectId,
}: {
  sessionId: number;
  projectId: number;
}) {
  const [data, setData] = useState<FinishingOut | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const fetchPreview = useCallback(async (): Promise<Result> => {
    try {
      const res = await fetch(`${API}/sessions/${sessionId}/finishing`);
      if (res.ok) return { data: (await res.json()) as FinishingOut };
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      return { error: body.detail ?? `erro ${res.status}` };
    } catch {
      return { error: "Engine fora do ar." };
    }
  }, [sessionId]);

  const show = useCallback((r: Result) => {
    setData(r.data ?? null);
    setMessage(r.error ?? "");
  }, []);

  useEffect(() => {
    let alive = true;
    void fetchPreview().then((r) => alive && show(r));
    return () => void (alive = false);
  }, [fetchPreview, show]);

  async function load() {
    setLoading(true);
    show(await fetchPreview());
    setLoading(false);
  }

  async function send(url: string, method: "PUT" | "POST", body: unknown, failure: string) {
    try {
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) await load();
      else setMessage(`${failure} (${res.status}).`);
    } catch {
      setMessage("Engine fora do ar.");
    }
  }

  function saveEffect(next: EffectSettingOut) {
    return send(
      `${API}/projects/${projectId}/finishing/effects/${next.kind}`,
      "PUT",
      { mode: next.mode, max_per_minute: next.max_per_minute, min_score: next.min_score },
      "Não salvou",
    );
  }

  function decide(item: FinishItemOut, decision: FinishDecisionIn["decision"]) {
    return send(
      `${API}/sessions/${sessionId}/finishing/items/${item.id}/decision`,
      "POST",
      { decision },
      "Não registrou",
    );
  }

  if (!data) {
    return (
      <section aria-label="Acabamento">
        <h3>Acabamento</h3>
        <p>{message || "Carregando…"}</p>
        {message && <button onClick={() => void load()}>Tentar de novo</button>}
      </section>
    );
  }
  if (!data.enabled) {
    return (
      <section aria-label="Acabamento">
        <h3>Acabamento</h3>
        <p>Brand kit não encontrado: rode `cronista brand-check` e confira `packages/brand-kit/`.</p>
      </section>
    );
  }

  const effects = data.effects ?? [];
  const items = data.items ?? [];
  return (
    <section aria-label="Acabamento">
      <h3>Acabamento{data.series && ` · série ${data.series}`}</h3>
      <p>
        <small>
          Teto de {data.max_effects_per_minute} efeitos aplicados por minuto.
          {!data.has_library && " Sem biblioteca pessoal: não há SFX nem música."}
        </small>
      </p>
      <table>
        <thead>
          <tr>
            <th>Efeito</th>
            <th>Modo</th>
            <th>Máx./min</th>
            <th>Nota mín.</th>
            <th>Origem</th>
          </tr>
        </thead>
        <tbody>
          {effects.map((e) => (
            <EffectRow
              key={`${e.kind}-${e.mode}-${e.max_per_minute}-${e.min_score}`}
              effect={e}
              onSave={saveEffect}
            />
          ))}
        </tbody>
      </table>

      <h4>
        Prévia ({items.length} efeitos){" "}
        <button disabled={loading} onClick={() => void load()}>
          {loading ? "Atualizando…" : "Atualizar"}
        </button>
      </h4>
      <ul>
        {items.map((i) => (
          <li key={i.id} aria-label={`${i.kind} em ${clock(i.start_s)}`}>
            <strong>{clock(i.start_s)}</strong> {i.kind} · {i.track} ·{" "}
            {i.effective_mode === null ? (
              <s>{i.mode}</s>
            ) : i.effective_mode !== i.mode ? (
              <>
                <s>{i.mode}</s> → {i.effective_mode}
              </>
            ) : (
              i.mode
            )}{" "}
            <small>
              (intensidade {i.intensity.toFixed(2)}; {i.reason}
              {i.asset_id ? `; ${i.asset_id}` : ""})
            </small>{" "}
            {i.mode === "sugerir" && i.decision !== "aceito" && (
              <button onClick={() => void decide(i, "aceito")}>Aceitar</button>
            )}{" "}
            {i.effective_mode !== null && i.decision !== "removido" && (
              <button onClick={() => void decide(i, "removido")}>Tirar</button>
            )}{" "}
            {i.decision && <button onClick={() => void decide(i, "padrao")}>Voltar ao padrão</button>}
          </li>
        ))}
      </ul>
      <ul>
        {(data.warnings ?? []).map((w) => (
          <li key={w}>
            <small>{w}</small>
          </li>
        ))}
      </ul>
      <small>
        {message || "Aceitar põe a sugestão como editável; Tirar e Aceitar valem na próxima exportação."}
      </small>
    </section>
  );
}
