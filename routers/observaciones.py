# -*- coding: utf-8 -*-
"""Router de Redactor de Observaciones al Pliego — SIACO v3.0"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import logging

import anthropic
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from config import API_KEY
from prompts import SKILL_JURIDICO, SKILL_ESTRATEGIA
from routers.utils import parsear_json_claude

logger = logging.getLogger("siaco")

router = APIRouter(tags=["observaciones"])


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
        (" ", " "),   # non-breaking space → normal
        ("…", "..."),
        (""", '"'), (""", '"'), ("'", "'"), ("'", "'"),
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


# ── POST /api/observaciones/generar ──────────────────────────────────────────

@router.post("/observaciones/generar")
def generar_observaciones(body: ObservacionesBody, authorization: str = Header(None)):
    """
    Identifica discrepancias entre el pliego (en sesión) y los Documentos Tipo CCE.
    Genera PDF de observaciones listo para presentar en SECOP II.
    """
    from routers.auth import require_auth
    from routers.perfil import _load_perfil
    from contexto_sesion import obtener_contexto_sesion
    from analizador import obtener_contexto_legal

    require_auth(authorization)

    # 1. Texto del pliego desde sesión de auditoría
    ctx = obtener_contexto_sesion(body.cliente_id)
    texto_pliego = ctx.get("texto_pliego", "")
    if not texto_pliego or len(texto_pliego.strip()) < 200:
        raise HTTPException(
            status_code=422,
            detail=(
                "No hay pliego en sesión. "
                "Sube el PDF del pliego en Auditoría de Pliegos y analízalo primero."
            ),
        )

    # 2. Perfil del cliente
    perfil = _load_perfil(body.cliente_id) or {}
    nombre_empresa = perfil.get("nombre", "Empresa Cliente")
    nit_empresa    = perfil.get("nit", "")
    fin = perfil.get("financiero",  {})
    exp = perfil.get("experiencia", {})
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

    # 3. Contexto normativo vía RAG (biblioteca Documentos Tipo CCE)
    consulta_rag = (
        "indicadores financieros liquidez endeudamiento experiencia habilitante "
        "pliegos tipo documentos tipo requisitos restriccion irregularidad sastre"
    )
    try:
        contexto_normativo = obtener_contexto_legal(
            "infraestructura_obra_publica", "institucional",
            consulta=consulta_rag, top_k=8,
        )
    except Exception:
        contexto_normativo = "Biblioteca normativa no disponible para esta consulta."

    # 4. Llamado único a Claude
    client = anthropic.Anthropic(api_key=API_KEY, timeout=120.0, max_retries=2)

    system_prompt = (
        f"{SKILL_JURIDICO}\n"
        f"{SKILL_ESTRATEGIA}\n\n"
        "Eres un abogado experto en contratación pública colombiana especializado en "
        "Documentos Tipo de Colombia Compra Eficiente (CCE) y en la detección de "
        "pliegos sastre o condiciones ilegalmente restrictivas."
    )

    user_prompt = f"""Analiza este pliego de condiciones y compáralo con los Documentos Tipo CCE y la normativa vigente.

PLIEGO DE CONDICIONES:
{texto_pliego[:12000]}

NORMATIVA DE REFERENCIA (Biblioteca CCE — fragmentos más relevantes):
{contexto_normativo[:6000]}

PERFIL DE LA EMPRESA PROPONENTE:
{perfil_str}

Identifica TODAS las discrepancias donde el pliego exija condiciones MÁS RESTRICTIVAS que las permitidas por los Documentos Tipo CCE o la normativa vigente.

Busca especialmente:
- Índices financieros (IDL, NDE, RCI) superiores a los matrices CCE
- Experiencia exigida mayor al estándar normativo (valor, número de contratos, objetos demasiado específicos)
- Plazos de publicación inferiores al mínimo legal (Decreto 1082/2015)
- Combinación de códigos UNSPSC inusuales que limiten participación
- Requisitos que solo una empresa podría cumplir (pliego sastre — Ley 1882/2018)
- Garantías superiores a las permitidas por la ley
- Certificaciones no previstas en Documentos Tipo
- Número de contratos de experiencia excesivo para el tamaño del contrato

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

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            temperature=0.0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = resp.content[0].text
        resultado = parsear_json_claude(raw)
        if resultado is None:
            logger.error(
                "[OBSERVACIONES] parsear_json_claude retornó None. Respuesta cruda (primeros 1000 chars):\n%s",
                raw[:1000],
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "Claude no devolvió JSON válido al analizar el pliego. "
                    "Intenta nuevamente; si persiste, el pliego puede ser demasiado corto o ilegible."
                ),
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al analizar con IA: {str(e)[:200]}")

    # Normalizar campos
    discrepancias = resultado.get("discrepancias") or []
    tiene_disc    = bool(discrepancias) or bool(resultado.get("tiene_discrepancias"))
    resultado["tiene_discrepancias"]  = tiene_disc
    resultado["total_discrepancias"]  = len(discrepancias)

    # 5. Generar PDF si hay discrepancias
    pdf_bytes   = None
    pdf_filename = None

    if tiene_disc and discrepancias:
        try:
            pdf_bytes = _build_pdf_observaciones(resultado, nombre_empresa, nit_empresa)
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="fpdf2 no está instalado. Ejecuta: pip install fpdf2",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error generando PDF: {str(e)[:200]}")

        # 6. Guardar PDF + metadata
        proceso_id_safe = re.sub(r"[^\w\-]", "_", body.proceso_id or "proceso")[:40]
        pdf_filename    = f"{proceso_id_safe}_observaciones.pdf"
        carpeta         = Path(f"./clientes/{body.cliente_id}/observaciones")
        carpeta.mkdir(parents=True, exist_ok=True)

        (carpeta / pdf_filename).write_bytes(pdf_bytes)

        meta = {
            "proceso_id":         body.proceso_id,
            "proceso":            resultado.get("proceso", ""),
            "entidad":            resultado.get("entidad", ""),
            "total_discrepancias": len(discrepancias),
            "fecha_generacion":   datetime.now().isoformat(),
            "pdf_filename":       pdf_filename,
        }
        (carpeta / f"{proceso_id_safe}_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return {
        "tiene_discrepancias":         tiene_disc,
        "total_discrepancias":         len(discrepancias),
        "proceso":                     resultado.get("proceso", ""),
        "entidad":                     resultado.get("entidad", ""),
        "fecha_cierre_observaciones":  resultado.get("fecha_cierre_observaciones"),
        "discrepancias":               discrepancias,
        "pdf_disponible":              pdf_bytes is not None,
        "pdf_filename":                pdf_filename,
    }


# ── GET /api/observaciones/pdf/{cliente_id}/{filename} ────────────────────────

@router.get("/observaciones/pdf/{cliente_id}/{filename}")
def descargar_pdf_observaciones(
    cliente_id: str,
    filename:   str,
    authorization: str = Header(None),
):
    """Descarga el PDF de observaciones previamente generado."""
    from routers.auth import require_auth
    require_auth(authorization)

    # Sanitizar: solo chars seguros para evitar path traversal
    if not re.match(r"^[\w\-\.]+$", filename):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")

    ruta = Path(f"./clientes/{cliente_id}/observaciones/{filename}")
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="PDF no encontrado. Genera las observaciones primero.")

    return Response(
        content=ruta.read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Generador PDF ─────────────────────────────────────────────────────────────

def _build_pdf_observaciones(resultado: dict, nombre_empresa: str, nit: str) -> bytes:
    """Construye el PDF de Observaciones al Pliego usando fpdf2."""
    from fpdf import FPDF, XPos, YPos

    proceso       = resultado.get("proceso", "Proceso de contratacion")
    entidad       = resultado.get("entidad", "Entidad Estatal")
    fecha_cierre  = resultado.get("fecha_cierre_observaciones") or ""
    discrepancias = resultado.get("discrepancias", [])
    fecha_hoy     = datetime.now().strftime("%d/%m/%Y")

    # fpdf2 >= 2.5 no resetea X al margen izquierdo tras multi_cell por defecto;
    # se debe pasar new_x/new_y explícitamente en cada llamada.
    NL  = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}   # salto de línea + volver al margen
    NR  = {"new_x": XPos.RIGHT,   "new_y": YPos.TOP}    # continuar en la misma línea

    class _PDF(FPDF):
        def __init__(self):
            super().__init__()
            self.set_margins(15, 15, 15)  # izquierda, arriba, derecha (mm)

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

    # ══ PORTADA ══════════════════════════════════════════════════════════════
    pdf.add_page()

    # Banda superior oscura (cubre todo el ancho de página)
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

    # Datos del proceso — etiqueta fija 48 mm + valor en el ancho restante
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

    # Recuadro total de observaciones
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

    # ══ CUERPO — una página por discrepancia ═════════════════════════════════
    for d in discrepancias:
        pdf.add_page()

        # Cabecera de la observación
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

        # Recuadro especial: texto formal de la observación
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

        # Separador
        pdf.set_draw_color(200, 200, 200)
        pdf.set_line_width(0.3)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())

    return bytes(pdf.output())
