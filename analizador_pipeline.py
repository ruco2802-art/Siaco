# -*- coding: utf-8 -*-
"""
analizador_pipeline.py — Agentes de redacción sobre datos estructurados del pipeline.

Los agentes NO extraen del pliego (ya lo hizo el pipeline con 100% de cobertura).
Reciben datos calculados y redactan concepto narrativo, riesgos y recomendaciones.

Dos agentes públicos:
  agente_financiero_pipeline(evaluacion, perfil, licitacion) → dict
  agente_juridico_pipeline(requisitos_habilitantes, evaluacion, perfil, licitacion) → dict
"""
from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from prompts import SKILL_FINANCIERO, SKILL_JURIDICO, SKILL_ESTRATEGIA, SKILL_ANTI_RECHAZO

_MODEL = "claude-sonnet-4-6"
_TIMEOUT = 60.0  # outputs de hasta ~3 000 tokens necesitan más de 30s
_MAX_RETRIES = 2  # reintentos de red vía SDK; JSON-parse errors → fallback dict


# ─── JSON parsing ─────────────────────────────────────────────────────────────

def _limpiar_md(texto: str) -> str:
    """Extrae JSON desde bloques ```json ... ``` o devuelve el texto limpio."""
    texto = texto.strip()
    if "```" not in texto:
        return texto
    for frag in texto.split("```")[1::2]:
        limpio = frag.strip()
        if limpio.lower().startswith("json"):
            limpio = limpio[4:].strip()
        if limpio:
            return limpio
    return texto


def _parsear_json(texto: str) -> dict:
    """Intenta parsear JSON del texto del modelo; lanza ValueError si falla."""
    try:
        return json.loads(_limpiar_md(texto))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido en respuesta del modelo: {exc}") from exc


# ─── Prompts de sistema (constantes, cacheable via prompt caching) ─────────────

_SISTEMA_FINANCIERO = (
    "Eres un consultor financiero de contratación pública colombiana especializado en SECOP II.\n"
    "Recibirás el resultado de un evaluador automático (Python puro, sin LLM) que comparó "
    "los indicadores financieros de la empresa contra los umbrales del pliego.\n"
    "Tu tarea es SOLO redactar: concepto narrativo, razones y recomendaciones.\n"
    "NO recalcules scores — los valores y el veredicto ya están calculados y son canónicos.\n"
    "NO inventes indicadores que no aparezcan en los datos.\n"
    "Cita normas específicas (Decreto 1082/2015, Resolución 196/2016 CCE, Ley 1474/2011).\n"
    "Si un indicador tiene estado dato_faltante, indica qué documento debe aportar el usuario.\n\n"
    + SKILL_FINANCIERO
)

# Bloques con cache_control para activar prompt caching (se paga creación × 1, lectura × 0.1)
_SISTEMA_FINANCIERO_BLOCKS: list[dict] = [
    {
        "type": "text",
        "text": _SISTEMA_FINANCIERO,
        "cache_control": {"type": "ephemeral"},
    }
]

_SISTEMA_JURIDICO = (
    "Eres un consultor jurídico de contratación pública colombiana especializado en SECOP II.\n"
    "Recibirás los requisitos habilitantes extraídos del pliego por el pipeline (100% del documento) "
    "junto con el resultado de la evaluación automática (cumple/no_cumple/dato_faltante).\n"
    "Tu tarea es SOLO redactar: concepto jurídico, riesgos, subsanabilidad y documentos a gestionar.\n"
    "NO extraigas nuevos requisitos del pliego — ya están dados.\n"
    "NO recalcules scores — el veredicto ya está calculado.\n"
    "Para subsanabilidad aplica Ley 1150/2007 art. 5. Los causales de rechazo explícitos "
    "marcados en los datos NO son subsanables salvo indicación contraria del pliego.\n"
    "Cita normas específicas en cada riesgo y en cada instrucción de documento.\n\n"
    + SKILL_JURIDICO + "\n\n" + SKILL_ESTRATEGIA + "\n\n" + SKILL_ANTI_RECHAZO
)

_SISTEMA_JURIDICO_BLOCKS: list[dict] = [
    {
        "type": "text",
        "text": _SISTEMA_JURIDICO,
        "cache_control": {"type": "ephemeral"},
    }
]


# ─── Agente financiero ─────────────────────────────────────────────────────────

def agente_financiero_pipeline(
    evaluacion: dict,
    perfil: dict,
    licitacion: dict,
) -> dict:
    """
    Redacta concepto financiero sobre el resultado de evaluar_empresa().

    evaluacion : salida de pipeline.src.evaluator.evaluar_empresa()
    perfil     : dict con al menos nombre, es_mipyme
    licitacion : dict con nombre_proceso, entidad, valor
    """
    items_fin = [
        it for it in evaluacion.get("items", [])
        if it.get("categoria") == "financiero"
    ]
    desglose_fin = evaluacion.get("desglose", {}).get("financiero", {})

    lineas: list[str] = []
    for it in items_fin:
        estado = it.get("estado", "?").upper()
        val    = f" | empresa: {it['valor_empresa']}" if "valor_empresa" in it else ""
        oper   = it.get("operador", "")
        unidad = it.get("unidad") or ""
        lim    = f" | límite: {oper} {it['umbral']} {unidad}".strip() if "umbral" in it else ""
        lineas.append(f"  · {it['requisito']}: {estado}{val}{lim}")

    prompt_usuario = (
        f"EMPRESA: {perfil.get('nombre', '[sin nombre]')} "
        f"| MiPyme: {perfil.get('es_mipyme', False)}\n"
        f"PROCESO: {licitacion.get('nombre_proceso', '[sin nombre]')}\n"
        f"ENTIDAD: {licitacion.get('entidad', '[no especificada]')}\n"
        f"VALOR: {licitacion.get('valor', '[no especificado]')}\n\n"
        "RESULTADO DEL EVALUADOR AUTOMÁTICO (Python — no LLM):\n"
        f"  Score financiero: {evaluacion.get('score_global', 'N/A')} "
        f"| Veredicto: {evaluacion.get('veredicto', 'N/A')}\n"
        f"  Cumple: {desglose_fin.get('cumple', 0)} "
        f"| No cumple: {desglose_fin.get('no_cumple', 0)} "
        f"| Sin dato: {desglose_fin.get('dato_faltante', 0)}\n\n"
        "DETALLE POR INDICADOR:\n"
        + ("\n".join(lineas) if lineas else "  (sin indicadores financieros evaluados)")
        + "\n\n"
        "Responde ÚNICAMENTE con JSON válido, sin texto antes ni después:\n"
        "{\n"
        '  "concepto_financiero": "VIABLE|CONDICIONAL|NO VIABLE",\n'
        '  "razones_financiero": ["razón 1 con norma citada", "..."],\n'
        '  "recomendaciones": ["recomendación 1", "..."],\n'
        '  "indices_evaluados": {"descripcion": "resumen ejecutivo en 2 oraciones"}\n'
        "}"
    )

    client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        timeout=_TIMEOUT,
        max_retries=_MAX_RETRIES,
    )
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=_SISTEMA_FINANCIERO_BLOCKS,
        messages=[{"role": "user", "content": prompt_usuario}],
    )

    texto = next(
        (b.text for b in resp.content if getattr(b, "type", None) == "text"),
        "",
    )
    try:
        return _parsear_json(texto)
    except ValueError:
        return {
            "concepto_financiero": "CONDICIONAL",
            "razones_financiero": [texto[:500] or "Error al parsear respuesta del agente financiero"],
            "recomendaciones": [],
            "indices_evaluados": {"descripcion": "Concepto no disponible — revisar con asesor"},
        }


# ─── Agente jurídico ───────────────────────────────────────────────────────────

def agente_juridico_pipeline(
    requisitos_habilitantes: list[dict],
    evaluacion: dict,
    perfil: dict,
    licitacion: dict,
) -> dict:
    """
    Redacta concepto jurídico, riesgos y documentos a gestionar.

    requisitos_habilitantes : lista de Requisito.model_dump() filtrada a
                              criticidad=="habilitante" (puede incluir todas las categorías).
    evaluacion              : salida de evaluar_empresa() — para el desglose jurídico.
    perfil                  : dict con nombre, es_mipyme.
    licitacion              : dict con nombre_proceso, entidad.
    """
    # Índice de estado por nombre de requisito (desde evaluacion["items"])
    _estado_por_nombre: dict[str, dict] = {
        it["requisito"]: it
        for it in evaluacion.get("items", [])
    }

    desglose_jur = evaluacion.get("desglose", {}).get("juridico", {})

    lineas: list[str] = []
    for req in requisitos_habilitantes:
        nombre    = req.get("nombre", "?")
        numeral   = req.get("fuente_numeral", "")
        cita      = (req.get("exigido_literal") or "")[:120]
        es_causal = req.get("es_causal_rechazo_explicita", False)
        criticidad = req.get("criticidad", "habilitante")

        it = _estado_por_nombre.get(nombre, {})
        estado = it.get("estado", "sin_evaluar").upper()

        linea = f"  [{estado}] {nombre} (§{numeral})"
        if criticidad != "habilitante":
            linea += f" [{criticidad}]"
        if es_causal:
            linea += " ⚠ CAUSAL DE RECHAZO EXPLÍCITA"
        if cita:
            linea += f'\n    Cita: "{cita}..."'
        lineas.append(linea)

    prompt_usuario = (
        f"EMPRESA: {perfil.get('nombre', '[sin nombre]')} "
        f"| MiPyme: {perfil.get('es_mipyme', False)}\n"
        f"PROCESO: {licitacion.get('nombre_proceso', '[sin nombre]')}\n"
        f"ENTIDAD: {licitacion.get('entidad', '[no especificada]')}\n\n"
        "EVALUADOR AUTOMÁTICO — habilitantes jurídicos:\n"
        f"  Cumple: {desglose_jur.get('cumple', 0)} "
        f"| No cumple: {desglose_jur.get('no_cumple', 0)} "
        f"| Sin dato: {desglose_jur.get('dato_faltante', 0)}\n\n"
        "REQUISITOS HABILITANTES EXTRAÍDOS DEL PLIEGO (100% del documento):\n"
        + ("\n".join(lineas) if lineas else "  (sin requisitos habilitantes clasificados)")
        + "\n\n"
        "Responde ÚNICAMENTE con JSON válido, sin texto antes ni después:\n"
        "{\n"
        '  "concepto_juridico": "VIABLE|CONDICIONAL|NO VIABLE",\n'
        '  "viable_juridico": true,\n'
        '  "requisitos_habilitantes": [\n'
        '    {"requisito": "nombre", "exigido": "cita breve", '
        '"cumple": true, "norma": "Ley X art. Y", "subsanable": false}\n'
        "  ],\n"
        '  "riesgos_juridicos": ["riesgo 1 con norma", "..."],\n'
        '  "documentos_faltantes": ["Nombre del doc — cómo obtenerlo"],\n'
        '  "documentos_checklist": [\n'
        '    {"documento": "nombre", "estado": "falta|ok|pendiente", "subsanable": true}\n'
        "  ]\n"
        "}"
    )

    client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        timeout=_TIMEOUT,
        max_retries=_MAX_RETRIES,
    )
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=3000,
        system=_SISTEMA_JURIDICO_BLOCKS,
        messages=[{"role": "user", "content": prompt_usuario}],
    )

    texto = next(
        (b.text for b in resp.content if getattr(b, "type", None) == "text"),
        "",
    )
    try:
        return _parsear_json(texto)
    except ValueError:
        return {
            "concepto_juridico": "CONDICIONAL",
            "viable_juridico": None,
            "requisitos_habilitantes": [],
            "riesgos_juridicos": [texto[:500] or "Error al parsear respuesta del agente jurídico"],
            "documentos_faltantes": [],
            "documentos_checklist": [],
        }
