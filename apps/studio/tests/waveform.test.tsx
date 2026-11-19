import type { SegmentOut, WaveformOut } from "@cronista/contracts";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Waveform from "../app/waveform";

const wave = { duration_s: 100, game: [-10, -30, -80], mic: [-20, -60, 5] } as unknown as WaveformOut;
const segmento = (start_s: number, end_s: number, score: number) =>
  ({ start_s, end_s, score }) as unknown as SegmentOut;

describe("Waveform", () => {
  it("desenha uma barra por amostra de jogo e de microfone mais um retângulo por segmento", () => {
    const { container } = render(<Waveform wave={wave} segments={[segmento(0, 10, 0.9)]} onSeek={() => {}} />);
    expect(screen.getByRole("img")).toBeInTheDocument();
    expect(container.querySelectorAll("rect")).toHaveLength(1 + 3 + 3);
  });

  it("limita barras fora da faixa de -60 a 0 dB", () => {
    const { container } = render(<Waveform wave={wave} segments={[]} onSeek={() => {}} />);
    const alturas = [...container.querySelectorAll("rect")].map((r) => Number(r.getAttribute("height")));
    expect(Math.max(...alturas)).toBeLessThanOrEqual(40);
    expect(Math.min(...alturas)).toBeGreaterThanOrEqual(1);
  });

  it("clique converte a posição em segundos do arquivo", () => {
    const onSeek = vi.fn();
    render(<Waveform wave={wave} segments={[]} onSeek={onSeek} />);
    const svg = screen.getByRole("img");
    svg.getBoundingClientRect = () => ({ left: 0, width: 200 }) as DOMRect;
    fireEvent.click(svg, { clientX: 50 });
    expect(onSeek).toHaveBeenCalledWith(25);
  });
});
