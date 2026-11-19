import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Exportar from "../app/exportar";

afterEach(() => vi.unstubAllGlobals());

const idle = () => Promise.resolve(new Response(JSON.stringify({ state: "idle" }), { status: 200 }));

describe("Exportar", () => {
  it("no vídeo da série consulta a exportação com serie=true na sessão âncora", async () => {
    const fetchMock = vi.fn().mockImplementation(idle);
    vi.stubGlobal("fetch", fetchMock);
    render(<Exportar sessionId={7} serie />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls[0][0])).toContain("/sessions/7/export?serie=true");
    expect(screen.getByText(/vídeo da série/)).toBeInTheDocument();
  });

  it("por sessão não manda o parâmetro", async () => {
    const fetchMock = vi.fn().mockImplementation(idle);
    vi.stubGlobal("fetch", fetchMock);
    render(<Exportar sessionId={7} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/sessions\/7\/export$/);
  });
});
