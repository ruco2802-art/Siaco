# -*- coding: utf-8 -*-
"""Router de inteligencia competitiva — SIACO v3.0 (Plan Premium)"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form
from pydantic import BaseModel, Field

import competidor as comp

router = APIRouter(tags=["competidores"])


def _check_premium(sesion: dict):
    plan = sesion.get("plan", "basico")
    if plan not in ("premium", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Esta función está disponible solo en el Plan Premium. Contacta a SIACO para actualizar.",
        )


# ── Endpoints ──────────────────────────────────────
@router.post("/competidores/extraer")
async def extraer_oferta(
    proceso_id: str = Form(...),
    nit_competidor: str = Form(...),
    nombre_competidor: str = Form(""),
    pdf: UploadFile = File(...),
    authorization: str = Header(None),
):
    """Extrae datos de oferta de un competidor desde PDF. Solo plan premium."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    _check_premium(sesion)

    raw = await pdf.read()
    if not raw:
        raise HTTPException(status_code=400, detail="PDF vacío")

    result = comp.extraer_datos_oferta(raw, proceso_id, nit_competidor)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Error al extraer PDF"))

    # Actualizar perfil acumulado del competidor
    datos = result.get("datos", {})
    datos["nombre"] = nombre_competidor or datos.get("nombre", nit_competidor)
    comp.actualizar_inteligencia_competitiva(nit_competidor, datos)

    return result


@router.get("/competidores/{proceso_id}")
def listar_competidores(proceso_id: str, authorization: str = Header(None)):
    """Lista competidores analizados para un proceso. Solo plan premium."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    _check_premium(sesion)

    lista = comp.listar_competidores_proceso(proceso_id)
    return {"competidores": lista, "total": len(lista)}


@router.post("/competidores/estrategia/{proceso_id}")
def generar_estrategia(proceso_id: str, authorization: str = Header(None)):
    """Genera estrategia de oferta vs competidores. Solo plan premium."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    _check_premium(sesion)

    cid = sesion.get("cliente_id") or sesion.get("id") or ""
    competidores_proceso = comp.listar_competidores_proceso(proceso_id)

    if not competidores_proceso:
        raise HTTPException(
            status_code=404,
            detail="No hay competidores analizados para este proceso. Sube las ofertas primero.",
        )

    estrategia = comp.generar_estrategia_oferta(cid, proceso_id, competidores_proceso)
    return {
        "proceso_id": proceso_id,
        "num_competidores": len(competidores_proceso),
        "estrategia": estrategia,
    }


@router.get("/competidores/inteligencia/{nit}")
def inteligencia_competidor(nit: str, authorization: str = Header(None)):
    """Perfil histórico acumulado de un competidor. Solo plan premium."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    _check_premium(sesion)

    perfil = comp.cargar_inteligencia_competidor(nit)
    if not perfil:
        raise HTTPException(status_code=404, detail=f"Sin datos históricos para NIT {nit}")
    return perfil


class EstrategiaPrecioBody(BaseModel):
    cliente_id:            str
    proceso_id:            str
    precio_minimo_cliente: float = Field(..., gt=0)
    presupuesto_oficial:   float = Field(..., gt=0)
    metodo_calificacion:   str   = "media_aritmetica"
    n_proponentes:         int   = Field(3, ge=1, le=20)


@router.post("/competidores/estrategia-precio")
def estrategia_precio(body: EstrategiaPrecioBody, authorization: str = Header(None)):
    """
    Modelo matemático de decisión de precio con simulación Monte Carlo.
    Calcula precio óptimo para maximizar probabilidad de adjudicación.
    Solo plan premium.
    """
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    _check_premium(sesion)

    if body.metodo_calificacion not in comp.METODOS_CALIFICACION:
        raise HTTPException(
            status_code=422,
            detail=f"Método '{body.metodo_calificacion}' no válido. "
                   f"Opciones: {list(comp.METODOS_CALIFICACION.keys())}",
        )

    # Recopilar historial de precios de competidores en el proceso
    competidores_proceso = comp.listar_competidores_proceso(body.proceso_id)
    precios_historicos   = [
        c.get("precio_ofertado") for c in competidores_proceso
        if c.get("precio_ofertado") and float(c.get("precio_ofertado", 0)) > 0
    ]

    # Complementar con historial global de la inteligencia acumulada
    intel_global = comp.cargar_inteligencia_competidor("")  # vacío → no existe
    for c in competidores_proceso:
        nit = c.get("nit", "")
        if nit:
            intel = comp.cargar_inteligencia_competidor(nit)
            precios_historicos += intel.get("historial_precios", [])

    try:
        resultado = comp.modelo_precio_optimo(
            precio_minimo_cliente = body.precio_minimo_cliente,
            presupuesto_oficial   = body.presupuesto_oficial,
            precios_historicos    = precios_historicos,
            metodo_calificacion   = body.metodo_calificacion,
            n_proponentes         = body.n_proponentes,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return resultado
