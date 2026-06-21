# -*- coding: utf-8 -*-
"""Router de generación de reportes PDF ejecutivos — SIACO v3.0"""
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter(tags=["reportes"])


def limpiar_texto_pdf(texto: str) -> str:
    """Reemplaza caracteres fuera del rango latin-1 que Helvetica no soporta."""
    if not texto:
        return ""
    reemplazos = [
        ("≥", ">="), ("≤", "<="),
        ("→", "->"), ("←", "<-"),
        ("—", "-"), ("–", "-"),
        ("✅", "[OK]"), ("☑", "[OK]"), ("✓", "[OK]"),
        ("❌", "[NO]"), ("✗", "[NO]"), ("✘", "[NO]"),
        ("⚠️", "[!]"), ("⚠", "[!]"),
        ("°", " grados"),
        ("•", "-"), ("·", "-"),
        (" ", " "),   # non-breaking space
        ("©", "(c)"), ("®", "(R)"), ("™", "(TM)"),
        ("…", "..."),
        (""", '"'), (""", '"'), ("'", "'"), ("'", "'"),
    ]
    for orig, reemplazo in reemplazos:
        texto = texto.replace(orig, reemplazo)
    # Eliminar cualquier carácter fuera de latin-1 que haya quedado
    return texto.encode("latin-1", errors="replace").decode("latin-1")


class ReporteBody(BaseModel):
    analisis: dict
    licitacion: dict
    cliente_nombre: str = "Cliente SIACO"


@router.post("/reportes/pdf")
def generar_pdf(body: ReporteBody, authorization: str = Header(None)):
    """Genera PDF ejecutivo del análisis de pliego. Retorna bytes del PDF."""
    from routers.auth import require_auth
    require_auth(authorization)

    try:
        pdf_bytes = _build_pdf(body.analisis, body.licitacion, body.cliente_nombre)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="fpdf2 no está instalado. Ejecuta: pip install fpdf2",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando PDF: {str(e)[:200]}")

    proceso = body.licitacion.get("id_del_proceso", "proceso")[:20].replace("/", "-")
    filename = f"siaco_{proceso}_{datetime.now().strftime('%Y%m%d')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_pdf(analisis: dict, licitacion: dict, cliente_nombre: str) -> bytes:
    """Construye el PDF ejecutivo usando fpdf2."""
    from fpdf import FPDF

    # ── Datos principales ──────────────────────────
    score_fin = analisis.get("score", analisis.get("score_financiero", 0))
    score_jur = analisis.get("score_juridico", 0)
    score_global = round((score_fin + score_jur) / 2)
    concepto = analisis.get("concepto_financiero") or analisis.get("accion", "REVISAR")
    concepto_jur = analisis.get("concepto_juridico", "")

    objeto = licitacion.get("nombre_del_procedimiento", licitacion.get("objeto", "N/A"))
    entidad = licitacion.get("entidad", "N/A")
    valor = licitacion.get("precio_base", licitacion.get("valor", "N/A"))
    proceso_id = licitacion.get("id_del_proceso", "")

    checklist = analisis.get("checklist_financiero", analisis.get("pdf_checklist", []))
    requisitos = analisis.get("requisitos_habilitantes", [])
    citas = analisis.get("articulos_aplicables", [])
    riesgos = analisis.get("riesgos_juridicos", [])
    docs_faltantes = analisis.get("documentos_faltantes", analisis.get("pdf_documentos", []))
    recomendaciones = analisis.get("recomendaciones", [])
    motivo = analisis.get("motivo", analisis.get("pdf_argumentos", ""))

    # ── Colores del concepto ───────────────────────
    if "VIABLE" in concepto and "NO" not in concepto:
        concepto_color = (40, 167, 69)
    elif "CONDICIONAL" in concepto or "REVISAR" in concepto:
        concepto_color = (255, 152, 0)
    else:
        concepto_color = (220, 53, 69)

    # ── PDF ───────────────────────────────────────
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Fuentes
    pdf.set_font("Helvetica", "B", 22)

    # ── PORTADA ───────────────────────────────────
    pdf.set_fill_color(10, 10, 10)
    pdf.rect(0, 0, 210, 60, "F")

    pdf.set_y(12)
    pdf.set_text_color(198, 242, 78)
    pdf.set_font("Helvetica", "B", 28)
    pdf.cell(0, 10, "SIACO v3.0", ln=True, align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(180, 180, 180)
    pdf.cell(0, 8, "Sistema de Inteligencia para Contratacion Publica SECOP II", ln=True, align="C")
    pdf.set_text_color(120, 120, 120)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"Reporte generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")

    pdf.set_y(68)
    pdf.set_text_color(30, 30, 30)

    # ── Cliente y proceso ─────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 8, limpiar_texto_pdf(f"Cliente: {cliente_nombre}"), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(0, 6, limpiar_texto_pdf(f"Proceso: {objeto}"))
    pdf.cell(0, 6, limpiar_texto_pdf(f"Entidad: {entidad}"), ln=True)
    _fmt_valor = f"COP {float(valor):,.0f}" if str(valor).replace(".", "").isdigit() else f"COP {valor}"
    pdf.cell(0, 6, limpiar_texto_pdf(f"Valor base: {_fmt_valor}"), ln=True)
    if proceso_id:
        pdf.cell(0, 6, limpiar_texto_pdf(f"ID Proceso: {proceso_id}"), ln=True)
    pdf.ln(4)

    # ── Score global ──────────────────────────────
    pdf.set_fill_color(*concepto_color)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 14)
    label_concepto = concepto if "VIABLE" in concepto or "CONDICIONAL" in concepto else "REVISAR"
    pdf.cell(0, 12, f"  CONCEPTO: {label_concepto}   |   SCORE GLOBAL: {score_global}/100", ln=True, fill=True)
    pdf.ln(2)

    # Scores individuales
    pdf.set_text_color(50, 50, 50)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(95, 8, f"Score Financiero: {score_fin}/100", border=1, align="C")
    pdf.cell(95, 8, f"Score Juridico: {score_jur}/100", border=1, align="C", ln=True)
    pdf.ln(4)

    # ── Resumen ejecutivo ──────────────────────────
    if motivo:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, "Resumen Ejecutivo", ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(0, 5, limpiar_texto_pdf(str(motivo)[:500]))
        pdf.ln(3)

    # ── Checklist financiero ───────────────────────
    if checklist:
        _section_header(pdf, "Evaluacion Financiera - Requisitos Habilitantes")
        _tabla_checklist(pdf, checklist)
        pdf.ln(3)

    # ── Requisitos jurídicos ───────────────────────
    if requisitos:
        _section_header(pdf, "Evaluacion Juridica - Experiencia y Habilitantes")
        _tabla_requisitos(pdf, requisitos)
        pdf.ln(3)

    # ── Citas normativas ──────────────────────────
    if citas:
        _section_header(pdf, "Marco Normativo Aplicado")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(40, 40, 40)
        for cita in citas[:10]:
            pdf.set_x(15)
            pdf.multi_cell(180, 5, limpiar_texto_pdf(f"- {cita}"))
        pdf.ln(2)

    # ── Riesgos ───────────────────────────────────
    if riesgos:
        _section_header(pdf, "Riesgos Identificados")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(180, 60, 40)
        for r in riesgos[:8]:
            pdf.set_x(15)
            pdf.multi_cell(180, 5, limpiar_texto_pdf(f"[!] {r}"))
        pdf.ln(2)

    # ── Documentos a gestionar ────────────────────
    if docs_faltantes:
        _section_header(pdf, "Documentos a Gestionar / Subsanar")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(60, 60, 60)
        for d in docs_faltantes[:10]:
            pdf.set_x(15)
            pdf.multi_cell(180, 5, limpiar_texto_pdf(f"[ ] {d}"))
        pdf.ln(2)

    # ── Recomendaciones ───────────────────────────
    if recomendaciones:
        _section_header(pdf, "Plan de Accion - Recomendaciones")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(40, 80, 40)
        for i, rec in enumerate(recomendaciones[:8], 1):
            pdf.set_x(15)
            pdf.multi_cell(180, 5, limpiar_texto_pdf(f"{i}. {rec}"))
        pdf.ln(2)

    # ── Pie de página ─────────────────────────────
    pdf.set_y(-20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "SIACO v3.0 - Inteligencia para Contratacion Publica | Analisis generado con IA + Biblioteca Normativa CCE", align="C")

    return bytes(pdf.output())


def _section_header(pdf, titulo: str):
    pdf.set_fill_color(230, 230, 230)
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 8, limpiar_texto_pdf(f"  {titulo}"), ln=True, fill=True)
    pdf.ln(1)


def _tabla_checklist(pdf, checklist: list):
    col_w = [65, 40, 50, 20]
    headers = ["Requisito", "Exigido", "Empresa tiene", "Cumple"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(210, 210, 210)
    pdf.set_text_color(20, 20, 20)
    for h, w in zip(headers, col_w):
        pdf.cell(w, 7, h, border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for item in checklist[:12]:
        cumple = item.get("cumple", False)
        pdf.set_fill_color(240, 255, 240) if cumple else pdf.set_fill_color(255, 240, 240)
        pdf.set_text_color(20, 100, 20) if cumple else pdf.set_text_color(150, 20, 20)

        req = limpiar_texto_pdf(str(item.get("requisito", ""))[:35])
        exig = limpiar_texto_pdf(str(item.get("valor_pliego", ""))[:20])
        tiene = limpiar_texto_pdf(str(item.get("valor_empresa", ""))[:28])
        ok = "SI" if cumple else "NO"

        pdf.cell(col_w[0], 6, req, border=1, fill=True)
        pdf.cell(col_w[1], 6, exig, border=1, fill=True)
        pdf.cell(col_w[2], 6, tiene, border=1, fill=True)
        pdf.cell(col_w[3], 6, ok, border=1, fill=True, align="C")
        pdf.ln()


def _tabla_requisitos(pdf, requisitos: list):
    col_w = [55, 40, 45, 25, 22]
    headers = ["Requisito", "Exigido", "Cliente tiene", "Cumple", "Subsanable"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(210, 210, 210)
    pdf.set_text_color(20, 20, 20)
    for h, w in zip(headers, col_w):
        pdf.cell(w, 7, h, border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for item in requisitos[:12]:
        if not isinstance(item, dict):
            continue
        cumple = item.get("cumple", False)
        pdf.set_fill_color(240, 255, 240) if cumple else pdf.set_fill_color(255, 240, 240)
        pdf.set_text_color(20, 100, 20) if cumple else pdf.set_text_color(150, 20, 20)

        req = limpiar_texto_pdf(str(item.get("requisito", ""))[:28])
        exig = limpiar_texto_pdf(str(item.get("exigido", ""))[:20])
        tiene = limpiar_texto_pdf(str(item.get("cliente_tiene", ""))[:22])
        ok = "SI" if cumple else "NO"
        sub = "Si" if item.get("subsanable", True) else "NO"

        pdf.cell(col_w[0], 6, req, border=1, fill=True)
        pdf.cell(col_w[1], 6, exig, border=1, fill=True)
        pdf.cell(col_w[2], 6, tiene, border=1, fill=True)
        pdf.cell(col_w[3], 6, ok, border=1, fill=True, align="C")
        pdf.cell(col_w[4], 6, sub, border=1, fill=True, align="C")
        pdf.ln()
