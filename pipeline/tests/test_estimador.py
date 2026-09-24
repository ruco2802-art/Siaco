# -*- coding: utf-8 -*-
"""
COTA SUPERIOR del costo. Lo que importa: nunca quedarse corto.

El estimado por caracteres predijo $1,14 para Ternera y salió $1,4416, porque
la salida —que se cobra 5× más que la entrada— se fue +41%. Un estimado que se
queda corto no sirve para decidir si algo cabe en un límite de gasto.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.src.estimador import MARGEN_SALIDA, estimar  # noqa: E402

# Costos REALES medidos, no estimados.
_REAL = {"paicol": 1.05654, "ternera": 1.4416}


def _chunks(chars: int, n: int = 85) -> list[dict]:
    """n chunks que suman `chars` caracteres."""
    por = chars // n
    return [{"texto": "deberá acreditar mínimo " * (por // 24 or 1)} for _ in range(n)]


def test_el_techo_cubre_las_dos_corridas_reales():
    """
    La condición que hace útil al estimador. Paicol y Ternera tienen casi los
    mismos caracteres (227.507 y 227.908) y produjeron 218 y 340 requisitos;
    el techo debe cubrir al denso sin haberlo visto.
    """
    for etq, chars, n in (("paicol", 227_507, 85), ("ternera", 227_908, 104)):
        e = estimar(_chunks(chars, n))
        assert e.techo_usd >= _REAL[etq], (
            f"{etq}: techo ${e.techo_usd:.4f} por DEBAJO del real "
            f"${_REAL[etq]:.4f} — el estimador no sirve para un límite"
        )


def test_el_margen_se_aplica_solo_a_la_salida():
    """La entrada es el texto que se envía: se conoce, no se infla."""
    e = estimar(_chunks(227_507, 85))
    sin_margen = estimar(_chunks(227_507, 85), margen=0.0)
    assert e.tokens_in == sin_margen.tokens_in
    assert e.tokens_out_techo > sin_margen.tokens_out_techo
    assert e.tokens_out_techo == pytest.approx(
        sin_margen.tokens_out_techo * (1 + MARGEN_SALIDA), rel=0.01)


def test_cabe_en_decide_contra_un_limite():
    e = estimar(_chunks(227_507, 85))
    ok, motivo = e.cabe_en(10.0)
    assert ok and "margen" in motivo
    no_ok, motivo = e.cabe_en(0.50)
    assert not no_ok and "SUPERA" in motivo


def test_el_techo_escala_con_el_texto():
    chico = estimar(_chunks(50_000, 20))
    grande = estimar(_chunks(400_000, 160))
    assert grande.techo_usd > chico.techo_usd * 3


def test_sin_chunks_no_hay_costo():
    e = estimar([])
    assert e.techo_usd == 0.0 and e.chunks == 0


def test_el_techo_es_mayor_que_la_referencia():
    """`referencia_usd` es el escenario de densidad conocida, no el techo."""
    e = estimar(_chunks(227_507, 85))
    assert e.techo_usd > e.referencia_usd
