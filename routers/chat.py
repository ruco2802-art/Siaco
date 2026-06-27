# -*- coding: utf-8 -*-
"""Router de chat asistente — SIACO v3.0"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

import os
import anthropic
from prompts import SKILL_JURIDICO, SKILL_ESTRATEGIA

API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
from contexto_sesion import contexto_para_chat

router = APIRouter(tags=["chat"])

# Historial de chat por token (en memoria, se pierde al reiniciar)
_chat_histories: dict[str, list[dict]] = {}

# Plantilla base — NO incluir texto del pliego aquí (puede tener llaves {})
_SYSTEM_BASE = """\
Eres un asesor experto en contratación pública colombiana especializado en ayudar \
empresas MiPymes a ganar licitaciones en SECOP II. Tu misión es guiar al usuario \
paso a paso de manera simple y clara, como si le explicaras a alguien sin experiencia \
en contratación pública.

Contexto del usuario:
- Empresa: {nombre_empresa}
- Sector: {sector}
- Pantalla actual: {pantalla_actual}
- Contrato en análisis: {contexto_contrato}

Puedes ayudar con:
1. Qué documentos necesita para aplicar y cómo conseguirlos
2. Cómo llenar cada plantilla con ejemplos concretos paso a paso
3. Cómo organizar la carpeta de la oferta (estructura exacta)
4. Orden de pasos para presentar la oferta en SECOP II
5. Qué significa cada término técnico del pliego en lenguaje simple
6. Qué hacer si falta algún requisito (consorcios, subsanaciones)
7. Cómo calcular el precio óptimo de la oferta
8. Cuándo y cómo subir la oferta a SECOP II sin errores técnicos
9. Alertas de fechas límite y qué preparar con anticipación

Reglas de respuesta:
- Usa lenguaje simple y cotidiano, evita tecnicismos sin explicar
- Da pasos numerados cuando expliques procesos
- Incluye ejemplos concretos (ej: 'En el campo Experiencia escriba: Contrato No. 001-2024 con Alcaldía de Neiva por $50.000.000')
- Cita las normas relevantes pero explícalas en lenguaje simple
- Si no sabes algo específico del contrato, dilo claramente
- Máximo 300 palabras por respuesta para no abrumar al usuario

{skills}
"""

_BLOQUE_CON_PLIEGO = (
    "\n\n"
    "════════════════════════════════════════════════════\n"
    "DOCUMENTOS DEL PROCESO EN ANÁLISIS\n"
    "════════════════════════════════════════════════════\n"
    "El usuario ha subido los siguientes documentos. "
    "USA ESTA INFORMACIÓN para responder sus preguntas de forma concreta. "
    "NO mandes al usuario a buscar información que ya está aquí. "
    "Cita el texto del pliego cuando sea relevante.\n\n"
    "PLIEGO DE CONDICIONES (extracto relevante):\n"
)

_BLOQUE_SIN_PLIEGO = (
    "\n\n"
    "NOTA IMPORTANTE: El usuario NO ha subido el pliego de condiciones todavía. "
    "Si pregunta sobre requisitos, experiencia, indicadores financieros o documentos "
    "específicos de un proceso, respóndele así: "
    "'Para darte los requisitos exactos de este proceso, necesito que vayas a la "
    "sección Auditoría y subas el pliego de condiciones. Una vez subido, podré "
    "responderte con información precisa del documento.' "
    "Para preguntas generales sobre contratación pública, responde normalmente."
)


class ChatBody(BaseModel):
    mensaje: str
    pantalla_actual: Optional[str] = ""
    cliente_id: Optional[str] = ""
    contexto_contrato: Optional[dict] = None


@router.post("/chat")
def chat_asistente(body: ChatBody, authorization: str = Header(None)):
    """Asesor conversacional con acceso al pliego subido en auditoría."""
    from routers.auth import require_auth
    from routers.perfil import _load_perfil, _cliente_id_from_session

    sesion = require_auth(authorization)
    token  = (authorization or "").replace("Bearer ", "")

    cid    = body.cliente_id or _cliente_id_from_session(sesion)
    perfil = _load_perfil(cid) if cid else {}

    nombre_empresa = (perfil or {}).get("nombre", "Tu empresa") or "Tu empresa"
    sector         = (perfil or {}).get("sector", "") or "construcción y servicios"

    # Contexto del contrato (enviado desde el frontend)
    ctx = body.contexto_contrato or {}
    partes: list[str] = []
    if ctx.get("nombre"):     partes.append(f"Proceso: {ctx['nombre']}")
    if ctx.get("entidad"):    partes.append(f"Entidad: {ctx['entidad']}")
    if ctx.get("valor"):      partes.append(f"Valor: {ctx['valor']}")
    if ctx.get("documentos"): partes.append(f"Docs: {', '.join(ctx['documentos'])}")
    contexto_str = " | ".join(partes) if partes else "Ninguno"

    # Construir prompt base con str.format() (solo valores controlados, sin pliego)
    system_prompt = _SYSTEM_BASE.format(
        nombre_empresa    = nombre_empresa,
        sector            = sector,
        pantalla_actual   = body.pantalla_actual or "general",
        contexto_contrato = contexto_str,
        skills            = SKILL_JURIDICO + "\n" + SKILL_ESTRATEGIA,
    )

    # Inyectar contexto documental (RAG si > 5 000 chars, completo si menor)
    # Se hace por concatenación para evitar que llaves en el pliego rompan .format()
    fragmento = contexto_para_chat(cid, body.mensaje) if cid else ""
    if fragmento:
        system_prompt += _BLOQUE_CON_PLIEGO + fragmento
    else:
        system_prompt += _BLOQUE_SIN_PLIEGO

    # Historial: últimos 10 mensajes
    hist = _chat_histories.setdefault(token, [])
    hist.append({"role": "user", "content": body.mensaje})

    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""), timeout=30.0, max_retries=2)
        resp   = client.messages.create(
            model      = "claude-sonnet-4-6",
            max_tokens = 600,
            system     = system_prompt,
            messages   = hist[-10:],
        )
        reply = resp.content[0].text
        hist.append({"role": "assistant", "content": reply})
        return {
            "respuesta":    reply,
            "historial_len": len(hist),
            "tiene_pliego": bool(fragmento),
        }
    except Exception as e:
        if hist and hist[-1]["role"] == "user":
            hist.pop()
        raise HTTPException(
            status_code=500,
            detail=f"Error al consultar IA: {str(e)[:200]}",
        )


@router.delete("/chat/historial")
def limpiar_historial(authorization: str = Header(None)):
    """Borra el historial de chat de la sesión actual."""
    from routers.auth import require_auth
    require_auth(authorization)
    token = (authorization or "").replace("Bearer ", "")
    _chat_histories.pop(token, None)
    return {"ok": True}
