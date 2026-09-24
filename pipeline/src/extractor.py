# -*- coding: utf-8 -*-
"""
src/extractor.py — chunks → requisitos habilitantes.

[I1] Procesa TODOS los chunks, sin filtro por palabras clave.
[I2] stop_reason se revisa ANTES de json.loads; max_tokens=8000 como fusible.
[I3] Lista de requisitos abierta, sin tope.
[I5] fuente_numeral del chunk tiene precedencia sobre la del modelo.
[I6] El modelo extrae hechos; nunca compara ni puntúa.
[I9] Toda corrida con costo de API debe persistir su resultado. La
     ruta de salida se valida como escribible ANTES de la primera llamada
     (responsabilidad del orquestador). Si el guardado final falla →
     IOError, no advertencia silenciosa.
"""
from __future__ import annotations

import dataclasses
import json
import os
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import anthropic
from pydantic import AliasChoices, BaseModel, Field, ValidationError

# Import en tiempo de ejecución — no hay circular: criterios.py no importa extractor.py
from .criterios import Criterio

# ─── Checklist CCE (~30 ítems) ─────────────────────────────────────────────

CHECKLIST_CCE: list[str] = [
    "RUP en firme",
    "Cámara de Comercio vigente",
    "Certificado existencia y representación legal",
    "Paz y salvo aportes parafiscales (SENA, ICBF, CCF)",
    "Certificado de aportes a seguridad social",
    "Paz y salvo impuestos municipales o distritales",
    "Boletín de responsables fiscales CGR",
    "Antecedentes disciplinarios PROCURADURÍA",
    "Antecedentes judiciales y penales",
    "Declaración de inhabilidades e incompatibilidades",
    "RUT vigente",
    "Índice de liquidez (IDL)",
    "Índice de endeudamiento (NDE)",
    "Razón de cobertura de intereses (RCI)",
    "Capital de trabajo mínimo",
    "Patrimonio neto líquido",
    "Rentabilidad del patrimonio",
    "Rentabilidad del activo",
    "EBITDA",
    "Capacidad residual de contratación",
    "Experiencia: valor acumulado contratos similares",
    "Experiencia: valor contrato individual mayor",
    "Experiencia: objeto similar (CIIU o UNSPSC)",
    "Experiencia: número máximo contratos acreditables",
    "Experiencia: antigüedad o plazo mínimo",
    "Clasificación UNSPSC",
    "Garantía de seriedad de la oferta",
    "Personal mínimo requerido",
    "Equipos mínimos requeridos",
    "Certificado de industria nacional",
]

assert len(CHECKLIST_CCE) > 0, "CHECKLIST_CCE no puede estar vacío"

# ─── Normalización de alias y sinónimos ────────────────────────────────────

def _quitar_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _norm_id(s: str) -> str:
    """Minúsculas, sin tildes, guiones→espacio — para lookup en mapas."""
    return _quitar_tildes(s.lower().replace("-", " ").replace("_", " ")).strip()


# clave_json_del_modelo → campo_canonical_en_Requisito
_ALIAS_CAMPOS: dict[str, str] = {
    "tipo": "categoria",
    "tipo_de_requisito": "categoria",
    "clase": "categoria",
    "cita": "exigido_literal",
    "cita_literal": "exigido_literal",
    "texto_literal": "exigido_literal",
    "numeral": "fuente_numeral",
    "seccion": "fuente_numeral",
    "sección": "fuente_numeral",
    "fuente": "fuente_numeral",
    "umbral": "valor_umbral",
    "minimo": "valor_umbral",
    "mínimo": "valor_umbral",
}

# Mapas semánticos: llave pre-normalizada con _norm_id
_MAP_CATEGORIA: dict[str, str] = {
    _norm_id(k): v for k, v in {
        "financiera": "financiero",
        "economico": "financiero",
        "económico": "financiero",
        "economica": "financiero",
        "económica": "financiero",
        "juridica": "juridico",
        "jurídica": "juridico",
        "legal": "juridico",
        "tecnica": "tecnico",
        "técnica": "tecnico",
        "documentos": "documental",
        "documentario": "documental",
        "experiencia_general": "experiencia",
    }.items()
}

_MAP_APLICA_A: dict[str, str] = {
    _norm_id(k): v for k, v in {
        "mipymes": "mipyme",
        "pymes": "mipyme",
        "mipyme domiciliada": "mipyme",
    }.items()
}

_MAP_OPERADOR: dict[str, str] = {
    "≥": ">=",
    "mayor o igual": ">=",
    "mayor_o_igual": ">=",
    "≤": "<=",
    "menor o igual": "<=",
    "menor_o_igual": "<=",
    "igual": "==",
    "distinto": "!=",
    "diferente": "!=",
}


# ─── Contexto de tracking mutable durante una llamada a extraer() ─────────

@dataclasses.dataclass
class _ExtraccionCtx:
    """Acumula métricas de blindaje a lo largo de una corrida completa."""
    alias_log: Counter = dataclasses.field(default_factory=Counter)
    norm_log: Counter = dataclasses.field(default_factory=Counter)
    rechazos: list[dict] = dataclasses.field(default_factory=list)


# ─── Modelos Pydantic ──────────────────────────────────────────────────────

class Requisito(BaseModel):
    model_config = {"populate_by_name": True}

    nombre: str
    categoria: Literal["juridico", "financiero", "tecnico", "experiencia", "documental"] = Field(
        validation_alias=AliasChoices("categoria", "tipo", "tipo_de_requisito", "clase")
    )
    exigido_literal: str = Field(
        validation_alias=AliasChoices("exigido_literal", "cita", "cita_literal", "texto_literal")
    )
    fuente_numeral: str = Field(
        validation_alias=AliasChoices("fuente_numeral", "numeral", "seccion", "fuente")
    )
    fuente_documento: str = "pliego"
    aplica_a: Literal["todos", "mipyme", "no_mipyme", "extranjero_sin_domicilio"] = Field(
        default="todos",
        validation_alias=AliasChoices("aplica_a", "aplica_para", "aplica"),
    )
    valor_umbral: float | None = Field(
        default=None,
        validation_alias=AliasChoices("valor_umbral", "umbral", "minimo", "mínimo"),
    )
    operador: Literal[">=", "<=", "==", "!="] | None = None
    unidad: str | None = None
    subsanable: bool | None = None
    cita_verificada: bool = False
    cita_verificada_parcial: bool = False   # primeros 60 chars normalizados existen
    # ── Clasificación de impacto ─────────────────────────────────────────────
    # Default "indeterminado": un requisito que no pasó por clasificador.py es
    # DESCONOCIDO, no habilitante. Con default "habilitante" un pliego sin
    # clasificar producía 218 falsos habilitantes y un score inflado en silencio.
    # [C3] clasificador.py asigna el valor real; este default sólo debe sobrevivir
    # cuando la clasificación no corrió — y entonces debe ser visible.
    criticidad: Literal["habilitante", "puntaje", "procedimental", "indeterminado"] = "indeterminado"
    evidencia_criticidad: Literal[
        "capitulo_habilitantes", "limitacion_participacion",
        "causal_rechazo", "capitulo_presentacion", "capitulo_puntaje", "inferido"
    ] | None = None
    tiene_plazo: bool = False
    # ── Consolidación (asignado por clasificador.py, no por el modelo LLM) ──
    numerales_fuentes: list[str] = Field(default_factory=list)
    # [B8] Fusión de fragmentos: el primario aporta identidad, pero el umbral
    # puede venir de cualquier miembro del grupo. Estos campos preservan de
    # dónde salió y qué pasa cuando hay más de un umbral distinto.
    fuente_umbral_numeral: str | None = None   # numeral del miembro que aportó el umbral
    umbrales_alternativos: list[dict] = Field(default_factory=list)
    conflicto_umbral: bool = False             # True ⇒ el evaluador NO debe evaluar
    # Nombres de los requisitos absorbidos al fusionar. Sin esto el nombre
    # desaparece del informe y el operador cree que el sistema no lo detectó
    # (caso real: "inhabilidades" absorbida en "Capacidad jurídica").
    nombres_absorbidos: list[str] = Field(default_factory=list)
    # True si la propia entidad lista este requisito como causal de rechazo en 1.15
    es_causal_rechazo_explicita: bool = False
    # ── Campos de análisis (asignados programáticamente, no por el modelo) ──
    pagina_origen: int | None = None
    estado_verificacion: Literal["verificada", "degradada", "no_verificada"] = "no_verificada"
    motivo_degradacion: str | None = None
    # ── Internos ─────────────────────────────────────────────────────────────
    chunk_idx: int | None = None
    origen: str = "extraccion"   # "extraccion" | "probable_indice"
    # Criterio estructurado de evaluación (None = usar lookup por nombre en evaluator)
    criterio: Criterio | None = Field(default=None)


class ResultadoExtraccion(BaseModel):
    entidad_publica: str
    numero_proceso: str
    requisitos: list[Requisito]
    checklist_no_encontrados: list[str]
    hallazgos_fuera_de_checklist: list[str]
    chunks_procesados: int
    chunks_totales: int
    # backward compat: siempre = chunks_truncados + chunks_error_json
    truncamientos: list[str]
    # ── campos diagnóstico (con defaults para no romper constructores existentes) ─
    chunks_truncados: list[str] = Field(default_factory=list)
    chunks_error_json: list[str] = Field(default_factory=list)
    requisitos_rechazados: list[dict] = Field(default_factory=list)
    aliases_activados: dict = Field(default_factory=dict)
    normalizaciones_aplicadas: dict = Field(default_factory=dict)
    chunks_advertencia_indice: list[int] = Field(default_factory=list)
    metadatos_corrida: dict = Field(default_factory=dict)


# ─── Configuración API ─────────────────────────────────────────────────────

_MODEL = "claude-sonnet-4-6"
# extra_body={'temperature': 0.0} funciona con la línea 4.6/4.5. Opus 4.7+ y
# Sonnet 5 rechazan valores no-default. Al migrar de modelo hay que quitarlo.
# El SDK anthropic 1.x quitó temperature de la firma, no de la API: pasarlo por
# extra_body conserva el determinismo del baseline (ver ESTADO_PIPELINE.md).
_MAX_TOKENS = 8_000        # fusible — no presupuesto
_ALERT_USO_PCT = 0.60


# ─── Prompt: parte constante (cacheable) y variable (por chunk) ────────────

def _limpiar_md(texto: str) -> str:
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


def _build_sistema() -> list[dict]:
    """
    Parte CONSTANTE del prompt — candidata a caché de API.
    Incluye reglas, ejemplos de errores reales y schema de salida.
    Objetivo: >= 1 024 tokens para activar prompt caching en claude-sonnet.
    """
    checklist_str = "\n".join(f"  - {item}" for item in CHECKLIST_CCE)
    texto = f"""Eres un extractor de requisitos habilitantes de pliegos de contratación pública colombiana.

REGLAS ABSOLUTAS — ninguna excepción:
1. exigido_literal DEBE ser una cita textual verbatim del fragmento. Prohibido parafrasear o resumir. Cita la oración o cláusula exacta que contiene la exigencia, NO el párrafo completo. Longitud objetivo: ≤200 caracteres. Si la oración supera 200 caracteres, cita desde el verbo modal (debe, deberá, acreditará) hasta el punto final de esa oración.
2. Si un valor numérico (umbral, porcentaje, monto, plazo) no aparece literalmente en el fragmento: valor_umbral=null. PROHIBIDO completar con valores de normas externas (Res. 196/2016, Decreto 1082, Ley 80, etc.). Un campo null es correcto. Un valor inventado es un error grave.
3. subsanable=true solo si el fragmento lo dice EXPLÍCITAMENTE. Si no lo menciona: null.
4. Prohibido evaluar si el proponente cumple o no cumple. Tu tarea es solo extraer hechos del texto.
5. Si este fragmento no contiene requisitos habilitantes, retorna requisitos=[].
6. criticidad clasifica el impacto del requisito:
   - "habilitante": su incumplimiento impide ofertar. Incluye capacidad jurídica, financiera, técnica, experiencia y garantía de seriedad.
   - "puntaje": afecta la calificación pero no habilita (criterio de evaluación). Ejemplo: factor de calidad, mayor experiencia, propuesta técnica valorable.
   - "procedimental": plazos, formatos y reglas de trámite que no eliminan ni puntúan. Ejemplo: plazo de subsanación, formato de presentación, número de copias.
   En caso de duda entre habilitante y procedimental: clasifica como "habilitante". Nunca omitir este campo.

EJEMPLOS — QUÉ NO HACER (errores reales de corridas anteriores):

EJEMPLO 1 — No completar valores desde normativa externa
  Fragmento real: "El proponente debe acreditar un índice de liquidez conforme a la normativa vigente."
  MAL → valor_umbral: 1.21, operador: ">="
        El valor 1.21 proviene de la Resolución 196/2016, que NO está en este fragmento.
        Completar desde norma externa es una alucinación con consecuencias legales.
  BIEN → valor_umbral: null, operador: null
  JSON correcto:
    {{"nombre": "Índice de liquidez", "categoria": "financiero",
      "exigido_literal": "El proponente debe acreditar un índice de liquidez conforme a la normativa vigente.",
      "fuente_numeral": "...", "fuente_documento": "pliego", "aplica_a": "todos",
      "valor_umbral": null, "operador": null, "unidad": null, "subsanable": null}}
  Regla: si el número no está en ESTE fragmento, es null. Siempre. La norma puede establecerlo
  en otro lugar — no te corresponde buscarlo ni inferirlo.

EJEMPLO 2 — Texto ilegible por OCR no se reconstruye
  Fragmento real: "Índice de liquidez = )+*!9- :-;;!4*4 %/5!9- :-;;!4*4"
  MAL → exigido_literal: "Activo Corriente / Pasivo Corriente"
        Inventar la fórmula desde conocimiento externo es alucinación.
  MAL → exigido_literal con el texto corrupto ()+*!9- etc.) tal cual.
  BIEN → usar el texto legible circundante al fragmento corrupto.
  JSON correcto:
    {{"nombre": "Índice de liquidez", "categoria": "financiero",
      "exigido_literal": "El proponente debe acreditar un índice de liquidez",
      "fuente_numeral": "...", "fuente_documento": "pliego", "aplica_a": "todos",
      "valor_umbral": null, "operador": null, "unidad": null, "subsanable": null}}
  Regla: OCR corrupto no se reconstruye ni se adivina. Usar solo texto limpio y legible.

EJEMPLO 3 — Entradas de tabla de contenido no son requisitos
  Fragmento real: "3.2 CAPACIDAD JURÍDICA.................................. 15"
  MAL → {{"nombre": "Capacidad jurídica", "exigido_literal": "3.2 CAPACIDAD JURÍDICA..... 15", ...}}
        Una línea de índice no exige nada — es solo una referencia de navegación.
  BIEN → requisitos: []  (respuesta completamente vacía)
  JSON correcto:
    {{"entidad_publica": "", "numero_proceso": "", "requisitos": [],
      "checklist_encontrado": [], "hallazgos_fuera_de_checklist": []}}
  Regla: título + puntos guía + número de página = entrada de índice/TOC, no una exigencia.
  Un texto que EXIGE algo usa verbos explícitos: "debe", "deberá", "es obligatorio", "se requiere",
  "acreditará", "aportará". Una línea de índice nunca exige nada.

CARRIL A — CHECKLIST CCE:
Solo marca presente si hay texto claro que lo exige en el fragmento. No marques por inferencia.
Responde SOLO los ítems encontrados en checklist_encontrado — omite completamente los ausentes:
{checklist_str}

CARRIL B — HALLAZGOS ADICIONALES:
Cualquier exigencia que NO esté en el checklist anterior.

Responde ÚNICAMENTE con JSON válido, sin texto antes ni después:
{{
    "entidad_publica": "nombre de la entidad si aparece en este fragmento, string vacío si no",
    "numero_proceso": "número del proceso si aparece, string vacío si no",
    "requisitos": [
        {{
            "nombre": "nombre corto del requisito",
            "categoria": "juridico|financiero|tecnico|experiencia|documental",
            "exigido_literal": "cita textual exacta del fragmento",
            "fuente_numeral": "numeral de la sección",
            "fuente_documento": "pliego",
            "aplica_a": "todos|mipyme|no_mipyme",
            "valor_umbral": numero_o_null,
            "operador": ">=|<=|==|!= o null",
            "unidad": "smmlv|veces|pesos|contratos|meses o null",
            "subsanable": true_false_o_null,
            "criticidad": "habilitante|puntaje|procedimental"
        }}
    ],
    "checklist_encontrado": ["SOLO nombres de ítems CCE PRESENTES — omite los ausentes"],
    "hallazgos_fuera_de_checklist": ["exigencias adicionales no cubiertas por el checklist"]
}}"""
    return [{"type": "text", "text": texto, "cache_control": {"type": "ephemeral"}}]


_SISTEMA_CONSTANTE: list[dict] = _build_sistema()


def _prompt_usuario(chunk: dict) -> str:
    """Parte VARIABLE del prompt — cambia por chunk."""
    meta = chunk["metadata"]
    cap = meta.get("capitulo", "")
    sub = meta.get("subcapitulo", "")
    num = meta.get("numeral", "")
    ubicacion = " > ".join(p for p in [cap, sub, num] if p) or "(sin encabezado)"
    return f"SECCIÓN: {ubicacion}\n\nFRAGMENTO:\n---\n{chunk['texto']}\n---"


# ─── helpers privados ──────────────────────────────────────────────────────

def _mapear_alias(d: dict, log: Counter) -> dict:
    """
    Remap alias keys → canonical. Registra cada activación en log.
    No remplaza si la clave canónica ya existe (el modelo a veces envía ambas).
    """
    resultado: dict = {}
    for k, v in d.items():
        canonical = _ALIAS_CAMPOS.get(k)
        if canonical and canonical not in d:
            resultado[canonical] = v
            log[k] += 1
        else:
            resultado[k] = v
    return resultado


def _normalizar_semantico(d: dict, log: Counter) -> dict:
    """Normaliza valores de categoria, aplica_a y operador. Registra cambios en log."""
    resultado = dict(d)

    if "categoria" in resultado:
        val = str(resultado["categoria"])
        norm_key = _norm_id(val)
        if norm_key in _MAP_CATEGORIA:
            normalizado = _MAP_CATEGORIA[norm_key]
            if normalizado != val:
                log[val] += 1
            resultado["categoria"] = normalizado

    if "aplica_a" in resultado:
        val = str(resultado["aplica_a"])
        norm_key = _norm_id(val)
        if norm_key in _MAP_APLICA_A:
            normalizado = _MAP_APLICA_A[norm_key]
            if normalizado != val:
                log[val] += 1
            resultado["aplica_a"] = normalizado

    if "operador" in resultado:
        val = str(resultado["operador"])
        if val in _MAP_OPERADOR:
            normalizado = _MAP_OPERADOR[val]
            if normalizado != val:
                log[val] += 1
            resultado["operador"] = normalizado

    return resultado


def _requisito_de_dict(
    r: dict,
    chunk: dict,
    chunk_idx: int | None = None,
    ctx: _ExtraccionCtx | None = None,
) -> Requisito | None:
    """
    Construye un Requisito desde la respuesta del modelo.
    [I5] fuente_numeral del chunk tiene precedencia sobre la del modelo.
    [1.1] Remap de alias con tracking en ctx.
    [1.2] Normalización semántica con tracking en ctx.
    [1.3] Rechazos van a ctx.rechazos — nunca silencio.
    """
    if ctx is None:
        ctx = _ExtraccionCtx()

    meta = chunk["metadata"]

    # 1. Remap alias
    r = _mapear_alias(dict(r), ctx.alias_log)

    # 2. Normalización semántica
    r = _normalizar_semantico(r, ctx.norm_log)

    # 3. [I5] fuente_numeral del chunk tiene precedencia
    fuente_num = (
        meta.get("numeral")
        or meta.get("subcapitulo")
        or meta.get("capitulo")
        or r.get("fuente_numeral", "sin_numeral")
    )
    r["fuente_numeral"] = fuente_num
    r["fuente_documento"] = r.get("fuente_documento", "pliego")

    # 4. Validar con Pydantic — rechazos van a ctx.rechazos, nunca silencio
    campos_validos = {k: v for k, v in r.items() if k in Requisito.model_fields}
    try:
        req = Requisito(**campos_validos)
        req.chunk_idx = chunk_idx
        req.origen = "extraccion"
        return req
    except ValidationError as exc:
        ctx.rechazos.append({
            "chunk_idx": chunk_idx,
            "dict_crudo": r,
            "motivo": str(exc),
        })
        return None
    except Exception as exc:
        ctx.rechazos.append({
            "chunk_idx": chunk_idx,
            "dict_crudo": r,
            "motivo": f"{type(exc).__name__}: {exc}",
        })
        return None


def _llamar(
    client: anthropic.Anthropic,
    chunk: dict,
    idx: int,
    sistema: list[dict] | None = None,
) -> dict:
    """
    [I2] stop_reason se verifica ANTES de json.loads.
    [1.5] Itera resp.content buscando type=='text' — nunca usa content[0] directamente.
    [2.4] Usa system prompt separado para prompt caching; reporta cache tokens.
    Retry x2 con backoff exponencial para errores de red transitorios (ProxyError, 503).
    """
    import time as _time

    if sistema is None:
        sistema = _SISTEMA_CONSTANTE

    # CASO B: tablas markdown pueden generar más output — fusible extendido
    max_tokens_chunk = (
        16_000 if chunk.get("metadata", {}).get("tipo_contenido") == "tabla_markdown"
        else _MAX_TOKENS
    )

    _MAX_INTENTOS = 3
    for intento in range(_MAX_INTENTOS):
        try:
            resp = client.messages.create(
                model=_MODEL,
                max_tokens=max_tokens_chunk,
                extra_body={"temperature": 0.0},
                system=sistema,
                messages=[{"role": "user", "content": _prompt_usuario(chunk)}],
            )
            break  # éxito — salir del loop de reintentos
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            if intento == _MAX_INTENTOS - 1:
                raise
            espera = 15 * (2 ** intento)  # 15s, 30s
            print(
                f"\n  [RETRY {intento+1}/{_MAX_INTENTOS-1}] chunk_{idx} — "
                f"{type(exc).__name__}: {str(exc)[:80]}. Reintento en {espera}s...",
                flush=True,
            )
            _time.sleep(espera)

    _cr = getattr(resp.usage, "cache_creation_input_tokens", None)
    _rd = getattr(resp.usage, "cache_read_input_tokens", None)
    cache_creation = _cr if isinstance(_cr, int) else 0
    cache_read = _rd if isinstance(_rd, int) else 0

    uso_pct = resp.usage.output_tokens / max_tokens_chunk
    if uso_pct > _ALERT_USO_PCT:
        print(
            f"\n  [ALERTA] chunk_{idx}: {resp.usage.output_tokens}/{max_tokens_chunk} tokens "
            f"({uso_pct:.0%}) — acercándose al fusible",
            flush=True,
        )

    # [I2] stop_reason ANTES de parsear
    if resp.stop_reason == "max_tokens":
        return {
            "estado": "truncado",
            "chunk_idx": idx,
            "output_tokens": resp.usage.output_tokens,
            "input_tokens": resp.usage.input_tokens,
            "cache_creation_tokens": cache_creation,
            "cache_read_tokens": cache_read,
        }

    # [1.5] Buscar bloque de texto defensivamente — hay modelos que devuelven thinking first
    texto: str | None = None
    for bloque in resp.content:
        if getattr(bloque, "type", None) == "text":
            texto = bloque.text
            break

    if texto is None:
        return {
            "estado": "json_error",
            "chunk_idx": idx,
            "error": "No se encontró bloque type='text' en resp.content",
            "crudo_inicio": "",
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cache_creation_tokens": cache_creation,
            "cache_read_tokens": cache_read,
        }

    try:
        datos = json.loads(_limpiar_md(texto))
    except json.JSONDecodeError as exc:
        return {
            "estado": "json_error",
            "chunk_idx": idx,
            "error": str(exc),
            "crudo_inicio": texto[:200],
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cache_creation_tokens": cache_creation,
            "cache_read_tokens": cache_read,
        }

    return {
        "estado": "ok",
        "datos": datos,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_creation_tokens": cache_creation,
        "cache_read_tokens": cache_read,
    }


# ─── helpers de post-proceso ───────────────────────────────────────────────

def _asignar_paginas_origen(
    requisitos: list[Requisito],
    chunks: list[dict],
    markdown: str,
) -> None:
    """
    Asigna pagina_origen a cada requisito localizando su chunk en el markdown.

    Funciona cuando el markdown usa separadores --- entre páginas (Claude OCR).
    Si el markdown tiene < 2 separadores (marker output), no modifica nada.
    La estimación es de baja granularidad: asigna la página donde COMIENZA
    el chunk, aunque el requisito pueda estar más adelante dentro del chunk.
    """
    n_sep_total = markdown.count("\n---\n")
    if n_sep_total < 2:
        return

    mapa: dict[int, int] = {}
    for idx, chunk in enumerate(chunks):
        muestra = chunk["texto"].strip()[:100]
        if not muestra:
            continue
        pos = markdown.find(muestra)
        if pos >= 0:
            n_sep_antes = markdown[:pos].count("\n---\n")
            mapa[idx] = n_sep_antes + 1  # páginas 1-indexed

    for req in requisitos:
        if req.chunk_idx is not None and req.chunk_idx in mapa:
            req.pagina_origen = mapa[req.chunk_idx]


# ─── API pública ───────────────────────────────────────────────────────────

def extraer(
    markdown: str,
    chunks: list[dict],
    api_key: str | None = None,
    ruta_salida: Path | None = None,
    pliego_sha256: str = "",
) -> ResultadoExtraccion:
    """
    Extrae requisitos habilitantes de TODOS los chunks.

    [I1] Ningún chunk se filtra ni se salta.
    [I3] Sin límite en el número de requisitos.
    [I6] El modelo extrae hechos; nunca compara ni puntúa.
    [I9] ruta_salida es obligatoria en producción — el orquestador
         valida la ruta como escribible ANTES de invocar (pre-gasto).
         Si el guardado final falla → IOError, no advertencia silenciosa.

    Parámetros:
      ruta_salida:   si se provee, guarda resultado.model_dump_json() en esa ruta.
      pliego_sha256: SHA256 del PDF de origen; se guarda en metadatos_corrida para
                     permitir que artefactos.py identifique el resultado sin ambigüedad.
    """
    client = anthropic.Anthropic(
        api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
        timeout=120.0,  # 120s — chunks grandes (1.15 causales) generan respuestas largas
        max_retries=0,  # reintentos propios en _llamar con backoff controlado
    )
    ctx = _ExtraccionCtx()

    todos_requisitos: list[Requisito] = []
    checklist_encontrado: set[str] = set()
    todos_hallazgos: list[str] = []
    chunks_truncados: list[str] = []
    chunks_error_json: list[str] = []
    entidad = ""
    numero = ""
    tokens_in_total = 0
    tokens_out_total = 0
    cache_creation_total = 0
    cache_read_total = 0

    for idx, chunk in enumerate(chunks):
        nd = chunk["metadata"].get("numeral_derivado") or ""
        cap_breve = (
            chunk["metadata"].get("numeral")
            or chunk["metadata"].get("subcapitulo")
            or chunk["metadata"].get("capitulo")
            or ""
        )[:30]
        print(
            f"  [{idx + 1:>3}/{len(chunks)}] {len(chunk['texto']):>6} chars"
            f"  {nd:8s}  {cap_breve!r}",
            end=" ", flush=True,
        )

        res = _llamar(client, chunk, idx)
        tokens_in_total += res.get("input_tokens", 0)
        tokens_out_total += res.get("output_tokens", 0)
        cache_creation_total += res.get("cache_creation_tokens", 0)
        cache_read_total += res.get("cache_read_tokens", 0)

        if res["estado"] == "truncado":
            chunks_truncados.append(f"chunk_{idx}")
            print("TRUNCADO")
            continue

        if res["estado"] == "json_error":
            chunks_error_json.append(f"chunk_{idx}")
            print(f"JSON_ERROR — {res.get('error', '')[:60]}")
            continue

        datos = res["datos"]

        if not entidad:
            entidad = datos.get("entidad_publica", "")
        if not numero:
            numero = datos.get("numero_proceso", "")

        n_req = 0
        for r in datos.get("requisitos", []):
            req = _requisito_de_dict(r, chunk, idx, ctx)
            if req is not None:
                todos_requisitos.append(req)
                n_req += 1

        checklist_encontrado.update(datos.get("checklist_encontrado", []))
        todos_hallazgos.extend(datos.get("hallazgos_fuera_de_checklist", []))
        print(f"ok ({n_req} req)")

    checklist_no_enc = [item for item in CHECKLIST_CCE if item not in checklist_encontrado]
    truncamientos_combinados = chunks_truncados + chunks_error_json
    costo_usd = tokens_in_total / 1e6 * 3 + tokens_out_total / 1e6 * 15

    print(
        f"\n  Tokens: {tokens_in_total:,} in / {tokens_out_total:,} out"
        f"  |  caché creado: {cache_creation_total:,} / leído: {cache_read_total:,}"
        f"  |  costo: ${costo_usd:.4f} USD"
    )

    if ctx.rechazos:
        print(f"  [BLINDAJE] {len(ctx.rechazos)} requisitos rechazados por Pydantic")
    if ctx.alias_log:
        print(f"  [BLINDAJE] aliases activados: {dict(ctx.alias_log)}")
    if ctx.norm_log:
        print(f"  [BLINDAJE] normalizaciones: {dict(ctx.norm_log)}")

    # [I5] Asignar pagina_origen usando separadores del OCR Claude
    _asignar_paginas_origen(todos_requisitos, chunks, markdown)

    metadatos = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "modelo": _MODEL,
        "tokens_in": tokens_in_total,
        "tokens_out": tokens_out_total,
        "cache_creation_tokens": cache_creation_total,
        "cache_read_tokens": cache_read_total,
        "costo_usd": round(costo_usd, 6),
        "chunks_totales": len(chunks),
        "n_chunks_truncados": len(chunks_truncados),
        "n_chunks_error_json": len(chunks_error_json),
        "n_requisitos_rechazados": len(ctx.rechazos),
        "pliego_sha256": pliego_sha256,
    }

    resultado = ResultadoExtraccion(
        entidad_publica=entidad,
        numero_proceso=numero,
        requisitos=todos_requisitos,
        checklist_no_encontrados=checklist_no_enc,
        hallazgos_fuera_de_checklist=list(dict.fromkeys(todos_hallazgos)),
        chunks_procesados=len(chunks) - len(truncamientos_combinados),
        chunks_totales=len(chunks),
        truncamientos=truncamientos_combinados,    # backward compat
        chunks_truncados=chunks_truncados,
        chunks_error_json=chunks_error_json,
        requisitos_rechazados=ctx.rechazos,
        aliases_activados=dict(ctx.alias_log),
        normalizaciones_aplicadas=dict(ctx.norm_log),
        metadatos_corrida=metadatos,
    )

    # [I9] persistir ANTES de retornar — error fatal si falla
    if ruta_salida is not None:
        ruta_salida = Path(ruta_salida)
        try:
            ruta_salida.parent.mkdir(parents=True, exist_ok=True)
            ruta_salida.write_text(
                resultado.model_dump_json(indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            raise IOError(
                f"[I9] No se pudo guardar resultado en '{ruta_salida}': {exc}"
            ) from exc

    return resultado
