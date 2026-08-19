# -*- coding: utf-8 -*-
"""
src/chunker.py — Markdown → chunks jerárquicos.

Usa MarkdownHeaderTextSplitter de LangChain para respetar la estructura
del documento como dato del parser (I5). Chunks grandes se subdividen
por párrafos, nunca se recortan (I1).

Jerarquía de metadata:
  - nivel_h     : nivel de encabezado Markdown (1=#, 2=##, 3=###) asignado por marker
  - numeral_derivado : numeral decimal/romano detectado en el título (None si no aplica)
  - profundidad : nº de segmentos del numeral (None si no aplica)
  - tipo_numeral: "decimal" | "parentesis" | "romano" | None
  - origen_jerarquia: "numeral" | "nivel_h"

El flag usar_numeral_derivado controla si se enriquece con numeral.
NUNCA se descarta el nivel_h — siempre presente en la metadata.
"""
from __future__ import annotations

import re

try:
    from langchain_text_splitters import MarkdownHeaderTextSplitter
except ImportError:
    from langchain.text_splitter import MarkdownHeaderTextSplitter  # type: ignore

_HEADERS = [
    ("#", "capitulo"),
    ("##", "subcapitulo"),
    ("###", "numeral"),
]

_MAX_CHUNK_CHARS = 15_000
_STRIP_HEADERS = False
try:
    _SPLITTER = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADERS,
        strip_headers=_STRIP_HEADERS,
    )
except TypeError:
    _SPLITTER = MarkdownHeaderTextSplitter(headers_to_split_on=_HEADERS)
    _STRIP_HEADERS = True

_COBERTURA_MIN_PCT = 99.0 if not _STRIP_HEADERS else 85.0

# ─── Regex conservadores para derivar numerales del título ─────────────────
#
# REGLA: anclados al inicio, exigen separador (. o ) seguido de espacio).
# Rechaza:
#   - 4 dígitos como primer nivel (años: 2026, 1993)
#   - 3+ dígitos como segundo nivel en adelante (cifras: 1.500)
#   - Más de 4 niveles de profundidad
#   - Romanos solo I-XX y solo si van seguidos de punto (no paréntesis)
# Ante cualquier duda: (None, None).

_RE_DECIMAL = re.compile(
    r"^(?!\d{4})"                    # rechaza 4-digit primer segmento (años)
    r"(\d{1,3}(?:\.\d{1,2}){0,4})"  # 1-5 niveles; 2º en adelante: max 2 dígitos
    r"(?:\.)?(?:\)|\s)",             # separador obligatorio: . ) o espacio
    re.UNICODE,
)

# Romanos explícitos I-XX, más largo primero para evitar match parcial.
# Solo acepta ". " (punto+espacio), no ")" ni solo espacio.
_RE_ROMANO = re.compile(
    r"^(XIX|XVIII|XVII|XVI|XV|XIV|XIII|XII|XI"
    r"|IX|VIII|VII|VI|IV|XX|X|V|III|II|I)\.\s",
    re.UNICODE,
)


# ─── Excepciones ───────────────────────────────────────────────────────────

class CoberturaIncompletaError(Exception):
    """chunks no cubren >= _COBERTURA_MIN_PCT % del markdown."""


class JerarquiaInconsistenteError(Exception):
    """Un chunk tiene un padre con profundidad igual o mayor a la suya."""


# ─── Helpers privados ──────────────────────────────────────────────────────

def _limpiar_bold(valor: str) -> str:
    """Elimina asteriscos de bold/italic en un string de metadata."""
    return re.sub(r"\*+", "", valor).strip()


def _derivar_numeral(titulo_limpio: str) -> tuple[str | None, str | None]:
    """
    Intenta derivar un numeral estructurado del título ya limpio de bold.
    Retorna (tipo, numeral_str) o (None, None) si no reconoce.
    Tipos posibles: "decimal", "parentesis", "romano".

    CONSERVADOR — ver docstring del módulo para las reglas de rechazo.
    """
    # Intento decimal / paréntesis
    m = _RE_DECIMAL.match(titulo_limpio)
    if m:
        num = m.group(1)
        # Doble verificación: ningún segmento posterior al primero tiene 3+ dígitos.
        # (El regex ya lo garantiza con \d{1,2}, pero lo dejamos explícito.)
        partes = num.split(".")
        if any(len(p) > 2 for p in partes[1:]):
            return None, None
        # Determinar si es estilo paréntesis o punto
        after_num = titulo_limpio[m.end(1):]  # lo que sigue al numeral capturado
        tipo = "parentesis" if after_num.lstrip(".").startswith(")") else "decimal"
        return tipo, num

    # Intento romano
    m = _RE_ROMANO.match(titulo_limpio)
    if m:
        return "romano", m.group(1)

    return None, None


def _padre_numeral(num_str: str) -> str | None:
    """Retorna el numeral del padre directo, o None si es raíz (1 segmento)."""
    partes = num_str.split(".")
    return ".".join(partes[:-1]) if len(partes) > 1 else None


def _nivel_h_de_meta(raw_meta: dict) -> int:
    """Determina el nivel H (1-3) desde la metadata cruda del splitter."""
    if raw_meta.get("numeral"):
        return 3
    if raw_meta.get("subcapitulo"):
        return 2
    if raw_meta.get("capitulo"):
        return 1
    return 0


def _enriquecer_metadata(
    raw_meta: dict,
    usar_numeral_derivado: bool,
) -> dict:
    """
    Limpia bold, añade nivel_h y — cuando el flag está activo — deriva el numeral.
    Opera SOLO sobre los strings de metadata; no toca el cuerpo del documento (I5).
    """
    # 1. Limpiar bold en todos los valores string
    limpia: dict = {
        k: _limpiar_bold(v) if isinstance(v, str) else v
        for k, v in raw_meta.items()
    }

    # 2. Nivel H siempre presente
    limpia["nivel_h"] = _nivel_h_de_meta(raw_meta)

    if not usar_numeral_derivado:
        limpia["numeral_derivado"] = None
        limpia["profundidad"] = None
        limpia["tipo_numeral"] = None
        limpia["origen_jerarquia"] = "nivel_h"
        return limpia

    # 3. Derivar numeral del encabezado más específico
    numeral_derivado: str | None = None
    tipo_numeral: str | None = None
    for campo in ("numeral", "subcapitulo", "capitulo"):
        valor = limpia.get(campo, "")
        if not valor:
            continue
        tipo, num = _derivar_numeral(valor)
        if tipo and num:
            numeral_derivado = num
            tipo_numeral = tipo
            break

    limpia["numeral_derivado"] = numeral_derivado
    limpia["profundidad"] = numeral_derivado.count(".") + 1 if numeral_derivado else None
    limpia["tipo_numeral"] = tipo_numeral
    limpia["origen_jerarquia"] = "numeral" if numeral_derivado else "nivel_h"
    return limpia


def _verificar_jerarquia(chunks: list[dict]) -> None:
    """
    Assert: ningún chunk puede tener un padre con profundidad >= a la suya.
    Falla ruidoso — nunca metadata falsa en silencio.
    Solo evalúa chunks con numeral_derivado.
    """
    num_a_prof: dict[str, int] = {}
    num_a_titulo: dict[str, str] = {}
    for c in chunks:
        nd = c["metadata"].get("numeral_derivado")
        prof = c["metadata"].get("profundidad")
        if nd and prof:
            num_a_prof[nd] = prof
            num_a_titulo[nd] = (
                c["metadata"].get("capitulo")
                or c["metadata"].get("subcapitulo")
                or c["metadata"].get("numeral")
                or nd
            )

    for c in chunks:
        nd = c["metadata"].get("numeral_derivado")
        if not nd:
            continue
        prof = c["metadata"].get("profundidad", 0)
        padre_num = _padre_numeral(nd)
        if padre_num and padre_num in num_a_prof:
            padre_prof = num_a_prof[padre_num]
            if padre_prof >= prof:
                raise JerarquiaInconsistenteError(
                    f"Numeral '{nd}' (profundidad={prof}) tiene padre "
                    f"'{padre_num}' con profundidad={padre_prof} >= {prof}. "
                    f"Chunk: {num_a_titulo.get(nd)!r} — "
                    f"Padre: {num_a_titulo.get(padre_num)!r}. "
                    "Revisa _derivar_numeral o el markdown fuente."
                )


def _subdividir_por_parrafos(texto: str, meta: dict) -> list[dict]:
    """
    Divide un chunk grande en sub-chunks por párrafos conservando metadata.
    [I1] Nunca trunca: párrafos > _MAX_CHUNK_CHARS van completos como parte única.
    [2.2] Sub-chunks etiquetados con subchunk_parte ("a","b",...) y subchunk_total.
          Metadata del padre heredada íntegra; solo se añaden las claves de parte.

    Detección de caso cuando \\n\\n no produce subdivisión:
    [CASO B] >50% de líneas son filas de tabla markdown (comienzan con "|") →
             NO se parte; se marca tipo_contenido="tabla_markdown" en metadata para
             que _llamar() use max_tokens elevado.
    [CASO A] Texto con separador \\n simple (sin \\n\\n) → se reintenta con \\n.
             [I1] assert garantiza que la suma de partes conserva todo el contenido.
    """
    import re as _re

    def _strip_ws(s: str) -> str:
        return _re.sub(r"\s", "", s)

    def _acumular(parrafos: list[str]) -> list[dict]:
        """Acumula párrafos en sub-chunks respetando _MAX_CHUNK_CHARS."""
        subchunks: list[dict] = []
        buffer: list[str] = []
        buffer_len = 0
        for p in parrafos:
            if buffer_len + len(p) > _MAX_CHUNK_CHARS and buffer:
                subchunks.append({"texto": "\n\n".join(buffer), "metadata": meta})
                buffer = [p]
                buffer_len = len(p)
            else:
                buffer.append(p)
                buffer_len += len(p)
        if buffer:
            subchunks.append({"texto": "\n\n".join(buffer), "metadata": meta})
        return subchunks or [{"texto": texto, "metadata": meta}]

    # Intento 1: separador estándar \n\n
    parrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]
    subchunks = _acumular(parrafos)

    if len(subchunks) == 1:
        # El texto no pudo dividirse por \n\n — detectar el caso
        lineas = texto.splitlines()
        pipe_pct = sum(1 for l in lineas if l.lstrip().startswith("|")) / max(len(lineas), 1)

        if pipe_pct > 0.5:
            # CASO B: tabla markdown — no se parte; aumentar max_tokens en _llamar
            new_meta = dict(meta)
            new_meta["tipo_contenido"] = "tabla_markdown"
            return [{"texto": texto, "metadata": new_meta}]

        # CASO A: párrafos con \n simple como separador
        parrafos_n = [p.strip() for p in texto.split("\n") if p.strip()]
        if len(parrafos_n) > 1:
            subchunks = _acumular(parrafos_n)

    if len(subchunks) == 1:
        # No se pudo dividir de ninguna forma — devolver sin etiquetas
        return subchunks

    # Etiquetar partes: "a", "b", ..., "z", "parte26", ...
    _LETRAS = "abcdefghijklmnopqrstuvwxyz"
    total = len(subchunks)
    labeled: list[dict] = []
    for i, sc in enumerate(subchunks):
        parte_id = _LETRAS[i] if i < len(_LETRAS) else f"parte{i}"
        meta_parte = dict(sc["metadata"])
        meta_parte["subchunk_parte"] = parte_id
        meta_parte["subchunk_total"] = total
        labeled.append({"texto": sc["texto"], "metadata": meta_parte})

    # [I1] Ningún carácter no-espacio debe perderse en la subdivisión
    assert _strip_ws("".join(sc["texto"] for sc in labeled)) == _strip_ws(texto), (
        f"[I1] _subdividir_por_parrafos perdió contenido: "
        f"original={len(texto)} chars, partes={[len(sc['texto']) for sc in labeled]}"
    )

    return labeled


# ─── API pública ───────────────────────────────────────────────────────────

def chunkear(
    markdown: str,
    usar_numeral_derivado: bool = True,
) -> tuple[list[dict], float]:
    """
    Markdown → lista de chunks con metadata jerárquica.

    Parámetros:
      usar_numeral_derivado=False → metadata solo con nivel H de marker (comportamiento base)
      usar_numeral_derivado=True  → añade numeral_derivado, profundidad, tipo_numeral,
                                    origen_jerarquia cuando el título contiene un numeral
                                    reconocible y conservador.

    El campo nivel_h está presente SIEMPRE independientemente del flag.

    [I5] La estructura jerárquica la determina MarkdownHeaderTextSplitter sobre el
         markdown del parser. La derivación de numeral opera sobre los STRINGS de
         metadata ya entregados — no sobre el documento.
    [I1] Chunks > _MAX_CHUNK_CHARS se subdividen por párrafos sin truncar.

    Retorna: (chunks, cobertura_pct)
    Raises CoberturaIncompletaError si cobertura < _COBERTURA_MIN_PCT.
    Raises JerarquiaInconsistenteError si un padre tiene profundidad >= al hijo.
    """
    if not markdown:
        raise ValueError("markdown no puede ser vacío")

    raw = _SPLITTER.split_text(markdown)

    if not raw:
        raise CoberturaIncompletaError(
            "MarkdownHeaderTextSplitter no produjo ningún chunk. "
            "¿El markdown tiene contenido real o solo encabezados?"
        )

    chars_en_chunks = sum(len(c.page_content) for c in raw)
    cobertura_pct = chars_en_chunks / len(markdown) * 100.0

    if cobertura_pct < _COBERTURA_MIN_PCT:
        chars_sin = len(markdown) - chars_en_chunks
        raise CoberturaIncompletaError(
            f"Cobertura {cobertura_pct:.2f}% < {_COBERTURA_MIN_PCT}%. "
            f"{chars_sin:,} chars del markdown no están en ningún chunk. "
            f"(strip_headers={_STRIP_HEADERS}, umbral={_COBERTURA_MIN_PCT}%)"
        )

    chunks: list[dict] = []
    for c in raw:
        meta = _enriquecer_metadata(dict(c.metadata), usar_numeral_derivado)
        texto = c.page_content
        if len(texto) > _MAX_CHUNK_CHARS:
            chunks.extend(_subdividir_por_parrafos(texto, meta))
        else:
            chunks.append({"texto": texto, "metadata": meta})

    if usar_numeral_derivado:
        _verificar_jerarquia(chunks)

    return chunks, cobertura_pct
