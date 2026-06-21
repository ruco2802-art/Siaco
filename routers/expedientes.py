# -*- coding: utf-8 -*-
"""Router de expedientes — SIACO v3.0"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from gestor_expedientes import (
    listar_expedientes as _listar,
    agregar_expediente as _agregar,
    actualizar_estado,
)

router = APIRouter(tags=["expedientes"])


@router.get("/expedientes/{cliente_id}")
def listar(cliente_id: str, authorization: str = Header(None)):
    from routers.auth import require_auth
    require_auth(authorization)
    expedientes = _listar(cliente_id)
    return {"expedientes": expedientes, "total": len(expedientes)}


class ExpedienteBody(BaseModel):
    licitacion:  dict
    score:       Optional[float] = 0
    cliente_id:  str


@router.post("/expedientes")
def agregar(body: ExpedienteBody, authorization: str = Header(None)):
    from routers.auth import require_auth
    require_auth(authorization)
    result = _agregar(body.cliente_id, body.licitacion, body.score)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Error al agregar"))
    return result


class EstadoBody(BaseModel):
    cliente_id:   str
    proceso_id:   str
    nuevo_estado: str


@router.put("/expedientes/estado")
def actualizar(body: EstadoBody, authorization: str = Header(None)):
    from routers.auth import require_auth
    require_auth(authorization)
    actualizar_estado(body.cliente_id, body.proceso_id, body.nuevo_estado)
    return {"ok": True}
