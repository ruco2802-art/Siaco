# -*- coding: utf-8 -*-
"""Router de Redactor de Observaciones al Pliego — SIACO v3.1

Patrón de ejecución:
  POST /api/observaciones/generar  → lanza job en background, responde inmediatamente
  GET  /api/observaciones/estado/{job_id} → frontend consulta cada 3s hasta "completo"

Esto evita el 504 Gateway Timeout de Railway causado por la suma de:
  chunking/embeddings (si caché fría) + llamada a Claude (~30-90s).
"""
import io
import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import logging
import anthropic
import numpy as np
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import os
from prompts import SKILL_JURIDICO, SKILL_ESTRATEGIA
from routers.utils import parsear_json_claude

API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
logger = logging.getLogger("siaco")

router = APIRouter(tags=["observaciones"])


# ── Almacén de jobs ───────────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _job_path(job_id: str) -> Path:
    return Path(f"/tmp/siaco/jobs/{job_id}.json")


def _guardar_job(job_id: str, data: dict) -> None:
    with _jobs_lock:
        _jobs[job_id] = data
    try:
        p = _job_path(job_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _leer_job(job_id: str) -> dict | None:
    with _jobs_lock:
        if job_id in _jobs:
            return dict(_jobs[job_id])
    try:
        p = _job_path(job_id)
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


# ── RAG sobre el texto del pliego ─────────────────────────────────────────────

_CONSULTA_RAG_PLIEGO = (
    "índices financieros liquidez endeudamiento RCI solvencia experiencia habilitante "
    "número contratos valor garantías plazos publicación UNSPSC códigos requisito "
    "restricción certificación inhabilidad inhabilidades"
)


def _extraer_fragmentos_pliego(texto: str, top_k: int = 7, chunk_size: int = 600, cliente_id: str = "") -> str:
    """
    Aplica RAG sobre el texto del pliego para extraer fragmentos relevantes.
    Si se pasa cliente_id, reutiliza embeddings cacheados en sesión (más rápido).
    Fallback: chunking + embeddings fresh sobre el texto recibido.
    """
    if cliente_id:
        try:
            from analizador import buscar_chunks_pliego_cacheados
            chunks = buscar_chunks_pliego_cacheados(cliente_id, _CONSULTA_RAG_PLIEGO, top_k=top_k)
            if chunks:
                logger.debug("[OBSERVACIONES] RAG caché: %d chunks para cliente %s", len(chunks), cliente_id)
                return "\n---\n".join(chunks)
        except Exception as exc:
            logger.warning("[OBSERVACIONES] RAG caché falló, usando texto directo: %s", exc)

    from analizador import _obtener_modelo_embeddings

    chunks: list[str] = []
    inicio, overlap = 0, 100
    while inicio < len(texto):
        chunk = texto[inicio: inicio + chunk_size].strip()
        if len(chunk) > 60:
            chunks.append(chunk)
        inicio += chunk_size - overlap

    if len(chunks) <= top_k:
        return texto[:4000]

    try:
        modelo = _obtener_modelo_embeddings()
        embs   = modelo.encode(chunks, convert_to_numpy=True, show_progress_bar=False)
        emb_q  = modelo.encode([_CONSULTA_RAG_PLIEGO], convert_to_numpy=True, show_progress_bar=False)[0]

        normas = np.linalg.norm(embs, axis=1, keepdims=True)
        normas[normas == 0] = 1
        sims   = (embs / normas) @ (emb_q / (np.linalg.norm(emb_q) or 1))

        top_idx = sorted(np.argsort(sims)[::-1][:top_k].tolist())
        return "\n---\n".join(chunks[i] for i in top_idx)
    except Exception as exc:
        logger.warning("[OBSERVACIONES] RAG pliego falló, usando texto crudo: %s", exc)
        return texto[:4000]


# ── Utilidad PDF ──────────────────────────────────────────────────────────────

def _limpiar_pdf(texto: str) -> str:
    """Reemplaza caracteres fuera de latin-1 que Helvetica no soporta."""
    if not texto:
        return ""
    reemplazos = [
        ("≥", ">="), ("≤", "<="),
        ("→", "->"), ("←", "<-"),
        ("—", "-"), ("–", "-"),
        ("✅", "[OK]"), ("✓", "[OK]"), ("☑", "[OK]"),
        ("❌", "[NO]"), ("✗", "[NO]"), ("✘", "[NO]"),
        ("⚠️", "[!]"), ("⚠", "[!]"),
        ("•", "-"), ("·", "-"),
        (" ", " "),
        ("…", "..."),
        ("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"),
        ("°", " grados"),
        ("©", "(c)"), ("®", "(R)"), ("™", "(TM)"),
    ]
    for orig, rep in reemplazos:
        texto = texto.replace(orig, rep)
    return texto.encode("latin-1", errors="replace").decode("latin-1")


# ── Modelos ───────────────────────────────────────────────────────────────────

class ObservacionesBody(BaseModel):
    cliente_id: str
    proceso_id: Optional[str] = ""


# ── Procesamiento real (corre en background) ──────────────────────────────────

def _procesar_observaciones_bg(
    job_id: str,
    cliente_id: str,
    proceso_id: str,
    fragmentos_pliego: str,
    contexto_normativo: str,
    perfil_str: str,
    nombre_empresa: str,
    nit_empresa: str,
) -> None:
    """
    Llama a Claude, construye el PDF y lo sube a Supabase.
    Guarda el resultado (o el error) en el almacén de jobs para que
    el frontend pueda recuperarlo via GET /api/observaciones/estado/{job_id}.
    Se ejecuta en background DESPUÉS de que la respuesta HTTP ya fue enviada,
    por lo que el timeout del gateway de Railway no aplica aquí.
    """
    try:
        system_prompt = (
            f"{SKILL_JURIDICO}\n"
            f"{SKILL_ESTRATEGIA}\n\n"
            "Eres un abogado experto en contratación pública colombiana especializado en "
            "Documentos Tipo de Colombia Compra Eficiente (CCE) y en la detección de "
            "pliegos sastre o condiciones ilegalmente restrictivas."
        )

        user_prompt = f"""Analiza los extractos del pliego y compáralos con los Documentos Tipo CCE.

EXTRACTOS RELEVANTES DEL PLIEGO (secciones de habilitación, requisitos y condiciones):
{fragmentos_pliego}

NORMATIVA DE REFERENCIA (Biblioteca CCE — fragmentos más relevantes):
{contexto_normativo[:5000]}

PERFIL DE LA EMPRESA PROPONENTE:
{perfil_str}

Identifica las 5 discrepancias MÁS GRAVES donde el pliego exija condiciones más restrictivas que las permitidas por los Documentos Tipo CCE o la normativa vigente.

Busca especialmente:
- Índices financieros (IDL, NDE, RCI) superiores a las matrices CCE
- Experiencia exigida mayor al estándar normativo (valor, número de contratos, objetos demasiado específicos)
- Plazos de publicación inferiores al mínimo legal (Decreto 1082/2015)
- Combinación de códigos UNSPSC inusuales que limiten participación
- Requisitos que solo una empresa podría cumplir (pliego sastre — Ley 1882/2018)
- Garantías superiores a las permitidas por la ley
- Certificaciones no previstas en Documentos Tipo

RESPONDE ÚNICAMENTE CON JSON VÁLIDO. Sin texto adicional antes ni después del JSON:
{{
  "proceso": "nombre del proceso extraído del pliego",
  "entidad": "nombre de la entidad contratante",
  "fecha_cierre_observaciones": "DD/MM/YYYY si aparece en el pliego, si no: null",
  "total_discrepancias": 0,
  "tiene_discrepancias": false,
  "discrepancias": [
    {{
      "numero": 1,
      "titulo": "Título breve de la discrepancia (max 80 chars)",
      "seccion_pliego": "Sección X.X o nombre de la sección del pliego",
      "texto_pliego": "cita textual exacta del pliego donde aparece el problema (max 200 chars)",
      "norma_vulnerada": "Ley/Decreto/Resolución art. X que lo prohíbe o limita",
      "texto_norma": "qué dice exactamente la norma (max 200 chars)",
      "argumento": "argumentación jurídica clara y concisa de por qué es irregularidad (max 350 chars)",
      "observacion_sugerida": "texto formal completo listo para presentar en SECOP II (max 500 chars)"
    }}
  ]
}}"""

        client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            timeout=90.0,
            max_retries=1,
        )
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3500,
            temperature=0.0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = resp.content[0].text
        resultado = parsear_json_claude(raw)
        if resultado is None:
            _guardar_job(job_id, {
                "estado": "error",
                "mensaje": (
                    "Claude no devolvió JSON válido. "
                    "El pliego puede ser demasiado corto o ilegible."
                ),
            })
            return

        discrepancias = resultado.get("discrepancias") or []
        tiene_disc    = bool(discrepancias) or bool(resultado.get("tiene_discrepancias"))
        resultado["tiene_discrepancias"] = tiene_disc
        resultado["total_discrepancias"] = len(discrepancias)

        pdf_bytes    = None
        pdf_filename = None
        docx_filename = None
        perfil_data   = {}

        if tiene_disc and discrepancias:
            # Cargar perfil para el Word
            try:
                from routers.perfil import _load_perfil
                perfil_data = _load_perfil(cliente_id) or {}
            except Exception:
                perfil_data = {"nombre": nombre_empresa, "nit": nit_empresa}

            try:
                pdf_bytes = _build_pdf_observaciones(resultado, nombre_empresa, nit_empresa)
            except Exception as e:
                logger.warning("[OBSERVACIONES] PDF falló (job=%s): %s", job_id, e)

            if pdf_bytes:
                proceso_id_safe = re.sub(r"[^\w\-]", "_", proceso_id or "proceso")[:40]
                pdf_filename    = f"{proceso_id_safe}_observaciones.pdf"
                sb_prefix       = f"clientes/{cliente_id}/observaciones"

                try:
                    from supabase_client import sb_upload
                    sb_upload(f"{sb_prefix}/{pdf_filename}", pdf_bytes, "application/pdf")
                except Exception as exc:
                    logger.error("[OBSERVACIONES] No se pudo subir PDF (job=%s): %s", job_id, exc)
                    pdf_bytes    = None
                    pdf_filename = None

                if pdf_filename:
                    meta = {
                        "proceso_id":          proceso_id,
                        "proceso":             resultado.get("proceso", ""),
                        "entidad":             resultado.get("entidad", ""),
                        "total_discrepancias": len(discrepancias),
                        "fecha_generacion":    datetime.now().isoformat(),
                        "pdf_filename":        pdf_filename,
                    }
                    try:
                        from supabase_client import sb_upload
                        sb_upload(
                            f"{sb_prefix}/{proceso_id_safe}_meta.json",
                            json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"),
                            "application/json",
                        )
                    except Exception:
                        pass

            # Generar DOCX Word
            try:
                proceso_id_safe = re.sub(r"[^\w\-]", "_", proceso_id or "proceso")[:40]
                sb_prefix       = f"clientes/{cliente_id}/observaciones"
                docx_bytes      = _build_docx_observaciones(resultado, perfil_data, proceso_id or "")
                docx_filename   = f"{proceso_id_safe}_observaciones.docx"
                from supabase_client import sb_upload
                sb_upload(f"{sb_prefix}/{docx_filename}", docx_bytes,
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            except Exception as exc:
                logger.warning("[OBSERVACIONES] DOCX falló (job=%s): %s", job_id, exc)
                docx_filename = None

        _guardar_job(job_id, {
            "estado": "completo",
            "datos": {
                "tiene_discrepancias":        tiene_disc,
                "total_discrepancias":        len(discrepancias),
                "proceso":                    resultado.get("proceso", ""),
                "entidad":                    resultado.get("entidad", ""),
                "fecha_cierre_observaciones": resultado.get("fecha_cierre_observaciones"),
                "discrepancias":              discrepancias,
                "pdf_disponible":             pdf_bytes is not None,
                "pdf_filename":               pdf_filename,
                "docx_filename":              docx_filename,
            },
        })
        logger.info("[OBSERVACIONES] Job %s completado: %d discrepancias", job_id, len(discrepancias))

    except anthropic.APITimeoutError:
        _guardar_job(job_id, {
            "estado": "error",
            "mensaje": (
                "El análisis con IA tardó demasiado. "
                "El pliego puede ser muy extenso. "
                "Intenta de nuevo."
            ),
        })
    except Exception as e:
        logger.error("[OBSERVACIONES] Error en job %s: %s", job_id, e)
        _guardar_job(job_id, {"estado": "error", "mensaje": str(e)[:300]})


# ── POST /api/observaciones/generar ──────────────────────────────────────────

@router.post("/observaciones/generar")
def generar_observaciones(
    body: ObservacionesBody,
    background_tasks: BackgroundTasks,
    authorization: str = Header(None),
):
    """
    Valida la sesión, prepara el contexto (rápido, usa caché del pliego) y
    lanza el análisis Claude en background. Responde en <1s con job_id para
    que el frontend haga polling — evita el 504 de Railway.
    """
    from routers.auth import require_auth
    from routers.perfil import _load_perfil
    from contexto_sesion import obtener_contexto_sesion
    from analizador import obtener_contexto_legal

    sesion = require_auth(authorization)

    cid_token = sesion.get("cliente_id") or sesion.get("id") or ""
    ctx = obtener_contexto_sesion(body.cliente_id) or obtener_contexto_sesion(cid_token)
    texto_pliego = ctx.get("texto_pliego", "")
    if not texto_pliego or len(texto_pliego.strip()) < 200:
        raise HTTPException(
            status_code=422,
            detail=(
                "No hay pliego en sesión. "
                "Sube el PDF del pliego en Auditoría de Pliegos y analízalo primero."
            ),
        )

    perfil         = _load_perfil(body.cliente_id) or {}
    nombre_empresa = perfil.get("nombre", "Empresa Cliente")
    nit_empresa    = perfil.get("nit", "")
    fin            = perfil.get("financiero",  {})
    exp            = perfil.get("experiencia", {})
    perfil_str = (
        f"Empresa: {nombre_empresa} | NIT: {nit_empresa}\n"
        f"Sector: {perfil.get('sector', '')}\n"
        f"Indice de Liquidez (IDL): {fin.get('indice_liquidez', '—')}\n"
        f"Indice de Endeudamiento (NDE): {fin.get('indice_endeudamiento', '—')}\n"
        f"Patrimonio Liquido: COP {fin.get('patrimonio_liquido', '—')}\n"
        f"Experiencia acumulada (3 años): COP {exp.get('valor_acumulado', '—')}\n"
        f"Valor contrato individual maximo: COP {exp.get('valor_individual_max', '—')}\n"
        f"Objeto similar: {exp.get('objeto_similar', '—')}\n"
        f"Codigos UNSPSC: {exp.get('codigos_unspsc', '—')}"
    )

    # RAG sobre el pliego (usa caché si ya analizó en Auditoría — instantáneo)
    fragmentos_pliego = _extraer_fragmentos_pliego(
        texto_pliego, top_k=7, cliente_id=body.cliente_id
    )

    consulta_rag = (
        "indicadores financieros liquidez endeudamiento experiencia habilitante "
        "pliegos tipo documentos tipo requisitos restriccion irregularidad sastre"
    )
    try:
        contexto_normativo = obtener_contexto_legal(
            "infraestructura_obra_publica", "institucional",
            consulta=consulta_rag, top_k=6,
        )
    except Exception:
        contexto_normativo = "Biblioteca normativa no disponible para esta consulta."

    job_id = uuid.uuid4().hex[:16]
    _guardar_job(job_id, {"estado": "procesando"})

    background_tasks.add_task(
        _procesar_observaciones_bg,
        job_id,
        body.cliente_id,
        body.proceso_id or "",
        fragmentos_pliego,
        contexto_normativo,
        perfil_str,
        nombre_empresa,
        nit_empresa,
    )

    logger.info("[OBSERVACIONES] Job %s lanzado para cliente %s", job_id, body.cliente_id)
    return {"job_id": job_id, "estado": "procesando"}


# ── GET /api/observaciones/estado/{job_id} ────────────────────────────────────

@router.get("/observaciones/estado/{job_id}")
def estado_observaciones(job_id: str, authorization: str = Header(None)):
    """Polling endpoint: devuelve {estado: 'procesando'} o {estado: 'completo', datos: {...}}."""
    from routers.auth import require_auth
    require_auth(authorization)

    job = _leer_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado o expirado")
    return job


# ── GET /api/observaciones/pdf/{cliente_id}/{filename} ────────────────────────

@router.get("/observaciones/pdf/{cliente_id}/{filename}")
def descargar_documento_observaciones(
    cliente_id: str,
    filename:   str,
    authorization: str = Header(None),
):
    """Descarga PDF o DOCX de observaciones desde Supabase Storage."""
    from routers.auth import require_auth
    require_auth(authorization)

    if not re.match(r"^[\w\-\.]+$", filename):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")

    try:
        from supabase_client import sb_download
        file_bytes = sb_download(f"clientes/{cliente_id}/observaciones/{filename}")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error al acceder al almacenamiento en la nube: {str(exc)[:200]}",
        )

    if not file_bytes:
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")

    if filename.endswith(".docx"):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        media_type = "application/pdf"

    return Response(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Generador Word ────────────────────────────────────────────────────────────

def _build_docx_observaciones(resultado: dict, perfil_data: dict, proceso_id: str) -> bytes:
    """
    Genera Word profesional de Observaciones al Pliego:
    TNR 12pt, 1.5 interlineado, justificado, encabezado/pie, citas en cursiva.
    """
    try:
        from docx import Document
        from docx.shared import Pt, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
    except ImportError:
        raise RuntimeError("python-docx no disponible")

    proceso       = resultado.get("proceso", proceso_id)
    entidad       = resultado.get("entidad", "Entidad Estatal")
    fecha_cierre  = resultado.get("fecha_cierre_observaciones") or ""
    discrepancias = resultado.get("discrepancias", [])

    nombre_empresa = perfil_data.get("nombre", "Empresa")
    nit_empresa    = perfil_data.get("nit", "")
    rep_legal      = perfil_data.get("representante_legal", "[REPRESENTANTE LEGAL]")
    cargo_rep      = perfil_data.get("cargo_representante", "Representante Legal")
    cedula_rep     = perfil_data.get("cedula_representante", "[C.C.]")
    ciudad         = perfil_data.get("ciudad", "Bogotá D.C.")
    fecha_hoy      = datetime.now().strftime("%d/%m/%Y")

    doc = Document()
    for sec in doc.sections:
        sec.top_margin    = Cm(2.5)
        sec.bottom_margin = Cm(2.5)
        sec.left_margin   = Cm(2.5)
        sec.right_margin  = Cm(2.5)

    # Estilo base
    normal = doc.styles['Normal']
    normal.font.name = 'Times New Roman'
    normal.font.size = Pt(12)
    pf = normal.paragraph_format
    pf.alignment         = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    pf.space_after       = Pt(0)

    # Encabezado
    hdr = doc.sections[0].header
    hp  = hdr.paragraphs[0] if hdr.paragraphs else hdr.add_paragraph()
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hp.clear()

    def _hr(text: str):
        r = hp.add_run(text)
        r.font.name = 'Times New Roman'; r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    def _field(code: str):
        r = hp.add_run()
        r.font.name = 'Times New Roman'; r.font.size = Pt(9)
        fc1 = OxmlElement('w:fldChar'); fc1.set(qn('w:fldCharType'), 'begin')
        it  = OxmlElement('w:instrText')
        it.text = f' {code} '; it.set(qn('xml:space'), 'preserve')
        fc2 = OxmlElement('w:fldChar'); fc2.set(qn('w:fldCharType'), 'end')
        r._r.extend([fc1, it, fc2])

    _hr(f"{nombre_empresa[:30]}  |  {proceso_id[:30]}  |  Pág. ")
    _field("PAGE"); _hr(" de "); _field("NUMPAGES")

    # Pie de página
    ftr = doc.sections[0].footer
    fp  = ftr.paragraphs[0] if ftr.paragraphs else ftr.add_paragraph()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER; fp.clear()
    fr = fp.add_run(
        "SIACO — Borrador generado con IA. Verifique con asesor jurídico antes de presentar en SECOP II."
    )
    fr.font.name = 'Times New Roman'; fr.font.size = Pt(8)
    fr.font.italic = True; fr.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    def _body(text: str, indent: float = 0):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(indent)
        r = p.add_run(str(text or "—"))
        r.font.name = 'Times New Roman'; r.font.size = Pt(12)
        return p

    def _label(label: str, value: str):
        p = doc.add_paragraph()
        r1 = p.add_run(label + ": ")
        r1.font.name = 'Times New Roman'; r1.font.size = Pt(12); r1.font.bold = True
        r2 = p.add_run(str(value or "—"))
        r2.font.name = 'Times New Roman'; r2.font.size = Pt(12)
        return p

    def _italic_quote(text: str, indent: float = 1.0):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(indent)
        r = p.add_run(f'"{text}"')
        r.font.name = 'Times New Roman'; r.font.size = Pt(11); r.font.italic = True
        return p

    def _section_heading(text: str):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        r = p.add_run(text)
        r.font.name = 'Times New Roman'; r.font.size = Pt(12)
        r.font.bold = True; r.font.color.rgb = RGBColor(0x00, 0x64, 0x50)
        return p

    # ── TÍTULO
    t = doc.add_heading("OBSERVACIONES AL PLIEGO DE CONDICIONES", level=1)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in t.runs:
        run.font.name = 'Times New Roman'; run.font.size = Pt(16)
        run.font.bold = True; run.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)
    doc.add_paragraph()

    # ── CABECERA
    _body(f"{ciudad}, {fecha_hoy}")
    doc.add_paragraph()
    _body(f"Señores")
    _body(entidad)
    doc.add_paragraph()
    _label("Proceso", proceso_id)
    _label("Objeto", proceso)
    if fecha_cierre:
        _label("Fecha cierre de observaciones", fecha_cierre)
    doc.add_paragraph()

    # ── APERTURA LEGAL
    _body(
        f"En nombre de {nombre_empresa} (NIT {nit_empresa}), y en ejercicio del derecho "
        "establecido en el artículo 30 de la Ley 80 de 1993, el artículo 4 de la Ley 1150 "
        "de 2007 y el artículo 2.2.1.1.2.1.4 del Decreto 1082 de 2015, que reconocen el "
        "derecho de los interesados a formular observaciones al pliego de condiciones durante "
        "la etapa de publicación, presento las siguientes observaciones:"
    )
    doc.add_paragraph()

    # ── OBSERVACIONES
    for d in discrepancias:
        num    = d.get('numero', '?')
        titulo = d.get('titulo', 'Observación')

        p_titulo = doc.add_paragraph()
        p_titulo.paragraph_format.space_before = Pt(10)
        r_t = p_titulo.add_run(f"OBSERVACIÓN No. {num} — {titulo.upper()}")
        r_t.font.name = 'Times New Roman'; r_t.font.size = Pt(13)
        r_t.font.bold = True; r_t.font.color.rgb = RGBColor(0x00, 0x64, 0x50)
        doc.add_paragraph()

        _label("Sección del pliego", d.get("seccion_pliego", "—"))
        _section_heading("Texto del pliego:")
        _italic_quote(d.get("texto_pliego", "—"))
        _label("Norma vulnerada", d.get("norma_vulnerada", "—"))
        if d.get("texto_norma"):
            _italic_quote(d.get("texto_norma", ""))
        _section_heading("Argumentación jurídica:")
        _body(d.get("argumento", "—"))

        p_sol_lbl = doc.add_paragraph()
        p_sol_lbl.paragraph_format.space_before = Pt(4)
        r_sl = p_sol_lbl.add_run("Solicitud formal (listo para copiar en SECOP II):")
        r_sl.font.name = 'Times New Roman'; r_sl.font.size = Pt(12)
        r_sl.font.bold = True; r_sl.font.color.rgb = RGBColor(0x00, 0x50, 0xA0)
        _body(d.get("observacion_sugerida", "—"), indent=0.5)

        doc.add_paragraph()
        p_hr = doc.add_paragraph()
        r_hr = p_hr.add_run("─" * 72)
        r_hr.font.name = 'Times New Roman'; r_hr.font.size = Pt(10)
        p_hr.alignment = WD_ALIGN_PARAGRAPH.LEFT
        doc.add_paragraph()

    # ── CIERRE
    _section_heading("CIERRE")
    doc.add_paragraph()
    _body(
        "Las observaciones anteriores se formulan dentro del término establecido en el "
        "cronograma del proceso, en ejercicio del derecho reconocido por la normativa "
        "vigente de contratación pública colombiana."
    )
    doc.add_paragraph()
    doc.add_paragraph()
    _body("Firma: _________________________________")
    _label("Nombre", rep_legal)
    _label("Cargo", cargo_rep)
    _label("C.C. No.", cedula_rep)
    _label("Empresa", nombre_empresa)
    _label("NIT", nit_empresa)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


# ── Generador PDF ─────────────────────────────────────────────────────────────

def _build_pdf_observaciones(resultado: dict, nombre_empresa: str, nit: str) -> bytes:
    """Construye el PDF de Observaciones al Pliego usando fpdf2."""
    from fpdf import FPDF, XPos, YPos

    proceso       = resultado.get("proceso", "Proceso de contratacion")
    entidad       = resultado.get("entidad", "Entidad Estatal")
    fecha_cierre  = resultado.get("fecha_cierre_observaciones") or ""
    discrepancias = resultado.get("discrepancias", [])
    fecha_hoy     = datetime.now().strftime("%d/%m/%Y")

    NL  = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}
    NR  = {"new_x": XPos.RIGHT,   "new_y": YPos.TOP}

    class _PDF(FPDF):
        def __init__(self):
            super().__init__()
            self.set_margins(15, 15, 15)

        def footer(self):
            self.set_y(-18)
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(130, 130, 130)
            self.cell(0, 4,
                "SIACO v3.0 - Borrador de referencia generado con IA. "
                "Verifique con asesor juridico antes de presentar en SECOP II.  "
                f"Pag. {self.page_no()}",
                align="C", **NL,
            )

    pdf = _PDF()
    pdf.set_auto_page_break(auto=True, margin=22)

    pdf.add_page()
    pdf.set_fill_color(10, 10, 10)
    pdf.rect(0, 0, 210, 48, "F")
    pdf.set_y(10)
    pdf.set_text_color(198, 242, 78)
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 10, "SIACO v3.0", align="C", **NL)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(170, 170, 170)
    pdf.cell(0, 7, "Sistema de Inteligencia para Contratacion Publica SECOP II", align="C", **NL)

    pdf.set_y(56)
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(0, 10, "OBSERVACIONES AL PLIEGO DE CONDICIONES", align="C", **NL)
    pdf.set_draw_color(0, 163, 122)
    pdf.set_line_width(1.0)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(5)

    def _campo(etiqueta: str, valor: str):
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(50, 50, 50)
        pdf.cell(48, 7, _limpiar_pdf(f"{etiqueta}:"), **NR)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(20, 20, 20)
        pdf.multi_cell(0, 7, _limpiar_pdf(str(valor or "-")), **NL)

    _campo("Proceso",        proceso)
    _campo("Entidad",        entidad)
    _campo("Presentado por", nombre_empresa)
    if nit:
        _campo("NIT",        nit)
    _campo("Fecha",          fecha_hoy)
    if fecha_cierre:
        _campo("Cierre de observaciones", fecha_cierre)

    pdf.ln(5)
    pdf.set_fill_color(215, 245, 225)
    pdf.set_draw_color(0, 163, 122)
    pdf.set_line_width(0.5)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(10, 80, 50)
    pdf.cell(0, 11,
             _limpiar_pdf(f"  Total de observaciones identificadas: {len(discrepancias)}"),
             fill=True, border=1, **NL)

    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(0, 5,
        "Este documento fue generado como borrador de referencia por SIACO. "
        "Revise y ajuste cada observacion antes de presentarla formalmente en SECOP II.",
        align="C", **NL,
    )

    for d in discrepancias:
        pdf.add_page()
        pdf.set_fill_color(0, 100, 80)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 12)
        titulo = _limpiar_pdf(
            f"OBSERVACION No. {d.get('numero', '?')} - {d.get('titulo', '')}"
        )
        pdf.multi_cell(0, 9, titulo, fill=True, **NL)
        pdf.ln(3)

        def _bloque(etiqueta: str, contenido: str, color=(0, 100, 80)):
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*color)
            pdf.cell(0, 6, _limpiar_pdf(etiqueta), **NL)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(0, 5, _limpiar_pdf(str(contenido or "-")), **NL)
            pdf.ln(2)

        _bloque("Seccion del pliego:",     d.get("seccion_pliego", ""))
        _bloque("Texto del pliego:",       d.get("texto_pliego",   ""))
        _bloque("Norma vulnerada:",        d.get("norma_vulnerada", ""), color=(140, 20, 20))
        _bloque("Texto de la norma:",      d.get("texto_norma",    ""))
        _bloque("Argumentacion juridica:", d.get("argumento",      ""))

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(0, 70, 130)
        pdf.cell(0, 6, "Texto de la observacion (listo para presentar en SECOP II):", **NL)

        pdf.set_fill_color(235, 245, 255)
        pdf.set_draw_color(80, 130, 200)
        pdf.set_line_width(0.4)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(15, 15, 70)
        pdf.multi_cell(0, 5,
            _limpiar_pdf(str(d.get("observacion_sugerida") or "-")),
            border=1, fill=True, **NL,
        )
        pdf.ln(3)

        pdf.set_draw_color(200, 200, 200)
        pdf.set_line_width(0.3)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())

    return bytes(pdf.output())
