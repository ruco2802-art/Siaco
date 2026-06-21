# -*- coding: utf-8 -*-
"""Router de inteligencia competitiva — SIACO v3.0 (Plan Premium)"""
from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form
from pydantic import BaseModel

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
