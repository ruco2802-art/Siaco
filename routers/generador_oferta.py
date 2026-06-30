# -*- coding: utf-8 -*-
"""Generador de documentos formales de oferta — SIACO v3.0"""
import io
import json
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter(tags=["generador_oferta"])

FORMULARIOS_DIR = Path("biblioteca_normativa/formularios")
CLIENTES_DIR    = Path("clientes")

MESES_ES = ["enero","febrero","marzo","abril","mayo","junio",
            "julio","agosto","septiembre","octubre","noviembre","diciembre"]


# ── Utilidades ────────────────────────────────────────────────────────────────

def numero_a_letras(valor: float) -> str:
    """
    Convierte un valor monetario a texto en español para documentos legales.
    Ej: 197_500_000 → 'CIENTO NOVENTA Y SIETE MILLONES QUINIENTOS MIL PESOS M/CTE'
    """
    n = int(round(abs(valor)))
    if n == 0:
        return "CERO PESOS M/CTE"

    ONES  = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE",
             "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS",
             "DIECISIETE", "DIECIOCHO", "DIECINUEVE"]
    TENS  = ["", "DIEZ", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA",
             "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
    HUNDS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS",
             "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]
    VEINTI = {21: "VEINTIÚN", 22: "VEINTIDÓS", 23: "VEINTITRÉS", 24: "VEINTICUATRO",
              25: "VEINTICINCO", 26: "VEINTISÉIS", 27: "VEINTISIETE",
              28: "VEINTIOCHO", 29: "VEINTINUEVE"}

    def _grupo(m: int) -> str:
        if m == 0:   return ""
        if m == 100: return "CIEN"
        parts = []
        c = m // 100
        r = m % 100
        if c: parts.append(HUNDS[c])
        if 1 <= r <= 19:
            parts.append(ONES[r])
        elif r == 20:
            parts.append("VEINTE")
        elif 21 <= r <= 29:
            parts.append(VEINTI[r])
        elif r >= 30:
            d, u = divmod(r, 10)
            s = TENS[d] + (f" Y {ONES[u]}" if u else "")
            parts.append(s)
        return " ".join(parts)

    resultado = []
    # Billones (10^12)
    if n >= 1_000_000_000_000:
        b = n // 1_000_000_000_000; n %= 1_000_000_000_000
        resultado.append(f"{_grupo(b)} {'BILLÓN' if b == 1 else 'BILLONES'}")
    # Miles de millones (10^9)
    if n >= 1_000_000_000:
        mm = n // 1_000_000_000; n %= 1_000_000_000
        if mm == 1:
            resultado.append("MIL MILLONES")
        else:
            resultado.append(f"{_grupo(mm)} MIL MILLONES")
    # Millones (10^6)
    if n >= 1_000_000:
        m = n // 1_000_000; n %= 1_000_000
        resultado.append(f"{_grupo(m)} {'MILLÓN' if m == 1 else 'MILLONES'}")
    # Miles (10^3)
    if n >= 1_000:
        k = n // 1_000; n %= 1_000
        resultado.append("MIL" if k == 1 else f"{_grupo(k)} MIL")
    # Resto
    if n > 0:
        resultado.append(_grupo(n))

    prefijo = "MENOS " if valor < 0 else ""
    return prefijo + " ".join(resultado) + " PESOS M/CTE"


def _fmt_cop(v: float) -> str:
    """Formato colombiano: $ 1.234.567"""
    return f"${int(round(v)):,}".replace(",", ".")


def _fmt_fecha() -> str:
    hoy = date.today()
    return f"{hoy.day} de {MESES_ES[hoy.month-1]} de {hoy.year}"


def _cargar_perfil(cliente_id: str) -> dict:
    """Carga perfil del cliente: /tmp → Supabase (mismo patrón que routers/perfil.py)."""
    cache = Path(f"/tmp/siaco/{cliente_id}/perfil.json")
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        from supabase_client import sb_download
        data = sb_download(f"clientes/{cliente_id}/perfil.json")
        if data:
            perfil = json.loads(data.decode("utf-8"))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
            return perfil
    except Exception:
        pass
    return {}


def _cargar_proceso(cliente_id: str, proceso_id: str) -> dict:
    """Busca datos del proceso en expedientes e historial (fallback disco local)."""
    candidatos = [
        CLIENTES_DIR / cliente_id / "expedientes.json",
        CLIENTES_DIR / cliente_id / "historial" / "licitaciones.json",
    ]
    for ruta in candidatos:
        if not ruta.exists():
            continue
        try:
            data = json.loads(ruta.read_text(encoding="utf-8"))
            lista = data if isinstance(data, list) else data.get("contratos", [])
            for item in lista:
                pid = (item.get("id_del_proceso") or item.get("referencia_del_proceso")
                       or item.get("proceso_id") or item.get("id") or "")
                if pid == proceso_id or proceso_id in str(item):
                    return item
        except Exception:
            continue
    return {}


def _cargar_params_sesion(cliente_id: str) -> dict:
    """Lee los parámetros del proceso guardados en sesión por analizar_pliego."""
    try:
        from contexto_sesion import obtener_contexto_sesion
        ctx = obtener_contexto_sesion(cliente_id)
        return ctx.get("parametros_proceso", {})
    except Exception:
        return {}


def _vars_base(cliente_id: str, proceso_id: str) -> dict:
    """Arma diccionario de sustitución con datos del cliente y proceso."""
    perfil  = _cargar_perfil(cliente_id)
    proceso = _cargar_proceso(cliente_id, proceso_id)
    sesion  = _cargar_params_sesion(cliente_id)   # parámetros guardados por analizar_pliego

    fin = perfil.get("financiero", {})
    patr = float(fin.get("patrimonio_liquido", perfil.get("patrimonio_liquido", 0)))

    # Para entidad y objeto: sesión (más reciente) > expedientes/historial > placeholder
    nombre_entidad = (proceso.get("nombre_entidad_compradora")
                      or proceso.get("entidad")
                      or sesion.get("entidad", "[ENTIDAD CONTRATANTE]"))
    objeto_proceso = (proceso.get("nombre_del_procedimiento")
                      or proceso.get("objeto")
                      or sesion.get("objeto", "[OBJETO DEL CONTRATO]"))
    plazo = str(proceso.get("plazo_meses", sesion.get("plazo_meses", "[PLAZO]")))

    return {
        "razon_social":         perfil.get("nombre", perfil.get("razon_social", "[RAZÓN SOCIAL]")),
        "nit":                  perfil.get("nit", "[NIT]"),
        "nombre_representante": perfil.get("representante_legal", "[REPRESENTANTE LEGAL]"),
        "cargo_representante":  perfil.get("cargo_representante", "Representante Legal"),
        "cedula_representante": perfil.get("cedula_representante", "[C.C.]"),
        "direccion":            perfil.get("direccion", "[DIRECCIÓN]"),
        "telefono":             perfil.get("telefono", perfil.get("contacto_whatsapp", "[TELÉFONO]")),
        "correo":               perfil.get("correo", perfil.get("contacto_email", "[CORREO]")),
        "ciudad":               perfil.get("ciudad", "Bogotá D.C."),
        "fecha":                _fmt_fecha(),
        "codigo_proceso":       proceso_id or "[CÓDIGO PROCESO]",
        "nombre_entidad":       nombre_entidad,
        "objeto_proceso":       objeto_proceso,
        "plazo_meses":          plazo,
        "plazo_meses_num":      plazo,
        "patrimonio_liquido":   _fmt_cop(patr),
    }


def _sustituir(plantilla: str, variables: dict) -> str:
    """Reemplaza todos los marcadores {campo} en la plantilla."""
    for k, v in variables.items():
        plantilla = plantilla.replace("{" + k + "}", str(v) if v is not None else "")
    return plantilla


def _generar_docx(titulo: str, contenido: str) -> bytes:
    """Crea un .docx con python-docx a partir de texto plano."""
    try:
        from docx import Document
        from docx.shared import Pt, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise HTTPException(status_code=500, detail="python-docx no disponible")

    doc = Document()

    # Márgenes
    for sec in doc.sections:
        sec.top_margin    = Cm(2.5)
        sec.bottom_margin = Cm(2.5)
        sec.left_margin   = Cm(3)
        sec.right_margin  = Cm(2.5)

    # Título
    t = doc.add_heading(titulo, level=1)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in t.runs:
        run.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)
        run.font.size      = Pt(14)

    doc.add_paragraph()

    # Contenido línea a línea
    for linea in contenido.split("\n"):
        linea = linea.rstrip()
        if linea.startswith("━"):
            doc.add_paragraph("─" * 70)
        elif linea.startswith("⚠️"):
            p = doc.add_paragraph()
            r = p.add_run(linea)
            r.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
            r.bold            = True
            r.font.size       = Pt(9)
        elif linea.strip() == "":
            doc.add_paragraph()
        else:
            p = doc.add_paragraph(linea)
            p.paragraph_format.space_after = Pt(2)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _tabla_docx_items(items: list) -> tuple[str, object]:
    """Retorna texto plano (para template) y función que agrega tabla a un doc."""
    lineas = []
    for i, it in enumerate(items, 1):
        nom  = it.get("nombre", it.get("descripcion", f"Ítem {i}"))
        und  = it.get("unidad", "und")
        cant = it.get("cantidad", 1)
        pu   = it.get("precio_unitario", 0)
        tot  = cant * pu
        lineas.append(f"  {i:>3}. {nom:<35} {und:<6} {cant:>8.2f}  {_fmt_cop(pu):>16}  {_fmt_cop(tot):>16}")
    return "\n".join(lineas) if lineas else "  [Sin ítems registrados]"


# ── Modelos ──────────────────────────────────────────────────────────────────

class DocRequest(BaseModel):
    cliente_id: str
    proceso_id: str

class FormularioEconomicoRequest(BaseModel):
    cliente_id:  str
    proceso_id:  str
    datos_apu:   dict = {}

class CapacidadResidualRequest(BaseModel):
    cliente_id:      str
    proceso_id:      str
    k_requerido:     float = 0.0
    contratos_vigentes: list[dict] = []

class PaqueteRequest(BaseModel):
    cliente_id:      str
    proceso_id:      str
    datos_apu:       dict = {}
    k_requerido:     float = 0.0
    contratos_vigentes: list[dict] = []


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/oferta/carta-presentacion")
def carta_presentacion(body: DocRequest, authorization: str = Header(None)):
    """Genera carta de presentación formal en Word."""
    from routers.auth import require_auth
    require_auth(authorization)

    vars_ = _vars_base(body.cliente_id, body.proceso_id)
    # valor placeholder — el usuario completará en Word
    vars_["valor_letras"] = "[VALOR EN LETRAS] PESOS M/CTE"
    vars_["valor_numeros"] = "[VALOR OFERTA]"

    tpl = (FORMULARIOS_DIR / "carta_presentacion.txt").read_text(encoding="utf-8")
    contenido = _sustituir(tpl, vars_)
    docx_bytes = _generar_docx("CARTA DE PRESENTACIÓN DE OFERTA", contenido)

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition":
                 f'attachment; filename="Carta_Presentacion_{body.proceso_id}.docx"'},
    )


@router.post("/oferta/formulario-economico")
def formulario_economico(body: FormularioEconomicoRequest, authorization: str = Header(None)):
    """Genera Formulario 1 — Propuesta Económica en Word."""
    from routers.auth import require_auth
    require_auth(authorization)

    vars_ = _vars_base(body.cliente_id, body.proceso_id)
    apu   = body.datos_apu
    cd    = apu.get("costos_directos", {})
    aiu_d = apu.get("aiu", {})

    materiales = apu.get("items_materiales", apu.get("materiales_lista", []))
    personal   = apu.get("items_personal", apu.get("personal_lista", []))
    equipos    = apu.get("items_equipos", apu.get("equipos_lista", []))
    todos_items = list(materiales) + list(personal) + list(equipos)

    precio_total = float(apu.get("precio_minimo", 0))

    vars_.update({
        "tabla_items":          _tabla_docx_items(todos_items),
        "subtotal_directos":    _fmt_cop(float(cd.get("subtotal", 0))),
        "admin_pct":            f"{aiu_d.get('admin_pct', 12):.1f}",
        "valor_admin":          _fmt_cop(float(aiu_d.get("administracion", 0))),
        "imprev_pct":           f"{aiu_d.get('imprevistos_pct', 3):.1f}",
        "valor_imprev":         _fmt_cop(float(aiu_d.get("imprevistos", 0))),
        "util_pct":             f"{aiu_d.get('utilidad_pct', 8):.1f}",
        "valor_util":           _fmt_cop(float(aiu_d.get("utilidad", 0))),
        "subtotal_aiu":         _fmt_cop(float(aiu_d.get("total_aiu", 0))),
        "valor_total":          _fmt_cop(precio_total),
        "valor_iva":            _fmt_cop(0),
        "valor_total_definitivo": _fmt_cop(precio_total),
        "valor_letras":         numero_a_letras(precio_total) if precio_total else "[VALOR EN LETRAS]",
    })

    tpl = (FORMULARIOS_DIR / "formulario_economico.txt").read_text(encoding="utf-8")
    contenido = _sustituir(tpl, vars_)
    docx_bytes = _generar_docx("FORMULARIO 1 – PROPUESTA ECONÓMICA", contenido)

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition":
                 f'attachment; filename="Formulario_Economico_{body.proceso_id}.docx"'},
    )


@router.post("/oferta/formato-experiencia")
def formato_experiencia(body: DocRequest, authorization: str = Header(None)):
    """Genera Formulario 2 — Experiencia del Proponente en Word."""
    from routers.auth import require_auth
    require_auth(authorization)

    vars_   = _vars_base(body.cliente_id, body.proceso_id)
    perfil  = _cargar_perfil(body.cliente_id)
    experiencias = perfil.get("contratos_experiencia",
                              perfil.get("experiencia_contratos", []))
    exp_agg = perfil.get("experiencia", {})

    # Construir tabla de texto
    if isinstance(experiencias, list) and experiencias:
        # Lista de contratos individuales (si el perfil los tiene)
        filas = ["  No. | Entidad/Cliente             | Objeto (resumen)           | Valor COP      | Inicio     | Fin        | % Part."]
        filas.append("  " + "-" * 120)
        for i, c in enumerate(experiencias, 1):
            ent   = str(c.get("entidad", c.get("cliente", "")))[:28]
            obj   = str(c.get("objeto", ""))[:27]
            val   = _fmt_cop(float(c.get("valor", 0)))
            ini   = str(c.get("fecha_inicio", c.get("inicio", "")))[:10]
            fin_c = str(c.get("fecha_fin", c.get("fin", "")))[:10]
            part  = str(c.get("porcentaje_participacion", c.get("participacion", 100)))
            filas.append(f"  {i:>3}  | {ent:<28} | {obj:<27} | {val:>14} | {ini:<10} | {fin_c:<10} | {part}%")
        tabla_exp = "\n".join(filas)
    elif isinstance(exp_agg, dict) and exp_agg.get("valor_acumulado"):
        # Datos agregados del perfil (ExperienciaModel)
        val_acum = float(exp_agg.get("valor_acumulado", 0))
        val_max  = float(exp_agg.get("valor_individual_max", 0))
        obj_sim  = exp_agg.get("objeto_similar", "")
        codigos  = exp_agg.get("codigos_unspsc", "")
        tabla_exp = (
            f"  EXPERIENCIA ACREDITADA (datos del perfil SIACO):\n"
            f"  Valor acumulado en contratos similares : {_fmt_cop(val_acum)}\n"
            f"  Contrato de mayor cuantía ejecutado   : {_fmt_cop(val_max)}\n"
            f"  Objeto similar declarado              : {obj_sim or '[pendiente]'}\n"
            f"  Códigos UNSPSC                        : {codigos or '[pendiente]'}\n"
            f"\n"
            f"  ⚠️  Complete la tabla individual con los contratos que acreditan la experiencia.\n"
            f"      Adjunte certificados de contratos o actas de liquidación como soporte."
        )
    else:
        tabla_exp = (
            "  [Sin contratos de experiencia registrados en el perfil]\n"
            "  Complete esta tabla con los contratos que acreditan la experiencia requerida.\n"
            "  Adjunte certificados de contratos o actas de liquidación como soporte."
        )

    vars_["tabla_experiencia"] = tabla_exp
    tpl      = (FORMULARIOS_DIR / "formulario_experiencia.txt").read_text(encoding="utf-8")
    contenido = _sustituir(tpl, vars_)
    docx_bytes = _generar_docx("FORMULARIO 2 – EXPERIENCIA DEL PROPONENTE", contenido)

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition":
                 f'attachment; filename="Formulario_Experiencia_{body.proceso_id}.docx"'},
    )


@router.post("/oferta/capacidad-residual")
def capacidad_residual(body: CapacidadResidualRequest, authorization: str = Header(None)):
    """Genera Formato K Residual — Capacidad de Contratación en Word."""
    from routers.auth import require_auth
    require_auth(authorization)

    vars_  = _vars_base(body.cliente_id, body.proceso_id)
    perfil = _cargar_perfil(body.cliente_id)
    patr   = float(perfil.get("patrimonio_liquido", 0))
    ochenta = patr * 0.8

    # Contratos en ejecución
    vigentes = body.contratos_vigentes or perfil.get("contratos_en_ejecucion", [])
    total_comp = sum(
        float(c.get("valor", 0)) * float(c.get("pct_pendiente", c.get("porcentaje_pendiente", 0))) / 100
        for c in vigentes
    )
    k_residual = ochenta - total_comp
    k_req      = body.k_requerido

    if vigentes:
        filas = ["  Contrato / Objeto                    | Valor total    | % pendiente | Compromiso"]
        filas.append("  " + "-" * 80)
        for c in vigentes:
            obj    = str(c.get("objeto", c.get("descripcion", "")))[:38]
            val    = float(c.get("valor", 0))
            pct    = float(c.get("pct_pendiente", c.get("porcentaje_pendiente", 0)))
            comp   = val * pct / 100
            filas.append(f"  {obj:<38} | {_fmt_cop(val):>14} | {pct:>11.1f}% | {_fmt_cop(comp):>14}")
        tabla_v = "\n".join(filas)
    else:
        tabla_v = "  [Sin contratos en ejecución a la fecha — o ingrese manualmente]"

    resultado_k = "CUMPLE ✓" if k_residual >= k_req else "NO CUMPLE ✗ — Verifique sus contratos en ejecución"

    vars_.update({
        "tabla_contratos_ejecucion":  tabla_v,
        "total_compromisos":          _fmt_cop(total_comp),
        "ochenta_pct_patrimonio":     _fmt_cop(ochenta),
        "k_residual":                 _fmt_cop(k_residual),
        "k_requerido":                _fmt_cop(k_req) if k_req else "[Ver pliego]",
        "resultado_k":                resultado_k,
    })

    tpl       = (FORMULARIOS_DIR / "formato_k_residual.txt").read_text(encoding="utf-8")
    contenido = _sustituir(tpl, vars_)
    docx_bytes = _generar_docx("CAPACIDAD RESIDUAL DE CONTRATACIÓN — FACTOR K", contenido)

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition":
                 f'attachment; filename="Capacidad_Residual_{body.proceso_id}.docx"'},
    )


@router.post("/oferta/paquete-completo")
def paquete_completo(body: PaqueteRequest, authorization: str = Header(None)):
    """Genera ZIP con todos los documentos de la oferta."""
    from routers.auth import require_auth
    require_auth(authorization)

    def _get_bytes(endpoint_fn, req_body):
        resp = endpoint_fn(req_body, authorization=authorization)
        return resp.body

    docs = {}

    # Carta
    docs["01_Carta_Presentacion.docx"] = _get_bytes(
        carta_presentacion, DocRequest(cliente_id=body.cliente_id, proceso_id=body.proceso_id))

    # Formulario económico
    docs["02_Formulario_Economico.docx"] = _get_bytes(
        formulario_economico, FormularioEconomicoRequest(
            cliente_id=body.cliente_id, proceso_id=body.proceso_id, datos_apu=body.datos_apu))

    # Experiencia
    docs["03_Formulario_Experiencia.docx"] = _get_bytes(
        formato_experiencia, DocRequest(cliente_id=body.cliente_id, proceso_id=body.proceso_id))

    # Capacidad residual
    docs["04_Capacidad_Residual.docx"] = _get_bytes(
        capacidad_residual, CapacidadResidualRequest(
            cliente_id=body.cliente_id, proceso_id=body.proceso_id,
            k_requerido=body.k_requerido, contratos_vigentes=body.contratos_vigentes))

    # Índice
    hoy   = _fmt_fecha()
    pid   = body.proceso_id
    indice = (
        f"ÍNDICE DE DOCUMENTOS — PAQUETE DE OFERTA\n"
        f"Proceso: {pid}\n"
        f"Generado: {hoy}\n\n"
        f"DOCUMENTOS INCLUIDOS:\n"
        f"  01_Carta_Presentacion.docx    — Carta formal de presentación de oferta\n"
        f"  02_Formulario_Economico.docx  — Formulario 1: Propuesta económica detallada\n"
        f"  03_Formulario_Experiencia.docx— Formulario 2: Acreditación de experiencia\n"
        f"  04_Capacidad_Residual.docx    — Factor K: Capacidad residual de contratación\n\n"
        f"CHECKLIST ANTES DE CARGAR EN SECOP II:\n"
        f"  [ ] Revise y complete todos los campos marcados con [CORCHETES]\n"
        f"  [ ] Firme cada documento con la firma autenticada del representante legal\n"
        f"  [ ] Adjunte certificados de contratos para el Formulario de Experiencia\n"
        f"  [ ] Verifique que el valor total coincide con el Formulario Económico\n"
        f"  [ ] Confirme que el Factor K es suficiente según el pliego\n"
        f"  [ ] Adjunte todos los documentos habilitantes requeridos en el pliego\n\n"
        f"⚠️  ADVERTENCIA: Estos documentos son borradores generados automáticamente por SIACO.\n"
        f"    SIACO no se responsabiliza por errores u omisiones en la oferta final.\n"
        f"    Es responsabilidad del proponente verificar el cumplimiento de todos los\n"
        f"    requisitos del pliego antes de presentar la oferta en SECOP II.\n"
    )
    docs["00_INDICE_Y_CHECKLIST.txt"] = indice.encode("utf-8")

    # Empacar ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for nombre, contenido in docs.items():
            zf.writestr(nombre, contenido)
    buf.seek(0)

    fecha_str = date.today().isoformat()
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="SIACO_Oferta_{pid}_{fecha_str}.zip"'},
    )
