# -*- coding: utf-8 -*-
"""
routers/portafolio.py — Análisis ya pagados, servidos sin gastar API.

Dos usos:

  · HISTORIAL del cliente — reabrir un análisis propio sin recalcularlo. El
    historial de `analizador.py` guarda dos scores; el resultado entero vive
    en el almacén y se devuelve tal cual.

  · PORTAFOLIO de demostración — enseñar a un prospecto qué produce el
    sistema. Usa SÓLO el perfil ficticio: mostrar la evaluación de un cliente
    real expondría sus estados financieros y su experiencia a un tercero.
    `registro.CLIENTE_DEMO` es la única fuente de estas respuestas.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from pipeline.src import registro

router = APIRouter(tags=["portafolio"])


@router.get("/portafolio")
def listar_portafolio(authorization: str = Header(None)):
    """
    Pliegos analizados que se pueden abrir sin gastar API.

    `demo=true` marca los que tienen evaluación con el perfil ficticio, que
    son los únicos presentables ante un prospecto.
    """
    from routers.auth import require_auth
    require_auth(authorization)

    items = registro.portafolio()
    estado = registro.estado_almacen()
    return {
        "items": items,
        "total": len(items),
        "presentables": sum(1 for i in items if i["demo"]),
        "almacen_respaldado": estado["respaldado"],
        "aviso_almacen": estado["aviso"],
    }


@router.get("/portafolio/demo/{sha256}")
def abrir_demo(sha256: str, authorization: str = Header(None)):
    """Resultado guardado del perfil ficticio. Sin recalcular, sin API."""
    from routers.auth import require_auth
    require_auth(authorization)

    resultado = registro.cargar_evaluacion(registro.CLIENTE_DEMO, sha256)
    if resultado is None:
        raise HTTPException(
            404,
            "No hay evaluación de demostración para este pliego. "
            "Se prepara analizándolo con el perfil ficticio.",
        )
    return resultado


@router.get("/historial/analisis")
def historial_analisis(authorization: str = Header(None)):
    """Análisis del cliente autenticado, el más reciente primero."""
    from routers.auth import require_auth
    from routers.perfil import _cliente_id_from_session

    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)
    pliegos = registro.cargar_registro_pliegos()

    salida = []
    for ev in registro.evaluaciones_de(cid):
        p = pliegos.get(ev["sha256"], {})
        salida.append({
            "sha256": ev["sha256"],
            "fecha": ev.get("fecha", ""),
            "veredicto": ev.get("veredicto", ""),
            "numero_proceso": ev.get("numero_proceso") or p.get("numero_proceso", ""),
            "entidad": ev.get("entidad") or p.get("entidad", ""),
            "archivo": p.get("archivo", ""),
            "tiene_pdf": bool(ev.get("ruta_pdf")),
        })
    return {"items": salida, "total": len(salida)}


@router.get("/historial/analisis/{sha256}")
def abrir_analisis(sha256: str, authorization: str = Header(None)):
    """
    Reabre un análisis propio sin recalcularlo.

    Es lo que hoy no se podía: el historial guardaba `score_financiero` y
    `score_juridico`, así que volver a ver la tabla exigía repetir el
    análisis y pagar la API otra vez.
    """
    from routers.auth import require_auth
    from routers.perfil import _cliente_id_from_session

    sesion = require_auth(authorization)
    cid = _cliente_id_from_session(sesion)

    resultado = registro.cargar_evaluacion(cid, sha256)
    if resultado is None:
        raise HTTPException(404, "No hay análisis guardado de este pliego.")
    return resultado


@router.get("/almacen/estado")
def estado_almacen(authorization: str = Header(None)):
    """Dónde vive lo pagado y si hay respaldo."""
    from routers.auth import require_auth
    require_auth(authorization)
    estado = registro.estado_almacen()
    pliegos = registro.cargar_registro_pliegos()
    return {
        **estado,
        "pliegos": len(pliegos),
        "con_extraccion": sum(1 for p in pliegos.values()
                              if "extraccion" in (p.get("artefactos") or {})),
        "evaluaciones": len(registro.cargar_registro_evaluaciones()),
        "invertido_usd": round(
            sum(p.get("costo_usd", 0.0) for p in pliegos.values()), 2),
    }
