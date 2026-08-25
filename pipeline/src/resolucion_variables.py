# -*- coding: utf-8 -*-
"""
pipeline/src/resolucion_variables.py — Resolución de nombres de variables a campos canónicos.

Convierte los nombres que el LLM extrae de fórmulas de pliegos (abreviaturas como
AC, PC, POE; nombres libres como "activo_corriente") a sus rutas canónicas en
PerfilEmpresa o en el dict de valores del pliego.

Estrategia de resolución:
  (C) Diccionario de abreviaturas  ← precedencia máxima
  (B) Nombre libre → catálogo auto-generado de PerfilEmpresa
  Ninguna → variable_no_resuelta (registrar en fallo_log para mejorar el dict)

Estrategia descartada:
  (A) Catálogo completo en el prompt del LLM — causa alucinación silenciosa de rutas.
"""
from __future__ import annotations

import ast as _ast
from dataclasses import dataclass
from typing import Literal


# ─── Catálogo auto-generado de PerfilEmpresa ─────────────────────────────────

def _construir_catalogo_perfil() -> dict[str, str]:
    """
    Recorre los sub-modelos de PerfilEmpresa y devuelve
    {campo_corto: ruta_canónica} y {ruta_completa: ruta_canónica}.

    Se actualiza automáticamente si perfil.py añade campos.
    """
    from .perfil import (
        PerfilFinanciero, PerfilExperiencia,
        PerfilJuridico, PerfilTecnico, PerfilSocial,
    )
    bloques: dict[str, type] = {
        "financiero":  PerfilFinanciero,
        "experiencia": PerfilExperiencia,
        "juridico":    PerfilJuridico,
        "tecnico":     PerfilTecnico,
        "social":      PerfilSocial,
    }
    catalogo: dict[str, str] = {}
    for bloque, modelo in bloques.items():
        for campo in modelo.model_fields:
            ruta = f"{bloque}.{campo}"
            catalogo[campo] = ruta   # nombre corto → ruta canónica
            catalogo[ruta]  = ruta   # ruta completa → identidad
    return catalogo


# Construido en tiempo de importación (solo inspección de model_fields, sin I/O)
_PERFIL_CAMPOS: dict[str, str] = _construir_catalogo_perfil()


# ─── Variables del pliego ─────────────────────────────────────────────────────

_PLIEGO_CAMPOS: dict[str, str] = {
    "presupuesto_oficial_estimado": "presupuesto_oficial_estimado",
    "presupuesto_oficial":          "presupuesto_oficial_estimado",   # alias
    "porcentaje_anticipo":          "porcentaje_anticipo",
    "valor_anticipo":               "valor_anticipo",
    "valor_smmlv_anio":             "valor_smmlv_anio",
    "capital_trabajo_demandado":    "capital_trabajo_demandado",
    "CTd":                          "capital_trabajo_demandado",
    "compromisos":                  "saldos_contratos_en_ejecucion_pliego",
    "valor_contrato":               "valor_contrato",
    "plazo_meses":                  "plazo_meses",
    "plazo_dias":                   "plazo_dias",
}


# ─── Diccionario de abreviaturas (CCE + pliegos colombianos) ─────────────────
# Tupla: (fuente, campo_canónico)
# Registrar TODAS las variantes de ortografía conocidas.

_ABREV: dict[str, tuple[Literal["perfil", "pliego"], str]] = {
    # ── Activo / Pasivo Corriente ──────────────────────────────────────────
    "AC":   ("perfil", "financiero.activo_corriente"),
    "PC":   ("perfil", "financiero.pasivo_corriente"),
    # ── Patrimonio ────────────────────────────────────────────────────────
    "PN":   ("perfil", "financiero.patrimonio_neto"),
    "PL":   ("perfil", "financiero.patrimonio_neto"),    # patrimonio líquido
    # ── Capital de trabajo ────────────────────────────────────────────────
    "CT":   ("perfil", "financiero.capital_trabajo"),
    "KT":   ("perfil", "financiero.capital_trabajo"),
    # ── Ingresos operacionales ────────────────────────────────────────────
    "CO":   ("perfil", "financiero.ingresos_operacionales_ultimos_5_anos"),
    "IO":   ("perfil", "financiero.ingresos_operacionales_ultimos_5_anos"),
    # ── Índices derivados ─────────────────────────────────────────────────
    "IDL":  ("perfil", "financiero.indice_liquidez"),
    "IL":   ("perfil", "financiero.indice_liquidez"),
    "NDE":  ("perfil", "financiero.indice_endeudamiento"),
    "IE":   ("perfil", "financiero.indice_endeudamiento"),
    "RCI":  ("perfil", "financiero.cobertura_intereses"),
    # ── Rentabilidad ──────────────────────────────────────────────────────
    "ROE":  ("perfil", "financiero.rentabilidad_patrimonio"),
    "ROA":  ("perfil", "financiero.rentabilidad_activo"),
    "Roe":  ("perfil", "financiero.rentabilidad_patrimonio"),
    "Roa":  ("perfil", "financiero.rentabilidad_activo"),
    # ── Saldo contratos en ejecución (Factor K) ───────────────────────────
    "SCE":  ("perfil", "financiero.saldos_contratos_en_ejecucion"),
    # ── Pliego ────────────────────────────────────────────────────────────
    "POE":  ("pliego", "presupuesto_oficial_estimado"),
    "anticipo": ("pliego", "porcentaje_anticipo"),
}


# ─── Resultado ───────────────────────────────────────────────────────────────

@dataclass
class ResultadoResolucion:
    variable: str               # nombre original de la variable en la expresión
    fuente: Literal["perfil", "pliego", "no_resuelta"]
    campo: str | None           # ruta canónica; None si no_resuelta
    es_ambigua: bool = False    # encontrada en perfil Y en pliego
    fuente_usada: Literal["perfil", "pliego"] | None = None  # si es_ambigua
    motivo_no_resuelta: str | None = None


# ─── Resolución ──────────────────────────────────────────────────────────────

def resolver_variable(
    nombre: str,
    fuente_inferida: Literal["perfil", "pliego"] = "perfil",
) -> ResultadoResolucion:
    """
    Resuelve el nombre de una variable a su fuente y campo canónico.

    Precedencia:
      1. Diccionario de abreviaturas (_ABREV)
      2. Catálogo auto-generado de PerfilEmpresa (_PERFIL_CAMPOS)
      3. Catálogo de variables del pliego (_PLIEGO_CAMPOS)
      4. No encontrado → variable_no_resuelta

    Cuando la variable existe en AMBOS catálogos (ambigua), se usa fuente_inferida
    y se marca es_ambigua=True para auditoría.
    """
    # ── 1. Diccionario de abreviaturas (precedencia máxima) ──
    if nombre in _ABREV:
        fuente_abrev, campo_abrev = _ABREV[nombre]
        otra: Literal["perfil", "pliego"] = "pliego" if fuente_abrev == "perfil" else "perfil"
        en_otro = nombre in (_PLIEGO_CAMPOS if otra == "pliego" else _PERFIL_CAMPOS)
        if en_otro:
            campo_otro = (
                _PLIEGO_CAMPOS[nombre] if otra == "pliego" else _PERFIL_CAMPOS[nombre]
            )
            campo_elegido = campo_abrev if fuente_inferida == fuente_abrev else campo_otro
            return ResultadoResolucion(
                variable=nombre,
                fuente=fuente_inferida,
                campo=campo_elegido,
                es_ambigua=True,
                fuente_usada=fuente_inferida,
            )
        return ResultadoResolucion(variable=nombre, fuente=fuente_abrev, campo=campo_abrev)

    # ── 2-3. Nombre libre en catálogos ──
    en_perfil = nombre in _PERFIL_CAMPOS
    en_pliego  = nombre in _PLIEGO_CAMPOS

    if en_perfil and en_pliego:
        campo = _PERFIL_CAMPOS[nombre] if fuente_inferida == "perfil" else _PLIEGO_CAMPOS[nombre]
        return ResultadoResolucion(
            variable=nombre,
            fuente=fuente_inferida,
            campo=campo,
            es_ambigua=True,
            fuente_usada=fuente_inferida,
        )
    if en_perfil:
        return ResultadoResolucion(variable=nombre, fuente="perfil", campo=_PERFIL_CAMPOS[nombre])
    if en_pliego:
        return ResultadoResolucion(variable=nombre, fuente="pliego", campo=_PLIEGO_CAMPOS[nombre])

    # ── 4. No encontrado ──
    return ResultadoResolucion(
        variable=nombre,
        fuente="no_resuelta",
        campo=None,
        motivo_no_resuelta=(
            f"'{nombre}' no está en el diccionario de abreviaturas ni en el catálogo "
            f"de perfil/pliego. Añadir a _ABREV o _PLIEGO_CAMPOS si es una abreviatura nueva."
        ),
    )


# ─── Utilidad ─────────────────────────────────────────────────────────────────

def extraer_nombres_de_expresion(expresion: str) -> list[str]:
    """
    Extrae los nombres de variables de una expresión aritmética Python-evaluable.

    Usa ast.parse() — no evalúa la expresión. Filtra los nombres de funciones
    permitidas (sqrt, abs, min, max, round). Devuelve nombres únicos en orden.

    Ejemplos:
      "AC - PC"          → ["AC", "PC"]
      "(POE - anticipo) * 0.33" → ["POE", "anticipo"]
    """
    if not expresion:
        return []
    from .criterios import _FUNCIONES_PERMITIDAS
    try:
        tree = _ast.parse(expresion.strip(), mode="eval")
    except SyntaxError:
        return []
    nombres: list[str] = []
    vistos: set[str] = set()
    for nodo in _ast.walk(tree):
        if isinstance(nodo, _ast.Name) and nodo.id not in _FUNCIONES_PERMITIDAS:
            if nodo.id not in vistos:
                nombres.append(nodo.id)
                vistos.add(nodo.id)
    return nombres
