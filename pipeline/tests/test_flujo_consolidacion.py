# -*- coding: utf-8 -*-
"""
tests/test_flujo_consolidacion.py — Test de INTEGRACIÓN contra la desconexión.

Motivo: es la sexta vez que aparece código construido, probado y sin llamador
(reparar_markdown, marcar_indices, I9, reparar_con_modelo, SKILL_FINANCIERO,
consolidar). Un test unitario de consolidar() pasa aunque nadie la invoque.

Este test recorre el flujo real obtener_artefactos() → evaluar_empresa() y
falla si la consolidación deja de aplicarse en la capa de acceso.

Sin API. Sin red. Fixtures en tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.src import artefactos as mod_artefactos
from pipeline.src.artefactos import obtener_artefactos, bloque_requisitos
from pipeline.src.extractor import Requisito
from pipeline.src.evaluator import evaluar_empresa, PerfilEmpresa


_SHA_FALSO = "a" * 64

# Markdown mínimo con las cabeceras que el chunker necesita
_MARKDOWN = (
    "# CAPÍTULO I GENERALIDADES\n\nTexto introductorio del pliego.\n\n"
    "# CAPÍTULO III REQUISITOS HABILITANTES\n\n"
    "## 3.6 CAPACIDAD FINANCIERA\n\nÍndice de liquidez mayor o igual a 1,2.\n\n"
    "# CAPÍTULO IV CRITERIOS DE EVALUACIÓN\n\n"
    "## 4.1 PROPUESTA ECONÓMICA\n\nAsignación de puntaje.\n"
)


def _req_crudo(nombre: str, numeral: str, categoria: str = "juridico") -> dict:
    """
    Requisito tal como lo emite el extractor: SIN campo criticidad.
    Reproduce exactamente el formato de resultados_evaluacion/*.json.
    """
    return {
        "nombre": nombre,
        "categoria": categoria,
        "fuente_numeral": numeral,
        "exigido_literal": f"El proponente deberá acreditar {nombre} conforme al pliego.",
    }


# Conjunto crudo: mezcla de habilitantes (cap. 3), procedimentales (cap. 2 y 7)
# y puntaje (cap. 4), más un duplicado exacto para ejercitar la deduplicación.
_REQUISITOS_CRUDOS: list[dict] = [
    _req_crudo("Índice de liquidez", "3.6 CAPACIDAD FINANCIERA", "financiero"),
    _req_crudo("Índice de endeudamiento", "3.6 CAPACIDAD FINANCIERA", "financiero"),
    _req_crudo("RUP en firme al cierre", "3.1 CAPACIDAD JURÍDICA"),
    _req_crudo("Ausencia de inhabilidades", "3.1 CAPACIDAD JURÍDICA"),
    _req_crudo("Ausencia de inhabilidades", "3.1 CAPACIDAD JURÍDICA"),  # duplicado
    _req_crudo("Carta de presentación de la oferta", "2.1 PRESENTACIÓN"),
    _req_crudo("Garantía de seriedad de la oferta", "7.1 GARANTÍAS"),
    _req_crudo("Puntaje por propuesta económica", "4.1 PROPUESTA ECONÓMICA"),
    _req_crudo("Puntaje por componente nacional", "4.3.2 COMPONENTE NACIONAL"),
]


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Monta cache + resultados en tmp_path y apunta artefactos.py allí."""
    cache_dir = tmp_path / ".pipeline_cache"
    result_dir = tmp_path / "resultados_evaluacion"
    cache_dir.mkdir()
    result_dir.mkdir()

    (cache_dir / f"{_SHA_FALSO}.json").write_text(
        json.dumps({
            "markdown": _MARKDOWN,
            "metadata": {"sha256": _SHA_FALSO, "archivo": "pliego_test.pdf", "n_paginas": 3},
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (result_dir / f"{_SHA_FALSO}_extraccion.json").write_text(
        json.dumps({
            "requisitos": _REQUISITOS_CRUDOS,
            "metadatos_corrida": {"pliego_sha256": _SHA_FALSO, "timestamp_utc": "2026-09-07T00:00:00Z"},
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod_artefactos, "_CACHE_DIR", cache_dir)
    monkeypatch.setattr(mod_artefactos, "_RESULTADOS_DIR", result_dir)
    monkeypatch.setattr(mod_artefactos, "_CHUNKS_CACHE", {})
    monkeypatch.setattr(mod_artefactos, "_CONSOLIDADO_CACHE", {})
    return tmp_path


# ─── 1. La consolidación se aplica en la capa de acceso ──────────────────────

def test_obtener_artefactos_devuelve_consolidados(entorno):
    """obtener_artefactos() debe entregar requisitos YA clasificados y deduplicados."""
    arts = obtener_artefactos(_SHA_FALSO)
    assert arts is not None, "obtener_artefactos devolvió None con caché válida"

    assert arts.consolidacion.get("aplicada") is True, (
        "La consolidación NO se aplicó en artefactos.py. "
        "consolidar() volvió a quedar sin llamador en el flujo de producción."
    )
    # El duplicado exacto debe desaparecer
    assert len(arts.requisitos) < len(_REQUISITOS_CRUDOS), (
        f"Sin reducción: {len(arts.requisitos)} de {len(_REQUISITOS_CRUDOS)} crudos. "
        "La deduplicación no corrió."
    )


# ─── 2. Ningún requisito conserva criticidad por default ─────────────────────

def test_ningun_requisito_queda_sin_clasificar(entorno):
    """
    Todo requisito debe tener criticidad asignada POR EL CLASIFICADOR,
    no heredada del default del modelo.
    """
    arts = obtener_artefactos(_SHA_FALSO)

    for r in arts.requisitos:
        assert r.get("criticidad") is not None, f"criticidad ausente en {r.get('nombre')}"
        # evidencia_criticidad la escribe SOLO clasificar_requisito(); si falta,
        # el valor de criticidad vino del default del modelo.
        assert r.get("evidencia_criticidad") is not None, (
            f"'{r.get('nombre')}' tiene criticidad={r.get('criticidad')} pero sin "
            "evidencia_criticidad: el valor viene del default del modelo, "
            "no del clasificador."
        )


def test_default_criticidad_es_indeterminado():
    """
    Un Requisito sin clasificar debe quedar 'indeterminado', nunca 'habilitante'.
    Con default 'habilitante' un pliego sin clasificar producía habilitantes falsos.
    """
    r = Requisito(
        nombre="Requisito sin clasificar",
        categoria="juridico",
        fuente_numeral="X",
        exigido_literal="texto",
    )
    assert r.criticidad == "indeterminado", (
        f"El default de criticidad es {r.criticidad!r}. Debe ser 'indeterminado': "
        "un requisito sin clasificar es desconocido, no habilitante."
    )


# ─── 3. Las tres criticidades se separan ─────────────────────────────────────

def test_criticidades_se_separan(entorno):
    """El conjunto debe repartirse entre habilitante / procedimental / puntaje."""
    arts = obtener_artefactos(_SHA_FALSO)
    crits = {r.get("criticidad") for r in arts.requisitos}

    assert "habilitante" in crits, "Ningún habilitante: el capítulo 3 no se clasificó"
    assert "puntaje" in crits, "Ningún puntaje: el capítulo 4 no se clasificó"

    hab = [r for r in arts.requisitos if r.get("criticidad") == "habilitante"]
    assert 0 < len(hab) < len(arts.requisitos), (
        f"{len(hab)} habilitantes de {len(arts.requisitos)}: el filtro no discrimina. "
        "Si son todos, la clasificación no corrió."
    )


# ─── 4. Flujo completo hasta evaluar_empresa ─────────────────────────────────

def test_flujo_completo_hasta_evaluador(entorno):
    """
    obtener_artefactos() → filtrar habilitantes → evaluar_empresa().
    Replica la cadena de _analizar_con_pipeline() sin API.
    """
    arts = obtener_artefactos(_SHA_FALSO)
    reqs = [Requisito.model_validate(r) for r in arts.requisitos]
    habilitantes = [r for r in reqs if r.criticidad == "habilitante"]

    assert habilitantes, "Cero habilitantes: el evaluador no podría decidir habilitación"

    perfil = PerfilEmpresa(
        nombre="Empresa Test SAS",
        es_mipyme=True,
        municipio_domicilio="Paicol",
        financiero={"indice_liquidez": 1.5, "indice_endeudamiento": 0.4},
        juridico={"rup_en_firme": True, "sin_inhabilidades": False},
    )
    ev = evaluar_empresa(perfil, habilitantes)

    assert ev["total_evaluados"] > 0
    estados = {i["estado"] for i in ev["items"]}
    assert "cumple" in estados or "no_cumple" in estados, (
        f"Todos los estados son {estados}: el mapeo perfil↔requisito no produce "
        "ninguna evaluación efectiva."
    )
    # El evaluador sólo vio habilitantes
    assert ev["total_evaluados"] <= len(habilitantes)


# ─── 5. El chat recibe el mismo conjunto consolidado ─────────────────────────

def test_bloque_requisitos_recibe_consolidados(entorno):
    """
    bloque_requisitos() alimenta el chat. Debe ver los consolidados,
    no los crudos: una sola verdad sobre el pliego.
    """
    arts = obtener_artefactos(_SHA_FALSO)
    bloque = bloque_requisitos(arts, solo_habilitantes=True)

    assert bloque, "bloque_requisitos devolvió vacío"
    assert "[AVISO]" not in bloque, (
        "bloque_requisitos activó el aviso de 'sin clasificar': "
        "el chat no está recibiendo requisitos consolidados."
    )
    # Los de puntaje (cap. 4) no deben aparecer con solo_habilitantes=True
    assert "Puntaje por propuesta económica" not in bloque, (
        "Un requisito de puntaje llegó al bloque de habilitantes del chat."
    )


def test_bloque_requisitos_avisa_si_no_hay_clasificacion():
    """
    Si la clasificación no corrió (cero habilitantes), el chat debe recibir
    un aviso explícito en vez de los crudos disfrazados de habilitantes.
    """
    arts = mod_artefactos.Artefactos(
        pliego_id="x", archivo="a.pdf", markdown="m", chunks=[],
        requisitos=[{**r, "criticidad": "indeterminado"} for r in _REQUISITOS_CRUDOS],
        metadatos_parser={}, metadatos_corrida={},
    )
    bloque = bloque_requisitos(arts, solo_habilitantes=True)
    assert "[AVISO]" in bloque, (
        "Con cero habilitantes el chat recibe la lista completa sin advertencia: "
        "creería que son habilitantes."
    )


# ─── 6. Paicol real — sólo si el archivo local existe ────────────────────────

_PAICOL = _ROOT / "resultados_evaluacion" / "paicol_2026_resultado.json"


@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol_2026_resultado.json no disponible (gitignored)")
def test_paicol_consolidacion_218_a_61(tmp_path, monkeypatch):
    """
    Datos reales: 218 crudos → 99 consolidados → 60 habilitantes.

    Los límites anteriores (61 / 28) codificaban el comportamiento con [B9]:
    dos bolsas (21 y 16 fragmentos) se contaban como un requisito cada una.
    Al dejar de fusionarlas el conteo sube y refleja el pliego real.
    """
    raw = json.loads(_PAICOL.read_text("utf-8"))
    crudos = raw["requisitos"]
    assert len(crudos) == 218, f"El fixture de Paicol cambió: {len(crudos)} requisitos"

    cache_dir = tmp_path / "c"; cache_dir.mkdir()
    result_dir = tmp_path / "r"; result_dir.mkdir()
    (cache_dir / f"{_SHA_FALSO}.json").write_text(
        json.dumps({"markdown": _MARKDOWN, "metadata": {"archivo": "paicol.pdf"}}),
        encoding="utf-8",
    )
    (result_dir / f"{_SHA_FALSO}_extraccion.json").write_text(
        json.dumps({"requisitos": crudos, "metadatos_corrida": {"pliego_sha256": _SHA_FALSO}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod_artefactos, "_CACHE_DIR", cache_dir)
    monkeypatch.setattr(mod_artefactos, "_RESULTADOS_DIR", result_dir)
    monkeypatch.setattr(mod_artefactos, "_CHUNKS_CACHE", {})
    monkeypatch.setattr(mod_artefactos, "_CONSOLIDADO_CACHE", {})

    arts = obtener_artefactos(_SHA_FALSO)
    n_total = len(arts.requisitos)
    hab = [r for r in arts.requisitos if r.get("criticidad") == "habilitante"]

    # Bandas anchas a propósito: lo que vigilan son DOS REGRESIONES
    # concretas, no un número exacto. El catálogo v2.0.0 (eje `sujeto` + 11
    # objetos nuevos) subió Paicol de 141 a 154 consolidados y de 81 a 91
    # habilitantes al separar sujetos que antes se fusionaban; eso es la
    # corrección, no una desviación.
    assert 120 <= n_total <= 175, (
        f"Consolidación de Paicol dio {n_total} requisitos; se esperaban "
        "~154 con el catálogo v2.0.0 [B11][K4]. Si subió cerca de 218, la "
        "consolidación dejó de aplicarse; si bajó cerca de 105, el catálogo "
        "dejó de tomar la clave primaria y volvió la agrupación por prefijo."
    )
    assert 70 <= len(hab) <= 105, (
        f"Paicol dio {len(hab)} habilitantes; se esperaban ~91 con el "
        "catálogo v2.0.0. Si son ~218, el default de criticidad volvió a "
        "'habilitante'; si bajan a ~58, `aspecto=None` volvió a agrupar."
    )
