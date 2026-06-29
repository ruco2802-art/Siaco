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
    import os; API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

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
    import os; API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

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


# ── Módulo 2: Modelo matemático de decisión de precio ────────────────────────

METODOS_CALIFICACION = {
    "media_aritmetica":      "Media aritmética",
    "media_geometrica":      "Media geométrica",
    "menor_valor":           "Menor valor",
    "media_aritmetica_alta": "Media aritmética alta",
}


def calcular_probabilidad(
    precio_oferta:          float,
    precios_historicos:     list,
    metodo_calificacion:    str,
    n_proponentes:          int,
    precio_minimo_cliente:  float,
    presupuesto_oficial:    float,
    n_simulaciones:         int = 1_000,
) -> dict:
    """
    Estima probabilidad de adjudicación via simulación Monte Carlo.
    Usa historial de precios de competidores como distribución de referencia.
    """
    import numpy as np

    precios_validos = [float(p) for p in precios_historicos if p and float(p) > 0]

    if len(precios_validos) < 3:
        # Estimación conservadora sin suficiente historial
        pbase = 0.40 if metodo_calificacion == "menor_valor" else 0.35
        prob  = pbase * (presupuesto_oficial / max(precio_oferta, 1)) if precio_oferta > presupuesto_oficial * 0.6 else pbase
        return {
            "probabilidad":          round(min(prob, 0.99), 2),
            "confianza":             "baja",
            "mensaje":               "Historial insuficiente — estimación aproximada (menos de 3 datos históricos)",
            "precio_ideal_estimado": round(presupuesto_oficial * 0.88),
            "rango_competitivo":     {
                "minimo": round(presupuesto_oficial * 0.70),
                "maximo": round(presupuesto_oficial * 0.95),
            },
        }

    media = np.mean(precios_validos)
    desv  = np.std(precios_validos) or media * 0.08   # mínimo 8% de desviación

    # Precio temerario: 70% del presupuesto oficial (criterio SECOP habitual)
    precio_temerario = presupuesto_oficial * 0.70

    ganadoras = 0
    rng = np.random.default_rng(42)
    for _ in range(n_simulaciones):
        n_otros = max(n_proponentes - 1, 1)
        sim = rng.normal(media, desv, n_otros)
        sim = np.clip(sim, precio_minimo_cliente * 0.90, presupuesto_oficial * 1.0)
        todas = np.append(sim, precio_oferta)

        if precio_oferta < precio_temerario:
            continue   # oferta temeraria — eliminada

        if metodo_calificacion == "media_aritmetica":
            ideal    = np.mean(todas)
            distanc  = np.abs(todas - ideal)
            if np.argmin(distanc) == len(todas) - 1:
                ganadoras += 1

        elif metodo_calificacion == "media_geometrica":
            validos  = todas[todas > 0]
            ideal    = float(np.exp(np.mean(np.log(validos))))
            distanc  = np.abs(todas - ideal)
            if np.argmin(distanc) == len(todas) - 1:
                ganadoras += 1

        elif metodo_calificacion == "menor_valor":
            if precio_oferta == np.min(todas):
                ganadoras += 1

        elif metodo_calificacion == "media_aritmetica_alta":
            # Favorece precios por encima del promedio
            ideal   = np.mean(todas) * 1.08
            distanc = np.abs(todas - ideal)
            if np.argmin(distanc) == len(todas) - 1:
                ganadoras += 1

        else:   # fallback: media aritmética
            ideal   = np.mean(todas)
            distanc = np.abs(todas - ideal)
            if np.argmin(distanc) == len(todas) - 1:
                ganadoras += 1

    probabilidad = ganadoras / n_simulaciones
    confianza    = "alta" if len(precios_validos) >= 5 else "media"

    return {
        "probabilidad":          round(probabilidad, 2),
        "confianza":             confianza,
        "mensaje":               f"Basado en {len(precios_validos)} precios históricos y {n_simulaciones} simulaciones",
        "precio_ideal_estimado": round(float(media)),
        "rango_competitivo":     {
            "minimo": round(float(max(media - desv, precio_minimo_cliente))),
            "maximo": round(float(min(media + desv, presupuesto_oficial))),
        },
    }


def modelo_precio_optimo(
    precio_minimo_cliente:  float,
    presupuesto_oficial:    float,
    precios_historicos:     list,
    metodo_calificacion:    str = "media_aritmetica",
    n_proponentes:          int = 3,
) -> dict:
    """
    Calcula precios estratégicos y sus probabilidades de adjudicación.
    Retorna escenarios: mínimo / agresivo / óptimo / conservador.
    """
    precios_validos = [float(p) for p in precios_historicos if p and float(p) > 0]

    # Definir escenarios de precio
    if precios_validos:
        import numpy as np
        media_hist = float(np.mean(precios_validos))
    else:
        media_hist = presupuesto_oficial * 0.88   # estimación sin historial

    # Factores según metodología de calificación
    factores = {
        "media_aritmetica":      {"agresivo": 0.97, "optimo": 0.99, "conservador": 1.03},
        "media_geometrica":      {"agresivo": 0.96, "optimo": 0.98, "conservador": 1.02},
        "menor_valor":           {"agresivo": 1.01, "optimo": 1.03, "conservador": 1.08},
        "media_aritmetica_alta": {"agresivo": 1.02, "optimo": 1.05, "conservador": 1.10},
    }
    f = factores.get(metodo_calificacion, factores["media_aritmetica"])

    # Precios base: usar media histórica o presupuesto como referencia
    base = media_hist if precios_validos else presupuesto_oficial * 0.88

    precio_agresivo    = max(precio_minimo_cliente * 1.01, base * f["agresivo"])
    precio_optimo      = max(precio_minimo_cliente * 1.03, base * f["optimo"])
    precio_conservador = max(precio_minimo_cliente * 1.05, base * f["conservador"])

    # Asegurar que ninguno supera el presupuesto oficial
    tope = presupuesto_oficial * 0.99
    precio_agresivo    = min(precio_agresivo,    tope)
    precio_optimo      = min(precio_optimo,      tope)
    precio_conservador = min(precio_conservador, tope)

    def _prob(p):
        return calcular_probabilidad(
            precio_oferta         = p,
            precios_historicos    = precios_historicos,
            metodo_calificacion   = metodo_calificacion,
            n_proponentes         = n_proponentes,
            precio_minimo_cliente = precio_minimo_cliente,
            presupuesto_oficial   = presupuesto_oficial,
        )

    prob_ag  = _prob(precio_agresivo)
    prob_op  = _prob(precio_optimo)
    prob_con = _prob(precio_conservador)

    def _utilidad(precio):
        return max(0.0, precio - precio_minimo_cliente)

    util_ag  = _utilidad(precio_agresivo)
    util_op  = _utilidad(precio_optimo)
    util_con = _utilidad(precio_conservador)

    # Recomendación textual
    metodo_label = METODOS_CALIFICACION.get(metodo_calificacion, metodo_calificacion)
    n_hist = len(precios_validos)
    confianza = prob_op["confianza"]

    if metodo_calificacion == "menor_valor":
        estrategia_txt = (
            f"El proceso usa MENOR VALOR — gana quien oferte el precio más bajo sin ser temerario. "
            f"Recomendamos el precio agresivo de {_fmt_cop(precio_agresivo)}, que está apenas por encima "
            f"de su costo mínimo y maximiza la probabilidad de adjudicación ({int(prob_ag['probabilidad']*100)}%). "
            f"No se recomienda el precio conservador en este método de calificación."
        )
    elif metodo_calificacion in ("media_aritmetica", "media_geometrica"):
        estrategia_txt = (
            f"El proceso usa {metodo_label} — gana quien más se acerque al promedio del grupo. "
            f"Con {n_hist} ofertas históricas analizadas (confianza {confianza}), el precio ideal estimado "
            f"es de {_fmt_cop(prob_op['precio_ideal_estimado'])}. Recomendamos ofertar "
            f"{_fmt_cop(precio_optimo)} (probabilidad {int(prob_op['probabilidad']*100)}%, "
            f"utilidad {_fmt_cop(util_op)}). "
            f"Si prefiere maximizar la probabilidad de ganar, oferte {_fmt_cop(precio_agresivo)} "
            f"(probabilidad {int(prob_ag['probabilidad']*100)}% pero utilidad {_fmt_cop(util_ag)}). "
            f"Si prefiere mayor margen, oferte {_fmt_cop(precio_conservador)} "
            f"(probabilidad {int(prob_con['probabilidad']*100)}%, utilidad {_fmt_cop(util_con)})."
        )
    else:
        estrategia_txt = (
            f"El proceso usa {metodo_label}. Precio óptimo estimado: {_fmt_cop(precio_optimo)} "
            f"(probabilidad {int(prob_op['probabilidad']*100)}%)."
        )

    advertencias = []
    if n_hist < 3:
        advertencias.append("Con menos de 3 competidores históricos, la precisión del modelo es limitada.")
    if n_proponentes <= 2:
        advertencias.append("Con pocos proponentes esperados, la probabilidad puede variar significativamente.")
    advertencias.append("Si el método de calificación cambia por adenda, recalcule la estrategia.")
    advertencias.append("Verifique que el precio óptimo no está por debajo del precio mínimo (no perder dinero).")

    return {
        "precio_minimo":        round(precio_minimo_cliente),
        "precio_agresivo":      round(precio_agresivo),
        "precio_optimo":        round(precio_optimo),
        "precio_conservador":   round(precio_conservador),
        "probabilidades": {
            "agresivo":    prob_ag["probabilidad"],
            "optimo":      prob_op["probabilidad"],
            "conservador": prob_con["probabilidad"],
        },
        "utilidades_proyectadas": {
            "agresivo":    round(util_ag),
            "optimo":      round(util_op),
            "conservador": round(util_con),
        },
        "utilidades_pct": {
            "agresivo":    round(util_ag / max(precio_agresivo, 1) * 100, 1),
            "optimo":      round(util_op / max(precio_optimo, 1) * 100, 1),
            "conservador": round(util_con / max(precio_conservador, 1) * 100, 1),
        },
        "metodo_calificacion":        metodo_calificacion,
        "metodo_label":               metodo_label,
        "precio_ideal_estimado":      prob_op["precio_ideal_estimado"],
        "rango_competitivo":          prob_op["rango_competitivo"],
        "n_historicos_analizados":    n_hist,
        "n_proponentes_esperados":    n_proponentes,
        "confianza_modelo":           confianza,
        "estrategia_recomendada":     estrategia_txt,
        "advertencias":               advertencias,
    }


def _fmt_cop(v: float) -> str:
    return f"${int(round(v)):,}".replace(",", ".")
