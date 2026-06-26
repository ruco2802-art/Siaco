# -*- coding: utf-8 -*-
"""Generador del contrato de servicios SIACO en formato .docx"""
import io
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


# ── Helpers ──────────────────────────────────────────────────────────────────

def _add_borders(table):
    """Agrega bordes simples a una tabla."""
    tbl = table._tbl
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)
    tblBorders = OxmlElement("w:tblBorders")
    for name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{name}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "000000")
        tblBorders.append(el)
    tblPr.append(tblBorders)


def _par(doc, text="", bold=False, size=11, align=WD_ALIGN_PARAGRAPH.LEFT, space_after=6):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    run.bold = bold
    run.font.name = "Calibri"
    run.font.size = Pt(size)
    return p


def _section_heading(doc, num, title):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(f"{num}. {title}")
    run.bold = True
    run.font.name = "Calibri"
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(0x0D, 0x3D, 0x6B)   # azul oscuro
    return p


def _body(doc, text, space_after=5):
    return _par(doc, text, size=11, space_after=space_after)


def _checkbox_line(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(1)
    p.paragraph_format.space_after = Pt(3)
    run = p.add_run(f"☐  {text}")
    run.font.name = "Calibri"
    run.font.size = Pt(11)
    return p


def _bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    run = p.runs[0] if p.runs else p.add_run()
    run.font.name = "Calibri"
    run.font.size = Pt(11)
    # python-docx List Bullet adds the text via the style; set explicitly
    for r in p.runs:
        r.text = ""
    r = p.add_run(text)
    r.font.name = "Calibri"
    r.font.size = Pt(11)
    return p


def _table_cell(cell, text, bold=False, center=False, shaded=False):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(text)
    run.bold = bold
    run.font.name = "Calibri"
    run.font.size = Pt(10)
    if shaded:
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:color"), "auto")
        shading.set(qn("w:fill"), "D9E2F3")
        cell._tc.get_or_add_tcPr().append(shading)


# ── Generador principal ───────────────────────────────────────────────────────

def generar_docx(destino=None):
    """
    Genera el contrato de servicios SIACO.
    destino: path de archivo o objeto BytesIO. Si es None, retorna BytesIO.
    """
    doc = Document()

    # Márgenes
    sec = doc.sections[0]
    for attr in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(sec, attr, Cm(2.5))

    # Footer
    footer_par = sec.footer.paragraphs[0]
    footer_par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_run = footer_par.add_run(
        "SIACO — Sistema Inteligente de Análisis de Contratación Pública  |  Neiva, Huila, Colombia"
    )
    footer_run.font.name = "Calibri"
    footer_run.font.size = Pt(9)
    footer_run.font.color.rgb = RGBColor(0x70, 0x70, 0x70)

    # ── TÍTULO ───────────────────────────────────────────────────────────────
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(4)
    t1 = title.add_run("ACUERDO DE SERVICIOS Y AUTORIZACIÓN DE TRATAMIENTO DE DATOS")
    t1.bold = True
    t1.font.name = "Calibri"
    t1.font.size = Pt(14)

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(14)
    t2 = subtitle.add_run("SIACO — Sistema Inteligente de Análisis de Contratación Pública")
    t2.bold = True
    t2.font.name = "Calibri"
    t2.font.size = Pt(12)
    t2.font.color.rgb = RGBColor(0x0D, 0x3D, 0x6B)

    _par(doc, "Suscrito en Neiva, Huila, Colombia, el día ___ del mes de ___________ de 20____",
         align=WD_ALIGN_PARAGRAPH.CENTER, size=10, space_after=14)

    # ── SECCIÓN 1: PARTES ────────────────────────────────────────────────────
    _section_heading(doc, 1, "PARTES DEL ACUERDO")
    _body(doc, "EL PROVEEDOR: SIACO, operado por _____________________________________, "
               "identificado con CC/NIT _______________________, con domicilio en "
               "Neiva, Huila, Colombia. Correo de contacto: siaco@siaco.co")
    _body(doc, "EL CLIENTE: _____________________________________, identificado con "
               "NIT _______________________, representado legalmente por "
               "_____________________________________, identificado con CC _______________________. "
               "Correo electrónico: _____________________________________")

    # ── SECCIÓN 2: OBJETO ────────────────────────────────────────────────────
    _section_heading(doc, 2, "OBJETO DEL CONTRATO")
    _body(doc, "El presente acuerdo regula la prestación del servicio de inteligencia de "
               "contratación pública denominado SIACO, que comprende:")
    for item in [
        "Búsqueda y monitoreo automatizado de oportunidades en el portal SECOP II.",
        "Análisis de pliegos de condiciones mediante inteligencia artificial (Claude Sonnet).",
        "Scoring de relevancia de contratos según el perfil técnico del CLIENTE.",
        "Generación de observaciones al pliego en formato PDF.",
        "Auditoría de pliegos y alertas de fechas de cierre.",
        "Gestión de expedientes y seguimiento de procesos.",
        "Acceso multiusuario según el plan contratado.",
    ]:
        _bullet(doc, item)

    # ── SECCIÓN 3: PLAN CONTRATADO ───────────────────────────────────────────
    _section_heading(doc, 3, "PLAN DE SERVICIOS CONTRATADO")
    _body(doc, "El CLIENTE selecciona uno de los siguientes planes (marque con X):")
    _checkbox_line(doc, "Plan Básico — $490.000 COP/mes + IVA")
    _checkbox_line(doc, "Plan Premium — $990.000 COP/mes + IVA")
    _checkbox_line(doc, "Plan Agencia (multi-cliente) — $1.800.000 COP/mes + IVA")
    _checkbox_line(doc, "Plan Personalizado — Valor acordado en oferta formal adjunta")

    # ── SECCIÓN 4: COMISIONES Y PAGOS ────────────────────────────────────────
    _section_heading(doc, 4, "HONORARIOS, COMISIONES Y FORMA DE PAGO")
    _body(doc, "Las tarifas y características de cada plan son las siguientes:")

    headers_com = ["Característica", "Plan Básico", "Plan Premium", "Plan Agencia"]
    rows_com = [
        ["Valor mensual + IVA",      "$490.000",   "$990.000",   "$1.800.000"],
        ["Búsqueda SECOP II",        "Ilimitada",  "Ilimitada",  "Ilimitada"],
        ["Análisis IA por búsqueda", "50 contratos","200 contratos","Ilimitados"],
        ["Auditorías de pliego",     "5/mes",       "Ilimitadas", "Ilimitadas"],
        ["Observaciones al pliego",  "3/mes",       "Ilimitadas", "Ilimitadas"],
        ["Perfiles de cliente",      "1",           "1",          "Hasta 10"],
        ["Reportes PDF exportables", "5/mes",       "Ilimitados", "Ilimitados"],
        ["Inteligencia competitiva", "No incluido", "Incluido",   "Incluido"],
        ["Soporte técnico",          "Email 72h",   "Email 24h",  "Prioritario 8h"],
        ["Forma de pago",            "Mensual anticipado", "Mensual anticipado", "Mensual anticipado"],
    ]

    tbl_com = doc.add_table(rows=1 + len(rows_com), cols=4)
    tbl_com.alignment = WD_TABLE_ALIGNMENT.CENTER
    _add_borders(tbl_com)
    for j, h in enumerate(headers_com):
        _table_cell(tbl_com.rows[0].cells[j], h, bold=True, center=True, shaded=True)
    for i, row in enumerate(rows_com):
        for j, val in enumerate(row):
            _table_cell(tbl_com.rows[i + 1].cells[j], val, center=(j > 0))
    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    _body(doc, "PARÁGRAFO: El pago se realizará mediante transferencia bancaria o PSE a la "
               "cuenta indicada por EL PROVEEDOR en la factura electrónica correspondiente. "
               "El incumplimiento en el pago generará intereses de mora a la tasa máxima legal vigente.")

    # ── SECCIÓN 5: OBLIGACIONES DE SIACO ─────────────────────────────────────
    _section_heading(doc, 5, "OBLIGACIONES DE SIACO (EL PROVEEDOR)")
    for item in [
        "Mantener la plataforma disponible con un nivel de servicio (SLA) mínimo del 95% mensual.",
        "Actualizar la información proveniente de SECOP II con una frecuencia mínima de cada 24 horas.",
        "Responder solicitudes de soporte técnico dentro de los plazos indicados en el plan contratado.",
        "Garantizar la confidencialidad de la información suministrada por EL CLIENTE.",
        "Notificar con al menos 15 días de anticipación cualquier cambio tarifario o de condiciones.",
        "Mantener copias de seguridad de los datos del CLIENTE durante la vigencia del acuerdo.",
    ]:
        _bullet(doc, item)

    # ── SECCIÓN 6: OBLIGACIONES DEL CLIENTE ──────────────────────────────────
    _section_heading(doc, 6, "OBLIGACIONES DEL CLIENTE")
    for item in [
        "Suministrar información veraz, completa y actualizada sobre su empresa y perfil de contratación.",
        "Utilizar la plataforma exclusivamente para los fines legítimos de búsqueda y análisis de contratos públicos.",
        "No compartir sus credenciales de acceso con terceros no autorizados.",
        "Efectuar los pagos acordados dentro de los primeros cinco (5) días hábiles de cada período.",
        "Informar a SIACO sobre cualquier inexactitud detectada en los análisis generados.",
        "Cumplir con la normativa colombiana de contratación pública al presentar sus propuestas.",
    ]:
        _bullet(doc, item)

    # ── SECCIÓN 7: CONFIDENCIALIDAD ───────────────────────────────────────────
    _section_heading(doc, 7, "CONFIDENCIALIDAD")
    _body(doc, "Ambas partes se obligan recíprocamente a mantener estricta reserva sobre la "
               "información técnica, comercial, estratégica y de negocio que se intercambie "
               "durante la ejecución de este acuerdo. Esta obligación se extiende hasta dos (2) "
               "años después de la terminación del acuerdo por cualquier causa.")
    _body(doc, "Se exceptúa de esta obligación la información que: (i) sea de dominio público "
               "sin responsabilidad de las partes; (ii) deba revelarse por orden de autoridad "
               "judicial o administrativa competente; (iii) haya sido conocida previamente "
               "de manera lícita.")

    # ── SECCIÓN 8: DATOS PERSONALES ───────────────────────────────────────────
    _section_heading(doc, 8, "AUTORIZACIÓN DE TRATAMIENTO DE DATOS PERSONALES")
    _body(doc, "De conformidad con la Ley 1581 de 2012, el Decreto 1377 de 2013 y las demás "
               "normas concordantes, EL CLIENTE en calidad de Titular autoriza a SIACO en "
               "calidad de Responsable del Tratamiento para recolectar, almacenar, usar, "
               "circular, actualizar y suprimir sus datos personales con las siguientes finalidades:")
    for item in [
        "Prestar los servicios contratados y administrar la relación comercial.",
        "Enviar notificaciones, alertas de oportunidades y comunicaciones del servicio.",
        "Generar reportes, estadísticas y análisis de uso de la plataforma.",
        "Cumplir con obligaciones legales, contables y tributarias.",
    ]:
        _bullet(doc, item)
    _body(doc, "EL CLIENTE podrá ejercer sus derechos de acceso, corrección, supresión, "
               "revocación y queja ante la Superintendencia de Industria y Comercio (SIC) "
               "escribiendo a la dirección de correo electrónico del PROVEEDOR. "
               "La Política de Tratamiento de Datos de SIACO se encuentra disponible en la plataforma.")

    # ── SECCIÓN 9: VIGENCIA Y TERMINACIÓN ────────────────────────────────────
    _section_heading(doc, 9, "VIGENCIA, TERMINACIÓN Y LEY APLICABLE")
    _body(doc, "VIGENCIA: El presente acuerdo tendrá una vigencia de ___ mes(es) a partir de la "
               "fecha de suscripción, renovándose automáticamente por períodos iguales salvo que "
               "alguna de las partes manifieste su intención de no renovarlo con al menos "
               "treinta (30) días de anticipación.")
    _body(doc, "TERMINACIÓN: Cualquiera de las partes podrá terminar el acuerdo: "
               "(i) por mutuo acuerdo; (ii) por incumplimiento grave de la otra parte "
               "no subsanado dentro de los diez (10) días hábiles siguientes al requerimiento escrito; "
               "(iii) unilateralmente con aviso previo de treinta (30) días.")
    _body(doc, "LEY APLICABLE Y JURISDICCIÓN: Este acuerdo se rige por las leyes de la República "
               "de Colombia. Para dirimir cualquier controversia, las partes se someten a la "
               "jurisdicción de los jueces y tribunales de la ciudad de Neiva, Huila, "
               "renunciando expresamente a fueros distintos.")

    # ── DECLARACIÓN FINAL ─────────────────────────────────────────────────────
    doc.add_paragraph()
    _par(doc, "Las partes declaran haber leído íntegramente el presente acuerdo, "
              "comprenderlo en su totalidad y suscribirlo de manera libre y voluntaria.",
         size=11, space_after=20)

    # ── TABLA DE FIRMAS ───────────────────────────────────────────────────────
    _par(doc, "FIRMAS DE LAS PARTES", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
         size=11, space_after=8)

    sig_data = [
        ("Por EL PROVEEDOR (SIACO)", "Por EL CLIENTE"),
        ("Nombre: ________________________", "Nombre: ________________________"),
        ("CC / NIT: ______________________", "NIT: ___________________________"),
        ("Cargo:  ________________________", "Cargo:  ________________________"),
        ("", ""),
        ("Firma:  ________________________", "Firma:  ________________________"),
        ("Fecha:  ________________________", "Fecha:  ________________________"),
    ]
    tbl_sig = doc.add_table(rows=len(sig_data), cols=2)
    tbl_sig.alignment = WD_TABLE_ALIGNMENT.CENTER
    _add_borders(tbl_sig)
    for i, (left, right) in enumerate(sig_data):
        bold_row = i == 0
        shaded_row = i == 0
        _table_cell(tbl_sig.rows[i].cells[0], left, bold=bold_row, center=bold_row, shaded=shaded_row)
        _table_cell(tbl_sig.rows[i].cells[1], right, bold=bold_row, center=bold_row, shaded=shaded_row)

    # ── GUARDAR ───────────────────────────────────────────────────────────────
    if destino is None:
        destino = io.BytesIO()
    doc.save(destino)
    return destino
