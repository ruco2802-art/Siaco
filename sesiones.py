# -*- coding: utf-8 -*-
"""Sesiones persistentes en archivo — SIACO v3.0"""
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

_SESSIONS_FILE = Path("sesiones.json")
SESSION_TTL_DAYS = 7
_lock = threading.Lock()
_cache: dict[str, dict] = {}
_loaded = False


def _now() -> datetime:
    return datetime.utcnow()


def _is_expired(entry: dict) -> bool:
    try:
        return _now() > datetime.fromisoformat(entry["expires_at"])
    except Exception:
        return True


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


def _bootstrap():
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        raw = _read_file()
        clean = {k: v for k, v in raw.items() if not _is_expired(v)}
        _cache.update(clean)
        if len(clean) < len(raw):
            _write_file(clean)
        _loaded = True


def create_session(data: dict) -> str:
    """Crea sesión, la persiste en disco y retorna el token."""
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
    return token


def get_session(token: str) -> dict | None:
    """Retorna datos de la sesión o None si expirada/inexistente."""
    _bootstrap()
    entry = _cache.get(token)
    if not entry:
        with _lock:
            raw = _read_file()
            entry = raw.get(token)
            if entry:
                _cache[token] = entry
    if not entry or _is_expired(entry):
        if entry:
            delete_session(token)
        return None
    return entry["data"]


def delete_session(token: str):
    """Elimina sesión del cache y del disco."""
    _cache.pop(token, None)
    with _lock:
        raw = _read_file()
        raw.pop(token, None)
        _write_file(raw)
