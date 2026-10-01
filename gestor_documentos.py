# -*- coding: utf-8 -*-
import json
import logging
import numpy as np
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("siaco")

TIPOS_DOCUMENTO = [
    "RUP",
    "Certificado de experiencia",
    "Estado financiero",
    "Cámara de comercio",
    "Poder de representación",
    "Otro",
]


def _extraer_texto_bytes(archivo_bytes: bytes, filename: str) -> str:
    """Extrae texto de PDF (con fallback OCR Tesseract) o DOCX."""
    nombre_lower = filename.lower()
    texto = ""

    if nombre_lower.endswith(".pdf"):
        try:
            import fitz
            doc = fitz.open(stream=archivo_bytes, filetype="pdf")
            partes = []
            for pagina in doc:
                t = pagina.get_text()
                if len(t.strip()) < 100:
                    try:
                        import pytesseract
                        from PIL import Image
                        import io
                        if __import__("sys").platform == "win32":
                            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
                        pix = pagina.get_pixmap(matrix=fitz.Matrix(2, 2))
                        img = Image.open(io.BytesIO(pix.tobytes("png")))
                        t = pytesseract.image_to_string(img, lang="spa")
                    except Exception:
                        pass
                partes.append(t)
            texto = "\n".join(partes)
        except Exception as e:
            texto = f"[Error extrayendo PDF: {e}]"

    elif nombre_lower.endswith(".docx"):
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(archivo_bytes))
            texto = "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            texto = f"[Error extrayendo DOCX: {e}]"

    return texto


def _chunkear(texto: str, tamano: int = 500, overlap: int = 100) -> list:
    """Divide texto en chunks con overlap."""
    texto = texto.strip()
    if len(texto) <= tamano:
        return [texto] if texto else []
    chunks = []
    inicio = 0
    while inicio < len(texto):
        chunk = texto[inicio : inicio + tamano].strip()
        if chunk:
            chunks.append(chunk)
        inicio += tamano - overlap
    return chunks


# ── Almacenamiento: caché local /tmp + Supabase Storage ──────────────────────
#
# Estrategia:
#   - Escritura: guardar en /tmp (rápido) + subir a Supabase (persistente)
#   - Lectura:   leer desde /tmp si existe; si no, descargar desde Supabase
#   - /tmp sobrevive entre requests del mismo contenedor pero no entre deploys.
#   - Supabase persiste entre deploys.

def _cache_meta(cliente_id: str) -> Path:
    return Path(f"/tmp/siaco/{cliente_id}/embeddings/documentos_meta.json")


def _cache_emb(cliente_id: str) -> Path:
    return Path(f"/tmp/siaco/{cliente_id}/embeddings/documentos_emb.npy")


def _sb_meta(cid: str) -> str:
    return f"clientes/{cid}/embeddings/documentos_meta.json"


def _sb_emb(cid: str) -> str:
    return f"clientes/{cid}/embeddings/documentos_emb.npy"


def _cargar_indice(cliente_id: str) -> list:
    """
    Carga el índice de documentos.
    1. Busca en caché local /tmp (mismo contenedor — rápido).
    2. Si no existe, descarga desde Supabase (después de un redeploy).
    """
    if not cliente_id or cliente_id == "admin":
        # El usuario admin no tiene carpeta de documentos propia — evita
        # ruido de errores 400 de Supabase al intentar descargar algo que no existe.
        return []

    cache_meta = _cache_meta(cliente_id)
    cache_emb  = _cache_emb(cliente_id)

    if not cache_meta.exists() or not cache_emb.exists():
        try:
            from supabase_client import sb_download
            meta_bytes = sb_download(_sb_meta(cliente_id))
            emb_bytes  = sb_download(_sb_emb(cliente_id))
            if meta_bytes and emb_bytes:
                cache_meta.parent.mkdir(parents=True, exist_ok=True)
                cache_meta.write_bytes(meta_bytes)
                cache_emb.write_bytes(emb_bytes)
        except Exception as exc:
            logger.warning("[DOCUMENTOS] No se pudo descargar índice de Supabase: %s", exc)

    if not cache_meta.exists() or not cache_emb.exists():
        return []

    try:
        with open(cache_meta, "r", encoding="utf-8") as f:
            meta = json.load(f)
        embs = np.load(str(cache_emb), allow_pickle=False)
        if len(meta) != len(embs):
            return []
        return [{**m, "embedding": embs[i]} for i, m in enumerate(meta)]
    except Exception:
        return []


def _guardar_indice(cliente_id: str, indice: list) -> None:
    """
    Persiste el índice:
    1. En caché local /tmp (rápido para la sesión actual).
    2. En Supabase Storage (persistente entre deploys).
    Lanza excepción si Supabase falla, para que el llamador retorne HTTP 500.
    """
    cache_meta = _cache_meta(cliente_id)
    cache_emb  = _cache_emb(cliente_id)
    cache_meta.parent.mkdir(parents=True, exist_ok=True)

    meta_sin_emb = [{k: v for k, v in e.items() if k != "embedding"} for e in indice]
    embs = np.array([e["embedding"] for e in indice]) if indice else np.empty((0,))

    with open(cache_meta, "w", encoding="utf-8") as f:
        json.dump(meta_sin_emb, f, ensure_ascii=False)
    np.save(str(cache_emb), embs)

    from supabase_client import sb_upload
    sb_upload(_sb_meta(cliente_id), cache_meta.read_bytes(), "application/json")
    sb_upload(_sb_emb(cliente_id), cache_emb.read_bytes(), "application/octet-stream")


# ── API pública ─────────────────────────────────────────────────────────────

def procesar_documento(archivo_bytes: bytes, filename: str, cliente_id: str, tipo_doc: str) -> dict:
    """
    Extrae texto, genera chunks y embeddings, actualiza el índice del cliente.
    Guarda el archivo original en Supabase Storage.
    Retorna dict con ok, filename, tipo, chunks, caracteres.
    """
    from analizador import _obtener_modelo_embeddings

    texto = _extraer_texto_bytes(archivo_bytes, filename)
    if not texto or len(texto.strip()) < 20:
        return {"ok": False, "error": "No se pudo extraer texto del documento"}

    chunks = _chunkear(texto)
    if not chunks:
        return {"ok": False, "error": "El documento no generó chunks de texto"}

    modelo     = _obtener_modelo_embeddings()
    embeddings = modelo.encode(chunks, convert_to_numpy=True, show_progress_bar=False)

    indice = _cargar_indice(cliente_id)
    indice = [e for e in indice if e.get("filename") != filename]

    fecha_subida = datetime.now().isoformat()
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        indice.append({
            "doc_type":     tipo_doc,
            "filename":     filename,
            "fecha_subida": fecha_subida,
            "chunk_id":     i,
            "texto":        chunk,
            "embedding":    emb,
        })

    try:
        _guardar_indice(cliente_id, indice)
    except Exception as exc:
        logger.error("[DOCUMENTOS] Error guardando índice en Supabase: %s", exc)
        return {"ok": False, "error": "Error al guardar el documento en la nube."}

    # Guardar archivo original en Supabase Storage
    try:
        from supabase_client import sb_upload
        ext   = Path(filename).suffix.lower()
        ctype = "application/pdf" if ext == ".pdf" else "application/octet-stream"
        sb_upload(f"clientes/{cliente_id}/documentos/{filename}", archivo_bytes, ctype)
    except Exception as exc:
        logger.error("[DOCUMENTOS] Error subiendo archivo original a Supabase: %s", exc)
        return {"ok": False, "error": "Error al guardar el documento en la nube."}

    return {
        "ok":         True,
        "filename":   filename,
        "tipo":       tipo_doc,
        "chunks":     len(chunks),
        "caracteres": len(texto),
    }


def buscar_en_documentos_cliente(query: str, cliente_id: str, top_k: int = 5) -> list:
    """Similitud coseno de la query contra los chunks del cliente. Retorna top_k."""
    from analizador import _obtener_modelo_embeddings

    indice = _cargar_indice(cliente_id)
    if not indice:
        return []

    modelo  = _obtener_modelo_embeddings()
    emb_q   = modelo.encode([query], convert_to_numpy=True, show_progress_bar=False)[0]

    embeddings = np.array([e["embedding"] for e in indice])
    normas     = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normas[normas == 0] = 1
    embs_norm  = embeddings / normas
    emb_q_norm = emb_q / (np.linalg.norm(emb_q) or 1)
    sims       = embs_norm @ emb_q_norm

    top_idx   = np.argsort(sims)[::-1][:top_k]
    resultado = []
    for i in top_idx:
        entrada = {k: v for k, v in indice[i].items() if k != "embedding"}
        entrada["score"] = float(sims[i])
        resultado.append(entrada)
    return resultado


def verificar_vigencia_rup(cliente_id: str) -> dict:
    """
    Verifica vigencia del RUP.

    [D42c] Usa el LECTOR ÚNICO. Esta función tenía su propia copia del camino
    caché→Supabase, así que podía ver un perfil distinto del que veía la
    búsqueda o el evaluador para el mismo cliente.
    """
    try:
        from routers.perfil import _load_perfil
        perfil = _load_perfil(cliente_id) or {}
    except Exception:
        perfil = {}

    fecha_str = perfil.get("fecha_vencimiento_rup", "")
    if not fecha_str:
        return {"tiene_rup": False, "dias_restantes": None, "alerta": False}

    try:
        fecha_venc = datetime.fromisoformat(fecha_str)
        dias = (fecha_venc - datetime.now()).days
        return {
            "tiene_rup":         True,
            "fecha_vencimiento": fecha_str,
            "dias_restantes":    dias,
            "alerta":            dias < 60,
        }
    except Exception:
        return {"tiene_rup": True, "dias_restantes": None, "alerta": False}


def listar_documentos(cliente_id: str) -> list:
    """
    Tabla de documentos cargados: tipo, filename, fecha_subida, chunks.
    Lee solo la metadata (sin embeddings) desde caché o Supabase.
    """
    cache_meta = _cache_meta(cliente_id)

    # Poblar caché si falta (ej. tras un redeploy)
    if not cache_meta.exists():
        try:
            from supabase_client import sb_download
            meta_bytes = sb_download(_sb_meta(cliente_id))
            if meta_bytes:
                cache_meta.parent.mkdir(parents=True, exist_ok=True)
                cache_meta.write_bytes(meta_bytes)
        except Exception:
            return []

    if not cache_meta.exists():
        return []

    try:
        with open(cache_meta, "r", encoding="utf-8") as f:
            indice = json.load(f)
    except Exception:
        return []

    vistos = {}
    for e in indice:
        fname = e.get("filename", "")
        if fname not in vistos:
            vistos[fname] = {
                "tipo":         e.get("doc_type", ""),
                "filename":     fname,
                "fecha_subida": e.get("fecha_subida", "")[:10],
                "chunks":       0,
            }
        vistos[fname]["chunks"] += 1
    return list(vistos.values())
