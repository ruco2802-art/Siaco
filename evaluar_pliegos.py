# -*- coding: utf-8 -*-
"""
evaluar_pliegos.py — Evaluación de extracción de habilitantes SIACO v3.0

Uso:
  # 1 pliego de prueba (recomendado primero)
  py -3.13 evaluar_pliegos.py pliegos_evaluacion --test

  # Todos los PDFs de la carpeta
  py -3.13 evaluar_pliegos.py pliegos_evaluacion

  # Con modalidad/sector explícitos (override del default)
  py -3.13 evaluar_pliegos.py pliegos_evaluacion --modalidad infraestructura_menor_cuantia --sector salud

  # Pliego específico por índice (0-based)
  py -3.13 evaluar_pliegos.py pliegos_evaluacion --indice 3

Config por pliego (opcional):
  Crea pliegos_evaluacion/config.json para dar modalidad/sector distintos por PDF:
  {
    "pliego_salud_01.pdf": {"modalidad": "infraestructura_obra_publica", "sector": "salud"},
    "pliego_educ_02.pdf":  {"modalidad": "infraestructura_menor_cuantia", "sector": "educacion"}
  }
  Los PDFs sin entrada en config.json usan el default (--modalidad / --sector).

Salida:
  resultados_evaluacion/
    {nombre_pdf}_resultado.json   — resultado completo por pliego
    tabla_resumen.json            — vista unificada de todos los pliegos
"""

import argparse
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# ── UTF-8 global — evita UnicodeEncodeError en consola Windows (CP1252) ───────
# Necesario porque analizador.py tiene prints con → (U+2192) dentro de bloques
# try/except — si el print falla, el except lo captura y hace fallback al RAG
# no semántico. Forzar UTF-8 aquí evita ese efecto lateral sin tocar analizador.py.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# ── Setup de path y .env ──────────────────────────────────────────────────────
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
    COBERTURA_NORMAL_MIN_PCT,
)

# ── Constantes ────────────────────────────────────────────────────────────────
RAG_THRESHOLD = 8_000      # misma lógica que auditoria.py
_SEP_RAG      = "\n\n[...]\n\n"   # separador de chunking_rag_pliego

# Sentinel para el tipo "no encontrado" en contexto degradado
_NO_ENC = "NO_ENCONTRADO_EN_PLIEGO"


def _calcular_calidad_retrieval(
    chars_totales: int,
    chars_enviados: int,
    rag_activado: bool,
    rag_meta: dict,
) -> dict:
    """
    Construye el bloque calidad_retrieval según el resultado del RAG.
    Estado:
      completo  — embeddings operativos y cobertura dentro del rango normal
      degradado — embeddings caídos (fallback) o cobertura por debajo del umbral
      fallido   — sin texto útil extraído del documento
    """
    chars_esperados = min(50_000, chars_totales)  # MAX_CHARS de chunking_rag_pliego
    if chars_totales == 0:
        cobertura_pct = 0.0
    else:
        cobertura_pct = round(chars_enviados / chars_totales * 100, 1)

    emb_ok  = rag_meta.get("embeddings_disponibles", False)
    motivo  = rag_meta.get("motivo_degradacion")

    if not rag_activado:
        # Texto completo enviado directamente
        estado = "completo"
        motivo = None
    elif chars_enviados == 0:
        estado = "fallido"
        motivo = motivo or "No se pudo extraer texto útil del documento"
    elif not emb_ok:
        estado = "degradado"
        motivo = motivo or "Servicio de embeddings no disponible — retrieval en modo fallback"
    elif cobertura_pct < COBERTURA_NORMAL_MIN_PCT:
        estado = "degradado"
        motivo = motivo or f"Cobertura {cobertura_pct}% < umbral {COBERTURA_NORMAL_MIN_PCT}%"
    else:
        estado = "completo"
        motivo = None

    return {
        "estado":                   estado,
        "chars_enviados":           chars_enviados,
        "chars_esperados":          chars_esperados,
        "chars_totales_documento":  chars_totales,
        "cobertura_pct":            cobertura_pct,
        "embeddings_disponibles":   emb_ok,
        "motivo_degradacion":       motivo,
    }


def _reemplazar_sentinel(obj, viejo: str, nuevo: str):
    """
    Recorre recursivamente dicts/listas y reemplaza el valor exacto `viejo` por `nuevo`.
    Modifica `obj` in-place y lo retorna.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v == viejo:
                obj[k] = nuevo
            elif isinstance(v, (dict, list)):
                _reemplazar_sentinel(v, viejo, nuevo)
    elif isinstance(obj, list):
        for item in obj:
            _reemplazar_sentinel(item, viejo, nuevo)
    return obj


def _aplicar_contexto_insuficiente(resultado_legal: dict, resultado_financiero: dict) -> None:
    """
    Cuando el retrieval está degradado, reemplaza NO_ENCONTRADO_EN_PLIEGO por
    NO_ANALIZADO_CONTEXTO_INSUFICIENTE en los campos evaluados de ambos agentes,
    y actualiza fuente='contexto_insuficiente' donde corresponda.
    """
    for req in resultado_legal.get("requisitos_habilitantes") or []:
        if req.get("exigido_literal") == _NO_ENC:
            req["exigido_literal"] = NO_ANALIZADO_SENTINEL
            req["exigido"]         = NO_ANALIZADO_SENTINEL
        if req.get("documento_soporte") == _NO_ENC:
            req["documento_soporte"] = NO_ANALIZADO_SENTINEL
        if req.get("fuente") == "no_encontrado":
            req["fuente"] = "contexto_insuficiente"

    for item in resultado_financiero.get("checklist_detallado") or []:
        if item.get("valor_pliego") == _NO_ENC or (
            isinstance(item.get("valor_pliego"), str)
            and item["valor_pliego"].startswith(_NO_ENC)
        ):
            item["valor_pliego"]   = NO_ANALIZADO_SENTINEL
            item["exigido_literal"] = NO_ANALIZADO_SENTINEL
        if item.get("fuente") == "no_encontrado":
            item["fuente"] = "contexto_insuficiente"

# Perfil neutro: sin datos del cliente para que la extracción refleje
# únicamente lo que dice el pliego, no lo que tiene o falta al proponente.
_PERFIL_NEUTRO = {
    "nombre": "Evaluación — Perfil Neutro",
    "sector": "",
    "rup": {
        "tiene_rup": False,
        "estado_rup": "No especificado",
        "numero_rup": "",
    },
    "financiero": {
        "indice_liquidez": 0,
        "indice_endeudamiento": 0,
        "razon_cobertura_interes": 0,
        "capital_trabajo": 0,
        "patrimonio_liquido": 0,
        "presupuesto_maximo_contrato": 0,
        "presupuesto_minimo_contrato": 0,
    },
    "experiencia": {
        "valor_acumulado": 0,
        "valor_individual_max": 0,
        "objeto_similar": "No especificado",
        "codigos_unspsc": "",
        "participacion_minima": 0,
    },
    "codigos_unspsc_permitidos": [],
}

_EXPERIENCIA_NEUTRA = _PERFIL_NEUTRO["experiencia"]


# ── Función principal de evaluación ──────────────────────────────────────────

def evaluar_un_pliego(pdf_path: Path, modalidad: str, sector: str) -> dict:
    """
    Extrae texto del PDF, aplica RAG, llama a los dos agentes IA con perfil
    neutro y devuelve el resultado crudo completo incluyendo los chunks
    recuperados por el retriever.
    """
    # 1. Extracción de texto ──────────────────────────────────────────────────
    print(f"  [1/4] Extrayendo texto de '{pdf_path.name}'...")
    raw_bytes = pdf_path.read_bytes()
    texto, formato = extraer_texto_documento(raw_bytes, pdf_path.name)

    if texto == SCANNED_PDF_MARKER:
        return {
            "pliego": pdf_path.name,
            "error": "PDF escaneado sin OCR — no se puede extraer texto seleccionable.",
            "formato_detectado": formato,
        }
    if texto == DOC_NOT_SUPPORTED_MARKER or not texto or not texto.strip():
        return {
            "pliego": pdf_path.name,
            "error": f"No se pudo extraer texto (formato={formato}).",
            "formato_detectado": formato,
        }

    print(f"       {len(texto):,} chars extraídos | formato: {formato}")

    # 2. RAG sobre el pliego ──────────────────────────────────────────────────
    rag_activado = len(texto) > RAG_THRESHOLD
    if rag_activado:
        print(f"  [2/4] RAG sobre pliego ({len(texto):,} chars > {RAG_THRESHOLD})...")
        query_rag = (
            f"requisitos habilitantes financieros experiencia tecnica juridica "
            f"{modalidad} {sector} RUP camara comercio indices financieros "
            f"liquidez endeudamiento valor acumulado contratos"
        )
        contexto_pliego, rag_meta = chunking_rag_pliego(texto, query=query_rag)
        # Recuperar chunks individuales para diagnóstico
        if _SEP_RAG in contexto_pliego:
            chunks_lista = contexto_pliego.split(_SEP_RAG)
        else:
            chunks_lista = [contexto_pliego]
        print(f"       {len(chunks_lista)} chunks → {len(contexto_pliego):,} chars enviados a Claude")
    else:
        print(f"  [2/4] Pliego corto — sin RAG, texto completo a Claude")
        contexto_pliego = texto
        chunks_lista    = [texto]
        rag_meta        = {
            "embeddings_disponibles": True,
            "n_chunks_content":       1,
            "n_chunks_seleccionados": 1,
            "chars_enviados":         len(texto),
            "motivo_degradacion":     None,
        }

    calidad_retrieval = _calcular_calidad_retrieval(
        chars_totales  = len(texto),
        chars_enviados = rag_meta["chars_enviados"],
        rag_activado   = rag_activado,
        rag_meta       = rag_meta,
    )
    if calidad_retrieval["estado"] != "completo":
        print(
            f"  [!] RETRIEVAL {calidad_retrieval['estado'].upper()}: "
            f"{calidad_retrieval['motivo_degradacion']}"
        )

    # 3. RAG sobre biblioteca normativa CCE ───────────────────────────────────
    print(f"  [3/4] Recuperando normativa CCE (modalidad={modalidad}, sector={sector})...")
    consulta_rag_norm = (
        f"requisitos habilitantes experiencia financieros RUP "
        f"indice liquidez endeudamiento {modalidad} {sector}"
    )
    contexto_normativo = obtener_contexto_legal(
        modalidad, sector, consulta=consulta_rag_norm, top_k=8
    )
    print(f"       {len(contexto_normativo):,} chars de normativa")

    licitacion = {
        "nombre_del_procedimiento": f"Evaluación: {pdf_path.stem}",
        "entidad":           "Entidad no especificada",
        "precio_base":       "0",
        "fase":              "Publicado",
        "id_del_proceso":    f"eval-{pdf_path.stem[:40]}",
        "modalidad_seleccion": modalidad,
    }

    # 4. Agentes IA ───────────────────────────────────────────────────────────
    print(f"  [4/4] Llamando agentes IA (legal + financiero, en secuencia)...")

    t0 = time.time()
    resultado_legal = agente_legal_rag(
        licitacion,
        contexto_normativo,
        _EXPERIENCIA_NEUTRA,
        contexto_pliego,
        cliente_id=None,
    )
    t_legal = round(time.time() - t0, 1)
    print(f"       Agente legal:      {t_legal}s | "
          f"score_juridico={resultado_legal.get('score_juridico')} | "
          f"{len(resultado_legal.get('requisitos_habilitantes') or [])} habilitantes")

    t0 = time.time()
    resultado_financiero = agente_financiero(
        licitacion,
        _PERFIL_NEUTRO,
        texto_pliego=contexto_pliego,
        cliente_id=None,
    )
    t_fin = round(time.time() - t0, 1)
    print(f"       Agente financiero: {t_fin}s | "
          f"score_financiero={resultado_financiero.get('score_financiero')} | "
          f"{len(resultado_financiero.get('checklist_detallado') or [])} items financieros")

    # 5. Post-procesar sentinels cuando retrieval degradado ───────────────────
    if calidad_retrieval["estado"] in ("degradado", "fallido"):
        _aplicar_contexto_insuficiente(resultado_legal, resultado_financiero)

    # 6. Etiquetar requisitos por agente de origen ───────────────────────────
    habilitantes = [
        {**r, "_agente": "legal"}
        for r in (resultado_legal.get("requisitos_habilitantes") or [])
    ]
    financieros = [
        {**r, "_agente": "financiero"}
        for r in (resultado_financiero.get("checklist_detallado") or [])
    ]

    return {
        "pliego":     pdf_path.name,
        "modalidad":  modalidad,
        "sector":     sector,
        "timestamp":  datetime.now().isoformat(),

        # ── Calidad del retrieval (Task 5) ────────────────────────────
        "calidad_retrieval": calidad_retrieval,

        # ── Diagnóstico del pipeline de retrieval ─────────────────────
        "retrieval": {
            "formato_detectado":            formato,
            "texto_chars_total":            len(texto),
            "rag_activado":                 rag_activado,
            "chunks_recuperados_n":         len(chunks_lista),
            "chunks_recuperados":           chunks_lista,       # texto de cada chunk
            "contexto_chars_enviado_claude": len(contexto_pliego),
            "normativa_chars_enviada":      len(contexto_normativo),
        },

        # ── Resultados crudos de cada agente ──────────────────────────
        "agente_legal":      resultado_legal,
        "agente_financiero": resultado_financiero,

        # ── Vista unificada: todos los requisitos con _agente ─────────
        "todos_los_requisitos": habilitantes + financieros,

        "tiempos_segundos": {"legal": t_legal, "financiero": t_fin},
    }


# ── Runner ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluación de extracción de habilitantes SIACO v3.0"
    )
    parser.add_argument("carpeta_pliegos",
                        help="Carpeta que contiene los PDFs a evaluar")
    parser.add_argument("--modalidad", default="infraestructura_obra_publica",
                        help="Modalidad de contratación (default: infraestructura_obra_publica)")
    parser.add_argument("--sector",    default="institucional",
                        help="Sector (default: institucional)")
    parser.add_argument("--test",      action="store_true",
                        help="Corre solo el primer PDF (prueba de smoke)")
    parser.add_argument("--indice",    type=int, default=None,
                        help="Corre solo el PDF en esta posición (0-based)")
    args = parser.parse_args()

    carpeta = Path(args.carpeta_pliegos)
    if not carpeta.exists():
        print(f"Error: la carpeta '{carpeta}' no existe.")
        sys.exit(1)

    # Config opcional por pliego
    config_path = carpeta / "config.json"
    config_por_pliego: dict = {}
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            config_por_pliego = json.load(f)
        print(f"Usando config.json: {len(config_por_pliego)} entradas")

    pdfs = sorted(carpeta.glob("*.pdf"))
    if not pdfs:
        print(f"No se encontraron PDFs en '{carpeta}'.")
        sys.exit(1)

    if args.test:
        pdfs = pdfs[:1]
        print(f"Modo --test: procesando solo '{pdfs[0].name}'")
    elif args.indice is None:
        # Corrida por lote: verificar embeddings antes de procesar
        print("Verificando disponibilidad del servicio de embeddings...")
        emb_status = verificar_embeddings()
        if not emb_status["disponible"]:
            print(
                f"\n{'='*62}\n"
                f"ABORTADO — Servicio de embeddings no disponible.\n"
                f"Error: {emb_status['error']}\n"
                f"\nEl retrieval semántico estaría en modo fallback para todos los\n"
                f"pliegos, produciendo análisis degradados sin advertencia visible.\n"
                f"Solución: verifica que sentence-transformers esté instalado y que\n"
                f"el modelo 'all-MiniLM-L6-v2' sea accesible, luego reintenta.\n"
                f"{'='*62}"
            )
            sys.exit(2)
        print(f"  Embeddings OK — modelo all-MiniLM-L6-v2 operativo")
    elif args.indice is not None:
        if args.indice >= len(pdfs):
            print(f"Error: --indice {args.indice} fuera de rango (hay {len(pdfs)} PDFs).")
            sys.exit(1)
        pdfs = [pdfs[args.indice]]

    salida = _ROOT / "resultados_evaluacion"
    salida.mkdir(exist_ok=True)

    resultados_todos = []
    errores = []

    for i, pdf in enumerate(pdfs):
        print(f"\n{'='*62}")
        print(f"Pliego {i+1}/{len(pdfs)}: {pdf.name}")
        print(f"{'='*62}")

        cfg = config_por_pliego.get(pdf.name, {})
        modalidad = cfg.get("modalidad", args.modalidad)
        sector    = cfg.get("sector",    args.sector)

        t_inicio = time.time()
        try:
            resultado = evaluar_un_pliego(pdf, modalidad, sector)
        except Exception as exc:
            resultado = {
                "pliego": pdf.name,
                "error":  f"{type(exc).__name__}: {exc}",
                "timestamp": datetime.now().isoformat(),
            }
            errores.append(pdf.name)
            print(f"  ERROR: {exc}")

        t_total = round(time.time() - t_inicio, 1)
        resultado["tiempo_total_segundos"] = t_total

        # Guardar resultado individual
        nombre_salida = pdf.stem + "_resultado.json"
        out_path = salida / nombre_salida
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)

        n_req = len(resultado.get("todos_los_requisitos") or [])
        estado = "ERROR" if "error" in resultado else f"{n_req} requisitos"
        print(f"  >> {out_path.name} | {estado} | {t_total}s total")

        resultados_todos.append(resultado)

    # ── Tabla resumen ─────────────────────────────────────────────────────────
    resumen = _construir_resumen(resultados_todos)
    resumen_path = salida / "tabla_resumen.json"
    with open(resumen_path, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*62}")
    print(f"Completado: {len(pdfs) - len(errores)}/{len(pdfs)} pliegos OK")
    if errores:
        print(f"Con error:  {errores}")
    print(f"Resultados: {salida.resolve()}")
    print(f"Resumen:    {resumen_path.name}")
    print(f"{'='*62}")


def _construir_resumen(resultados: list) -> dict:
    """Tabla plana por pliego: qué requisitos extrajo cada agente."""
    filas = []
    for r in resultados:
        if "error" in r:
            filas.append({
                "pliego":               r["pliego"],
                "error":                r["error"],
                "n_requisitos_legal":   0,
                "n_requisitos_financ":  0,
                "requisitos_legal":     [],
                "requisitos_financiero":[],
            })
            continue

        req_legal = [
            {
                "requisito":                  x.get("requisito", ""),
                "exigido":                    x.get("exigido", ""),
                "exigido_literal":            x.get("exigido_literal", x.get("exigido", "")),
                "ubicacion_pliego":           x.get("ubicacion_pliego"),
                "valor_normativo_referencia": x.get("valor_normativo_referencia"),
                "fuente":                     x.get("fuente", "no_encontrado"),
                "norma":                      x.get("norma", ""),
                "documento_soporte":          x.get("documento_soporte", ""),
            }
            for x in (r.get("agente_legal", {}).get("requisitos_habilitantes") or [])
        ]
        req_fin = [
            {
                "requisito":                  x.get("requisito", ""),
                "valor_pliego":               x.get("valor_pliego", ""),
                "exigido_literal":            x.get("exigido_literal", x.get("valor_pliego", "")),
                "valor_normativo_referencia": x.get("valor_normativo_referencia"),
                "fuente":                     x.get("fuente", "no_encontrado"),
            }
            for x in (r.get("agente_financiero", {}).get("checklist_detallado") or [])
        ]

        cal = r.get("calidad_retrieval", {})
        filas.append({
            "pliego":                r["pliego"],
            "modalidad":             r.get("modalidad", ""),
            "sector":                r.get("sector", ""),
            "score_juridico":        r.get("agente_legal", {}).get("score_juridico"),
            "score_financiero":      r.get("agente_financiero", {}).get("score_financiero"),
            # ── Calidad del retrieval (Task 5) ─────────────
            "retrieval_estado":         cal.get("estado", "desconocido"),
            "retrieval_cobertura_pct":  cal.get("cobertura_pct"),
            "retrieval_embeddings_ok":  cal.get("embeddings_disponibles"),
            "retrieval_motivo":         cal.get("motivo_degradacion"),
            # ── Diagnóstico previo ─────────────────────────
            "rag_activado":          r.get("retrieval", {}).get("rag_activado"),
            "chunks_n":              r.get("retrieval", {}).get("chunks_recuperados_n"),
            "texto_chars_total":     r.get("retrieval", {}).get("texto_chars_total"),
            "n_requisitos_legal":    len(req_legal),
            "n_requisitos_financ":   len(req_fin),
            "requisitos_legal":      req_legal,
            "requisitos_financiero": req_fin,
            "tiempo_total_s":        r.get("tiempo_total_segundos"),
        })

    return {
        "generado":    datetime.now().isoformat(),
        "total_pliegos": len(resultados),
        "pliegos":     filas,
    }


if __name__ == "__main__":
    main()
