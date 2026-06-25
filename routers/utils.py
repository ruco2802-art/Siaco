# -*- coding: utf-8 -*-
"""Utilidades compartidas entre routers — SIACO v3.0"""
import json
import logging
import re

logger = logging.getLogger("siaco")


def parsear_json_claude(texto: str) -> dict | None:
    """
    Extrae un dict JSON de una respuesta de Claude de forma segura.
    Retorna None si no se puede parsear (nunca lanza excepción).
    Maneja: JSON directo, bloques ```json...```, JSON embebido en texto.
    """
    if not texto:
        return None
    texto = texto.strip()

    # 1. Extraer contenido dentro de bloque ```...```
    if "```" in texto:
        partes = texto.split("```")
        for parte in partes:
            parte = parte.strip()
            if parte.startswith("json"):
                parte = parte[4:].strip()
            if parte.startswith("{") or parte.startswith("["):
                try:
                    return json.loads(parte)
                except Exception:
                    pass

    # 2. Parseo directo del texto completo
    try:
        return json.loads(texto)
    except Exception:
        pass

    # 3. Buscar el primer { y el último } (JSON embebido en prosa)
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    return None
