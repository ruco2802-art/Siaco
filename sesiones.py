# -*- coding: utf-8 -*-
"""Sesiones persistentes — SIACO v3.1

Estrategia de persistencia (3 capas, igual que contexto_sesion.py):
  1. dict en memoria  — acceso instantáneo en la misma ejecución del proceso
  2. sesiones.json en disco — sobrevive entre requests del mismo contenedor
  3. Supabase Storage  — sobrevive entre deploys y reinicios de Railway
"""
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
import logging

logger = logging.getLogger("siaco")

_SESSIONS_FILE  = Path("sesiones.json")
_SUPABASE_PATH  = "sesiones/sesiones.json"
SESSION_TTL_DAYS = 7

_lock   = threading.Lock()
_cache: dict[str, dict] = {}
_loaded = False


def _now() -> datetime:
    return datetime.utcnow()


def _is_expired(entry: dict) -> bool:
    try:
        return _now() > datetime.fromisoformat(entry["expires_at"])
    except Exception:
        return True


# ── Disco local ────────────────────────────────────────────────────────────────

def _read_file() -> dict:
    try:
        with open(_SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_file(data: dict):
    try:
        with open(_SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── Supabase ───────────────────────────────────────────────────────────────────

def _read_supabase() -> dict:
    """Carga sesiones desde Supabase Storage. Retorna {} si no existe o falla."""
    try:
        from supabase_client import sb_download
        data = sb_download(_SUPABASE_PATH)
        if data:
            return json.loads(data.decode("utf-8"))
    except Exception as exc:
        logger.debug("[SESION] No se pudo leer sesiones desde Supabase: %s", exc)
    return {}


def _write_supabase(data: dict):
    """Persiste sesiones en Supabase Storage (best-effort, no bloquea)."""
    try:
        from supabase_client import sb_upload
        sb_upload(
            _SUPABASE_PATH,
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
        )
    except Exception as exc:
        logger.warning("[SESION] No se pudo persistir sesiones en Supabase: %s", exc)


# ── Bootstrap ──────────────────────────────────────────────────────────────────

def _bootstrap():
    """
    Carga las sesiones vigentes al iniciar el proceso (una sola vez).
    Orden: disco local → Supabase (si el disco está vacío, ej. tras un redeploy).
    """
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        raw = _read_file()
        if not raw:
            # Redeploy — intentar recuperar desde Supabase
            raw = _read_supabase()
            if raw:
                print(f"[SESION] Bootstrap: {len(raw)} sesiones restauradas desde Supabase")
                _write_file(raw)   # poblar disco para el nuevo contenedor
        clean = {k: v for k, v in raw.items() if not _is_expired(v)}
        _cache.update(clean)
        if len(clean) < len(raw):
            _write_file(clean)
            _write_supabase(clean)
        _loaded = True


# ── API pública ────────────────────────────────────────────────────────────────

def create_session(data: dict) -> str:
    """Crea sesión de 7 días, la persiste en disco + Supabase y retorna el token."""
    import uuid
    _bootstrap()
    token = str(uuid.uuid4())
    entry = {
        "data": data,
        "expires_at": (_now() + timedelta(days=SESSION_TTL_DAYS)).isoformat(),
    }
    with _lock:
        _cache[token] = entry
        raw = _read_file()
        raw = {k: v for k, v in raw.items() if not _is_expired(v)}
        raw[token] = entry
        _write_file(raw)
        _write_supabase(raw)
    return token


def get_session(token: str) -> dict | None:
    """
    Retorna datos de la sesión o None si expirada/inexistente.
    Imprime diagnóstico cuando rechaza un token para facilitar debug.
    """
    _bootstrap()
    entry = _cache.get(token)
    if not entry:
        with _lock:
            raw = _read_file()
            entry = raw.get(token)
            if entry:
                _cache[token] = entry

    if not entry:
        # Token no encontrado ni en memoria ni en disco — probable redeploy
        print(
            f"[SESION] Token no encontrado en memoria ni en disco. "
            "Si el usuario acaba de hacer login esto es normal. "
            "Si fue durante uso activo, un redeploy borro sesiones.json sin Supabase backup."
        )
        return None

    if _is_expired(entry):
        try:
            expires_at = entry.get("expires_at", "unknown")
            now_iso    = _now().isoformat()
            delta_days = (
                (_now() - datetime.fromisoformat(expires_at)).total_seconds() / 86400
            )
            print(
                f"[SESION] Token rechazado — expirado hace {delta_days:.2f} días "
                f"| expires_at={expires_at} | now={now_iso}"
            )
        except Exception:
            print("[SESION] Token rechazado — error calculando antigüedad")
        delete_session(token)
        return None

    return entry["data"]


def delete_session(token: str):
    """Elimina sesión de memoria, disco y Supabase."""
    _cache.pop(token, None)
    with _lock:
        raw = _read_file()
        raw.pop(token, None)
        _write_file(raw)
        _write_supabase(raw)
