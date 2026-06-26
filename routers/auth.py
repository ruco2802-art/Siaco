# -*- coding: utf-8 -*-
"""Router de autenticación — SIACO v3.0"""
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

import auth as _auth_core   # módulo raíz del proyecto

router = APIRouter(tags=["auth"])

# Sesiones en memoria: token (UUID) → datos del cliente
_sessions: dict[str, dict] = {}


class LoginBody(BaseModel):
    username: str
    password: str


class CrearClienteBody(BaseModel):
    nombre_empresa: str
    nit: str
    username: str
    password: str
    sector: str = ""
    plan: str = "socio"
    email: str = ""
    whatsapp: str = ""


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


@router.post("/admin/clientes")
def crear_cliente_admin(body: CrearClienteBody, authorization: str = Header(None)):
    """Crea un nuevo cliente. Solo administradores."""
    admin = require_auth(authorization)
    if admin.get("plan") != "admin":
        raise HTTPException(status_code=403, detail="Acceso restringido a administradores")

    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=422, detail="El nombre de usuario es obligatorio")
    if Path(f"./clientes/{username}").exists():
        raise HTTPException(status_code=409, detail=f"El usuario '{username}' ya existe")

    result = _auth_core.crear_cliente(username, body.password, plan=body.plan)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail="Error al crear cliente en el sistema")

    perfil_path = Path(f"./clientes/{username}/perfil.json")
    try:
        with open(perfil_path, "r", encoding="utf-8") as f:
            perfil = json.load(f)
        perfil.update({
            "nombre": body.nombre_empresa,
            "nit": body.nit,
            "sector": body.sector,
            "contacto_email": body.email,
            "contacto_whatsapp": body.whatsapp,
        })
        with open(perfil_path, "w", encoding="utf-8") as f:
            json.dump(perfil, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return {"ok": True, "username": username, "plan": body.plan}
