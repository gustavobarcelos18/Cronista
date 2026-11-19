"""Tipos comuns às análises de áudio e vídeo, num só lugar (A9)."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float32]
"""Vetor de amostras ou sinais em float32."""

Pause = Callable[[], None]
"""Chamada que bloqueia enquanto a GPU não está livre (o gate), feita entre blocos de trabalho."""
