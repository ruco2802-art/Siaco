# -*- coding: utf-8 -*-
"""
Almacén en memoria del texto extraído del pliego por cliente.
Compartido entre routers/auditoria.py y routers/chat.py.
Se limpia al reiniciar el servidor (volátil, por diseño).
"""
from datetime import datetime

# Umbral: por debajo se inyecta completo, por encima se aplica RAG
_CHAT_RAG_THRESHOLD = 5_000

# {cliente_id: {texto_pliego, textos_adicionales, fecha}}
contextos_sesion: dict[str, dict] = {}


def guardar_contexto_sesion(
    cliente_id: str,
    texto_pliego: str,
    textos_adicionales: str = "",
) -> None:
    """Guarda hasta 15 000 chars del pliego y 5 000 de docs adicionales."""
    contextos_sesion[cliente_id] = {
        "texto_pliego":       texto_pliego[:15_000],
        "textos_adicionales": textos_adicionales[:5_000],
        "fecha":              datetime.now().isoformat(),
    }


def obtener_contexto_sesion(cliente_id: str) -> dict:
    """Retorna el contexto guardado para el cliente o dict vacío."""
    return contextos_sesion.get(cliente_id, {})


def contexto_para_chat(cliente_id: str, query: str) -> str:
    """
    Devuelve el fragmento de pliego más relevante para la query del chat.
    - Si el pliego es corto (<= 5 000 chars): lo devuelve completo.
    - Si es largo: aplica RAG con la query del usuario (top-2 por sub-query).
    Siempre añade los documentos adicionales al final (hasta 2 000 chars).
    Devuelve cadena vacía si no hay pliego guardado para el cliente.
    """
    ctx = contextos_sesion.get(cliente_id)
    if not ctx:
        return ""

    texto      = ctx.get("texto_pliego", "")
    adicionales = ctx.get("textos_adicionales", "")

    if not texto:
        return ""

    if len(texto) <= _CHAT_RAG_THRESHOLD:
        fragmento = texto
    else:
        try:
            from analizador import chunking_rag_pliego
            fragmento = chunking_rag_pliego(texto, query=query, top_k_por_query=2)
        except Exception:
            # Fallback: primeros 5 000 chars si el modelo no carga
            fragmento = texto[:_CHAT_RAG_THRESHOLD]

    if adicionales:
        fragmento += f"\n\n--- DOCUMENTOS ADICIONALES ---\n{adicionales[:2_000]}"

    return fragmento
