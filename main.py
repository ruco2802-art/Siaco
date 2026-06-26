# -*- coding: utf-8 -*-
"""SIACO v3.0 — FastAPI backend"""
import os
import sys

# Asegura que los módulos del proyecto sean importables desde los routers
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from routers import auth, busqueda, auditoria, expedientes, perfil, competidores, reportes, chat, observaciones

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

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok", "version": "3.0"}


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
