# -*- coding: utf-8 -*-
"""
pipeline/src/fallo_log.py — Dos canales separados para fallos de estructuración.

Hay dos audiencias con necesidades opuestas:

  B1 — El abogado (en el reporte):
       Necesita saber QUÉ revisar y DÓNDE. No puede hacer nada con detalles
       técnicos del parser; verlos hace que el reporte parezca defectuoso
       cuando en realidad señala correctamente sus límites.

  B2 — El equipo de desarrollo (log interno):
       Necesita el detalle completo para saber qué añadir al diccionario de
       variables o a la whitelist del evaluador. Sin este canal, cada fallo
       parece aislado y nadie mejora nada.

API pública:
  mensajes_usuario(req)   → str     (B1)
  registrar_fallo(...)    → None    (B2, escribe en logs/)
  reporte_agregado(...)   → dict    (B2, lectura y análisis del JSONL)
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("siaco")

# ─── Ruta del log JSONL ───────────────────────────────────────────────────────
# fallo_log.py → src/ → pipeline/ → raíz del proyecto
_RAIZ        = Path(__file__).parent.parent.parent
_LOG_JSONL   = _RAIZ / "logs" / "estructuracion_fallida.jsonl"

TipoFallo = Literal[
    "clasificacion_ambigua",
    "variable_no_resuelta",
    "expresion_no_soportada",
    "json_invalido",
]


# ─── B1 — Mensaje para el usuario ────────────────────────────────────────────

def mensaje_usuario(
    numeral: str,
    pagina: int | None,
    cita_literal: str,
) -> str:
    """
    Genera el texto mínimo que aparece en el reporte para el abogado.

    Solo responde: ¿qué revisar? y ¿dónde? Sin mencionar parsers, variables,
    ni causas técnicas. El cuerpo es la cita literal para que el abogado ubique
    el requisito en el pliego original.
    """
    ubicacion = f"numeral {numeral}"
    if pagina is not None:
        ubicacion += f", página {pagina}"

    return (
        f"Requiere revisión manual — {ubicacion}\n"
        f'"{cita_literal}"'
    )


# ─── B2 — Registro interno (JSONL) ───────────────────────────────────────────

def registrar_fallo(
    tipo_fallo: TipoFallo,
    pliego: str,
    numeral: str,
    texto_original: str,
    *,
    pagina: int | None = None,
    detalle: str = "",
    criterio_parcial: dict[str, Any] | None = None,
) -> None:
    """
    Añade un registro al JSONL de fallos de estructuración.

    Nunca lanza excepción: si el archivo no se puede escribir, registra el
    fallo en el logger de aplicación y continúa. Un fallo de log no debe
    detener el procesamiento del pliego.
    """
    registro: dict[str, Any] = {
        "timestamp":       datetime.now().isoformat(),
        "pliego":          pliego,
        "numeral":         numeral,
        "pagina":          pagina,
        "texto_original":  texto_original[:500],  # evitar registros gigantes
        "tipo_fallo":      tipo_fallo,
        "detalle":         detalle,
        "criterio_parcial": criterio_parcial or {},
    }
    try:
        _LOG_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error(
            "[FALLO_LOG] No se pudo escribir en %s: %s | fallo original: %s | numeral: %s",
            _LOG_JSONL, exc, tipo_fallo, numeral,
        )


# ─── B2 — Reporte agregado ────────────────────────────────────────────────────

def reporte_agregado(
    desde: str | None = None,
    hasta: str | None = None,
    solo_pliego: str | None = None,
) -> dict[str, Any]:
    """
    Lee el JSONL de fallos y devuelve un resumen accionable.

    Args:
        desde:       timestamp ISO mínimo (inclusive). None = sin límite.
        hasta:       timestamp ISO máximo (inclusive). None = sin límite.
        solo_pliego: si se indica, filtra solo los registros de ese pliego.

    Returns dict con:
      total_fallos            int
      por_tipo_fallo          dict[str, int]   — frecuencia de cada TipoFallo
      top_variables           list[dict]       — top 10 variables no resueltas
      top_expresiones         list[dict]       — top 5 operaciones rechazadas
      pliegos_con_mas_fallos  list[dict]       — top 5 pliegos
      periodo                 dict             — desde / hasta efectivos
    """
    if not _LOG_JSONL.exists():
        return {
            "total_fallos": 0,
            "mensaje": "Sin fallos registrados todavía.",
            "archivo": str(_LOG_JSONL),
        }

    registros: list[dict] = []
    try:
        with _LOG_JSONL.open("r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    registros.append(json.loads(linea))
                except json.JSONDecodeError:
                    continue
    except Exception as exc:
        return {"error": f"No se pudo leer {_LOG_JSONL}: {exc}"}

    # ── Filtros opcionales ──
    if desde:
        registros = [r for r in registros if r.get("timestamp", "") >= desde]
    if hasta:
        registros = [r for r in registros if r.get("timestamp", "") <= hasta]
    if solo_pliego:
        registros = [r for r in registros if r.get("pliego") == solo_pliego]

    if not registros:
        return {"total_fallos": 0, "mensaje": "Sin fallos en el período indicado."}

    # ── Conteos por tipo ──
    por_tipo = Counter(r.get("tipo_fallo", "desconocido") for r in registros)

    # ── Top variables no resueltas ──
    variables: list[str] = []
    for r in registros:
        if r.get("tipo_fallo") == "variable_no_resuelta":
            det = r.get("detalle", "")
            if det:
                # El detalle tiene formato: "variable_no_resuelta: CTd"
                nombre = det.split(":")[-1].strip()
                if nombre:
                    variables.append(nombre)
    top_variables = [
        {"variable": v, "frecuencia": c}
        for v, c in Counter(variables).most_common(10)
    ]

    # ── Top expresiones no soportadas ──
    expresiones: list[str] = []
    for r in registros:
        if r.get("tipo_fallo") == "expresion_no_soportada":
            det = r.get("detalle", "")
            if det:
                expresiones.append(det[:120])  # truncar expresiones largas
    top_expresiones = [
        {"expresion": e, "frecuencia": c}
        for e, c in Counter(expresiones).most_common(5)
    ]

    # ── Top pliegos con más fallos ──
    por_pliego = Counter(r.get("pliego", "desconocido") for r in registros)
    top_pliegos = [
        {"pliego": p, "fallos": c}
        for p, c in por_pliego.most_common(5)
    ]

    # ── Rango de fechas efectivo ──
    timestamps = [r.get("timestamp", "") for r in registros if r.get("timestamp")]
    periodo = {
        "desde": min(timestamps) if timestamps else None,
        "hasta": max(timestamps) if timestamps else None,
    }

    return {
        "total_fallos":           len(registros),
        "por_tipo_fallo":         dict(por_tipo.most_common()),
        "top_variables":          top_variables,
        "top_expresiones":        top_expresiones,
        "pliegos_con_mas_fallos": top_pliegos,
        "periodo":                periodo,
        "archivo_fuente":         str(_LOG_JSONL),
    }


# ─── Utilidad: imprimir reporte en consola ────────────────────────────────────

def imprimir_reporte(reporte: dict) -> None:
    """Formatea el reporte agregado para salida legible en terminal."""
    if "error" in reporte:
        print(f"[FALLO_LOG] Error al leer el log: {reporte['error']}")
        return

    total = reporte.get("total_fallos", 0)
    print(f"\n{'='*60}")
    print(f"  REPORTE DE FALLOS DE ESTRUCTURACIÓN")
    periodo = reporte.get("periodo", {})
    if periodo.get("desde"):
        print(f"  Período: {periodo['desde'][:10]} → {periodo['hasta'][:10]}")
    print(f"  Total: {total} fallo(s)")
    print(f"{'='*60}")

    if total == 0:
        print("  Sin fallos registrados.")
        return

    print("\n  Por tipo:")
    for tipo, cnt in reporte.get("por_tipo_fallo", {}).items():
        print(f"    {tipo:<35} {cnt:>4}")

    if reporte.get("top_variables"):
        print("\n  Variables no resueltas (top 10):")
        for v in reporte["top_variables"]:
            print(f"    {v['variable']:<20} × {v['frecuencia']}")

    if reporte.get("top_expresiones"):
        print("\n  Expresiones rechazadas (top 5):")
        for e in reporte["top_expresiones"]:
            print(f"    {e['expresion'][:55]:<55} × {e['frecuencia']}")

    if reporte.get("pliegos_con_mas_fallos"):
        print("\n  Pliegos con más fallos:")
        for p in reporte["pliegos_con_mas_fallos"]:
            print(f"    {p['pliego']:<40} {p['fallos']:>3} fallo(s)")

    print()
