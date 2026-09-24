# -*- coding: utf-8 -*-
"""
Tarea 12 — Extracción por recorrido estructurado de secciones.

Pipeline de tres pasadas:
  Pasada 1: Mapa de secciones  — identifica estructura y marca candidatas.
  Pasada 2: Extracción focalizada — una llamada por sección candidata.
  Consolidación: une resultados, deduplica, registra cobertura.

Resultado: pliego_1_T12.json (no sobreescribe archivos de producción).

Uso:
  py -3.13 evaluar_t12.py
  py -3.13 evaluar_t12.py --pdf "16. PLIEGO DE CONDICIONES DEFINITIVO.pdf"
  py -3.13 evaluar_t12.py --pdf otro.pdf --salida otro_T12.json
  py -3.13 evaluar_t12.py --max-chars-seccion 200000
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

import anthropic as _anth

from analizador import (
    extraer_texto_documento,
    SCANNED_PDF_MARKER,
    DOC_NOT_SUPPORTED_MARKER,
    API_KEY,
)

SALIDA = _ROOT / "resultados_evaluacion"
SALIDA.mkdir(exist_ok=True)

# Pricing claude-sonnet-4-6 (USD / millón de tokens)
_PRECIO_IN  = 3.00
_PRECIO_OUT = 15.00

# CAMBIO 1: el tope pasa de 12 000 a 200 000 chars.
# 200 000 chars ≈ 55 000 tokens en ventana de 1 M — actúa como fusible
# contra un match patológico, no como presupuesto de entrada.
_MAX_CHARS_SECCION_DEFAULT = 200_000

# Modelo
_MODELO = "claude-sonnet-4-6"


# ── Prompt Pasada 1 ──────────────────────────────────────────────────────────

_PROMPT_P1 = """\
Analiza la estructura de este pliego de contratación pública colombiana.

Tu tarea: identificar las secciones del documento (niveles 1 y 2 únicamente — \
ej: '3' y '3.1', pero NO '3.1.1' ni más profundos) y determinar si contienen o \
podrían contener REQUISITOS HABILITANTES — condiciones que el proponente debe \
cumplir para que su oferta sea evaluada.

PROFUNDIDAD MÁXIMA: lista solo secciones de nivel 1 y nivel 2. \
No listes sub-numerales más profundos (ej: 3.1.1, 3.1.1.a). \
Si una sección de nivel 2 contiene listas de requisitos, es UN SOLO ítem del mapa.

Son CANDIDATAS las secciones sobre:
- Capacidad jurídica, documentos legales exigidos al proponente
- Capacidad financiera (indicadores, estados financieros, índices)
- Capacidad organizacional (experiencia, contratos previos, UNSPSC)
- Capacidad técnica o administrativa (personal, equipos, certificaciones)
- Requisitos de participación, habilitación, condiciones del proponente

NO son candidatas: objeto del contrato, descripción del bien/servicio, cronograma \
de actividades, condiciones económicas, pliego de cláusulas contractuales, \
términos del proceso, metodología de calificación de puntaje.

Incluye TODAS las secciones de nivel 1-2, incluso las que no son candidatas \
(las necesito para delimitar el texto de cada sección).

TEXTO DEL PLIEGO:
{texto}

Responde ÚNICAMENTE con JSON válido, sin texto antes ni después:
{{
  "secciones": [
    {{
      "id": "identificador tal como aparece (ej: '2.1', 'CAPÍTULO III', 'Numeral 3.9')",
      "titulo": "título literal de la sección tal como aparece en el documento",
      "candidata": true
    }}
  ]
}}"""


# ── Prompt Pasada 2 ──────────────────────────────────────────────────────────

_PROMPT_P2 = """\
Analiza la sección "{sec_id} — {sec_titulo}" de este pliego de contratación pública.

TAREA: Extrae los requisitos habilitantes que contiene ESTA SECCIÓN ÚNICAMENTE.
Un requisito habilitante es una condición que, si no se cumple, impide que la oferta \
sea evaluada.

DEFINICIÓN ESTRICTA DE UN REQUISITO (léela antes de reportar cualquier ítem):
- Es una condición INDEPENDIENTE: si el proponente incumple SOLO esta condición, su \
oferta no puede ser evaluada.
- Las notas, excepciones, aclaraciones, formas de acreditación y documentos de soporte \
de un mismo requisito NO son requisitos separados: van en el campo "detalles".
- ANTES DE REPORTAR DOS ÍTEMS: pregúntate si son dos condiciones independientes \
(si incumple solo una ¿sigue siendo descalificado?) o una condición con sus detalles. \
En caso de duda, consolida en uno.

REGLAS DE EXTRACCIÓN:
1. Solo el pliego es tu fuente. No apliques conocimiento general ni normativa externa.
2. Si el valor o umbral no aparece textualmente, escribe: NO_ENCONTRADO_EN_PLIEGO
3. Máx 200 chars por campo de texto libre.
4. Si esta sección NO contiene requisitos habilitantes, devuelve "requisitos": []
5. No excluyas requisitos por no tener umbral numérico — las declaraciones y \
certificados también son habilitantes.

TEXTO DE LA SECCIÓN:
{texto_seccion}

Responde ÚNICAMENTE con JSON válido, sin texto antes ni después:
{{
  "requisitos": [
    {{
      "requisito": "nombre corto del requisito",
      "exigido_literal": "cita textual del pliego o NO_ENCONTRADO_EN_PLIEGO (máx 200 chars)",
      "ubicacion_pliego": "{sec_id}",
      "documento_soporte": "documento requerido (máx 80 chars) o null",
      "detalles": ["nota o excepción relevante (máx 120 chars)"]
    }}
  ],
  "nota_seccion": "observación si la sección es ambigua o el texto está incompleto (máx 120 chars, null si no aplica)"
}}"""


# ── Utilidades ───────────────────────────────────────────────────────────────

def _costo(tok_in: int, tok_out: int) -> float:
    return (tok_in / 1_000_000) * _PRECIO_IN + (tok_out / 1_000_000) * _PRECIO_OUT


def _llamar(client, prompt: str, max_tokens: int, etiqueta: str) -> tuple[dict, dict]:
    """
    Llama al modelo y devuelve (resultado_json, meta).
    meta: {tokens_in, tokens_out, max_tokens, uso_pct, stop_reason, tiempo_s,
           ok, truncado, error}
    Si stop_reason == 'max_tokens', aborta ANTES de parsear el JSON y devuelve
    ok=False, truncado=True — el JSON truncado nunca se toca.
    """
    t0 = time.time()
    try:
        resp = client.messages.create(
            model=_MODELO,
            max_tokens=max_tokens,
            extra_body={"temperature": 0.0},
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = round(time.time() - t0, 1)
        stop    = resp.stop_reason
        tok_in  = resp.usage.input_tokens
        tok_out = resp.usage.output_tokens
        uso_pct = round(tok_out / max_tokens * 100, 1)

        print(f"    [{etiqueta}] {elapsed}s | stop={stop} | {tok_in}in / {tok_out}/{max_tokens}out ({uso_pct}%)")

        # CAMBIO 2: chequeo pre-parse — JSON truncado nunca se parsea.
        if stop == "max_tokens":
            print(f"    [{etiqueta}] TRUNCADO — stop=max_tokens. JSON descartado ({tok_out}/{max_tokens} tokens usados).")
            return {}, {
                "tokens_in": tok_in, "tokens_out": tok_out,
                "max_tokens": max_tokens, "uso_pct": uso_pct,
                "stop_reason": stop, "tiempo_s": elapsed,
                "ok": False, "truncado": True,
                "error": f"stop=max_tokens ({tok_out}/{max_tokens} tokens)",
            }

        texto = resp.content[0].text.strip()
        if texto.startswith("```"):
            lineas = texto.split("\n")
            texto = "\n".join(l for l in lineas if not l.startswith("```"))

        inicio = texto.find("{")
        fin = texto.rfind("}")
        if inicio != -1 and fin != -1:
            resultado = json.loads(texto[inicio:fin + 1])
        else:
            resultado = json.loads(texto)

        return resultado, {
            "tokens_in": tok_in, "tokens_out": tok_out,
            "max_tokens": max_tokens, "uso_pct": uso_pct,
            "stop_reason": stop, "tiempo_s": elapsed,
            "ok": True, "truncado": False, "error": None,
        }
    except Exception as exc:
        elapsed = round(time.time() - t0, 1)
        print(f"    [{etiqueta}] ERROR {type(exc).__name__}: {str(exc)[:120]}")
        return {}, {
            "tokens_in": 0, "tokens_out": 0,
            "max_tokens": max_tokens, "uso_pct": 0.0,
            "stop_reason": "error", "tiempo_s": elapsed,
            "ok": False, "truncado": False, "error": str(exc)[:200],
        }


# ── CAMBIO 3: segmentador reescrito ──────────────────────────────────────────

def _normalizar(s: str) -> str:
    """Colapsa todos los espacios en blanco (incluyendo saltos de línea) a un espacio."""
    return " ".join(s.split())


def _patron_seccion(seccion: dict) -> str | None:
    """
    Construye patrón regex para localizar el encabezado de una sección al inicio
    de línea. Devuelve None si la clave combinada tiene menos de 5 palabras.

    Reglas:
    - Clave = id + título (el id desambigua títulos repetidos).
    - Si el título ya empieza por el id, no se duplica.
    - Permite espaciado flexible (\s+) entre palabras del patrón para
      absorber saltos de línea que el PDF introduce dentro de los títulos.
    - Ancla al inicio de línea con ^\s* y re.MULTILINE.
    - Usa las primeras 10 palabras de la clave (suficiente para identificar la
      sección, robusto ante títulos largos con diferencias al final).
    """
    sec_id = _normalizar(seccion.get("id", ""))
    titulo = _normalizar(seccion.get("titulo", ""))
    # No duplicar el id si ya encabeza el título
    clave = titulo if titulo.lower().startswith(sec_id.lower()) else f"{sec_id} {titulo}".strip()
    palabras = clave.split()
    if len(palabras) < 5:
        return None
    fragmento = r"\s+".join(re.escape(p) for p in palabras[:10])
    return r"^\s*" + fragmento


def _extraer_texto_seccion(
    texto_pliego: str,
    seccion: dict,
    siguiente_seccion: dict | None,
    max_chars: int,
) -> tuple[str, str]:
    """
    Localiza el texto de una sección entre su encabezado y el del siguiente.
    Devuelve (texto_seccion, estado): 'ok' | 'truncado' | 'no_encontrado'.

    Busca el inicio al comienzo de línea (re.MULTILINE). Si el patrón
    resultante tiene menos de 5 palabras, devuelve no_encontrado sin fallback.
    Prefiere un fallo ruidoso a un corte silencioso.
    """
    patron_inicio = _patron_seccion(seccion)
    if patron_inicio is None:
        return "", "no_encontrado"

    m_inicio = re.search(patron_inicio, texto_pliego, re.IGNORECASE | re.MULTILINE)
    if m_inicio is None:
        return "", "no_encontrado"

    pos_inicio = m_inicio.start()
    pos_fin = len(texto_pliego)

    if siguiente_seccion:
        patron_fin = _patron_seccion(siguiente_seccion)
        if patron_fin:
            # Buscar solo a partir de 20 chars después del inicio para evitar
            # que el mismo encabezado haga match consigo mismo.
            m_fin = re.search(
                patron_fin,
                texto_pliego[pos_inicio + 20:],
                re.IGNORECASE | re.MULTILINE,
            )
            if m_fin:
                pos_fin = pos_inicio + 20 + m_fin.start()

    texto = texto_pliego[pos_inicio:pos_fin]
    if len(texto) > max_chars:
        return texto[:max_chars], "truncado"
    return texto, "ok"


def _encontrar_inicio_seccion(texto_pliego: str, seccion: dict) -> int:
    """
    Devuelve la posición de inicio de la sección, o -1 si no se localiza.
    Usa la misma lógica estricta que _extraer_texto_seccion.
    """
    patron = _patron_seccion(seccion)
    if patron is None:
        return -1
    m = re.search(patron, texto_pliego, re.IGNORECASE | re.MULTILINE)
    return m.start() if m else -1


# ── Consolidación ─────────────────────────────────────────────────────────────

def _normalizar_nombre(nombre: str) -> str:
    return " ".join(nombre.lower().split())


def _consolidar(resultados_secciones: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """
    Une requisitos de todas las secciones.
    Deduplica por nombre normalizado. Devuelve (requisitos, sin_req, con_error).
    """
    vistos: dict[str, dict] = {}
    orden_insercion: list[str] = []
    sin_req:   list[str] = []
    con_error: list[str] = []

    for bloque in resultados_secciones:
        sec_id = bloque["sec_id"]
        ok     = bloque["meta"]["ok"]

        if not ok:
            con_error.append(sec_id)
            continue

        reqs = bloque.get("requisitos", [])
        if not reqs:
            sin_req.append(sec_id)
            continue

        for req in reqs:
            nombre = req.get("requisito", "")
            clave  = _normalizar_nombre(nombre)
            if clave in vistos:
                ub_existente = vistos[clave].get("ubicacion_pliego", "")
                ub_nueva     = req.get("ubicacion_pliego", "")
                if ub_nueva and ub_nueva not in ub_existente:
                    vistos[clave]["ubicacion_pliego"] = f"{ub_existente}; {ub_nueva}"
                if (
                    vistos[clave].get("exigido_literal") == "NO_ENCONTRADO_EN_PLIEGO"
                    and req.get("exigido_literal") != "NO_ENCONTRADO_EN_PLIEGO"
                ):
                    vistos[clave]["exigido_literal"] = req.get("exigido_literal")
                det_existentes = set(vistos[clave].get("detalles") or [])
                for d in req.get("detalles") or []:
                    det_existentes.add(d)
                vistos[clave]["detalles"] = list(det_existentes)
            else:
                vistos[clave] = {
                    "requisito":         nombre,
                    "exigido_literal":   req.get("exigido_literal", "NO_ENCONTRADO_EN_PLIEGO"),
                    "ubicacion_pliego":  req.get("ubicacion_pliego", sec_id),
                    "documento_soporte": req.get("documento_soporte"),
                    "detalles":          req.get("detalles") or [],
                    "seccion_origen":    sec_id,
                }
                orden_insercion.append(clave)

    return [vistos[c] for c in orden_insercion], sin_req, con_error


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Tarea 12 — Extracción por recorrido estructurado")
    parser.add_argument("--pdf", default="16. PLIEGO DE CONDICIONES DEFINITIVO.pdf")
    parser.add_argument("--salida", default=None)
    parser.add_argument("--max-chars-seccion", type=int, default=_MAX_CHARS_SECCION_DEFAULT)
    args = parser.parse_args()

    pdf_path = _ROOT / "pliegos_evaluacion" / args.pdf
    if not pdf_path.exists():
        print(f"ERROR: no se encontró {pdf_path}")
        sys.exit(1)

    salida_nombre = args.salida or f"{pdf_path.stem}_T12.json"
    out_path = SALIDA / salida_nombre

    print("=" * 62)
    print("TAREA 12 — Extracción por recorrido estructurado")
    print(f"  PDF    : {pdf_path.name}")
    print(f"  Salida : {out_path.name}")
    print(f"  Max chars/sección: {args.max_chars_seccion:,}")
    print("=" * 62)

    # ── Extracción de texto ──────────────────────────────────────────────────
    print("\n[1] Extrayendo texto completo del pliego...")
    raw = pdf_path.read_bytes()
    texto, fmt = extraer_texto_documento(raw, pdf_path.name)
    if texto in (SCANNED_PDF_MARKER, DOC_NOT_SUPPORTED_MARKER) or not texto.strip():
        print(f"ERROR: no se pudo extraer texto ({texto[:50]})")
        sys.exit(1)
    chars_totales_pliego = len(texto)
    print(f"     {chars_totales_pliego:,} chars | formato: {fmt}")

    client = _anth.Anthropic(api_key=API_KEY, timeout=300.0, max_retries=1)

    tok_total_in  = 0
    tok_total_out = 0
    t_global      = time.time()

    # ── Pasada 1: mapa de secciones ──────────────────────────────────────────
    print("\n[2] Pasada 1 — Mapa de secciones...")
    prompt_p1 = _PROMPT_P1.format(texto=texto)
    p1_resultado, p1_meta = _llamar(client, prompt_p1, max_tokens=4_000, etiqueta="P1-mapa")
    tok_total_in  += p1_meta["tokens_in"]
    tok_total_out += p1_meta["tokens_out"]

    if not p1_meta["ok"]:
        print(f"ERROR en Pasada 1: {p1_meta['error']}")
        sys.exit(1)

    secciones  = p1_resultado.get("secciones", [])
    candidatas = [s for s in secciones if s.get("candidata")]
    print(f"     {len(secciones)} secciones identificadas | {len(candidatas)} candidatas")
    for s in candidatas:
        print(f"       ✓  {s['id']:<10}  {s['titulo'][:55]}")

    # ── CAMBIO 4: validar orden del mapa ─────────────────────────────────────
    print(f"\n[2b] Validando orden del mapa ({len(secciones)} secciones)...")
    posiciones_mapa: list[tuple[str, int]] = []
    for sec in secciones:
        pos = _encontrar_inicio_seccion(texto, sec)
        posiciones_mapa.append((sec.get("id", "?"), pos))

    orden_mapa_valido = True
    for i in range(1, len(posiciones_mapa)):
        id_prev, pos_prev = posiciones_mapa[i - 1]
        id_curr, pos_curr = posiciones_mapa[i]
        if pos_prev != -1 and pos_curr != -1 and pos_curr <= pos_prev:
            print(f"  WARNING orden: '{id_prev}'(pos={pos_prev}) → '{id_curr}'(pos={pos_curr}) — no monótono")
            orden_mapa_valido = False

    localizadas   = sum(1 for _, p in posiciones_mapa if p != -1)
    no_localizadas = sum(1 for _, p in posiciones_mapa if p == -1)
    print(f"     orden_mapa_valido={orden_mapa_valido} | localizadas={localizadas}/{len(secciones)} | no_localizadas={no_localizadas}")

    # ── Pasada 2: extracción por sección ─────────────────────────────────────
    print(f"\n[3] Pasada 2 — Extracción por sección ({len(candidatas)} llamadas)...")

    resultados_secciones:  list[dict] = []
    stop_reasons_p2:       list[str]  = []
    truncamientos_entrada: list[str]  = []  # CAMBIO 2: entrada separada de salida
    truncamientos_salida:  list[str]  = []  # CAMBIO 2
    chars_enviados_total:  int        = 0   # CAMBIO 5: acumulador auditoría

    for idx, sec in enumerate(candidatas):
        sec_id    = sec.get("id", f"sec_{idx}")
        sec_titulo = sec.get("titulo", "")

        # Sección siguiente en el mapa (para delimitar el texto)
        pos_en_mapa = secciones.index(sec) if sec in secciones else -1
        siguiente_seccion = (
            secciones[pos_en_mapa + 1]
            if pos_en_mapa != -1 and pos_en_mapa + 1 < len(secciones)
            else None
        )

        # CAMBIO 3: nueva firma — pasa dicts completos, no strings
        texto_sec, estado_extraccion = _extraer_texto_seccion(
            texto, sec, siguiente_seccion, args.max_chars_seccion
        )

        etiqueta = f"P2-{sec_id[:12]}"
        chars_sec = len(texto_sec)

        if not texto_sec:
            print(f"  [{etiqueta}] Sección no localizada en el texto — marcada como error")
            resultados_secciones.append({
                "sec_id":            sec_id,
                "sec_titulo":        sec_titulo,
                "extraccion_estado": estado_extraccion,
                "chars_extraidos":   0,
                "texto_sec_tail":    None,
                "meta": {
                    "ok": False, "truncado": False,
                    "error": "texto_no_encontrado",
                    "tokens_in": 0, "tokens_out": 0,
                    "max_tokens": 8_000, "uso_pct": 0.0,
                    "stop_reason": "skipped", "tiempo_s": 0,
                },
                "requisitos": [],
                "nota_seccion": None,
            })
            continue

        chars_enviados_total += chars_sec

        # CAMBIO 2: truncado de ENTRADA registrado aquí, antes de llamar al modelo
        if estado_extraccion == "truncado":
            print(f"  [{etiqueta}] ENTRADA truncada a {args.max_chars_seccion:,} chars — registrando en truncamientos_entrada")
            truncamientos_entrada.append(sec_id)

        prompt_p2 = _PROMPT_P2.format(
            sec_id=sec_id,
            sec_titulo=sec_titulo,
            texto_seccion=texto_sec,
        )

        p2_resultado, p2_meta = _llamar(client, prompt_p2, max_tokens=8_000, etiqueta=etiqueta)
        tok_total_in  += p2_meta["tokens_in"]
        tok_total_out += p2_meta["tokens_out"]
        stop_reasons_p2.append(f"{sec_id}:{p2_meta['stop_reason']}")

        # CAMBIO 2: truncado de SALIDA (stop=max_tokens) registrado por separado
        if p2_meta.get("truncado"):
            truncamientos_salida.append(sec_id)

        reqs = p2_resultado.get("requisitos", []) if p2_meta["ok"] else []
        nota = p2_resultado.get("nota_seccion")   if p2_meta["ok"] else None
        if nota:
            print(f"       nota: {nota}")

        resultados_secciones.append({
            "sec_id":            sec_id,
            "sec_titulo":        sec_titulo,
            "extraccion_estado": estado_extraccion,
            "chars_extraidos":   chars_sec,                   # CAMBIO 5
            "texto_sec_tail":    texto_sec[-80:] if texto_sec else None,  # CAMBIO 5
            "meta":              p2_meta,
            "requisitos":        reqs,
            "nota_seccion":      nota,
        })

    # ── Consolidación ─────────────────────────────────────────────────────────
    print("\n[4] Consolidando resultados...")
    reqs_finales, sec_sin_req, sec_con_error = _consolidar(resultados_secciones)

    secs_procesadas = len(candidatas) - len(sec_con_error)
    print(f"     {len(reqs_finales)} requisitos consolidados")

    # ── CAMBIO 5: auditoría de cobertura de segmentación ─────────────────────
    cobertura_pct = round(chars_enviados_total / chars_totales_pliego * 100, 1) if chars_totales_pliego else 0.0
    secciones_no_localizadas = [
        r["sec_id"] for r in resultados_secciones
        if r["meta"].get("error") == "texto_no_encontrado"
    ]
    auditoria_segmentacion = {
        "chars_totales_pliego": chars_totales_pliego,
        "chars_enviados_a_p2":  chars_enviados_total,
        "cobertura_pct":        cobertura_pct,
        "secciones_no_localizadas": secciones_no_localizadas,
        "por_seccion": [
            {
                "sec_id":        r["sec_id"],
                "chars_extraidos": r["chars_extraidos"],
                "tokens_in":     r["meta"]["tokens_in"],
                "fin_texto":     r.get("texto_sec_tail"),
            }
            for r in resultados_secciones
            if r["chars_extraidos"] > 0
        ],
    }

    # ── Bloque recorrido ─────────────────────────────────────────────────────
    # CAMBIO 2: truncamientos de ENTRADA o de SALIDA bloquean "completo".
    todos_truncamientos = truncamientos_entrada + [
        s for s in truncamientos_salida if s not in truncamientos_entrada
    ]
    estado_analisis = (
        "completo"
        if secs_procesadas >= len(candidatas) and not todos_truncamientos
        else "parcial"
    )

    recorrido = {
        "secciones_identificadas":  len(secciones),
        "secciones_candidatas":     len(candidatas),
        "secciones_procesadas":     secs_procesadas,
        "secciones_sin_requisitos": sec_sin_req,
        "secciones_con_error":      sec_con_error,
        "truncamientos_entrada":    truncamientos_entrada,   # CAMBIO 2
        "truncamientos_salida":     truncamientos_salida,    # CAMBIO 2
        "orden_mapa_valido":        orden_mapa_valido,       # CAMBIO 4
        "estado":                   estado_analisis,
    }

    t_total = round(time.time() - t_global, 1)
    costo   = _costo(tok_total_in, tok_total_out)

    metricas = {
        "tokens_p1_in":        p1_meta["tokens_in"],
        "tokens_p1_out":       p1_meta["tokens_out"],
        "stop_reason_p1":      p1_meta["stop_reason"],
        "tokens_p2_total_in":  tok_total_in  - p1_meta["tokens_in"],
        "tokens_p2_total_out": tok_total_out - p1_meta["tokens_out"],
        "stop_reasons_p2":     stop_reasons_p2,
        "tokens_total_in":     tok_total_in,
        "tokens_total_out":    tok_total_out,
        "costo_usd":           round(costo, 5),
        "tiempo_total_s":      t_total,
        "llamadas_p2":         len(candidatas),
    }

    # ── Guardar JSON ─────────────────────────────────────────────────────────
    resultado_final = {
        "experimento":         "t12_recorrido_estructurado",
        "pliego":              pdf_path.name,
        "timestamp":           datetime.now().isoformat(),
        "recorrido":           recorrido,
        "metricas":            metricas,
        "auditoria_segmentacion": auditoria_segmentacion,   # CAMBIO 5
        "secciones_mapa":          secciones,
        "detalle_por_seccion":     resultados_secciones,
        "requisitos_consolidados": reqs_finales,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(resultado_final, f, ensure_ascii=False, indent=2)
    print(f"\n  >> Guardado: {out_path.name}")

    # ── Tabla de control ──────────────────────────────────────────────────────
    sep = "─" * 72
    n_req_2121 = sum(
        1 for r in reqs_finales
        if "2.12.1" in (r.get("seccion_origen") or "") or
           "2.12.1" in (r.get("ubicacion_pliego") or "")
    )

    print(f"\n{sep}")
    print("TABLA DE CONTROL — Tarea 12 (recorrido estructurado)")
    print(sep)
    print(f"  Secciones identificadas : {len(secciones)}")
    print(f"  Secciones candidatas    : {len(candidatas)}")
    print(f"  Secciones procesadas    : {secs_procesadas}")
    if sec_sin_req:
        print(f"  Sin requisitos          : {', '.join(sec_sin_req)}")
    if sec_con_error:
        print(f"  Con error               : {', '.join(sec_con_error)}")
    if truncamientos_entrada:
        print(f"  Truncam. ENTRADA        : {', '.join(truncamientos_entrada)}")
    if truncamientos_salida:
        print(f"  Truncam. SALIDA         : {', '.join(truncamientos_salida)}")
    print(f"  orden_mapa_valido       : {orden_mapa_valido}")
    print(f"  Estado análisis         : {estado_analisis}")
    print(sep)
    print(f"  Req. habilitantes total : {len(reqs_finales)}")
    print(f"  Req. sección 2.12.1     : {n_req_2121}  (anterior: 7)")
    print(sep)
    print(f"  Cobertura segmentación  : {cobertura_pct}%  "
          f"({chars_enviados_total:,}/{chars_totales_pliego:,} chars)")
    if secciones_no_localizadas:
        print(f"  No localizadas          : {', '.join(secciones_no_localizadas)}")
    print(sep)
    print(f"  Tokens entrada total    : {tok_total_in:,}  (P1={p1_meta['tokens_in']:,} | P2={tok_total_in - p1_meta['tokens_in']:,})")
    print(f"  Tokens salida total     : {tok_total_out:,}  (P1={p1_meta['tokens_out']:,} | P2={tok_total_out - p1_meta['tokens_out']:,})")
    print(f"  Costo estimado          : ${costo:.4f} USD")
    print(f"  Tiempo total            : {t_total}s")
    print(f"  Llamadas P2             : {len(candidatas)}")
    print(f"  stop_reason P1          : {p1_meta['stop_reason']}")
    print(f"  stop_reason P2          : {', '.join(stop_reasons_p2)}")
    print(sep)
    print(f"\nResultado: {out_path.resolve()}")


if __name__ == "__main__":
    main()
