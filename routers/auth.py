# -*- coding: utf-8 -*-
"""Router de autenticación — SIACO v3.0"""
import uuid
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

import auth as _auth_core   # módulo raíz del proyecto

router = APIRouter(tags=["auth"])

# Sesiones en memoria: token (UUID) → datos del cliente
_sessions: dict[str, dict] = {}


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginBody):
    cliente = _auth_core.verificar_credenciales(
        body.username.strip(), body.password.strip()
    )
    if not cliente:
        raise HTTPException(status_code=401, detail="Credenciales inválidas o cuenta inactiva")
    token = str(uuid.uuid4())
    _sessions[token] = cliente
    return {"token": token, "cliente": cliente}


@router.post("/logout")
def logout(authorization: str = Header(None)):
    token = (authorization or "").replace("Bearer ", "")
    _sessions.pop(token, None)
    return {"ok": True}


def require_auth(authorization: str) -> dict:
    """Valida token y retorna datos del cliente. Lanza 401 si inválido."""
    token = (authorization or "").replace("Bearer ", "")
    cliente = _sessions.get(token)
    if not cliente:
        raise HTTPException(status_code=401, detail="Token inválido o expirado. Inicia sesión de nuevo.")
    return cliente
