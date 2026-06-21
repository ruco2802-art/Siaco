import json
import os
import requests

# Mostrar perfiles de clientes
print("=== PERFILES DE CLIENTES ===")
for f in os.listdir("clientes"):
    if f.endswith(".json"):
        c = json.load(open(f"clientes/{f}", encoding="utf-8"))
        print(f"\n{c['nombre']}")
        print(f"  Min: COP {c['financiero']['presupuesto_minimo_contrato']:,}")
        print(f"  Max: COP {c['financiero']['presupuesto_maximo_contrato']:,}")
        print(f"  Sectores: {c['sectores_clave']}")
        print(f"  RUP: {c['rup']['tiene_rup']}")

# Mostrar licitaciones actuales
print("\n=== LICITACIONES ACTUALES ===")
url = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
params = {
    "$where": "fecha_de_publicacion > '2026-01-01T00:00:00' AND estado_del_procedimiento = 'Publicado'",
    "$limit": "20",
    "$order": "fecha_de_publicacion DESC"
}
licitaciones = requests.get(url, params=params, timeout=12).json()

keywords = ["hvac", "aire acondicionado", "climatizacion", "refrigeracion",
            "mantenimiento", "adecuacion", "obra civil", "transporte",
            "construccion", "remodelacion"]

for lic in licitaciones:
    nombre = lic.get("nombre_del_procedimiento", "")
    desc = lic.get("descripci_n_del_procedimiento", "")
    texto = (nombre + " " + desc).lower()
    if any(k in texto for k in keywords):
        valor = lic.get("precio_base", "0")
        depto = lic.get("departamento_entidad", "N/A")
        print(f"\nObjeto: {nombre[:80]}")
        print(f"  Valor: COP {valor}")
        print(f"  Depto: {depto}")