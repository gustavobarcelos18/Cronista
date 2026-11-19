"""Teste de instalação de CUDA (1C, tarefa 4; plano mestre, seção 5.2): o CTranslate2 (faster-whisper) e o
PyTorch convivem no mesmo ambiente na RTX 3060? Não mede desempenho de modelo: isso é da Fase 2.

Rodar num ambiente descartável, sem tocar nas dependências do projeto (uv baixa tudo para um ambiente temporário):

    uv run --python 3.12 --index https://download.pytorch.org/whl/cu128 `
        --with torch --with faster-whisper --with numpy python integrations/cuda/check_cuda.py

Cada ordem de importação roda num processo próprio (a ordem muda quais DLLs do cuBLAS/cuDNN o Windows acha primeiro):
  A) torch antes do ctranslate2   B) ctranslate2 antes do torch
Sai com código 0 só se as duas ordens passarem. Escreve um resumo em JSON no fim, para colar no registro da 1C.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

PROBE = r"""
import json, sys, time
order = sys.argv[1]
out = {"order": order}
try:
    if order == "torch_first":
        import torch
        import ctranslate2
    else:
        import ctranslate2
        import torch
    out["torch"] = torch.__version__
    out["torch_cuda_build"] = torch.version.cuda
    out["torch_cuda_available"] = bool(torch.cuda.is_available())
    out["cudnn"] = torch.backends.cudnn.version()
    out["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    out["ctranslate2"] = ctranslate2.__version__
    out["ct2_cuda_devices"] = ctranslate2.get_cuda_device_count()
    out["ct2_compute_types"] = sorted(ctranslate2.get_supported_compute_types("cuda"))
    # Uma operação de verdade em cada biblioteca (convolução usa cuDNN; o Whisper usa cuBLAS no CTranslate2).
    x = torch.randn(1, 3, 64, 64, device="cuda", dtype=torch.float16)
    conv = torch.nn.Conv2d(3, 8, 3).cuda().half()
    out["torch_conv_ok"] = bool(conv(x).isfinite().all().item())
    from faster_whisper import WhisperModel
    import numpy as np
    t0 = time.monotonic()
    model = WhisperModel("tiny", device="cuda", compute_type="float16")
    segments, _ = model.transcribe(np.zeros(16000 * 3, dtype=np.float32))
    list(segments)
    out["whisper_tiny_cuda_ok"] = True
    out["whisper_tiny_seconds"] = round(time.monotonic() - t0, 1)
    out["vram_used_mib"] = round(torch.cuda.mem_get_info()[1] / 2**20 - torch.cuda.mem_get_info()[0] / 2**20)
    out["ok"] = bool(out["torch_cuda_available"] and out["ct2_cuda_devices"] > 0 and out["torch_conv_ok"])
except BaseException as exc:  # o ponto do teste é registrar a falha, qualquer que seja
    out["ok"] = False
    out["error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(out))
"""


def run_probe(order: str) -> dict:
    t0 = time.monotonic()
    proc = subprocess.run([sys.executable, "-c", PROBE, order], capture_output=True, text=True, check=False)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if not lines:
        return {
            "order": order,
            "ok": False,
            "error": f"sem saída (código {proc.returncode}): {proc.stderr[-600:]}",
        }
    result = json.loads(lines[-1])
    result["seconds"] = round(time.monotonic() - t0, 1)
    return result


def main() -> int:
    results = [run_probe("torch_first"), run_probe("ctranslate2_first")]
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
