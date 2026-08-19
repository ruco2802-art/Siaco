# -*- coding: utf-8 -*-
"""
analizar_procesos_huila.py — SECOP II Procesos p6dx-8zbt
Cuenta procesos vigentes en Huila por sector.

Estrategia (luego de diagnóstico de campos):
  1. estado_del_procedimiento = 'Publicado'  (aceptando ofertas)
  2. fecha_de_publicacion_del >= '2025-01-01' (publicados en 2025-2026,
     es decir últimos ~18 meses — SECOP no actualiza el estado al cerrar,
     por lo que el filtro de fecha es la mejor proxy de "vigente")
"""
import unicodedata, requests, random
from datetime import date

BASE     = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
HOY      = date.today().isoformat()
DESDE    = "2025-01-01"
random.seed(42)

def norm(t):
    s = unicodedata.normalize("NFD", str(t or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper().strip()

# ─────────────────────────────────────────────────────────────────────────────
# DIAGNÓSTICO: ¿existe fecha_limite_recepcion_ofertas?
# ─────────────────────────────────────────────────────────────────────────────
print("═" * 62)
print("DIAGNÓSTICO — Campos de fecha en el dataset")
print("═" * 62)

# Buscar en 50 registros de Huila si existe el campo de cierre
r_diag = requests.get(BASE, params={
    "$where": "departamento_entidad = 'Huila' AND estado_del_procedimiento = 'Publicado'",
    "$limit": "50",
}, timeout=30)
diag_data = r_diag.json() if r_diag.status_code == 200 else []

CAMPOS_FECHA_CANDIDATOS = [
    "fecha_limite_recepcion_ofertas", "fecha_de_recepcion_de",
    "fecha_limite_de_recepcion", "fecha_apertura",
    "fecha_de_publicacion_del", "fecha_de_publicacion_fase_3",
]
print("\n  Campos de fecha disponibles en la muestra de 50 registros:")
for campo in CAMPOS_FECHA_CANDIDATOS:
    valores = [r.get(campo) for r in diag_data if campo in r and r.get(campo)]
    if valores:
        print(f"  ✓ {campo!r:42s}: ej. {str(valores[0])[:30]!r}")
    else:
        print(f"  ✗ {campo!r:42s}: NO presente")

campo_cierre = next(
    (c for c in ["fecha_limite_recepcion_ofertas", "fecha_de_recepcion_de"]
     if any(c in r for r in diag_data)), None
)
campo_publicacion = "fecha_de_publicacion_del"  # confirmado

print(f"\n  → Campo de CIERRE usable: {campo_cierre!r}")
print(f"  → Campo de PUBLICACIÓN:   {campo_publicacion!r}")

# ─────────────────────────────────────────────────────────────────────────────
# DECISIÓN DE FILTRO
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'═' * 62}")
print("DECISIÓN DE FILTRO")
print(f"{'═' * 62}")

if campo_cierre:
    WHERE = (
        f"departamento_entidad = 'Huila' "
        f"AND estado_del_procedimiento = 'Publicado' "
        f"AND {campo_cierre} >= '{HOY}T00:00:00.000'"
    )
    nota_filtro = f"estado='Publicado' + {campo_cierre} >= {HOY} (fecha de cierre futura)"
else:
    # SECOP no actualiza estados; proxy: publicados en 2025-hoy y aún 'Publicado'
    WHERE = (
        f"departamento_entidad = 'Huila' "
        f"AND estado_del_procedimiento = 'Publicado' "
        f"AND {campo_publicacion} >= '{DESDE}T00:00:00.000'"
    )
    nota_filtro = (
        f"estado='Publicado' + publicados desde {DESDE} "
        f"(proxy: campo de fecha cierre no disponible en API)"
    )

print(f"\n  WHERE: {WHERE}")
print(f"\n  Interpretación: {nota_filtro}")

# ─────────────────────────────────────────────────────────────────────────────
# CONTEO TOTAL
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'═' * 62}")
print("CONTEO TOTAL")
print(f"{'═' * 62}")

r_cnt = requests.get(BASE, params={
    "$where": WHERE, "$select": "count(*) as total"
}, timeout=30)
cnt = r_cnt.json()
total = int(cnt[0]["total"]) if isinstance(cnt, list) and cnt else -1
print(f"\n  Procesos vigentes en Huila: {total:,}")

print("  (Desglose histórico omitido para evitar timeout)")

# ─────────────────────────────────────────────────────────────────────────────
# DESCARGA (max 10k para análisis rápido)
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'═' * 62}")
print("DESCARGANDO MUESTRA PARA ANÁLISIS")
print(f"{'═' * 62}")

CAMPOS_SELECT = ",".join([
    "nombre_del_procedimiento",
    "descripci_n_del_procedimiento",
    "estado_del_procedimiento",
    "ciudad_entidad",
    "precio_base",
    "modalidad_de_contratacion",
    "entidad",
    campo_publicacion,
] + ([campo_cierre] if campo_cierre else []))

todos = []
offset = 0
MAX = 10000
while offset < MAX:
    params = {
        "$where":  WHERE,
        "$select": CAMPOS_SELECT,
        "$limit":  str(min(5000, MAX - offset)),
        "$offset": str(offset),
        "$order":  f"{campo_publicacion} DESC",
    }
    print(f"  → offset={offset}...", end=" ", flush=True)
    resp = requests.get(BASE, params=params, timeout=30)
    if resp.status_code != 200:
        print(f"\n  ✗ HTTP {resp.status_code}: {resp.text[:200]}")
        break
    lote = resp.json()
    if not isinstance(lote, list) or not lote: break
    todos.extend(lote)
    print(f"lote={len(lote)}  acum={len(todos)}")
    if len(lote) < 5000: break
    offset += 5000

print(f"\n  Descargados: {len(todos)} (de {total:,} totales)")

if not todos:
    print("  ✗ Sin datos para analizar")
    raise SystemExit(1)

# ─────────────────────────────────────────────────────────────────────────────
# CONTEO POR SECTOR
# ─────────────────────────────────────────────────────────────────────────────
SECTORES = {
    "Obras civiles / construcción": {
        "incl": [
            "CONSTRUC", "OBRA CIVIL", "OBRAS CIVILES", "PAVIMENT",
            "INFRAESTRUCTURA VIAL", "EDIFICACION", "URBANIZACION",
            "MEJORAMIENTO VIAL", "MANTENIMIENTO VIAL",
            "ACUEDUCTO", "ALCANTARILLADO", "REDES HIDRO",
            "PUENTE VEHICULAR", "PUENTE PEATONAL",
            "TALUD", "DRENAJE", "ALCANTARILLA",
        ],
        "excl": [],
    },
    "Climatización / HVAC / refrigeración": {
        "incl": [
            "CLIMATIZAC", "AIRE ACONDICIONADO", "AIRES ACONDICIONADOS",
            "HVAC", "REFRIGERAC", "CUARTO FRIO", "CUARTOS FRIOS",
            "SISTEMA DE FRIO", "VENTILACION MECANICA", "TERMOMECAN",
        ],
        "excl": [],
    },
    "Transporte de carga / logística": {
        "incl": [
            "TRANSPORTE DE CARGA", "TRANSPORTE CARGA",
            "LOGISTICA DE CARGA", "CARGA PESADA", "FLETES",
            "TRANSPORTE DE MATERIALES", "TRANSPORTE DE RESIDUOS",
            "SERVICIO DE TRANSPORTE DE",  # + contexto
        ],
        "excl": [
            "TRANSPORTE ESCOLAR", "TRANSPORTE DE ESTUDIANTES",
            "TRANSPORTE MEDICO", "TRANSPORTE DE PACIENTES",
            "TRANSPORTE DE PERSONAL", "TRANSPORTE AEREO",
        ],
    },
    "Ingeniería y consultoría técnica": {
        "incl": [
            "CONSULTORIA TECNICA", "CONSULTORIA DE INGENIERIA",
            "CONSULTORIA DE OBRA", "INTERVENTORIA DE OBRA",
            "SUPERVISION DE OBRA", "ESTUDIOS Y DISEÑOS",
            "DISEÑO VIAL", "DISEÑO ESTRUCTURAL",
            "ESTUDIOS HIDRAULICOS", "HIDROLOGICO",
            "TOPOGRAFIA", "GEOTECNIA", "INGENIERIA DE PROYECTO",
        ],
        "excl": [],
    },
    "Suministro materiales / ferretería": {
        "incl": [
            "MATERIALES DE CONSTRUC", "MATERIALES PARA CONSTRUC",
            "FERRETERIA", "INSUMOS DE CONSTRUC",
            "SUMINISTRO DE AGREGADO", "SUMINISTRO DE CONCRETO",
            "SUMINISTRO DE CEMENTO", "SUMINISTRO DE TUBERIA",
            "SUMINISTRO DE ACERO", "SUMINISTRO DE HIERRO",
        ],
        "excl": ["SUMINISTRO DE MEDICAMENTO", "SUMINISTRO DE ALIMENTO",
                 "SUMINISTRO MEDICO", "SUMINISTRO DE MATERIAL MEDICO"],
    },
    "Mantenimiento locativo / adecuaciones": {
        "incl": [
            "MANTENIMIENTO LOCATIVO", "ADECUACION DE INSTALACIONES",
            "ADECUACION LOCATIVA", "ADECUACION DE OFICINAS",
            "ADECUACION DE AULAS", "REMODELACION",
            "REPARACION LOCATIVA", "IMPERMEABILIZACION",
            "MANTENIMIENTO DE INSTALACIONES",
        ],
        "excl": [],
    },
}

def texto(p):
    n = norm(p.get("nombre_del_procedimiento", "") or "")
    d = norm(p.get("descripci_n_del_procedimiento", "") or "")
    return n + " | " + d

resultados = {}
for sector, cfg in SECTORES.items():
    matchs = [
        p for p in todos
        if (any(norm(kw) in texto(p) for kw in cfg["incl"]) and
            not any(norm(ex) in texto(p) for ex in cfg["excl"]))
    ]
    ejemplos = []
    entidades_vistas = set()
    for p in matchs:
        nom = str(p.get("nombre_del_procedimiento", "") or "").strip()[:90]
        ent = str(p.get("entidad", "") or "").strip()[:45]
        clave = ent[:20]
        if clave not in entidades_vistas and nom:
            entidades_vistas.add(clave)
            ejemplos.append((nom, ent))
        if len(ejemplos) >= 3:
            break
    resultados[sector] = {"n": len(matchs), "ejemplos": ejemplos}

# ─────────────────────────────────────────────────────────────────────────────
# TABLA FINAL
# ─────────────────────────────────────────────────────────────────────────────
muestra_n = len(todos)
factor    = total / muestra_n if muestra_n else 1

print(f"\n{'═' * 62}")
print(f"TABLA — Procesos vigentes en HUILA  [{HOY}]")
print(f"Filtro: {nota_filtro}")
print(f"Total en SECOP: {total:,}  |  Muestra analizada: {muestra_n:,}")
if muestra_n < total:
    print(f"(conteos de sector × factor {factor:.1f} = estimado para el total)")
print(f"{'═' * 62}\n")
print(f"  {'Sector':<42} {'En muestra':>10}  {'Estimado total':>14}")
print(f"  {'─'*42} {'─'*10}  {'─'*14}")

for sector, data in resultados.items():
    n     = data["n"]
    estim = round(n * factor)
    print(f"  {sector:<42} {n:>10,}  {estim:>14,}")

print(f"\n{'═' * 62}")
print("DETALLE Y EJEMPLOS")
print(f"{'═' * 62}")

for sector, data in resultados.items():
    n     = data["n"]
    estim = round(n * factor)
    print(f"\n  ── {sector} ──")
    print(f"     Muestra: {n:,}  |  Estimado total: {estim:,}")
    for nom, ent in data["ejemplos"]:
        print(f"     · {nom}")
        print(f"       ↳ {ent}")
    if not data["ejemplos"]:
        print("     (sin ejemplos en la muestra)")

print(f"\n{'═' * 62}")
print("ALERTAS")
print(f"{'═' * 62}")
alertas = False
for sector, data in resultados.items():
    n = data["n"]
    if n == 0:
        alertas = True
        print(f"\n  ⚠ CERO en muestra — '{sector}'")
        print(f"     SECOP usa vocabulario variable; no concluir que no existen.")
    elif factor > 1 and round(n * factor) > 1000:
        alertas = True
        pct = round(100 * n / muestra_n, 1)
        print(f"\n  ⚠ NÚMERO ALTO — '{sector}' ({round(n*factor):,} estimados = {pct}% del total)")
        print(f"     Revisa los 3 ejemplos arriba para confirmar que no hay falsos positivos.")

if not alertas:
    print("  Sin alertas.")

print(f"""
NOTA METODOLÓGICA:
  • "Publicado" en SECOP II = proceso en fase de Presentación de Oferta.
  • SECOP NO actualiza el estado al cerrar un proceso automáticamente —
    por eso se usa como proxy el filtro de publicación >= {DESDE}.
  • El campo fecha_limite_recepcion_ofertas {'NO está disponible' if not campo_cierre else 'SÍ está disponible'} en la API pública.
  • Los conteos de sector se hacen sobre {muestra_n:,} de {total:,} procesos;
    el "estimado total" asume distribución uniforme.
  • Para uso comercial: cruzar siempre con SECOP II directamente
    (community.secop.gov.co) antes de tomar decisiones.
""")
