import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Ajuste from "../app/ajuste";

function montar() {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  render(<Ajuste start={10} end={20} onSubmit={onSubmit} onCancel={onCancel} />);
  const inicio = screen.getByLabelText(/Novo início/);
  const fim = screen.getByLabelText(/Novo fim/);
  return { onSubmit, onCancel, inicio, fim };
}

describe("Ajuste", () => {
  it("envia início e fim, aceitando vírgula decimal", () => {
    const { onSubmit, inicio, fim } = montar();
    fireEvent.change(inicio, { target: { value: "12,5" } });
    fireEvent.change(fim, { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar ajuste" }));
    expect(onSubmit).toHaveBeenCalledWith(12.5, 30);
  });

  it("campo vazio ou texto não vira 0: mostra o problema e não envia", () => {
    const { onSubmit, inicio } = montar();
    fireEvent.change(inicio, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar ajuste" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("números em segundos");
  });

  it("fim antes do início é recusado", () => {
    const { onSubmit, fim } = montar();
    fireEvent.change(fim, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar ajuste" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("depois do início");
  });

  it("cancelar não envia nada", () => {
    const { onSubmit, onCancel } = montar();
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(onCancel).toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
