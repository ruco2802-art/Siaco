# -*- coding: utf-8 -*-
# Configuración de SIACO v3.0
# Las credenciales sensibles se cargan desde .env (python-dotenv)

from dotenv import load_dotenv
import os

load_dotenv(override=False)  # Railway env vars tienen prioridad sobre .env local

API_KEY            = os.getenv("ANTHROPIC_API_KEY")
ADMIN_KEY          = os.getenv("ADMIN_KEY", "siaco_admin_2026")
GMAIL_USER         = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# Filtros de búsqueda SECOP II
DEPARTAMENTO = "Huila"
VALOR_MINIMO = 5_000_000
MAX_LICITACIONES = 50

KEYWORDS_HVAC = [
    # HVAC y refrigeración
    "hvac", "aire acondicionado", "aires acondicionados",
    "climatizacion", "climatización", "refrigeracion", "refrigeración",
    "ventilacion", "ventilación", "ductos", "chiller", "fan coil",
    "sistema termico", "sistemas de energia", "mantenimiento electrico",
    "instalacion electrica", "instalaciones electricas",
    # Obras civiles
    "obra civil", "obras civiles", "construccion", "construcción",
    "adecuacion", "adecuación", "adecuaciones", "mantenimiento locativo",
    "mantenimiento de infraestructura", "mantenimiento preventivo",
    "mantenimiento correctivo", "remodelacion", "remodelación",
    "pintura", "impermeabilizacion", "acabados", "infraestructura",
    "mejoramiento", "escenarios deportivos", "sedes administrativas",
    "mantenimiento de sedes", "conservacion", "conservación",
    "estructuras", "mitigacion", "mitigación",
    # Transporte
    "transporte", "logistica", "logística", "transporte de carga",
    "transporte de personal", "flota vehicular", "movilizacion",
    "traslado", "traslados", "vehiculos", "buses",
]

# Archivo de historial de contratos ya enviados (Task Scheduler)
ARCHIVO_ENVIADOS = "C:\\Users\\aleja\\agente_secop\\enviados.json"
