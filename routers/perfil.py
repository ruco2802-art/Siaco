# -*- coding: utf-8 -*-
"""Router de perfil de cliente — SIACO v3.0"""
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form
from pydantic import BaseModel

import gestor_documentos as gd

logger = logging.getLogger("siaco")

router = APIRouter(tags=["perfil"])


# ── Modelos ────────────────────────────────────────
# PerfilBody = vista que el formulario frontend puede enviar hoy.
# Los campos None llegan al pipeline como dato_faltante (no como cero).
# Campos pendientes de agregar al formulario frontend marcados con [TODO-FORM].

class PerfilBodyFinanciero(BaseModel):
    # Hoy en el formulario
    indice_liquidez: float | None = None
    indice_endeudamiento: float | None = None
    cobertura_intereses: float | None = None    # era razon_cobertura_interes
    capital_trabajo: float | None = None
    patrimonio_neto: float | None = None        # era patrimonio_liquido
    renta_operacional: float | None = None      # [TODO-FORM]
    ebitda: float | None = None                 # [TODO-FORM]
    rentabilidad_patrimonio: float | None = None  # [TODO-FORM] ROE
    rentabilidad_activo: float | None = None      # [TODO-FORM] ROA
    roe: float | None = None                    # [TODO-FORM]
    roa: float | None = None                    # [TODO-FORM]
    ingresos_operacionales_ultimos_5_anos: list[float] = []  # [TODO-FORM] lista 5 años
    saldos_contratos_en_ejecucion: float | None = None       # [TODO-FORM]
    numero_profesionales_vinculados: int | None = None       # [TODO-FORM]


class PerfilBodyJuridico(BaseModel):
    rup_en_firme: bool | None = None
    rup_fecha_expedicion: str | None = None     # [TODO-FORM]
    camara_comercio: bool | None = None
    camara_comercio_fecha: str | None = None    # [TODO-FORM]
    rut_vigente: bool | None = None             # [TODO-FORM]
    rut_fecha: str | None = None                # [TODO-FORM]
    paz_y_salvo_parafiscales: bool | None = None      # [TODO-FORM]
    paz_y_salvo_seguridad_social: bool | None = None  # [TODO-FORM]
    paz_y_salvo_impuestos: bool | None = None         # [TODO-FORM]
    paz_salvo_municipal: bool | None = None           # [TODO-FORM]
    sin_inhabilidades: bool | None = None             # [TODO-FORM]
    sin_antecedentes_disciplinarios: bool | None = None  # [TODO-FORM]
    sin_antecedentes_penales: bool | None = None         # [TODO-FORM]
    antecedentes_fiscales: bool | None = None         # [TODO-FORM]
    redam: bool | None = None                         # [TODO-FORM]
    medidas_correctivas: bool | None = None           # [TODO-FORM]
    garantia_seriedad: bool | None = None             # [TODO-FORM]


class PerfilBodyExperiencia(BaseModel):
    valor_acumulado: float | None = None
    valor_individual_max: float | None = None
    objetos_similares: list[str] = []           # era objeto_similar (str)
    codigos_unspsc: list[str] = []              # era codigos_unspsc (str)
    contratos_acreditados: int | None = None    # [TODO-FORM]
    antiguedad_meses: int | None = None         # [TODO-FORM]


class PerfilBodySocial(BaseModel):
    porcentaje_mujeres_nomina: float | None = None  # [TODO-FORM]
    porcentaje_discapacidad: float | None = None    # [TODO-FORM]
    personas_reincorporadas: int | None = None      # [TODO-FORM]
    poblacion_etnica: bool | None = None            # [TODO-FORM]


class PerfilBody(BaseModel):
    # Identificación
    nombre: str = ""
    nit: str = ""
    sector: str = ""
    municipio_domicilio: str = ""           # [TODO-FORM]
    departamento_domicilio: str = ""        # [TODO-FORM]
    es_mipyme: bool = False
    tamano_empresa: str | None = None       # [TODO-FORM] "micro"|"pequena"|"mediana"|"grande"
    es_empresa_de_mujeres: bool = False     # [TODO-FORM]
    # Metadatos de contacto (no van al pipeline)
    notificacion: str = "whatsapp"
    contacto_whatsapp: str = ""
    contacto_email: str = ""
    # Bloques de capacidad
    financiero: PerfilBodyFinanciero = PerfilBodyFinanciero()
    juridico: PerfilBodyJuridico = PerfilBodyJuridico()
    experiencia: PerfilBodyExperiencia = PerfilBodyExperiencia()
    social: PerfilBodySocial = PerfilBodySocial()      # [TODO-FORM] sección nueva

    def to_perfil_empresa(self) -> dict:
        """
        Produce el dict que cargar_perfil() acepta.
        Los campos vacíos (0.0, "") se convierten en None para que el evaluador
        los trate como dato_faltante en vez de producir un score de cero.
        """
        fin = self.financiero.model_dump()
        jur = self.juridico.model_dump()
        exp = self.experiencia.model_dump()
        soc = self.social.model_dump()

        # Normalizar strings vacíos → None en campos de fecha
        for d in (jur,):
            for k, v in d.items():
                if isinstance(v, str) and v.strip() == "":
                    d[k] = None

        return {
            "nombre": self.nombre,
            "nit": self.nit or None,
            "sector": self.sector or None,
            "municipio_domicilio": self.municipio_domicilio or None,
            "departamento_domicilio": self.departamento_domicilio or None,
            "es_mipyme": self.es_mipyme,
            "tamano_empresa": self.tamano_empresa or None,
            "es_empresa_de_mujeres": self.es_empresa_de_mujeres,
            "financiero": fin if any(v is not None for v in fin.values() if not isinstance(v, list)) else None,
            "juridico": jur if any(v is not None for v in jur.values() if not isinstance(v, str)) else None,
            "experiencia": exp if any(v is not None for v in exp.values() if not isinstance(v, list)) else None,
            "social": soc if any(v is not None for v in soc.values()) else None,
        }


# ── Helpers ────────────────────────────────────────

def _cliente_id_from_session(sesion: dict) -> str:
    return sesion.get("cliente_id") or sesion.get("id") or ""


def _cache_perfil(cid: str) -> Path:
    """Caché local /tmp — rápido dentro del contenedor, efímero entre deploys."""
    return Path(f"/tmp/siaco/{cid}/perfil.json")


def _sb_perfil_path(cid: str) -> str:
    return f"clientes/{cid}/perfil.json"


def _load_perfil(cid: str) -> dict:
    """
    Carga el perfil del cliente.
    1. Busca en caché /tmp (mismo contenedor).
    2. Si no existe, descarga desde Supabase Storage.
    """
    cache = _cache_perfil(cid)
    if cache.exists():
        try:
            with open(cache, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    try:
        from supabase_client import sb_download
        data = sb_download(_sb_perfil_path(cid))
        if data:
            perfil = json.loads(data.decode("utf-8"))
            cache.parent.mkdir(parents=True, exist_ok=True)
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(perfil, f, ensure_ascii=False, indent=2)
            return perfil
    except Exception as exc:
        logger.warning("[PERFIL] No se pudo cargar perfil de Supabase: %s", exc)

    return {}


def _save_perfil(cid: str, datos: dict):
    """
    Guarda el perfil:
    1. En caché /tmp (rápido para la sesión actual).
    2. En Supabase Storage (persiste entre deploys).
    """
    cache = _cache_perfil(cid)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

    try:
        from supabase_client import sb_upload
        sb_upload(_sb_perfil_path(cid), cache.read_bytes(), "application/json")
    except RuntimeError as exc:
        # RuntimeError = variables de entorno faltantes o bucket inexistente
        msg = str(exc)
        logger.error("[PERFIL] Supabase config error: %s", msg)
        raise HTTPException(status_code=500, detail=f"Supabase: {msg[:300]}")
    except Exception as exc:
        msg = str(exc)
        logger.error("[PERFIL] No se pudo guardar perfil en Supabase: %s", msg)
        raise HTTPException(
            status_code=500,
            detail=f"Error al guardar en la nube: {msg[:300]}",
        )


# ── Endpoints ──────────────────────────────────────

@router.get("/perfil")
def get_perfil(authorization: str = Header(None)):
    """Retorna perfil completo del cliente autenticado."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)

    perfil = _load_perfil(cid)

    rup_info = {}
    try:
        rup_info = gd.verificar_vigencia_rup(cid)
    except Exception:
        pass

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

    existente = _load_perfil(cid)
    # Guarda en formato canónico (PerfilEmpresa) con metadatos de sesión preservados
    nuevo = body.to_perfil_empresa()
    nuevo["cliente_id"] = cid
    nuevo["notificacion"] = body.notificacion
    nuevo["contacto_whatsapp"] = body.contacto_whatsapp
    nuevo["contacto_email"] = body.contacto_email

    for campo in ("plan", "fecha_creacion"):
        if campo in existente:
            nuevo[campo] = existente[campo]

    _save_perfil(cid, nuevo)
    return {"ok": True, "cliente_id": cid}


@router.post("/perfil/documento")
async def upload_documento(
    tipo_doc: str = Form(...),
    archivo: UploadFile = File(...),
    authorization: str = Header(None),
):
    """Indexa un documento del cliente (PDF/DOCX) con embeddings y lo sube a Supabase."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)

    raw = await archivo.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Archivo vacío")

    resultado = gd.procesar_documento(raw, archivo.filename, cid, tipo_doc)
    if not resultado.get("ok"):
        raise HTTPException(
            status_code=500 if "nube" in resultado.get("error", "") else 422,
            detail=resultado.get("error", "Error al procesar"),
        )

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

    indice = gd._cargar_indice(cid)
    if not indice:
        return {"ok": True, "eliminados": 0}

    original = sum(1 for e in indice if e.get("filename") == filename)
    indice   = [e for e in indice if e.get("filename") != filename]

    try:
        gd._guardar_indice(cid, indice)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al actualizar índice: {str(exc)[:200]}")

    return {"ok": True, "eliminados": original}
