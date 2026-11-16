# /// script
# requires-python = ">=3.12"
# dependencies = ["hidapi>=0.14", "mido>=1.3", "python-rtmidi>=1.5"]
# ///
"""Spike da FIFINE SC3 (plano mestre, seção 4): a mesa manda algum evento ao PC quando o criador aperta um botão?

Ordem do plano: 1) HID/MIDI; 2) marcador por áudio; 3) F13–F24/mouse/macropad. Este script cobre o passo 1:
lista os dispositivos HID e MIDI e imprime, com carimbo de tempo, tudo o que chegar enquanto estiver rodando.
Não depende do engine (roda com `uv run integrations/fifine/spike_fifine.py`); não altera nada na mesa.

Uso:
    uv run integrations/fifine/spike_fifine.py list              # só lista o que encontrou
    uv run integrations/fifine/spike_fifine.py listen [--vid 3142] [--seconds 120]
        Aperte cada botão/pad/botão giratório da mesa, um de cada vez, anotando qual apertou.
"""

from __future__ import annotations

import argparse
import threading
import time

import hid  # type: ignore[import-not-found]

FIFINE_VID = 0x3142  # `VID_3142&PID_0C33` no Gerenciador de Dispositivos (SC3), conferido em 2026-11-16


def stamp(t0: float) -> str:
    return f"{time.monotonic() - t0:8.3f}s"


def list_hid(vid: int | None) -> list[dict]:
    found = [d for d in hid.enumerate() if vid is None or d["vendor_id"] == vid]
    for d in found:
        print(
            f"HID  vid={d['vendor_id']:04x} pid={d['product_id']:04x} iface={d['interface_number']} "
            f"usage_page={d['usage_page']:#06x} usage={d['usage']:#04x} "
            f"{d['manufacturer_string']!r} {d['product_string']!r}"
        )
    if not found:
        print("HID  nenhum dispositivo encontrado" + (f" com vid={vid:04x}" if vid else ""))
    return found


def list_midi() -> None:
    try:
        import mido

        inputs = mido.get_input_names()
    except Exception as exc:  # noqa: BLE001 - spike: qualquer falha vira informação
        print(f"MIDI indisponível: {exc}")
        return
    print("MIDI entradas:", inputs or "nenhuma")


def listen_hid(info: dict, stop: threading.Event, t0: float) -> None:
    label = f"hid iface={info['interface_number']} up={info['usage_page']:#06x}/{info['usage']:#04x}"
    dev = hid.device()
    try:
        dev.open_path(info["path"])
    except OSError as exc:
        print(f"[{label}] não abriu ({exc}); o Windows reserva teclado/mouse, tente as outras interfaces")
        return
    dev.set_nonblocking(True)
    print(f"[{label}] escutando")
    last: list[int] | None = None
    while not stop.is_set():
        data = dev.read(64)
        if data and data != last:
            print(f"{stamp(t0)} [{label}] {bytes(data).hex(' ')}")
        if data:
            last = data
        else:
            time.sleep(0.005)
    dev.close()


def listen_midi(stop: threading.Event, t0: float) -> None:
    try:
        import mido

        names = mido.get_input_names()
    except Exception:  # noqa: BLE001
        return
    ports = [mido.open_input(n) for n in names]
    for port in ports:
        print(f"[midi {port.name}] escutando")
    while not stop.is_set():
        for port in ports:
            for msg in port.iter_pending():
                print(f"{stamp(t0)} [midi {port.name}] {msg}")
        time.sleep(0.005)
    for port in ports:
        port.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["list", "listen"])
    parser.add_argument("--vid", type=lambda s: int(s, 16), default=FIFINE_VID, help="vendor id em hex")
    parser.add_argument("--seconds", type=float, default=120.0)
    args = parser.parse_args()

    infos = list_hid(args.vid)
    list_midi()
    if args.mode == "list":
        return

    stop = threading.Event()
    t0 = time.monotonic()
    threads = [threading.Thread(target=listen_hid, args=(i, stop, t0), daemon=True) for i in infos]
    threads.append(threading.Thread(target=listen_midi, args=(stop, t0), daemon=True))
    for t in threads:
        t.start()
    print(f"\nAperte os botões da mesa agora ({args.seconds:.0f} s, Ctrl+C encerra)...")
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    stop.set()
    for t in threads:
        t.join(timeout=1)


if __name__ == "__main__":
    main()
