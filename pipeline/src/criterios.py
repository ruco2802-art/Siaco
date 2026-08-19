# -*- coding: utf-8 -*-
"""
src/criterios.py — modelo de criterios de evaluación + evaluador aritmético seguro.

[I6] Toda evaluación numérica ocurre en Python puro, nunca en el LLM.
     Las fórmulas se interpretan con un AST visitor que rechaza CUALQUIER
     construcción que no esté en la whitelist explícita — sin eval(), sin exec().
"""
from __future__ import annotations

import ast
import logging
import math
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ─── Whitelist del evaluador aritmético ───────────────────────────────────
# Modificar aquí para añadir operaciones sin tocar el intérprete.

_NODOS_ARITMETICOS: frozenset[type] = frozenset(
    {
        ast.Expression,
        # Valores
        ast.Constant,
        ast.Name,
        # Operaciones binarias y unarias
        ast.BinOp,
        ast.UnaryOp,
        # Operadores binarios permitidos
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
        # Operadores unarios permitidos
        ast.USub, ast.UAdd,
        # Llamadas a funciones (solo de _FUNCIONES_PERMITIDAS)
        ast.Call,
        # Argumentos posicionales dentro de Call
        ast.arguments,
    }
)

_FUNCIONES_PERMITIDAS: frozenset[str] = frozenset({"sqrt", "abs", "min", "max", "round"})

_FUNCIONES_MATH: dict[str, Any] = {
    "sqrt":  math.sqrt,
    "abs":   abs,
    "min":   min,
    "max":   max,
    "round": round,
}

# ─── Error ────────────────────────────────────────────────────────────────

class ExpresionNoPermitidaError(ValueError):
    """La expresión contiene una construcción fuera de la whitelist aritmética."""


# ─── Intérprete AST (sin eval / sin exec) ─────────────────────────────────

def _interpretar(nodo: ast.expr, namespace: dict[str, float]) -> float:
    """
    Intérprete recursivo de AST aritmético.

    Soporta: +, -, *, /, **, unario -, y las funciones de _FUNCIONES_PERMITIDAS.
    Rechaza TODO lo demás con ExpresionNoPermitidaError.
    No usa eval() ni exec() en ninguna forma.
    """
    if isinstance(nodo, ast.Constant):
        if not isinstance(nodo.value, (int, float)):
            raise ExpresionNoPermitidaError(
                f"constante no numérica: {type(nodo.value).__name__!r}"
            )
        return float(nodo.value)

    if isinstance(nodo, ast.Name):
        if nodo.id in namespace:
            return float(namespace[nodo.id])
        raise ExpresionNoPermitidaError(f"variable no declarada en whitelist: {nodo.id!r}")

    if isinstance(nodo, ast.BinOp):
        izq = _interpretar(nodo.left, namespace)
        der = _interpretar(nodo.right, namespace)
        op = nodo.op
        if isinstance(op, ast.Add):   return izq + der
        if isinstance(op, ast.Sub):   return izq - der
        if isinstance(op, ast.Mult):  return izq * der
        if isinstance(op, ast.Div):
            if der == 0.0:
                raise ExpresionNoPermitidaError("división por cero")
            return izq / der
        if isinstance(op, ast.Pow):   return izq ** der
        raise ExpresionNoPermitidaError(
            f"operador binario no soportado: {type(op).__name__}"
        )

    if isinstance(nodo, ast.UnaryOp):
        operando = _interpretar(nodo.operand, namespace)
        op = nodo.op
        if isinstance(op, ast.USub): return -operando
        if isinstance(op, ast.UAdd): return operando
        raise ExpresionNoPermitidaError(
            f"operador unario no soportado: {type(op).__name__}"
        )

    if isinstance(nodo, ast.Call):
        if not isinstance(nodo.func, ast.Name):
            raise ExpresionNoPermitidaError(
                "llamada a función compleja no permitida (solo nombres simples)"
            )
        nombre_fn = nodo.func.id
        if nombre_fn not in _FUNCIONES_PERMITIDAS:
            raise ExpresionNoPermitidaError(f"función no permitida: {nombre_fn!r}")
        if nodo.keywords:
            raise ExpresionNoPermitidaError(
                f"kwargs en funciones no soportados: {nombre_fn!r}"
            )
        args = [_interpretar(a, namespace) for a in nodo.args]
        return _FUNCIONES_MATH[nombre_fn](*args)

    raise ExpresionNoPermitidaError(
        f"construcción no soportada: {type(nodo).__name__}"
    )


def evaluar_expresion(expresion: str, namespace: dict[str, float]) -> float:
    """
    Evalúa una expresión aritmética usando el intérprete AST seguro.

    Args:
        expresion: cadena aritmética, e.g. "AC - PC" o "(POE - anticipo) * 0.33"
        namespace: variables permitidas y sus valores numéricos

    Raises:
        ExpresionNoPermitidaError: si la expresión usa cualquier construcción
            fuera de la whitelist (funciones no permitidas, atributos, imports, etc.)
    """
    try:
        tree = ast.parse(expresion.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExpresionNoPermitidaError(f"sintaxis inválida: {exc}") from exc
    return _interpretar(tree.body, namespace)


# ─── Modelos de criterio ───────────────────────────────────────────────────

class _CriterioBase(BaseModel):
    """Campos de trazabilidad presentes en todos los tipos de criterio."""
    fuente_numeral: str
    pagina_origen: int | None = None
    confianza: Literal["alta", "media", "baja"]


class UmbralSimple(_CriterioBase):
    """
    Caso 1 — comparación directa de un campo del perfil contra un valor fijo.
    Ejemplo: IDL >= 1.21
    """
    tipo: Literal["umbral_simple"] = "umbral_simple"
    campo_perfil: str    # ruta de puntos, e.g. "financiero.indice_liquidez"
    operador: Literal[">=", "<=", "==", "!=", ">", "<"]
    valor: float
    unidad: str | None = None


class Variable(BaseModel):
    """Variable de una fórmula con su fuente (perfil o pliego)."""
    nombre: str                         # nombre dentro de la expresión, e.g. "AC"
    fuente: Literal["perfil", "pliego"]
    campo: str                          # ruta en el dict fuente, e.g. "financiero.activo_corriente"


class Formula(_CriterioBase):
    """
    Caso 2 — fórmula que combina variables del perfil y del pliego.
    Ejemplo: CT = AC - PC >= (POE - anticipo) * 0.33
    """
    tipo: Literal["formula"] = "formula"
    expresion_empresa: str   # Python-evaluable, e.g. "AC - PC"
    operador: Literal[">=", "<=", "==", "!=", ">", "<"]
    expresion_umbral: str    # Python-evaluable, e.g. "(POE - anticipo) * 0.33"
    variables: list[Variable]
    descripcion: str | None = None  # texto libre para el reporte


class Tramo(BaseModel):
    """Rango de un tramo en TablaTramos."""
    desde: float | None               # None = sin límite inferior (-inf)
    hasta: float | None               # None = sin límite superior (+inf)
    incluye_inferior: bool = True     # True → [desde, ...  False → (desde, ...
    incluye_superior: bool = False    # True → ..., hasta]  False → ..., hasta)
    puntaje: float


class TablaTramos(_CriterioBase):
    """
    Caso 3 — puntaje según el rango en que cae el valor del perfil.
    Ejemplo: liquidez [0, 0.50) → 20 pts, [0.50, 0.75) → 25 pts, ...
    """
    tipo: Literal["tabla_tramos"] = "tabla_tramos"
    campo_perfil: str
    tramos: list[Tramo]


class Booleano(_CriterioBase):
    """
    Caso 4 — verificación de presencia/ausencia de un documento o condición.
    Ejemplo: juridico.rup_en_firme == True
    """
    tipo: Literal["booleano"] = "booleano"
    campo_perfil: str
    valor_requerido: bool = True


# Union discriminada — Pydantic v2 la serializa y valida sin if/isinstance
Criterio = Annotated[
    UmbralSimple | Formula | TablaTramos | Booleano,
    Field(discriminator="tipo"),
]


# ─── Resultado de evaluación ───────────────────────────────────────────────

@dataclass
class ResultadoEvaluacion:
    evaluable: bool
    cumple: bool | None = None
    valor_empresa: float | None = None
    valor_umbral: float | None = None
    puntaje: float | None = None
    motivo_no_evaluable: str | None = None


# ─── Helpers internos ──────────────────────────────────────────────────────

def _obtener_campo(ruta: str, origen: dict) -> Any:
    """Obtiene un valor del dict anidado por ruta de puntos. None si no existe."""
    cabeza, *cola = ruta.split(".", maxsplit=1)
    valor = origen.get(cabeza)
    if valor is None or not cola:
        return valor
    if not isinstance(valor, dict):
        return None
    return _obtener_campo(cola[0], valor)


def _comparar_op(valor: float, operador: str, umbral: float) -> bool:
    if operador == ">=": return valor >= umbral
    if operador == "<=": return valor <= umbral
    if operador == ">":  return valor > umbral
    if operador == "<":  return valor < umbral
    if operador == "==": return valor == umbral
    if operador == "!=": return valor != umbral
    raise ExpresionNoPermitidaError(f"operador de comparación no reconocido: {operador!r}")


def _no_evaluable(motivo: str) -> ResultadoEvaluacion:
    return ResultadoEvaluacion(evaluable=False, motivo_no_evaluable=motivo)


# ─── Evaluadores por tipo ──────────────────────────────────────────────────

def _eval_umbral_simple(criterio: UmbralSimple, valores_perfil: dict) -> ResultadoEvaluacion:
    raw = _obtener_campo(criterio.campo_perfil, valores_perfil)
    if raw is None:
        return _no_evaluable(
            f"campo '{criterio.campo_perfil}' no disponible en el perfil"
        )
    try:
        valor = float(raw)
    except (TypeError, ValueError):
        return _no_evaluable(
            f"campo '{criterio.campo_perfil}' no es numérico: {raw!r}"
        )
    cumple = _comparar_op(valor, criterio.operador, criterio.valor)
    return ResultadoEvaluacion(
        evaluable=True,
        cumple=cumple,
        valor_empresa=valor,
        valor_umbral=criterio.valor,
    )


def _eval_formula(
    criterio: Formula,
    valores_perfil: dict,
    valores_pliego: dict,
) -> ResultadoEvaluacion:
    namespace: dict[str, float] = {}
    for var in criterio.variables:
        origen = valores_perfil if var.fuente == "perfil" else valores_pliego
        raw = _obtener_campo(var.campo, origen)
        if raw is None:
            return _no_evaluable(
                f"variable '{var.nombre}' no disponible "
                f"(fuente: {var.fuente}, campo: '{var.campo}')"
            )
        try:
            namespace[var.nombre] = float(raw)
        except (TypeError, ValueError):
            return _no_evaluable(
                f"variable '{var.nombre}' no es numérica: {raw!r}"
            )

    try:
        valor_empresa = evaluar_expresion(criterio.expresion_empresa, namespace)
        valor_umbral  = evaluar_expresion(criterio.expresion_umbral, namespace)
    except ExpresionNoPermitidaError as exc:
        motivo = f"operación no soportada: {exc}"
        logger.warning("[CRITERIO] Fórmula rechazada — %s | numeral: %s", exc, criterio.fuente_numeral)
        return _no_evaluable(motivo)

    cumple = _comparar_op(valor_empresa, criterio.operador, valor_umbral)
    return ResultadoEvaluacion(
        evaluable=True,
        cumple=cumple,
        valor_empresa=valor_empresa,
        valor_umbral=valor_umbral,
    )


def _eval_tabla_tramos(criterio: TablaTramos, valores_perfil: dict) -> ResultadoEvaluacion:
    raw = _obtener_campo(criterio.campo_perfil, valores_perfil)
    if raw is None:
        return _no_evaluable(
            f"campo '{criterio.campo_perfil}' no disponible en el perfil"
        )
    try:
        valor = float(raw)
    except (TypeError, ValueError):
        return _no_evaluable(
            f"campo '{criterio.campo_perfil}' no es numérico: {raw!r}"
        )

    for tramo in criterio.tramos:
        en_inferior = True
        en_superior = True
        if tramo.desde is not None:
            en_inferior = valor >= tramo.desde if tramo.incluye_inferior else valor > tramo.desde
        if tramo.hasta is not None:
            en_superior = valor <= tramo.hasta if tramo.incluye_superior else valor < tramo.hasta
        if en_inferior and en_superior:
            return ResultadoEvaluacion(
                evaluable=True,
                cumple=True,
                valor_empresa=valor,
                puntaje=tramo.puntaje,
            )

    return ResultadoEvaluacion(
        evaluable=True,
        cumple=False,
        valor_empresa=valor,
        puntaje=0.0,
    )


def _eval_booleano(criterio: Booleano, valores_perfil: dict) -> ResultadoEvaluacion:
    raw = _obtener_campo(criterio.campo_perfil, valores_perfil)
    if raw is None:
        return _no_evaluable(
            f"campo '{criterio.campo_perfil}' no disponible en el perfil"
        )
    bool_val = bool(raw)
    cumple = bool_val == criterio.valor_requerido
    return ResultadoEvaluacion(
        evaluable=True,
        cumple=cumple,
        valor_empresa=1.0 if bool_val else 0.0,
        valor_umbral=1.0 if criterio.valor_requerido else 0.0,
    )


# ─── API pública ───────────────────────────────────────────────────────────

def evaluar_criterio(
    criterio: UmbralSimple | Formula | TablaTramos | Booleano,
    valores_perfil: dict,
    valores_pliego: dict,
) -> ResultadoEvaluacion:
    """
    Evalúa un criterio contra los valores del perfil de empresa y del pliego.

    Regla de confianza:
      baja → no se evalúa, se devuelve no_evaluable con motivo explícito.
      media/alta → se evalúa normalmente.

    [I6] Python puro. Ninguna lógica de evaluación sale del LLM.
    """
    if criterio.confianza == "baja":
        return _no_evaluable(
            "criterio de baja confianza — cita no verificada, requiere revisión manual"
        )

    if isinstance(criterio, UmbralSimple):
        return _eval_umbral_simple(criterio, valores_perfil)
    if isinstance(criterio, Formula):
        return _eval_formula(criterio, valores_perfil, valores_pliego)
    if isinstance(criterio, TablaTramos):
        return _eval_tabla_tramos(criterio, valores_perfil)
    if isinstance(criterio, Booleano):
        return _eval_booleano(criterio, valores_perfil)

    return _no_evaluable(f"tipo de criterio desconocido: {type(criterio).__name__}")
