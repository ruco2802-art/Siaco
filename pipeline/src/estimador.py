# -*- coding: utf-8 -*-
"""
pipeline/src/estimador.py — COTA SUPERIOR del costo de una extracción.

Devuelve un techo, no una predicción. Sirve para decidir «esto cabe en mi
límite de gasto», que es la pregunta real antes de lanzar.

POR QUÉ UN TECHO Y NO UNA ESTIMACIÓN
====================================
El estimado por caracteres falló en Ternera: predijo $1,14 y salió $1,4416.
La entrada acertó al 1% —es el texto que se envía— pero la SALIDA se fue
+41%, y la salida se cobra 5× más que la entrada.

Se intentaron dos proxies de densidad y **ninguno funciona**:

  · chunks con contenido normativo:  Paicol 65/85 = 1,31 · Ternera 76/104 = 1,37
  · conteo de señales normativas:    Paicol 479    · Ternera 484

Dos pliegos de longitud casi idéntica (227.507 y 227.908 chars) y con el mismo
número de señales produjeron **218 y 340 requisitos**. La densidad está en la
ESTRUCTURA del pliego —Ternera usa Documentos Tipo v2 con 22 criterios de
desempate— y no en ninguna propiedad medible de su superficie.

Queda documentado para que nadie vuelva a construir el proxy: se probó y no
predice. La consecuencia de diseño es que el margen tiene que cubrir al pliego
más denso, así que sobre uno poco denso el techo sobra bastante. Eso es
correcto para un techo y sería un defecto en una predicción.
"""
from __future__ import annotations

from dataclasses import dataclass

# Precios de claude-sonnet-4-6, USD por millón de tokens.
_PRECIO_IN, _PRECIO_OUT = 3.00, 15.00
_PRECIO_CACHE_W, _PRECIO_CACHE_R = 3.75, 0.30

# Corrida de referencia: Paicol, 2026-08-15. Medida, no estimada.
_REF = {
    "chunks": 85, "requisitos": 218, "chars": 227_507,
    "tokens_in": 66_845, "tokens_out": 57_067,
    "cache_read": 164_724, "cache_creation": 1_961,
    "costo_usd": 1.05654,
}

# Margen sobre la SALIDA. Ternera se pasó un 41% del estimado por caracteres;
# 50% lo cubre con holgura. Con la referencia de Paicol el techo queda ~46% por
# encima del costo real, que es el precio de no poder distinguir los dos
# pliegos por adelantado.
MARGEN_SALIDA = 0.50


@dataclass
class Estimado:
    chunks: int
    chars: int
    tokens_in: int
    tokens_out_techo: int
    techo_usd: float
    referencia_usd: float

    def __str__(self) -> str:
        return "\n".join([
            f"  chunks / chars       : {self.chunks} / {self.chars:,}",
            f"  tokens in            : {self.tokens_in:,}",
            f"  tokens out (techo)   : {self.tokens_out_techo:,}  "
            f"(+{MARGEN_SALIDA:.0%} sobre la referencia)",
            f"  TECHO DE COSTO       : ${self.techo_usd:.4f}",
            f"  si la densidad fuera la de Paicol: ${self.referencia_usd:.4f}",
        ])

    def cabe_en(self, limite_usd: float) -> tuple[bool, str]:
        """¿Se puede lanzar con este límite de gasto?"""
        if self.techo_usd <= limite_usd:
            return True, (f"techo ${self.techo_usd:.2f} ≤ límite "
                          f"${limite_usd:.2f} (margen ${limite_usd - self.techo_usd:.2f})")
        return False, (f"techo ${self.techo_usd:.2f} SUPERA el límite "
                       f"${limite_usd:.2f}. No se lanza sin confirmación.")


def estimar(chunks: list[dict], margen: float = MARGEN_SALIDA) -> Estimado:
    """
    Cota superior del costo de extraer estos chunks. Sin API.

    `chunks` es la salida de `chunkear()`: cada uno con su `texto`.
    """
    n = len(chunks)
    if n == 0:
        return Estimado(0, 0, 0, 0, 0.0, 0.0)

    chars = sum(len(c.get("texto", "")) for c in chunks)
    factor = chars / _REF["chars"]

    tokens_in = round(_REF["tokens_in"] * factor)
    cache_read = round(_REF["cache_read"] * factor)
    out_ref = round(_REF["tokens_out"] * factor)
    out_techo = round(out_ref * (1 + margen))

    def _total(out: int) -> float:
        return (tokens_in / 1e6 * _PRECIO_IN
                + out / 1e6 * _PRECIO_OUT
                + cache_read / 1e6 * _PRECIO_CACHE_R
                + _REF["cache_creation"] / 1e6 * _PRECIO_CACHE_W)

    return Estimado(
        chunks=n, chars=chars, tokens_in=tokens_in,
        tokens_out_techo=out_techo,
        techo_usd=_total(out_techo), referencia_usd=_total(out_ref),
    )
