# -*- coding: utf-8 -*-
"""Router de perfil de cliente — SIACO v3.0"""
import json
import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form
from pydantic import BaseModel, field_validator

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
    sin_antecedentes_fiscales: bool | None = None      # [TODO-FORM]
    sin_redam: bool | None = None                     # [TODO-FORM]
    sin_medidas_correctivas: bool | None = None       # [TODO-FORM]
    garantia_seriedad: bool | None = None             # [TODO-FORM]


def _a_lista(v) -> list[str]:
    """
    Normaliza a lista lo que el formulario manda como texto separado por comas.

    [D39] El formulario web tiene un `<input type="text">` para los códigos
    UNSPSC y los objetos similares, así que manda una CADENA. El modelo los
    declaraba `list[str]`, y pydantic la rechazaba: **guardar el perfil desde
    la interfaz devolvía HTTP 422** en cuanto se escribía algo en esos campos.
    Es la misma discrepancia de forma que rompía el scoring, un piso más
    arriba.
    """
    if v is None or v == "":
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [t.strip() for t in str(v).replace(";", ",").split(",") if t.strip()]


class PerfilBodyExperiencia(BaseModel):
    valor_acumulado: float | None = None
    valor_individual_max: float | None = None
    objetos_similares: list[str] = []
    codigos_unspsc: list[str] = []
    contratos_acreditados: int | None = None    # [TODO-FORM]
    antiguedad_meses: int | None = None         # [TODO-FORM]

    # El formulario manda el singular `objeto_similar` y una cadena. Pydantic
    # descartaba el campo por nombre desconocido **en silencio**, así que la
    # consulta semántica del scorer llegaba vacía y caía al sector.
    objeto_similar: str = ""

    @field_validator("codigos_unspsc", "objetos_similares", mode="before")
    @classmethod
    def _acepta_cadena(cls, v):
        return _a_lista(v)


class PerfilBodySocial(BaseModel):
    porcentaje_mujeres_nomina: float | None = None  # [TODO-FORM]
    porcentaje_discapacidad: float | None = None    # [TODO-FORM]
    personas_reincorporadas: int | None = None      # [TODO-FORM]
    poblacion_etnica: bool | None = None            # [TODO-FORM]


class PerfilBodyDocumento(BaseModel):
    """
    [D27] Un documento del expediente tal como llega del formulario.

    `tiene` es tri-estado y los tres valores son distintos: `None` es «no se
    respondió», `False` es «no lo tiene» —un HALLAZGO que el informe reporta— y
    `True` es «lo tiene». Aplastar `None` a `False` inventaría un
    incumplimiento contra la empresa [I10].
    """
    tiene: bool | None = None
    fecha_expedicion: str | None = None


class PerfilBodyDocumentos(BaseModel):
    rup: PerfilBodyDocumento = PerfilBodyDocumento()
    existencia_representacion: PerfilBodyDocumento = PerfilBodyDocumento()
    estados_financieros: PerfilBodyDocumento = PerfilBodyDocumento()
    seguridad_social: PerfilBodyDocumento = PerfilBodyDocumento()
    documento_identidad: PerfilBodyDocumento = PerfilBodyDocumento()
    subcontratacion: PerfilBodyDocumento = PerfilBodyDocumento()
    capacidad_juridica: bool | None = None
    duracion_sociedad_hasta: str | None = None   # [D34]


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
    documentos: PerfilBodyDocumentos = PerfilBodyDocumentos()  # [D27]

    def to_perfil_empresa(self) -> dict:
        """
        Produce el dict que cargar_perfil() acepta.
        Los campos vacíos (0.0, "") se convierten en None para que el evaluador
        los trate como dato_faltante en vez de producir un score de cero.
        """
        fin = self.financiero.model_dump()
        jur = self.juridico.model_dump()
        exp = self.experiencia.model_dump()
        # `objeto_similar` no está en `PerfilExperiencia` pero SÍ lo usa el
        # scorer como consulta semántica, así que viaja igual. Si está vacío y
        # hay objetos similares, se deriva del primero en vez de dejarlo en
        # blanco y perder la señal.
        if not exp.get("objeto_similar") and exp.get("objetos_similares"):
            exp["objeto_similar"] = exp["objetos_similares"][0]
        soc = self.social.model_dump()
        docs = self.documentos.model_dump()
        for clave, v in docs.items():
            if isinstance(v, dict) and isinstance(v.get("fecha_expedicion"), str)                     and not v["fecha_expedicion"].strip():
                v["fecha_expedicion"] = None
        if isinstance(docs.get("duracion_sociedad_hasta"), str)                 and not docs["duracion_sociedad_hasta"].strip():
            docs["duracion_sociedad_hasta"] = None

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
            # [D27] El bloque documental viaja entero. Las fechas vacías pasan a
            # None por el mismo motivo que el resto: "" no es una fecha.
            "documentos": docs,
        }


# ── Helpers ────────────────────────────────────────

def _cliente_id_from_session(sesion: dict) -> str:
    """[D42a] El perfil ACTIVO manda sobre el de la sesión. Ver `cliente_id_activo`."""
    return cliente_id_activo(sesion)


def _cache_perfil(cid: str) -> Path:
    """Caché local /tmp — rápido dentro del contenedor, efímero entre deploys."""
    return Path(f"/tmp/siaco/{cid}/perfil.json")


def _sb_perfil_path(cid: str) -> str:
    return f"clientes/{cid}/perfil.json"


def _load_perfil(cid: str) -> dict:
    """
    **EL ÚNICO LECTOR del perfil de empresa.** [D42c]

    Todo el sistema pasa por aquí: la búsqueda, el chat, las observaciones, la
    auditoría, el generador de oferta y la verificación de RUP. Antes había
    tres copias de esta lógica —aquí, en `gestor_documentos.py` y en
    `routers/generador_oferta.py`— y la pregunta «¿qué perfil está usando el
    sistema?» dependía de qué módulo la hiciera.

    ORDEN DE VERDAD, y no es arbitrario [I11]:

      1. `clientes/{cid}.json` — **la verdad.** Es lo que escribe
         `_save_perfil()` y lo que lee el evaluador del pipeline.
      2. caché local — copia derivada, para no tocar disco en cada petición.
      3. Supabase — copia derivada, para sobrevivir a un redespliegue.

    Si la verdad existe, se usa y se refresca la caché. Si sólo hay copia, se
    usa **y se avisa**: significa que el disco perdió el archivo o que el
    perfil viene de otro despliegue, y quien opera tiene que saberlo.
    """
    from pipeline.src.perfil import ruta_perfil_cliente

    verdad = ruta_perfil_cliente(cid)
    if verdad.exists():
        try:
            perfil = json.loads(verdad.read_text("utf-8"))
        except Exception as exc:
            logger.error("[PERFIL] %s ilegible: %s", verdad, exc)
        else:
            # La caché se deriva de la verdad, nunca al revés.
            try:
                cache = _cache_perfil(cid)
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(perfil, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
            except Exception:
                pass
            return perfil

    cache = _cache_perfil(cid)
    if cache.exists():
        try:
            perfil = json.loads(cache.read_text("utf-8"))
            logger.warning(
                "[PERFIL] '%s' no está en %s; se usa la caché. La copia "
                "sobrevivió a la verdad.", cid, verdad)
            return perfil
        except Exception:
            pass

    try:
        from supabase_client import sb_download
        data = sb_download(_sb_perfil_path(cid))
        if data:
            perfil = json.loads(data.decode("utf-8"))
            logger.warning("[PERFIL] '%s' recuperado de Supabase: no estaba "
                           "en disco ni en caché.", cid)
            cache.parent.mkdir(parents=True, exist_ok=True)
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(perfil, f, ensure_ascii=False, indent=2)
            return perfil
    except Exception as exc:
        logger.warning("[PERFIL] No se pudo cargar perfil de Supabase: %s", exc)

    return {}


def _ruta_perfil_pipeline(cid: str) -> Path:
    """La ruta de la verdad. Definida en `pipeline/src/perfil.py` [D42c]."""
    from pipeline.src.perfil import ruta_perfil_cliente
    return ruta_perfil_cliente(cid)


def _hay_supabase() -> bool:
    return bool(os.environ.get("SUPABASE_URL")
                and (os.environ.get("SUPABASE_KEY")
                     or os.environ.get("SUPABASE_SERVICE_KEY")))


def _save_perfil(cid: str, datos: dict) -> str | None:
    """
    Guarda el perfil en los tres sitios que lo necesitan y devuelve un aviso
    si algo quedó a medias.

    1. Caché local — rápido para la sesión actual.
    2. **`clientes/{cid}.json` — donde lo lee el PIPELINE.** Sin esto, editar
       el perfil en la interfaz no cambiaba nada del análisis: la interfaz
       escribía en un sitio y el evaluador leía otro, así que el veredicto no
       se movía al cambiar un dato. Dos almacenes para el mismo perfil es la
       misma divergencia de [G1-bis].
    3. Supabase Storage — persiste entre despliegues.

    **Sin Supabase configurado NO falla**: guarda en disco y devuelve un
    aviso. Antes lanzaba HTTP 500, así que en local no se podía guardar el
    perfil en absoluto. El aviso NO es opcional [principio 2: ningún fallo
    silencioso]: quien opera tiene que saber que ese perfil no sobrevive a un
    redespliegue.
    """
    cache = _cache_perfil(cid)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

    ruta_pipeline = _ruta_perfil_pipeline(cid)
    ruta_pipeline.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_pipeline, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

    if not _hay_supabase():
        logger.warning("[PERFIL] Supabase sin configurar: perfil de '%s' "
                       "guardado sólo en disco local", cid)
        return ("Guardado en este equipo. Supabase no está configurado, así "
                "que este perfil no sobrevive a un redespliegue.")

    try:
        from supabase_client import sb_upload
        sb_upload(_sb_perfil_path(cid), cache.read_bytes(), "application/json")
    except RuntimeError as exc:
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
    return None


# [D42a] Re-exportado desde el esquema canónico: vive allí porque es lógica
# pura y los tests del pipeline corren en un intérprete sin FastAPI.
from pipeline.src.perfil import cliente_id_activo  # noqa: E402,F401


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

    aviso = _save_perfil(cid, nuevo)
    # El aviso viaja a la respuesta, no sólo al log [principio 2]: quien opera
    # tiene que enterarse de que el perfil quedó sólo en este equipo.
    return {"ok": True, "cliente_id": cid, **({"aviso": aviso} if aviso else {})}


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


# ── Selector de perfil [D42a] ─────────────────────────────────────────────

class PerfilActivoBody(BaseModel):
    cid: str


@router.get("/perfiles")
def listar_perfiles(authorization: str = Header(None)):
    """
    Los perfiles de empresa guardados y cuál está activo.

    Existe porque el operador maneja varios: analizar con el perfil equivocado
    produce un informe correcto sobre la empresa que no es, y eso no se ve
    mirando el resultado.
    """
    from routers.auth import require_auth
    sesion = require_auth(authorization)
    from pipeline.src.perfil import perfiles_disponibles
    return {
        "perfiles": perfiles_disponibles(),
        "activo": cliente_id_activo(sesion),
        "cliente_sesion": sesion.get("cliente_id") or sesion.get("id") or "",
    }


@router.post("/perfil/activo")
def fijar_perfil_activo(body: PerfilActivoBody, authorization: str = Header(None)):
    """
    Fija el perfil de empresa con el que se va a buscar y analizar.

    Se guarda en la SESIÓN y no en el navegador: así la respuesta a «¿con qué
    perfil se hizo este análisis?» no depende de la pestaña que estuviera
    abierta [I11].
    """
    from routers.auth import require_auth
    require_auth(authorization)
    cid = (body.cid or "").strip()
    from pipeline.src.perfil import ruta_perfil_cliente
    if not cid or not ruta_perfil_cliente(cid).exists():
        raise HTTPException(
            status_code=404,
            detail=f"No hay perfil de empresa guardado para '{cid}'.")

    import sesiones as _sesiones
    token = (authorization or "").replace("Bearer ", "")
    datos = _sesiones.update_session(token, {"perfil_activo": cid})
    if datos is None:
        raise HTTPException(status_code=401, detail="Sesión expirada.")
    perfil = _load_perfil(cid) or {}
    return {
        "ok": True,
        "activo": cid,
        "nombre": perfil.get("nombre") or cid,
        "sector": perfil.get("sector") or "",
    }
