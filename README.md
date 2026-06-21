# SIACO v3.0 — Sistema Inteligente de Análisis de Contratación

## Descripción
Plataforma SaaS de inteligencia artificial para detectar y analizar 
licitaciones públicas colombianas en SECOP II. Ayuda a MiPymes a 
ganar contratos públicos mediante análisis financiero, jurídico y 
de inteligencia competitiva.

## Requisitos
- Python 3.13
- Node.js 22+
- Tesseract OCR instalado
- Cuenta Anthropic con API key

## Instalación
1. Clonar repositorio
2. pip install -r requirements.txt
3. Crear archivo .env con: ANTHROPIC_API_KEY=tu_key
4. py -3.13 -m uvicorn main:app --reload --port 8000

## Credenciales por defecto
- Admin: admin / siaco_admin_2026
- Crear clientes desde panel admin

## Estructura
- main.py — FastAPI backend principal
- routers/ — endpoints por módulo
- static/ — frontend HTML/CSS/JS
- analizador.py — motor RAG y agentes IA
- clientes/ — perfiles y documentos por cliente
- biblioteca_normativa/ — RAG legal colombiano

## Stack
Python 3.13, FastAPI, Anthropic Claude Sonnet 4.6, 
sentence-transformers, PyMuPDF, Tesseract OCR, fpdf2
