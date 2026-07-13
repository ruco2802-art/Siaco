# -*- coding: utf-8 -*-
"""Router de búsqueda SECOP II — SIACO v3.0"""
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
from concurrent.futures import ThreadPoolExecutor
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

# App token de Socrata — levanta bloqueos de IP de hosting (Railway, Heroku, etc.)
# Registrar en https://www.datos.gov.co/profile/app_tokens
# Agregar en Railway: Settings → Variables → SOCRATA_APP_TOKEN=xxxxx
_SOCRATA_TOKEN = os.getenv("SOCRATA_APP_TOKEN", "")
_SECOP_HEADERS = {"X-App-Token": _SOCRATA_TOKEN} if _SOCRATA_TOKEN else {}


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


_SECOP_TIMEOUT_MSG = (
    "El SECOP II está tardando demasiado en responder. "
    "Por favor, intenta aplicar más filtros de búsqueda o inténtalo de nuevo en unos minutos."
)


def _fetch_secop(url: str, params: dict) -> list[dict] | None:
    """Fetch con un solo reintento desde un endpoint SECOP II.
    - timeout=15s por intento.
    - Propaga requests.exceptions.Timeout sin reintentar (el caller lanza 504).
    - Retorna None si SECOP no es alcanzable tras 2 intentos (fallo de red).
    - Retorna [] si SECOP responde pero sin datos o con formato inesperado.
    """
    for intento in range(2):
        try:
            resp   = requests.get(url, params=params, timeout=15, headers=_SECOP_HEADERS)
            if resp.status_code == 403:
                logger.error("[SECOP] 403 Forbidden desde %s — IP bloqueada por datos.gov.co", url)
                return None  # bloqueo de IP → tratar como no alcanzable
            parsed = resp.json()
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, dict)]
            logger.warning("[SECOP] Respuesta no-lista de %s (HTTP %d): %s",
                           url, resp.status_code, str(parsed)[:300])
            return []  # SECOP alcanzable pero formato inesperado (ej: SoQL error)
        except requests.exceptions.Timeout:
            raise
        except Exception as e:
            logger.warning("[SECOP] Intento %d/%s falló: %s", intento + 1, url, e)
            if intento == 0:
                time.sleep(2)
    return None  # No alcanzable tras 2 intentos


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


# ── GET /api/secop-health ──────────────────────────────────────────────────────
@router.get("/secop-health")
def secop_health():
    """Diagnóstico de conectividad con SECOP II desde el servidor. Sin auth requerida."""
    import socket
    result = {}

    # DNS resolution
    try:
        ip = socket.gethostbyname("www.datos.gov.co")
        result["dns"] = {"ok": True, "ip": ip}
    except Exception as e:
        result["dns"] = {"ok": False, "error": str(e)}

    result["app_token_configured"] = bool(_SOCRATA_TOKEN)

    # HTTP test contra ambos datasets
    for label, url in [("p6dx8zbt", SECOP_URL), ("rpmrutcd", SECOP_URL_2)]:
        t0 = time.time()
        try:
            r = requests.get(url, params={"$limit": "1"}, timeout=10, headers=_SECOP_HEADERS)
            result[label] = {
                "ok": r.status_code == 200,
                "status": r.status_code,
                "ms": round((time.time() - t0) * 1000),
                "body_snippet": r.text[:200],
                "blocked_403": r.status_code == 403,
            }
        except requests.exceptions.Timeout:
            result[label] = {"ok": False, "error": "timeout", "ms": round((time.time() - t0) * 1000)}
        except Exception as e:
            result[label] = {"ok": False, "error": f"{type(e).__name__}: {e}", "ms": round((time.time() - t0) * 1000)}

    return result


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

    fuente1: list[dict] | None = None
    fuente2: list[dict] | None = None
    t1_ok = True
    t2_ok = True

    with ThreadPoolExecutor(max_workers=2) as _pool:
        _f1 = _pool.submit(_fetch_secop, SECOP_URL,   params_base)
        _f2 = _pool.submit(_fetch_secop, SECOP_URL_2, params_base)
        try:
            fuente1 = _f1.result()
        except requests.exceptions.Timeout:
            t1_ok = False
        try:
            fuente2 = _f2.result()
        except requests.exceptions.Timeout:
            t2_ok = False

    if not t1_ok and not t2_ok:
        raise HTTPException(status_code=504, detail=_SECOP_TIMEOUT_MSG)

    # None = SECOP no alcanzable (fallo de red); [] = alcanzable pero sin datos
    secop_ok = (t1_ok and fuente1 is not None) or (t2_ok and fuente2 is not None)
    if not secop_ok:
        raise HTTPException(
            status_code=503,
            detail="No se pudo conectar con SECOP II. Intente en unos segundos.",
        )

    f1 = fuente1 or []
    f2 = fuente2 or []
    lics_raw = _fusionar(f1, f2)
    logger.info("[CONTRATOS] fuente1=%d fuente2=%d fusionados=%d",
                len(f1), len(f2), len(lics_raw))

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


# ── POST /api/contratos/score ─────────────────────
# El browser trae los contratos desde datos.gov.co (evita 403 a IPs de Railway).
# Este endpoint aplica filtros duros + scoring híbrido con perfil del cliente.
class ScoreBody(BaseModel):
    contratos: list
    valor_minimo: float = 5_000_000


@router.post("/contratos/score")
def score_contratos(body: ScoreBody, authorization: str = Header(None)):
    """Filtra y puntúa contratos traídos por el browser. Misma respuesta que GET /api/contratos."""
    from routers.auth import require_auth
    from routers.perfil import _load_perfil, _cliente_id_from_session
    from analizador import busqueda_hibrida_triple

    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)
    perfil = _load_perfil(cid)

    now = datetime.now()
    seen: set[str] = set()
    contratos_pre: list[dict] = []
    descartados: list[dict] = []

    for lic in (body.contratos or []):
        if not isinstance(lic, dict):
            continue
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
        if valor < body.valor_minimo:
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

    modo_busqueda = "keywords_only"
    contratos_relevantes = contratos_pre

    if perfil:
        try:
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
            pass

    return {
        "contratos_relevantes":  contratos_relevantes,
        "contratos_descartados": descartados,
        "total_analizados":      len(body.contratos or []),
        "total_relevantes":      len(contratos_relevantes),
        "total_descartados":     len(descartados),
        "modo_busqueda":         modo_busqueda,
        "contratos":             contratos_relevantes,
        "descartados":           descartados[:5],
        "total":                 len(contratos_relevantes),
        "total_raw":             len(body.contratos or []),
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
    params_only:    bool           = Query(False),
    authorization:  str            = Header(None),
):
    """Búsqueda avanzada en SECOP II. Con ?params_only=true devuelve SoQL para fetch desde el browser."""
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
            clausulas.append(f"upper(modalidad_de_contratacion) like upper('%{_safe(modalidad.strip())}%')")
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

    # El browser puede hacer el fetch directamente (datos.gov.co bloquea IPs de Railway).
    if params_only:
        return {
            "secop_url":      SECOP_URL,
            "soql_params":    params_av,
            "busqueda_exacta": busqueda_exacta,
            "fases_excluidas": FASES_EXCLUIDAS,
            "sugerencia_base": (
                "No se encontraron contratos con esa combinación de filtros. "
                "Intenta con menos filtros o palabras más generales."
                if len(clausulas) >= 3 else
                "No se encontraron contratos en SECOP II. "
                "Prueba ampliar el rango de fechas o usar palabras más generales."
            ),
        }

    logger.info("[BUSQ-AVZ] $where completo: %s", where)

    fuente1: list[dict] | None = None
    fuente2: list[dict] | None = None
    timeout1 = False
    timeout2 = False

    with ThreadPoolExecutor(max_workers=2) as _pool:
        _f1 = _pool.submit(_fetch_secop, SECOP_URL,   params_av)
        _f2 = _pool.submit(_fetch_secop, SECOP_URL_2, params_av)
        try:
            fuente1 = _f1.result()
        except requests.exceptions.Timeout:
            timeout1 = True
            logger.warning("[BUSQ-AVZ] Timeout en fuente1 (%s)", SECOP_URL)
        try:
            fuente2 = _f2.result()
        except requests.exceptions.Timeout:
            timeout2 = True
            logger.warning("[BUSQ-AVZ] Timeout en fuente2 (%s)", SECOP_URL_2)

    if timeout1 and timeout2:
        raise HTTPException(status_code=504, detail=_SECOP_TIMEOUT_MSG)

    # None = SECOP no alcanzable (fallo de red); [] = alcanzable pero sin coincidencias
    secop_ok = (not timeout1 and fuente1 is not None) or (not timeout2 and fuente2 is not None)
    if not secop_ok:
        raise HTTPException(
            status_code=503,
            detail="No se pudo conectar con SECOP II. Intente en unos segundos.",
        )

    f1 = fuente1 or []
    f2 = fuente2 or []
    resultados = _fusionar(f1, f2)
    logger.info("[BUSQ-AVZ] fuente1=%d fuente2=%d fusionados=%d",
                len(f1), len(f2), len(resultados))

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

    sugerencia: Optional[str] = None
    if not resultados and not busqueda_exacta:
        filtros_activos = len(clausulas)
        if filtros_activos >= 3:
            sugerencia = (
                "No se encontraron contratos con esa combinación de filtros. "
                "Intenta con menos filtros: por ejemplo, solo departamento + palabra clave, "
                "o cambia la modalidad a 'Licitación' para ampliar la búsqueda. "
                "En SECOP II los nombres de procesos varían; prueba sinónimos como "
                "'climatizacion', 'refrigeracion' o 'adecuacion' (sin tilde)."
            )
        else:
            sugerencia = (
                "No se encontraron contratos con esos criterios en SECOP II. "
                "Prueba ampliar el rango de fechas o usar palabras más generales."
            )

    return {
        "contratos":       resultados,
        "total":           len(resultados),
        "advertencia":     advertencia,
        "sugerencia":      sugerencia,
        "busqueda_exacta": busqueda_exacta,
        "fuentes": {
            "endpoint_1": len(f1),
            "endpoint_2": len(f2),
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
