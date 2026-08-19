# -*- coding: utf-8 -*-
"""
Tarea 7/8 — Corrida de evaluación sobre los pliegos en pliegos_evaluacion/.

Reglas:
  - Preflight de embeddings obligatorio; aborta con exit 2 si no responden.
  - Configuración congelada: top_k_por_query=5, MAX_CHARS=50_000, prompts sin tocar.
  - Perfil neutro (sin datos de cliente).
  - Guarda resultados_evaluacion/pliego_1.json ... pliego_N.json.
  - Task 8: continúa en caso de error de agente, reporta fallidos al final.
  - Tabla de control al final: sin contenido de requisitos.

Uso:
  py -3.13 evaluar_tarea7.py
  py -3.13 evaluar_tarea7.py --modalidad infraestructura_obra_publica --sector institucional
  py -3.13 evaluar_tarea7.py --config pliegos_evaluacion/config.json
  py -3.13 evaluar_tarea7.py --desde 3          # procesa desde el pliego #3 en adelante
  py -3.13 evaluar_tarea7.py --desde 3 --hasta 3  # reprocesa sólo el pliego #3
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
)
from evaluar_pliegos import (
    RAG_THRESHOLD,
    _SEP_RAG,
    _calcular_calidad_retrieval,
    _aplicar_contexto_insuficiente,
    _PERFIL_NEUTRO,
    _EXPERIENCIA_NEUTRA,
)

SALIDA = _ROOT / "resultados_evaluacion"
SALIDA.mkdir(exist_ok=True)


def evaluar_pliego(pdf_path: Path, modalidad: str, sector: str, indice: int) -> dict:
    """
    Análisis completo de un pliego. Retorna el resultado crudo.
    Lanza RuntimeError si retrieval no es 'completo'.
    No lanza excepción por fallo de agente — el resultado incluye estado_analisis.
    """
    print(f"\n{'='*62}")
    print(f"  [{indice}] {pdf_path.name}")
    print(f"{'='*62}")

    # 1. Extracción
    print("  [1/4] Extrayendo texto...")
    raw_bytes = pdf_path.read_bytes()
    texto, formato = extraer_texto_documento(raw_bytes, pdf_path.name)

    if texto in (SCANNED_PDF_MARKER, DOC_NOT_SUPPORTED_MARKER):
        raise RuntimeError(f"No se pudo extraer texto: {texto}")
    if not texto or not texto.strip():
        raise RuntimeError("Texto extraído vacío")

    print(f"         {len(texto):,} chars | formato: {formato}")

    # 2. RAG pliego
    rag_activado = len(texto) > RAG_THRESHOLD
    if rag_activado:
        print(f"  [2/4] RAG sobre pliego ({len(texto):,} chars > {RAG_THRESHOLD})...")
        query_rag = (
            f"requisitos habilitantes financieros experiencia tecnica juridica "
            f"{modalidad} {sector} RUP camara comercio indices financieros "
            f"liquidez endeudamiento valor acumulado contratos"
        )
        contexto_pliego, rag_meta = chunking_rag_pliego(texto, query=query_rag)
        if _SEP_RAG in contexto_pliego:
            chunks_lista = contexto_pliego.split(_SEP_RAG)
        else:
            chunks_lista = [contexto_pliego]
        print(f"         {len(chunks_lista)} chunks → {len(contexto_pliego):,} chars")
    else:
        print("  [2/4] Pliego corto — texto completo a Claude")
        contexto_pliego = texto
        chunks_lista    = [texto]
        rag_meta = {
            "embeddings_disponibles": True,
            "n_chunks_content":       1,
            "n_chunks_seleccionados": 1,
            "chars_enviados":         len(texto),
            "motivo_degradacion":     None,
        }

    calidad = _calcular_calidad_retrieval(
        chars_totales  = len(texto),
        chars_enviados = rag_meta["chars_enviados"],
        rag_activado   = rag_activado,
        rag_meta       = rag_meta,
    )
    print(f"         retrieval={calidad['estado']} | cobertura={calidad['cobertura_pct']}%")

    # ── STOP si retrieval no es completo (el RAG mismo falló) ────────────────
    if calidad["estado"] != "completo":
        raise RuntimeError(
            f"Retrieval {calidad['estado']}: {calidad['motivo_degradacion']}  "
            f"(chars_enviados={calidad['chars_enviados']:,}, "
            f"cobertura={calidad['cobertura_pct']}%)"
        )

    # 3. Normativa CCE
    print(f"  [3/4] Normativa CCE (modalidad={modalidad}, sector={sector})...")
    consulta_norm = (
        f"requisitos habilitantes experiencia financieros RUP "
        f"indice liquidez endeudamiento {modalidad} {sector}"
    )
    contexto_normativo = obtener_contexto_legal(
        modalidad, sector, consulta=consulta_norm, top_k=8
    )
    print(f"         {len(contexto_normativo):,} chars de normativa")

    licitacion = {
        "nombre_del_procedimiento": pdf_path.stem,
        "entidad":         "Entidad no especificada",
        "precio_base":     "0",
        "fase":            "Publicado",
        "id_del_proceso":  f"t7-{indice}-{pdf_path.stem[:30]}",
        "modalidad_seleccion": modalidad,
    }

    # 4. Agentes IA
    print("  [4/4] Agentes IA (legal + financiero)...")

    t0 = time.time()
    resultado_legal = agente_legal_rag(
        licitacion, contexto_normativo, _EXPERIENCIA_NEUTRA,
        contexto_pliego, cliente_id=None,
    )
    t_legal = round(time.time() - t0, 1)
    n_legal = len(resultado_legal.get("requisitos_habilitantes") or [])
    estado_an = resultado_legal.get("_estado_analisis", {}).get("estado", "completo")
    print(f"         legal: {t_legal}s | {n_legal} habilitantes | análisis={estado_an}")

    t0 = time.time()
    resultado_financiero = agente_financiero(
        licitacion, _PERFIL_NEUTRO, texto_pliego=contexto_pliego, cliente_id=None,
    )
    t_fin = round(time.time() - t0, 1)
    n_fin = len(resultado_financiero.get("checklist_detallado") or [])
    print(f"         financiero: {t_fin}s | {n_fin} ítems")

    if calidad["estado"] in ("degradado", "fallido"):
        _aplicar_contexto_insuficiente(resultado_legal, resultado_financiero)

    # Promover _estado_analisis al top-level del resultado
    estado_analisis = resultado_legal.pop("_estado_analisis", {
        "estado": "completo", "paso_a_exitoso": True, "paso_b_exitoso": True, "errores": [],
    })

    return {
        "indice":    indice,
        "pliego":    pdf_path.name,
        "modalidad": modalidad,
        "sector":    sector,
        "timestamp": datetime.now().isoformat(),

        "calidad_retrieval": calidad,
        "estado_analisis":   estado_analisis,

        "retrieval": {
            "formato_detectado":             formato,
            "texto_chars_total":             len(texto),
            "rag_activado":                  rag_activado,
            "chunks_recuperados_n":          len(chunks_lista),
            "contexto_chars_enviado_claude": len(contexto_pliego),
            "normativa_chars_enviada":       len(contexto_normativo),
        },

        "agente_legal":      resultado_legal,
        "agente_financiero": resultado_financiero,

        "tiempos_segundos": {
            "legal":      t_legal,
            "financiero": t_fin,
            "total":      round(t_legal + t_fin, 1),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Tarea 7/8 — Evaluación por lote con línea base congelada")
    parser.add_argument("--modalidad", default="infraestructura_obra_publica")
    parser.add_argument("--sector",    default="institucional")
    parser.add_argument("--config",    default=None,
                        help="JSON con modalidad/sector por PDF")
    parser.add_argument("--desde",     type=int, default=1,
                        help="Número de pliego desde el que iniciar (1-based, inclusive)")
    parser.add_argument("--hasta",     type=int, default=None,
                        help="Número de pliego hasta el que procesar (1-based, inclusive)")
    args = parser.parse_args()

    # ── Preflight OBLIGATORIO ─────────────────────────────────────────────────
    print("=" * 62)
    print("TAREA 7/8 — Preflight de embeddings")
    print("=" * 62)
    emb = verificar_embeddings()
    if not emb["disponible"]:
        print("\nABORTADO (exit 2) — Embeddings no disponibles.")
        print(f"Error: {emb['error']}")
        sys.exit(2)
    print("  Embeddings OK")

    config_por_pliego: dict = {}
    if args.config:
        cfg_path = Path(args.config)
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                config_por_pliego = json.load(f)
            print(f"  Config: {len(config_por_pliego)} entradas desde {cfg_path.name}")

    carpeta = _ROOT / "pliegos_evaluacion"
    pdfs = sorted(carpeta.glob("*.pdf"))
    if not pdfs:
        print("No se encontraron PDFs en 'pliegos_evaluacion/'.")
        sys.exit(1)

    print(f"\n{len(pdfs)} PDFs encontrados:")
    for i, p in enumerate(pdfs, 1):
        marcador = ""
        if i < args.desde:
            marcador = "  [omitido]"
        elif args.hasta and i > args.hasta:
            marcador = "  [omitido]"
        print(f"  {i}. {p.name}{marcador}")

    # ── Ejecución ─────────────────────────────────────────────────────────────
    print(f"\nInicio: {datetime.now().strftime('%H:%M:%S')}")
    filas_tabla  = []
    fallidos     = []

    for indice, pdf_path in enumerate(pdfs, 1):
        # Respetar rango --desde / --hasta
        if indice < args.desde:
            continue
        if args.hasta and indice > args.hasta:
            break

        cfg      = config_por_pliego.get(pdf_path.name, {})
        modalidad = cfg.get("modalidad", args.modalidad)
        sector    = cfg.get("sector",    args.sector)

        t_inicio = time.time()
        resultado = None

        try:
            resultado = evaluar_pliego(pdf_path, modalidad, sector, indice)

        except RuntimeError as exc:
            # Errores no retriables (PDF escaneado, retrieval fallido)
            print(f"\n{'!'*62}")
            print(f"  ERROR RETRIEVAL en pliego {indice}: {pdf_path.name}")
            print(f"  Motivo: {exc}")
            print(f"{'!'*62}")
            fallidos.append({
                "indice": indice, "nombre": pdf_path.name,
                "tipo": "retrieval", "error": str(exc),
            })
            continue

        except Exception as exc:
            print(f"\n{'!'*62}")
            print(f"  ERROR inesperado en pliego {indice}: {pdf_path.name}")
            print(f"  {type(exc).__name__}: {exc}")
            print(f"{'!'*62}")
            fallidos.append({
                "indice": indice, "nombre": pdf_path.name,
                "tipo": type(exc).__name__, "error": str(exc),
            })
            continue

        t_total = round(time.time() - t_inicio, 1)
        resultado["tiempo_total_segundos"] = t_total

        # Guardar JSON
        out_path = SALIDA / f"pliego_{indice}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
        print(f"  >> {out_path.name} | {t_total}s total")

        cr = resultado["calidad_retrieval"]
        ea = resultado["estado_analisis"]
        filas_tabla.append({
            "indice":        indice,
            "nombre":        pdf_path.name[:50],
            "chars_total":   resultado["retrieval"]["texto_chars_total"],
            "chars_env":     cr["chars_enviados"],
            "cobertura":     cr["cobertura_pct"],
            "retrieval":     cr["estado"],
            "analisis":      ea.get("estado", "completo"),
            "n_legal":       len(resultado["agente_legal"].get("requisitos_habilitantes") or []),
            "n_fin":         len(resultado["agente_financiero"].get("checklist_detallado") or []),
            "tiempo_s":      t_total,
        })

    # ── Tabla de control ──────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"Fin: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*62}\n")

    ctrl_path = SALIDA / "t7_tabla_control.json"
    with open(ctrl_path, "w", encoding="utf-8") as f:
        json.dump({
            "generado":  datetime.now().isoformat(),
            "n_pliegos": len(filas_tabla),
            "tabla":     filas_tabla,
            "fallidos":  fallidos,
        }, f, ensure_ascii=False, indent=2)

    sep = "─" * 118
    print(sep)
    print(f"{'#':>2}  {'Pliego':<50}  {'Chars tot':>10}  {'Chars env':>10}  {'Cob%':>6}  {'Retrieval':<10}  {'Análisis':<10}  {'Legal':>6}  {'Fin':>5}  {'T(s)':>7}")
    print(sep)
    for fila in filas_tabla:
        print(
            f"{fila['indice']:>2}  {fila['nombre']:<50}  "
            f"{fila['chars_total']:>10,}  {fila['chars_env']:>10,}  "
            f"{fila['cobertura']:>5.1f}%  {fila['retrieval']:<10}  "
            f"{fila['analisis']:<10}  "
            f"{fila['n_legal']:>6}  {fila['n_fin']:>5}  {fila['tiempo_s']:>7.1f}"
        )
    print(sep)

    if fallidos:
        print(f"\nPLIEGOS FALLIDOS ({len(fallidos)}):")
        for fl in fallidos:
            print(f"  [{fl['indice']}] {fl['nombre']}  ({fl['tipo']}: {fl['error'][:80]})")

    print(f"\nResultados individuales: {SALIDA.resolve()}")
    print(f"Tabla control:           {ctrl_path.name}")


if __name__ == "__main__":
    main()
