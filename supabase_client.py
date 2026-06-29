# -*- coding: utf-8 -*-
"""
Cliente de Supabase Storage para SIACO — implementado sobre requests.
No usa el SDK supabase-py para evitar conflictos de dependencias con httpx.

Variables de entorno requeridas:
  SUPABASE_URL  — URL del proyecto (ej. https://xxxx.supabase.co)
  SUPABASE_KEY  — service_role key (NO la anon key)

Bucket:  siaco-documentos
API ref: https://supabase.com/docs/reference/javascript/storage-from-upload
"""
import logging
import os

import requests

logger = logging.getLogger("siaco")

BUCKET = "siaco-documentos"


def _base_url() -> str:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("SUPABASE_URL debe configurarse en variables de entorno.")
    return f"{url}/storage/v1/object/{BUCKET}"


def _headers(extra: dict | None = None) -> dict:
    key = os.environ.get("SUPABASE_KEY", "")
    if not key:
        raise RuntimeError("SUPABASE_KEY debe configurarse en variables de entorno.")
    h = {
        "Authorization": f"Bearer {key}",
        "apikey": key,          # Supabase exige este header además del Authorization
    }
    if extra:
        h.update(extra)
    return h


def sb_upload(path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """
    Sube bytes a Supabase Storage con upsert (sobreescribe si existe).
    Lanza excepción si la operación falla.

    Usa PUT /storage/v1/object/{bucket}/{path}?upsert=true
    """
    url = f"{_base_url()}/{path}"
    logger.info("[SUPABASE] POST %s", url)
    resp = requests.post(
        url,
        data=data,
        headers=_headers({"Content-Type": content_type, "x-upsert": "true"}),
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Supabase upload falló [{resp.status_code}] URL={url} : {resp.text[:300]}"
        )


def sb_download(path: str) -> bytes | None:
    """
    Descarga bytes desde Supabase Storage.
    Retorna None si el archivo no existe (404) o hay error de red.
    """
    try:
        url = f"{_base_url()}/{path}"
        resp = requests.get(url, headers=_headers(), timeout=30)
        if resp.status_code == 404:
            return None
        if not resp.ok:
            logger.warning(
                "[SUPABASE] Download error [%s] %s: %s",
                resp.status_code, path, resp.text[:200],
            )
            return None
        return resp.content
    except Exception as exc:
        logger.debug("[SUPABASE] Download excepción: %s — %s", path, exc)
        return None
