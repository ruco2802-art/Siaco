# -*- coding: utf-8 -*-
import hashlib
import secrets
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

ADMIN_KEY = os.getenv("ADMIN_KEY", "siaco_admin_2026")


def generar_hash(password: str, salt: str = None):
    """Genera hash SHA-256 con salt. Retorna (hash, salt)."""
    if salt is None:
        salt = secrets.token_hex(32)
    hash_val = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return hash_val, salt


def crear_cliente(cliente_id: str, password: str, plan: str = "básico", dias_vigencia: int = 30) -> dict:
    """Crea estructura de carpetas y archivos para un nuevo cliente."""
    base = Path(f"./clientes/{cliente_id}")
    for subdir in [
        "documentos/rup",
        "documentos/experiencia",
        "documentos/financieros",
        "documentos/juridicos",
        "embeddings",
        "historial",
    ]:
        (base / subdir).mkdir(parents=True, exist_ok=True)

    hash_val, salt = generar_hash(password)
    ahora = datetime.now().isoformat()
    vencimiento = (datetime.now() + timedelta(days=dias_vigencia)).isoformat()

    credenciales = {
        "cliente_id": cliente_id,
        "hash": hash_val,
        "salt": salt,
        "plan": plan,
        "activo": True,
        "fecha_creacion": ahora,
        "fecha_vencimiento": vencimiento,
    }
    perfil = {
        "cliente_id": cliente_id,
        "nombre": cliente_id,
        "plan": plan,
        "fecha_creacion": ahora,
        "notificacion": "whatsapp",
        "contacto_whatsapp": "",
        "contacto_email": "",
        "fecha_vencimiento_rup": "",
    }

    with open(base / "credenciales.json", "w", encoding="utf-8") as f:
        json.dump(credenciales, f, ensure_ascii=False, indent=2)
    with open(base / "perfil.json", "w", encoding="utf-8") as f:
        json.dump(perfil, f, ensure_ascii=False, indent=2)
    with open(base / "historial/licitaciones.json", "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(base / "expedientes.json", "w", encoding="utf-8") as f:
        json.dump([], f)

    return {"ok": True, "cliente_id": cliente_id, "plan": plan}


def verificar_credenciales(username: str, password: str):
    """
    Verifica credenciales de un usuario.
    Retorna dict con {id, nombre, plan, perfil_json} si válido, None si no.
    Caso especial: username "admin" + password == ADMIN_KEY → retorna perfil admin.
    """
    # Caso admin
    if username == "admin":
        if password == ADMIN_KEY:
            return {"id": "admin", "nombre": "Administrador SIACO", "plan": "admin", "perfil_json": {}}
        return None

    ruta_cred = Path(f"./clientes/{username}/credenciales.json")
    ruta_perfil = Path(f"./clientes/{username}/perfil.json")

    if not ruta_cred.exists():
        return None

    try:
        with open(ruta_cred, "r", encoding="utf-8") as f:
            cred = json.load(f)
    except Exception:
        return None

    if not cred.get("activo", False):
        return None

    try:
        fecha_venc = datetime.fromisoformat(cred["fecha_vencimiento"])
        if datetime.now() > fecha_venc:
            return None
    except Exception:
        pass

    hash_calc, _ = generar_hash(password, cred["salt"])
    if hash_calc != cred["hash"]:
        return None

    perfil = {}
    if ruta_perfil.exists():
        try:
            with open(ruta_perfil, "r", encoding="utf-8") as f:
                perfil = json.load(f)
        except Exception:
            pass

    return {
        "id": username,
        "nombre": perfil.get("nombre", username),
        "plan": cred.get("plan", "básico"),
        "perfil_json": perfil,
    }


def listar_clientes_activos() -> list:
    """Lista todos los clientes para el panel admin."""
    ruta_base = Path("./clientes")
    if not ruta_base.exists():
        return []

    clientes = []
    for carpeta in sorted(ruta_base.iterdir()):
        if not carpeta.is_dir():
            continue
        ruta_cred = carpeta / "credenciales.json"
        if not ruta_cred.exists():
            continue
        try:
            with open(ruta_cred, "r", encoding="utf-8") as f:
                cred = json.load(f)
            perfil = {}
            ruta_p = carpeta / "perfil.json"
            if ruta_p.exists():
                with open(ruta_p, "r", encoding="utf-8") as f:
                    perfil = json.load(f)
            clientes.append({
                "cliente_id": cred["cliente_id"],
                "nombre": perfil.get("nombre", cred["cliente_id"]),
                "plan": cred.get("plan", "básico"),
                "activo": cred.get("activo", False),
                "fecha_creacion": cred.get("fecha_creacion", ""),
                "fecha_vencimiento": cred.get("fecha_vencimiento", ""),
            })
        except Exception:
            continue
    return clientes


def generar_nueva_password(cliente_id: str):
    """Regenera contraseña. Retorna nueva password en texto plano o None si falla."""
    ruta_cred = Path(f"./clientes/{cliente_id}/credenciales.json")
    if not ruta_cred.exists():
        return None
    nueva = secrets.token_urlsafe(12)
    hash_val, salt = generar_hash(nueva)
    try:
        with open(ruta_cred, "r", encoding="utf-8") as f:
            cred = json.load(f)
        cred["hash"] = hash_val
        cred["salt"] = salt
        with open(ruta_cred, "w", encoding="utf-8") as f:
            json.dump(cred, f, ensure_ascii=False, indent=2)
        return nueva
    except Exception:
        return None


def desactivar_cliente(cliente_id: str) -> bool:
    """Desactiva un cliente."""
    ruta_cred = Path(f"./clientes/{cliente_id}/credenciales.json")
    if not ruta_cred.exists():
        return False
    try:
        with open(ruta_cred, "r", encoding="utf-8") as f:
            cred = json.load(f)
        cred["activo"] = False
        with open(ruta_cred, "w", encoding="utf-8") as f:
            json.dump(cred, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def guardar_perfil(cliente_id: str, perfil: dict) -> bool:
    """Actualiza perfil.json del cliente."""
    ruta = Path(f"./clientes/{cliente_id}/perfil.json")
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(perfil, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
