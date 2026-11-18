"""Trilhas da timeline do Resolve num único lugar (glossário: trilha = da timeline; faixa = do OBS).

Cada trilha traz a lane do FCPXML (V1 é o `spine`, lane 0; vídeo acima é positivo; áudio é negativo), então
o mapa trilha → lane não se espalha pelos escritores.
"""

from __future__ import annotations

from enum import StrEnum

_LANES = {
    "V1": 0,
    "V2": 1,
    "V3": 2,
    "V4": 3,
    "V5": 4,
    "A1": -1,
    "A2": -2,
    "A4": -4,
    "A5": -5,
    "A6": -6,
    "A7": -7,
}


class Track(StrEnum):
    V1 = "V1"  # gameplay (spine)
    V2 = "V2"  # zoom e shake sobre o corte
    V3 = "V3"  # B-roll
    V4 = "V4"  # overlays: contador de mortes, textos
    V5 = "V5"  # cartelas
    A1 = "A1"  # jogo
    A2 = "A2"  # microfone
    A4 = "A4"  # música
    A5 = "A5"  # SFX
    A6 = "A6"  # narração (desligada na importação)
    A7 = "A7"  # sobra (desligada na importação)

    @property
    def lane(self) -> int:
        return _LANES[self.value]
