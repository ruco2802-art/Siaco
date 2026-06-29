# -*- coding: utf-8 -*-
"""Router de búsqueda SECOP II — SIACO v3.0"""
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel

import os
import anthropic

API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
logger = logging.getLogger("siaco")

router = APIRouter(tags=["busqueda"])

FASES_EXCLUIDAS = [
    "adjudicado", "desierto", "liquidado", "terminado", "celebrado",
    "suspendido", "cancelado",
]

SECOP_URL   = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
SECOP_URL_2 = "https://www.datos.gov.co/resource/rpmr-utcd.json"


def _parse_dt(valor: str) -> Optional[datetime]:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "").split("+")[0])
    except Exception:
        return None


def _fmt_descartado(lic: dict, razon: str) -> dict:
    """Wraps a SECOP contract with a discard reason, preserving full data for 'Analizar de todas formas'."""
    try:
        valor = float(lic.get("precio_base", 0) or 0)
    except Exception:
        valor = 0
    return {
        **lic,
        "razon_descarte": razon,
        "_razon":         razon,       # backward compat
        "_score":         0,
        "_score_hibrido": float(lic.get("score_hibrido", 0)),
        "precio_base":    valor,       # ensure numeric
    }


def _fetch_secop(url: str, params: dict) -> list[dict]:
    """Fetch con retry desde un endpoint SECOP II. Retorna lista vacía en fallo silencioso."""
    for intento in range(3):
        try:
            resp   = requests.get(url, params=params, timeout=30)
            parsed = resp.json()
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, dict)]
            return []
        except Exception:
            if intento < 2:
                time.sleep(3)
    return []


def _fusionar(lista1: list[dict], lista2: list[dict]) -> list[dict]:
    """Une dos listas de SECOP deduplicando por id_del_proceso."""
    visto: set[str] = set()
    resultado: list[dict] = []
    for item in lista1 + lista2:
        pid = item.get("id_del_proceso") or item.get("referencia_del_proceso", "")
        if pid and pid in visto:
            continue
        if pid:
            visto.add(pid)
        resultado.append(item)
    return resultado


def _keywords_where(keywords: str) -> str:
    """
    SoQL case-insensitive por palabras clave usando upper() LIKE.
    "mejoramiento vivienda" → cada palabra con AND implícito.
    """
    palabras = [w.strip() for w in keywords.split() if w.strip()]
    if not palabras:
        return ""
    return " AND ".join(
        f"upper(nombre_del_procedimiento) LIKE upper('%{_safe(p)}%')"
        for p in palabras
    )


# ── GET /api/contratos ────────────────────────────
@router.get("/contratos")
def buscar_contratos(
    fecha_desde:    str   = Query("2026-01-01"),
    valor_minimo:   float = Query(5_000_000),
    max_resultados: int   = Query(50),
    departamento:   str   = Query(""),
    authorization:  str   = Header(None),
):
    """Obtiene contratos de SECOP II, aplica filtros duros y scoring híbrido con perfil del cliente."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)

    # ── SECOP II fetch — ambas fuentes ───────────────────────────────────
    where = f"fecha_de_publicacion > '{fecha_desde}T00:00:00'"
    if departamento:
        where += f" AND departamento_entidad = '{_safe(departamento)}'"

    params_base = {
        "$where": where,
        "$limit": str(min(max_resultados, 200)),
        "$order": "fecha_de_publicacion DESC",
    }

    fuente1 = _fetch_secop(SECOP_URL,   params_base)
    fuente2 = _fetch_secop(SECOP_URL_2, params_base)

    if not fuente1 and not fuente2:
        raise HTTPException(
            status_code=503,
            detail="No se pudo conectar con SECOP II. Intente en unos segundos.",
        )

    lics_raw = _fusionar(fuente1, fuente2)
    logger.info("[CONTRATOS] fuente1=%d fuente2=%d fusionados=%d",
                len(fuente1), len(fuente2), len(lics_raw))

    # ── Hard filters ──────────────────────────────────────────────────────
    now = datetime.now()
    seen: set[str] = set()
    contratos_pre: list[dict] = []
    descartados: list[dict] = []

    for lic in lics_raw:
        cod = lic.get("id_del_proceso") or lic.get("referencia_del_proceso", "")
        if not cod or cod in seen:
            continue
        seen.add(cod)

        fase = str(lic.get("fase", "") or lic.get("estado_del_procedimiento", "")).lower().strip()
        if any(exc in fase for exc in FASES_EXCLUIDAS):
            descartados.append(_fmt_descartado(lic, f"Fase cerrada: {fase or 'sin fase'}"))
            continue

        dt_manif = _parse_dt(lic.get("fecha_limite_manifestacion_interes", ""))
        if dt_manif and dt_manif < now + timedelta(hours=24):
            horas = max(0, int((dt_manif - now).total_seconds() / 3600))
            descartados.append(_fmt_descartado(lic, f"Manifestacion de interes cierra en {horas}h"))
            continue

        dt_oferta = (_parse_dt(lic.get("fecha_limite_recepcion_ofertas", ""))
                     or _parse_dt(lic.get("fecha_de_recepcion_de", "")))
        if dt_oferta and dt_oferta < now + timedelta(hours=48):
            horas = max(0, int((dt_oferta - now).total_seconds() / 3600))
            descartados.append(_fmt_descartado(lic, f"Cierre de ofertas en {horas}h"))
            continue

        try:
            valor = float(lic.get("precio_base", 0) or 0)
        except Exception:
            valor = 0
        if valor < valor_minimo:
            descartados.append(_fmt_descartado(lic, f"Valor COP {valor:,.0f} menor al minimo"))
            continue

        dias_cierre = None
        if dt_oferta:
            dias_cierre = max(0, int((dt_oferta - now).total_seconds() / 86400))

        contratos_pre.append({
            **lic,
            "_score": 0,
            "_score_hibrido": 0.0,
            "_motivo": "",
            "_urgente": dias_cierre is not None and dias_cierre <= 3,
            "_dias_cierre": dias_cierre,
        })

    # ── Hybrid scoring inline (uses client profile from session) ──────────
    modo_busqueda = "keywords_only"
    contratos_relevantes = contratos_pre

    try:
        from routers.perfil import _load_perfil, _cliente_id_from_session
        from analizador import busqueda_hibrida_triple

        cid = _cliente_id_from_session(sesion)
        perfil = _load_perfil(cid) if cid else None

        if perfil:
            exp = perfil.get("experiencia", {}) or {}
            codigos_unspsc = exp.get("codigos_unspsc", "").strip()
            objeto_similar = exp.get("objeto_similar", "").strip()
            sector = perfil.get("sector", "").strip()
            query = objeto_similar or sector

            if query or codigos_unspsc:
                perfil_analisis = {
                    "codigos_unspsc": codigos_unspsc,
                    "objeto_similar": objeto_similar,
                }
                relevantes = busqueda_hibrida_triple(query, perfil_analisis, contratos_pre)
                ids_rel = {
                    r.get("id_del_proceso") or r.get("referencia_del_proceso", "")
                    for r in relevantes
                }
                for c in contratos_pre:
                    ckey = c.get("id_del_proceso") or c.get("referencia_del_proceso", "")
                    if ckey not in ids_rel:
                        descartados.append(_fmt_descartado(c, "Baja relevancia para el perfil"))

                contratos_relevantes = []
                for r in relevantes:
                    sh = r.get("score_hibrido", 0)
                    contratos_relevantes.append({
                        **r,
                        "_score": int(round(sh * 100)),
                        "_motivo": (
                            f"UNSPSC:{int(r.get('score_unspsc', 0)*100)} "
                            f"KW:{int(r.get('score_keywords', 0)*100)} "
                            f"Sem:{int(r.get('score_semantico', 0)*100)}"
                        ),
                    })
                modo_busqueda = "hibrido"
    except Exception:
        pass  # fallback: all contratos_pre are relevant, keywords_only mode

    return {
        "contratos_relevantes":  contratos_relevantes,
        "contratos_descartados": descartados,
        "total_analizados":      len(lics_raw),
        "total_relevantes":      len(contratos_relevantes),
        "total_descartados":     len(descartados),
        "modo_busqueda":         modo_busqueda,
        # backward compat keys for any cached frontend
        "contratos":             contratos_relevantes,
        "descartados":           [d for d in descartados if d.get("razon_descarte","").startswith("Fase") or d.get("razon_descarte","").startswith("Manifestacion") or d.get("razon_descarte","").startswith("Cierre") or d.get("razon_descarte","").startswith("Valor")][:5],
        "total":                 len(contratos_relevantes),
        "total_raw":             len(lics_raw),
    }


# ── POST /api/contratos/filtrar ───────────────────
class FiltrarBody(BaseModel):
    contratos: list
    query: Optional[str] = ""


@router.post("/contratos/filtrar")
def filtrar_hibrido(body: FiltrarBody, authorization: str = Header(None)):
    """Aplica búsqueda híbrida triple (UNSPSC + keywords + semántica) usando perfil del cliente."""
    from routers.auth import require_auth
    from routers.perfil import _load_perfil, _cliente_id_from_session
    from analizador import busqueda_hibrida_triple

    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)
    perfil = _load_perfil(cid)

    if not perfil:
        return {"resultados": body.contratos, "filtrados": len(body.contratos), "modo": "sin_perfil"}

    query = body.query or perfil.get("experiencia", {}).get("objeto_similar", "") or perfil.get("sector", "")

    # Mapear perfil al formato que espera busqueda_hibrida_triple
    perfil_analisis = {
        "codigos_unspsc": perfil.get("experiencia", {}).get("codigos_unspsc", ""),
        "objeto_similar": perfil.get("experiencia", {}).get("objeto_similar", ""),
    }

    try:
        resultados = busqueda_hibrida_triple(query, perfil_analisis, body.contratos)
    except Exception:
        resultados = body.contratos

    return {
        "resultados": resultados,
        "filtrados": len(resultados),
        "total_entrada": len(body.contratos),
        "modo": "hibrido_triple",
    }


# ── POST /api/contratos/analizar ──────────────────
class AnalizarBody(BaseModel):
    contratos: list
    cliente_id: Optional[str] = None


@router.post("/contratos/analizar")
def analizar_contratos(body: AnalizarBody, authorization: str = Header(None)):
    """Scoring de relevancia con Claude para hasta 50 contratos."""
    from routers.auth import require_auth
    from routers.perfil import _load_perfil, _cliente_id_from_session
    from routers.utils import parsear_json_claude

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    logger.info("[ANALIZAR] API_KEY presente: %s | primeros 10: %r", bool(api_key), api_key[:10])

    sesion = require_auth(authorization)
    cid = body.cliente_id or _cliente_id_from_session(sesion)
    perfil = _load_perfil(cid) if cid else {}

    sector = perfil.get("sector", "obras civiles y servicios")
    objeto_cliente = perfil.get("experiencia", {}).get("objeto_similar", sector)

    logger.info("[ANALIZAR] Perfil cliente: sector=%s objeto=%s", sector, objeto_cliente[:80])

    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY no configurada en el servidor")

    client = anthropic.Anthropic(api_key=api_key, timeout=30.0)
    resultados: list[dict] = []

    for idx, lic in enumerate(body.contratos[:50]):
        if not isinstance(lic, dict):
            continue
        nombre  = lic.get("nombre_del_procedimiento", "N/A")
        desc    = str(lic.get("descripci_n_del_procedimiento") or lic.get("descripcion_del_procedimiento") or "")[:300]
        valor   = lic.get("precio_base", "N/A")
        entidad = lic.get("entidad", "N/A")
        fase    = lic.get("fase", "N/A")

        raw_txt = ""
        analisis: dict = {}
        error_msg = ""

        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=200,
                temperature=0.0,
                system=(
                    f"Eres SIACO, experto en licitaciones SECOP II Colombia. "
                    f"El cliente trabaja en: {objeto_cliente}. "
                    "Evalua la relevancia del contrato para ese perfil. "
                    "Responde EXCLUSIVAMENTE con un objeto JSON con estos campos exactos: "
                    '{"score": <entero 0-100>, "motivo": "<max 8 palabras>", "urgente": <true|false>}'
                ),
                messages=[{"role": "user", "content": (
                    f"Contrato a evaluar:\n"
                    f"Objeto: {nombre}\n"
                    f"Descripcion: {desc}\n"
                    f"Valor: COP {valor}\n"
                    f"Entidad: {entidad}\n"
                    f"Fase: {fase}"
                )}],
            )
            raw_txt = resp.content[0].text.strip()
            logger.info("[ANALIZAR %d] Claude raw: %s", idx, raw_txt[:200])

            analisis = parsear_json_claude(raw_txt) or {}
            logger.info("[ANALIZAR %d] JSON parseado: %s", idx, analisis)

        except anthropic.AuthenticationError as e:
            error_msg = f"API key inválida: {str(e)[:100]}"
            logger.error("[ANALIZAR %d] AuthenticationError: %s", idx, error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
        except anthropic.APIConnectionError as e:
            error_msg = f"Sin conexión a Anthropic: {str(e)[:100]}"
            logger.error("[ANALIZAR %d] ConnectionError: %s", idx, error_msg)
            raise HTTPException(status_code=503, detail=error_msg)
        except Exception as e:
            error_msg = str(e)[:120]
            logger.error("[ANALIZAR %d] Error inesperado: %s | raw=%s", idx, error_msg, raw_txt[:200])
            # Continúa con el siguiente contrato en lugar de abortar todo

        # Soporta variantes de nombre de campo: score / score_viabilidad / relevancia
        score_val = (
            analisis.get("score")
            or analisis.get("score_viabilidad")
            or analisis.get("relevancia")
            or 0
        )
        try:
            score_val = int(score_val)
        except (TypeError, ValueError):
            score_val = 0

        resultados.append({
            **lic,
            "_score":   score_val,
            "_motivo":  str(analisis.get("motivo") or analisis.get("razon") or error_msg or "Sin análisis"),
            "_urgente": bool(analisis.get("urgente", lic.get("_urgente", False))),
        })

    resultados.sort(key=lambda x: x["_score"], reverse=True)
    logger.info("[ANALIZAR] Completado: %d contratos, scores: %s",
                len(resultados), [r["_score"] for r in resultados[:5]])
    return {"resultados": resultados}


# ── GET /api/contratos/busqueda-avanzada ─────────
def _safe(v: str) -> str:
    """Elimina comillas simples para evitar inyección en SoQL."""
    return str(v).replace("'", "").replace(";", "")


@router.get("/contratos/busqueda-avanzada")
def busqueda_avanzada(
    codigo_proceso: str            = Query(""),
    nit_entidad:    str            = Query(""),
    municipio:      str            = Query(""),
    departamento:   str            = Query(""),
    modalidad:      str            = Query(""),
    valor_min:      Optional[float]= Query(None),
    valor_max:      Optional[float]= Query(None),
    fecha_desde:    str            = Query(""),
    fecha_hasta:    str            = Query(""),
    keywords:       str            = Query(""),
    unspsc:         str            = Query(""),
    authorization:  str            = Header(None),
):
    """Búsqueda avanzada en SECOP II con filtros combinables. Código de proceso = búsqueda exacta."""
    from routers.auth import require_auth
    require_auth(authorization)

    busqueda_exacta = bool(codigo_proceso.strip())
    clausulas: list[str] = []

    if busqueda_exacta:
        clausulas.append(f"id_del_proceso = '{_safe(codigo_proceso.strip())}'")
    else:
        if nit_entidad:
            clausulas.append(f"nit_entidad = '{_safe(nit_entidad.strip())}'")
        if municipio:
            clausulas.append(f"municipio_entidad like '%{_safe(municipio.strip())}%'")
        if departamento:
            clausulas.append(f"departamento_entidad like '%{_safe(departamento.strip())}%'")
        if modalidad:
            clausulas.append(f"modalidad_de_contratacion = '{_safe(modalidad.strip())}'")
        if valor_min is not None:
            clausulas.append(f"precio_base >= {int(valor_min)}")
        if valor_max is not None:
            clausulas.append(f"precio_base <= {int(valor_max)}")
        if fecha_desde:
            clausulas.append(f"fecha_de_publicacion >= '{_safe(fecha_desde)}T00:00:00'")
        if fecha_hasta:
            clausulas.append(f"fecha_de_publicacion <= '{_safe(fecha_hasta)}T23:59:59'")
        if keywords:
            kw_clause = _keywords_where(keywords.strip())
            if kw_clause:
                clausulas.append(kw_clause)
        if unspsc:
            clausulas.append(f"unspsc_bienes_y_servicios like '%{_safe(unspsc.strip())}%'")

    if not clausulas:
        raise HTTPException(
            status_code=400,
            detail="Ingresa al menos un criterio de búsqueda.",
        )

    where = " AND ".join(clausulas)
    params_av = {
        "$where": where,
        "$limit": "50",
        "$order": "fecha_de_publicacion DESC",
    }

    fuente1 = _fetch_secop(SECOP_URL,   params_av)
    fuente2 = _fetch_secop(SECOP_URL_2, params_av)

    if not fuente1 and not fuente2 and not busqueda_exacta:
        raise HTTPException(
            status_code=503,
            detail="No se pudo conectar con SECOP II. Intente en unos segundos.",
        )

    resultados = _fusionar(fuente1, fuente2)
    logger.info("[BUSQ-AVZ] fuente1=%d fuente2=%d fusionados=%d where=%s",
                len(fuente1), len(fuente2), len(resultados), where[:120])

    # Advertencia si búsqueda exacta y proceso ya está cerrado
    advertencia: Optional[str] = None
    if busqueda_exacta and resultados:
        fase = str(
            resultados[0].get("fase", "") or
            resultados[0].get("estado_del_procedimiento", "")
        ).lower()
        if any(exc in fase for exc in FASES_EXCLUIDAS):
            raw_fecha = (
                resultados[0].get("fecha_limite_recepcion_ofertas", "") or
                resultados[0].get("fecha_de_recepcion_de", "") or ""
            )
            fecha_fmt = ""
            if raw_fecha:
                try:
                    dt = datetime.fromisoformat(str(raw_fecha).replace("Z", "").split("+")[0])
                    fecha_fmt = dt.strftime("%d/%m/%Y")
                except Exception:
                    fecha_fmt = str(raw_fecha)[:10]
            advertencia = (
                f"Este proceso ya cerro el {fecha_fmt} pero puedes revisar su informacion."
                if fecha_fmt else
                "Este proceso ya esta cerrado pero puedes revisar su informacion."
            )

    # Enriquecer con campos calculados
    now = datetime.now()
    for r in resultados:
        dt_oferta = (
            _parse_dt(r.get("fecha_limite_recepcion_ofertas", "")) or
            _parse_dt(r.get("fecha_de_recepcion_de", ""))
        )
        dias_cierre = None
        if dt_oferta:
            dias_cierre = max(0, int((dt_oferta - now).total_seconds() / 86400))
        r.update({
            "_score":            0,
            "_score_hibrido":    0.0,
            "_motivo":           "Búsqueda avanzada",
            "_urgente":          dias_cierre is not None and dias_cierre <= 3,
            "_dias_cierre":      dias_cierre,
            "_busqueda_avanzada": True,
        })

    return {
        "contratos":       resultados,
        "total":           len(resultados),
        "advertencia":     advertencia,
        "busqueda_exacta": busqueda_exacta,
        "fuentes": {
            "endpoint_1": len(fuente1),
            "endpoint_2": len(fuente2),
            "total_fusionados": len(resultados),
        },
    }


# ── POST /api/contratos/expediente ────────────────
class ExpedienteDesdeBody(BaseModel):
    contrato: dict
    score: Optional[int] = 0


@router.post("/contratos/expediente")
def agregar_a_expediente(body: ExpedienteDesdeBody, authorization: str = Header(None)):
    """Agrega contrato directamente al expediente desde búsqueda."""
    from routers.auth import require_auth
    from routers.perfil import _cliente_id_from_session
    from gestor_expedientes import agregar_expediente

    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)
    result = agregar_expediente(cid, body.contrato, body.score)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Error al agregar"))
    return result
