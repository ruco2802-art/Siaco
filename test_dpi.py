# -*- coding: utf-8 -*-
"""
Prueba de sensibilidad DPI para OCR Tesseract sobre pliegos escaneados.

Corre tres niveles de resolución (Matrix(2,2)/Matrix(3,3)/Matrix(4.17,4.17))
sobre el pliego principal y reporta cuáles de los 6 términos habilitantes
aparecen en el texto completo, junto con el tiempo de extracción.

No modifica analizador.py.
"""
import io
import sys
import time
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # fallback: nombre legacy

import pytesseract
from PIL import Image

if sys.platform == "win32":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

PDF_PATH = Path("pliegos_evaluacion/16. PLIEGO DE CONDICIONES DEFINITIVO.pdf")

TERMINOS = [
    "RUT",
    "seguridad social",
    "paz y salvo",
    "RUP",
    "existencia y representación",
    "antecedentes",
]

NIVELES = [
    ("Matrix(2,2)  — 144 DPI (actual)", fitz.Matrix(2, 2)),
    ("Matrix(3,3)  — 216 DPI",          fitz.Matrix(3, 3)),
    ("Matrix(4.17) — 300 DPI",          fitz.Matrix(4.17, 4.17)),
]


def _ocr_completo(pdf_path: Path, matrix: fitz.Matrix) -> tuple[str, float]:
    """
    Extrae texto completo del PDF usando Tesseract (lang=spa).
    Replica exactamente la lógica de analizador.py::extraer_texto_completo_pdf,
    pero con la matrix configurable.
    Retorna (texto_completo, segundos_transcurridos).
    """
    doc = fitz.open(str(pdf_path))
    bloques = []
    t0 = time.perf_counter()

    for i, pagina in enumerate(doc):
        texto = pagina.get_text().strip()
        if len(texto) < 50:
            pix = pagina.get_pixmap(matrix=matrix)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            texto = pytesseract.image_to_string(img, lang="spa").strip()
        if texto:
            bloques.append(texto)

        # Progreso cada 10 páginas
        if (i + 1) % 10 == 0:
            print(f"    página {i + 1}/{len(doc)} ...", flush=True)

    elapsed = time.perf_counter() - t0
    return "\n".join(bloques), elapsed


def _buscar_terminos(texto: str) -> dict[str, bool]:
    texto_lower = texto.lower()
    return {t: t.lower() in texto_lower for t in TERMINOS}


def main():
    if not PDF_PATH.exists():
        print(f"ERROR: no se encuentra {PDF_PATH}")
        sys.exit(1)

    print("=" * 70)
    print("PRUEBA DE SENSIBILIDAD DPI — Tesseract OCR (lang=spa)")
    print(f"PDF: {PDF_PATH}")
    print("=" * 70)

    resultados = []
    for etiqueta, matrix in NIVELES:
        print(f"\n[{etiqueta}]")
        texto, elapsed = _ocr_completo(PDF_PATH, matrix)
        encontrados = _buscar_terminos(texto)
        n_ok = sum(encontrados.values())
        resultados.append((etiqueta, elapsed, len(texto), n_ok, encontrados))
        print(f"  Chars extraídos : {len(texto):,}")
        print(f"  Tiempo          : {elapsed:.1f}s")
        print(f"  Términos        : {n_ok}/{len(TERMINOS)}")
        for term, ok in encontrados.items():
            marca = "✓" if ok else "✗"
            print(f"    {marca} {term}")

    # Tabla comparativa final
    print("\n")
    print("=" * 70)
    print("TABLA COMPARATIVA")
    print("=" * 70)
    header = f"{'Nivel':<32} {'Tiempo':>7}  {'Chars':>8}  {'Términos':>8}"
    print(header)
    print("-" * 70)
    for etiqueta, elapsed, chars, n_ok, _ in resultados:
        print(f"{etiqueta:<32} {elapsed:>6.1f}s  {chars:>8,}  {n_ok:>4}/{len(TERMINOS)}")

    print("\nDetalle por término:")
    term_header = f"{'Término':<32}" + "".join(
        f"  {r[0][:10]:>10}" for r in resultados
    )
    print(term_header)
    print("-" * 70)
    for term in TERMINOS:
        row = f"{term:<32}"
        for _, _, _, _, encontrados in resultados:
            marca = "✓" if encontrados[term] else "✗"
            row += f"  {marca:>10}"
        print(row)
    print("=" * 70)


if __name__ == "__main__":
    main()
