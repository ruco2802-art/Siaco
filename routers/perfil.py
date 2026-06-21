# -*- coding: utf-8 -*-
"""Router de perfil de cliente — SIACO v3.0"""
import json
import pickle
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form
from pydantic import BaseModel

import gestor_documentos as gd

router = APIRouter(tags=["perfil"])


# ── Modelos ────────────────────────────────────────
class RupModel(BaseModel):
    tiene_rup: bool = False
    estado_rup: str = "Inactivo"
    numero_rup: str = ""
    fecha_vencimiento_rup: str = ""


class FinancieroModel(BaseModel):
    indice_liquidez: float = 0.0
    indice_endeudamiento: float = 0.0
    razon_cobertura_interes: float = 0.0
    patrimonio_liquido: float = 0.0
    presupuesto_minimo_contrato: float = 10_000_000
    presupuesto_maximo_contrato: float = 500_000_000
    capital_trabajo: float = 0.0


class ExperienciaModel(BaseModel):
    valor_acumulado: float = 0.0
    valor_individual_max: float = 0.0
    objeto_similar: str = ""
    codigos_unspsc: str = ""
    participacion_minima: float = 30.0


class PerfilBody(BaseModel):
    nombre: str = ""
    nit: str = ""
    sector: str = ""
    notificacion: str = "whatsapp"
    contacto_whatsapp: str = ""
    contacto_email: str = ""
    rup: RupModel = RupModel()
    financiero: FinancieroModel = FinancieroModel()
    experiencia: ExperienciaModel = ExperienciaModel()


# ── Helpers ────────────────────────────────────────
def _cliente_id_from_session(sesion: dict) -> str:
    return sesion.get("cliente_id") or sesion.get("id") or ""


def _ruta_perfil(cid: str) -> Path:
    return Path(f"./clientes/{cid}/perfil.json")


def _load_perfil(cid: str) -> dict:
    ruta = _ruta_perfil(cid)
    if not ruta.exists():
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_perfil(cid: str, datos: dict):
    ruta = _ruta_perfil(cid)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


# ── Endpoints ──────────────────────────────────────
@router.get("/perfil")
def get_perfil(authorization: str = Header(None)):
    """Retorna perfil completo del cliente autenticado."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)

    perfil = _load_perfil(cid)

    # Enriquecer con vigencia RUP
    rup_info = {}
    try:
        rup_info = gd.verificar_vigencia_rup(cid)
    except Exception:
        pass

    # Lista de documentos indexados
    docs = []
    try:
        docs = gd.listar_documentos(cid)
    except Exception:
        pass

    return {
        "perfil": perfil,
        "rup_vigencia": rup_info,
        "documentos": docs,
        "plan": sesion.get("plan", "basico"),
    }


@router.put("/perfil")
def update_perfil(body: PerfilBody, authorization: str = Header(None)):
    """Actualiza el perfil completo del cliente."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)

    # Cargar perfil existente y fusionar
    existente = _load_perfil(cid)
    nuevo = body.model_dump()
    nuevo["cliente_id"] = cid

    # Preservar campos de sistema que el frontend no envía
    for campo in ("plan", "fecha_creacion", "notificacion"):
        if campo in existente and campo not in nuevo:
            nuevo[campo] = existente[campo]

    _save_perfil(cid, nuevo)
    return {"ok": True, "cliente_id": cid}


@router.post("/perfil/documento")
async def upload_documento(
    tipo_doc: str = Form(...),
    archivo: UploadFile = File(...),
    authorization: str = Header(None),
):
    """Indexa un documento del cliente (PDF/DOCX) con embeddings."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)

    raw = await archivo.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Archivo vacío")

    resultado = gd.procesar_documento(raw, archivo.filename, cid, tipo_doc)
    if not resultado.get("ok"):
        raise HTTPException(status_code=422, detail=resultado.get("error", "Error al procesar"))

    return resultado


@router.get("/perfil/documentos")
def list_documentos(authorization: str = Header(None)):
    """Lista documentos indexados del cliente."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)
    return {"documentos": gd.listar_documentos(cid)}


@router.delete("/perfil/documento/{filename}")
def delete_documento(filename: str, authorization: str = Header(None)):
    """Elimina un documento del índice de embeddings del cliente."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)

    ruta_pkl = Path(f"./clientes/{cid}/embeddings/documentos_index.pkl")
    if not ruta_pkl.exists():
        return {"ok": True, "eliminados": 0}

    try:
        with open(ruta_pkl, "rb") as f:
            indice = pickle.load(f)
        original = len(indice)
        indice = [e for e in indice if e.get("filename") != filename]
        with open(ruta_pkl, "wb") as f:
            pickle.dump(indice, f)
        return {"ok": True, "eliminados": original - len(indice)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
