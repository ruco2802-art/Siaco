# -*- coding: utf-8 -*-
"""
Tarea 9 — Experimento: documento completo sin RAG.

Procesa un pliego pasando el texto íntegro a ambos agentes (Paso A legal + financiero),
sin chunking ni selección por similitud semántica.

Safety check: si la estimación de tokens supera el límite configurado, aborta con
exit 2 ANTES de enviar nada al modelo. No trunca silenciosamente.

Resultado guardado en resultados_evaluacion/<nombre>_SINRAG.json.
No sobreescribe el resultado de producción (pliego_1.json).

Uso:
  py -3.13 evaluar_sinrag.py
  py -3.13 evaluar_sinrag.py --pdf "16. PLIEGO DE CONDICIONES DEFINITIVO.pdf"
  py -3.13 evaluar_sinrag.py --pdf otro.pdf --salida pliego_X_SINRAG.json
"""
import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

from analizador import (
    extraer_texto_documento,
    agente_legal_rag,
    agente_financiero,
    obtener_contexto_legal,
    verificar_embeddings,
    SCANNED_PDF_MARKER,
    DOC_NOT_SUPPORTED_MARKER,
)
from evaluar_pliegos import _PERFIL_NEUTRO, _EXPERIENCIA_NEUTRA

SALIDA = _ROOT / "resultados_evaluacion"
SALIDA.mkdir(exist_ok=True)

# Pricing claude-sonnet-4-6 (USD por millón de tokens)
_PRECIO_INPUT  = 3.00
_PRECIO_OUTPUT = 15.00

# Safety: abortar si se estima más de este número de tokens de entrada para Paso A.
# claude-sonnet-4-6 acepta hasta 200 000 tokens.
# Se usa 180 000 como margen de seguridad.
_LIMITE_TOKENS_ESTIMADO   = 180_000
_OVERHEAD_PROMPT_TOKENS   = 2_500   # tokens de instrucciones en Paso A, estimados


def _estimar_tokens(chars: int) -> int:
    """Estimación conservadora: 3.5 chars / token + overhead de prompt."""
    return math.ceil(chars / 3.5) + _OVERHEAD_PROMPT_TOKENS


def _costo_usd(tok_in: int, tok_out: int) -> float:
    return (tok_in / 1_000_000) * _PRECIO_INPUT + (tok_out / 1_000_000) * _PRECIO_OUTPUT


def main():
    parser = argparse.ArgumentParser(description="Tarea 9 — Experimento sin RAG")
    parser.add_argument(
        "--pdf", default="16. PLIEGO DE CONDICIONES DEFINITIVO.pdf",
        help="Nombre del PDF dentro de pliegos_evaluacion/"
    )
    parser.add_argument(
        "--salida", default=None,
        help="Nombre del JSON de salida (default: <stem>_SINRAG.json)"
    )
    parser.add_argument("--modalidad", default="infraestructura_obra_publica")
    parser.add_argument("--sector",    default="institucional")
    args = parser.parse_args()

    pdf_path = _ROOT / "pliegos_evaluacion" / args.pdf
    if not pdf_path.exists():
        print(f"ERROR: No se encontró {pdf_path}")
        sys.exit(1)

    salida_nombre = args.salida or f"{pdf_path.stem}_SINRAG.json"
    out_path = SALIDA / salida_nombre

    print("=" * 62)
    print("TAREA 9 — Experimento sin RAG")
    print(f"  PDF    : {pdf_path.name}")
    print(f"  Salida : {out_path.name}")
    print("=" * 62)

    # ── 1. Preflight de embeddings (no se usan, pero verifica el entorno) ────
    emb = verificar_embeddings()
    if not emb["disponible"]:
        print(f"\nADVERTENCIA: Embeddings no disponibles ({emb['error']})")
        print("El experimento no usa RAG, pero el entorno puede estar degradado. Continuando...")

    # ── 2. Extracción de texto ────────────────────────────────────────────────
    print("\n[1/4] Extrayendo texto completo...")
    raw_bytes = pdf_path.read_bytes()
    texto, formato = extraer_texto_documento(raw_bytes, pdf_path.name)

    if texto in (SCANNED_PDF_MARKER, DOC_NOT_SUPPORTED_MARKER):
        print(f"ERROR: No se pudo extraer texto ({texto})")
        sys.exit(1)
    if not texto or not texto.strip():
        print("ERROR: Texto extraído vacío")
        sys.exit(1)

    chars_totales = len(texto)
    print(f"  {chars_totales:,} chars | formato: {formato}")

    # ── 3. Safety check ANTES de enviar al modelo ─────────────────────────────
    tokens_estimados = _estimar_tokens(chars_totales)
    print(f"\n[2/4] Safety check de contexto...")
    print(f"  Chars totales  : {chars_totales:,}")
    print(f"  Tokens estimados (texto + prompt): ~{tokens_estimados:,}")
    print(f"  Límite seguro  : {_LIMITE_TOKENS_ESTIMADO:,}")
    print(f"  Límite modelo  : 200,000")

    if tokens_estimados > _LIMITE_TOKENS_ESTIMADO:
        print(
            f"\nABORTADO (exit 2) — Estimación de tokens ({tokens_estimados:,}) supera "
            f"el límite de seguridad ({_LIMITE_TOKENS_ESTIMADO:,}).\n"
            f"El texto NO fue enviado al modelo. Confirma antes de continuar."
        )
        sys.exit(2)

    print(f"  OK — {tokens_estimados:,} tokens estimados, dentro del límite. Cobertura = 100%")

    # ── 4. Normativa CCE ──────────────────────────────────────────────────────
    print(f"\n[3/4] Normativa CCE (modalidad={args.modalidad}, sector={args.sector})...")
    consulta_norm = (
        f"requisitos habilitantes experiencia financieros RUP "
        f"indice liquidez endeudamiento {args.modalidad} {args.sector}"
    )
    contexto_normativo = obtener_contexto_legal(
        args.modalidad, args.sector, consulta=consulta_norm, top_k=8
    )
    print(f"  {len(contexto_normativo):,} chars de normativa")

    licitacion = {
        "nombre_del_procedimiento": pdf_path.stem,
        "entidad":         "Entidad no especificada",
        "precio_base":     "0",
        "fase":            "Publicado",
        "id_del_proceso":  f"t9-sinrag-{pdf_path.stem[:30]}",
        "modalidad_seleccion": args.modalidad,
    }

    # ── 5. Agentes IA — sin RAG ───────────────────────────────────────────────
    print("\n[4/4] Agentes IA (texto completo, sin RAG)...")

    t_global = time.time()

    # Legal (sin_rag=True → pasa texto completo a Paso A, sin cap de 70 000 chars)
    t0 = time.time()
    resultado_legal = agente_legal_rag(
        licitacion, contexto_normativo, _EXPERIENCIA_NEUTRA,
        texto,  # texto COMPLETO, no contexto RAG
        cliente_id=None,
        sin_rag=True,
    )
    t_legal = round(time.time() - t0, 1)

    tokens_legal  = resultado_legal.pop("_tokens_uso", {})
    estado_an     = resultado_legal.pop("_estado_analisis", {"estado": "completo", "paso_a_exitoso": True, "paso_b_exitoso": True, "errores": []})
    n_legal       = len(resultado_legal.get("requisitos_habilitantes") or [])
    print(f"  Legal: {t_legal}s | {n_legal} habilitantes | análisis={estado_an.get('estado')}")

    # Financiero (sin_rag=True → pasa texto completo, sin cap de 70 000 chars)
    t0 = time.time()
    resultado_financiero = agente_financiero(
        licitacion, _PERFIL_NEUTRO,
        texto_pliego=texto,  # texto COMPLETO
        cliente_id=None,
        sin_rag=True,
    )
    t_fin = round(time.time() - t0, 1)

    tokens_fin = resultado_financiero.pop("_uso", {})
    n_fin      = len(resultado_financiero.get("checklist_detallado") or [])
    print(f"  Financiero: {t_fin}s | {n_fin} ítems")

    t_total = round(time.time() - t_global, 1)

    # ── 6. Métricas de tokens y costo ────────────────────────────────────────
    tok_in_paso_a  = tokens_legal.get("paso_a_input")  or 0
    tok_out_paso_a = tokens_legal.get("paso_a_output") or 0
    tok_in_paso_b  = tokens_legal.get("paso_b_input")  or 0
    tok_out_paso_b = tokens_legal.get("paso_b_output") or 0
    tok_in_fin     = tokens_fin.get("input_tokens")    or 0
    tok_out_fin    = tokens_fin.get("output_tokens")   or 0

    tok_in_total  = tok_in_paso_a + tok_in_paso_b + tok_in_fin
    tok_out_total = tok_out_paso_a + tok_out_paso_b + tok_out_fin
    costo_usd     = _costo_usd(tok_in_total, tok_out_total)

    metricas = {
        "chars_enviados":          chars_totales,
        "cobertura_pct":           100.0,
        "tokens_in_paso_a":        tok_in_paso_a,
        "tokens_out_paso_a":       tok_out_paso_a,
        "tokens_in_paso_b":        tok_in_paso_b,
        "tokens_out_paso_b":       tok_out_paso_b,
        "tokens_in_financiero":    tok_in_fin,
        "tokens_out_financiero":   tok_out_fin,
        "tokens_in_total":         tok_in_total,
        "tokens_out_total":        tok_out_total,
        "costo_estimado_usd":      round(costo_usd, 5),
        "tiempo_legal_s":          t_legal,
        "tiempo_financiero_s":     t_fin,
        "tiempo_total_s":          t_total,
    }

    # ── 7. Guardar JSON ──────────────────────────────────────────────────────
    resultado_final = {
        "experimento":     "sinrag_tarea9",
        "pliego":          pdf_path.name,
        "timestamp":       datetime.now().isoformat(),
        "modalidad":       args.modalidad,
        "sector":          args.sector,
        "estado_analisis": estado_an,
        "metricas":        metricas,
        "agente_legal":    resultado_legal,
        "agente_financiero": resultado_financiero,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(resultado_final, f, ensure_ascii=False, indent=2)
    print(f"\n  >> Guardado: {out_path.name}")

    # ── 8. Tabla de control (sin contenido de requisitos) ────────────────────
    sep = "─" * 78
    print(f"\n{sep}")
    print("TABLA DE CONTROL — Tarea 9 (sin RAG)")
    print(sep)
    print(f"  Pliego             : {pdf_path.name}")
    print(f"  Chars enviados     : {chars_totales:,}  (cobertura = 100%)")
    print(f"  Tokens entrada     : {tok_in_total:,}  "
          f"(A={tok_in_paso_a:,} | B={tok_in_paso_b:,} | Fin={tok_in_fin:,})")
    print(f"  Tokens salida      : {tok_out_total:,}  "
          f"(A={tok_out_paso_a:,} | B={tok_out_paso_b:,} | Fin={tok_out_fin:,})")
    print(f"  Costo estimado     : ${costo_usd:.4f} USD")
    print(f"  Tiempo total       : {t_total}s  (legal={t_legal}s | financiero={t_fin}s)")
    print(f"  Req. legales       : {n_legal}")
    print(f"  Req. financieros   : {n_fin}")
    print(f"  Estado análisis    : {estado_an.get('estado')}")
    print(sep)
    print(f"\nResultado guardado en: {out_path.resolve()}")


if __name__ == "__main__":
    main()
