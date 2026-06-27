# -*- coding: utf-8 -*-
"""Router de autenticación — SIACO v3.0"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

import auth as _auth_core
import sesiones as _sesiones

router = APIRouter(tags=["auth"])


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
    tipo: str = "cliente"
    dias_acceso: int = 7
    email: str = ""
    whatsapp: str = ""


class ConsumiirBody(BaseModel):
    feature: str


@router.post("/login")
def login(body: LoginBody):
    cliente = _auth_core.verificar_credenciales(
        body.username.strip(), body.password.strip()
    )
    if not cliente or cliente.get("_bloqueado"):
        detail = cliente.get("_mensaje", "Credenciales inválidas o cuenta inactiva") \
            if isinstance(cliente, dict) else "Credenciales inválidas o cuenta inactiva"
        raise HTTPException(status_code=401, detail=detail)
    token = _sesiones.create_session(cliente)
    return {"token": token, "cliente": cliente}


@router.post("/logout")
def logout(authorization: str = Header(None)):
    token = (authorization or "").replace("Bearer ", "")
    _sesiones.delete_session(token)
    return {"ok": True}


def require_auth(authorization: str) -> dict:
    """Valida token y retorna datos del cliente. Lanza 401 si inválido."""
    token = (authorization or "").replace("Bearer ", "")
    cliente = _sesiones.get_session(token)
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

    result = _auth_core.crear_cliente(
        username, body.password,
        plan=body.plan,
        tipo=body.tipo,
        dias_acceso=body.dias_acceso,
    )
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

    return {"ok": True, "username": username, "plan": body.plan, "tipo": body.tipo}


@router.get("/admin/clientes")
def listar_clientes(authorization: str = Header(None)):
    """Lista todos los clientes. Solo admin."""
    admin = require_auth(authorization)
    if admin.get("plan") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    return {"clientes": _auth_core.listar_clientes_activos()}


@router.post("/admin/clientes/{username}/extender")
def extender_acceso(username: str, authorization: str = Header(None)):
    """Extiende acceso del tester 7 días."""
    admin = require_auth(authorization)
    if admin.get("plan") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    ok = _auth_core.extender_acceso(username, 7)
    if not ok:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return {"ok": True}


@router.post("/admin/clientes/{username}/convertir")
def convertir_a_cliente(username: str, authorization: str = Header(None)):
    """Convierte tester a cliente."""
    admin = require_auth(authorization)
    if admin.get("plan") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    ok = _auth_core.convertir_a_cliente(username)
    if not ok:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return {"ok": True}


@router.post("/tester/consumir")
def consumir_premium(body: ConsumiirBody, authorization: str = Header(None)):
    """Marca una función premium como usada por el tester."""
    sesion = require_auth(authorization)
    cliente_id = sesion.get("id") or sesion.get("cliente_id") or ""
    if not cliente_id or not body.feature:
        raise HTTPException(status_code=422, detail="Parámetros incompletos")
    resultado = _auth_core.actualizar_usos_premium(cliente_id, body.feature)
    if resultado == "ya_usado":
        raise HTTPException(status_code=409, detail="Ya utilizaste tu acceso de prueba a esta función")
    return {"ok": True, "feature": body.feature}
