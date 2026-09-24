# -*- coding: utf-8 -*-
"""
Barrera permanente sobre las citas normativas de los prompts.

El sistema tiene DOS fuentes de conocimiento normativo —los `.md` de
`.claude/skills/` y los fallbacks de `prompts.py`— y sólo se revisaba una. Los
cuatro artículos inventados que alimentaban al agente financiero vivían en la
otra y sobrevivieron meses. Este test los habría atrapado el primer día.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.src.auditor_citas import (  # noqa: E402
    FUENTES,
    auditar_citas,
    formatear,
)
from pipeline.src.bibliotecario import cargar_indice  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (_ROOT / "biblioteca_normativa" / "indice.json").exists(),
    reason="biblioteca_normativa/indice.json no disponible",
)


@pytest.fixture(scope="module")
def indice():
    return cargar_indice()


def test_todas_las_citas_de_los_prompts_verifican(indice):
    """
    Si esto falla: una cita de `prompts.py` o de una skill apunta a una norma
    que el índice no marca citable, o a un artículo que no existe.

    Para registrar deliberadamente una referencia no citable, marca la línea
    con `[no-citable]`, `[norma no disponible en la biblioteca: ...]` o
    `[cita pendiente de verificar]`.
    """
    hallazgos = auditar_citas(indice)
    assert not hallazgos, "\n" + formatear(hallazgos)


def test_todas_las_fuentes_existen(indice):
    """Un renombre de skill que rompa la ruta deja al agente con el fallback."""
    faltan = [f for f in FUENTES if not (_ROOT / f).exists()]
    assert not faltan, f"Fuentes declaradas que no existen: {faltan}"


def test_prompts_carga_las_skills_del_disco_no_el_fallback():
    """
    `skill_juridica_licitaciones.md.md` tenía la extensión duplicada y
    `_cargar_skill` caía al fallback en silencio. El fallback es el texto que
    llevaba las citas equivocadas.
    """
    import prompts

    for atributo, marcador in (
        ("SKILL_FINANCIERO", "=== MARCO FINANCIERO SAFE-L"),
        ("SKILL_JURIDICO", "=== MARCO JURÍDICO"),
    ):
        texto = getattr(prompts, atributo)
        assert not texto.lstrip().startswith(marcador), (
            f"{atributo} viene del fallback: el .md no se encontró en disco"
        )


def test_el_auditor_detecta_un_articulo_inventado(tmp_path, indice):
    """Prueba de saboteo: si el auditor no atrapa esto, no sirve de nada."""
    import pipeline.src.auditor_citas as A

    (tmp_path / "prompts.py").write_text(
        "BASE = 'Decreto 1082/2015 art. 9.9.9.9 regula los habilitantes'\n",
        encoding="utf-8",
    )
    original = A.FUENTES
    A.FUENTES = ("prompts.py",)
    try:
        hallazgos = auditar_citas(indice, raiz=tmp_path)
    finally:
        A.FUENTES = original
    assert any(h["problema"] == "articulo_inexistente" for h in hallazgos)


def test_el_auditor_detecta_una_norma_no_citable(tmp_path, indice):
    import pipeline.src.auditor_citas as A

    (tmp_path / "prompts.py").write_text(
        "BASE = 'segun la Ley 1474/2011 art. 91 el anticipo es 50%'\n",
        encoding="utf-8",
    )
    original = A.FUENTES
    A.FUENTES = ("prompts.py",)
    try:
        hallazgos = auditar_citas(indice, raiz=tmp_path)
    finally:
        A.FUENTES = original
    assert any(h["problema"] == "norma_no_citable" for h in hallazgos)


def test_la_marca_de_exencion_silencia_la_advertencia(tmp_path, indice):
    """
    Una línea que nombra una norma para PROHIBIRLA no es una cita. Sin esta
    exención habría que borrar el aviso para que pase el test, que es lo
    contrario de lo que se busca.
    """
    import pipeline.src.auditor_citas as A

    (tmp_path / "prompts.py").write_text(
        "AVISO = 'NUNCA cites la Ley 1474/2011 art. 91 para el tope [no-citable]'\n",
        encoding="utf-8",
    )
    original = A.FUENTES
    A.FUENTES = ("prompts.py",)
    try:
        assert auditar_citas(indice, raiz=tmp_path) == []
    finally:
        A.FUENTES = original
