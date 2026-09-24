# -*- coding: utf-8 -*-
"""
pipeline/src/artefactos.py — Capa de acceso a artefactos del pipeline.

Los routers usan obtener_artefactos(pliego_id) sin saber de dónde salen
los datos. Hoy: disco local. Mañana: Supabase o base de datos, cambiando
solo este módulo.

pliego_id = SHA256 del PDF original.
  - El markdown reparado vive en .pipeline_cache/{sha256}.json
  - El resultado de extracción se busca en resultados_evaluacion/ por el campo
    metadatos_corrida.pliego_sha256. Resultados sin ese campo se ignoran.

Chunks: se regeneran de markdown la primera vez (chunkear() ~0.3s) y se
cachean en _CHUNKS_CACHE para el proceso. Sin latencia en accesos siguientes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Raíz del repo (dos niveles arriba de este archivo)
_REPO_ROOT = Path(__file__).parent.parent.parent

_CACHE_DIR     = _REPO_ROOT / ".pipeline_cache"
_RESULTADOS_DIR = _REPO_ROOT / "resultados_evaluacion"

# Caché en memoria: {sha256 → chunks}. Sobrevive múltiples requests en el mismo proceso.
_CHUNKS_CACHE: dict[str, list[dict]] = {}

# Caché en memoria: {sha256 → (requisitos_consolidados, info_consolidacion)}.
_CONSOLIDADO_CACHE: dict[str, tuple[list[dict], dict]] = {}


def _consolidar_requisitos(sha256: str, requisitos: list[dict]) -> tuple[list[dict], dict]:
    """
    Aplica clasificación + consolidación a los requisitos crudos del extractor.

    Esta es la capa de NORMALIZACIÓN: todo consumidor de artefactos (auditoría,
    chat, reportes) debe ver el mismo conjunto consolidado. El filtro por
    criticidad es política y corresponde al sitio de llamada, no a esta capa.

    Devuelve (requisitos_consolidados_como_dicts, info_consolidacion).
    Si la consolidación falla, devuelve los crudos con el error registrado —
    nunca se pierden requisitos por un fallo del clasificador.
    """
    if not requisitos:
        return [], {"aplicada": False, "motivo": "sin_requisitos"}

    if sha256 in _CONSOLIDADO_CACHE:
        return _CONSOLIDADO_CACHE[sha256]

    try:
        from .clasificador import consolidar
        from .extractor import Requisito

        objetos = [Requisito.model_validate(r) for r in requisitos]
        res = consolidar(objetos)

        # [B11] Cobertura del catálogo de objetos: qué fracción de los crudos
        # obtuvo objeto identificable. Se registra en el JSONL de faltantes,
        # que es lo que se revisa para hacer crecer el catálogo.
        cobertura_catalogo: dict = {}
        try:
            from .catalogo import registrar_no_identificados
            cobertura_catalogo = registrar_no_identificados(objetos, pliego=sha256)
        except Exception as exc:
            cobertura_catalogo = {"error": str(exc)}

        n_indet = sum(1 for r in res.requisitos if r.criticidad == "indeterminado")
        total = len(res.requisitos)
        info = {
            "aplicada":          True,
            "catalogo":          cobertura_catalogo,
            "antes_total":       res.antes_total,
            "despues_dedup":     res.despues_dedup,
            "despues_fusion":    res.despues_fusion,
            "despues_descarte":  res.despues_descarte,
            "despues_causales":  res.despues_causales,
            "n_descartados":     len(res.descartados),
            "n_habilitantes":    sum(1 for r in res.requisitos if r.criticidad == "habilitante"),
            "n_procedimentales": sum(1 for r in res.requisitos if r.criticidad == "procedimental"),
            "n_puntaje":         sum(1 for r in res.requisitos if r.criticidad == "puntaje"),
            "n_indeterminados":  n_indet,
            "pct_indeterminados": round(n_indet / total, 3) if total else 0.0,
            "descartados":       res.descartados,
        }
        salida = [r.model_dump() for r in res.requisitos]
        _CONSOLIDADO_CACHE[sha256] = (salida, info)
        return salida, info

    except Exception as exc:
        # [C1] No perder requisitos: devolver crudos y dejar el fallo visible.
        print(f"[ARTEFACTOS] Consolidación falló para {sha256[:12]}: {exc}")
        info = {"aplicada": False, "motivo": f"error: {exc}", "antes_total": len(requisitos)}
        return requisitos, info


@dataclass
class Artefactos:
    pliego_id: str              # SHA256 del PDF
    archivo: str                # nombre original del PDF (ej: "29. PLIEGO DE CONDICIONES.pdf")
    markdown: str               # texto completo reparado por el parser
    chunks: list[dict]          # chunks con metadata (capitulo, subcapitulo, numeral)
    requisitos: list[dict]      # Requisito.model_dump() YA CONSOLIDADOS, o []
    metadatos_parser: dict      # n_paginas, uso_ocr, chars, sha256
    metadatos_corrida: dict     # timestamp, modelo, tokens, costo, pliego_sha256
    consolidacion: dict = field(default_factory=dict)  # trazabilidad del paso de consolidación


def _cargar_chunks(sha256: str, markdown: str) -> list[dict]:
    """
    Devuelve chunks desde caché o los genera con chunkear().
    Guarda en _CHUNKS_CACHE para evitar regenerarlos en cada request.
    """
    if sha256 in _CHUNKS_CACHE:
        return _CHUNKS_CACHE[sha256]
    try:
        from .chunker import chunkear
        chunks, _ = chunkear(markdown)
        _CHUNKS_CACHE[sha256] = chunks
        return chunks
    except Exception as exc:
        # No interrumpir si chunker falla — artefactos parciales son mejor que ninguno
        print(f"[ARTEFACTOS] Error al generar chunks para {sha256[:12]}: {exc}")
        _CHUNKS_CACHE[sha256] = []
        return []


def _buscar_resultado(sha256: str) -> tuple[list[dict], dict]:
    """
    Escanea resultados_evaluacion/ buscando el archivo cuyo campo
    metadatos_corrida.pliego_sha256 coincide con sha256.

    Devuelve (requisitos, metadatos_corrida). Si no encuentra, devuelve ([], {}).
    Archivos sin el campo pliego_sha256 se ignoran (son resultados anteriores a
    artefactos.py y su correspondencia con el PDF sería una suposición).
    """
    if not _RESULTADOS_DIR.exists():
        return [], {}

    # Nombre exacto: {sha256}_extraccion.json (generado por main.py post-artefactos)
    exacto = _RESULTADOS_DIR / f"{sha256}_extraccion.json"
    if exacto.exists():
        try:
            d = json.loads(exacto.read_text("utf-8"))
            return d.get("requisitos", []), d.get("metadatos_corrida", {})
        except Exception:
            pass

    # Fallback: escanear todos los JSON buscando el campo pliego_sha256
    for p in sorted(_RESULTADOS_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            d = json.loads(p.read_text("utf-8"))
            mc = d.get("metadatos_corrida", {})
            if mc.get("pliego_sha256") == sha256:
                return d.get("requisitos", []), mc
        except Exception:
            continue

    return [], {}


def obtener_artefactos(pliego_id: str) -> Artefactos | None:
    """
    Devuelve los artefactos del pipeline para el pliego identificado por SHA256.

    Devuelve None si el pliego no fue procesado por el pipeline (el pipeline
    es un proceso offline — no se dispara desde aquí).

    El campo `requisitos` puede ser [] si el resultado de extracción no existe
    todavía; el markdown y chunks siguen disponibles.
    """
    cache_file = _CACHE_DIR / f"{pliego_id}.json"
    if not cache_file.exists():
        return None

    try:
        raw = json.loads(cache_file.read_text("utf-8"))
    except Exception as exc:
        print(f"[ARTEFACTOS] Error leyendo caché {pliego_id[:12]}: {exc}")
        return None

    markdown: str = raw.get("markdown", "")
    meta_parser: dict[str, Any] = raw.get("metadata", {})

    if not markdown:
        return None

    chunks = _cargar_chunks(pliego_id, markdown)
    requisitos_crudos, meta_corrida = _buscar_resultado(pliego_id)

    # NORMALIZACIÓN: clasificar + consolidar antes de exponer los requisitos.
    # Todos los consumidores (auditoría, chat, reportes) ven el mismo conjunto.
    requisitos, info_consolidacion = _consolidar_requisitos(pliego_id, requisitos_crudos)

    return Artefactos(
        pliego_id=pliego_id,
        archivo=meta_parser.get("archivo", ""),
        markdown=markdown,
        chunks=chunks,
        requisitos=requisitos,
        metadatos_parser=meta_parser,
        metadatos_corrida=meta_corrida,
        consolidacion=info_consolidacion,
    )


def chunks_relevantes(
    artefactos: Artefactos,
    query: str,
    top_k: int = 4,
    max_chars_por_chunk: int = 1_200,
) -> list[dict]:
    """
    Devuelve top_k chunks del pipeline más relevantes para la query.
    Búsqueda por similitud semántica si hay modelo de embeddings disponible;
    si no, fallback a keyword overlap (sin dependencia externa).

    Cada chunk devuelto incluye su metadata de sección (capitulo, numeral, etc.)
    y el texto recortado a max_chars_por_chunk.
    """
    chunks = artefactos.chunks
    if not chunks:
        return []

    # Recortar texto de cada chunk conservando metadata
    def _recortar(c: dict) -> dict:
        texto = c.get("texto", "")
        if len(texto) > max_chars_por_chunk:
            texto = texto[:max_chars_por_chunk] + "…"
        return {**c, "texto": texto}

    # Intentar similitud semántica (sentence-transformers, opcional)
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer

        _MODEL_NAME = "all-MiniLM-L6-v2"
        texts = [c.get("texto", "") for c in chunks]

        # Singleton del modelo (costoso cargarlo en cada llamada)
        if not hasattr(chunks_relevantes, "_emb_model"):
            chunks_relevantes._emb_model = SentenceTransformer(_MODEL_NAME)  # type: ignore[attr-defined]

        model = chunks_relevantes._emb_model  # type: ignore[attr-defined]
        doc_embs = model.encode(texts, show_progress_bar=False)
        q_emb = model.encode([query], show_progress_bar=False)[0]

        norms = np.linalg.norm(doc_embs, axis=1, keepdims=True)
        norms[norms == 0] = 1
        q_norm = q_emb / (np.linalg.norm(q_emb) or 1)
        sims = (doc_embs / norms) @ q_norm
        top_idx = np.argsort(sims)[::-1][:top_k].tolist()
        return [_recortar(chunks[i]) for i in top_idx]

    except Exception:
        pass

    # Fallback: keyword overlap (sin dependencias externas)
    q_words = set(query.lower().split())
    def _score(c: dict) -> int:
        return sum(1 for w in q_words if w in c.get("texto", "").lower())

    ranked = sorted(enumerate(chunks), key=lambda ic: _score(ic[1]), reverse=True)
    return [_recortar(chunks[i]) for i, _ in ranked[:top_k]]


def bloque_requisitos(
    artefactos: Artefactos,
    solo_habilitantes: bool = True,
    max_chars_total: int = 3_000,
) -> str:
    """
    Construye el bloque fijo de requisitos para el chat.

    Con cita si cabe en max_chars_total; sin cita si supera el límite.
    Incluye nombre, numeral, categoría y criticidad siempre.
    El numeral permite al chat citar la sección exacta del pliego.
    """
    requisitos = artefactos.requisitos
    if not requisitos:
        return ""

    aviso = ""
    if solo_habilitantes:
        filtrados = [r for r in requisitos if r.get("criticidad") == "habilitante"]
        # Cero habilitantes ⇒ la clasificación no corrió. Mostrar todos SIN avisar
        # haría creer al chat que los 218 fragmentos son habilitantes (el bug que
        # infló el conteo en la auditoría). Se muestran, pero marcados.
        if not filtrados:
            filtrados = requisitos
            aviso = (
                "[AVISO] Los requisitos de este pliego no están clasificados. "
                "La lista siguiente NO distingue habilitantes de procedimentales "
                "ni de criterios de puntaje; no la uses para afirmar si la empresa "
                "queda habilitada.\n"
            )
    else:
        filtrados = requisitos

    def _linea_completa(r: dict) -> str:
        cita = (r.get("exigido_literal") or "")[:150]
        nm = (r.get("fuente_numeral") or "")[:40]
        return f"[{r.get('categoria','?')}] {nm}: {r.get('nombre','?')} | {cita}"

    def _linea_compacta(r: dict) -> str:
        nm = (r.get("fuente_numeral") or "")[:40]
        crit = r.get("criticidad") or "indeterminado"
        return f"[{r.get('categoria','?')}] {nm}: {r.get('nombre','?')} ({crit})"

    # Intenta versión completa
    lineas = [_linea_completa(r) for r in filtrados]
    bloque = aviso + "\n".join(lineas)
    if len(bloque) <= max_chars_total:
        return bloque

    # Versión compacta si supera el límite
    lineas_c = [_linea_compacta(r) for r in filtrados]
    return aviso + "\n".join(lineas_c)
