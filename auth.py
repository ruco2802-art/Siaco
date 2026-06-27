# -*- coding: utf-8 -*-
import hashlib
import secrets
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=False)  # Railway env vars tienen prioridad sobre .env local

ADMIN_KEY = os.getenv("ADMIN_KEY", "siaco_admin_2026")


def generar_hash(password: str, salt: str = None):
    """Genera hash SHA-256 con salt. Retorna (hash, salt)."""
    if salt is None:
        salt = secrets.token_hex(32)
    hash_val = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return hash_val, salt


_USOS_PREMIUM_DEFAULT = {
    "descargar_pdf_analisis": False,
    "descargar_pdf_observaciones": False,
    "analisis_competencia": False,
    "notificaciones": False,
    "subir_documentos": False,
}


def crear_cliente(
    cliente_id: str,
    password: str,
    plan: str = "básico",
    tipo: str = "cliente",
    dias_acceso: int = 30,
) -> dict:
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
    vencimiento = (datetime.now() + timedelta(days=dias_acceso)).isoformat()

    credenciales = {
        "cliente_id": cliente_id,
        "hash": hash_val,
        "salt": salt,
        "plan": plan,
        "tipo": tipo,
        "activo": True,
        "fecha_creacion": ahora,
        "fecha_vencimiento": vencimiento,
    }
    if tipo == "tester":
        credenciales["usos_premium"] = dict(_USOS_PREMIUM_DEFAULT)

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

    return {"ok": True, "cliente_id": cliente_id, "plan": plan, "tipo": tipo}


def verificar_credenciales(username: str, password: str):
    """
    Verifica credenciales de un usuario.
    Retorna dict con datos del cliente si válido.
    Retorna {"_bloqueado": True, "_mensaje": "..."} si cuenta expirada.
    Retorna None si credenciales inválidas.
    Caso especial: username "admin" + password == ADMIN_KEY → retorna perfil admin.
    """
    if username == "admin":
        if password == ADMIN_KEY:
            return {
                "id": "admin", "nombre": "Administrador SIACO",
                "plan": "admin", "tipo": "admin", "perfil_json": {},
            }
        return None

    ruta_cred  = Path(f"./clientes/{username}/credenciales.json")
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

    tipo = cred.get("tipo", "cliente")

    # Verificar vencimiento
    try:
        fecha_venc = datetime.fromisoformat(cred["fecha_vencimiento"])
        if datetime.now() > fecha_venc:
            if tipo == "tester":
                return {
                    "_bloqueado": True,
                    "_mensaje": "Su acceso de prueba ha vencido. Contáctenos para continuar.",
                    "_whatsapp": "573138343997",
                }
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

    resultado = {
        "id": username,
        "nombre": perfil.get("nombre", username),
        "plan": cred.get("plan", "básico"),
        "tipo": tipo,
        "perfil_json": perfil,
    }

    if tipo == "tester":
        resultado["usos_premium"] = cred.get("usos_premium", dict(_USOS_PREMIUM_DEFAULT))
        try:
            fv = datetime.fromisoformat(cred["fecha_vencimiento"])
            resultado["dias_restantes"] = max(0, (fv - datetime.now()).days)
        except Exception:
            resultado["dias_restantes"] = 0

    return resultado


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

            tipo = cred.get("tipo", "cliente")
            entrada = {
                "cliente_id": cred["cliente_id"],
                "nombre": perfil.get("nombre", cred["cliente_id"]),
                "plan": cred.get("plan", "básico"),
                "tipo": tipo,
                "activo": cred.get("activo", False),
                "fecha_creacion": cred.get("fecha_creacion", ""),
                "fecha_vencimiento": cred.get("fecha_vencimiento", ""),
            }
            if tipo == "tester":
                entrada["usos_premium"] = cred.get("usos_premium", dict(_USOS_PREMIUM_DEFAULT))
                try:
                    fv = datetime.fromisoformat(cred["fecha_vencimiento"])
                    entrada["dias_restantes"] = max(0, (fv - datetime.now()).days)
                except Exception:
                    entrada["dias_restantes"] = 0

            clientes.append(entrada)
        except Exception:
            continue
    return clientes


def actualizar_usos_premium(cliente_id: str, feature: str) -> str:
    """
    Marca una función premium como usada por el tester.
    Retorna: 'ok' (primera vez), 'ya_usado', 'no_aplica' (no es tester o feature inválida).
    """
    ruta_cred = Path(f"./clientes/{cliente_id}/credenciales.json")
    if not ruta_cred.exists():
        return "no_aplica"
    try:
        with open(ruta_cred, "r", encoding="utf-8") as f:
            cred = json.load(f)
        if cred.get("tipo") != "tester":
            return "no_aplica"
        usos = cred.get("usos_premium", {})
        if feature not in usos:
            return "no_aplica"
        if usos[feature]:
            return "ya_usado"
        usos[feature] = True
        cred["usos_premium"] = usos
        with open(ruta_cred, "w", encoding="utf-8") as f:
            json.dump(cred, f, ensure_ascii=False, indent=2)
        return "ok"
    except Exception:
        return "no_aplica"


def extender_acceso(cliente_id: str, dias: int = 7) -> bool:
    """Extiende la fecha de vencimiento del tester en X días desde hoy."""
    ruta_cred = Path(f"./clientes/{cliente_id}/credenciales.json")
    if not ruta_cred.exists():
        return False
    try:
        with open(ruta_cred, "r", encoding="utf-8") as f:
            cred = json.load(f)
        try:
            base = max(datetime.now(), datetime.fromisoformat(cred.get("fecha_vencimiento", "")))
        except Exception:
            base = datetime.now()
        cred["fecha_vencimiento"] = (base + timedelta(days=dias)).isoformat()
        with open(ruta_cred, "w", encoding="utf-8") as f:
            json.dump(cred, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def convertir_a_cliente(cliente_id: str) -> bool:
    """Convierte un tester a cliente: elimina restricciones y extiende acceso."""
    ruta_cred = Path(f"./clientes/{cliente_id}/credenciales.json")
    if not ruta_cred.exists():
        return False
    try:
        with open(ruta_cred, "r", encoding="utf-8") as f:
            cred = json.load(f)
        cred["tipo"] = "cliente"
        cred["fecha_vencimiento"] = (datetime.now() + timedelta(days=3650)).isoformat()
        cred.pop("usos_premium", None)
        with open(ruta_cred, "w", encoding="utf-8") as f:
            json.dump(cred, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


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
