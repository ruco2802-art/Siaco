#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/ocr_resoluciones.py — extrae tablas de las Resoluciones CCE 539/540/541.

Usa pipeline/skills/transcripcion_tablas.md + anexo_escaneados.md como sistema.
Guarda:
  - {pdf_stem}_tablas.json   → JSON de tablas por página (para el catálogo)
  - {pdf_stem}.md            → Markdown reconstruido de las tablas (para el RAG)

FASE C.1: si algún skill no existe → error explícito, sin prompt de respaldo.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

import anthropic
import pymupdf as fitz

# ─── Rutas (reproducible desde cualquier directorio de ejecución) ──────────
# scripts/ocr_resoluciones.py → parent = scripts/ → parent.parent = raíz proyecto
_RAIZ = Path(__file__).parent.parent
_SKILLS_DIR = _RAIZ / "pipeline" / "skills"

RESOLUCIONES = [
    _RAIZ / "biblioteca_normativa/infraestructura_obra_publica/Resolucion-539-de-2025.pdf",
    _RAIZ / "biblioteca_normativa/infraestructura_menor_cuantia/Resolucion-540-de-2025_transversal_menor_cuantia.pdf",
    _RAIZ / "biblioteca_normativa/infraestructura_minima_cuantia/Resolucion-541-de-2025_minima_cuantia.pdf",
]

MODELO = "claude-haiku-4-5-20251001"
ESCALA = 2   # 2× para ~300 DPI efectivos

# Precios (USD / MTok)
PRECIO_IN  = 0.80
PRECIO_OUT = 4.00


# ─── [I9] Carga y validación de API key ───────────────────────────────────

def _cargar_y_validar_key() -> str:
    """
    Carga el .env, diagnostica encoding y valida la key ANTES de gastar.
    [I9] Aborta con mensaje claro si la key es inválida o no existe.
    """
    env_path = _RAIZ / ".env"

    # ── Diagnóstico de BOM (causa más común de que la key "nunca se cargue") ──
    tiene_bom = False
    if env_path.exists():
        if env_path.read_bytes().startswith(b"\xef\xbb\xbf"):
            tiene_bom = True
            print(
                f"\n[AVISO] {env_path.name} tiene BOM UTF-8 al inicio.\n"
                "        El Bloc de notas de Windows lo añade al guardar con 'UTF-8'.\n"
                "        Efecto: la variable se lee como '\\ufeffANTHROPIC_API_KEY',\n"
                "        no coincide con el nombre esperado y la key nunca se carga.\n"
                "        Solución: guarda el .env como 'UTF-8 sin BOM' (VS Code lo hace\n"
                "        por defecto; en Bloc de notas elige 'UTF-8' en lugar de 'UTF-8 con BOM')."
            )

    # ── Cargar .env (override=True para que siempre gane sobre la sesión) ──
    key_sesion = os.environ.get("ANTHROPIC_API_KEY", "")
    load_dotenv(env_path, override=True)
    key = os.environ.get("ANTHROPIC_API_KEY", "")

    # ── Determinar fuente ──
    if key and key != key_sesion:
        fuente = f".env ({env_path})"
    elif key:
        fuente = "variable de entorno (sesión PowerShell/shell)"
    else:
        fuente = "ninguna"

    # ── Reporte diagnóstico (siempre visible, antes de cualquier gasto) ──
    preview = (key[:12] + "...") if len(key) > 12 else (key or "(vacía)")
    print(f"  API key → fuente={fuente}")
    print(f"            longitud={len(key)}  inicio='{preview}'")
    if tiene_bom:
        print("            ADVERTENCIA: BOM detectado en .env — verifica que la key se cargó correctamente")

    # ── Validación [I9] ──
    if not key:
        raise SystemExit(
            "\n[I9] ANTHROPIC_API_KEY no encontrada.\n"
            f"     .env buscado en: {env_path}\n"
            "     Opción A: añade ANTHROPIC_API_KEY=sk-ant-... al archivo .env (sin BOM).\n"
            "     Opción B: exporta la variable en la sesión antes de ejecutar el script.\n"
            "     No se hizo ninguna llamada API."
        )
    if not key.startswith("sk-ant-") or len(key) < 50:
        raise SystemExit(
            f"\n[I9] ANTHROPIC_API_KEY inválida.\n"
            f"     fuente={fuente}  longitud={len(key)}  inicio='{preview}'\n"
            "     Una clave Anthropic real comienza con 'sk-ant-' y tiene ≥ 50 caracteres.\n"
            "     Corrígela en .env antes de continuar. No se hizo ninguna llamada API."
        )

    return key


# ─── FASE C.1 — Carga de skills ───────────────────────────────────────────

def _cargar_skills() -> str:
    """
    Carga y concatena los dos skills de transcripción.
    FASE C.1: si alguno no existe → FileNotFoundError explícito.
    NO hay prompt de respaldo.
    """
    archivos = [
        _SKILLS_DIR / "transcripcion_tablas.md",
        _SKILLS_DIR / "anexo_escaneados.md",
    ]
    partes: list[str] = []
    for ruta in archivos:
        if not ruta.exists():
            raise FileNotFoundError(
                f"\n[FASE C.1] Skill no encontrado: {ruta}\n"
                "El OCR no puede continuar sin el skill.\n"
                "Corrija la ruta antes de reintentar.\n"
                f"Directorio esperado: {_SKILLS_DIR}"
            )
        partes.append(ruta.read_text("utf-8"))
        print(f"  [skill] Cargado: {ruta.name}")
    return "\n\n---\n\n".join(partes)


# ─── OCR por página ────────────────────────────────────────────────────────

def _renderizar(page: fitz.Page) -> bytes:
    mat = fitz.Matrix(ESCALA, ESCALA)
    return page.get_pixmap(matrix=mat).tobytes("png")


def _parsear_json(texto: str, pagina: int) -> dict:
    """Extrae el JSON de la respuesta. Devuelve dict con _error si falla."""
    t = texto.strip()
    # Quita cerca de ``` si el modelo lo envuelve
    if t.startswith("```"):
        lines = t.splitlines()
        t = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(t)
    except json.JSONDecodeError as exc:
        return {
            "pagina_pdf": pagina,
            "tablas": [],
            "_error_json": str(exc),
            "_raw": texto[:400],
        }


def _ocr_pagina(
    client: anthropic.Anthropic,
    sistema: str,
    png: bytes,
    pagina: int,
) -> tuple[dict, int, int]:
    """Llama al modelo y retorna (resultado_json, tokens_in, tokens_out)."""
    b64 = base64.standard_b64encode(png).decode()
    resp = client.messages.create(
        model=MODELO,
        max_tokens=2048,
        system=sistema,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    },
                },
                {
                    "type": "text",
                    "text": f"Página {pagina} de este documento escaneado.",
                },
            ],
        }],
    )
    texto = resp.content[0].text if resp.content else "{}"
    resultado = _parsear_json(texto, pagina)
    return resultado, resp.usage.input_tokens, resp.usage.output_tokens


# ─── Reconstrucción de Markdown para RAG ──────────────────────────────────

def _tablas_a_markdown(paginas: list[dict]) -> str:
    """
    Reconstruye un Markdown legible a partir del JSON de tablas.
    Solo contiene las tablas encontradas; el texto corrido de las páginas sin
    tablas no se incluye (el OCR usa el skill de tablas, no transcripción total).
    """
    partes: list[str] = []
    for p in paginas:
        n = p.get("pagina_pdf", "?")
        tablas = p.get("tablas", [])
        if not tablas:
            continue
        partes.append(f"## Página {n}\n")
        for t in tablas:
            ancla = t.get("ancla", "")
            previo = t.get("texto_previo", "")
            md = t.get("markdown", "")
            conf = t.get("confianza", "")
            if ancla:
                partes.append(f"### {ancla}")
            if previo:
                partes.append(f"*{previo}*\n")
            partes.append(md)
            if conf:
                partes.append(f"\n*confianza: {conf}*")
            partes.append("")
    return "\n\n".join(partes) if partes else "(Sin tablas extraídas)"


# ─── Procesamiento de una resolución ──────────────────────────────────────

def _procesar(
    pdf_path: Path,
    client: anthropic.Anthropic,
    sistema: str,
) -> dict:
    doc = fitz.open(str(pdf_path))
    n_pags = doc.page_count
    paginas_json: list[dict] = []
    tot_in = tot_out = 0

    print(f"\n  {pdf_path.name}  ({n_pags} páginas)")

    for i in range(n_pags):
        n = i + 1
        print(f"    p.{n:2d}/{n_pags} ", end="", flush=True)
        png = _renderizar(doc[i])
        try:
            resultado, tk_in, tk_out = _ocr_pagina(client, sistema, png, n)
            tot_in  += tk_in
            tot_out += tk_out
            paginas_json.append(resultado)
            n_tablas = len(resultado.get("tablas", []))
            estado = f"✓  {n_tablas}T  {tk_in}i/{tk_out}o"
            if resultado.get("_error_json"):
                estado += "  [JSON INVÁLIDO]"
            print(estado)
        except Exception as exc:
            paginas_json.append({"pagina_pdf": n, "tablas": [], "_error": str(exc)})
            print(f"ERROR: {exc}")
        time.sleep(0.5)

    doc.close()

    # Guardar JSON de tablas
    json_path = pdf_path.with_name(pdf_path.stem + "_tablas.json")
    salida = {"archivo": pdf_path.name, "paginas": paginas_json}
    json_path.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    # Guardar Markdown para RAG
    md_path = pdf_path.with_suffix(".md")
    md_path.write_text(_tablas_a_markdown(paginas_json), encoding="utf-8")

    return {
        "archivo": pdf_path.name,
        "n_paginas": n_pags,
        "json": str(json_path),
        "md": str(md_path),
        "input_tokens": tot_in,
        "output_tokens": tot_out,
    }


# ─── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    print("=== OCR Resoluciones CCE  |  " + MODELO + " ===\n")
    print("Validando API key:")
    api_key = _cargar_y_validar_key()
    print()
    print("Cargando skills:")
    sistema = _cargar_skills()
    print(f"  Sistema: {len(sistema):,} chars\n")

    client = anthropic.Anthropic(api_key=api_key)
    resultados: list[dict] = []

    for pdf_path in RESOLUCIONES:
        if not pdf_path.exists():
            print(f"  [FALTANTE] {pdf_path}")
            continue
        resultados.append(_procesar(pdf_path, client, sistema))

    print("\n\n=== RESUMEN ===")
    tot_in = tot_out = 0
    for r in resultados:
        c = r["input_tokens"] / 1e6 * PRECIO_IN + r["output_tokens"] / 1e6 * PRECIO_OUT
        tot_in  += r["input_tokens"]
        tot_out += r["output_tokens"]
        print(f"\n  {r['archivo']}")
        print(f"    {r['n_paginas']} págs | {r['input_tokens']:,}i + {r['output_tokens']:,}o tok | ${c:.3f}")
        print(f"    Tablas → {r['json']}")
        print(f"    RAG MD → {r['md']}")

    tot_costo = tot_in / 1e6 * PRECIO_IN + tot_out / 1e6 * PRECIO_OUT
    print(f"\n  TOTAL: {tot_in:,}i + {tot_out:,}o tok | COSTO REAL: ${tot_costo:.3f}")

    reporte = {
        "modelo": MODELO,
        "skills": ["transcripcion_tablas.md", "anexo_escaneados.md"],
        "resultados": [
            {k: v for k, v in r.items() if k not in ("json", "md")}
            for r in resultados
        ],
        "totales": {
            "input_tokens": tot_in,
            "output_tokens": tot_out,
            "costo_usd": round(tot_costo, 4),
        },
    }
    rpt = _RAIZ / "biblioteca_normativa" / "ocr_resoluciones_reporte.json"
    rpt.write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Reporte → {rpt}")


if __name__ == "__main__":
    main()
