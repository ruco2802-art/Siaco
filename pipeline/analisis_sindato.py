# -*- coding: utf-8 -*-
"""
analisis_sindato.py — Tareas 2, 3 y 4 sin API.

Carga paicol_2026_resultado.json, re-ejecuta el evaluador con el
PERFIL_COMPLETO actualizado, luego clasifica cada sin_dato.

Ejecutar desde pipeline/:  python analisis_sindato.py
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import json

from src.clasificador import consolidar
from src.extractor import ResultadoExtraccion, Requisito
from src.evaluator import cargar_perfil, evaluar_empresa
from src.evaluator import _MAP_JUR, _MAP_FIN, _MAP_EXP  # introspección

# ── Perfil completo (igual que main.py, post-corrección) ──────────────────

PERFIL_COMPLETO: dict = {
    "nombre": "Constructora ABCD SAS",
    "es_mipyme": True,
    "municipio_domicilio": "Paicol",
    "departamento_domicilio": "Huila",
    "financiero": {
        "indice_liquidez": 1.85,
        "indice_endeudamiento": 0.42,
        "capital_trabajo": 450_000_000.0,
        "patrimonio_neto": 1_200_000_000.0,
        "renta_operacional": 3_500_000_000.0,
        "ebitda": 420_000_000.0,
        "rentabilidad_patrimonio": 0.18,
        "rentabilidad_activo": 0.09,
        "roe": 0.18,
        "roa": 0.09,
        "cobertura_intereses": 3.2,
        "saldos_contratos_en_ejecucion": 800_000_000.0,
        "numero_profesionales_vinculados": 12,
        "ingresos_operacionales_ultimos_5_anos": [
            2_800_000_000.0, 3_100_000_000.0, 3_500_000_000.0,
            3_700_000_000.0, 4_000_000_000.0,
        ],
    },
    "experiencia": {
        "valor_acumulado": 8_500_000_000.0,
        "valor_individual_max": 4_200_000_000.0,
        "objetos_similares": ["obra civil", "mantenimiento vial", "construcción"],
        "codigos_unspsc": ["72151501", "72151502", "72151601"],
        "contratos_acreditados": 3,
        "antiguedad_meses": 60,
    },
    "juridico": {
        "rup_en_firme": True,
        "camara_comercio": True,
        "paz_y_salvo_parafiscales": True,
        "paz_y_salvo_seguridad_social": True,
        "paz_y_salvo_impuestos": True,
        "paz_salvo_municipal": True,
        "sin_inhabilidades": True,
        "sin_antecedentes_disciplinarios": True,
        "sin_antecedentes_penales": True,
        "sin_antecedentes_fiscales": True,
        "sin_redam": True,
        "sin_medidas_correctivas": True,
        "sin_insolvencia": True,
        "objeto_social_compatible": True,
        "sin_conflicto_interes": True,
        "sin_estudios_diseno_previos": True,
        "garantia_seriedad": True,
        "rut_vigente": True,
    },
    "tecnico": {
        "personal_disponible": 15,
        "equipos": ["excavadora", "volqueta", "compactador"],
        "certificaciones": ["ISO 9001"],
        "titulo_profesional": "ingeniero",
        "porcentaje_empleados_colombianos": 95.0,
    },
    "social": {
        "porcentaje_mujeres_nomina": 0.35,
    },
}

# ── Carga resultado ──────────────────────────────────────────────────────

json_path = Path(__file__).parent.parent / "resultados_evaluacion" / "paicol_2026_resultado.json"
if not json_path.exists():
    print(f"ERROR: no se encontró {json_path}")
    sys.exit(1)

raw = json.loads(json_path.read_text("utf-8"))
res = ResultadoExtraccion(**raw)

# Consolidar (igual que en producción)
consolidado = consolidar(res.requisitos)
requisitos = consolidado.requisitos

perfil = cargar_perfil(PERFIL_COMPLETO)
ev = evaluar_empresa(perfil, requisitos)

# ── Helpers para introspección del mapa ─────────────────────────────────

def _keyword_jur(nombre: str) -> str | None:
    """Primera keyword de _MAP_JUR que coincide con el nombre."""
    nl = nombre.lower()
    for kw, _ in _MAP_JUR:
        if kw in nl:
            return kw
    return None

def _keyword_fin(nombre: str) -> str | None:
    nl = nombre.lower()
    for kw, _ in _MAP_FIN:
        if kw in nl:
            return kw
    return None

def _keyword_exp(nombre: str) -> str | None:
    nl = nombre.lower()
    for kw, _ in _MAP_EXP:
        if kw in nl:
            return kw
    return None

def _campo_jur(nombre: str) -> str | None:
    """Nombre del campo de PerfilJuridico que devolvería para este nombre."""
    nl = nombre.lower()
    for kw, fn in _MAP_JUR:
        if kw in nl:
            try:
                # Simular el lambda: obtener el nombre del atributo
                import inspect
                src = inspect.getsource(fn)
                # extrae p.xxx del source
                import re
                m = re.search(r"p\.(\w+)", src)
                return m.group(1) if m else "?"
            except Exception:
                return "?"
    return None

# ── Clasificación de cada sin_dato ─────────────────────────────────────

CAUSAS = {
    "falta_campo_perfil": [],
    "falta_mapeo":        [],
    "sin_criterio_evaluable": [],
    "no_aplica":          [],
}

sin_dato_items = [i for i in ev["items"] if i["estado"] in ("dato_faltante", "no_evaluable")]
no_aplica_items = [i for i in ev["items"] if i["estado"] == "no_aplica"]

# Mapear req.nombre → Requisito original para acceder a aplica_a
req_by_nombre: dict[str, Requisito] = {r.nombre: r for r in requisitos}

for item in sin_dato_items:
    nombre = item["requisito"]
    cat = item.get("categoria", "?")
    req = req_by_nombre.get(nombre)
    aplica_a = req.aplica_a if req else "todos"

    # d) no_aplica: extranjero sin domicilio (ya manejado en el evaluador,
    #    pero si aún aparece como sin_dato, lo marcamos aquí)
    if aplica_a == "extranjero_sin_domicilio":
        CAUSAS["no_aplica"].append((nombre, cat, "aplica_a=extranjero_sin_domicilio"))
        continue

    # Buscar keyword en el mapa correspondiente
    if cat in ("juridico", "documental"):
        kw = _keyword_jur(nombre)
    elif cat == "financiero":
        kw = _keyword_fin(nombre)
    elif cat == "experiencia":
        kw = _keyword_exp(nombre)
    else:
        kw = None

    if kw is None:
        # Sin keyword → sin_criterio_evaluable o falta_mapeo
        # Distinguimos: si el req tiene valor_umbral → debería ser evaluable pero no hay campo
        if req and (req.valor_umbral is not None or req.operador is not None):
            CAUSAS["sin_criterio_evaluable"].append(
                (nombre, cat, f"umbral={req.valor_umbral} {req.operador} — sin keyword")
            )
        else:
            CAUSAS["falta_mapeo"].append((nombre, cat, "sin keyword en el mapa"))
    else:
        # Hay keyword → el campo del perfil es None
        CAUSAS["falta_campo_perfil"].append((nombre, cat, f"keyword='{kw}' → campo no en perfil"))

# ── Reporte Tarea 1: cobertura global ───────────────────────────────────

print("=" * 72)
print("TAREA 1 — COBERTURA DE LA EVALUACIÓN (post-correcciones)")
print("=" * 72)
print(f"  Score global    : {ev['score_global']:.1f} / 100")
cob = ev.get("cobertura_global", 0.0)
td = ev.get("total_con_datos", 0)
te = ev.get("total_evaluados", 0)
print(f"  Cobertura global: {cob*100:.1f}%  ({td} de {te} req con dato)")
print(f"  Veredicto       : {ev['veredicto'].upper()}")

print()
print(f"  {'Categoría':<16} {'Score':>6}  {'Cob%':>5}  {'Cumple':>6}  "
      f"{'No_cumple':>9}  {'Sin_dato':>8}")
print(f"  {'─'*16} {'─'*6}  {'─'*5}  {'─'*6}  {'─'*9}  {'─'*8}")
for cat, st in ev["desglose"].items():
    score_s = f"{st['score']:.1f}" if st["score"] is not None else "  N/A"
    cob_s = f"{st['cobertura']*100:.0f}%"
    print(f"  {cat:<16} {score_s:>6}  {cob_s:>5}  {st['cumple']:>6}  "
          f"{st['no_cumple']:>9}  {st['dato_faltante']:>8}")

# ── Reporte Tarea 2: mapeo jurídico ─────────────────────────────────────

print()
print("=" * 72)
print("TAREA 2 — MAPEO DE CAMPOS JURÍDICOS")
print("=" * 72)

jur_items = [i for i in ev["items"] if i.get("categoria") in ("juridico", "documental")]
jur_cumple = [i for i in jur_items if i["estado"] == "cumple"]
jur_no_cumple = [i for i in jur_items if i["estado"] == "no_cumple"]
jur_sin_dato = [i for i in jur_items if i["estado"] in ("dato_faltante", "no_evaluable")]
jur_no_aplica = [i for i in jur_items if i["estado"] == "no_aplica"]

print(f"  Jurídico+documental total : {len(jur_items)}")
print(f"  cumple    : {len(jur_cumple)}")
print(f"  no_cumple : {len(jur_no_cumple)}")
print(f"  sin_dato  : {len(jur_sin_dato)}")
print(f"  no_aplica : {len(jur_no_aplica)}")

print()
print("  CUMPLE (jurídico):")
for i in jur_cumple:
    kw = _keyword_jur(i["requisito"]) or "—"
    print(f"    OK [{kw}]  {i['requisito']}")

print()
print("  SIN DATO (jurídico) — keyword encontrada:")
for i in jur_sin_dato:
    kw = _keyword_jur(i["requisito"])
    if kw:
        print(f"    ? [{kw}]  {i['requisito']}")

print()
print("  SIN DATO (jurídico) — sin keyword (falta mapeo):")
for i in jur_sin_dato:
    kw = _keyword_jur(i["requisito"])
    if not kw:
        print(f"    ? [sin_kw]  {i['requisito']}")

print()
print("  NO APLICA (jurídico):")
for i in jur_no_aplica:
    req = req_by_nombre.get(i["requisito"])
    print(f"    ø [{req.aplica_a if req else '?'}]  {i['requisito']}")

# ── Reporte Tarea 3: clasificación de los 47 sin_dato ───────────────────

print()
print("=" * 72)
print("TAREA 3 — LOS SIN_DATO CLASIFICADOS POR CAUSA")
print("=" * 72)
print(f"  Total sin_dato : {len(sin_dato_items)}")
for causa, lista in CAUSAS.items():
    print(f"  {causa:<26}: {len(lista)}")

for causa, lista in CAUSAS.items():
    if not lista:
        continue
    print(f"\n  [{causa.upper()}]")
    for nombre, cat, nota in lista:
        print(f"    [{cat}] {nombre}")
        print(f"           → {nota}")

# ── Reporte Tarea 4: campos faltantes del perfil ────────────────────────

print()
print("=" * 72)
print("TAREA 4 — CAMPOS FALTANTES DEL PERFIL (spec para el formulario web)")
print("=" * 72)
print("  Campos que el evaluador necesitó pero no encontró en el perfil:")
print("  (ordenados por categoría y frecuencia de aparición)")

# Extraer de sin_dato cuáles tienen keyword pero campo = None
campos_faltantes: dict[str, list[str]] = {}  # campo → lista de req que lo necesitan

for item in sin_dato_items:
    nombre = item["requisito"]
    cat = item.get("categoria", "?")
    req = req_by_nombre.get(nombre)

    if cat in ("juridico", "documental"):
        kw = _keyword_jur(nombre)
        if kw:
            # Encontrar el nombre del campo
            nl = nombre.lower()
            for k, fn in _MAP_JUR:
                if k in nl:
                    import inspect, re as _re
                    src = inspect.getsource(fn)
                    m = _re.search(r"p\.(\w+)", src)
                    campo = m.group(1) if m else f"juridico.{kw}"
                    campos_faltantes.setdefault(f"juridico.{campo}", []).append(nombre)
                    break
    elif cat == "financiero":
        kw = _keyword_fin(nombre)
        if kw:
            nl = nombre.lower()
            for k, fn in _MAP_FIN:
                if k in nl:
                    import inspect, re as _re
                    src = inspect.getsource(fn)
                    m = _re.search(r"p\.(\w+)", src)
                    campo = m.group(1) if m else f"financiero.{kw}"
                    campos_faltantes.setdefault(f"financiero.{campo}", []).append(nombre)
                    break
    elif cat == "experiencia":
        kw = _keyword_exp(nombre)
        if kw:
            nl = nombre.lower()
            for k, fn in _MAP_EXP:
                if k in nl:
                    import inspect, re as _re
                    src = inspect.getsource(fn)
                    m = _re.search(r"p\.(\w+)", src)
                    campo = m.group(1) if m else f"experiencia.{kw}"
                    campos_faltantes.setdefault(f"experiencia.{campo}", []).append(nombre)
                    break

# Campos sin keyword (no tienen campo asignable todavía)
sin_campo: list[tuple[str, str, str]] = []  # (nombre, cat, literal)
for item in sin_dato_items:
    nombre = item["requisito"]
    cat = item.get("categoria", "?")
    req = req_by_nombre.get(nombre)
    if cat in ("juridico", "documental"):
        kw = _keyword_jur(nombre)
    elif cat == "financiero":
        kw = _keyword_fin(nombre)
    elif cat == "experiencia":
        kw = _keyword_exp(nombre)
    else:
        kw = None
    if kw is None:
        literal = (req.exigido_literal or "")[:80] if req else ""
        sin_campo.append((nombre, cat, literal))

if campos_faltantes:
    print()
    print("  A) Tienen keyword/campo en el perfil pero el campo era None antes de la corrección:")
    for campo, reqs in sorted(campos_faltantes.items()):
        print(f"    {campo}  ← necesitado por {len(reqs)} req(s)")
        for r in reqs:
            print(f"         · {r}")

if sin_campo:
    print()
    print("  B) Sin keyword — requieren nuevo campo de perfil o nuevo mapeo:")
    for nombre, cat, literal in sin_campo:
        req = req_by_nombre.get(nombre)
        aplica_a = req.aplica_a if req else "todos"
        print(f"    [{cat}] [{aplica_a}] {nombre}")
        if literal:
            print(f"           literal: {literal[:80]}")

print()
print("ANÁLISIS COMPLETADO.")
