# -*- coding: utf-8 -*-
"""SIACO v3.0 — FastAPI backend"""
import io
import json as _json
import os
import sys
from datetime import datetime as _datetime
from pathlib import Path

# Diagnóstico de variables de entorno al arrancar
_api_key_raw = os.getenv("ANTHROPIC_API_KEY", "")
print(f"[STARTUP] API_KEY presente: {bool(_api_key_raw)}")
print(f"[STARTUP] Primeros 10 chars: {_api_key_raw[:10]!r}")
print(f"[STARTUP] Platform: {sys.platform} | CWD: {os.getcwd()}")
print(f"[STARTUP] .env existe: {Path('.env').exists()}")

# Asegura que los módulos del proyecto sean importables desde los routers
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from routers import auth, busqueda, auditoria, expedientes, perfil, competidores, reportes, chat, observaciones, calculadora, generador_oferta

app = FastAPI(
    title="SIACO v3.0",
    description="Sistema de Inteligencia para Contratación Pública SECOP II",
    version="3.0",
)

app.include_router(auth.router,         prefix="/api")
app.include_router(perfil.router,       prefix="/api")
app.include_router(busqueda.router,     prefix="/api")
app.include_router(auditoria.router,    prefix="/api")
app.include_router(expedientes.router,  prefix="/api")
app.include_router(competidores.router, prefix="/api")
app.include_router(reportes.router,     prefix="/api")
app.include_router(chat.router,         prefix="/api")
app.include_router(observaciones.router, prefix="/api")
app.include_router(calculadora.router,      prefix="/api")
app.include_router(generador_oferta.router, prefix="/api")

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok", "version": "3.0"}


@app.get("/landing")
async def landing():
    return FileResponse("static/landing.html")


@app.post("/api/solicitud-demo")
async def solicitud_demo(request: Request):
    """Guarda solicitud de evaluación gratuita."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    body["fecha"] = _datetime.now().isoformat()
    _guardar_solicitud(body)
    return {"ok": True}


def _guardar_solicitud(data: dict):
    try:
        ruta = Path("solicitudes_demo.json")
        lista: list = []
        if ruta.exists():
            with open(ruta, "r", encoding="utf-8") as f:
                lista = _json.load(f)
        lista.append(data)
        with open(ruta, "w", encoding="utf-8") as f:
            _json.dump(lista, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


@app.get("/api/contrato/descargar")
def descargar_contrato():
    """Genera y retorna el contrato de servicios SIACO como archivo .docx."""
    from generar_contrato import generar_docx
    buf = io.BytesIO()
    generar_docx(buf)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=Contrato_Servicios_SIACO.docx"},
    )
