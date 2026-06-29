# -*- coding: utf-8 -*-
"""
Cliente singleton de Supabase Storage para SIACO.

Variables de entorno requeridas:
  SUPABASE_URL  — URL del proyecto Supabase (ej. https://xxxx.supabase.co)
  SUPABASE_KEY  — service_role key (no la anon key)

Bucket:  siaco-documentos
"""
import logging
import os

logger = logging.getLogger("siaco")

BUCKET = "siaco-documentos"

_client = None  # tipo: supabase.Client


def get_supabase():
    """Retorna el cliente Supabase (inicialización perezosa al primer uso)."""
    global _client
    if _client is None:
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL y SUPABASE_KEY deben configurarse en variables de entorno."
            )
        _client = create_client(url, key)
    return _client


def sb_upload(path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """
    Sube bytes a Supabase Storage con upsert (sobreescribe si existe).
    Lanza excepción si la operación falla — el llamador decide si es fatal.
    """
    sb = get_supabase()
    storage = sb.storage.from_(BUCKET)
    try:
        storage.upload(path, data, {"content-type": content_type, "x-upsert": "true"})
    except Exception as primary_exc:
        # Compatibilidad con versiones del SDK que no soportan x-upsert:
        # intentar eliminar el archivo y volver a subir.
        if any(w in str(primary_exc).lower() for w in ("already", "duplicate", "exists", "409")):
            try:
                storage.remove([path])
            except Exception:
                pass
            storage.upload(path, data, {"content-type": content_type})
        else:
            raise primary_exc


def sb_download(path: str) -> bytes | None:
    """
    Descarga bytes desde Supabase Storage.
    Retorna None si el archivo no existe o hay error de red.
    """
    try:
        sb = get_supabase()
        return bytes(sb.storage.from_(BUCKET).download(path))
    except Exception as exc:
        logger.debug("[SUPABASE] Archivo no encontrado o error: %s — %s", path, exc)
        return None
