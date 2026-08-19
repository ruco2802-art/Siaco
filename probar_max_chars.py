# -*- coding: utf-8 -*-
"""
Tarea 6 — Comparación de presupuestos de contexto.

Corre el SAMC-IET-001-2026 con tres valores de MAX_CHARS y registra:
  - chars_enviados, cobertura_pct
  - fuente="pliego"  (encontrado con valor real)
  - exigido_literal="NO_ENCONTRADO_EN_PLIEGO"
  - requisitos nuevos en B o C que no estaban en A
  - tiempos y tokens de Paso A / Paso B / financiero

Uso:
  py -3.13 probar_max_chars.py
  py -3.13 probar_max_chars.py --pdf <nombre_pdf>   # otro pliego
  py -3.13 probar_max_chars.py --corridas A B       # solo algunas corridas
"""
import argparse
import json
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
    chunking_rag_pliego,
    agente_legal_rag,
    agente_financiero,
    obtener_contexto_legal,
    verificar_embeddings,
    SCANNED_PDF_MARKER,
    DOC_NOT_SUPPORTED_MARKER,
    NO_ANALIZADO_SENTINEL,
)
from evaluar_pliegos import (
    RAG_THRESHOLD,
    _SEP_RAG,
    _calcular_calidad_retrieval,
    _PERFIL_NEUTRO,
    _EXPERIENCIA_NEUTRA,
)

# ── Configuración de las corridas ─────────────────────────────────────────────
CORRIDAS = {
    "A": 50_000,
    "B": 100_000,
    "C": 150_000,
}

MODALIDAD = "infraestructura_obra_publica"
SECTOR    = "institucional"

_NO_ENC = "NO_ENCONTRADO_EN_PLIEGO"


def correr_una(pdf_path: Path, max_chars: int, label: str, texto: str, contexto_normativo: str) -> dict:
    """
    Ejecuta RAG + ambos agentes para un MAX_CHARS dado.
    `texto` y `contexto_normativo` ya están extraídos (se reusan entre corridas).
    """
    print(f"\n{'─'*60}")
    print(f"CORRIDA {label} — MAX_CHARS={max_chars:,}")
    print(f"{'─'*60}")

    licitacion = {
        "nombre_del_procedimiento": f"TAREA6-{label}: {pdf_path.stem}",
        "entidad": "Entidad no especificada",
        "precio_base": "0",
        "fase": "Publicado",
        "id_del_proceso": f"t6-{label}-{pdf_path.stem[:30]}",
        "modalidad_seleccion": MODALIDAD,
    }

    # RAG con el max_chars de esta corrida
    t_rag = time.time()
    query_rag = (
        "requisitos habilitantes financieros experiencia tecnica juridica "
        f"{MODALIDAD} {SECTOR} RUP camara comercio indices financieros "
        "liquidez endeudamiento valor acumulado contratos"
    )
    contexto_pliego, rag_meta = chunking_rag_pliego(texto, query=query_rag, max_chars=max_chars)
    t_rag = round(time.time() - t_rag, 1)

    if _SEP_RAG in contexto_pliego:
        chunks_lista = contexto_pliego.split(_SEP_RAG)
    else:
        chunks_lista = [contexto_pliego]

    calidad = _calcular_calidad_retrieval(
        chars_totales  = len(texto),
        chars_enviados = rag_meta["chars_enviados"],
        rag_activado   = True,
        rag_meta       = rag_meta,
    )

    print(f"  RAG: {len(chunks_lista)} chunks, {len(contexto_pliego):,} chars "
          f"({calidad['cobertura_pct']}% doc) | {t_rag}s")
    if calidad["estado"] != "completo":
        print(f"  [!] ESTADO {calidad['estado']}: {calidad['motivo_degradacion']}")
        return {
            "label": label, "max_chars": max_chars,
            "calidad_retrieval": calidad,
            "error": "Retrieval degradado — corrida invalida para comparación",
        }

    # Agente legal
    t_legal = time.time()
    resultado_legal = agente_legal_rag(
        licitacion, contexto_normativo, _EXPERIENCIA_NEUTRA,
        contexto_pliego, cliente_id=None,
    )
    t_legal = round(time.time() - t_legal, 1)

    # Agente financiero
    t_fin = time.time()
    resultado_financiero = agente_financiero(
        licitacion, _PERFIL_NEUTRO, texto_pliego=contexto_pliego, cliente_id=None,
    )
    t_fin = round(time.time() - t_fin, 1)

    reqs    = resultado_legal.get("requisitos_habilitantes") or []
    fin_its = resultado_financiero.get("checklist_detallado") or []

    return {
        "label":           label,
        "max_chars":       max_chars,
        "calidad_retrieval": calidad,
        "t_rag_s":         t_rag,
        "t_legal_s":       t_legal,
        "t_fin_s":         t_fin,
        "t_total_s":       round(t_rag + t_legal + t_fin, 1),
        "score_juridico":  resultado_legal.get("score_juridico"),
        "score_financiero": resultado_financiero.get("score_financiero"),
        "requisitos_legales":   reqs,
        "requisitos_financiero": fin_its,
    }


def _clasificar(reqs: list) -> tuple[list, list]:
    """Devuelve (encontrados_con_valor, no_encontrados)."""
    encontrados = [r for r in reqs if r.get("exigido_literal") not in (_NO_ENC, NO_ANALIZADO_SENTINEL, None, "")]
    no_enc      = [r for r in reqs if r.get("exigido_literal") in (_NO_ENC, NO_ANALIZADO_SENTINEL)]
    return encontrados, no_enc


def _clasificar_fin(items: list) -> tuple[list, list]:
    no_enc = [it for it in items if (it.get("valor_pliego") or "").startswith(_NO_ENC)
              or (it.get("valor_pliego") or "") == NO_ANALIZADO_SENTINEL]
    enc    = [it for it in items if it not in no_enc]
    return enc, no_enc


def imprimir_tabla(resultados: list[dict]):
    print("\n" + "="*70)
    print("TABLA COMPARATIVA — PRESUPUESTO DE CONTEXTO")
    print("="*70)

    # Encabezado
    print(f"{'Métrica':<45} {'A':>10} {'B':>10} {'C':>10}")
    print(f"{'MAX_CHARS configurado':.<45} {'50.000':>10} {'100.000':>10} {'150.000':>10}")

    def fila(label, fn, fmt=None):
        vals = []
        for r in resultados:
            if "error" in r:
                vals.append("ERROR")
            else:
                v = fn(r)
                vals.append(fmt.format(v) if fmt else str(v))
        print(f"{label:<45} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10}")

    fila("chars_enviados a Claude",
         lambda r: f"{r['calidad_retrieval']['chars_enviados']:,}")
    fila("cobertura_pct del documento",
         lambda r: f"{r['calidad_retrieval']['cobertura_pct']}%")
    fila("estado retrieval",
         lambda r: r["calidad_retrieval"]["estado"])

    print(f"{'─'*70}")

    # Requisitos legales
    for r in resultados:
        if "error" not in r:
            enc, no = _clasificar(r["requisitos_legales"])
            r["_enc_l"] = enc
            r["_no_l"]  = no
        else:
            r["_enc_l"] = r["_no_l"] = []

    fila("Requisitos legales — fuente=pliego (valor real)",
         lambda r: len(r["_enc_l"]))
    fila("Requisitos legales — NO_ENCONTRADO_EN_PLIEGO",
         lambda r: len(r["_no_l"]))
    fila("Total requisitos legales extraídos",
         lambda r: len(r.get("requisitos_legales") or []))

    print(f"{'─'*70}")

    # Financiero
    for r in resultados:
        if "error" not in r:
            enc_f, no_f = _clasificar_fin(r["requisitos_financiero"])
            r["_enc_f"] = enc_f
            r["_no_f"]  = no_f
        else:
            r["_enc_f"] = r["_no_f"] = []

    fila("Ítems financieros — valor real del pliego",
         lambda r: len(r["_enc_f"]))
    fila("Ítems financieros — NO_ENCONTRADO_EN_PLIEGO",
         lambda r: len(r["_no_f"]))

    print(f"{'─'*70}")

    # Tiempos
    fila("Tiempo RAG (s)",
         lambda r: r.get("t_rag_s", "—"))
    fila("Tiempo legal (s)",
         lambda r: r.get("t_legal_s", "—"))
    fila("Tiempo financiero (s)",
         lambda r: r.get("t_fin_s", "—"))
    fila("Tiempo TOTAL (s)",
         lambda r: r.get("t_total_s", "—"))

    print(f"{'─'*70}")

    # Score
    fila("score_juridico",
         lambda r: r.get("score_juridico", "—"))
    fila("score_financiero",
         lambda r: r.get("score_financiero", "—"))

    # Diferencias entre corridas
    print("\n" + "="*70)
    print("REQUISITOS NUEVOS EN B o C (no presentes en A con valor real)")
    print("="*70)
    if all("error" not in r for r in resultados):
        req_a_nombres = {r["requisito"] for r in resultados[0]["_enc_l"]}

        for r in resultados[1:]:
            label = r["label"]
            nuevos = [req for req in r["_enc_l"] if req["requisito"] not in req_a_nombres]
            if nuevos:
                print(f"\nCorrida {label} — {len(nuevos)} requisito(s) nuevos con valor real:")
                for req in nuevos:
                    print(f"  + {req.get('requisito')}")
                    print(f"    exigido_literal: {req.get('exigido_literal', '')[:120]}")
                    print(f"    ubicacion_pliego: {req.get('ubicacion_pliego')}")
            else:
                print(f"\nCorrida {label}: sin requisitos nuevos vs corrida A")

        # También los que estaban en A como NO_ENCONTRADO y en B/C como pliego
        no_a_nombres = {r["requisito"] for r in resultados[0]["_no_l"]}
        print("\nDE NO_ENCONTRADO_EN_PLIEGO (A) → valor real (B o C):")
        for r in resultados[1:]:
            label = r["label"]
            recuperados = [req for req in r["_enc_l"]
                          if req["requisito"] in no_a_nombres]
            if recuperados:
                print(f"\n  Corrida {label} — {len(recuperados)} requisito(s) recuperados:")
                for req in recuperados:
                    print(f"  * {req.get('requisito')}")
                    print(f"    exigido_literal: {req.get('exigido_literal', '')[:120]}")
                    print(f"    ubicacion_pliego: {req.get('ubicacion_pliego')}")
            else:
                print(f"\n  Corrida {label}: ningún NO_ENCONTRADO de A se recuperó")
    else:
        print("  Una o más corridas tuvieron error — comparación parcial")

    print()


def main():
    parser = argparse.ArgumentParser(description="Tarea 6 — comparación MAX_CHARS")
    parser.add_argument("--pdf",     default=None, help="Nombre del PDF en pliegos_evaluacion/")
    parser.add_argument("--corridas", nargs="+", choices=["A","B","C"], default=["A","B","C"],
                        help="Qué corridas ejecutar (default: A B C)")
    args = parser.parse_args()

    carpeta = _ROOT / "pliegos_evaluacion"
    if args.pdf:
        pdf_path = carpeta / args.pdf
        if not pdf_path.exists():
            print(f"Error: '{pdf_path}' no existe.")
            sys.exit(1)
    else:
        pdfs = sorted(carpeta.glob("*.pdf"))
        if not pdfs:
            print("No se encontraron PDFs en 'pliegos_evaluacion/'.")
            sys.exit(1)
        pdf_path = pdfs[0]

    print(f"Pliego: {pdf_path.name}")
    print(f"Corridas: {' '.join(args.corridas)}")
    print(f"Timestamp: {datetime.now().isoformat()}")

    # ── Verificar embeddings ──────────────────────────────────────────────────
    print("\nVerificando servicio de embeddings...")
    emb = verificar_embeddings()
    if not emb["disponible"]:
        print(f"ABORTADO — embeddings no disponibles: {emb['error']}")
        print("Las corridas necesitan embeddings operativos para ser comparables.")
        sys.exit(2)
    print("  Embeddings OK")

    # ── Extraer texto (una sola vez) ──────────────────────────────────────────
    print(f"\nExtrayendo texto de '{pdf_path.name}'...")
    raw_bytes = pdf_path.read_bytes()
    texto, formato = extraer_texto_documento(raw_bytes, pdf_path.name)
    if texto in (SCANNED_PDF_MARKER, DOC_NOT_SUPPORTED_MARKER) or not texto.strip():
        print(f"Error extrayendo texto: {texto[:60]}")
        sys.exit(1)
    print(f"  {len(texto):,} chars | formato: {formato}")

    # ── Normativa CCE (una sola vez) ──────────────────────────────────────────
    print(f"\nRecuperando normativa CCE (modalidad={MODALIDAD}, sector={SECTOR})...")
    consulta_rag_norm = (
        f"requisitos habilitantes experiencia financieros RUP "
        f"indice liquidez endeudamiento {MODALIDAD} {SECTOR}"
    )
    contexto_normativo = obtener_contexto_legal(
        MODALIDAD, SECTOR, consulta=consulta_rag_norm, top_k=8
    )
    print(f"  {len(contexto_normativo):,} chars de normativa")

    # ── Ejecutar cada corrida ─────────────────────────────────────────────────
    resultados = []
    salida_dir = _ROOT / "resultados_evaluacion"
    salida_dir.mkdir(exist_ok=True)

    for label in args.corridas:
        max_chars = CORRIDAS[label]
        r = correr_una(pdf_path, max_chars, label, texto, contexto_normativo)
        resultados.append(r)

        # Guardar JSON individual
        out = salida_dir / f"t6_corrida_{label.lower()}_{pdf_path.stem[:30]}.json"
        with open(out, "w", encoding="utf-8") as f:
            # No serializar el texto completo de los chunks (muy grande)
            r_slim = {k: v for k, v in r.items() if k not in ("_enc_l","_no_l","_enc_f","_no_f")}
            json.dump(r_slim, f, ensure_ascii=False, indent=2)
        print(f"  Guardado: {out.name}")

        # Verificar que embeddings siguen activos entre corridas
        if label != args.corridas[-1]:
            emb_check = verificar_embeddings()
            if not emb_check["disponible"]:
                print(f"\n[!] EMBEDDINGS CAÍDOS entre corridas — abortando. Error: {emb_check['error']}")
                print("Las corridas completadas hasta aquí pueden no ser comparables con las pendientes.")
                break

    # ── Tabla comparativa ─────────────────────────────────────────────────────
    if len(resultados) >= 2:
        imprimir_tabla(resultados)
    else:
        print("\nMenos de 2 corridas completadas — sin tabla comparativa.")

    # Guardar tabla como JSON también
    tabla_out = salida_dir / "t6_tabla_comparativa.json"
    with open(tabla_out, "w", encoding="utf-8") as f:
        resumen = []
        for r in resultados:
            resumen.append({
                "label":            r["label"],
                "max_chars":        r["max_chars"],
                "calidad_retrieval": r["calidad_retrieval"],
                "t_total_s":        r.get("t_total_s"),
                "score_juridico":   r.get("score_juridico"),
                "score_financiero": r.get("score_financiero"),
                "n_legal_encontrado": len(r.get("_enc_l", [])),
                "n_legal_no_enc":    len(r.get("_no_l", [])),
                "n_fin_encontrado":  len(r.get("_enc_f", [])),
                "n_fin_no_enc":      len(r.get("_no_f", [])),
                "requisitos_legales": r.get("requisitos_legales", []),
                "requisitos_financiero": r.get("requisitos_financiero", []),
            })
        json.dump({"generado": datetime.now().isoformat(), "corridas": resumen},
                  f, ensure_ascii=False, indent=2)
    print(f"\nTabla JSON: {tabla_out.name}")


if __name__ == "__main__":
    main()
