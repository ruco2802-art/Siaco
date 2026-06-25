# -*- coding: utf-8 -*-
"""Router de auditoría de pliegos — SIACO v3.0"""
from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form

from config import API_KEY
import anthropic
import logging

from analizador import (
    extraer_texto_pliego,
    extraer_texto_completo_pdf,
    chunking_rag_pliego,
    analizar_cliente_vs_licitacion_paralelo,
    guardar_analisis_historial,
)
from routers.utils import parsear_json_claude

logger = logging.getLogger("siaco")

router = APIRouter(tags=["auditoria"])


def _cliente_id(sesion: dict) -> str:
    return sesion.get("cliente_id") or sesion.get("id") or ""


def _load_perfil_cliente(cid: str) -> dict:
    from routers.perfil import _load_perfil
    return _load_perfil(cid) or {}


def _perfil_a_formato_analisis(perfil: dict) -> dict:
    """Convierte perfil v3.0 al formato que espera analizar_cliente_vs_licitacion_paralelo."""
    fin = perfil.get("financiero", {})
    exp = perfil.get("experiencia", {})
    rup = perfil.get("rup", {})
    return {
        "nombre": perfil.get("nombre", "Cliente"),
        "sector": perfil.get("sector", ""),
        "rup": {
            "tiene_rup": rup.get("tiene_rup", False),
            "estado_rup": rup.get("estado_rup", "Inactivo"),
            "numero_rup": rup.get("numero_rup", ""),
        },
        "financiero": {
            "indice_liquidez": fin.get("indice_liquidez", 0),
            "indice_endeudamiento": fin.get("indice_endeudamiento", 0),
            "razon_cobertura_interes": fin.get("razon_cobertura_interes", 0),
            "capital_trabajo": fin.get("capital_trabajo", 0),
            "patrimonio_liquido": fin.get("patrimonio_liquido", 0),
            "presupuesto_maximo_contrato": fin.get("presupuesto_maximo_contrato", 0),
            "presupuesto_minimo_contrato": fin.get("presupuesto_minimo_contrato", 0),
        },
        "experiencia": {
            "valor_acumulado": exp.get("valor_acumulado", 0),
            "valor_individual_max": exp.get("valor_individual_max", 0),
            "objeto_similar": exp.get("objeto_similar", ""),
            "codigos_unspsc": exp.get("codigos_unspsc", ""),
            "participacion_minima": exp.get("participacion_minima", 30),
        },
        "codigos_unspsc_permitidos": [
            c.strip() for c in str(exp.get("codigos_unspsc", "")).split(",") if c.strip()
        ],
    }


def _enriquecer_resultado(resultado: dict) -> dict:
    """
    Enriquece el resultado del orquestador con campos adicionales para el frontend:
    - concepto_global (VIABLE/CONDICIONAL/NO VIABLE)
    - score_global
    - tabla_comparativa (fusión de checklist financiero + requisitos jurídicos)
    - citas_normativas (unifica articulos_aplicables + riesgos con citas)
    - checklist_documentos (documentos faltantes con estado)
    """
    score_fin = resultado.get("score", resultado.get("score_financiero", 0))
    score_jur = resultado.get("score_juridico", 0)
    score_global = round((score_fin + score_jur) / 2)

    viable = resultado.get("viable", False)
    concepto_fin = resultado.get("concepto_financiero", "")
    concepto_jur = resultado.get("concepto_juridico", "")

    if viable or ("VIABLE" in concepto_fin and "NO" not in concepto_fin
                  and "VIABLE" in concepto_jur and "NO" not in concepto_jur):
        concepto_global = "VIABLE"
        concepto_color = "green"
    elif score_global >= 40:
        concepto_global = "CONDICIONAL"
        concepto_color = "amber"
    else:
        concepto_global = "NO VIABLE"
        concepto_color = "red"

    # Tabla comparativa unificada
    tabla: list[dict] = []
    for item in resultado.get("checklist_financiero", []):
        if not isinstance(item, dict):
            continue
        tabla.append({
            "tipo": "financiero",
            "requisito": item.get("requisito", ""),
            "exigido": item.get("valor_pliego", ""),
            "cliente_tiene": item.get("valor_empresa", ""),
            "cumple": bool(item.get("cumple", False)),
            "norma": item.get("norma", "Decreto 1082/2015 art. 2.2.1.2.1.5.8"),
            "subsanable": False,
        })
    for item in resultado.get("requisitos_habilitantes", []):
        if not isinstance(item, dict):
            continue
        tabla.append({
            "tipo": "juridico",
            "requisito": item.get("requisito", ""),
            "exigido": item.get("exigido", ""),
            "cliente_tiene": item.get("cliente_tiene", ""),
            "cumple": bool(item.get("cumple", False)),
            "norma": item.get("norma", "Ley 80/1993"),
            "subsanable": bool(item.get("subsanable", True)),
        })

    # Citas normativas
    citas = list(resultado.get("articulos_aplicables", []))
    for r in resultado.get("riesgos_juridicos", []):
        if isinstance(r, str) and any(w in r for w in ["Ley", "Decreto", "art.", "CCE"]):
            citas.append(r)

    # Checklist documentos
    docs_faltantes = resultado.get("documentos_faltantes", resultado.get("pdf_documentos", []))
    checklist_docs = [
        {"documento": d, "estado": "falta", "subsanable": True}
        for d in docs_faltantes if d
    ]

    resultado.update({
        "score_global": score_global,
        "concepto_global": concepto_global,
        "concepto_color": concepto_color,
        "tabla_comparativa": tabla,
        "citas_normativas": citas,
        "checklist_documentos": checklist_docs,
    })
    return resultado


# ── POST /api/auditoria/extraer ───────────────────
@router.post("/auditoria/extraer")
async def extraer_pliego(
    pdf: UploadFile = File(...),
    authorization: str = Header(None),
):
    """Extrae texto y metadatos relevantes de un PDF de pliego."""
    from routers.auth import require_auth
    require_auth(authorization)

    raw = await pdf.read()
    texto = extraer_texto_pliego(raw)

    if not texto:
        raise HTTPException(status_code=422, detail="No se pudo extraer texto del PDF. Verifica que no sea solo imágenes sin OCR.")

    extraidos: dict = {}
    try:
        client = anthropic.Anthropic(api_key=API_KEY, timeout=20.0)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            temperature=0.0,
            messages=[{"role": "user", "content": (
                "Extrae del texto de pliego de licitacion publica colombiana:\n"
                "1) entidad contratante  2) objeto del contrato (max 200 chars)  "
                "3) valor base en pesos colombianos (numero entero, solo cifra)  "
                "4) modalidad de seleccion  5) sector\n\n"
                f"Texto del pliego:\n{texto[:6000]}\n\n"
                'Responde SOLO con JSON: {"entidad":"nombre","objeto":"desc","valor":numero_o_null,'
                '"modalidad":"infraestructura_obra_publica|suministro|prestacion_servicios|consultoria",'
                '"sector":"salud|educacion|infraestructura|transporte|ambiente|institucional"}'
            )}],
        )
        raw = resp.content[0].text
        extraidos = parsear_json_claude(raw) or {}
        if not extraidos:
            logger.warning("[AUDITORIA/extraer] parsear_json_claude retornó None. Respuesta cruda:\n%s", raw[:800])
    except Exception:
        pass

    return {
        "texto_chars": len(texto),
        "paginas_extraidas": texto.count("--- EXTRACTO PÁGINA"),
        "entidad":   extraidos.get("entidad", ""),
        "objeto":    extraidos.get("objeto", ""),
        "valor":     extraidos.get("valor"),
        "modalidad": extraidos.get("modalidad", "infraestructura_obra_publica"),
        "sector":    extraidos.get("sector", "salud"),
    }


# ── POST /api/auditoria/analizar ──────────────────
@router.post("/auditoria/analizar")
async def analizar_pliego(
    cliente_id:     str        = Form(...),
    modalidad:      str        = Form("infraestructura_obra_publica"),
    sector:         str        = Form("salud"),
    entidad:        str        = Form(""),
    objeto:         str        = Form(""),
    valor:          str        = Form("450000000"),
    pliego:         UploadFile = File(None),
    estudio_previo: UploadFile = File(None),
    anexo_tecnico:  UploadFile = File(None),
    adenda:         UploadFile = File(None),
    pdf:            UploadFile = File(None),   # backward compat
    authorization:  str        = Header(None),
):
    """Análisis completo de pliego con agentes IA financiero + jurídico RAG."""
    from routers.auth import require_auth
    sesion = require_auth(authorization)

    cid = cliente_id or _cliente_id(sesion)
    perfil_raw = _load_perfil_cliente(cid)

    if not perfil_raw:
        raise HTTPException(
            status_code=404,
            detail="Perfil del cliente no encontrado. Completa el perfil antes de auditar.",
        )

    perfil_analisis = _perfil_a_formato_analisis(perfil_raw)

    try:
        valor_num = int(str(valor).replace(",", "").replace(".", "").strip() or 0)
    except Exception:
        valor_num = 450_000_000

    licitacion = {
        "nombre_del_procedimiento": objeto or "Licitacion ingresada manualmente",
        "entidad": entidad or "Entidad Estatal",
        "precio_base": str(valor_num),
        "fase": "Publicado",
        "id_del_proceso": f"manual-{cid}-{int(__import__('time').time())}",
        "modalidad_seleccion": modalidad,
    }

    # ── Extraer texto del pliego (obligatorio) ────────
    archivo_pliego = pliego or pdf
    texto_pliego = ""
    if archivo_pliego and archivo_pliego.filename:
        raw = await archivo_pliego.read()
        if raw:
            texto_pliego = extraer_texto_completo_pdf(raw)

    if not texto_pliego or len(texto_pliego.strip()) < 200:
        raise HTTPException(
            status_code=422,
            detail=(
                "No se pudo extraer texto del pliego. "
                "Verifica que el PDF no sea solo imágenes sin OCR, "
                "o que hayas subido el archivo correctamente."
            ),
        )

    # ── Documentos adicionales (opcionales) ──────────
    textos_extra: list[str] = []
    docs_adicionales = [
        ("ESTUDIOS PREVIOS", estudio_previo),
        ("ANEXO TECNICO",    anexo_tecnico),
        ("ADENDA",           adenda),
    ]
    for nombre_doc, archivo in docs_adicionales:
        if archivo and archivo.filename:
            raw = await archivo.read()
            if raw:
                t = extraer_texto_completo_pdf(raw)
                if t:
                    textos_extra.append(f"=== {nombre_doc} ===\n{t[:4000]}")

    # ── Guardar texto completo en sesión para el chat ─
    from contexto_sesion import guardar_contexto_sesion
    guardar_contexto_sesion(
        cid,
        texto_pliego,
        "\n\n".join(textos_extra),
    )

    # ── Combinar y aplicar RAG si es necesario ────────
    contexto_completo = texto_pliego
    if textos_extra:
        contexto_completo += "\n\n" + "\n\n".join(textos_extra)

    RAG_THRESHOLD = 8_000
    query_rag = f"{objeto} {modalidad} {sector} requisitos habilitantes financieros experiencia"
    rag_activado = len(contexto_completo) > RAG_THRESHOLD

    if rag_activado:
        print(f"[AUDITORIA] Modo RAG activado ({len(contexto_completo)} chars > {RAG_THRESHOLD})")
        contexto_docs = chunking_rag_pliego(contexto_completo, query=query_rag)
    else:
        contexto_docs = contexto_completo

    # ── LOG: verificar que el texto llega a Claude ────
    print(f"\n{'='*60}")
    print(f"[AUDITORIA] Pliego: {len(texto_pliego)} chars | "
          f"Contexto Claude: {len(contexto_docs)} chars | RAG: {rag_activado}")
    print(f"[AUDITORIA] Preview (primeros 200 chars):\n{texto_pliego[:200]}")
    print(f"{'='*60}\n")

    try:
        resultado = analizar_cliente_vs_licitacion_paralelo(
            licitacion=licitacion,
            cliente=perfil_analisis,
            modalidad=modalidad,
            sector=sector,
            texto_pliego=contexto_docs,
            cliente_id=cid,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en análisis IA: {str(e)[:300]}")

    try:
        guardar_analisis_historial(cid, resultado, licitacion["id_del_proceso"])
    except Exception:
        pass

    resultado["pliego_chars"]   = len(texto_pliego)
    resultado["contexto_chars"] = len(contexto_docs)
    resultado["rag_activado"]   = rag_activado
    return _enriquecer_resultado(resultado)
