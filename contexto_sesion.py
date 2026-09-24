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
    pliego_sha256: str = "",
) -> None:
    """Guarda el contexto en memoria + /tmp + Supabase Storage."""
    datos = {
        "texto_pliego":       texto_pliego[:15_000],
        "textos_adicionales": textos_adicionales[:5_000],
        "fecha":              datetime.now().isoformat(),
    }
    if parametros_proceso:
        datos["parametros_proceso"] = parametros_proceso
    if pliego_sha256:
        datos["pliego_sha256"] = pliego_sha256
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
        print(f"[SESION] Contexto de '{cliente_id}' guardado en Supabase ({_sb_path(cliente_id)})")
    except Exception as exc:
        logger.warning("[SESION] No se pudo persistir contexto en Supabase: %s", exc)


def guardar_pliego_procesado(
    cliente_id: str,
    chunks: list,
    embeddings_list: list,
    hash_contenido: str,
) -> None:
    """
    Añade chunks y embeddings del pliego al contexto de sesión existente.
    No sobreescribe texto_pliego ni parametros_proceso — solo suma los campos de caché.
    Se guarda en memoria + /tmp + Supabase igual que el resto del contexto.
    """
    ctx = dict(contextos_sesion.get(cliente_id, {}))
    if not ctx:
        cache = _cache_path(cliente_id)
        if cache.exists():
            try:
                with open(cache, "r", encoding="utf-8") as f:
                    ctx = json.load(f)
            except Exception:
                ctx = {}

    ctx["chunks_pliego"]      = chunks
    ctx["embeddings_pliego"]  = embeddings_list
    ctx["hash_contenido"]     = hash_contenido
    ctx["fecha_procesado"]    = datetime.now().isoformat()

    contextos_sesion[cliente_id] = ctx

    try:
        cache = _cache_path(cliente_id)
        cache.parent.mkdir(parents=True, exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(ctx, f, ensure_ascii=False)
    except Exception as exc:
        logger.warning("[SESION] No se pudo escribir caché /tmp (chunks): %s", exc)

    try:
        from supabase_client import sb_upload
        sb_upload(
            _sb_path(cliente_id),
            json.dumps(ctx, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )
        print(
            f"[SESION] Pliego procesado de '{cliente_id}' guardado en Supabase "
            f"({len(chunks)} chunks, hash={hash_contenido[:8]})"
        )
    except Exception as exc:
        logger.warning("[SESION] No se pudo persistir chunks en Supabase: %s", exc)


def obtener_contexto_sesion(cliente_id: str) -> dict:
    """
    Retorna el contexto del pliego para el cliente.
    Busca en orden: memoria → /tmp → Supabase.
    """
    if not cliente_id:
        return {}

    # 1. Memoria (mismo proceso, más rápido)
    if cliente_id in contextos_sesion:
        print(f"[SESION] Contexto de '{cliente_id}' servido desde memoria")
        return contextos_sesion[cliente_id]

    # 2. Caché /tmp (mismo contenedor, entre requests)
    cache = _cache_path(cliente_id)
    if cache.exists():
        try:
            with open(cache, "r", encoding="utf-8") as f:
                datos = json.load(f)
            contextos_sesion[cliente_id] = datos   # repoblar memoria
            print(f"[SESION] Contexto de '{cliente_id}' servido desde /tmp")
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
            print(f"[SESION] Contexto de '{cliente_id}' servido desde Supabase (redeploy)")
            return datos
    except Exception as exc:
        logger.warning("[SESION] No se pudo recuperar contexto de Supabase: %s", exc)

    print(f"[SESION] Sin contexto para '{cliente_id}' en ninguna capa (memoria/tmp/Supabase)")
    return {}


FuenteContexto = str  # Literal: "pipeline" | "rag_clasico" | "sin_pliego"


def contexto_para_chat(cliente_id: str, query: str) -> tuple[str, FuenteContexto]:
    """
    Devuelve (fragmento, fuente) donde fuente declara la calidad del contexto:
      "pipeline"   — SHA + artefactos disponibles; chunks semánticos, 100% cobertura
      "rag_clasico"— pliego presente pero sin artefactos; RAG sobre primeros 15 000 chars
      "sin_pliego" — sin sesión o sin texto; el chat trabaja sin documento

    Prioridad del fragmento:
    1. Pipeline (artefactos.py): chunks semánticos con metadata de sección + bloque
       de requisitos habilitantes estructurado.
    2. RAG clásico (buscar_chunks_pliego_cacheados): embeddings sobre texto[:15_000].
    3. Texto directo: si el pliego cabe en _CHAT_RAG_THRESHOLD (no aplica RAG).

    El límite de 5 000 chars se mantiene en todos los caminos (control de costo).
    Siempre añade documentos adicionales al final (hasta 2 000 chars).
    """
    ctx = obtener_contexto_sesion(cliente_id)
    if not ctx:
        return "", "sin_pliego"

    texto       = ctx.get("texto_pliego", "")
    adicionales = ctx.get("textos_adicionales", "")
    sha256      = ctx.get("pliego_sha256", "")

    if not texto:
        return "", "sin_pliego"

    fragmento = ""
    fuente: FuenteContexto = "rag_clasico"

    # ── Camino 1: pipeline chunks ──────────────────────────────────────────
    if sha256:
        try:
            import sys, os
            _pipeline_src = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "pipeline"
            )
            if _pipeline_src not in sys.path:
                sys.path.insert(0, _pipeline_src)

            from src.artefactos import obtener_artefactos, chunks_relevantes, bloque_requisitos

            art = obtener_artefactos(sha256)
            if art:
                bloque_req = bloque_requisitos(art, solo_habilitantes=True, max_chars_total=3_000)
                presupuesto_chunks = _CHAT_RAG_THRESHOLD - len(bloque_req) - 200
                n_chunks = max(2, presupuesto_chunks // 1_200)
                top_chunks = chunks_relevantes(art, query, top_k=n_chunks, max_chars_por_chunk=1_200)

                partes_chunk = []
                chars_usados = 0
                for c in top_chunks:
                    t = c.get("texto", "")
                    if chars_usados + len(t) > presupuesto_chunks:
                        t = t[:presupuesto_chunks - chars_usados] + "…"
                    if t:
                        cap = c.get("metadata", {}).get("capitulo", "") or c.get("capitulo", "")
                        num = c.get("metadata", {}).get("numeral_derivado", "") or c.get("numeral_derivado", "")
                        meta = f"[{cap or ''}{' §' + num if num else ''}] " if (cap or num) else ""
                        partes_chunk.append(meta + t)
                        chars_usados += len(t)
                    if chars_usados >= presupuesto_chunks:
                        break

                if partes_chunk or bloque_req:
                    secciones = []
                    if bloque_req:
                        secciones.append(f"=== REQUISITOS HABILITANTES ===\n{bloque_req}")
                    if partes_chunk:
                        secciones.append("=== SECCIONES RELEVANTES ===\n" + "\n\n[...]\n\n".join(partes_chunk))
                    fragmento = "\n\n".join(secciones)
                    fuente = "pipeline"
                    logger.info(
                        "[CHAT-RAG] fuente=pipeline chunks=%d requisitos=%d fragmento=%d chars cliente=%s",
                        len(art.chunks), len(art.requisitos), len(fragmento), cliente_id,
                    )
        except Exception as exc:
            logger.warning("[CHAT-RAG] Pipeline chunks fallaron, usando RAG clásico: %s", exc)
            fragmento = ""

    # ── Camino 2: RAG clásico (fallback) ──────────────────────────────────
    if not fragmento:
        fuente = "rag_clasico"
        if len(texto) <= _CHAT_RAG_THRESHOLD:
            fragmento = texto
        else:
            try:
                from analizador import buscar_chunks_pliego_cacheados
                chunks_cl = buscar_chunks_pliego_cacheados(cliente_id, query, top_k=10)
                fragmento = "\n\n[...]\n\n".join(chunks_cl) if chunks_cl else texto[:_CHAT_RAG_THRESHOLD]
            except Exception:
                fragmento = texto[:_CHAT_RAG_THRESHOLD]
        logger.info(
            "[CHAT-RAG] fuente=rag_clasico fragmento=%d chars cliente=%s",
            len(fragmento), cliente_id,
        )

    if adicionales:
        fragmento += f"\n\n--- DOCUMENTOS ADICIONALES ---\n{adicionales[:2_000]}"

    return fragmento, fuente
