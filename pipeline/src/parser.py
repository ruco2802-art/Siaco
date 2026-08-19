# -*- coding: utf-8 -*-
"""
src/parser.py — PDF → Markdown usando marker-pdf.

Detecta capa de texto nativa; si existe usa --disable_ocr (rápido).
Cachea por SHA256: el parseo se hace UNA vez por documento.

[I1] Devuelve markdown íntegro. Ningún recorte (excepto markup residual
     de marker: spans de número de página, que se eliminan y se reportan
     en metadata para no perder esa información).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore[import]

_CACHE_DIR = Path(".pipeline_cache")
_MIN_CHARS = 500
_CHARS_POR_PAGINA_UMBRAL = 50


class ParserVacioError(Exception):
    """marker devolvió menos de _MIN_CHARS caracteres."""


class ParserError(Exception):
    """marker falló al convertir el PDF."""


class ParserTimeoutError(ParserError):
    """marker/surya no respondió dentro del timeout configurado.
    El hilo daemon sigue corriendo en background — reiniciar el proceso
    si se repite. Controla el límite con PARSER_TIMEOUT_S (defecto: 300s).
    """


# ─── helpers privados ──────────────────────────────────────────────────────

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inspeccionar_pdf(pdf_path: Path) -> tuple[int, bool]:
    """Devuelve (n_paginas, tiene_capa_texto)."""
    doc = fitz.open(str(pdf_path))
    n = doc.page_count
    total_chars = sum(len(doc[i].get_text()) for i in range(n))
    doc.close()
    tiene_texto = n > 0 and total_chars >= n * _CHARS_POR_PAGINA_UMBRAL
    return n, tiene_texto


def _ruta_cache(sha: str) -> Path:
    _CACHE_DIR.mkdir(exist_ok=True)
    return _CACHE_DIR / f"{sha}.json"


def _leer_cache(sha: str) -> tuple[str, dict] | None:
    p = _ruta_cache(sha)
    if not p.exists():
        return None
    data = json.loads(p.read_text("utf-8"))
    return data["markdown"], data["metadata"]


def _guardar_cache(sha: str, markdown: str, meta: dict) -> None:
    _ruta_cache(sha).write_text(
        json.dumps({"markdown": markdown, "metadata": meta}, ensure_ascii=False),
        encoding="utf-8",
    )


# ─── Limpieza de markup residual de marker ────────────────────────────────
#
# marker-pdf inserta <span id="page-N-M"></span> en los encabezados para
# marcar posición de página. Son siempre vacíos (sin contenido entre tags).
# Impacto si no se limpian:
#   - El regex de _derivar_numeral falla sobre "<span...>1.1. Título" y
#     cae al capitulo padre → numerales duplicados en PASO C.
#   - El LLM recibe títulos con HTML crudo → ruido en prompts.
#   - verifier.py busca citas en el markdown y fallaría si el span está
#     en medio de la frase buscada (falso negativo en I7).
#
# [I1] Eliminar contenido requiere reportarlo: se registran spans_eliminados,
#      chars_afectados_por_span y paginas_con_span en la metadata del parseo.
#      paginas_con_span preserva el número de página que porta cada span.

_RE_SPAN_PAGINA = re.compile(
    r'<span\s+id="page-(\d+)-\d+"\s*>\s*</span>',
    re.IGNORECASE,
)

# Detecta tags HTML de apertura, excluyendo autolinks CommonMark.
# Lookahead negativo excluye esquemas URI (http://, https://, mailto:, etc.)
# que el regex original capturaría erróneamente como HTML.
_RE_HTML_TAG = re.compile(
    r'<(?!(?:https?|mailto|ftps?|tel|irc|data)://)[a-zA-Z][^>]{0,80}>',
    re.IGNORECASE,
)

# Tags semánticos usados legítimamente por marker.
# <sup>: notas al pie con remisiones normativas (contenido real para observaciones).
# <sub>: subíndices en formulas y simbolos.
# Sus closing tags (</sup>, </sub>) no son detectados por _RE_HTML_TAG (empiezan con `</`).
_TAGS_BENIGNOS = frozenset({"sup", "sub"})


def _limpiar_markup(
    markdown: str,
) -> tuple[str, int, int, list[int], str, list[str]]:
    """
    Elimina <span id="page-N-M"></span> residuales y clasifica markup HTML restante.

    Retorna:
      (markdown_limpio, n_spans, chars_eliminados, paginas_unicas,
       estado_limpieza, markup_residual_muestra)

    estado_limpieza (4 estados):
      "sin_markup"                  -> nunca hubo spans ni markup HTML
      "limpio"                      -> spans eliminados, sin residuo HTML
      "markup_conocido_preservado"  -> solo <sup>/<sub> y/o autolinks. INFO, no WARNING.
      "markup_desconocido"          -> tags fuera de whitelist. WARNING obligatorio.

    markup_residual_muestra:
      "markup_desconocido":         conteo de tags desconocidos (excluye benignos).
      "markup_conocido_preservado": conteo de tags benignos encontrados.
      Otros estados: [].

    El markdown devuelto siempre preserva el markup desconocido intacto:
    preferimos texto sucio a texto mutilado.
    """
    matches = list(_RE_SPAN_PAGINA.finditer(markdown))
    n_spans = len(matches)

    if n_spans > 0:
        paginas = sorted({int(m.group(1)) for m in matches})
        chars_eliminados = sum(len(m.group(0)) for m in matches)
        clean = _RE_SPAN_PAGINA.sub("", markdown)
    else:
        paginas = []
        chars_eliminados = 0
        clean = markdown

    tags = _RE_HTML_TAG.findall(clean)
    if not tags:
        estado = "limpio" if n_spans > 0 else "sin_markup"
        return clean, n_spans, chars_eliminados, paginas, estado, []

    # Separar tags benignos (whitelist) de desconocidos
    cnt = Counter(tags)
    desconocidos: dict[str, int] = {}
    benignos: dict[str, int] = {}
    for tag, n in cnt.items():
        m = re.match(r'<([a-zA-Z]+)', tag)
        nombre = m.group(1).lower() if m else ""
        (benignos if nombre in _TAGS_BENIGNOS else desconocidos)[tag] = n

    if desconocidos:
        muestra = [
            f"{n}x {tag!r}"
            for tag, n in sorted(desconocidos.items(), key=lambda x: -x[1])[:5]
        ]
        return clean, n_spans, chars_eliminados, paginas, "markup_desconocido", muestra

    # Solo benignos: INFO sin WARNING
    muestra = [
        f"{n}x {tag!r}"
        for tag, n in sorted(benignos.items(), key=lambda x: -x[1])[:5]
    ]
    return clean, n_spans, chars_eliminados, paginas, "markup_conocido_preservado", muestra


def _emitir_warning_markup(archivo: str, muestra: list[str]) -> None:
    ejemplos = "; ".join(muestra[:3])
    warnings.warn(
        f"[parser] '{archivo}': markup HTML desconocido (fuera de whitelist "
        f"sup/sub/autolinks) en markdown de marker -- se preserva intacto. "
        f"Tags: {ejemplos}. "
        "Registrado en meta['markup_residual_muestra'].",
        stacklevel=3,
    )


_MARKER_MODEL_DICT: dict | None = None  # caché proceso — carga ML una sola vez


def _convertir_con_timeout(pdf_path: Path, disable_ocr: bool, timeout_s: int) -> str:
    """
    Llama a _convertir() desde un hilo daemon con timeout.

    Si timeout_s <= 0: sin límite (compat con entornos sin llama.cpp).
    Si el hilo supera el timeout: ParserTimeoutError.
    El hilo colgado queda como daemon; el proceso principal puede continuar.
    Controlado con PARSER_TIMEOUT_S (defecto: 300s).
    """
    import threading

    if timeout_s <= 0:
        return _convertir(pdf_path, disable_ocr)

    caja: list[str | BaseException] = []

    def _run() -> None:
        try:
            caja.append(_convertir(pdf_path, disable_ocr))
        except BaseException as exc:  # noqa: BLE001
            caja.append(exc)

    hilo = threading.Thread(target=_run, daemon=True, name="marker-convertir")
    hilo.start()
    hilo.join(timeout=timeout_s)

    if hilo.is_alive():
        raise ParserTimeoutError(
            f"marker/surya colgado: sin respuesta en {timeout_s}s para "
            f"'{pdf_path.name}'. Probablemente inferencia CPU lenta (llama.cpp). "
            "Usa PARSER_OCR_BACKEND=claude o aumenta PARSER_TIMEOUT_S."
        )

    valor = caja[0]
    if isinstance(valor, BaseException):
        raise valor
    return valor


def _get_model_dict() -> dict:
    """Carga los modelos de marker la primera vez; reutiliza en llamadas sucesivas."""
    global _MARKER_MODEL_DICT
    if _MARKER_MODEL_DICT is None:
        from marker.models import create_model_dict  # type: ignore
        _MARKER_MODEL_DICT = create_model_dict()
    return _MARKER_MODEL_DICT


def _convertir(pdf_path: Path, disable_ocr: bool) -> str:
    """
    Llama a la API Python de marker-pdf.
    Soporta v0.x (convert_single_pdf) y v1.x+ (PdfConverter).
    Raises ParserError si ninguna API está disponible o falla.
    Los modelos ML se cachean en _MARKER_MODEL_DICT para no recargarlos.
    """
    # marker v0.x
    try:
        from marker.convert import convert_single_pdf  # type: ignore
        from marker.models import load_all_models  # type: ignore

        models = load_all_models()
        text, _imgs, _meta = convert_single_pdf(
            str(pdf_path), models, disable_ocr=disable_ocr
        )
        return text
    except (ImportError, AttributeError):
        pass

    # marker v1.x+
    try:
        from marker.converters.pdf import PdfConverter  # type: ignore
        from marker.config.parser import ConfigParser  # type: ignore

        cfg_args: dict = {}
        if disable_ocr:
            cfg_args["disable_ocr"] = True
        # Windows: spawn requiere if __name__=='__main__' en el caller.
        # pdftext_workers=1 evita el crash si el caller no tiene el guard.
        cfg_args["pdftext_workers"] = 1
        cfg = ConfigParser(cfg_args)
        conv = PdfConverter(
            config=cfg.generate_config_dict(),
            artifact_dict=_get_model_dict(),
        )
        rendered = conv(str(pdf_path))
        if hasattr(rendered, "markdown"):
            return rendered.markdown
        if isinstance(rendered, tuple):
            return rendered[0]
        return str(rendered)

    except ImportError as exc:
        raise ParserError(
            "marker-pdf no está instalado. "
            "Ejecutar: pip install marker-pdf"
        ) from exc
    except Exception as exc:
        raise ParserError(f"marker falló al convertir {pdf_path.name}: {exc}") from exc


def _ocr_con_claude(pdf_path: Path, n_paginas: int) -> str:
    """
    OCR para PDFs escaneados usando Claude vision (haiku).

    Activo cuando PARSER_OCR_BACKEND=claude o como fallback si marker/surya falla.
    Procesa cada página por separado y ensambla el markdown resultante.

    Sin contexto de dominio al modelo — transcripción neutral por diseño.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise ParserError(
            "anthropic no instalado — requerido para PARSER_OCR_BACKEND=claude"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ParserError(
            "ANTHROPIC_API_KEY no configurada — requerida para PARSER_OCR_BACKEND=claude"
        )

    _PROMPT_OCR = (
        "Transcribe el texto de esta página de documento a Markdown. "
        "Preserva encabezados, tablas, listas y estructura. "
        "Las tablas deben estar en formato Markdown (|col|col|). "
        "Devuelve únicamente el texto transcrito, sin preámbulo ni explicación."
    )

    client = anthropic.Anthropic(api_key=api_key)
    doc = fitz.open(str(pdf_path))
    paginas_md: list[str] = []

    for i in range(n_paginas):
        pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()
        print(f"  [OCR-Claude] página {i + 1}/{n_paginas}...", end="\r", flush=True)
        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=8_000,
                temperature=0.0,
                system=_PROMPT_OCR,
                messages=[{
                    "role": "user",
                    "content": [{
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    }],
                }],
            )
            texto = next(
                (b.text for b in resp.content if getattr(b, "type", "") == "text"),
                "",
            )
            paginas_md.append(texto.strip() or f"<!-- página {i + 1} en blanco -->")
        except Exception as exc:
            paginas_md.append(f"<!-- página {i + 1}: error OCR — {exc} -->")

    doc.close()
    print(flush=True)  # limpia la línea \r
    return "\n\n---\n\n".join(paginas_md)


# ─── API pública ───────────────────────────────────────────────────────────

def parsear_pdf(pdf_path: str | Path) -> tuple[str, dict[str, Any]]:
    """
    Convierte un PDF a Markdown usando marker-pdf.

    Devuelve: (markdown, metadata)
      metadata: {sha256, archivo, n_paginas, uso_ocr, chars, tiempo_s, desde_cache}

    [I1] markdown íntegro — ningún recorte en ninguna ruta.
    Raises ParserVacioError si marker devuelve < 500 chars.
    Raises ParserError si marker no puede procesar el PDF.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF no encontrado: {pdf_path}")

    pdf_bytes = pdf_path.read_bytes()
    sha = _sha256(pdf_bytes)

    cached = _leer_cache(sha)
    if cached is not None:
        md, meta = cached
        meta["desde_cache"] = True

        actualizar_cache = False

        if "estado_limpieza" not in meta or meta["estado_limpieza"] == "markup_no_reconocido":
            md, n_spans, n_chars, pags, estado, muestra = _limpiar_markup(md)
            if estado == "sin_markup" and meta.get("spans_eliminados", 0) > 0:
                estado = "limpio"
            meta["spans_eliminados"] = meta.get("spans_eliminados", 0) + n_spans
            meta["chars_afectados_por_span"] = meta.get("chars_afectados_por_span", 0) + n_chars
            if pags:
                meta["paginas_con_span"] = pags
            meta["estado_limpieza"] = estado
            meta["markup_residual_muestra"] = muestra
            if estado == "markup_desconocido":
                _emitir_warning_markup(meta["archivo"], muestra)
            actualizar_cache = True

        # Caché anterior a la integración de reparación de tablas — reparar y actualizar
        if "tablas_reparacion" not in meta:
            try:
                from .tablas import reparar_markdown
                md, meta_tablas = reparar_markdown(md, pdf_path)
                meta["tablas_reparacion"] = meta_tablas
            except Exception as exc:
                meta["tablas_reparacion"] = {"error": str(exc)}
            actualizar_cache = True

        if actualizar_cache:
            _guardar_cache(sha, md, {k: v for k, v in meta.items() if k != "desde_cache"})

        return md, meta

    n_paginas, tiene_texto = _inspeccionar_pdf(pdf_path)
    disable_ocr = tiene_texto  # True → rápido; False → OCR completo

    t0 = time.perf_counter()
    timeout_s = int(os.environ.get("PARSER_TIMEOUT_S", "300"))
    ocr_backend = os.environ.get("PARSER_OCR_BACKEND", "").lower()
    ocr_fallback_motivo: str | None = None

    if not tiene_texto and ocr_backend == "claude":
        # Backend Claude explícito: salta marker/surya/llama.cpp por completo
        print("  [parser] PARSER_OCR_BACKEND=claude — usando Claude vision para OCR", flush=True)
        markdown = _ocr_con_claude(pdf_path, n_paginas)
    else:
        try:
            markdown = _convertir_con_timeout(pdf_path, disable_ocr=disable_ocr, timeout_s=timeout_s)
        except (ParserError, ParserTimeoutError) as exc:
            # Fallback automático a Claude si marker falla/timeout y hay API key
            if not tiene_texto and os.environ.get("ANTHROPIC_API_KEY"):
                motivo = "timeout" if isinstance(exc, ParserTimeoutError) else "error"
                print(
                    f"  [parser] marker {motivo}; fallback a Claude vision para OCR...",
                    flush=True,
                )
                ocr_fallback_motivo = f"{motivo}: {str(exc)[:120]}"
                markdown = _ocr_con_claude(pdf_path, n_paginas)
            else:
                raise
    elapsed = time.perf_counter() - t0

    # Limpia markup residual ANTES de validar longitud y cachear
    markdown, n_spans, chars_span, pags_span, estado, muestra = _limpiar_markup(markdown)
    if estado == "markup_desconocido":
        _emitir_warning_markup(pdf_path.name, muestra)

    if len(markdown) < _MIN_CHARS:
        raise ParserVacioError(
            f"marker/OCR devolvió solo {len(markdown)} chars para '{pdf_path.name}' "
            f"(mínimo esperado: {_MIN_CHARS}). "
            "¿El PDF está dañado, cifrado o es una imagen sin OCR disponible?"
        )

    # Reparar tablas fragmentadas por marker (FASE B)
    chars_pre_reparacion = len(markdown)
    try:
        from .tablas import reparar_markdown
        markdown, meta_tablas = reparar_markdown(markdown, pdf_path)
    except Exception as exc:
        meta_tablas = {"error": str(exc)}

    # [I1] La longitud total no puede reducirse tras la reparación
    assert len(markdown) >= chars_pre_reparacion, (
        f"[I1 parser] reparar_markdown redujo el markdown de {chars_pre_reparacion} "
        f"a {len(markdown)} chars en '{pdf_path.name}'."
    )

    meta = {
        "sha256": sha,
        "archivo": pdf_path.name,
        "n_paginas": n_paginas,
        "uso_ocr": not disable_ocr,
        "chars": len(markdown),
        "tiempo_s": round(elapsed, 2),
        "desde_cache": False,
        "spans_eliminados": n_spans,
        "chars_afectados_por_span": chars_span,
        "paginas_con_span": pags_span,
        "estado_limpieza": estado,
        "markup_residual_muestra": muestra,
        "tablas_reparacion": meta_tablas,
        "ocr_fallback_motivo": ocr_fallback_motivo,  # None si no hubo fallback
        "parser_timeout_s": timeout_s,
    }
    _guardar_cache(sha, markdown, meta)
    return markdown, meta
