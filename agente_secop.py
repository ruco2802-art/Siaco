import os
import anthropic
import requests
import json
import webbrowser
import urllib.parse
import time
from analizador import cargar_clientes, cruzar_licitacion_con_clientes
from datetime import datetime, timedelta
from config_legacy import API_KEY, DEPARTAMENTO, VALOR_MINIMO, MAX_LICITACIONES, KEYWORDS_HVAC, ARCHIVO_ENVIADOS

FASES_EXCLUIDAS = {"manifestación de interés", "adjudicado", "desierto", "liquidado", "terminado", "celebrado"}
FASES_INCLUIDAS = {"convocado", "publicado", "selección abreviada", "concurso de méritos"}

client = anthropic.Anthropic(api_key=API_KEY)

def cargar_enviados():
    try:
        with open(ARCHIVO_ENVIADOS, "r", encoding="utf-8") as f:
            return json.load(f).get("enviados", [])
    except FileNotFoundError:
        return []

def guardar_enviado(codigo):
    enviados = cargar_enviados()
    if not any(e["codigo"] == codigo for e in enviados):
        enviados.append({"codigo": codigo, "fecha": datetime.now().strftime("%Y-%m-%d %H:%M")})
    data = {"enviados": enviados}
    try:
        with open(ARCHIVO_ENVIADOS, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Codigo {codigo} registrado en historial")
    except Exception as e:
        print(f"Error escribiendo historial: {e}")

def ya_fue_enviado(codigo):
    enviados = cargar_enviados()
    return any(e["codigo"] == codigo for e in enviados)

def buscar_licitaciones():
    print("Buscando licitaciones en SECOP II...")
    url = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
    params = {
        "$where": "fecha_de_publicacion > '2026-04-01T00:00:00' AND estado_del_procedimiento = 'Publicado'",
        "$limit": str(MAX_LICITACIONES),
        "$order": "fecha_de_publicacion DESC"
    }
    try:
        respuesta = requests.get(url, params=params, timeout=12)
        licitaciones = respuesta.json()
        print(f"Se encontraron {len(licitaciones)} licitaciones")
        return licitaciones
    except Exception as e:
        print(f"Error conectando a SECOP: {e}")
        return []

def filtrar_por_keywords(licitaciones):
    relevantes = []
    for lic in licitaciones:
        nombre = str(lic.get("nombre_del_procedimiento", ""))
        descripcion = str(lic.get("descripci_n_del_procedimiento", ""))
        objeto_contrato = str(lic.get("objeto_a_contratar", ""))
        objeto = f"{nombre} {descripcion} {objeto_contrato}".lower()
        for keyword in KEYWORDS_HVAC:
            if keyword.lower() in objeto:
                relevantes.append(lic)
                break
    print(f"Despues keywords: {len(relevantes)} licitaciones")
    return relevantes

def filtrar_por_fase(licitaciones):
    """Excluye fases cerradas e incluye solo fases activas."""
    validas = []
    for lic in licitaciones:
        fase = lic.get("fase", "").lower().strip()
        if any(exc in fase for exc in FASES_EXCLUIDAS):
            continue
        if fase and not any(inc in fase for inc in FASES_INCLUIDAS):
            continue
        validas.append(lic)
    print(f"Despues filtro fase: {len(validas)} licitaciones")
    return validas


def filtrar_por_fecha_cierre(licitaciones):
    """Descarta licitaciones con fechas de cierre demasiado próximas o vencidas."""
    now = datetime.now()
    validas = []
    for lic in licitaciones:
        def _dt(campo):
            s = lic.get(campo, "")
            if not s:
                return None
            try:
                return datetime.fromisoformat(str(s).replace("Z", "").split("+")[0])
            except Exception:
                return None

        dt_manif = _dt("fecha_limite_manifestacion_interes")
        if dt_manif and dt_manif < now + timedelta(hours=24):
            continue

        dt_oferta = _dt("fecha_limite_recepcion_ofertas") or _dt("fecha_de_recepcion_de")
        if dt_oferta and dt_oferta < now + timedelta(hours=48):
            continue

        validas.append(lic)
    print(f"Despues filtro temporal: {len(validas)} licitaciones")
    return validas


def filtrar_por_valor(licitaciones):
    relevantes = []
    for lic in licitaciones:
        try:
            valor = float(lic.get("precio_base", 0))
            if valor >= VALOR_MINIMO:
                relevantes.append(lic)
        except Exception:
            relevantes.append(lic)
    print(f"Despues valor: {len(relevantes)} licitaciones")
    return relevantes

def analizar_licitacion(licitacion):
    objeto = licitacion.get("nombre_del_procedimiento", "No disponible")
    descripcion = licitacion.get("descripci_n_del_procedimiento", "No disponible")
    valor = licitacion.get("precio_base", "No disponible")
    entidad = licitacion.get("entidad", "No disponible")
    fecha_cierre = licitacion.get("fecha_de_recepcion_de", "No disponible")

    system_prompt = (
       "Eres SIACO, un experto analista senior en licitaciones de SECOP II para Colombia.\n"
       "Trabajas para la agencia SIACO, que gestiona licitaciones publicas para empresas MiPyme a nivel nacional.\n"
        "1. Climatización e ingeniería térmica (HVAC, instalación y mantenimiento de aires acondicionados industriales/comerciales, sistemas de ventilación).\n"
        "2. Obras civiles, adecuaciones locativas, remodelaciones, mantenimiento de infraestructura física, pintura, impermeabilización y acabados.\n\n"
        "3. Transporte, logística, movilización de personal, transporte de carga, mantenimiento de flota de vehículos, transporte de personal.\n\n"
        "REGLA DE ORO DE UBICACIÓN:\n"
        "- Ejecuta proyectos en CUALQUIER PARTE DEL PAÍS. JAMÁS descartes por ubicación geográfica.\n\n"
        "CRITERIO DE EVALUACIÓN:\n"
        "- RELEVANTE: adecuación de infraestructura, museos, edificios, mantenimiento aeroportuario, pintura, acabados, climatización.\n"
        "- NO RELEVANTE: suministro de alimentos, software, vigilancia, uniformes.\n"
        "- Los contratos de obras civiles con valor mayor a COP 5.000.000 deben recibir score mínimo de 60, independiente del componente."
        "- Considera también contratos donde los clientes de SIACO puedan participar como subcontratista o aliado técnico.\n\n"
        "Tu respuesta debe ser estrictamente un objeto JSON plano, sin introducciones ni bloques de código."
    )

    user_prompt = f"""Analiza la viabilidad de la siguiente licitación:
- Entidad: {entidad}
- Objeto: {objeto}
- Descripción: {descripcion}
- Valor Base: COP {valor}
- Cierre de Recepción: {fecha_cierre}

Formato de salida requerido (JSON estricto):
{{"relevante": true, "score": 75, "motivo": "Explicación concisa", "accion": "PRESENTAR", "urgente": false}}"""

    try:
        respuesta = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            temperature=0.1,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        texto = respuesta.content[0].text.strip()
        return json.loads(texto)
    except Exception as e:
        print(f"Error analizando con Claude: {e}")
        return None    

def enviar_alerta_whatsapp(numero_celular, codigo, entidad, objeto, valor, score, motivo, url_proceso):
    mensaje = (
        f"🤖 *SIACO v1.2 - ALERTA DE OPORTUNIDAD SECOP II*\n"
        f"==================================\n\n"
        f"🏢 *Entidad:* {entidad}\n"
        f"📌 *Proceso:* {codigo}\n"
        f"💰 *Valor:* COP {valor}\n"
        f"🎯 *Score de Viabilidad:* {score}/100\n\n"
        f"💡 *Análisis Estratégico SIACO:*\n_{motivo}_\n\n"
        f"🔗 *Enlace Directo al Proceso:*\n{url_proceso}\n\n"
        f"==================================\n"
        f"📦 _SIACO - Inteligencia de Contratacion Publica Nacional_"
    )
    
    texto_codificado = urllib.parse.quote(mensaje)
    url_whatsapp = f"https://web.whatsapp.com/send?phone={numero_celular}&text={texto_codificado}"
    
    print(f"📱 Despachando alerta de WhatsApp en tu navegador para el proceso {codigo} al numero {numero_celular}...")
    webbrowser.open(url_whatsapp)
    time.sleep(25)

def ejecutar_agente():
    print("=" * 50)
    print("🤖 SIACO v1.2 - EN EJECUCIÓN")
    print(datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 50)
    
    licitaciones = buscar_licitaciones()
    if not licitaciones:
        print("No se obtuvieron registros de la API.")
        return
        
    licitaciones = filtrar_por_keywords(licitaciones)
    if not licitaciones:
        print("Ninguna coincidencia con las palabras clave (KEYWORDS).")
        return

    licitaciones = filtrar_por_fase(licitaciones)
    if not licitaciones:
        print("Ninguna en fase válida.")
        return

    licitaciones = filtrar_por_fecha_cierre(licitaciones)
    if not licitaciones:
        print("Todas las licitaciones tienen fechas de cierre demasiado próximas o vencidas.")
        return

    licitaciones = filtrar_por_valor(licitaciones)
    if not licitaciones:
        print("Ninguna superó el filtro de valor mínimo.")
        return
        
    print("Cargando perfiles de clientes...")
    clientes = cargar_clientes()

    print("Analizando con IA y cruzando con clientes...")
    resultados = []

    for lic in licitaciones:
        codigo = lic.get("id_del_proceso", lic.get("referencia_del_proceso", "SIN-CODIGO"))

        if codigo == "SIN-CODIGO":
            continue

        if ya_fue_enviado(codigo):
            print(f"Omitiendo (ya evaluada): {codigo}")
            continue

        print(f"Analizando proceso {codigo}...")
        analisis = analizar_licitacion(lic)

        if not analisis:
            guardar_enviado(codigo)
            continue

        guardar_enviado(codigo)

        if analisis.get("relevante", False):
            cruces = cruzar_licitacion_con_clientes(lic, clientes)
            clientes_viables = [c for c in cruces if c["pasa_filtro"] and c["analisis_ia"] and c["analisis_ia"].get("viable")]

            if clientes_viables:
                resultados.append({
                    "licitacion": lic,
                    "analisis": analisis,
                    "codigo": codigo,
                    "clientes_viables": clientes_viables
                })

    print(f"\nRESULTADOS: {len(resultados)} oportunidades con clientes viables encontradas")

    if not resultados:
        print("No se encontraron oportunidades con clientes viables.")
        return

    for r in resultados:
        lic = r["licitacion"]
        ans = r["analisis"]
        print("-" * 50)
        print(f"Proceso: {r['codigo']}")
        print(f"Entidad: {lic.get('entidad', 'N/A')}")
        print(f"Objeto: {lic.get('nombre_del_procedimiento', 'N/A')[:100]}")
        print(f"Valor: COP {lic.get('precio_base', 'N/A')}")
        print(f"Score SIACO: {ans.get('score', 0)}/100")
        print(f"Motivo: {ans.get('motivo', 'N/A')}")
        url_data = lic.get("urlproceso", {})
        url_final = url_data.get("url") if isinstance(url_data, dict) else url_data
        print(f"URL: {url_final if url_final else 'Ver en SECOP II'}")
        print(f"\nClientes viables para este contrato:")
        for c in r["clientes_viables"]:
            ia = c["analisis_ia"]
            print(f"  -> {c['cliente']}")
            print(f"     Score: {ia.get('score', 0)}/100 | Accion: {ia.get('accion', 'N/A')} | Riesgo: {ia.get('riesgo', 'N/A')}")
            print(f"     Motivo: {ia.get('motivo', 'N/A')}")

        if ans.get("score", 0) >= 65:
            LISTA_CONTACTOS = ["573138343997", "573125443346"]
            for numero in LISTA_CONTACTOS:
                enviar_alerta_whatsapp(
                    numero_celular=numero,
                    codigo=r["codigo"],
                    entidad=lic.get("entidad", "N/A"),
                    objeto=lic.get("nombre_del_procedimiento", "N/A")[:100],
                    valor=lic.get("precio_base", "N/A"),
                    score=ans.get("score", 0),
                    motivo=ans.get("motivo", "N/A"),
                    url_proceso=url_final if url_final else "N/A"
                )

if __name__ == "__main__":
    ejecutar_agente()