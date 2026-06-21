# -*- coding: utf-8 -*-
import json
import re
from datetime import datetime
from pathlib import Path


def extraer_datos_oferta(pdf_bytes: bytes, proceso_id: str, nit_competidor: str) -> dict:
    """
    Usa Claude para extraer datos clave de la oferta de un competidor.
    Guarda resultado en /competidores/{proceso_id}/{nit}.json
    """
    import anthropic
    from config import API_KEY

    texto = ""
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        texto = "\n".join(p.get_text() for p in doc)[:12000]
    except Exception as e:
        return {"ok": False, "error": f"Error extrayendo PDF: {e}"}

    client = anthropic.Anthropic(api_key=API_KEY)
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            temperature=0.0,
            messages=[{
                "role": "user",
                "content": (
                    f"Extrae los siguientes datos de esta oferta de licitación pública colombiana.\n"
                    f"Texto:\n{texto}\n\n"
                    f"Responde SOLO con JSON sin texto adicional:\n"
                    f'{{"precio_ofertado": numero_o_null, "experiencia_declarada": "resumen corto", '
                    f'"personal_propuesto": "resumen corto", "metodologia": "resumen corto", '
                    f'"certificaciones": ["cert1", "cert2"]}}'
                ),
            }],
        )
        txt = resp.content[0].text.strip()
        if "```" in txt:
            partes = txt.split("```")
            for frag in partes[1::2]:
                limpio = frag.strip()
                if limpio.lower().startswith("json"):
                    limpio = limpio[4:].strip()
                if limpio:
                    txt = limpio
                    break
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        datos = json.loads(m.group(0)) if m else {}
    except Exception as e:
        datos = {"error": str(e)}

    datos.update({
        "nit": nit_competidor,
        "proceso_id": proceso_id,
        "fecha_extraccion": datetime.now().isoformat(),
    })

    ruta = Path(f"./competidores/{proceso_id}")
    ruta.mkdir(parents=True, exist_ok=True)
    with open(ruta / f"{nit_competidor}.json", "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

    return {"ok": True, "datos": datos}


def actualizar_inteligencia_competitiva(nit: str, datos_proceso: dict):
    """Actualiza perfil acumulado del competidor en /competidores/inteligencia.json."""
    ruta_intel = Path("./competidores/inteligencia.json")
    ruta_intel.parent.mkdir(parents=True, exist_ok=True)

    intel = {}
    if ruta_intel.exists():
        try:
            with open(ruta_intel, "r", encoding="utf-8") as f:
                intel = json.load(f)
        except Exception:
            intel = {}

    if nit not in intel:
        intel[nit] = {
            "nit": nit,
            "nombre": datos_proceso.get("nombre", ""),
            "sectores_frecuentes": [],
            "rango_precios": {"min": None, "max": None, "promedio": None},
            "procesos_ganados": 0,
            "procesos_perdidos": 0,
            "estrategias": [],
            "historial_precios": [],
        }

    perfil = intel[nit]
    precio = datos_proceso.get("precio_ofertado")
    if precio:
        try:
            precio = float(precio)
            perfil["historial_precios"].append(precio)
            ps = perfil["historial_precios"]
            perfil["rango_precios"] = {
                "min": min(ps),
                "max": max(ps),
                "promedio": sum(ps) / len(ps),
            }
        except Exception:
            pass

    sector = datos_proceso.get("sector")
    if sector and sector not in perfil["sectores_frecuentes"]:
        perfil["sectores_frecuentes"].append(sector)

    with open(ruta_intel, "w", encoding="utf-8") as f:
        json.dump(intel, f, ensure_ascii=False, indent=2)


def cargar_inteligencia_competidor(nit: str) -> dict:
    """Retorna perfil acumulado del competidor, o {} si no existe."""
    ruta = Path("./competidores/inteligencia.json")
    if not ruta.exists():
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            intel = json.load(f)
        return intel.get(nit, {})
    except Exception:
        return {}


def generar_estrategia_oferta(cliente_id: str, proceso_id: str, competidores_proceso: list) -> dict:
    """
    Genera estrategia de oferta comparando perfil cliente vs inteligencia acumulada de competidores.
    """
    import anthropic
    from config import API_KEY

    perfil_cliente = {}
    ruta_perfil = Path(f"./clientes/{cliente_id}/perfil.json")
    if ruta_perfil.exists():
        try:
            with open(ruta_perfil, "r", encoding="utf-8") as f:
                perfil_cliente = json.load(f)
        except Exception:
            pass

    perfiles_comp = [cargar_inteligencia_competidor(c.get("nit", "")) for c in competidores_proceso]

    client = anthropic.Anthropic(api_key=API_KEY)
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            temperature=0.1,
            messages=[{
                "role": "user",
                "content": (
                    f"Eres experto en estrategia de licitaciones públicas colombianas.\n\n"
                    f"PERFIL CLIENTE:\n{json.dumps(perfil_cliente, ensure_ascii=False)[:2000]}\n\n"
                    f"COMPETIDORES ANALIZADOS:\n{json.dumps(perfiles_comp, ensure_ascii=False)[:3000]}\n\n"
                    f"Responde SOLO con JSON:\n"
                    f'{{"precio_sugerido": numero_o_null, "fortalezas_a_destacar": ["f1"], '
                    f'"advertencias": ["adv1"], "template_oferta_estructura": "descripcion estructura oferta"}}'
                ),
            }],
        )
        txt = resp.content[0].text.strip()
        if "```" in txt:
            partes = txt.split("```")
            for frag in partes[1::2]:
                limpio = frag.strip()
                if limpio.lower().startswith("json"):
                    limpio = limpio[4:].strip()
                if limpio:
                    txt = limpio
                    break
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        return json.loads(m.group(0)) if m else {}
    except Exception as e:
        return {"error": str(e)}


def listar_competidores_proceso(proceso_id: str) -> list:
    """Lista todos los competidores analizados para un proceso."""
    ruta = Path(f"./competidores/{proceso_id}")
    if not ruta.exists():
        return []
    resultado = []
    for f in ruta.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                resultado.append(json.load(fp))
        except Exception:
            pass
    return resultado
