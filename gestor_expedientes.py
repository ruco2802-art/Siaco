# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta
from pathlib import Path

ESTADOS_INTERNOS = [
    "En seguimiento",
    "Documentación en preparación",
    "Oferta enviada",
    "Adjudicado",
    "No adjudicado",
    "Descartado",
]


def agregar_expediente(cliente_id: str, contrato_data: dict, score_viabilidad: int) -> dict:
    """Agrega un proceso al expediente del cliente si no existe ya."""
    ruta = Path(f"./clientes/{cliente_id}/expedientes.json")
    ruta.parent.mkdir(parents=True, exist_ok=True)

    expedientes = []
    if ruta.exists():
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                expedientes = json.load(f)
        except Exception:
            expedientes = []

    proceso_id = (
        contrato_data.get("id_del_proceso")
        or contrato_data.get("referencia_del_proceso")
        or ""
    )
    if any(e.get("proceso_id") == proceso_id for e in expedientes):
        return {"ok": False, "error": "El proceso ya está en expedientes"}

    url_data = contrato_data.get("urlproceso", {})
    url_final = (url_data.get("url") if isinstance(url_data, dict) else url_data) or ""

    expediente = {
        "proceso_id": proceso_id,
        "nombre": contrato_data.get("nombre_del_procedimiento", ""),
        "entidad": contrato_data.get("entidad", ""),
        "valor": contrato_data.get("precio_base", 0),
        "fase_secop": contrato_data.get("fase", ""),
        "estado_interno": "En seguimiento",
        "score_viabilidad": score_viabilidad,
        "fecha_manifestacion": contrato_data.get("fecha_limite_manifestacion_interes", ""),
        "fecha_cierre_oferta": (
            contrato_data.get("fecha_limite_recepcion_ofertas")
            or contrato_data.get("fecha_de_recepcion_de", "")
        ),
        "fecha_agregado": datetime.now().isoformat(),
        "url": url_final,
    }

    expedientes.append(expediente)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(expedientes, f, ensure_ascii=False, indent=2)
    return {"ok": True, "proceso_id": proceso_id}


def actualizar_estado(cliente_id: str, proceso_id: str, nuevo_estado: str) -> bool:
    """Actualiza estado_interno de un expediente."""
    ruta = Path(f"./clientes/{cliente_id}/expedientes.json")
    if not ruta.exists():
        return False
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            expedientes = json.load(f)
        for e in expedientes:
            if e.get("proceso_id") == proceso_id:
                e["estado_interno"] = nuevo_estado
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(expedientes, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def calcular_urgencia(fecha_manifestacion: str, fecha_cierre: str) -> dict:
    """Retorna nivel rojo/amarillo/verde y días restantes."""
    now = datetime.now()

    def _parse_fecha(s):
        if not s:
            return None
        try:
            s_limpio = s.replace("Z", "").split("+")[0].strip()
            return datetime.fromisoformat(s_limpio)
        except Exception:
            return None

    dt_manif = _parse_fecha(fecha_manifestacion)
    dt_cierre = _parse_fecha(fecha_cierre)

    dias_manif = int((dt_manif - now).total_seconds() / 86400) if dt_manif else None
    dias_cierre = int((dt_cierre - now).total_seconds() / 86400) if dt_cierre else None

    dias_ref = dias_manif if dias_manif is not None else dias_cierre
    if dias_ref is None:
        nivel = "verde"
    elif dias_ref < 1:
        nivel = "rojo"
    elif dias_ref < 3:
        nivel = "amarillo"
    else:
        nivel = "verde"

    return {"nivel": nivel, "dias_manif": dias_manif, "dias_cierre": dias_cierre}


def listar_expedientes(cliente_id: str, filtro_estado: str = None) -> list:
    """Lista expedientes enriquecidos con urgencia, ordenados rojo→amarillo→verde."""
    ruta = Path(f"./clientes/{cliente_id}/expedientes.json")
    if not ruta.exists():
        return []
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            expedientes = json.load(f)
    except Exception:
        return []

    if filtro_estado:
        expedientes = [e for e in expedientes if e.get("estado_interno") == filtro_estado]

    orden = {"rojo": 0, "amarillo": 1, "verde": 2}
    for e in expedientes:
        e["urgencia"] = calcular_urgencia(
            e.get("fecha_manifestacion", ""), e.get("fecha_cierre_oferta", "")
        )

    expedientes.sort(key=lambda x: orden.get(x["urgencia"]["nivel"], 3))
    return expedientes
