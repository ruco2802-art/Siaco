import os
import io
import json
import shutil
import logging
from datetime import datetime
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from anthropic import Anthropic

# =====================================================================
# 🎛️ CONFIGURACIÓN GLOBAL Y LOGGING (Robustez Original)
# =====================================================================
os.makedirs("./logs", exist_ok=True)
os.makedirs("./pendientes_analisis", exist_ok=True)
os.makedirs("./procesados", exist_ok=True)
os.makedirs("./reportes", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(f"./logs/siaco_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Conexión al motor de OCR local en Windows
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

import os
API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
client_anthropic = Anthropic(api_key=API_KEY)

# =====================================================================
# 📁 FUNCIONES DE APOYO Y CARGA DE DATOS
# =====================================================================
def cargar_clientes():
    """Carga los perfiles de los clientes desde la carpeta local"""
    ruta_clientes = "./clientes"
    clientes = []
    if not os.path.exists(ruta_clientes):
        os.makedirs(ruta_clientes, exist_ok=True)
        logging.warning("La carpeta './clientes' no existía. Se ha creado automáticamente.")
        return clientes
        
    for archivo in os.listdir(ruta_clientes):
        if archivo.endswith('.json'):
            try:
                with open(os.path.join(ruta_clientes, archivo), 'r', encoding='utf-8') as f:
                    clientes.append(json.load(f))
            except Exception as e:
                logging.error(f"Error al cargar el perfil de cliente {archivo}: {str(e)}")
    return clientes

def guardar_reporte(nombre_archivo, cliente, checklist):
    """Guarda el checklist generado en la carpeta de reportes en formato Markdown"""
    nombre_limpio = os.path.splitext(nombre_archivo)[0]
    fecha_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_reporte = f"./reportes/REPORTE_{cliente['nombre'].replace(' ', '_')}_{nombre_limpio}_{fecha_str}.md"
    
    try:
        with open(ruta_reporte, 'w', encoding='utf-8') as f:
            f.write(f"# 📊 REPORTE DE VIABILIDAD SIACO\n")
            f.write(f"**Fecha de Análisis:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Documento Analizado:** {nombre_archivo}\n")
            f.write(f"**Cliente Evaluado:** {cliente['nombre']} (Sector: {cliente.get('sector')})\n")
            f.write(f"--- \n\n")
            f.write(checklist)
        logging.info(f"✨ Reporte guardado con éxito: {ruta_reporte}")
    except Exception as e:
        logging.error(f"No se pudo guardar el reporte para {cliente['nombre']}: {str(e)}")

# =====================================================================
# 🔍 EXTRACTOR INTELIGENTE HÍBRIDO (OCR + TEXTO NATIVO)
# =====================================================================
def escanear_paginas_pdf(ruta_pdf):
    """Lee el PDF de forma híbrida y extrae páginas con contenido crítico"""
    try:
        doc = fitz.open(ruta_pdf)
    except Exception as e:
        logging.error(f"Error crítico al abrir el archivo PDF {ruta_pdf}: {str(e)}")
        return []

    paginas_criticas = []
    keywords_financieros = [
        'liquidez', 'endeudamiento', 'capital de trabajo', 
        'cobertura de interes', 'razon de cobertura', 'requisitos financieros',
        'capacidad organizacional', 'rentabilidad', 'rup'
    ]
    
    logging.info(f"📡 Analizando un total de {len(doc)} páginas...")
    
    for i, pagina in enumerate(doc):
        texto = pagina.get_text()
        metodo = "Texto Nativo"
        
        # Si la página está escaneada (Imagen), aplicamos OCR de respaldo
        if len(texto.strip()) < 100:
            metodo = "OCR (Ojos Digitales)"
            try:
                pix = pagina.get_pixmap(matrix=fitz.Matrix(2, 2))
                imagen_data = pix.tobytes("png")
                imagen = Image.open(io.BytesIO(imagen_data))
                texto = pytesseract.image_to_string(imagen, lang='spa')
            except Exception as ocr_err:
                logging.warning(f"Fallo en OCR de página {i+1}: {str(ocr_err)}. Se usará texto nativo residual.")
        
        texto_minuscula = texto.lower()
        if any(key in texto_minuscula for key in keywords_financieros):
            logging.info(f"  [Pág. {i+1}] [{metodo}] ✨ ¡Detectada información financiera potencial!")
            paginas_criticas.append({
                "pagina": i + 1,
                "texto": texto
            })
            
    # Lógica de ordenamiento original para priorizar densidad de datos
    paginas_criticas.sort(key=lambda x: len(x['texto']), reverse=True)
    return paginas_criticas[:7]  # Limitamos a las 7 páginas más densas para cuidar la ventana de contexto

# =====================================================================
# 🧠 CEREBRO DEL AGENTE (Integración Recomendada de API de Anthropic)
# =====================================================================
def analizar_con_claude(paginas, cliente, nombre_archivo):
    """Envía los fragmentos extraídos a Claude para la validación financiera final"""
    if not client_anthropic.api_key:
        logging.error("❌ Variable de entorno ANTHROPIC_API_KEY no detectada.")
        return None

    # Unificamos las páginas en un bloque estructurado
    contexto_paginas = ""
    for p in paginas:
        contexto_paginas += f"\n--- EXTRACTO PÁGINA {p['pagina']} ---\n{p['texto']}\n"

    prompt = f"""
    Eres un analista experto en contratación estatal en Colombia (SECOP II).
    Tu misión es contrastar los requisitos financieros exigidos en los siguientes extractos de un pliego de condiciones frente a las capacidades financieras de nuestro cliente.

    === PERFIL DEL CLIENTE CONTRATISTA ===
    {json.dumps(cliente, indent=2, ensure_ascii=False)}

    === EXTRACTOS DEL PLIEGO DE CONDICIONES ===
    {contexto_paginas}

    === INSTRUCCIONES DE SALIDA ===
    Genera un informe ejecutivo estructurado en Markdown que responda:
    1. PUNTAJE DE VIABILIDAD (0 al 100%).
    2. CHECKLIST DETALLADO: Compara uno a uno el Índice de Liquidez, Índice de Endeudamiento, Razón de Cobertura de Intereses y Capital de Trabajo exigido vs lo que tiene el cliente.
    3. VEREDICTO FINAL: ¿Cumple o No Cumple con el RUP? Si no cumple, especifica exactamente por cuánto margen falla.
    4. RECOMENDACIÓN ESTRATÉGICA: (Ej: Ir en Consorcio, solicitar aclaración a la entidad, etc.)
    """

    try:
        # 🎯 RECOMENDACIÓN 4 APLICADA: Uso del alias universal y actualizado de Claude
        respuesta = client_anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2500,  # Ampliado para evitar el corte prematuro del reporte
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}]
        )
        return respuesta.content[0].text
    except Exception as api_err:
        logging.error(f"Error de conectividad en la API de Claude: {str(api_err)}")
        return None

# =====================================================================
# ⚡ RECOMENDACIÓN 2: INTEGRACIÓN DEL FILTRO INTELIGENTE DE SECTORES
# =====================================================================
def procesar_pdf(ruta_pdf, nombre_archivo, sector_proceso_licitacion):
    """Controla el flujo de análisis filtrando idoneidad comercial antes de gastar tokens"""
    logging.info(f"\n" + "="*60)
    logging.info(f"🚀 INICIANDO ANÁLISIS E2E: {nombre_archivo}")
    logging.info(f"🎯 Sector Objetivo de la Licitación: {sector_proceso_licitacion.upper()}")
    logging.info("="*60)
    
    # 1. Extracción y Filtrado de Páginas local (OCR híbrido)
    paginas = escanear_paginas_pdf(ruta_pdf)
    if not paginas:
        logging.warning(f"❌ El documento {nombre_archivo} no contiene páginas con indicadores RUP. Proceso abortado.")
        return

    # 2. Carga de Base de Datos de Clientes
    clientes = cargar_clientes()
    if not clientes:
        logging.error("No se encontraron perfiles de clientes en la carpeta './clientes'.")
        return

    # 3. Mapeo Flexible de Sectores (Evita descarte por tecnicismos de texto plano)
    sector_licitacion_clean = sector_proceso_licitacion.lower()
    keywords_obra = ["obra", "civil", "construc", "adecuac", "mantenimiento", "locativo", "infraestructura", "via"]
    keywords_hvac = ["hvac", "refrigeracion", "aire", "climatizacion", "acondicionado"]
    keywords_transporte = ["transporte", "logistica", "carga", "vehiculo", "flete"]

    clientes_aptos = []
    for c in clientes:
        sector_cliente = c.get("sector", "").lower()
        match_sector = False
        
        if "obra" in sector_licitacion_clean:
            if any(kw in sector_cliente for kw in keywords_obra):
                match_sector = True
        elif "hvac" in sector_licitacion_clean or "refrigerac" in sector_licitacion_clean:
            if any(kw in sector_cliente for kw in keywords_hvac):
                match_sector = True
        elif "transporte" in sector_licitacion_clean:
            if any(kw in sector_cliente for kw in keywords_transporte):
                match_sector = True
        
        if match_sector:
            clientes_aptos.append(c)
        else:
            logging.info(f"🚫 [DESCARTADO LOCALMENTE] Cliente: {c['nombre']} (Motivo: El sector del cliente '{c.get('sector')}' no aplica para {sector_proceso_licitacion})")

    logging.info(f"📊 Filtrado Concluido. Clientes aptos para evaluación de IA: {len(clientes_aptos)} de {len(clientes)}")

    # 4. Evaluación E2E vía Claude únicamente para los perfiles idóneos
    for cliente in clientes_aptos:
        logging.info(f"🧠 Conectando con Claude-3.5-Sonnet para evaluar viabilidad financiera de: {cliente['nombre']}")
        checklist = analizar_con_claude(paginas, cliente, nombre_archivo)
        
        if checklist:
            print(f"\n📝 --- CHECKLIST GENERADO PARA {cliente['nombre'].upper()} ---")
            print(checklist[:300] + "\n... [Contenido del Reporte guardado en archivo] ...\n")
            guardar_reporte(nombre_archivo, cliente, checklist)
        else:
            logging.error(f"Fallo el análisis cognitivo para el cliente {cliente['nombre']}")

def monitor_carpetas():
    """Bucle principal de ejecución del Agente SIACO"""
    carpeta_pendientes = "./pendientes_analisis"
    carpeta_procesados = "./procesados"
    
    archivos = [f for f in os.listdir(carpeta_pendientes) if f.endswith('.pdf')]
    
    if not archivos:
        logging.info("📥 No se encontraron archivos PDF nuevos en la carpeta de pendientes.")
        return

    for archivo in archivos:
        ruta_completa = os.path.join(carpeta_pendientes, archivo)
        
        # 💡 DEFINICIÓN OPERATIVA DEL SECTOR (Ajustar según el contrato a probar)
        # Para el pliego de la AEROCIVIL o San Vicente, asignamos "OBRAS CIVILES"
        sector_objetivo = "OBRAS CIVILES" 
        
        try:
            procesar_pdf(ruta_completa, archivo, sector_objetivo)
            # Movimiento seguro del archivo una vez completado el ciclo E2E
            shutil.move(ruta_completa, os.path.join(carpeta_procesados, archivo))
            logging.info(f"📦 Ciclo E2E concluido con éxito. Archivo {archivo} movido a './procesados'.")
        except Exception as e:
            logging.critical(f"🚨 Falla catastrófica en el procesamiento del archivo {archivo}: {str(e)}")

# =====================================================================
# 🏁 PUNTO DE ENTRADA ÚNICO (Estructura Jerárquica Normalizada)
# =====================================================================
if __name__ == "__main__":
    print("\n==================================================================")
    print("🤖 SIACO v1.6 - RESTAURACIÓN DE COMPATIBILIDAD Y PIPELINE SECTORIAL")
    print("==================================================================")
    logging.info("Iniciando servicio de escaneo de pliegos...")
    monitor_carpetas()