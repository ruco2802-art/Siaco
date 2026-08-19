# -*- coding: utf-8 -*-
"""
Experimento de comparación de parsers de PDF.
NO modifica ningún archivo existente del sistema. Costo de API: $0.

Parsers comparados:
  A) PyMuPDF plano      — page.get_text()             (baseline actual)
  B) pymupdf4llm        — to_markdown()
  C) Docling            — DocumentConverter + export_to_markdown()

Uso: .venv_parsers/Scripts/python comparar_parsers.py
"""
import re
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).parent
SALIDA = ROOT / "resultados_evaluacion"
SALIDA.mkdir(exist_ok=True)

PDF_PRINCIPAL = ROOT / "pliegos_evaluacion" / "16. PLIEGO DE CONDICIONES DEFINITIVO.pdf"

# PDFs adicionales (máx 2, uno por carpeta)
DIRS_EXTRA = ["pendientes_analisis", "procesados"]

# Términos de ground truth en sección 2.12.1
TERMINOS_2121 = [
    "RUT",
    "seguridad social",
    "paz y salvo",
    "existencia y representación",
    "antecedentes",
    "RUP",
]

# Chars de ventana alrededor de 2.12.1 para buscar términos
VENTANA_2121 = 12_000

# Chars del fragmento de 3.1 mostrado en el reporte
FRAGMENTO_31_CHARS = 2_500

# Ruta de Tesseract en Windows (hardcoded igual que analizador.py)
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# ── Imports con degradación graciosa ─────────────────────────────────────────

try:
    import pymupdf as fitz           # pymupdf 1.24+ recomienda import pymupdf
    HAS_FITZ = True
except ImportError:
    try:
        import fitz
        HAS_FITZ = True
    except ImportError:
        HAS_FITZ = False
        print("FATAL: PyMuPDF no disponible — instalar en el venv.")
        sys.exit(1)

try:
    import pytesseract
    from PIL import Image as _PILImage
    import io as _io
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    import pymupdf4llm
    HAS_P4LLM = True
except ImportError:
    HAS_P4LLM = False
    print("ADVERTENCIA: pymupdf4llm no disponible — Parser B omitido.")

try:
    from docling.document_converter import DocumentConverter as _DocConverter
    HAS_DOCLING = True
except ImportError:
    HAS_DOCLING = False
    print("ADVERTENCIA: docling no disponible — Parser C omitido.")


# ── Funciones de parseo ───────────────────────────────────────────────────────

def _medir(fn):
    """Ejecuta fn(), devuelve (resultado, tiempo_s, pico_ram_bytes)."""
    tracemalloc.start()
    t0 = time.time()
    res = fn()
    elapsed = round(time.time() - t0, 2)
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return res, elapsed, pico


def parsear_a(pdf_path: Path) -> tuple[str, float, int]:
    """
    Parser A — replica el comportamiento real de analizador.extraer_texto_completo_pdf:
    page.get_text() con fallback OCR (Tesseract) si la página tiene < 50 chars nativos.
    Este PDF es escaneado: page.get_text() sola devuelve 0 chars; el texto real
    viene 100% de Tesseract.
    """
    def _run():
        raw = pdf_path.read_bytes()
        doc = fitz.open(stream=raw, filetype="pdf")
        bloques = []
        for i, pagina in enumerate(doc):
            texto = pagina.get_text().strip()
            if len(texto) < 50 and HAS_TESSERACT:
                try:
                    pix = pagina.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img = _PILImage.open(_io.BytesIO(pix.tobytes("png")))
                    texto = pytesseract.image_to_string(img, lang="spa").strip()
                except Exception:
                    pass
            if texto:
                bloques.append(f"--- PÁGINA {i+1} ---\n{texto}")
        doc.close()
        return "\n".join(bloques)
    texto, t, ram = _medir(_run)
    return texto, t, ram


def parsear_b(pdf_path: Path) -> tuple[str, float, int]:
    def _run():
        return pymupdf4llm.to_markdown(str(pdf_path))
    return _medir(_run)


def parsear_c(pdf_path: Path) -> tuple[str, float, int]:
    def _run():
        conv = _DocConverter()
        res = conv.convert(str(pdf_path))
        return res.document.export_to_markdown()
    return _medir(_run)


# ── Análisis ──────────────────────────────────────────────────────────────────

def contar_encabezados(texto: str, es_markdown: bool) -> dict:
    if es_markdown:
        niveles = {1: 0, 2: 0, 3: 0, 4: 0}
        for line in texto.splitlines():
            m = re.match(r'^(#{1,4})\s', line)
            if m:
                n = len(m.group(1))
                niveles[n] = niveles.get(n, 0) + 1
        return {f"h{k}": v for k, v in niveles.items()} | {"total": sum(niveles.values())}
    else:
        # Texto plano: líneas que empiezan con un patrón numérico de sección
        patron = len(re.findall(r'^\s*\d+(?:\.\d+)*\s{1,4}[A-ZÁÉÍÓÚÑ]', texto, re.MULTILINE))
        return {"h1": 0, "h2": 0, "h3": 0, "h4": 0, "patron_numerico_plano": patron, "total": 0}


def encabezado_2121(texto: str, es_markdown: bool) -> bool:
    """¿Aparece '2.12.1' como encabezado (markdown) o al inicio de línea (plano)?"""
    if es_markdown:
        return bool(re.search(r'^#{1,6}\s.*2\.12\.1', texto, re.MULTILINE))
    return bool(re.search(r'^\s*2\.12\.1[\s\W]', texto, re.MULTILINE))


def _hallar_ventana_2121(texto: str) -> str:
    """Devuelve la ventana de texto alrededor de la sección 2.12.1."""
    claves = ["2.12.1", "capacidad juridica", "capacidad jurídica",
              "requisitos habilitantes capacidad"]
    for clave in claves:
        pos = texto.lower().find(clave.lower())
        if pos != -1:
            inicio = max(0, pos - 300)
            return texto[inicio: inicio + VENTANA_2121]
    return texto  # fallback: todo el documento


def verificar_terminos(texto: str) -> dict[str, bool]:
    ventana = _hallar_ventana_2121(texto)
    return {t: t.lower() in ventana.lower() for t in TERMINOS_2121}


def extraer_fragmento(texto: str, marcadores: list[str]) -> str:
    """Extrae el primer fragmento que haga match con algún marcador."""
    for m in marcadores:
        pos = texto.lower().find(m.lower())
        if pos != -1:
            return texto[pos: pos + FRAGMENTO_31_CHARS]
    return f"[NO ENCONTRADO — buscado: {marcadores}]"


# ── Formateo del reporte ──────────────────────────────────────────────────────

def _mb(b: int) -> str:
    return f"{b / 1_048_576:.1f} MB"


def _td(v) -> str:
    """True/False → ✓ / ✗ para el reporte."""
    if isinstance(v, bool):
        return "✓" if v else "✗"
    return str(v)


def generar_md(resultados: dict, pdfs_procesados: list[Path]) -> str:
    bloques: list[str] = []

    bloques.append("# Comparación de parsers de PDF — SIACO\n")
    bloques.append(f"PDF principal: `{PDF_PRINCIPAL.name}`\n")
    bloques.append("\n> **Hallazgo de contexto:** este PDF es escaneado (cada página es una imagen).\n")
    bloques.append("> `page.get_text()` devuelve 0 chars por sí sola. El texto se extrae 100% vía OCR.\n")
    bloques.append("> Parser A usa Tesseract (igual que el sistema productivo). B y C usan sus propios mecanismos.\n")
    if len(pdfs_procesados) > 1:
        otros = ", ".join(f"`{p.name}`" for p in pdfs_procesados[1:])
        bloques.append(f"PDFs adicionales: {otros}\n")
    bloques.append("\n")

    # ── 1. Tabla resumen ──────────────────────────────────────────────────────
    bloques.append("## 1. Tabla resumen\n\n")
    bloques.append("| Métrica | A — PyMuPDF plano | B — pymupdf4llm | C — Docling |\n")
    bloques.append("|---|---|---|---|\n")

    def fila(label, fn_a, fn_b, fn_c):
        va = fn_a(resultados.get("A")) if resultados.get("A") else "—"
        vb = fn_b(resultados.get("B")) if resultados.get("B") else "—"
        vc = fn_c(resultados.get("C")) if resultados.get("C") else "—"
        bloques.append(f"| {label} | {va} | {vb} | {vc} |\n")

    def _chars(r): return f"{len(r['texto']):,}" if r else "—"
    def _tiempo(r): return f"{r['tiempo']}s" if r else "—"
    def _ram(r): return _mb(r["ram"]) if r else "—"
    def _enc(r): return str(r["analisis"]["encabezados"].get("total", "—")) if r else "—"
    def _pat(r):
        if not r: return "—"
        enc = r["analisis"]["encabezados"]
        return str(enc.get("patron_numerico_plano", enc.get("total", "—")))
    def _2121(r): return _td(r["analisis"]["enc_2121"]) if r else "—"
    def _terminos(r):
        if not r: return "—"
        ok = sum(1 for v in r["analisis"]["terminos"].values() if v)
        return f"{ok}/{len(TERMINOS_2121)}"

    fila("Chars extraídos", _chars, _chars, _chars)
    fila("Tiempo parseo", _tiempo, _tiempo, _tiempo)
    fila("Pico RAM", _ram, _ram, _ram)
    fila("Encabezados detectados (total)", _pat, _enc, _enc)
    fila("2.12.1 como encabezado", _2121, _2121, _2121)
    fila("Términos 2.12.1 recuperados", _terminos, _terminos, _terminos)
    bloques.append("\n")

    # ── 2. Términos de 2.12.1 ─────────────────────────────────────────────────
    bloques.append("## 2. Integridad sección 2.12.1 — términos buscados\n\n")
    bloques.append("| Término | A | B | C |\n")
    bloques.append("|---|---|---|---|\n")
    for t in TERMINOS_2121:
        va = _td(resultados["A"]["analisis"]["terminos"].get(t, False)) if resultados.get("A") else "—"
        vb = _td(resultados["B"]["analisis"]["terminos"].get(t, False)) if resultados.get("B") else "—"
        vc = _td(resultados["C"]["analisis"]["terminos"].get(t, False)) if resultados.get("C") else "—"
        bloques.append(f"| `{t}` | {va} | {vb} | {vc} |\n")
    bloques.append("\n")

    # ── 3. Fragmento sección 3.1 ─────────────────────────────────────────────
    bloques.append("## 3. Fragmento sección 3.1 — MATRIZ DE INDICADORES (primeros 2 500 chars)\n\n")
    for nombre, parser_id in [("A — PyMuPDF plano", "A"), ("B — pymupdf4llm", "B"), ("C — Docling", "C")]:
        r = resultados.get(parser_id)
        bloques.append(f"### Parser {nombre}\n\n")
        if r:
            bloques.append("```\n")
            bloques.append(r["analisis"]["fragmento_31"])
            bloques.append("\n```\n\n")
        else:
            bloques.append("_No disponible_\n\n")

    # ── 4. Notas ──────────────────────────────────────────────────────────────
    bloques.append("## 4. Notas de ejecución\n\n")
    for pid, label in [("A", "PyMuPDF plano"), ("B", "pymupdf4llm"), ("C", "Docling")]:
        r = resultados.get(pid)
        if r and r.get("error"):
            bloques.append(f"- **Parser {pid} ({label})**: ERROR — `{r['error']}`\n")
        elif r is None:
            bloques.append(f"- **Parser {pid} ({label})**: no instalado / omitido\n")

    return "".join(bloques)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not PDF_PRINCIPAL.exists():
        print(f"ERROR: no se encontró {PDF_PRINCIPAL}")
        sys.exit(1)

    # PDFs a procesar
    pdfs_extra = []
    for nombre_dir in DIRS_EXTRA:
        d = ROOT / nombre_dir
        if d.exists():
            pdfs = sorted(d.glob("*.pdf"))
            if pdfs:
                pdfs_extra.append(pdfs[0])  # uno por carpeta
    pdfs = [PDF_PRINCIPAL] + pdfs_extra

    print("=" * 64)
    print("COMPARACIÓN DE PARSERS DE PDF")
    print(f"  Parsers: A={'sí'} B={'sí' if HAS_P4LLM else 'NO'} C={'sí' if HAS_DOCLING else 'NO'}")
    print(f"  PDFs   : {len(pdfs)}")
    for p in pdfs:
        print(f"    - {p.parent.name}/{p.name}")
    print("=" * 64)

    # Sólo el PDF principal se analiza en profundidad; los extras miden rendimiento
    resultados: dict[str, dict | None] = {"A": None, "B": None, "C": None}

    def _procesar_parser(nombre, fn_parsear, es_md, guardar_md_como=None):
        print(f"\n[Parser {nombre}] {PDF_PRINCIPAL.name}...")
        try:
            texto, t, ram = fn_parsear(PDF_PRINCIPAL)
            print(f"  {len(texto):,} chars | {t}s | {_mb(ram)}")
            if guardar_md_como:
                out = SALIDA / guardar_md_como
                out.write_text(texto, encoding="utf-8")
                print(f"  >> Guardado: {out.name}")

            print(f"  Analizando estructura...")
            enc  = contar_encabezados(texto, es_md)
            e2121 = encabezado_2121(texto, es_md)
            term = verificar_terminos(texto)
            frag = extraer_fragmento(texto,
                ["3.1", "MATRIZ DE INDICADORES", "INDICADORES FINANCIEROS"])
            ok_terminos = sum(1 for v in term.values() if v)
            print(f"  Encabezados: {enc}")
            print(f"  2.12.1 como encabezado: {e2121}")
            print(f"  Términos 2.12.1: {ok_terminos}/{len(TERMINOS_2121)} — "
                  + ", ".join(f"{'✓' if v else '✗'}{k}" for k, v in term.items()))

            return {
                "texto": texto, "tiempo": t, "ram": ram, "es_markdown": es_md,
                "analisis": {
                    "encabezados": enc,
                    "enc_2121": e2121,
                    "terminos": term,
                    "fragmento_31": frag,
                },
                "error": None,
            }
        except Exception as exc:
            print(f"  ERROR: {exc}")
            return {"texto": "", "tiempo": 0, "ram": 0, "es_markdown": es_md,
                    "analisis": {"encabezados": {}, "enc_2121": False,
                                 "terminos": {t: False for t in TERMINOS_2121},
                                 "fragmento_31": ""},
                    "error": str(exc)[:300]}

    # Parser A — siempre disponible
    resultados["A"] = _procesar_parser("A — PyMuPDF plano", parsear_a, es_md=False)

    # Parser B
    if HAS_P4LLM:
        stem = PDF_PRINCIPAL.stem
        resultados["B"] = _procesar_parser(
            "B — pymupdf4llm", parsear_b, es_md=True,
            guardar_md_como=f"{stem}_parserB.md",
        )
    else:
        print("\n[Parser B] omitido — pymupdf4llm no instalado")

    # Parser C
    if HAS_DOCLING:
        stem = PDF_PRINCIPAL.stem
        resultados["C"] = _procesar_parser(
            "C — Docling", parsear_c, es_md=True,
            guardar_md_como=f"{stem}_parserC.md",
        )
    else:
        print("\n[Parser C] omitido — docling no instalado")

    # Rendimiento en PDFs adicionales (sin análisis de fondo)
    if len(pdfs) > 1:
        print(f"\n{'─'*64}")
        print("RENDIMIENTO EN PDFs ADICIONALES (parsers A y B)")
        for pdf_extra in pdfs[1:]:
            print(f"\n  {pdf_extra.parent.name}/{pdf_extra.name}")
            _, ta, ra = parsear_a(pdf_extra)
            print(f"    A: {ta}s | {_mb(ra)}")
            if HAS_P4LLM:
                try:
                    _, tb, rb = parsear_b(pdf_extra)
                    print(f"    B: {tb}s | {_mb(rb)}")
                except Exception as e:
                    print(f"    B: ERROR — {e}")

    # Generar reporte
    print(f"\n{'─'*64}")
    print("Generando comparacion_parsers.md...")
    md = generar_md(resultados, pdfs)
    out_md = ROOT / "comparacion_parsers.md"
    out_md.write_text(md, encoding="utf-8")
    print(f"  >> {out_md}")

    # Tabla final rápida
    print(f"\n{'='*64}")
    print("RESUMEN FINAL")
    print(f"{'Parser':<22} {'Chars':>10} {'Tiempo':>8} {'RAM':>8} {'Enc':>5} {'2.12.1 enc':>11} {'Términos':>9}")
    print("─" * 76)
    labels = {"A": "A — PyMuPDF plano", "B": "B — pymupdf4llm", "C": "C — Docling"}
    for pid, label in labels.items():
        r = resultados.get(pid)
        if not r:
            print(f"{label:<22} {'N/D':>10}")
            continue
        enc_total = r["analisis"]["encabezados"].get("total",
                    r["analisis"]["encabezados"].get("patron_numerico_plano", "—"))
        ok_t = sum(1 for v in r["analisis"]["terminos"].values() if v)
        e_flag = "✓" if r["analisis"]["enc_2121"] else "✗"
        print(f"{label:<22} {len(r['texto']):>10,} {r['tiempo']:>7}s {_mb(r['ram']):>8} "
              f"{enc_total:>5} {e_flag:>11} {ok_t}/{len(TERMINOS_2121):>7}")
    print("=" * 64)


if __name__ == "__main__":
    main()
