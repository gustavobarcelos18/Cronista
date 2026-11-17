"""`GpuGate` reais: OBS gravando, jogo em tela cheia e (opcional) carga da GPU.

Cada gate responde "a GPU está livre para mim?" e, se não, por quê (`reason()`). Qualquer sinal que não
consiga ser lido (OBS fechado, sem `nvidia-smi`, sem Windows) conta como "não ocupado": o processamento só é
adiado por um sinal que existe de fato, nunca por dúvida.

Limite honesto: o gate é consultado **antes** de cada etapa que vai rodar e entre os blocos em que a etapa
chama `ctx.wait_for_gpu()`. Uma etapa que não faz isso só pausa na próxima fronteira (plano mestre, 4.1).
Entre blocos vale `is_free_while_working()`, que ignora sinais causados pelo próprio processamento.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

from cronista.config import Settings
from cronista.logging_setup import log_event
from cronista.pipeline.gpu import AlwaysFreeGate, GpuGate, gate_reason, is_free_now
from cronista.recorder.core import system_clock
from cronista.recorder.obs import SimpleObsLink
from cronista.recorder.ports import ObsError

# `SHQueryUserNotificationState` (shell32, Windows). ⚠️ valores de memória: conferir no PC de casa.
QUNS_BUSY = 2  # aplicativo em tela cheia (ou modo de apresentação)
QUNS_RUNNING_D3D_FULL_SCREEN = 3  # Direct3D em tela cheia exclusiva
QUNS_PRESENTATION_MODE = 4
FULLSCREEN_STATES = {QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE}

OBS_PROBE_TIMEOUT_S = 2.0
PORT_CHECK_TIMEOUT_S = 0.25  # localhost responde em ms; recusar leva ~2 s por endereço no Windows
CACHE_TTL_S = 3.0  # menor que `gpu_poll_seconds` (5 s): esperar por um gate ocupado sempre reconsulta


class ObsRecordingGate:
    """Ocupada enquanto o OBS grava (`GetRecordStatus` pelo obs-websocket). OBS fechado = livre.

    Precisa do servidor WebSocket do OBS ligado (já exigido pelo gravador de marcadores). Cada consulta abre e
    fecha uma conexão curta, em uma thread própria, para funcionar mesmo dentro de um laço asyncio.
    """

    def __init__(
        self,
        host: str,
        port: int,
        password: str | None,
        probe: Callable[[], bool | None] | None = None,
    ) -> None:
        self._host, self._port, self._password = host, port, password
        self._probe = probe or self._probe_obs
        self._recording = False

    async def _status(self) -> bool:
        link = SimpleObsLink(
            self._host, self._port, self._password, system_clock, identify_timeout_s=OBS_PROBE_TIMEOUT_S
        )
        await link.connect()
        try:
            return (await link.record_status()).active
        finally:
            await link.close()

    def _port_open(self) -> bool:
        try:
            socket.create_connection((self._host, self._port), timeout=PORT_CHECK_TIMEOUT_S).close()
        except OSError:
            return False
        return True

    def _probe_obs(self) -> bool | None:
        """True/False = estado da gravação; None = OBS inacessível."""
        if not self._port_open():  # o Windows leva ~2 s por endereço para recusar uma conexão; isto é rápido
            return None
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(self._status())).result(
                    timeout=OBS_PROBE_TIMEOUT_S * 3
                )
        except (ObsError, OSError, TimeoutError) as exc:
            # A porta responde mas a conexão falha (senha errada, WebSocket sem autenticação esperada):
            # o gate fica cego para a gravação, então isso precisa aparecer no log.
            log_event("gate_obs_recusou_conexao", level=logging.WARNING, erro=str(exc))
            return None

    def is_free(self) -> bool:
        self._recording = self._probe() is True
        return not self._recording

    def reason(self) -> str | None:
        return "OBS gravando" if self._recording else None


def _shell_notification_state() -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes

    state = ctypes.c_int()
    result = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    return int(state.value) if result == 0 else None


class FullscreenGate:
    """Ocupada com um aplicativo em tela cheia (o jogo). Só no Windows.

    ⚠️ Jogo em janela sem borda pode não ser detectado como tela cheia: para esse caso existe `GpuLoadGate`.
    """

    def __init__(self, query: Callable[[], int | None] = _shell_notification_state) -> None:
        self._query = query
        self._state: int | None = None

    def is_free(self) -> bool:
        self._state = self._query()
        return self._state not in FULLSCREEN_STATES

    def reason(self) -> str | None:
        return (
            f"aplicativo em tela cheia (estado {self._state})" if self._state in FULLSCREEN_STATES else None
        )


def query_nvidia_smi(field: str, executable: str = "nvidia-smi") -> list[int]:
    """Um campo numérico do `nvidia-smi --query-gpu` (um valor por GPU). Vazio se não der para ler."""
    cmd = [executable, f"--query-gpu={field}", "--format=csv,noheader,nounits"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(line) for line in out.split() if line.strip().isdigit()]


def _nvidia_smi_utilization(executable: str = "nvidia-smi") -> int | None:
    values = query_nvidia_smi("utilization.gpu", executable)
    return max(values) if values else None


class GpuLoadGate:
    """Ocupada quando a GPU está ocupada por outro programa (uso >= `busy_percent`), via `nvidia-smi`.

    Cobre o jogo em janela sem borda, que a tela cheia não pega. Mede a GPU inteira, então só vale **antes**
    de começar a trabalhar (`is_free`). Entre blocos de uma etapa (`is_free_while_working`) ela não é
    consultada: a carga medida seria a da própria etapa, que esperaria por si mesma para sempre.
    """

    def __init__(self, busy_percent: int, read: Callable[[], int | None] = _nvidia_smi_utilization) -> None:
        self._busy, self._read = busy_percent, read
        self._utilization: int | None = None

    def is_free(self) -> bool:
        self._utilization = self._read()
        return self._utilization is None or self._utilization < self._busy

    def is_free_while_working(self) -> bool:
        return True

    def reason(self) -> str | None:
        busy = self._utilization is not None and self._utilization >= self._busy
        return f"GPU em uso por outro programa ({self._utilization}%)" if busy else None


class CompositeGate:
    """Livre só se todos os gates estão livres; o motivo é o do primeiro que recusou."""

    def __init__(self, gates: Sequence[GpuGate]) -> None:
        self._gates = list(gates)
        self._blocking: GpuGate | None = None

    def is_free(self) -> bool:
        self._blocking = next((g for g in self._gates if not is_free_now(g, working=False)), None)
        return self._blocking is None

    def is_free_while_working(self) -> bool:
        self._blocking = next((g for g in self._gates if not is_free_now(g, working=True)), None)
        return self._blocking is None

    def reason(self) -> str | None:
        return gate_reason(self._blocking) if self._blocking is not None else None


class CachedGate:
    """Guarda a resposta do gate por `ttl_s`: quem consulta em sequência rápida (um trecho de prévia a cada
    poucos segundos) não paga a sonda do OBS toda vez. A espera por um gate ocupado reconsulta sempre, porque
    o intervalo entre as sondagens é maior que o TTL."""

    def __init__(self, inner: GpuGate, ttl_s: float, now: Callable[[], float] = time.monotonic) -> None:
        self._inner, self._ttl, self._now = inner, ttl_s, now
        self._cache: dict[bool, tuple[float, bool]] = {}

    def _check(self, working: bool) -> bool:
        moment = self._now()
        hit = self._cache.get(working)
        if hit is not None and moment - hit[0] < self._ttl:
            return hit[1]
        free = is_free_now(self._inner, working=working)
        self._cache[working] = (moment, free)
        return free

    def is_free(self) -> bool:
        return self._check(False)

    def is_free_while_working(self) -> bool:
        return self._check(True)

    def reason(self) -> str | None:
        return gate_reason(self._inner)


def build_gate(settings: Settings) -> GpuGate:
    """Gate do ambiente: desligado em `dev`; em `prod`, OBS + tela cheia (+ carga, se configurada)."""
    if not settings.gpu_gate:
        return AlwaysFreeGate()
    gates: list[GpuGate] = [
        ObsRecordingGate(settings.obs_host, settings.obs_port, settings.obs_password),
        FullscreenGate(),
    ]
    if settings.gpu_busy_percent is not None:
        gates.append(GpuLoadGate(settings.gpu_busy_percent))
    return CachedGate(CompositeGate(gates), CACHE_TTL_S)
