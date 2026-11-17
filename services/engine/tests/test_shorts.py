from __future__ import annotations

import json

from cronista.assembly.plan import WordSpan
from cronista.domain.frames import FPS
from cronista.relevance.engine import Segment
from cronista.shorts.candidates import (
    Emotion,
    FileMaterial,
    ShortsParams,
    SpeechUtterance,
    candidates_for_file,
    pick_candidates,
    to_json,
)


def _seg(
    a: int, b: int, score: float = 0.8, classe: str = "momento", markers: list[str] | None = None
) -> Segment:
    return Segment(a, b, classe, score, ["marcador +0.50"], markers or [])


def _utt(start_s: float, end_s: float, words: list[tuple[float, float]] | None = None) -> SpeechUtterance:
    spans = tuple(WordSpan(round(a * FPS), round(b * FPS)) for a, b in (words or []))
    return SpeechUtterance(round(start_s * FPS), round(end_s * FPS), spans)


def test_janela_de_ate_13_s_com_gancho_nos_3_primeiros() -> None:
    # momento de 100 s a 160 s, marcador (pico) em 150 s; fala começa em 140 s
    mat = FileMaterial(1, [_seg(100, 160, markers=["m1"])], {"m1": 150 * FPS}, speech=[_utt(140, 149)])
    (c,) = candidates_for_file(mat, ShortsParams())
    assert c.duration_s <= 13.0
    assert c.start_frame <= c.hook_frame <= c.start_frame + 3 * FPS
    assert c.hook_kind == "fala"
    assert c.start_frame <= c.peak_frame <= c.end_frame
    assert c.end_frame == 154 * FPS  # pico + 4 s de reação


def test_gancho_tarde_recua_o_inicio_para_ele() -> None:
    # nada acontece até a emoção em 148 s; o pico (marcador) é em 150 s
    mat = FileMaterial(
        1, [_seg(100, 160, markers=["m1"])], {"m1": 150 * FPS}, emotions=[Emotion(148 * FPS, 149 * FPS, 0.9)]
    )
    (c,) = candidates_for_file(mat, ShortsParams())
    assert c.hook_kind == "emocao"
    assert c.start_frame == round(147.5 * FPS)  # 0,5 s de folga antes do gancho
    assert c.hook_offset_s <= 3.0


def test_sem_pico_ou_sem_gancho_nao_ha_candidato() -> None:
    sem_pico = FileMaterial(1, [_seg(100, 160)], {}, speech=[_utt(110, 120)])
    assert candidates_for_file(sem_pico, ShortsParams()) == []
    sem_gancho = FileMaterial(1, [_seg(100, 160, markers=["m1"])], {"m1": 100 * FPS}, speech=[])
    # o pico é o gancho quando está na janela; fora dela (pico muito cedo e janela só no fim) não sobra nada
    assert len(candidates_for_file(sem_gancho, ShortsParams())) == 1
    curto = FileMaterial(1, [_seg(100, 103, markers=["m1"])], {"m1": 102 * FPS})
    assert candidates_for_file(curto, ShortsParams()) == []  # menos de 5 s


def test_corte_nao_cai_dentro_de_palavra() -> None:
    # o fim natural (154 s) cai no meio da palavra de 153,8 s a 154,3 s
    words = [(153.8, 154.3)]
    mat = FileMaterial(
        1, [_seg(100, 160, markers=["m1"])], {"m1": 150 * FPS}, speech=[_utt(140, 154.3, words)]
    )
    (c,) = candidates_for_file(mat, ShortsParams())
    assert c.end_frame == round(153.8 * FPS)  # o fim da palavra passaria de 13 s: recua para o começo dela


def test_notas_baixas_e_classes_fora_do_momento_sao_ignoradas() -> None:
    mat = FileMaterial(
        1,
        [_seg(100, 160, score=0.3, markers=["a"]), _seg(200, 260, classe="farm", markers=["b"])],
        {"a": 150 * FPS, "b": 250 * FPS},
        speech=[_utt(140, 149), _utt(240, 249)],
    )
    assert candidates_for_file(mat, ShortsParams()) == []


def test_escolha_sem_sobreposicao_ordenada_e_limitada() -> None:
    segs = [
        _seg(100, 160, 0.9, markers=["a"]),
        _seg(110, 170, 0.7, markers=["b"]),
        _seg(300, 360, 0.8, markers=["c"]),
    ]
    marks = {"a": 150 * FPS, "b": 152 * FPS, "c": 350 * FPS}
    mat = FileMaterial(1, segs, marks, speech=[_utt(140, 149), _utt(340, 349)])
    found = pick_candidates([mat])
    assert [c.score for c in found] == [0.9, 0.8]  # o de 0,7 encosta no de 0,9 e sai
    assert len(pick_candidates([mat], ShortsParams(max_candidates=1))) == 1
    assert all(c.duration_s <= 13.0 for c in found)


def test_json_e_deterministico() -> None:
    mat = FileMaterial(1, [_seg(100, 160, markers=["m"])], {"m": 150 * FPS}, speech=[_utt(140, 149)])
    a, b = to_json(pick_candidates([mat])), to_json(pick_candidates([mat]))
    assert a == b
    row = json.loads(a)["candidatos"][0]
    assert row["duracao_s"] <= 13 and row["gancho_em_s"] <= 3
