# -*- coding: utf-8 -*-
"""Router de auditoría de pliegos — SIACO v3.0"""
import re
import json
import threading
import uuid

import anthropic
from fastapi import APIRouter, BackgroundTasks, HTTPException, Header, UploadFile, File, Form

import os
import logging

API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

from analizador import (
    extraer_texto_pliego,
    extraer_texto_completo_pdf,
    extraer_texto_documento,
    chunking_rag_pliego,
    rag_pliego_con_cache,
    analizar_cliente_vs_licitacion_paralelo,
    guardar_analisis_historial,
    SCANNED_PDF_MARKER,
    DOC_NOT_SUPPORTED_MARKER,
)
from routers.utils import parsear_json_claude

logger = logging.getLogger("siaco")

router = APIRouter(tags=["auditoria"])


# ── Almacén de jobs (igual que observaciones.py) ──────────────────────────────

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _guardar_job(job_id: str, data: dict) -> None:
    from pathlib import Path
    with _jobs_lock:
        _jobs[job_id] = data
    try:
        p = Path(f"/tmp/siaco/jobs/audit_{job_id}.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _leer_job(job_id: str) -> dict | None:
    from pathlib import Path
    with _jobs_lock:
        if job_id in _jobs:
            return dict(_jobs[job_id])
    try:
        p = Path(f"/tmp/siaco/jobs/audit_{job_id}.json")
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _cliente_id(sesion: dict) -> str:
    return sesion.get("cliente_id") or sesion.get("id") or ""


def _load_perfil_cliente(cid: str) -> dict:
    from routers.perfil import _load_perfil
    return _load_perfil(cid) or {}


def _perfil_a_formato_analisis(perfil: dict) -> dict:
    """Convierte perfil v3.0 al formato que espera analizar_cliente_vs_licitacion_paralelo."""
    fin = perfil.get("financiero", {})
    exp = perfil.get("experiencia", {})
    rup = perfil.get("rup", {})
    return {
        "nombre": perfil.get("nombre", "Cliente"),
        "sector": perfil.get("sector", ""),
        "rup": {
            "tiene_rup": rup.get("tiene_rup", False),
            "estado_rup": rup.get("estado_rup", "Inactivo"),
            "numero_rup": rup.get("numero_rup", ""),
        },
        "financiero": {
            "indice_liquidez": fin.get("indice_liquidez", 0),
            "indice_endeudamiento": fin.get("indice_endeudamiento", 0),
            "razon_cobertura_interes": fin.get("razon_cobertura_interes", 0),
            "capital_trabajo": fin.get("capital_trabajo", 0),
            "patrimonio_liquido": fin.get("patrimonio_liquido", 0),
            "presupuesto_maximo_contrato": fin.get("presupuesto_maximo_contrato", 0),
            "presupuesto_minimo_contrato": fin.get("presupuesto_minimo_contrato", 0),
        },
        "experiencia": {
            "valor_acumulado": exp.get("valor_acumulado", 0),
            "valor_individual_max": exp.get("valor_individual_max", 0),
            "objeto_similar": exp.get("objeto_similar", ""),
            "codigos_unspsc": exp.get("codigos_unspsc", ""),
            "participacion_minima": exp.get("participacion_minima", 30),
        },
        "codigos_unspsc_permitidos": [
            c.strip() for c in str(exp.get("codigos_unspsc", "")).split(",") if c.strip()
        ],
    }


def _enriquecer_resultado(resultado: dict) -> dict:
    """
    Enriquece el resultado del orquestador con campos adicionales para el frontend:
    - concepto_global (VIABLE/CONDICIONAL/NO VIABLE)
    - score_global
    - tabla_comparativa (fusión de checklist financiero + requisitos jurídicos)
    - citas_normativas (unifica articulos_aplicables + riesgos con citas)
    - checklist_documentos (documentos faltantes con estado)
    """
    score_fin = resultado.get("score", resultado.get("score_financiero", 0))
    score_jur = resultado.get("score_juridico", 0)
    score_global = round((score_fin + score_jur) / 2)

    viable = resultado.get("viable", False)
    concepto_fin = resultado.get("concepto_financiero", "")
    concepto_jur = resultado.get("concepto_juridico", "")

    if viable or ("VIABLE" in concepto_fin and "NO" not in concepto_fin
                  and "VIABLE" in concepto_jur and "NO" not in concepto_jur):
        concepto_global = "VIABLE"
        concepto_color = "green"
    elif score_global >= 40:
        concepto_global = "CONDICIONAL"
        concepto_color = "amber"
    else:
        concepto_global = "NO VIABLE"
        concepto_color = "red"

    # Tabla comparativa unificada
    tabla: list[dict] = []
    for item in resultado.get("checklist_financiero", []):
        if not isinstance(item, dict):
            continue
        tabla.append({
            "tipo": "financiero",
            "requisito": item.get("requisito", ""),
            "exigido": item.get("valor_pliego", ""),
            "cliente_tiene": item.get("valor_empresa", ""),
            "cumple": bool(item.get("cumple", False)),
            # El estado real acompaña al booleano: `cumple=False` no distingue
            # "no cumple" de "falta el dato". Los resultados antiguos del
            # historial no lo traen, de ahí el default.
            "estado": item.get("estado", "cumple" if item.get("cumple") else "no_cumple"),
            # SIN VALOR POR DEFECTO. Aquí decía "Decreto 1082/2015
            # art. 2.2.1.2.1.5.8", un artículo que NO EXISTE: la serie del
            # decreto llega hasta 2.2.1.2.1.5.6. Cada fila financiera salía con
            # esa cita en pantalla y en el PDF. Un valor por defecto en un
            # campo de norma es una cita fabricada por diseño: si no hay norma
            # verificada, el campo va vacío.
            "norma": item.get("norma", ""),
            "subsanable": False,
        })
    for item in resultado.get("requisitos_habilitantes", []):
        if not isinstance(item, dict):
            continue
        tabla.append({
            "tipo": "juridico",
            "requisito": item.get("requisito", ""),
            "exigido": item.get("exigido", ""),
            "cliente_tiene": item.get("cliente_tiene", ""),
            "cumple": bool(item.get("cumple", False)),
            # Igual que arriba: sin norma concreta, vacío. "Ley 80/1993"
            # como relleno sugiere un fundamento que nadie verificó.
            "norma": item.get("norma", ""),
            "subsanable": bool(item.get("subsanable", True)),
        })

    # Citas normativas
    citas = list(resultado.get("articulos_aplicables", []))
    for r in resultado.get("riesgos_juridicos", []):
        if isinstance(r, str) and any(w in r for w in ["Ley", "Decreto", "art.", "CCE"]):
            citas.append(r)

    # Checklist documentos
    docs_faltantes = resultado.get("documentos_faltantes", resultado.get("pdf_documentos", []))
    checklist_docs = [
        {"documento": d, "estado": "falta", "subsanable": True}
        for d in docs_faltantes if d
    ]

    resultado.update({
        "score_global": score_global,
        "concepto_global": concepto_global,
        "concepto_color": concepto_color,
        "tabla_comparativa": tabla,
        "citas_normativas": citas,
        "checklist_documentos": checklist_docs,
    })
    return resultado


# ── Helpers de progreso del pipeline ──────────────────────────────────────────

def _guardar_fase(job_id: str, fase: str, paso: int, total: int, mensaje: str = "") -> None:
    """Actualiza el job con la fase actual. El frontend lee esto en cada poll de 3s."""
    _guardar_job(job_id, {
        "estado":  "procesando",
        "fase":    fase,
        "paso":    paso,
        "total":   total,
        "mensaje": mensaje,
    })


# ── Pipeline path — funciones privadas ────────────────────────────────────────

def _ejecutar_pipeline(job_id: str, sha256: str, raw_pliego: bytes):
    """
    Corre el pipeline completo (parsear → chunkear → extraer) y retorna los artefactos.
    Actualiza el job con la fase actual en cada paso.
    Retorna None si algo falla — el llamador debe verificar y no continuar.
    """
    from pathlib import Path
    try:
        _guardar_fase(job_id, "leyendo_documento", 1, 6, "Extrayendo texto del PDF")
        pdf_path = Path(__file__).parent.parent / "pliegos_temp" / f"{sha256}.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(raw_pliego)

        _guardar_fase(job_id, "reparando_tablas", 2, 6, "Reparando tablas del documento")
        from pipeline.src.parser import parsear_pdf
        resultado_parser = parsear_pdf(pdf_path)
        markdown = resultado_parser["markdown"]

        _guardar_fase(job_id, "analizando_secciones", 3, 6, "Dividiendo el pliego en secciones")
        from pipeline.src.chunker import chunkear
        chunks, _ = chunkear(markdown)

        _guardar_fase(job_id, "extrayendo_requisitos", 4, 6,
                      f"Extrayendo requisitos habilitantes ({len(chunks)} secciones)")
        from pipeline.src.extractor import extraer
        ruta_salida = (
            Path(__file__).parent.parent / "resultados_evaluacion" / f"{sha256}_extraccion.json"
        )
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        extraer(markdown, chunks, ruta_salida=ruta_salida, pliego_sha256=sha256)

        from pipeline.src.artefactos import obtener_artefactos
        return obtener_artefactos(sha256)

    except ImportError as exc:
        logger.error("[AUDITORIA/pipeline] Dependencia faltante: %s", exc)
        _guardar_job(job_id, {
            "estado": "error",
            "mensaje": (
                f"El pipeline requiere dependencias no instaladas: {exc}. "
                "Contacta al administrador para instalar marker-pdf, pdfplumber y langchain."
            ),
        })
        return None
    except Exception as exc:
        logger.error("[AUDITORIA/pipeline] Error ejecutando pipeline: %s", exc, exc_info=True)
        _guardar_job(job_id, {
            "estado": "error",
            "mensaje": f"Error al procesar el pliego: {str(exc)[:300]}",
        })
        return None


def _analizar_con_pipeline(job_id: str, artefactos, cid: str, licitacion: dict) -> dict | None:
    """
    Evalúa perfil × requisitos del pipeline y llama a los dos agentes de redacción en paralelo.
    Retorna resultado enriquecido, o None si algo falla.
    """
    from concurrent.futures import ThreadPoolExecutor

    try:
        _guardar_fase(job_id, "evaluando_perfil", 5, 6, "Evaluando perfil de la empresa")
        from pipeline.src.evaluator import evaluar_empresa, cargar_perfil_por_cid
        from pipeline.src.extractor import Requisito as _Requisito
        perfil_obj = cargar_perfil_por_cid(cid)
        if perfil_obj is None:
            raise ValueError(f"Perfil del cliente '{cid}' no encontrado en clientes/")

        # artefactos.requisitos llega YA consolidado desde artefactos.py.
        reqs = [_Requisito.model_validate(r) for r in artefactos.requisitos]

        # ── POLÍTICA: la habilitación se decide SOLO con requisitos habilitantes.
        # Los procedimentales y de puntaje responden otra pregunta ("¿cumplió el
        # trámite?", "¿qué puntaje saca?"), no "¿puede ofertar esta empresa?".
        habilitantes_obj = [r for r in reqs if r.criticidad == "habilitante"]

        # ── SALVAGUARDA 1: cero habilitantes ⇒ la clasificación no corrió.
        # Un análisis sobre cero habilitantes es peor que ninguno: reporta
        # "viable" sin haber verificado nada. Abortar en vez de mentir.
        if reqs and not habilitantes_obj:
            raise ValueError(
                "Los requisitos no están clasificados; el análisis no puede "
                "determinar habilitación. Verifica que la consolidación "
                "(clasificador.py) se haya aplicado en artefactos.py."
            )

        # ── SALVAGUARDA 2: exceso de indeterminados ⇒ clasificación degradada.
        n_indet = sum(1 for r in reqs if r.criticidad == "indeterminado")
        pct_indet = (n_indet / len(reqs)) if reqs else 0.0
        aviso_clasificacion = None
        if pct_indet > 0.20:
            aviso_clasificacion = (
                f"Clasificación degradada: {n_indet} de {len(reqs)} requisitos "
                f"({pct_indet:.0%}) quedaron sin clasificar. El análisis de "
                f"habilitación puede estar incompleto."
            )
            logger.warning("[AUDITORIA/pipeline] %s", aviso_clasificacion)

        evaluacion = evaluar_empresa(perfil_obj, habilitantes_obj)
    except Exception as exc:
        logger.error("[AUDITORIA/pipeline] Error en evaluar_empresa: %s", exc)
        _guardar_job(job_id, {
            "estado": "error",
            "mensaje": f"Error al evaluar el perfil: {str(exc)[:300]}",
        })
        return None

    try:
        _guardar_fase(job_id, "redactando_concepto", 6, 6, "Redactando concepto de viabilidad")
        from analizador_pipeline import agente_financiero_pipeline, agente_juridico_pipeline

        perfil_dict = {"nombre": perfil_obj.nombre, "es_mipyme": perfil_obj.es_mipyme}
        licitacion_dict = {
            "nombre_proceso": licitacion.get("nombre_del_procedimiento", ""),
            "entidad":        licitacion.get("entidad", ""),
            "valor":          licitacion.get("precio_base", ""),
        }
        # Mismo conjunto que recibió el evaluador — una sola verdad sobre qué es habilitante.
        habilitantes = [r.model_dump() for r in habilitantes_obj]

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_fin = executor.submit(
                agente_financiero_pipeline, evaluacion, perfil_dict, licitacion_dict
            )
            fut_jur = executor.submit(
                agente_juridico_pipeline, habilitantes, evaluacion, perfil_dict, licitacion_dict
            )
            resultado_financiero = fut_fin.result()
            resultado_juridico   = fut_jur.result()

    except Exception as exc:
        logger.error("[AUDITORIA/pipeline] Error en agentes de redacción: %s", exc)
        _guardar_job(job_id, {
            "estado": "error",
            "mensaje": f"Error al redactar concepto: {str(exc)[:200]}",
        })
        return None

    resultado = _construir_resultado(
        evaluacion, resultado_financiero, resultado_juridico, artefactos, licitacion, perfil_obj
    )
    if aviso_clasificacion:
        resultado["aviso_clasificacion"] = aviso_clasificacion
    return resultado


# Documento que aporta cada indicador financiero, para que "falta el dato" sea
# accionable. Los indicadores de capacidad financiera y organizacional se
# acreditan con el RUP (Ley 1150/2007 art. 6); los de capacidad residual con
# los estados financieros y el Formato 5 del pliego.
_DOC_POR_INDICADOR: list[tuple[str, str]] = [
    ("liquidez",        "RUP — capacidad financiera (o estados financieros del último año)"),
    ("endeudamiento",   "RUP — capacidad financiera (o estados financieros del último año)"),
    ("cobertura",       "RUP — capacidad financiera (utilidad operacional / gastos de intereses)"),
    ("capital de trab", "Estados financieros: activo corriente y pasivo corriente"),
    ("patrimonio",      "Estados financieros: patrimonio neto"),
    ("rentabilidad",    "RUP — capacidad organizacional"),
    ("organizacion",    "RUP — capacidad organizacional (ingresos operacionales)"),
    ("organizacional",  "RUP — capacidad organizacional (ingresos operacionales)"),
    ("ingresos",        "Estado de resultados: ingresos operacionales"),
    ("residual",        "Formato 5 del pliego + estados financieros"),
    ("estados financi", "Estados financieros firmados por contador y revisor fiscal"),
]


def _documento_que_aporta(requisito: str) -> str:
    """Documento con el que se acredita un indicador financiero. '' si no se sabe."""
    r = (requisito or "").lower()
    for aguja, doc in _DOC_POR_INDICADOR:
        if aguja in r:
            return doc
    return ""


def _construir_checklist_financiero(evaluacion: dict) -> list[dict]:
    """
    Checklist financiero con los CINCO estados del evaluador.

    Antes: `"cumple": it.get("estado") == "cumple"`. Ese booleano convertía
    `dato_faltante` en "no cumple" — 8 de los 14 indicadores de Paicol. Le
    decía al cliente "no cumples cobertura de intereses" cuando la verdad era
    "no tenemos tu dato", que es la afirmación falsa que el sistema no puede
    permitirse: el operador firma ese informe.

    También corrige `valor_pliego`: `"umbral" in it` es cierto aunque el valor
    sea None, y producía el string roto ">= None pesos".

    Se conserva `cumple` (bool) para los consumidores heredados —
    `_enriquecer_resultado` y el exportador de PDF— con la semántica estricta:
    True sólo cuando el estado es "cumple".
    """
    salida: list[dict] = []
    for it in evaluacion.get("items", []):
        if it.get("categoria") != "financiero":
            continue

        estado = it.get("estado", "dato_faltante")
        umbral = it.get("umbral")
        operador = it.get("operador")
        unidad = (it.get("unidad") or "").strip()
        valor_empresa = it.get("valor_empresa")

        # valor_pliego: sólo si hay umbral Y operador reales
        if umbral is not None and operador:
            valor_pliego = f"{operador} {umbral}" + (f" {unidad}" if unidad else "")
        elif estado == "revisar_manual":
            valor_pliego = "varios umbrales — ver alternativas"
        else:
            # El pliego lo exige pero sin valor numérico extraíble
            valor_pliego = "definido en el pliego"

        fila: dict = {
            "requisito":     it.get("requisito", ""),
            "estado":        estado,
            "valor_pliego":  valor_pliego,
            "valor_empresa": "" if valor_empresa is None else str(valor_empresa),
            "unidad":        unidad,
            "fuente_numeral": it.get("fuente_numeral", ""),
            # Heredado: True SÓLO si cumple de verdad
            "cumple":        estado == "cumple",
        }

        if estado == "no_cumple" and umbral is not None:
            try:
                fila["diferencia"] = round(float(valor_empresa) - float(umbral), 4)
            except (TypeError, ValueError):
                pass
        elif estado == "dato_faltante":
            fila["documento_requerido"] = _documento_que_aporta(fila["requisito"])
        elif estado == "revisar_manual":
            fila["umbrales_alternativos"] = it.get("umbrales_alternativos", [])
            fila["motivo"] = it.get("motivo", "")

        salida.append(fila)
    return salida


def _construir_resultado(
    evaluacion: dict,
    resultado_financiero: dict,
    resultado_juridico: dict,
    artefactos,
    licitacion: dict,
    perfil_obj,
) -> dict:
    """
    Adapta outputs del pipeline + agentes al formato que espera el frontend y reportes.py.
    Conserva campos heredados (score, checklist_financiero, requisitos_habilitantes…) junto
    a campos nuevos del pipeline (cobertura_pliego, estado_verificacion, pagina_origen…).
    """
    score_fin  = round(evaluacion.get("score_global", 0))
    score_jur  = round(evaluacion.get("desglose", {}).get("juridico", {}).get("score") or 0)
    veredicto  = evaluacion.get("veredicto", "dato_insuficiente")
    viable     = veredicto == "viable"

    checklist_financiero = _construir_checklist_financiero(evaluacion)

    resultado: dict = {
        # ── Campos heredados (frontend + reportes.py) ──────────────────────────
        "viable":            viable,
        "score":             score_fin,
        "score_juridico":    score_jur,
        "accion":            "PRESENTAR" if viable else "REVISAR",
        "motivo":            resultado_juridico.get("concepto_juridico", veredicto.upper()),

        "concepto_financiero":  resultado_financiero.get("concepto_financiero", "CONDICIONAL"),
        "razones_financiero":   resultado_financiero.get("razones_financiero", []),
        "articulos_aplicables": resultado_financiero.get("razones_financiero", []),
        "recomendaciones":      resultado_financiero.get("recomendaciones", []),
        "indices_evaluados":    resultado_financiero.get("indices_evaluados", {}),
        "checklist_financiero": checklist_financiero,

        "concepto_juridico":       resultado_juridico.get("concepto_juridico", "CONDICIONAL"),
        "viable_juridico":         resultado_juridico.get("viable_juridico"),
        "requisitos_habilitantes": resultado_juridico.get("requisitos_habilitantes", []),
        "riesgos_juridicos":       resultado_juridico.get("riesgos_juridicos", []),
        "documentos_faltantes":    resultado_juridico.get("documentos_faltantes", []),
        "documentos_checklist":    resultado_juridico.get("documentos_checklist", []),

        "pdf_checklist":  checklist_financiero,
        "pdf_argumentos": resultado_juridico.get("concepto_juridico", ""),
        "pdf_documentos": resultado_juridico.get("documentos_faltantes", []),
        "detalles_licitacion": {
            "objeto":  licitacion.get("nombre_del_procedimiento", ""),
            "entidad": licitacion.get("entidad", ""),
            "valor":   licitacion.get("precio_base", ""),
            "cliente": perfil_obj.nombre,
        },

        # ── Campos nuevos del pipeline (se conservan junto a los heredados) ───
        "fuente_analisis":     "pipeline",
        "cobertura_pliego":    evaluacion.get("cobertura_global", 0.0),
        "veredicto_evaluador": veredicto,
        "desglose_evaluador":  evaluacion.get("desglose", {}),
        "total_evaluados":     evaluacion.get("total_evaluados", 0),
        "total_con_datos":     evaluacion.get("total_con_datos", 0),
        "chunks_procesados":   len(artefactos.chunks),
        "timestamp_pipeline":  artefactos.metadatos_corrida.get("timestamp_utc", ""),
        # artefactos.requisitos son dicts (Requisito.model_dump()) ya consolidados
        "requisitos_con_cita": [
            {
                "nombre":                      req.get("nombre", ""),
                "categoria":                   req.get("categoria", ""),
                "fuente_numeral":              req.get("fuente_numeral", ""),
                "exigido_literal":             req.get("exigido_literal", ""),
                "criticidad":                  req.get("criticidad", "indeterminado"),
                "es_causal_rechazo_explicita": req.get("es_causal_rechazo_explicita", False),
                "pagina_origen":               req.get("pagina_origen"),
                "estado_verificacion":         req.get("estado_verificacion", "no_verificada"),
            }
            for req in artefactos.requisitos
        ],
        # Trazabilidad: de cuántos requisitos crudos salió este conjunto
        "consolidacion": getattr(artefactos, "consolidacion", {}),
    }

    return _enriquecer_resultado(resultado)


# ── Background: análisis IA (corre fuera del timeout de Railway) ──────────────

def _analizar_pliego_bg(
    job_id: str,
    licitacion: dict,
    cid: str,
    pliego_sha256: str,
    raw_pliego: bytes,
    modalidad: str,
    sector: str,
) -> None:
    """
    Análisis basado en el pipeline (100% del pliego).
    Se ejecuta en el thread pool de FastAPI BackgroundTasks.

    DESCONECTADO — flujo anterior (analizar_cliente_vs_licitacion_paralelo):
      operaba sobre ~6% del pliego (RAG de 5.000 chars sobre texto[:15.000]).
      No reactivar sin revisar por qué se desconectó: análisis era sobre texto truncado
      y producía scores inventados por el LLM.
    """
    try:
        from pipeline.src.artefactos import obtener_artefactos
        artefactos = obtener_artefactos(pliego_sha256) if pliego_sha256 else None

        if artefactos:
            logger.info("[AUDITORIA] Caché hit — pliego %s ya procesado (%d chunks)",
                        pliego_sha256[:12], len(artefactos.chunks))
            _guardar_fase(job_id, "evaluando_perfil", 5, 6, "Usando análisis cacheado del pliego")
        else:
            logger.info("[AUDITORIA] Ejecutando pipeline sobre pliego %s...", pliego_sha256[:12])
            artefactos = _ejecutar_pipeline(job_id, pliego_sha256, raw_pliego)

        if artefactos is None:
            return  # _ejecutar_pipeline ya guardó el error en el job

        resultado = _analizar_con_pipeline(job_id, artefactos, cid, licitacion)
        if resultado is None:
            return  # _analizar_con_pipeline ya guardó el error

        try:
            guardar_analisis_historial(cid, resultado, licitacion["id_del_proceso"])
        except Exception:
            pass

        # [G1] El resultado completo al almacén, no sólo los scores. El
        # historial de `analizador.py` guarda dos números; reabrir el análisis
        # exigía recalcularlo. Aquí queda entero y sobrevive al reinicio.
        try:
            from pipeline.src import registro
            registro.registrar_evaluacion(
                pliego_sha256, cid,
                veredicto=resultado.get("veredicto_evaluador", ""),
                resultado=resultado,
                numero_proceso=licitacion.get("id_del_proceso", ""),
                entidad=licitacion.get("entidad", ""),
            )
            registro.registrar_pliego(
                pliego_sha256,
                archivo=artefactos.archivo,
                entidad=licitacion.get("entidad", ""),
                numero_proceso=licitacion.get("id_del_proceso", ""),
                modalidad=modalidad, sector=sector, estado="evaluado",
            )
        except Exception as exc:
            logger.error("[AUDITORIA] No se pudo registrar la evaluación: %s", exc)

        _guardar_job(job_id, {"estado": "completo", "datos": resultado})
        logger.info("[AUDITORIA] Job %s completado para cliente %s (pipeline)", job_id, cid)

    except anthropic.APITimeoutError:
        _guardar_job(job_id, {
            "estado": "error",
            "mensaje": (
                "El análisis tardó demasiado. "
                "Intenta de nuevo — si el error persiste, contacta soporte."
            ),
        })
    except Exception as exc:
        logger.error("[AUDITORIA] Error en job %s: %s", job_id, exc)
        _guardar_job(job_id, {"estado": "error", "mensaje": str(exc)[:300]})


# ── POST /api/auditoria/extraer ───────────────────
@router.post("/auditoria/extraer")
async def extraer_pliego(
    pdf: UploadFile = File(...),
    authorization: str = Header(None),
):
    """Extrae texto y metadatos de un documento de pliego (PDF, Word, Excel o imagen)."""
    from routers.auth import require_auth
    require_auth(authorization)

    raw_bytes = await pdf.read()
    texto, formato = extraer_texto_documento(raw_bytes, pdf.filename or "")

    if formato == "doc_legacy":
        raise HTTPException(
            status_code=422,
            detail=(
                "El formato .doc (Word 97-2003) no está soportado directamente. "
                "Abre el archivo en Word y guárdalo como .docx, luego vuelve a intentarlo."
            ),
        )
    if texto == SCANNED_PDF_MARKER:
        raise HTTPException(
            status_code=422,
            detail=(
                "El documento es una imagen escaneada y OCR no está disponible en este momento. "
                "Por favor intente con un archivo con texto seleccionable, "
                "o contáctenos para asistencia."
            ),
        )
    if not texto or not texto.strip():
        raise HTTPException(
            status_code=422,
            detail=f"No se pudo extraer texto del archivo ({formato}). Verifica que el documento tenga contenido legible.",
        )

    _FORMATO_LABELS = {
        "pdf": "PDF", "word": "Word (.docx)",
        "imagen": "Imagen (OCR)", "excel": "Excel",
    }
    formato_label = _FORMATO_LABELS.get(formato, formato)

    extraidos: dict = {}
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""), timeout=20.0)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            extra_body={"temperature": 0.0},
            messages=[{"role": "user", "content": (
                "Extrae del texto de pliego de licitacion publica colombiana:\n"
                "1) entidad contratante  2) objeto del contrato (max 200 chars)  "
                "3) valor base en pesos colombianos (numero entero, solo cifra)  "
                "4) modalidad de seleccion  5) sector\n\n"
                f"Texto del pliego:\n{texto[:6000]}\n\n"
                'Responde SOLO con JSON: {"entidad":"nombre","objeto":"desc","valor":numero_o_null,'
                '"modalidad":"infraestructura_obra_publica|suministro|prestacion_servicios|consultoria",'
                '"sector":"salud|educacion|infraestructura|transporte|ambiente|institucional"}'
            )}],
        )
        raw_resp = resp.content[0].text
        extraidos = parsear_json_claude(raw_resp) or {}
        if not extraidos:
            logger.warning("[AUDITORIA/extraer] parsear_json_claude retornó None. Respuesta cruda:\n%s", raw_resp[:800])
    except anthropic.APITimeoutError:
        logger.warning("[AUDITORIA/extraer] Timeout en Claude API al extraer campos del pliego")
    except Exception as exc:
        logger.warning("[AUDITORIA/extraer] Error en Claude API: %s", exc)

    return {
        "texto_chars": len(texto),
        "paginas_extraidas": texto.count("--- EXTRACTO PÁGINA"),
        "formato_detectado": formato_label,
        "extraccion_ok": bool(extraidos),
        "entidad":   extraidos.get("entidad", ""),
        "objeto":    extraidos.get("objeto", ""),
        "valor":     extraidos.get("valor"),
        "modalidad": extraidos.get("modalidad", "infraestructura_obra_publica"),
        "sector":    extraidos.get("sector", "salud"),
    }


# ── POST /api/auditoria/analizar ──────────────────
@router.post("/auditoria/analizar")
async def analizar_pliego(
    background_tasks: BackgroundTasks,
    cliente_id:     str        = Form(...),
    modalidad:      str        = Form("infraestructura_obra_publica"),
    sector:         str        = Form("salud"),
    entidad:        str        = Form(""),
    objeto:         str        = Form(""),
    valor:          str        = Form("450000000"),
    pliego:         UploadFile = File(None),
    estudio_previo: UploadFile = File(None),
    anexo_tecnico:  UploadFile = File(None),
    adenda:         UploadFile = File(None),
    pdf:            UploadFile = File(None),   # backward compat
    authorization:  str        = Header(None),
):
    """
    Lanza análisis de pliego en background y responde inmediatamente con job_id.
    El frontend hace polling a GET /api/auditoria/estado/{job_id} cada 3s.
    Esto evita el 502 de Railway causado por los ~60-120s que toman los agentes IA.
    """
    from routers.auth import require_auth
    sesion = require_auth(authorization)

    cid = cliente_id or _cliente_id(sesion)
    perfil_raw = _load_perfil_cliente(cid)

    if not perfil_raw:
        raise HTTPException(
            status_code=404,
            detail="Perfil del cliente no encontrado. Completa el perfil antes de auditar.",
        )

    perfil_analisis = _perfil_a_formato_analisis(perfil_raw)

    try:
        valor_num = int(str(valor).replace(",", "").replace(".", "").strip() or 0)
    except Exception:
        valor_num = 450_000_000

    licitacion = {
        "nombre_del_procedimiento": objeto or "Licitacion ingresada manualmente",
        "entidad": entidad or "Entidad Estatal",
        "precio_base": str(valor_num),
        "fase": "Publicado",
        "id_del_proceso": f"manual-{cid}-{int(__import__('time').time())}",
        "modalidad_seleccion": modalidad,
    }

    # ── Extraer texto del pliego (obligatorio, síncrono) ──
    archivo_pliego = pliego or pdf
    texto_pliego = ""
    raw_pliego = b""
    if archivo_pliego and archivo_pliego.filename:
        raw_pliego = await archivo_pliego.read()
        if raw_pliego:
            texto_pliego, fmt_pliego = extraer_texto_documento(raw_pliego, archivo_pliego.filename)
            if fmt_pliego == "doc_legacy":
                raise HTTPException(
                    status_code=422,
                    detail="El formato .doc (Word 97-2003) no está soportado. Guarda el archivo como .docx e inténtalo de nuevo.",
                )

    if texto_pliego == SCANNED_PDF_MARKER:
        raise HTTPException(
            status_code=422,
            detail=(
                "El documento es una imagen escaneada y OCR no está disponible en este momento. "
                "Por favor intente con un archivo con texto seleccionable, "
                "o contáctenos para asistencia."
            ),
        )

    # Guardar pliego original en Supabase (best-effort)
    if raw_pliego and archivo_pliego and archivo_pliego.filename:
        try:
            from supabase_client import sb_upload
            fname_safe = re.sub(r"[^\w.\-]", "_", archivo_pliego.filename)[:120]
            ext        = fname_safe.rsplit(".", 1)[-1].lower() if "." in fname_safe else ""
            ctype      = "application/pdf" if ext == "pdf" else "application/octet-stream"
            sb_upload(f"clientes/{cid}/pliego/{fname_safe}", raw_pliego, ctype)
        except Exception as exc:
            logger.warning("[AUDITORIA] No se pudo guardar pliego en Supabase: %s", exc)

    if not texto_pliego or len(texto_pliego.strip()) < 200:
        raise HTTPException(
            status_code=422,
            detail=(
                "No se pudo extraer texto suficiente del pliego. "
                "Verifica que el archivo no sea solo imágenes sin OCR "
                "y que hayas subido el documento correctamente."
            ),
        )

    # ── Documentos adicionales (opcionales) ──────────
    textos_extra: list[str] = []
    docs_adicionales = [
        ("ESTUDIOS PREVIOS", estudio_previo),
        ("ANEXO TECNICO",    anexo_tecnico),
        ("ADENDA",           adenda),
    ]
    for nombre_doc, archivo in docs_adicionales:
        if archivo and archivo.filename:
            raw_doc = await archivo.read()
            if raw_doc:
                t, _ = extraer_texto_documento(raw_doc, archivo.filename)
                if t and t not in (SCANNED_PDF_MARKER, DOC_NOT_SUPPORTED_MARKER):
                    textos_extra.append(f"=== {nombre_doc} ===\n{t[:4000]}")

    # ── Guardar texto en sesión (para chat y observaciones) ─
    import hashlib
    pliego_sha256 = hashlib.sha256(raw_pliego).hexdigest() if raw_pliego else ""
    from contexto_sesion import guardar_contexto_sesion
    guardar_contexto_sesion(
        cid,
        texto_pliego,
        "\n\n".join(textos_extra),
        parametros_proceso={
            "entidad":   entidad,
            "objeto":    objeto,
            "valor":     valor_num,
            "modalidad": modalidad,
            "sector":    sector,
        },
        pliego_sha256=pliego_sha256,
    )

    print(f"\n{'='*60}")
    print(f"[AUDITORIA] Pliego: {len(texto_pliego)} chars | SHA256: {pliego_sha256[:12]}...")
    print(f"[AUDITORIA] Preview:\n{texto_pliego[:200]}")
    print(f"{'='*60}\n")

    # ── Lanzar análisis IA en background (pipeline) ──
    job_id = uuid.uuid4().hex[:16]
    _guardar_job(job_id, {
        "estado":  "procesando",
        "fase":    "iniciando",
        "paso":    0,
        "total":   6,
        "mensaje": "Iniciando análisis del pliego...",
    })

    background_tasks.add_task(
        _analizar_pliego_bg,
        job_id,
        licitacion,
        cid,
        pliego_sha256,
        raw_pliego,
        modalidad,
        sector,
    )

    logger.info("[AUDITORIA] Job %s lanzado para cliente %s (pipeline)", job_id, cid)
    return {"job_id": job_id, "estado": "procesando"}


# ── GET /api/auditoria/estado/{job_id} ────────────
@router.get("/auditoria/estado/{job_id}")
def estado_analisis(job_id: str, authorization: str = Header(None)):
    """Polling endpoint — devuelve {estado: 'procesando'} o {estado: 'completo', datos: {...}}."""
    from routers.auth import require_auth
    require_auth(authorization)

    job = _leer_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado o expirado")
    return job
