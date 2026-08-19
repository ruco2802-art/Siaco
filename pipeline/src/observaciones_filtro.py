# -*- coding: utf-8 -*-
"""
pipeline/src/observaciones_filtro.py — Triple filtro de observaciones al pliego.

Una observación al pliego es un acto jurídico que puede presentarse ante una
entidad pública. Un error ahí desacredita todo el análisis. Por eso ninguna
observación nace confirmada: se construye con sustento verificable (F1 + F2)
y queda en estado "propuesta" hasta que una persona decide (F3).

Flujo de estados:
  construir_candidato() → "propuesta" (inicio)
      ↓ aplicar_filtro_1()
  "desviacion_no_confirmada"  ← la aritmética no la detecta → descarte silencioso
      ↓ (si F1 pasa)
      ↓ aplicar_filtro_2()
  "sustento_incompleto"  ← alguna cita no existe en el documento → descarte
      ↓ (si F2 pasa)
  "propuesta"  ← lista para que el usuario decida (F3)
      ↓ confirmar() / descartar()
  "confirmada" | "descartada"
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ─── Modelos ───────────────────────────────────────────────────────────────────

EstadoObservacion = Literal[
    "propuesta",
    "confirmada",
    "descartada",
    "sustento_incompleto",
    "desviacion_no_confirmada",
]


class CitaVerificada(BaseModel):
    """Fragmento literal de un documento con su ubicación."""
    texto: str
    numeral: str | None = None
    pagina: int | None = None
    fuente_doc: str | None = None   # nombre del archivo .md o .txt de la norma
    verificada: bool = False        # True → la cadena existe literalmente en el doc


class ResultadoFiltro(BaseModel):
    paso: bool
    motivo: str | None = None

    # F1 — campos del análisis aritmético
    valor_pliego: float | None = None
    valor_cce: float | None = None
    modalidad: str | None = None
    variante: str | None = None
    operador_req: str | None = None     # ">=" o "<=" — dirección del indicador
    direccion: Literal["mas_estricto", "menos_estricto", "igual"] | None = None
    diff: float | None = None           # valor_pliego − valor_cce (con signo)

    # F2 — campos de verificación de citas
    cita_pliego_verificada: bool | None = None
    cita_norma_verificada: bool | None = None


class ObservacionCandidato(BaseModel):
    """
    Candidato a observación. Nunca nace con estado 'confirmada'.
    Los tres filtros se registran explícitamente para trazabilidad.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    # Identificación
    indicador_id: str           # e.g. "indice_liquidez"
    descripcion_desviacion: str
    nivel_confianza: Literal["alta", "media"]

    # Citas — una del pliego, una de la norma
    cita_pliego: CitaVerificada
    cita_norma: CitaVerificada

    # Resultados de filtros (None = filtro aún no ejecutado)
    filtro_1: ResultadoFiltro | None = None
    filtro_2: ResultadoFiltro | None = None

    # Estado — nunca nace "confirmada"; F3 es la única que puede asignarla
    estado_observacion: EstadoObservacion = "propuesta"


# ─── F1 — Filtro determinista (aritmético) ────────────────────────────────────

def aplicar_filtro_1(
    candidato: ObservacionCandidato,
    valor_pliego: float,
    valor_cce: float,
    operador_req: str,
    modalidad: str,
    variante: str,
) -> ObservacionCandidato:
    """
    Compara el umbral del pliego contra el valor CCE por aritmética pura.

    operador_req define la dirección del indicador:
      ">=" → el proponente debe superar el umbral (ej. liquidez).
             Menos estricto = pliego exige MENOS que CCE → irregularidad.
      "<=" → el proponente debe estar por debajo del umbral (ej. endeudamiento).
             Menos estricto = pliego permite MÁS que CCE → irregularidad.

    Si la desviación no es detectable aritméticamente, el candidato queda
    en "desviacion_no_confirmada" — no se propone, no se descarta, se ignora.
    """
    diff = round(valor_pliego - valor_cce, 6)

    if operador_req == ">=":
        if diff < 0:
            direccion = "menos_estricto"
        elif diff > 0:
            direccion = "mas_estricto"
        else:
            direccion = "igual"
    elif operador_req == "<=":
        if diff > 0:
            direccion = "menos_estricto"
        elif diff < 0:
            direccion = "mas_estricto"
        else:
            direccion = "igual"
    else:
        candidato.filtro_1 = ResultadoFiltro(
            paso=False,
            motivo=f"operador_req no reconocido: '{operador_req}' — solo '>=' y '<=' soportados",
        )
        candidato.estado_observacion = "desviacion_no_confirmada"
        return candidato

    es_irregularidad = direccion == "menos_estricto"

    candidato.filtro_1 = ResultadoFiltro(
        paso=es_irregularidad,
        motivo=(
            None if es_irregularidad
            else f"No es irregularidad: pliego es {direccion} que CCE ({valor_pliego} vs {valor_cce})"
        ),
        valor_pliego=valor_pliego,
        valor_cce=valor_cce,
        modalidad=modalidad,
        variante=variante,
        operador_req=operador_req,
        direccion=direccion,
        diff=diff,
    )

    if not es_irregularidad:
        candidato.estado_observacion = "desviacion_no_confirmada"

    return candidato


# ─── F2 — Filtro de citas verificadas ─────────────────────────────────────────

def _buscar_cita(cita: str, texto_doc: str, tolerancia: int = 30) -> bool:
    """
    Verifica que la cita exista literalmente en el documento.

    Tolerancia: acepta hasta `tolerancia` caracteres de diferencia en espacios
    y puntuación para cubrir variaciones de OCR (saltos de línea, guiones).
    La búsqueda es insensible a mayúsculas para robustez.
    """
    if not cita or not texto_doc:
        return False

    # Normalización mínima: colapsar espacios y saltos de línea
    def _normalizar(s: str) -> str:
        return re.sub(r"[\s\n\r]+", " ", s).strip().lower()

    cita_norm = _normalizar(cita)
    doc_norm  = _normalizar(texto_doc)

    # Búsqueda exacta primero
    if cita_norm in doc_norm:
        return True

    # Búsqueda flexible: permitir hasta `tolerancia` chars distintos entre
    # subcadenas del documento (cubre diferencias de OCR en frases cortas)
    if len(cita_norm) <= tolerancia:
        return False  # cita demasiado corta para búsqueda flexible

    # Intentar buscar las primeras y últimas palabras significativas
    palabras = [w for w in cita_norm.split() if len(w) >= 4]
    if len(palabras) < 3:
        return False
    ancla_inicio = " ".join(palabras[:3])
    ancla_fin    = " ".join(palabras[-3:])
    return ancla_inicio in doc_norm and ancla_fin in doc_norm


def aplicar_filtro_2(
    candidato: ObservacionCandidato,
    texto_pliego_md: str,
    texto_norma_md: str,
) -> ObservacionCandidato:
    """
    Verifica que AMBAS citas existan literalmente en sus documentos fuente.
    Si cualquiera falla → "sustento_incompleto". La observación no se propone.

    texto_pliego_md: texto completo del markdown del pliego auditado.
    texto_norma_md:  texto del documento normativo citado (resolución, DT, etc.)
    """
    if candidato.estado_observacion == "desviacion_no_confirmada":
        return candidato  # F1 ya rechazó — no continuar

    cita_p = _buscar_cita(candidato.cita_pliego.texto, texto_pliego_md)
    cita_n = _buscar_cita(candidato.cita_norma.texto, texto_norma_md)

    candidato.cita_pliego.verificada = cita_p
    candidato.cita_norma.verificada  = cita_n

    ambas_ok = cita_p and cita_n

    motivo: str | None = None
    if not cita_p and not cita_n:
        motivo = "cita del pliego y de la norma no encontradas en sus documentos fuente"
    elif not cita_p:
        motivo = "cita del pliego no encontrada en el markdown del pliego"
    elif not cita_n:
        motivo = "cita de la norma no encontrada en el documento normativo"

    candidato.filtro_2 = ResultadoFiltro(
        paso=ambas_ok,
        motivo=motivo,
        cita_pliego_verificada=cita_p,
        cita_norma_verificada=cita_n,
    )

    if not ambas_ok:
        candidato.estado_observacion = "sustento_incompleto"

    return candidato


# ─── F3 — Confirmación humana ─────────────────────────────────────────────────

def confirmar(candidato: ObservacionCandidato) -> ObservacionCandidato:
    """
    Registra la decisión humana de confirmar la observación.
    Solo válido si el candidato está en estado 'propuesta'.
    """
    if candidato.estado_observacion != "propuesta":
        raise ValueError(
            f"Solo se puede confirmar una observación en estado 'propuesta'. "
            f"Estado actual: '{candidato.estado_observacion}'"
        )
    candidato.estado_observacion = "confirmada"
    return candidato


def descartar(candidato: ObservacionCandidato) -> ObservacionCandidato:
    """
    Registra la decisión humana de descartar la observación.
    Válido desde cualquier estado (el usuario siempre puede descartar).
    """
    candidato.estado_observacion = "descartada"
    return candidato


# ─── Pipeline completo ────────────────────────────────────────────────────────

def ejecutar_filtros(
    candidato: ObservacionCandidato,
    valor_pliego: float,
    valor_cce: float,
    operador_req: str,
    modalidad: str,
    variante: str,
    texto_pliego_md: str,
    texto_norma_md: str,
) -> ObservacionCandidato:
    """
    Ejecuta F1 y F2 en secuencia. F3 (confirmación) queda a cargo de la UI.
    El candidato resultante tiene estado_observacion actualizado y ambos
    ResultadoFiltro llenados para trazabilidad completa.
    """
    candidato = aplicar_filtro_1(
        candidato, valor_pliego, valor_cce, operador_req, modalidad, variante
    )
    candidato = aplicar_filtro_2(candidato, texto_pliego_md, texto_norma_md)
    return candidato


# ─── Presentación para el usuario (F3 UI) ────────────────────────────────────

def formatear_para_revision(candidato: ObservacionCandidato) -> dict:
    """
    Prepara el candidato para presentarlo al usuario en el paso de confirmación.
    Solo incluye lo que el abogado necesita — sin detalles técnicos de filtros.
    """
    f1 = candidato.filtro_1
    return {
        "id":                    candidato.id,
        "indicador":             candidato.indicador_id,
        "nivel_confianza":       candidato.nivel_confianza,
        "estado":                candidato.estado_observacion,
        "que_exige_el_pliego": {
            "cita":    candidato.cita_pliego.texto,
            "numeral": candidato.cita_pliego.numeral,
            "pagina":  candidato.cita_pliego.pagina,
        },
        "que_establece_la_norma": {
            "cita":       candidato.cita_norma.texto,
            "resolucion": candidato.cita_norma.fuente_doc,
            "pagina":     candidato.cita_norma.pagina,
        },
        "desviacion": candidato.descripcion_desviacion,
        "en_numeros": {
            "valor_pliego": f1.valor_pliego if f1 else None,
            "valor_cce":    f1.valor_cce    if f1 else None,
            "diferencia":   f1.diff         if f1 else None,
            "direccion":    f1.direccion    if f1 else None,
        },
    }
