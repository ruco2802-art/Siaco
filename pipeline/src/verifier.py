# -*- coding: utf-8 -*-
"""
src/verifier.py — verificación de citas y estado global.

[I7] Toda cita se verifica contra el markdown fuente completo.
[I4] estado_global() es una función pura; nunca se asigna 'completo' a mano.
[I8] La verificación busca en el texto COMPLETO, nunca en una ventana.
"""
from __future__ import annotations

import re
import unicodedata

from .extractor import Requisito, ResultadoExtraccion


# Versión del verificador. Sube cuando cambia lo que hace que una cita
# verifique o deje de verificar, para que un artefacto guardado pueda decir con
# cuál se calculó su `estado_verificacion` y no queden dos verdades sobre el
# mismo pliego [G1-bis].
#
#   1  original: normalización de símbolos, tildes y espacios
#   2  [D36] limpia markup, marcadores de imagen y viñetas anidadas; tolera un
#      punto final sobrante; distingue cuatro causas y detecta la elisión
VERSION_VERIFICADOR = 2


# ─── normalización ─────────────────────────────────────────────────────────

_SYMBOL_MAP = str.maketrans({
    "≥": ">=",
    "≤": "<=",
    "≠": "!=",
    "−": "-",   # guión largo (U+2212) → ASCII
    "–": "-",   # en-dash (U+2013)
    "—": "-",   # em-dash (U+2014)
    "×": "*",
    "÷": "/",
    "·": "*",  # punto medio (multiplicación)
    "’": "'",  # comilla derecha tipográfica
    "‘": "'",  # comilla izquierda tipográfica
    "“": '"',  # comilla doble izquierda
    "”": '"',  # comilla doble derecha
    "«": '"',  # guillemet izquierdo
    "»": '"',  # guillemet derecho
})


# Lo que el markdown añade y el pliego impreso no tiene. Comparar sin quitarlo
# hace fallar citas correctas [D36]. Medido sobre los dos pliegos: de 8 citas
# marcadas «no verificadas», 5 fallaban por esto.
_RX_IMAGEN = re.compile(r"!\[[^\]]*\]\([^)]*\)")          # ![](_page_46_picture_0.jpeg)
_RX_ETIQUETA = re.compile(r"</?[a-z][a-z0-9]{0,9}\s*/?>", re.I)  # <sup>, </sub>
_RX_ENFASIS = re.compile(r"\*+|`+|~~|_{2,}")                   # **negrita**, `code`
# Marcador de lista AL PRINCIPIO DE LÍNEA: «- », «# », «j. », «IV. », «a) ».
# Sólo al principio: «j.» en medio de una frase es texto, no marcador.
# El «+» final permite marcadores ANIDADOS: el markdown produce «- j. el
# porcentaje…» y quitar sólo el guion dejaba la «j.» dentro del texto, que es
# justo el caso que hacía fallar una de las ocho citas.
_RX_VINETA = re.compile(
    r"^[ \t]*(?:(?:[-*+>#]+|\(?[a-zA-Z0-9]{1,4}[.)])[ \t]+)+", re.M)


def _sin_markup(texto: str) -> str:
    """
    Quita lo que pone el markdown y no está en el pliego: marcadores de
    imagen, etiquetas HTML, énfasis, tuberías de tabla y viñetas de lista.

    No toca el contenido: un guion dentro de una palabra o un punto en mitad
    de una frase se conservan.
    """
    texto = _RX_IMAGEN.sub(" ", texto)
    texto = _RX_ETIQUETA.sub(" ", texto)
    texto = _RX_VINETA.sub(" ", texto)
    texto = _RX_ENFASIS.sub(" ", texto)
    return texto.replace("|", " ")


def _norm(texto: str) -> str:
    """Minúsculas, sin tildes/diacríticos, símbolos y markup normalizados, espacios colapsados."""
    texto = _sin_markup(texto).translate(_SYMBOL_MAP)
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    sin_acc = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acc).strip()


def _coincide(literal: str, fuente: str) -> bool:
    """
    Si la cita está en el fuente, admitiendo **un solo punto final sobrante**.

    El extractor cierra la frase con un punto que el pliego no siempre tiene:
    medido, 3 de las 8 citas no verificadas coincidían en 296 de 297, 248 de
    249 y 239 de 240 caracteres, y lo único que sobraba era ese punto.

    La tolerancia es EXACTAMENTE esa y no «los últimos caracteres»: una cita
    que difiera en la última palabra tiene que seguir fallando, porque una
    palabra cambiada al final puede invertir el sentido de un requisito.
    """
    if literal in fuente:
        return True
    return literal.endswith(".") and literal[:-1] in fuente


# ─── API pública ───────────────────────────────────────────────────────────

def verificar_citas(
    resultado: ResultadoExtraccion,
    markdown_fuente: str,
) -> ResultadoExtraccion:
    """
    [I7] Para cada requisito: normaliza exigido_literal y verifica que
         exista en el markdown fuente.
    [I8] Busca en el markdown COMPLETO — ninguna ventana, ningún slice.
         (Bug histórico: buscar solo en un fragmento produjo falso negativo
         y casi provocó una migración de parser innecesaria.)

    Marca req.cita_verificada = True/False.
    Si cita_verificada == False → el requisito tiene estado implícito
    'cita_no_verificada' y no debe publicarse como verificado.
    """
    # [I8] markdown_fuente completo — sin recorte
    assert isinstance(markdown_fuente, str), "markdown_fuente debe ser str"

    # Pre-normalizar el fuente una sola vez por eficiencia
    md_norm = _norm(markdown_fuente)

    for req in resultado.requisitos:
        if not req.exigido_literal:
            req.cita_verificada = False
            req.cita_verificada_parcial = False
            if req.estado_verificacion != "degradada":
                req.estado_verificacion = "no_verificada"
            continue
        lit_norm = _norm(req.exigido_literal)
        req.cita_verificada = _coincide(lit_norm, md_norm)
        if not req.cita_verificada:
            frag60 = lit_norm[:60]
            req.cita_verificada_parcial = len(frag60) >= 15 and frag60 in md_norm
        else:
            req.cita_verificada_parcial = False

        # Migración: estado_verificacion sigue la lógica de cita_verificada.
        # "degradada" solo lo asigna FASE C (tablas escaneadas); no se sobreescribe aquí.
        if req.cita_verificada:
            req.estado_verificacion = "verificada"
            req.motivo_degradacion = None
        elif req.estado_verificacion != "degradada":
            req.estado_verificacion = "no_verificada"

    return resultado


# ─── Por qué falló una verificación ──────────────────────────────────────────

# Símbolos que un PDF transforma al extraerse: el «≥» del pliego llega como
# «>=», el «∗» como «*», la raya larga como guion. La comparación literal falla
# por eso aunque el texto sea exactamente el del pliego.
SIMBOLOS_TRANSFORMABLES = "≥≤∗×÷−–—≠≈±·º°‰′″“”‘’…"
_RX_SIMBOLO = re.compile(f"[{SIMBOLOS_TRANSFORMABLES}]")


# Una cita que omite un pasaje con «...» NO es literal, y el informe promete
# en su sección 2 que lo es [The Full-Citation Rule]. Presentarla como textual
# hace que el documento se contradiga a sí mismo.
_RX_ELISION = re.compile(r"\.{3}|…|\[\s*\.{3}\s*\]|\[\s*…\s*\]")


def cita_elidida(literal: str | None) -> bool:
    """
    Si la cita omite un pasaje intermedio. Medido: 1 de 8 —«cualquier
    interesado**...** advierte que se dejó de incluir», donde el pliego dice
    «cualquier interesado, durante el traslado del informe de evaluación, o la
    entidad, en uso de la potestad verificadora, advierte…»—.

    No es una cita falsa: es una cita abreviada presentada como literal. La
    causa raíz es el prompt de extracción y se corrige con [D20] y [D25];
    mientras tanto el informe tiene que decirlo en vez de callarlo.
    """
    return bool(_RX_ELISION.search(literal or ""))


def causa_no_verificada(literal: str | None, parcial: bool = False) -> str:
    """
    Separa las CUATRO razones por las que una cita no verifica. Tienen
    consecuencias distintas y el informe las redacta distinto [D36]:

    - `cita_elidida`            SE SEÑALA junto al requisito. La cita omite un
                                pasaje y el informe promete que es literal.
    - `simbolo_transformado`    va a trazabilidad, sin alarma. La cita es
                                correcta; falla la comparación.
    - `artefacto_de_extraccion` va a trazabilidad, sin alarma. El arranque de
                                la cita sí está en el documento: lo que falla
                                es nuestro proceso, no el texto.
    - `texto_ausente`           SE SEÑALA. Ni el arranque aparece: puede ser
                                un error de extracción de verdad.

    - `simbolo_transformado` — el literal trae un símbolo que el PDF convirtió
      al extraerse. **La cita es correcta; lo que falla es la comparación.**
      No es información para el cliente: es una limitación de nuestro
      verificador, y va a la trazabilidad.
    - `texto_ausente` — el literal no aparece en el documento por ninguna razón
      identificable. **Eso sí puede ser un error de extracción** y tiene que
      verse junto al requisito.

    Medido en Paicol el 2026-09-27: de 8 citas no verificadas, **6 son de
    símbolo** (≥ en capital de trabajo, − y ∗ en capacidad residual, rayas
    largas en cuatro más) y **2 de texto ausente**, que son las que hay que
    revisar a mano.
    """
    if cita_elidida(literal):
        return "cita_elidida"
    if _RX_SIMBOLO.search(literal or ""):
        return "simbolo_transformado"
    return "artefacto_de_extraccion" if parcial else "texto_ausente"


def tasa_verificacion(resultado: ResultadoExtraccion) -> float:
    """Porcentaje de citas verificadas sobre el total de requisitos."""
    total = len(resultado.requisitos)
    if total == 0:
        return 100.0
    verificadas = sum(1 for r in resultado.requisitos if r.cita_verificada)
    return verificadas / total * 100.0


def marcar_indices(
    resultado: ResultadoExtraccion,
    umbral: float = 0.5,
) -> ResultadoExtraccion:
    """
    [2.3] Detección post-verificación de chunks que parecen índices/TOC.

    Para cada chunk: si la proporción de requisitos NO verificados supera umbral,
    sus requisitos se marcan con origen='probable_indice'.
    Los chunk_idx afectados se registran en resultado.chunks_advertencia_indice.

    No elimina requisitos — solo los marca. El umbral predeterminado es 0.5 (>50%).
    Requiere chunk_idx en cada Requisito (lo asigna extraer()).
    """
    from collections import defaultdict

    por_chunk: dict[int, list] = defaultdict(list)
    for req in resultado.requisitos:
        if req.chunk_idx is not None:
            por_chunk[req.chunk_idx].append(req)

    advertencias: list[int] = []
    for chunk_idx, reqs in por_chunk.items():
        if not reqs:
            continue
        # Con 1-2 requisitos el umbral es demasiado sensible a falsos positivos
        # (un solo requisito con símbolo matemático no reconocido dispararía la heurística).
        # Mínimo 3 requisitos para aplicar la detección de TOC/índice.
        if len(reqs) < 3:
            continue
        # Cuenta como "verificada" si es completa O parcial — solo el doble-negativo
        # (ni completa ni parcial) indica que la cita no existe en el documento
        no_verif = sum(1 for r in reqs if r.estado_verificacion == "no_verificada")
        tasa_no_verif = no_verif / len(reqs)
        if tasa_no_verif > umbral:
            advertencias.append(chunk_idx)
            for req in reqs:
                req.origen = "probable_indice"

    resultado.chunks_advertencia_indice = sorted(advertencias)
    return resultado


def generar_aviso_verificacion(resultado: ResultadoExtraccion) -> str | None:
    """
    [FASE D] Bloque de advertencia para el abogado revisor.

    Retorna None si todos los requisitos están verificados.
    Lista los no-verificados ordenados por criticidad (habilitantes primero),
    con numeral, página y cita para verificación directa en el PDF.
    """
    no_verif = [r for r in resultado.requisitos if r.estado_verificacion != "verificada"]
    if not no_verif:
        return None

    _ORDEN = {"habilitante": 0, "puntaje": 1, "procedimental": 2}
    no_verif.sort(key=lambda r: _ORDEN.get(r.criticidad, 9))

    total = len(resultado.requisitos)
    n = len(no_verif)

    lineas: list[str] = [
        f"VERIFICACIÓN MANUAL REQUERIDA — {n} de {total} requisitos sin verificar",
        "=" * 60,
        "",
        "El sistema no localizó la cita exacta en el texto procesado.",
        "Causas posibles: tabla fragmentada, OCR con ruido, cita reformulada.",
        "Revise cada ítem directamente en el PDF antes de emitir concepto.",
        "",
    ]

    for req in no_verif:
        pag = f"pág. {req.pagina_origen}" if req.pagina_origen else "pág. desconocida"
        crit = req.criticidad.upper()
        if req.estado_verificacion == "degradada":
            estado_desc = f"fuente escaneada — {req.motivo_degradacion or 'tabla reconstruida por modelo'}"
        else:
            estado_desc = "cita no encontrada en el texto procesado"

        lineas.append(f"[{crit}] {req.nombre}")
        lineas.append(f"  Numeral: {req.fuente_numeral} ({pag})")
        lineas.append(f"  Estado: {estado_desc}")
        cita_corta = req.exigido_literal[:140]
        if len(req.exigido_literal) > 140:
            cita_corta += "…"
        lineas.append(f"  Cita: \"{cita_corta}\"")
        if req.valor_umbral is not None:
            op = req.operador or ">="
            unidad = f" {req.unidad}" if req.unidad else ""
            lineas.append(f"  Confirme que el umbral es {op} {req.valor_umbral}{unidad}.")
        lineas.append("")

    return "\n".join(lineas)


def estado_global(
    errores: list,
    truncados: list,
    cobertura_pct: float,
) -> str:
    """
    [I4] Función pura — DERIVA el estado a partir de los datos.
         Nunca se asigna 'completo' directamente en ningún otro lugar del código.

    Prioridad: truncado > con_errores > cobertura_incompleta > completo.
    cobertura_pct == 100.0 exacto es el único camino a 'completo'.
    """
    assert isinstance(errores, list), "errores debe ser list"
    assert isinstance(truncados, list), "truncados debe ser list"
    assert isinstance(cobertura_pct, (int, float)), "cobertura_pct debe ser numérico"

    if truncados:
        return "truncado"
    if errores:
        return "con_errores"
    if cobertura_pct < 100.0:
        return "cobertura_incompleta"
    return "completo"
