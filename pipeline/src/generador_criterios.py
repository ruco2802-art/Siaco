# -*- coding: utf-8 -*-
"""
pipeline/src/generador_criterios.py — Convierte texto de requisitos en objetos Criterio.

Pipeline A → E (sin API hasta confirmar con el usuario — ver ESTADO_PIPELINE.md):
  A. Pre-clasificación heurística (sin API)
  B. Llamada al LLM con skill generacion_criterios.md
  C. Resolución de variables (resolucion_variables.py, sin API)
  D. Precedencia de umbrales: PLIEGO > CATÁLOGO CCE > no_disponible
  E. Validación AST de expresiones (criterios.py, sin API)

Invariantes:
  [I6]  Toda aritmética en Python puro. El LLM extrae estructura; no calcula.
  [I-G1] Skill faltante → FileNotFoundError explícito, sin fallback silencioso.
  [I-G2] Variable no resuelta → criterio=None, requisito preservado + fallo_log.
  [I-G3] AST inválida → criterio=None, requisito preservado + fallo_log.
  [I-G4] Umbral null en CCE Y ausente en pliego → "umbral_no_definido_en_pliego".
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import anthropic

from .criterios import (
    Booleano,
    Criterio,
    ExpresionNoPermitidaError,
    Formula,
    TablaTramos,
    Tramo,
    UmbralSimple,
    Variable,
    evaluar_expresion,
)
from .extractor import Requisito
from .fallo_log import registrar_fallo
from .resolucion_variables import (
    ResultadoResolucion,
    _PERFIL_CAMPOS,
    extraer_nombres_de_expresion,
    resolver_variable,
)

# ─── Rutas ───────────────────────────────────────────────────────────────────

_RAIZ_PIPELINE = Path(__file__).parent.parent
_SKILL_PATH    = _RAIZ_PIPELINE / "skills" / "generacion_criterios.md"

# ─── Resultado del generador ──────────────────────────────────────────────────

EstadoEstructuracion = Literal[
    "ok",
    "fallo",
    "umbral_no_definido_en_pliego",
]


@dataclass
class ResultadoGeneracion:
    criterio:              Criterio | None
    estado:                EstadoEstructuracion
    razon_fallo:           str | None = None
    fuente_umbral:         Literal["pliego", "catalogo_cce", "formula_universal", "no_disponible"] | None = None
    valor_ref_cce:         float | None = None
    difiere_de_cce:        dict | None = None   # {"valor_cce": float, "tendencia": "mas_estricto"|"menos_estricto"}
    variables_ambiguas:    list[str] = field(default_factory=list)


# ─── Carga del skill ──────────────────────────────────────────────────────────

def _cargar_skill() -> str:
    """
    [I-G1] Carga la skill desde disco. Error explícito si falta el archivo.
    Sin fallback: un prompt inventado causa extracción incorrecta.
    """
    if not _SKILL_PATH.exists():
        raise FileNotFoundError(
            f"[GENERADOR] Skill no encontrada: {_SKILL_PATH}\n"
            "Crea el archivo pipeline/skills/generacion_criterios.md antes de continuar."
        )
    return _SKILL_PATH.read_text(encoding="utf-8")


# ─── Llamada al LLM (separada para facilitar mock en tests) ──────────────────

def _llamar_llm(
    texto_requisito: str,
    skill_texto: str,
    client: anthropic.Anthropic,
) -> dict:
    """
    Llama al LLM con el skill de generación de criterios.
    Retorna dict con los campos del criterio o {"error": ...} si falla.

    Mantenemos temperatura=0 y max_tokens bajo porque el output es JSON compacto.
    """
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2_000,
        extra_body={"temperature": 0.0},
        system=[{"type": "text", "text": skill_texto, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": texto_requisito}],
    )

    # stop_reason primero (I2)
    if resp.stop_reason == "max_tokens":
        return {"error": "respuesta truncada (max_tokens)", "stop_reason": "max_tokens"}

    texto: str | None = None
    for bloque in resp.content:
        if getattr(bloque, "type", None) == "text":
            texto = bloque.text
            break

    if texto is None:
        return {"error": "no hay bloque text en resp.content"}

    # Limpiar markdown si el modelo añade ```json
    limpio = texto.strip()
    if "```" in limpio:
        for frag in limpio.split("```")[1::2]:
            frag = frag.strip()
            if frag.lower().startswith("json"):
                frag = frag[4:].strip()
            if frag:
                limpio = frag
                break

    try:
        return json.loads(limpio)
    except json.JSONDecodeError as exc:
        return {"error": f"json_invalido: {exc}", "crudo": texto[:300]}


# ─── Resolución de campo_perfil para tipos no-Formula ────────────────────────

def _resolver_campo_perfil(valor_llm: str) -> str | None:
    """
    Convierte el campo_perfil devuelto por el LLM a su ruta canónica.
    Acepta: ruta canónica, nombre corto, abreviatura conocida.
    Devuelve None si no se puede resolver.
    """
    if valor_llm in _PERFIL_CAMPOS:
        return _PERFIL_CAMPOS[valor_llm]

    # intentar como abreviatura
    res = resolver_variable(valor_llm)
    if res.fuente == "perfil" and res.campo:
        return res.campo

    return None


# ─── Búsqueda en catálogo CCE ─────────────────────────────────────────────────

def _buscar_en_cce(
    campo_perfil: str,
    modalidad: str | None,
    variante: str | None,
    catalogo: dict,
) -> float | None:
    """
    Devuelve el valor CCE para un indicador/modalidad/variante.
    Estructura esperada de catalogo (estructura_normativa.json["modalidades"]):
      catalogo[modalidad]["indicadores_obligatorios"][*]["id"] == campo_corto
      con "valor" o "por_variante.{variante}.valor"
    """
    if not modalidad or not catalogo:
        return None

    modalidad_data = catalogo.get("modalidades", {}).get(modalidad)
    if not modalidad_data:
        return None

    # campo_perfil tiene forma "financiero.indice_liquidez" — tomamos la parte derecha
    campo_corto = campo_perfil.split(".")[-1]

    for ind in modalidad_data.get("indicadores_obligatorios", []):
        if ind.get("id") != campo_corto:
            continue
        # Intento con por_variante
        if variante and "por_variante" in ind:
            return ind["por_variante"].get(variante, {}).get("valor")
        # Valor directo
        v = ind.get("valor")
        return v if isinstance(v, (int, float)) else None

    return None


# ─── Provenance ───────────────────────────────────────────────────────────────

def _calcular_provenance(
    valor_pliego: float | None,
    campo_perfil: str,
    modalidad: str | None,
    variante: str | None,
    catalogo: dict | None,
    operador: str | None,
) -> tuple[
    Literal["pliego", "catalogo_cce", "formula_universal", "no_disponible"],
    float | None,  # valor final a usar
    float | None,  # valor_ref_cce
    dict | None,   # difiere_de_cce
    EstadoEstructuracion,
]:
    """
    Aplica la precedencia: PLIEGO > CATÁLOGO CCE > no_disponible.
    Retorna: (fuente, valor_final, valor_ref_cce, difiere_de_cce, estado)
    """
    valor_cce = _buscar_en_cce(campo_perfil, modalidad, variante, catalogo or {})

    if valor_pliego is not None:
        # El pliego fija el umbral
        difiere: dict | None = None
        if valor_cce is not None and operador:
            if operador in (">=", ">"):
                tendencia = "mas_estricto" if valor_pliego > valor_cce else (
                    "menos_estricto" if valor_pliego < valor_cce else "igual"
                )
            elif operador in ("<=", "<"):
                tendencia = "mas_estricto" if valor_pliego < valor_cce else (
                    "menos_estricto" if valor_pliego > valor_cce else "igual"
                )
            else:
                tendencia = "igual" if valor_pliego == valor_cce else "diferente"
            if tendencia != "igual":
                difiere = {"valor_cce": valor_cce, "tendencia": tendencia}
        return ("pliego", valor_pliego, valor_cce, difiere, "ok")

    if valor_cce is not None:
        return ("catalogo_cce", valor_cce, valor_cce, None, "ok")

    # Null en CCE Y ausente en pliego → caso 7 (pendiente_deteccion_irregularidades)
    return ("no_disponible", None, None, None, "umbral_no_definido_en_pliego")


# ─── Parseo por tipo ──────────────────────────────────────────────────────────

def _parsear_umbral_simple(
    raw: dict,
    req: Requisito,
    modalidad: str | None,
    variante: str | None,
    catalogo: dict | None,
) -> ResultadoGeneracion:
    campo_llm = raw.get("campo_perfil", "")
    campo = _resolver_campo_perfil(campo_llm)
    if not campo:
        return ResultadoGeneracion(
            criterio=None,
            estado="fallo",
            razon_fallo=f"campo_perfil '{campo_llm}' no resuelto a ruta canónica",
        )

    operador = raw.get("operador")
    valor_pliego = raw.get("valor")
    if isinstance(valor_pliego, str):
        try:
            valor_pliego = float(valor_pliego)
        except ValueError:
            valor_pliego = None

    fuente, valor_final, valor_ref_cce, difiere, estado = _calcular_provenance(
        valor_pliego, campo, modalidad, variante, catalogo, operador
    )

    if valor_final is None:
        return ResultadoGeneracion(
            criterio=None,
            estado=estado,
            fuente_umbral=fuente,
            valor_ref_cce=valor_ref_cce,
        )

    try:
        criterio = UmbralSimple(
            campo_perfil=campo,
            operador=operador or ">=",
            valor=valor_final,
            fuente_numeral=req.fuente_numeral,
            pagina_origen=req.pagina_origen,
            confianza=raw.get("confianza", "media"),
        )
    except Exception as exc:
        return ResultadoGeneracion(criterio=None, estado="fallo", razon_fallo=str(exc))

    return ResultadoGeneracion(
        criterio=criterio,
        estado=estado,
        fuente_umbral=fuente,
        valor_ref_cce=valor_ref_cce,
        difiere_de_cce=difiere,
    )


def _parsear_formula(
    raw: dict,
    req: Requisito,
    catalogo: dict | None,
) -> ResultadoGeneracion:
    expr_empresa = raw.get("expresion_empresa") or ""
    expr_umbral  = raw.get("expresion_umbral") or ""
    operador     = raw.get("operador", ">=")

    # Resolución de variables — usar la lista del LLM si existe, sino extraer de expresiones
    vars_llm: list[dict] = raw.get("variables", [])
    nombres_en_exprs = list(dict.fromkeys(
        extraer_nombres_de_expresion(expr_empresa)
        + extraer_nombres_de_expresion(expr_umbral)
    ))

    # Construir mapa nombre→fuente desde la lista del LLM
    fuente_por_nombre: dict[str, Literal["perfil", "pliego"]] = {}
    for v in vars_llm:
        nombre = v.get("nombre", "")
        f = v.get("fuente", "perfil")
        if nombre and f in ("perfil", "pliego"):
            fuente_por_nombre[nombre] = f   # type: ignore[assignment]

    variables_resueltas: list[Variable] = []
    variables_ambiguas: list[str] = []

    for nombre in nombres_en_exprs:
        fuente_inf: Literal["perfil", "pliego"] = fuente_por_nombre.get(nombre, "perfil")
        res: ResultadoResolucion = resolver_variable(nombre, fuente_inf)
        if res.fuente == "no_resuelta":
            return ResultadoGeneracion(
                criterio=None,
                estado="fallo",
                razon_fallo=f"variable_no_resuelta: {res.motivo_no_resuelta}",
            )
        if res.es_ambigua:
            variables_ambiguas.append(nombre)
        variables_resueltas.append(
            Variable(nombre=nombre, fuente=res.fuente, campo=res.campo or "")   # type: ignore[arg-type]
        )

    # Validación AST — E (invariante I6)
    dummy_ns = {v.nombre: 1.0 for v in variables_resueltas}
    for label, expr in [("expresion_empresa", expr_empresa), ("expresion_umbral", expr_umbral)]:
        try:
            evaluar_expresion(expr, dummy_ns)
        except ExpresionNoPermitidaError as exc:
            return ResultadoGeneracion(
                criterio=None,
                estado="fallo",
                razon_fallo=f"expresion_no_soportada en {label}: {exc}",
            )

    try:
        criterio = Formula(
            expresion_empresa=expr_empresa,
            operador=operador,
            expresion_umbral=expr_umbral,
            variables=variables_resueltas,
            descripcion=raw.get("descripcion"),
            fuente_numeral=req.fuente_numeral,
            pagina_origen=req.pagina_origen,
            confianza=raw.get("confianza", "media"),
        )
    except Exception as exc:
        return ResultadoGeneracion(criterio=None, estado="fallo", razon_fallo=str(exc))

    return ResultadoGeneracion(
        criterio=criterio,
        estado="ok",
        fuente_umbral="formula_universal",
        variables_ambiguas=variables_ambiguas,
    )


def _parsear_tabla_tramos(
    raw: dict,
    req: Requisito,
) -> ResultadoGeneracion:
    campo_llm = raw.get("campo_perfil", "")
    campo = _resolver_campo_perfil(campo_llm)
    if not campo:
        return ResultadoGeneracion(
            criterio=None,
            estado="fallo",
            razon_fallo=f"campo_perfil '{campo_llm}' no resuelto en tabla_tramos",
        )

    naturaleza = raw.get("naturaleza", "habilitante")
    if naturaleza not in ("puntaje", "habilitante"):
        naturaleza = "habilitante"

    tramos_raw: list[dict] = raw.get("tramos", [])
    if not tramos_raw:
        return ResultadoGeneracion(
            criterio=None,
            estado="fallo",
            razon_fallo="tabla_tramos sin tramos",
        )

    tramos: list[Tramo] = []
    for t in tramos_raw:
        try:
            tramos.append(Tramo(
                desde=t.get("desde"),
                hasta=t.get("hasta"),
                incluye_inferior=t.get("incluye_inferior", True),
                incluye_superior=t.get("incluye_superior", False),
                puntaje=float(t["puntaje"]),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return ResultadoGeneracion(
                criterio=None,
                estado="fallo",
                razon_fallo=f"tramo inválido: {exc} — datos: {t}",
            )

    try:
        criterio = TablaTramos(
            campo_perfil=campo,
            naturaleza=naturaleza,
            tramos=tramos,
            fuente_numeral=req.fuente_numeral,
            pagina_origen=req.pagina_origen,
            confianza=raw.get("confianza", "media"),
        )
    except Exception as exc:
        return ResultadoGeneracion(criterio=None, estado="fallo", razon_fallo=str(exc))

    return ResultadoGeneracion(criterio=criterio, estado="ok")


def _parsear_booleano(
    raw: dict,
    req: Requisito,
) -> ResultadoGeneracion:
    campo_llm = raw.get("campo_perfil", "")
    campo = _resolver_campo_perfil(campo_llm)
    if not campo:
        return ResultadoGeneracion(
            criterio=None,
            estado="fallo",
            razon_fallo=f"campo_perfil '{campo_llm}' no resuelto en booleano",
        )

    try:
        criterio = Booleano(
            campo_perfil=campo,
            valor_requerido=bool(raw.get("valor_requerido", True)),
            fuente_numeral=req.fuente_numeral,
            pagina_origen=req.pagina_origen,
            confianza=raw.get("confianza", "media"),
        )
    except Exception as exc:
        return ResultadoGeneracion(criterio=None, estado="fallo", razon_fallo=str(exc))

    return ResultadoGeneracion(criterio=criterio, estado="ok")


# ─── Parseo central (punto de entrada desde tests) ────────────────────────────

def _parsear_respuesta(
    raw: dict,
    req: Requisito,
    modalidad: str | None = None,
    variante: str | None = None,
    catalogo_cce: dict | None = None,
) -> ResultadoGeneracion:
    """
    Convierte el dict devuelto por el LLM en un ResultadoGeneracion.
    Esta función NO hace llamadas a la API; los tests la llaman directamente.
    """
    if "error" in raw:
        return ResultadoGeneracion(
            criterio=None,
            estado="fallo",
            razon_fallo=f"json_invalido: {raw['error']}",
        )

    tipo = raw.get("tipo", "")
    if tipo == "umbral_simple":
        return _parsear_umbral_simple(raw, req, modalidad, variante, catalogo_cce)
    if tipo == "formula":
        return _parsear_formula(raw, req, catalogo_cce)
    if tipo == "tabla_tramos":
        return _parsear_tabla_tramos(raw, req)
    if tipo == "booleano":
        return _parsear_booleano(raw, req)

    return ResultadoGeneracion(
        criterio=None,
        estado="fallo",
        razon_fallo=f"clasificacion_ambigua: tipo '{tipo}' no reconocido",
    )


# ─── API pública ──────────────────────────────────────────────────────────────

def generar_criterio(
    req: Requisito,
    *,
    client: anthropic.Anthropic | None,
    catalogo_cce: dict | None = None,
    modalidad: str | None = None,
    variante: str | None = None,
    pliego_id: str = "desconocido",
) -> ResultadoGeneracion:
    """
    Convierte un Requisito en un objeto Criterio estructurado.

    Args:
        req:          Requisito extraído del pliego.
        client:       Cliente de Anthropic. None solo es válido en tests
                      (donde _llamar_llm está parcheado).
        catalogo_cce: dict completo de estructura_normativa.json (para precedencia).
        modalidad:    "obra_publica" | "menor_cuantia" | "minima_cuantia" | None.
        variante:     "mipyme" | "no_mipyme" | None.
        pliego_id:    identificador del pliego para fallo_log.

    Returns:
        ResultadoGeneracion. Si estado != "ok", criterio es None pero el requisito
        original NO se pierde — el llamador conserva req.exigido_literal.
    """
    skill_texto = _cargar_skill()

    prompt_usuario = (
        f"REQUISITO:\n"
        f"  nombre:    {req.nombre}\n"
        f"  categoria: {req.categoria}\n"
        f"  numeral:   {req.fuente_numeral}\n"
        f"  texto:     {req.exigido_literal}\n"
    )
    if req.valor_umbral is not None:
        prompt_usuario += f"  umbral extraído por el parser: {req.valor_umbral} {req.operador or ''}\n"
    prompt_usuario += "\nGenera el criterio estructurado:"

    raw = _llamar_llm(prompt_usuario, skill_texto, client)   # type: ignore[arg-type]
    resultado = _parsear_respuesta(raw, req, modalidad, variante, catalogo_cce)

    # [I-G2] y [I-G3]: registrar fallos en log B2
    if resultado.estado == "fallo" and resultado.razon_fallo:
        tipo_fallo = (
            "variable_no_resuelta"    if "variable_no_resuelta" in resultado.razon_fallo
            else "expresion_no_soportada" if "expresion_no_soportada" in resultado.razon_fallo
            else "clasificacion_ambigua"  if "clasificacion_ambigua" in resultado.razon_fallo
            else "json_invalido"
        )
        registrar_fallo(
            tipo_fallo=tipo_fallo,
            pliego=pliego_id,
            numeral=req.fuente_numeral,
            texto_original=req.exigido_literal,
            pagina=req.pagina_origen,
            detalle=resultado.razon_fallo,
        )

    return resultado
