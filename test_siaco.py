import json
import os
from analizador import obtener_contexto_legal, analizar_cliente_vs_licitacion

# 1. Variables exactas de tus carpetas (Ajustadas a tu mensaje anterior)
MODALIDAD_REAL = "infraestructura_obra_publica"
SECTOR_REAL = "salud"

# 2. Datos simulados para activar el Cerebro de Claude
licitacion_demo = {
    "fase": "Presentación de oferta",
    "nombre_del_procedimiento": "Contratación de obras de infraestructura para el sector salud",
    "descripci_n_del_procedimiento": "Adecuación y remodelación locativa de áreas hospitalarias.",
    "precio_base": 120000000,
    "entidad": "ESE Hospital Local",
    "codigo_principal_de_categoria": "72101500"
}

cliente_demo = {
    "nombre": "Construcciones del Huila S.A.S",
    "id_cliente": "CLI-001",
    "sector": "Obras Civiles",
    "rup": {"estado_rup": "Activo"},
    "sectores_clave": ["obras", "construccion", "salud"],
    "codigos_unspsc_permitidos": ["7210"],
    "financiero": {
        "presupuesto_minimo_contrato": 50000000,
        "presupuesto_maximo_contrato": 500000000,
        "indice_liquidez": 1.4,
        "indice_endeudamiento": 0.55
    }
}

print("🚀 INICIANDO VIGILANCIA EN VIVO DE SIACO 2.0...")
print("--------------------------------------------------")
print(f"📂 Buscando en: ./biblioteca_normativa/{MODALIDAD_REAL}/")
print(f"🔍 Buscando subcarpetas con la palabra: '{SECTOR_REAL}'")

# 3. Llamamos al analizador para triturar los archivos
contexto = obtener_contexto_legal(modalidad=MODALIDAD_REAL, sector=SECTOR_REAL)

print("--------------------------------------------------")
print(f"📊 RESULTADO DE LA LECTURA:")
print(f"• Caracteres legales acumulados: {len(contexto)}")

if len(contexto.strip()) == 0:
    print("❌ ALERTA: No se leyó nada de texto. Revisa:")
    print("   1. Que los nombres de las carpetas coincidan exactamente en minúsculas.")
    print("   2. Que los archivos dentro tengan la palabra 'matriz', 'herramienta' o 'resolucion'.")
else:
    print("✅ ¡Texto extraído con éxito! Despertando a Claude Sonnet...")
    print("🧠 Procesando dictamen jurídico, espera un momento...")
    
    # 4. Forzamos a Claude a dar el veredicto
    resultado = analizar_cliente_vs_licitacion(
        licitacion=licitacion_demo, 
        cliente=cliente_demo, 
        modalidad=MODALIDAD_REAL, 
        sector=SECTOR_REAL
    )
    
    print("\n🎯 REPORTE FINAL GENERADO POR SIACO:")
    print(json.dumps(resultado, indent=4, ensure_ascii=False))