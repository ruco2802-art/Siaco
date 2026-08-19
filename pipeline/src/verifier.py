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


def _norm(texto: str) -> str:
    """Minúsculas, sin tildes/diacríticos, símbolos matemáticos normalizados, espacios colapsados."""
    texto = texto.translate(_SYMBOL_MAP)
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    sin_acc = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acc).strip()


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
        req.cita_verificada = lit_norm in md_norm
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
