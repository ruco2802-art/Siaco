# -*- coding: utf-8 -*-
"""
tests/test_analizador_pipeline.py — Tests offline para analizador_pipeline.py.

Sin API. Sin disco. Todos los mocks en memoria.
Cubre:
  1. Marcador de skill SAFE-L presente en system de agente_financiero_pipeline
  2. Marcador de Anti-Rechazo SIACO presente en system de agente_juridico_pipeline
  3. Estructura del dict devuelto por agente_financiero_pipeline
  4. Estructura del dict devuelto por agente_juridico_pipeline
  5. Fallback cuando la API devuelve texto no-JSON (financiero)
  6. Fallback cuando la API devuelve texto no-JSON (jurídico)
  7. Inputs vacíos — sin items financieros
  8. Inputs vacíos — sin requisitos habilitantes
  9. Causal de rechazo explícita aparece marcada en el prompt del jurídico
 10. Items financieros se filtran correctamente por categoría
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ── path: ejecutar desde pipeline/ (como hace /verify) ──────────────────────
_ROOT = Path(__file__).parent.parent.parent  # raíz del repo
sys.path.insert(0, str(_ROOT))               # para importar analizador_pipeline

import analizador_pipeline as ap


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _mock_resp(texto_json: str) -> MagicMock:
    """Crea un mock de respuesta de la API con un bloque de texto."""
    bloque = SimpleNamespace(type="text", text=texto_json)
    resp   = MagicMock()
    resp.content = [bloque]
    return resp


def _evaluacion_fake(
    score: float = 75.0,
    veredicto: str = "viable",
    items: list[dict] | None = None,
) -> dict:
    """Evaluacion mínima compatible con la salida de evaluar_empresa()."""
    if items is None:
        items = [
            {"requisito": "Índice de liquidez", "estado": "cumple",
             "categoria": "financiero", "valor_empresa": 1.5, "umbral": 1.0, "operador": ">="},
            {"requisito": "RUP en firme", "estado": "cumple",
             "categoria": "juridico"},
        ]
    return {
        "score_global": score,
        "veredicto": veredicto,
        "items": items,
        "desglose": {
            "financiero": {"cumple": 1, "no_cumple": 0, "dato_faltante": 0},
            "juridico":   {"cumple": 1, "no_cumple": 0, "dato_faltante": 0},
        },
    }


def _requisitos_fake(
    n: int = 3,
    con_causal_rechazo: bool = False,
) -> list[dict]:
    """Lista de requisitos habilitantes simulados (Requisito.model_dump())."""
    reqs = [
        {
            "nombre": f"Requisito {i}",
            "categoria": "juridico",
            "fuente_numeral": f"3.{i}",
            "exigido_literal": f"El proponente deberá acreditar el requisito {i} según la norma vigente.",
            "criticidad": "habilitante",
            "es_causal_rechazo_explicita": (i == 1 and con_causal_rechazo),
        }
        for i in range(1, n + 1)
    ]
    return reqs


_PERFIL = {"nombre": "Empresa Test SAS", "es_mipyme": True}
_LICITACION = {"nombre_proceso": "LP-001-2026", "entidad": "Alcaldía de Neiva", "valor": "$500.000.000"}

_JSON_FINANCIERO_OK = json.dumps({
    "concepto_financiero": "VIABLE",
    "razones_financiero": ["IDL cumple Decreto 1082/2015"],
    "recomendaciones": [],
    "indices_evaluados": {"descripcion": "La empresa cumple todos los indicadores."},
})

_JSON_JURIDICO_OK = json.dumps({
    "concepto_juridico": "VIABLE",
    "viable_juridico": True,
    "requisitos_habilitantes": [
        {"requisito": "RUP en firme", "exigido": "RUP activo", "cumple": True,
         "norma": "Ley 80/1993 art. 22", "subsanable": False}
    ],
    "riesgos_juridicos": [],
    "documentos_faltantes": [],
    "documentos_checklist": [],
})


# ─── 1. Marcador SAFE-L en el system del agente financiero ────────────────────

def test_system_financiero_contiene_marcador_safe_l():
    """El system prompt del agente financiero debe contener 'SAFE-L' (marcador de skill)."""
    system_text = ap._SISTEMA_FINANCIERO
    assert "SAFE-L" in system_text, (
        "El system prompt de agente_financiero_pipeline no contiene el marcador 'SAFE-L'. "
        "Verifica que SKILL_FINANCIERO se está inyectando correctamente."
    )


# ─── 2a. Marcador Anti-Rechazo en el system del agente jurídico ───────────────

def test_system_juridico_contiene_marcador_anti_rechazo():
    """El system prompt del agente jurídico debe contener 'Anti-Rechazo SIACO' (skill)."""
    system_text = ap._SISTEMA_JURIDICO
    assert "Anti-Rechazo SIACO" in system_text, (
        "El system prompt de agente_juridico_pipeline no contiene el marcador 'Anti-Rechazo SIACO'. "
        "Verifica que SKILL_ANTI_RECHAZO se está inyectando correctamente."
    )


# ─── 2b. Marcador SKILL_ESTRATEGIA en el system del agente jurídico ───────────

def test_system_juridico_contiene_marcador_estrategia():
    """El system prompt del agente jurídico debe contener 'Reglas de Oro de Subsanabilidad'."""
    system_text = ap._SISTEMA_JURIDICO
    assert "Reglas de Oro de Subsanabilidad" in system_text, (
        "El system prompt de agente_juridico_pipeline no contiene el marcador "
        "'Reglas de Oro de Subsanabilidad'. "
        "Verifica que SKILL_ESTRATEGIA se está inyectando correctamente."
    )


# ─── 3. Estructura del dict devuelto por agente_financiero_pipeline ───────────

def test_agente_financiero_estructura_respuesta():
    """agente_financiero_pipeline devuelve dict con las claves requeridas."""
    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = _mock_resp(_JSON_FINANCIERO_OK)
        resultado = ap.agente_financiero_pipeline(_evaluacion_fake(), _PERFIL, _LICITACION)

    assert isinstance(resultado, dict)
    assert "concepto_financiero" in resultado
    assert "razones_financiero" in resultado
    assert "recomendaciones" in resultado
    assert "indices_evaluados" in resultado
    assert isinstance(resultado["razones_financiero"], list)


# ─── 4. Estructura del dict devuelto por agente_juridico_pipeline ─────────────

def test_agente_juridico_estructura_respuesta():
    """agente_juridico_pipeline devuelve dict con las claves requeridas."""
    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = _mock_resp(_JSON_JURIDICO_OK)
        resultado = ap.agente_juridico_pipeline(
            _requisitos_fake(), _evaluacion_fake(), _PERFIL, _LICITACION
        )

    assert isinstance(resultado, dict)
    assert "concepto_juridico" in resultado
    assert "viable_juridico" in resultado
    assert "requisitos_habilitantes" in resultado
    assert "riesgos_juridicos" in resultado
    assert "documentos_faltantes" in resultado
    assert "documentos_checklist" in resultado


# ─── 5. Fallback financiero cuando API devuelve texto no-JSON ─────────────────

def test_agente_financiero_fallback_json_invalido():
    """Si la API devuelve texto plano (no JSON), el agente devuelve dict de fallback."""
    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = _mock_resp(
            "Lo siento, no puedo responder en este momento."
        )
        resultado = ap.agente_financiero_pipeline(_evaluacion_fake(), _PERFIL, _LICITACION)

    assert isinstance(resultado, dict)
    assert "concepto_financiero" in resultado
    assert resultado["concepto_financiero"] == "CONDICIONAL"


# ─── 6. Fallback jurídico cuando API devuelve texto no-JSON ───────────────────

def test_agente_juridico_fallback_json_invalido():
    """Si la API devuelve texto plano (no JSON), el agente devuelve dict de fallback."""
    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = _mock_resp(
            "Error interno del sistema."
        )
        resultado = ap.agente_juridico_pipeline(
            _requisitos_fake(), _evaluacion_fake(), _PERFIL, _LICITACION
        )

    assert isinstance(resultado, dict)
    assert "concepto_juridico" in resultado
    assert resultado["viable_juridico"] is None


# ─── 7. Inputs vacíos — sin items financieros ─────────────────────────────────

def test_agente_financiero_sin_items_financieros():
    """Evaluacion sin items financieros no rompe la función."""
    evaluacion = _evaluacion_fake(items=[
        {"requisito": "RUP en firme", "estado": "cumple", "categoria": "juridico"}
    ])
    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = _mock_resp(_JSON_FINANCIERO_OK)
        resultado = ap.agente_financiero_pipeline(evaluacion, _PERFIL, _LICITACION)

    # El prompt llega al API y se obtiene respuesta — sin excepción
    assert "concepto_financiero" in resultado


# ─── 8. Inputs vacíos — sin requisitos habilitantes ──────────────────────────

def test_agente_juridico_sin_requisitos():
    """Lista vacía de requisitos no rompe la función."""
    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = _mock_resp(_JSON_JURIDICO_OK)
        resultado = ap.agente_juridico_pipeline(
            [], _evaluacion_fake(), _PERFIL, _LICITACION
        )

    assert "concepto_juridico" in resultado


# ─── 9. Causal de rechazo explícita aparece en el prompt del jurídico ─────────

def test_agente_juridico_causal_rechazo_en_prompt():
    """Un requisito con es_causal_rechazo_explicita=True debe marcar el prompt con ⚠."""
    calls: list[dict] = []

    def _capturar(**kwargs):
        calls.append(kwargs)
        return _mock_resp(_JSON_JURIDICO_OK)

    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = _capturar
        ap.agente_juridico_pipeline(
            _requisitos_fake(n=2, con_causal_rechazo=True),
            _evaluacion_fake(),
            _PERFIL,
            _LICITACION,
        )

    assert calls, "La API no fue llamada"
    prompt = calls[0]["messages"][0]["content"]
    assert "CAUSAL DE RECHAZO EXPLÍCITA" in prompt or "⚠" in prompt, (
        "El prompt del agente jurídico no marca el causal de rechazo explícito. "
        "Verifica que el campo es_causal_rechazo_explicita se refleja en el prompt."
    )


# ─── 10. Items financieros se filtran correctamente por categoría ─────────────

def test_agente_financiero_filtra_categoria():
    """Solo los items con categoria='financiero' deben llegar al prompt."""
    calls: list[dict] = []

    def _capturar(**kwargs):
        calls.append(kwargs)
        return _mock_resp(_JSON_FINANCIERO_OK)

    evaluacion = _evaluacion_fake(items=[
        {"requisito": "IDL", "estado": "cumple", "categoria": "financiero",
         "valor_empresa": 1.5, "umbral": 1.0, "operador": ">="},
        {"requisito": "RUP en firme", "estado": "cumple", "categoria": "juridico"},
        {"requisito": "Experiencia acumulada", "estado": "no_cumple", "categoria": "experiencia"},
    ])

    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = _capturar
        ap.agente_financiero_pipeline(evaluacion, _PERFIL, _LICITACION)

    prompt = calls[0]["messages"][0]["content"]
    assert "IDL" in prompt
    assert "RUP en firme" not in prompt, (
        "El agente financiero está incluyendo requisitos jurídicos en su prompt. "
        "Solo deben aparecer items con categoria='financiero'."
    )
    assert "Experiencia acumulada" not in prompt
