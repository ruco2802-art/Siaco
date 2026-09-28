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

import re
from typing import Literal, TypedDict

Estado = Literal["cumple", "no_cumple", "dato_faltante", "revisar_manual", "no_aplica"]


class Presentacion(TypedDict):
    etiqueta: str        # Texto en pantalla y en el informe. Sin iconos.
    # Nombre de la forma que dibuja el icono. NO un glifo: un carácter unicode
    # hereda la métrica de la fuente, no se alinea igual entre plataformas y no
    # es un sistema de iconos. `app.js` mapea cada forma a un SVG de trazo
    # consistente; el PDF no dibuja ninguna [The No-Icon Rule].
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
        "forma": "circulo-lleno",
        "clase": "estado-cumple",
        "detalle": "",
    },
    "no_cumple": {
        "etiqueta": "NO CUMPLE",
        "forma": "cruz",
        "clase": "estado-no-cumple",
        # Cuánto falta. "No cumple" sin la distancia no dice si es
        # inalcanzable o si sobra por dos décimas.
        "detalle": "diferencia",
    },
    "dato_faltante": {
        "etiqueta": "DATO FALTANTE",
        "forma": "interrogacion",
        "clase": "estado-dato-faltante",
        # Qué documento lo aportaría: convierte un hueco en una acción.
        "detalle": "documento_requerido",
    },
    "revisar_manual": {
        "etiqueta": "REVISIÓN MANUAL",
        "forma": "triangulo",
        "clase": "estado-revisar-manual",
        # El pliego define más de un umbral y el sistema no elige por ti.
        "detalle": "umbrales_alternativos",
    },
    "no_aplica": {
        "etiqueta": "NO APLICA",
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

    # [N8] `revisar_manual` tiene DOS causas y el detalle debe distinguirlas:
    # umbrales alternativos en el pliego, o la unidad del campo contradiciendo
    # el texto. Sin esto, una discrepancia de unidad salía sin explicación.
    if estado == "revisar_manual" and fila.get("unidad_en_el_pliego"):
        return (f"registrado {fila.get('valor_umbral')} "
                f"{fila.get('unidad_registrada')} · "
                f"el pliego dice {fila['unidad_en_el_pliego']}")

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
        return "alternativas: " + " / ".join(_texto_alternativa(v) for v in
                                             (valor if isinstance(valor, list)
                                              else [valor]))
    return str(valor)


# Los operadores tal como se leen, no como se codifican. Un informe firmado no
# puede decir `'operador': '<='`.
_OPERADORES = {"<=": "≤", ">=": "≥", "<": "<", ">": ">", "==": "=", "=": "="}

# Singular de las unidades que el extractor produce. Sólo las conocidas: una
# regla general («quitar la -s final») convertiría «meses» en «mese» y «SMMLV»
# en algo peor. Lo que no esté aquí se deja como vino.
_SINGULAR = {"contratos": "contrato", "meses": "mes", "años": "año",
             "anos": "año", "veces": "vez", "días": "día", "dias": "día",
             "puntos": "punto"}


def _texto_alternativa(alt) -> str:
    """
    Redacta UNA alternativa de umbral.

    `umbrales_alternativos` es `list[dict]` (ver `extractor.Requisito`), así que
    un `str(alt)` volcaba el diccionario de Python entero —claves, comillas y
    todo— dentro de la tabla del informe. Defecto real encontrado el 2026-09-27
    al maquetar la sección 7: una celda con 1.400 caracteres de `{'valor_umbral':
    5.0, 'operador': '<=', ...}` en un documento que se firma ante una entidad.
    """
    if not isinstance(alt, dict):
        return str(alt)
    op = _OPERADORES.get(str(alt.get("operador") or ""), alt.get("operador") or "")
    valor = alt.get("valor_umbral")
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    unidad = alt.get("unidad")
    if valor == 1 and unidad:
        unidad = _SINGULAR.get(str(unidad).lower(), unidad)
    cifra = " ".join(str(x) for x in (op, valor, unidad) if x not in (None, ""))
    nombre = alt.get("nombre")
    return f"{cifra} — {nombre}" if nombre and cifra else (cifra or str(nombre or ""))


# ─── [N7] Literal ilegible ────────────────────────────────────────────────────

# Racha de SÍMBOLOS donde deberían haber letras. La codificación rota de un PDF
# sustituye cada letra por un símbolo, así que el literal queda como
# "CRPC = %&'()\"*!+!,- -,/0-" — una cadena que llegaría al informe tal cual.
#
# Se permiten los símbolos que una fórmula legítima usa (= ≥ ≤ + - * ∗ × / % ° $
# paréntesis, corchetes, comillas) y se marca cuando aparecen 3 seguidos de los
# que NO pertenecen a una fórmula, o 4 de los que sí pueden encadenarse.
#
# Calibrado sobre los dos pliegos: marca 1 de 218 literales en Paicol —el roto—
# y 0 de 340 en Ternera. El ratio de caracteres no alfabéticos NO servía: el
# roto está en 8,6% y un literal sano de tabla ("Mipyme | 0,25") llega a 7,7%.
_SIMBOLOS_DE_FORMULA = r"""\w\s.,;:()\[\]%°/+=<>≥≤$'"*∗×\-–—"""
_RACHA_SIMBOLOS = re.compile(
    # 3+ seguidos de los que NO pertenecen a una fórmula
    rf"[^{_SIMBOLOS_DE_FORMULA}]{{3,}}"
    # o 4+ de los que sí pueden aparecer, pero nunca encadenados
    r"|[!?*+%&#@~^`|\\]{4,}")

# Lo que se muestra en vez de la cadena rota. Nombra el numeral para que el
# operador pueda ir al pliego: el dato existe, lo que falla es la extracción.
AVISO_ILEGIBLE = "texto no legible en el documento fuente — revisar numeral {}"


def literal_ilegible(literal: str | None) -> bool:
    """
    [N7] ¿El `exigido_literal` es texto corrupto de la extracción?

    Mismo problema que la Ley 1474 y el mismo principio: una cadena que existe
    en el documento no es necesariamente legible. Aquí además es peor, porque
    esa cadena es la CITA que sostiene la afirmación ante una entidad.
    """
    return bool(_RACHA_SIMBOLOS.search(literal or ""))


def texto_cita(fila: dict) -> str:
    """
    La cita que se muestra, o el aviso si no es legible.

    Nunca devuelve la cadena corrupta: un informe firmado no puede llevar
    "CRPC = %&'()\"*!+!,-" como cita textual del pliego.
    """
    literal = (fila.get("exigido_literal") or "").strip()
    if not literal:
        return ""
    if literal_ilegible(literal):
        return AVISO_ILEGIBLE.format(fila.get("fuente_numeral") or "sin numeral")
    return literal


# ─── [N8] Unidad del umbral vs unidad del texto del pliego ───────────────────
#
# El extractor pone `unidad="meses"` por defecto cuando la magnitud es temporal
# y no resuelve cuál. Cuatro casos medidos entre Paicol y Ternera, los cuatro
# con "meses":
#
#   maquinaria con edad menor a veinte (20) AÑOS      -> 20.0 meses
#   plazo de subsanación de tres (3) DÍAS hábiles     ->  3.0 meses
#   mínimo un AÑO de existencia para Mipyme           ->  1.0 meses
#   antigüedad máxima de documentos en DÍAS           -> 60.0 meses  (30x)
#
# El de la Mipyme es el peor: daría por válida a una empresa de seis meses
# cuando el pliego exige un año. Un FALSO POSITIVO —decirle al cliente que
# califica cuando va a ser rechazado— es peor que un falso negativo.
#
# Es DETECCIÓN, no corrección. Deducir que "20 meses" quería decir "20 años"
# sería inventar, el mismo error que el valor por defecto en el campo de norma
# de `auditoria.py:154`. El requisito va a `revisar_manual` y el operador ve
# ambos datos.

# Familias de magnitud, mutuamente excluyentes: confundir dos cambia el
# veredicto. Cada una con cómo se nombra en el texto del pliego.
_UNIDAD_EN_TEXTO: dict[str, str] = {
    "anios":     r"\ba[ñn]os?\b",
    "meses":     r"\bmes(?:es)?\b",
    "dias":      r"\bd[ií]as?\b",
    "smmlv":     r"\bsmmlv\b|\bsmlmv\b|salarios?\s+m[ií]nimos?",
    "porcentaje": r"por\s+ciento|%|porcentaje",
    "metros2":   r"\bm2\b|\bm²\b|metros\s+cuadrados",
}

# Cómo escribe el extractor el campo `unidad` para cada familia
_UNIDAD_EN_CAMPO: dict[str, frozenset[str]] = {
    "anios":      frozenset({"anios", "años", "año", "ano", "years"}),
    "meses":      frozenset({"meses", "mes", "months"}),
    "dias":       frozenset({"dias", "días", "dia", "día", "dias_habiles",
                             "días hábiles", "dias habiles"}),
    "smmlv":      frozenset({"smmlv", "smlmv"}),
    "porcentaje": frozenset({"porcentaje", "%", "por_ciento", "pct"}),
    "metros2":    frozenset({"m2", "m²", "metros_cuadrados"}),
}

_ETIQUETA_FAMILIA: dict[str, str] = {
    "anios": "años", "meses": "meses", "dias": "días",
    "smmlv": "SMMLV", "porcentaje": "porcentaje", "metros2": "m²",
}


def _familia_del_campo(unidad: str | None) -> str | None:
    u = (unidad or "").strip().lower()
    if not u:
        return None
    for familia, formas in _UNIDAD_EN_CAMPO.items():
        if u in formas:
            return familia
    return None


def _familias_en_texto(literal: str | None) -> set[str]:
    t = (literal or "").lower()
    return {f for f, patron in _UNIDAD_EN_TEXTO.items() if re.search(patron, t)}


def unidad_discordante(fila: dict) -> dict | None:
    """
    [N8] ¿La unidad del campo contradice la que nombra el pliego?

    Devuelve `{campo, texto, etiqueta_campo, etiqueta_texto}` cuando hay
    discrepancia, o None. Sólo dispara con evidencia en los dos lados: si el
    literal no nombra ninguna unidad reconocible, no se concluye nada — puede
    que el valor venga de una tabla o de un anexo.
    """
    familia_campo = _familia_del_campo(fila.get("unidad"))
    if familia_campo is None:
        return None
    # Sin umbral numérico no hay veredicto que falsear
    if fila.get("valor_umbral") is None:
        return None

    familias_texto = _familias_en_texto(fila.get("exigido_literal"))
    if not familias_texto or familia_campo in familias_texto:
        return None

    return {
        "campo": fila.get("unidad"),
        "etiqueta_campo": _ETIQUETA_FAMILIA.get(familia_campo, familia_campo),
        "texto": sorted(familias_texto),
        "etiqueta_texto": " o ".join(
            _ETIQUETA_FAMILIA.get(f, f) for f in sorted(familias_texto)),
    }


MOTIVO_UNIDAD = (
    "La unidad del umbral no coincide con el texto del pliego: el sistema "
    "registró «{campo}» y el pliego dice «{texto}». No se corrige el valor —"
    " eso sería inventar. Verifica el numeral {numeral} antes de ofertar."
)


def motivo_unidad_discordante(fila: dict, discordancia: dict) -> str:
    return MOTIVO_UNIDAD.format(
        campo=f"{fila.get('valor_umbral')} {discordancia['etiqueta_campo']}",
        texto=discordancia["etiqueta_texto"],
        numeral=fila.get("fuente_numeral") or "correspondiente",
    )


def como_json() -> dict[str, dict]:
    """El mapa tal como lo replica `app.js`. Lo usa el test de paridad."""
    return {k: dict(v) for k, v in ESTADOS.items()}
