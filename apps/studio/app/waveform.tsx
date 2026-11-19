import type { SegmentOut, WaveformOut } from "@cronista/contracts";

const WAVE_H = 80;
const FLOOR_DB = -60;

export default function Waveform({
  wave,
  segments,
  onSeek,
}: {
  wave: WaveformOut;
  segments: SegmentOut[];
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
