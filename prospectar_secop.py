# -*- coding: utf-8 -*-
"""
prospectar_secop.py — Prospección comercial SIACO
Consulta SECOP II Proveedores Registrados (dataset qmzu-gj57)
y genera prospectos_finales.csv filtrado por Huila + sector.

Schema real del dataset:
  nombre, nit, departamento, municipio, tipo_empresa,
  correo, telefono, sitio_web, fecha_creacion, espyme,
  esta_activa, descripcion_categoria_principal, ubicacion
"""
import csv
import time
import urllib.parse
import requests

BASE_URL = "https://www.datos.gov.co/resource/qmzu-gj57.json"

# Términos buscados en el NOMBRE de la empresa (upper LIKE en SoQL)
# Incluye variaciones sin tildes ya que SECOP es inconsistente
KW_NOMBRE = [
    # Obras / construcción
    "CONSTRUC", "CONTRATIST", "INGENIERIA", "INGENIEROS", "OBRAS CIVILES",
    "OBRA CIVIL", "PAVIMENT", "INFRAESTRUCTUR", "EDIFICACION", "ARQUITECT",
    "URBANIZACION", "URBANISMO", "REDES HIDROSANITARIAS", "VIAS Y",
    "ACUEDUCTO", "ALCANTARILLADO",
    # Mantenimiento locativo
    "MANTENIM", "REPARACION", "LOCATIVO", "ADECUACION", "REMODELACION",
    # HVAC / climatización / refrigeración
    "CLIMATIZAC", "REFRIGERAC", "AIRE ACONDICIONADO", "HVAC", "FRIGORI",
    "TERMOFRIG", "TERMOMECAN", "EQUIPO DE FRIO", "CUARTO FRIO",
    # Transporte de carga
    "TRANSPORT", "LOGISTICA", "CARGA PESADA", "FLETES", "CAMIONES",
    # Instalaciones eléctricas / hidráulicas
    "INSTALACION", "MONTAJE", "ELECTRIC", "HIDRAULIC", "SANITARI",
    # Suministros relacionados
    "SUMINISTRO", "FERRETERIA", "MATERIALES",
]

LIMITE_API    = 1000
TIMEOUT_WEB   = 5
MAX_FILAS_CSV = 30

# ── Helpers ────────────────────────────────────────────────────────────────────
def normalizar(texto: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", str(texto))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.upper().strip()


def construir_where_nombres(kws: list[str]) -> str:
    """Genera cláusula OR sobre upper(nombre) para cada keyword."""
    clauses = [f"upper(nombre) like upper('%{kw}%')" for kw in kws]
    return " OR ".join(clauses)


def fetch_huila_sector() -> list[dict]:
    """Descarga empresas de Huila con keywords en el nombre, paginando."""
    todos: list[dict] = []
    kw_where  = construir_where_nombres(KW_NOMBRE)
    base_where = (
        f"upper(departamento) = 'HUILA' "
        f"AND esta_activa = 'Si' "
        f"AND ({kw_where})"
    )

    offset = 0
    while True:
        params = {
            "$where":  base_where,
            "$limit":  str(LIMITE_API),
            "$offset": str(offset),
            "$order":  "fecha_creacion DESC",
        }
        url_debug = BASE_URL + "?" + urllib.parse.urlencode(params)
        print(f"  → offset={offset}  URL (primeros 160 chars): {url_debug[:160]}...")
        try:
            resp = requests.get(BASE_URL, params=params, timeout=30)
        except Exception as e:
            print(f"  ✗ Red: {e}")
            break
        if resp.status_code != 200:
            print(f"  ✗ HTTP {resp.status_code}: {resp.text[:300]}")
            break
        lote = resp.json()
        if not isinstance(lote, list):
            print(f"  ✗ Formato inesperado: {str(lote)[:200]}")
            break
        todos.extend(lote)
        print(f"    lote={len(lote)}  acumulado={len(todos)}")
        if len(lote) < LIMITE_API:
            break
        offset += LIMITE_API
    return todos


def fetch_count_total_huila() -> int:
    """Cuenta el total bruto de registros en Huila (sin filtro de sector)."""
    params = {
        "$where":  "upper(departamento) = 'HUILA'",
        "$select": "count(*) as total",
    }
    try:
        r = requests.get(BASE_URL, params=params, timeout=15)
        data = r.json()
        if isinstance(data, list) and data:
            return int(data[0].get("total", 0))
    except Exception:
        pass
    return -1


def verificar_sitio(url: str) -> str:
    if not url or normalizar(url) in ("NO PROVISTO", "N/A", ""):
        return "Sin sitio"
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "http://" + u
    try:
        r = requests.get(u, timeout=TIMEOUT_WEB, allow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        return "Sí" if r.status_code < 500 else "No"
    except Exception:
        return "No"


# ══════════════════════════════════════════════════════════════════════════════
print("\n══════════════════════════════════════════════")
print("SIACO — Prospección SECOP II Proveedores Huila")
print("══════════════════════════════════════════════\n")

# PASO 1: conteo total bruto
print("PASO 1 — Contando total de registros en Huila...")
total_brutos = fetch_count_total_huila()
print(f"  Registros totales en Huila (API): {total_brutos}")

# PASO 1b: Descarga con filtro sector
print("\nPASO 1b — Descargando empresas de Huila con keywords de sector...")
brutos_sector = fetch_huila_sector()
total_sector_bruto = len(brutos_sector)
print(f"\n  Descargados con filtro sector: {total_sector_bruto}")

# PASO 2: Verificar que TODOS sean de HUILA
print("\nPASO 2 — Verificando filtro de departamento...")
otros = [r for r in brutos_sector
         if normalizar(r.get("departamento", "")) != "HUILA"]
if otros:
    print(f"  ⚠ {len(otros)} registros con departamento != HUILA — aplicando filtro local")
    brutos_sector = [r for r in brutos_sector
                     if normalizar(r.get("departamento", "")) == "HUILA"]
    print(f"  Tras filtro local: {len(brutos_sector)}")
else:
    print(f"  ✓ Todos los {total_sector_bruto} registros son de HUILA")

total_huila_sector = len(brutos_sector)

# PASO 3: Ampliar si hay pocos
if total_huila_sector < 20:
    print(f"\nPASO 3 — Solo {total_huila_sector} empresas; descargando más sin filtro de sector...")
    params_all = {
        "$where":  "upper(departamento) = 'HUILA' AND esta_activa = 'Si'",
        "$limit":  "5000",
        "$order":  "fecha_creacion DESC",
    }
    resp_all = requests.get(BASE_URL, params=params_all, timeout=30)
    if resp_all.status_code == 200:
        brutos_sector = resp_all.json()
        total_huila_sector = len(brutos_sector)
        print(f"  Ampliado a {total_huila_sector} registros")
else:
    print(f"\nPASO 3 — {total_huila_sector} empresas con keywords — suficiente, no se amplía")

# PASO 4: Deduplicar + filtrar calidad
print("\nPASO 4 — Deduplicando y filtrando calidad...")
vistos_nit: set[str] = set()
candidatos: list[dict] = []

for r in brutos_sector:
    nit = str(r.get("nit", "") or "").strip()
    if not nit or nit.lower() in ("no provisto", ""):
        continue
    if nit in vistos_nit:
        continue
    vistos_nit.add(nit)

    correo = str(r.get("correo", "") or "").strip()
    if not correo or correo.lower() in ("no provisto", "n/a", ""):
        continue

    tipo = str(r.get("tipo_empresa", "") or "").upper()
    if "PERSONA NATURAL" in tipo:
        continue

    candidatos.append(r)

total_candidatos = len(candidatos)
print(f"  Tras dedup NIT + correo válido + sin personas naturales: {total_candidatos}")

# PASO 5: Verificar sitios web
print(f"\nPASO 5 — Verificando sitios web ({total_candidatos} empresas)...")
for i, r in enumerate(candidatos):
    sitio = str(r.get("sitio_web", "") or "").strip()
    r["sitio_activo"] = verificar_sitio(sitio)
    if (i + 1) % 10 == 0 or i == total_candidatos - 1:
        print(f"  {i + 1}/{total_candidatos} procesados...")
    time.sleep(0.1)

con_sitio_activo = sum(1 for r in candidatos if r["sitio_activo"] == "Sí")
print(f"  Sitios activos: {con_sitio_activo}")

# PASO 6: Ordenar
print("\nPASO 6 — Ordenando...")
ORDEN_SITIO = {"Sí": 0, "No": 1, "Sin sitio": 2}
candidatos.sort(key=lambda r: (
    ORDEN_SITIO.get(r.get("sitio_activo", "Sin sitio"), 2),
    "-" + str(r.get("fecha_creacion", "") or "")
))

# PASO 7: Exportar CSV
print(f"\nPASO 7 — Exportando CSV (máx {MAX_FILAS_CSV} filas)...")
COLUMNAS = [
    "nombre", "nit", "categoria", "municipio",
    "correo", "telefono", "sitio_web", "sitio_activo",
    "tipo_empresa", "es_pyme",
]

def fila(r):
    return {
        "nombre":      r.get("nombre", ""),
        "nit":         r.get("nit", ""),
        "categoria":   r.get("descripcion_categoria_principal", ""),
        "municipio":   r.get("municipio", ""),
        "correo":      r.get("correo", ""),
        "telefono":    r.get("telefono", ""),
        "sitio_web":   r.get("sitio_web", ""),
        "sitio_activo":r.get("sitio_activo", "Sin sitio"),
        "tipo_empresa":r.get("tipo_empresa", ""),
        "es_pyme":     r.get("espyme", ""),
    }

filas_csv = candidatos[:MAX_FILAS_CSV]
with open("prospectos_finales.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=COLUMNAS)
    w.writeheader()
    for r in filas_csv:
        w.writerow(fila(r))

print(f"  ✓ prospectos_finales.csv  ({len(filas_csv)} filas)")

# PASO 8: Resumen
print("\n══════════════════════════════════════════════")
print("RESUMEN FINAL")
print("══════════════════════════════════════════════")
print(f"  Registros brutos en HUILA (API)          : {total_brutos}")
print(f"  Con keywords de sector (HUILA activas)   : {total_huila_sector}")
print(f"  Tras dedup + correo válido + empresas    : {total_candidatos}")
print(f"  Con sitio web activo                     : {con_sitio_activo}")
print(f"  Exportados al CSV                        : {len(filas_csv)}")
print("══════════════════════════════════════════════\n")

print("Top del CSV:")
print(f"{'Nombre':<45} {'Municipio':<15} {'Sitio':<8} {'Correo'}")
print("-" * 100)
for r in filas_csv[:15]:
    print(f"{str(r.get('nombre',''))[:44]:<45} "
          f"{str(r.get('municipio',''))[:14]:<15} "
          f"{r.get('sitio_activo',''):<8} "
          f"{str(r.get('correo',''))[:40]}")
