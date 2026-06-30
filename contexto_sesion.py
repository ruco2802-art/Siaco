# -*- coding: utf-8 -*-
"""
Almacén del texto extraído del pliego por cliente.
Compartido entre routers/auditoria.py, routers/chat.py y routers/observaciones.py.

Estrategia de persistencia (3 capas):
  1. dict en memoria  — acceso instantáneo en la misma sesión del proceso
  2. caché /tmp       — sobrevive entre requests del mismo contenedor
  3. Supabase Storage — persiste entre deploys y reinicios de Railway
"""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("siaco")

_CHAT_RAG_THRESHOLD = 5_000

# {cliente_id: {texto_pliego, textos_adicionales, fecha}}
contextos_sesion: dict[str, dict] = {}


def _cache_path(cliente_id: str) -> Path:
    return Path(f"/tmp/siaco/{cliente_id}/sesion/contexto.json")


def _sb_path(cliente_id: str) -> str:
    return f"clientes/{cliente_id}/sesion/contexto.json"


def guardar_contexto_sesion(
    cliente_id: str,
    texto_pliego: str,
    textos_adicionales: str = "",
    parametros_proceso: dict | None = None,
) -> None:
    """Guarda el contexto en memoria + /tmp + Supabase Storage."""
    datos = {
        "texto_pliego":       texto_pliego[:15_000],
        "textos_adicionales": textos_adicionales[:5_000],
        "fecha":              datetime.now().isoformat(),
    }
    if parametros_proceso:
        datos["parametros_proceso"] = parametros_proceso
    # 1. Memoria
    contextos_sesion[cliente_id] = datos

    # 2. Caché /tmp
    try:
        cache = _cache_path(cliente_id)
        cache.parent.mkdir(parents=True, exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
    except Exception as exc:
        logger.warning("[SESION] No se pudo escribir caché /tmp: %s", exc)

    # 3. Supabase (no fatal: el análisis ya terminó, no queremos romper el flujo)
    try:
        from supabase_client import sb_upload
        sb_upload(
            _sb_path(cliente_id),
            json.dumps(datos, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )
    except Exception as exc:
        logger.warning("[SESION] No se pudo persistir contexto en Supabase: %s", exc)


def obtener_contexto_sesion(cliente_id: str) -> dict:
    """
    Retorna el contexto del pliego para el cliente.
    Busca en orden: memoria → /tmp → Supabase.
    """
    if not cliente_id:
        return {}

    # 1. Memoria (mismo proceso, más rápido)
    if cliente_id in contextos_sesion:
        return contextos_sesion[cliente_id]

    # 2. Caché /tmp (mismo contenedor, entre requests)
    cache = _cache_path(cliente_id)
    if cache.exists():
        try:
            with open(cache, "r", encoding="utf-8") as f:
                datos = json.load(f)
            contextos_sesion[cliente_id] = datos   # repoblar memoria
            return datos
        except Exception:
            pass

    # 3. Supabase (tras un redeploy de Railway)
    try:
        from supabase_client import sb_download
        raw = sb_download(_sb_path(cliente_id))
        if raw:
            datos = json.loads(raw.decode("utf-8"))
            contextos_sesion[cliente_id] = datos   # repoblar memoria y /tmp
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(raw)
            except Exception:
                pass
            return datos
    except Exception as exc:
        logger.warning("[SESION] No se pudo recuperar contexto de Supabase: %s", exc)

    return {}


def contexto_para_chat(cliente_id: str, query: str) -> str:
    """
    Devuelve el fragmento de pliego más relevante para la query del chat.
    - Si el pliego es corto (<= 5 000 chars): lo devuelve completo.
    - Si es largo: aplica RAG con la query del usuario (top-2 por sub-query).
    Siempre añade los documentos adicionales al final (hasta 2 000 chars).
    Devuelve cadena vacía si no hay pliego guardado para el cliente.
    """
    ctx = obtener_contexto_sesion(cliente_id)
    if not ctx:
        return ""

    texto       = ctx.get("texto_pliego", "")
    adicionales = ctx.get("textos_adicionales", "")

    if not texto:
        return ""

    if len(texto) <= _CHAT_RAG_THRESHOLD:
        fragmento = texto
    else:
        try:
            from analizador import chunking_rag_pliego
            fragmento = chunking_rag_pliego(texto, query=query, top_k_por_query=2)
        except Exception:
            fragmento = texto[:_CHAT_RAG_THRESHOLD]

    if adicionales:
        fragmento += f"\n\n--- DOCUMENTOS ADICIONALES ---\n{adicionales[:2_000]}"

    return fragmento
