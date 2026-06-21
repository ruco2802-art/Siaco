import requests
import json

url = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
params = {
    "departamento_entidad": "Huila",
    "$limit": 3,
    "$order": "fecha_de_publicacion DESC"
}

respuesta = requests.get(url, params=params, timeout=10)
licitaciones = respuesta.json()

print(f"Total encontradas: {len(licitaciones)}\n")
print("CAMPOS DISPONIBLES EN EL PRIMER REGISTRO:")
print(json.dumps(licitaciones[0], indent=2, ensure_ascii=False))