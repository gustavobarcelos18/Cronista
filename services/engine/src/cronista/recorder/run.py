"""Laço do gravador: conecta ao OBS (com nova tentativa), escuta teclas e eventos até Ctrl+C."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from functools import partial

from cronista.config import Settings
from cronista.domain.models import MarkerKind
from cronista.recorder.core import Recorder, system_clock
from cronista.recorder.hotkeys import PynputHotkeys, resolve_hotkeys
from cronista.recorder.obs import SimpleObsLink
from cronista.recorder.ports import Clock, Feedback, HotkeySource, ObsError, ObsLink

RETRY_S = 3.0

ObsFactory = Callable[[str, int, str | None, Clock], ObsLink]


async def run_session(recorder: Recorder, obs: ObsLink) -> None:
    """Uma conexão: assume gravação em andamento e processa eventos até a conexão cair."""
    await recorder.attach()
    while (event := await obs.next_event()) is not None:
        await recorder.handle(event)


async def run_forever(
    settings: Settings,
    feedback: Feedback,
    *,
    hotkeys: HotkeySource | None = None,
    clock: Clock = system_clock,
    obs_factory: ObsFactory = SimpleObsLink,
    retry_s: float = RETRY_S,
) -> None:
    loop = asyncio.get_running_loop()
    source = hotkeys or PynputHotkeys(resolve_hotkeys(settings.marker_hotkeys))
    tasks: set[asyncio.Task[None]] = set()
    current: Recorder | None = None

    def finished(task: asyncio.Task[None], *, kind: MarkerKind) -> None:
        tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            # Sem isto o toque falharia calado, e o som é justamente o que diz ao criador que funcionou.
            feedback.warn(f"{kind.value}: toque NÃO registrado ({error})")

    def on_press(kind: MarkerKind) -> None:  # chamado na thread do teclado
        stamp = clock()  # o instante do toque, não o de quando a tarefa rodar

        def schedule() -> None:
            if current is not None:
                task = loop.create_task(current.press(kind, stamp))
                tasks.add(task)
                task.add_done_callback(partial(finished, kind=kind))
            else:
                feedback.warn(f"{kind.value}: sem conexão com o OBS, toque perdido")

        loop.call_soon_threadsafe(schedule)

    source.start(on_press)
    feedback.info("Gravador de marcadores no ar. Ctrl+C para sair.")
    try:
        while True:
            obs = obs_factory(settings.obs_host, settings.obs_port, settings.obs_password, clock)
            try:
                await obs.connect()
            except ObsError as exc:
                feedback.warn(f"{exc}; tentando de novo em {retry_s:.0f}s")
                await asyncio.sleep(retry_s)
                continue
            current = Recorder(obs, feedback, settings, clock=clock)
            feedback.info("Conectado ao OBS.")
            try:
                await run_session(current, obs)
            except ObsError as exc:
                feedback.warn(str(exc))
            finally:
                current.close()
                current = None
                await obs.close()
            feedback.warn(f"conexão com o OBS perdida; tentando de novo em {retry_s:.0f}s")
            await asyncio.sleep(retry_s)
    finally:
        source.stop()
        for task in tasks:
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*tasks, return_exceptions=True)
