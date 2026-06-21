# -*- coding: utf-8 -*-
"""Router de búsqueda SECOP II — SIACO v3.0"""
import json
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel

from config import API_KEY
import anthropic

router = APIRouter(tags=["busqueda"])

FASES_EXCLUIDAS = [
    "adjudicado", "desierto", "liquidado", "terminado", "celebrado",
    "suspendido", "cancelado",
]

SECOP_URL = "https://www.datos.gov.co/resource/p6dx-8zbt.json"


def _parse_dt(valor: str) -> Optional[datetime]:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "").split("+")[0])
    except Exception:
        return None


def _fmt_razon(lic: dict, razon: str) -> dict:
    return {
        "_razon": razon,
        "nombre_del_procedimiento": lic.get("nombre_del_procedimiento", "Sin nombre"),
        "entidad": lic.get("entidad", ""),
        "precio_base": lic.get("precio_base", 0),
    }


# ── GET /api/contratos ────────────────────────────
@router.get("/contratos")
def buscar_contratos(
    fecha_desde:    str   = Query("2026-01-01"),
    valor_minimo:   float = Query(5_000_000),
    max_resultados: int   = Query(50),
    departamento:   str   = Query(""),
    authorization:  str   = Header(None),
):
    """Obtiene contratos de SECOP II y aplica filtros duros de fase/tiempo/valor."""
    from routers.auth import require_auth
    require_auth(authorization)

    where = f"fecha_de_publicacion > '{fecha_desde}T00:00:00'"
    if departamento:
        where += f" AND departamento_entidad = '{departamento}'"

    lics_raw: list[dict] = []
    for intento in range(3):
        try:
            resp = requests.get(
                SECOP_URL,
                params={
                    "$where": where,
                    "$limit": str(min(max_resultados, 200)),
                    "$order": "fecha_de_publicacion DESC",
                },
                timeout=30,
            )
            parsed = resp.json()
            if isinstance(parsed, list):
                lics_raw = [x for x in parsed if isinstance(x, dict)]
                break
            raise ValueError("Respuesta inesperada")
        except Exception:
            if intento < 2:
                time.sleep(3)
            else:
                raise HTTPException(
                    status_code=503,
                    detail="No se pudo conectar con SECOP II. Intente en unos segundos.",
                )

    now = datetime.now()
    seen: set[str] = set()
    contratos: list[dict] = []
    descartados: list[dict] = []

    for lic in lics_raw:
        cod = lic.get("id_del_proceso") or lic.get("referencia_del_proceso", "")
        if not cod or cod in seen:
            continue
        seen.add(cod)

        fase = str(lic.get("fase", "") or lic.get("estado_del_procedimiento", "")).lower().strip()
        if any(exc in fase for exc in FASES_EXCLUIDAS):
            descartados.append(_fmt_razon(lic, f"Fase cerrada: {fase or 'sin fase'}"))
            continue

        dt_manif = _parse_dt(lic.get("fecha_limite_manifestacion_interes", ""))
        if dt_manif and dt_manif < now + timedelta(hours=24):
            horas = max(0, int((dt_manif - now).total_seconds() / 3600))
            descartados.append(_fmt_razon(lic, f"Manifestacion de interes cierra en {horas}h"))
            continue

        dt_oferta = (_parse_dt(lic.get("fecha_limite_recepcion_ofertas", ""))
                     or _parse_dt(lic.get("fecha_de_recepcion_de", "")))
        if dt_oferta and dt_oferta < now + timedelta(hours=48):
            horas = max(0, int((dt_oferta - now).total_seconds() / 3600))
            descartados.append(_fmt_razon(lic, f"Cierre de ofertas en {horas}h"))
            continue

        try:
            valor = float(lic.get("precio_base", 0) or 0)
        except Exception:
            valor = 0
        if valor < valor_minimo:
            descartados.append(_fmt_razon(lic, f"Valor COP {valor:,.0f} menor al minimo"))
            continue

        dias_cierre = None
        if dt_oferta:
            dias_cierre = max(0, int((dt_oferta - now).total_seconds() / 86400))

        contratos.append({
            **lic,
            "_score": 0,
            "_score_hibrido": 0.0,
            "_motivo": "",
            "_urgente": dias_cierre is not None and dias_cierre <= 3,
            "_dias_cierre": dias_cierre,
        })

    return {
        "contratos":   contratos,
        "descartados": descartados[:5],
        "total":       len(contratos),
        "total_raw":   len(lics_raw),
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
    from prompts import SKILL_ESTRATEGIA

    sesion = require_auth(authorization)
    cid = body.cliente_id or _cliente_id_from_session(sesion)
    perfil = _load_perfil(cid) if cid else {}

    sector = perfil.get("sector", "obras civiles y servicios")
    objeto_cliente = perfil.get("experiencia", {}).get("objeto_similar", sector)

    client = anthropic.Anthropic(api_key=API_KEY, timeout=25.0)
    resultados: list[dict] = []

    for lic in body.contratos[:50]:
        if not isinstance(lic, dict):
            continue
        nombre  = lic.get("nombre_del_procedimiento", "N/A")
        desc    = str(lic.get("descripci_n_del_procedimiento") or lic.get("descripcion_del_procedimiento") or "")[:300]
        valor   = lic.get("precio_base", "N/A")
        entidad = lic.get("entidad", "N/A")
        fase    = lic.get("fase", "N/A")

        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=150,
                temperature=0.0,
                system=(
                    f"Eres SIACO, experto en licitaciones SECOP II Colombia. "
                    f"El cliente trabaja en: {objeto_cliente}. "
                    "Evalua relevancia del contrato para el perfil del cliente. "
                    "Responde SOLO JSON sin texto adicional."
                ),
                messages=[{"role": "user", "content": (
                    f"Objeto: {nombre}\nDesc: {desc}\nValor: COP {valor}\nEntidad: {entidad}\nFase: {fase}\n"
                    '{"score":0-100,"motivo":"max 8 palabras","urgente":true_o_false}'
                )}],
            )
            txt = resp.content[0].text.strip()
            m = re.search(r"\{.*?\}", txt, re.DOTALL)
            analisis = json.loads(m.group(0)) if m else {}
        except Exception:
            analisis = {}

        resultados.append({
            **lic,
            "_score":   int(analisis.get("score", 0)),
            "_motivo":  str(analisis.get("motivo", "Sin análisis")),
            "_urgente": bool(analisis.get("urgente", lic.get("_urgente", False))),
        })

    resultados.sort(key=lambda x: x["_score"], reverse=True)
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
            clausulas.append(f"nombre_del_procedimiento like '%{_safe(keywords.strip())}%'")
        if unspsc:
            clausulas.append(f"unspsc_bienes_y_servicios like '%{_safe(unspsc.strip())}%'")

    if not clausulas:
        raise HTTPException(
            status_code=400,
            detail="Ingresa al menos un criterio de búsqueda.",
        )

    where = " AND ".join(clausulas)
    resultados: list[dict] = []

    for intento in range(3):
        try:
            resp = requests.get(
                SECOP_URL,
                params={
                    "$where": where,
                    "$limit": "50",
                    "$order": "fecha_de_publicacion DESC",
                },
                timeout=30,
            )
            parsed = resp.json()
            if isinstance(parsed, list):
                resultados = [x for x in parsed if isinstance(x, dict)]
                break
            raise ValueError("Respuesta inesperada de SECOP II")
        except Exception:
            if intento < 2:
                time.sleep(3)
            else:
                raise HTTPException(
                    status_code=503,
                    detail="No se pudo conectar con SECOP II. Intente en unos segundos.",
                )

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
