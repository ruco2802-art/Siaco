# -*- coding: utf-8 -*-
"""
pipeline/src/estados.py — Mapa único de estados de un requisito.

FUENTE CANÓNICA. La pantalla y el PDF muestran lo mismo porque leen de aquí.

El evaluador distingue cinco estados; la interfaz y el informe los aplastaban
a un booleano:

    app.js        row.cumple ? '✅' : '❌'
    reportes.py   "SI" if cumple else "NO"

Con eso, `dato_faltante` —8 de los 14 indicadores de Paicol— salía como ❌ y
como "NO". El sistema le decía al cliente «no cumples la cobertura de
intereses» cuando la verdad era «no tenemos tu dato». En un informe que el
operador firma ante una entidad, eso no es una imprecisión de interfaz: es
una afirmación falsa sobre la empresa.

`app.js` mantiene una copia del mapa porque el navegador no importa Python.
`test_estados.py` compara las dos y falla si divergen: dos copias que se
separan en silencio son peores que una sola mal puesta.
"""
from __future__ import annotations

from typing import Literal, TypedDict

Estado = Literal["cumple", "no_cumple", "dato_faltante", "revisar_manual", "no_aplica"]


class Presentacion(TypedDict):
    etiqueta: str        # Texto en pantalla y en el informe. Sin iconos.
    icono: str           # SÓLO interfaz. El PDF nunca lo usa.
    forma: str           # Distinguible sin color [accesibilidad]
    clase: str           # Clase CSS de la fila
    detalle: str         # Campo extra que acompaña a este estado, si lo hay


# Las etiquetas son las que se imprimen. En mayúscula porque son un veredicto,
# no una descripción, y tienen que leerse de un vistazo en una tabla densa.
#
# `forma` existe por accesibilidad: en un informe impreso en blanco y negro, y
# para quien no distingue rojo de verde, el color no informa. La forma sí.
ESTADOS: dict[str, Presentacion] = {
    "cumple": {
        "etiqueta": "CUMPLE",
        "icono": "✓",
        "forma": "circulo-lleno",
        "clase": "estado-cumple",
        "detalle": "",
    },
    "no_cumple": {
        "etiqueta": "NO CUMPLE",
        "icono": "✕",
        "forma": "cruz",
        "clase": "estado-no-cumple",
        # Cuánto falta. "No cumple" sin la distancia no dice si es
        # inalcanzable o si sobra por dos décimas.
        "detalle": "diferencia",
    },
    "dato_faltante": {
        "etiqueta": "DATO FALTANTE",
        "icono": "?",
        "forma": "interrogacion",
        "clase": "estado-dato-faltante",
        # Qué documento lo aportaría: convierte un hueco en una acción.
        "detalle": "documento_requerido",
    },
    "revisar_manual": {
        "etiqueta": "REVISIÓN MANUAL",
        "icono": "!",
        "forma": "triangulo",
        "clase": "estado-revisar-manual",
        # El pliego define más de un umbral y el sistema no elige por ti.
        "detalle": "umbrales_alternativos",
    },
    "no_aplica": {
        "etiqueta": "NO APLICA",
        "icono": "–",
        "forma": "guion",
        "clase": "estado-no-aplica",
        "detalle": "",
    },
}

# Estados que NO permiten afirmar que la empresa incumple. Un informe que los
# presente como incumplimiento está afirmando algo que no verificó.
SIN_VEREDICTO: frozenset[str] = frozenset({"dato_faltante", "revisar_manual"})

_POR_DEFECTO: Presentacion = {
    "etiqueta": "SIN CLASIFICAR",
    "icono": "·",
    "forma": "punto",
    "clase": "estado-desconocido",
    "detalle": "",
}


def presentacion(estado: str | None) -> Presentacion:
    """Cómo se muestra un estado. Nunca revienta: lo desconocido se ve como tal."""
    return ESTADOS.get(estado or "", _POR_DEFECTO)


def etiqueta(estado: str | None) -> str:
    """Texto del estado. Lo mismo en pantalla y en el informe."""
    return presentacion(estado)["etiqueta"]


def desde_fila(fila: dict) -> str:
    """
    Estado de una fila, tolerando los resultados viejos del historial.

    Los guardados antes de la corrección sólo traen `cumple` booleano. Se
    deduce el estado, pero nunca se inventa `dato_faltante`: sin el campo, un
    False es «no cumple», que es lo que aquel resultado quiso decir.
    """
    estado = fila.get("estado")
    if estado in ESTADOS:
        return estado
    return "cumple" if fila.get("cumple") else "no_cumple"


def texto_detalle(fila: dict) -> str:
    """
    El detalle del estado, ya redactado. Vacío si no aplica.

    Es lo que convierte «DATO FALTANTE» en algo accionable y evita que
    «NO CUMPLE» se lea como un veredicto sin magnitud.
    """
    estado = desde_fila(fila)
    campo = presentacion(estado)["detalle"]
    if not campo:
        return ""
    valor = fila.get(campo)
    if valor in (None, "", []):
        return ""

    if campo == "diferencia":
        try:
            n = float(valor)
        except (TypeError, ValueError):
            return ""
        return f"faltan {abs(n):g}" if n < 0 else f"excede en {n:g}"
    if campo == "documento_requerido":
        return f"aporta: {valor}"
    if campo == "umbrales_alternativos":
        alts = [str(v) for v in valor] if isinstance(valor, list) else [str(valor)]
        return "alternativas: " + " / ".join(alts)
    return str(valor)


def como_json() -> dict[str, dict]:
    """El mapa tal como lo replica `app.js`. Lo usa el test de paridad."""
    return {k: dict(v) for k, v in ESTADOS.items()}
