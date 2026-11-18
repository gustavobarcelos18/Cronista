"""Benchmark de visão (3B/3C): estado de tela por VLM, leitura de HUD por OCR/VLM e efeito da resolução.

Gabarito: `visual-benchmark.json` (fora do git), com a classe de cada quadro amostrado a cada 90 s e o texto
do HUD lido no master em 1080p. Tudo roda sobre os mesmos quadros em três resoluções (proxy 360p, master em
720p e em 1080p). Os números são indícios: 23 telas e 12 leituras de HUD de um jogo só.

⚠️ Modelos e pacotes foram escritos de memória e rodam só aqui; cada candidato que falhar vira uma
linha "falhou" sem derrubar os outros.
"""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cronista.config import Settings
from cronista.media.ffmpeg import ffmpeg_cmd
from cronista.video.bench import free_gpu

SCREEN_LABELS = ("gameplay", "menu", "dialogue")
SCREEN_PROMPT = (
    "This is a screenshot from a video game. Classify the screen as exactly one of: "
    "gameplay (the 3D world with the normal HUD), menu (a full-screen or large menu, inventory, map or "
    "settings window), dialogue (a text box with a conversation over the scene). Answer with one word only."
)
OCR_PROMPT = "Read all the text in this image. Output only the text, on a single line."
RESOLUTIONS = (360, 720, 1080)
SAMPLE_EVERY_S = 90

VLM_CANDIDATES: dict[str, tuple[str, bool]] = {
    "qwen25vl-3b": ("Qwen/Qwen2.5-VL-3B-Instruct", False),
    "qwen25vl-7b-4bit": ("Qwen/Qwen2.5-VL-7B-Instruct", True),
    "qwen3vl-4b": ("Qwen/Qwen3-VL-4B-Instruct", False),
    "qwen3vl-8b-4bit": ("Qwen/Qwen3-VL-8B-Instruct", True),
}
"""nome curto -> (checkpoint, quantizar em 4 bits). Nomes de checkpoint de memória: conferir."""


@dataclass
class VisionRow:
    task: str  # tela | hud
    candidate: str
    resolution: str
    items: int
    seconds_per_item: float
    vram_peak_mib: int | None
    accuracy: float | None = None  # tela: acerto; hud: fração com CER <= 0,15
    cer: float | None = None  # hud: erro médio de caracteres
    day_time_ok: float | None = None  # hud: fração em que "Day N, HH:MM" saiu certo
    invalid: int = 0  # tela: respostas fora das classes
    per_class: dict[str, float] = field(default_factory=dict)
    note: str = ""


@dataclass
class Truth:
    screens: dict[int, str]
    hud: dict[int, str]
    hud_region: tuple[int, int, int, int]


def load_truth(path: Path) -> Truth:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Truth(
        screens={int(k): v for k, v in raw["screens"].items()},
        hud={int(k): v for k, v in raw["hud"].items()},
        hud_region=tuple(raw["hud_region"]),
    )


def extract_frames(settings: Settings, video: Path, height: int, out_dir: Path) -> dict[int, Path]:
    """Um quadro a cada 90 s, na altura pedida. O quadro `k` (a partir de 1) é o `k`-ésimo do filtro `fps`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "f%02d.png"
    cmd = ffmpeg_cmd(
        settings,
        ["-i", str(video), "-vf", f"fps=1/{SAMPLE_EVERY_S},scale=-2:{height}:flags=lanczos", str(pattern)],
    )
    subprocess.run(cmd, check=True, timeout=1800)
    return {int(p.stem[1:]): p for p in sorted(out_dir.glob("f*.png"))}


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\-]", "", text.lower())


def cer(truth: str, heard: str) -> float:
    t = normalize(truth)
    return levenshtein(t, normalize(heard)) / max(len(t), 1)


DAY_TIME = re.compile(r"day\s*(\d+)\D{0,4}?(\d{1,2})\s*[:.;]\s*(\d{2})", re.IGNORECASE)


def day_time(text: str) -> tuple[int, int, int] | None:
    match = DAY_TIME.search(text)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def parse_screen(answer: str) -> str | None:
    lowered = answer.lower()
    found = [(lowered.find(label), label) for label in SCREEN_LABELS if label in lowered]
    return min(found)[1] if found else None


def screen_metrics(truth: dict[int, str], answers: dict[int, str]) -> tuple[float, int, dict[str, float]]:
    right = {label: [0, 0] for label in SCREEN_LABELS}
    invalid = 0
    for k, label in truth.items():
        guess = parse_screen(answers.get(k, ""))
        invalid += guess is None
        right[label][1] += 1
        right[label][0] += guess == label
    hits = sum(r[0] for r in right.values())
    total = sum(r[1] for r in right.values())
    return hits / total if total else 0.0, invalid, {c: r[0] / r[1] for c, r in right.items() if r[1]}


def hud_metrics(truth: dict[int, str], answers: dict[int, str]) -> tuple[float, float, float]:
    errors = [cer(text, answers.get(k, "")) for k, text in truth.items()]
    ok = [
        day_time(answers.get(k, "")) == day_time(text) and day_time(text) is not None
        for k, text in truth.items()
    ]
    return (
        sum(e <= 0.15 for e in errors) / len(errors),
        sum(errors) / len(errors),
        sum(ok) / len(ok),
    )


def crop_hud(path: Path, region: tuple[int, int, int, int], height: int) -> Any:
    """Recorte da região do HUD (definida em 1080p) numa imagem na altura `height`."""
    pil: Any = importlib.import_module("PIL.Image")
    image = pil.open(path).convert("RGB")
    scale = height / 1080
    x, y, w, h = (round(v * scale) for v in region)
    return image.crop((x, y, x + w, y + h))


class VlmRunner:
    def __init__(self, model_id: str, quant4: bool) -> None:
        transformers: Any = importlib.import_module("transformers")
        torch: Any = importlib.import_module("torch")
        kwargs: dict[str, Any] = {"device_map": {"": 0}}
        if quant4:
            kwargs["quantization_config"] = transformers.BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_quant_type="nf4"
            )
        else:
            kwargs["dtype"] = torch.bfloat16
        self.torch = torch
        self.processor = transformers.AutoProcessor.from_pretrained(model_id)
        self.model = transformers.AutoModelForImageTextToText.from_pretrained(model_id, **kwargs).eval()

    def ask(self, image: Any, prompt: str, max_new_tokens: int = 24) -> str:
        messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        text = self.processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = self.processor(text=[text], images=[image], return_tensors="pt").to(self.model.device)
        with self.torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        new = out[:, inputs["input_ids"].shape[1] :]
        return str(self.processor.batch_decode(new, skip_special_tokens=True)[0]).strip()


class RapidOcrRunner:
    def __init__(self) -> None:
        try:
            module: Any = importlib.import_module("rapidocr")
            self.engine = module.RapidOCR()
            self.new_api = True
        except ImportError:
            module = importlib.import_module("rapidocr_onnxruntime")
            self.engine = module.RapidOCR()
            self.new_api = False

    def read(self, image: Any) -> str:
        import numpy as np

        array = np.asarray(image)[:, :, ::-1]  # RGB -> BGR
        result = self.engine(array)
        if self.new_api:
            texts = getattr(result, "txts", None) or ()
            return " ".join(texts)
        found, _ = result if isinstance(result, tuple) else (result, None)
        return " ".join(item[1] for item in (found or []))


def _timed(fn: Callable[[], dict[int, str]], count: int) -> tuple[dict[int, str], float, int | None]:
    t0 = time.monotonic()
    answers = fn()
    wall = time.monotonic() - t0
    torch: Any = importlib.import_module("torch")
    peak_mib = int(torch.cuda.max_memory_allocated() / 2**20)
    return answers, wall / max(count, 1), peak_mib


def run_vlm(
    name: str,
    truth: Truth,
    frames: dict[int, dict[int, Path]],
    progress: Callable[[], None],
    rows: list[VisionRow],
) -> None:
    model_id, quant4 = VLM_CANDIDATES[name]
    pil: Any = importlib.import_module("PIL.Image")
    free_gpu()
    torch: Any = importlib.import_module("torch")
    torch.cuda.reset_peak_memory_stats()  # pico alocado pelo PyTorch, sem depender do que veio antes
    runner = VlmRunner(model_id, quant4)
    try:
        for height in (360, 720):

            def screens(height: int = height) -> dict[int, str]:
                return {
                    k: runner.ask(pil.open(frames[height][k]).convert("RGB"), SCREEN_PROMPT)
                    for k in truth.screens
                }

            answers, per, vram = _timed(screens, len(truth.screens))
            acc, invalid, per_class = screen_metrics(truth.screens, answers)
            rows.append(
                VisionRow("tela", name, f"{height}p", len(truth.screens), round(per, 2), vram,
                          accuracy=round(acc, 3), invalid=invalid,
                          per_class={k: round(v, 2) for k, v in per_class.items()})
            )  # fmt: skip
            progress()
        for height in RESOLUTIONS:

            def hud(height: int = height) -> dict[int, str]:
                return {
                    k: runner.ask(crop_hud(frames[height][k], truth.hud_region, height), OCR_PROMPT, 48)
                    for k in truth.hud
                }

            answers, per, vram = _timed(hud, len(truth.hud))
            ok, mean_cer, day_ok = hud_metrics(truth.hud, answers)
            rows.append(
                VisionRow("hud", name, f"{height}p", len(truth.hud), round(per, 2), vram,
                          accuracy=round(ok, 3), cer=round(mean_cer, 3), day_time_ok=round(day_ok, 3))
            )  # fmt: skip
            progress()
    finally:
        runner.model = None  # solta os pesos antes do próximo candidato
        runner.processor = None
        free_gpu()


def run_rapidocr(
    truth: Truth, frames: dict[int, dict[int, Path]], progress: Callable[[], None], rows: list[VisionRow]
) -> None:
    runner = RapidOcrRunner()
    for height in RESOLUTIONS:

        def hud(height: int = height) -> dict[int, str]:
            return {k: runner.read(crop_hud(frames[height][k], truth.hud_region, height)) for k in truth.hud}

        answers, per, vram = _timed(hud, len(truth.hud))
        ok, mean_cer, day_ok = hud_metrics(truth.hud, answers)
        rows.append(
            VisionRow("hud", "rapidocr", f"{height}p", len(truth.hud), round(per, 3), vram,
                      accuracy=round(ok, 3), cer=round(mean_cer, 3), day_time_ok=round(day_ok, 3))
        )  # fmt: skip
        progress()


def decode_speed(settings: Settings, master: Path, proxy: Path, seconds: int = 120) -> list[dict[str, Any]]:
    """Segundos de vídeo decodificados por segundo de relógio, a 1 quadro/s, no proxy e no master."""
    cases: list[tuple[str, Path, list[str], str]] = [
        ("proxy 360p (CPU)", proxy, [], "fps=1"),
        ("master 720p (CPU)", master, [], "fps=1,scale=-2:720"),
        ("master 1080p (CPU)", master, [], "fps=1"),
        ("master 720p (NVDEC)", master, ["-hwaccel", "cuda"], "fps=1,scale=-2:720"),
        ("master 1080p (NVDEC)", master, ["-hwaccel", "cuda"], "fps=1"),
    ]
    out: list[dict[str, Any]] = []
    for label, path, pre, vf in cases:
        cmd = ffmpeg_cmd(
            settings,
            [*pre, "-t", str(seconds), "-i", str(path), "-an", "-vf", vf, "-f", "null", "-"],
            overwrite=False,
        )
        t0 = time.monotonic()
        proc = subprocess.run(cmd, capture_output=True, check=False, timeout=900)
        wall = time.monotonic() - t0
        out.append(
            {"caso": label, "video_s": seconds, "wall_s": round(wall, 1),
             "x_tempo_real": round(seconds / wall, 1) if proc.returncode == 0 and wall else 0.0,
             "ok": proc.returncode == 0}
        )  # fmt: skip
    return out


def _f(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def render_table(rows: list[VisionRow]) -> str:
    head = f"{'tarefa':<7}{'candidato':<20}{'res':<7}{'s/item':>8}{'VRAM':>7}{'acerto':>8}{'CER':>7}"
    head += f"{'dia/hora':>10}"
    lines = [head, "-" * len(head)]
    for r in rows:
        if r.note.startswith("falhou"):
            lines.append(f"{r.task:<7}{r.candidate:<20}{r.resolution:<7}{r.note}")
            continue
        lines.append(
            f"{r.task:<7}{r.candidate:<20}{r.resolution:<7}{r.seconds_per_item:>8.2f}"
            f"{r.vram_peak_mib if r.vram_peak_mib is not None else '?':>7}"
            f"{_f(r.accuracy):>8}{_f(r.cer):>7}{_f(r.day_time_ok):>10}"
        )
    return "\n".join(lines)


def write_json(path: Path, rows: list[VisionRow], extra: dict[str, Any] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"rows": [asdict(r) for r in rows], **(extra or {})}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_vision_bench(
    settings: Settings,
    master: Path,
    proxy: Path,
    truth: Truth,
    vlms: list[str],
    ocr: bool,
    work: Path,
    out: Path,
) -> list[VisionRow]:
    rows: list[VisionRow] = []
    extra: dict[str, Any] = {}
    frames: dict[int, dict[int, Path]] = {
        360: extract_frames(settings, proxy, 360, work / "360"),
        720: extract_frames(settings, master, 720, work / "720"),
        1080: extract_frames(settings, master, 1080, work / "1080"),
    }

    def save() -> None:
        write_json(out, rows, extra)

    if ocr:
        try:
            run_rapidocr(truth, frames, save, rows)
        except Exception as exc:  # pacote ausente, API diferente
            rows.append(VisionRow("hud", "rapidocr", "-", 0, 0.0, None, note=f"falhou: {exc}"[:300]))
            save()
    for name in vlms:
        try:
            run_vlm(name, truth, frames, save, rows)
        except Exception as exc:  # download recusado, VRAM estourada, bitsandbytes ausente
            rows.append(VisionRow("tela", name, "-", 0, 0.0, None, note=f"falhou: {exc}"[:300]))
            save()
    extra["decodificacao"] = decode_speed(settings, master, proxy)
    save()
    return rows
