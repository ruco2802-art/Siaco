import requests
import json

url = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
# Traemos el último registro absoluto publicado para garantizar datos frescos
params = {
    "$limit": "1",
    "$order": "fecha_de_publicacion DESC"
}

try:
    print("📡 Conectando con la API de SECOP II...")
    r = requests.get(url, params=params, timeout=15)
    
    if r.status_code == 200:
        data = r.json()
        if data:
            registro = data[0]
            print("\n🔍 ¡CONEXIÓN EXITOSA! CAMPOS DISPONIBLES EN TU API:\n")
            print("=" * 60)
            for key in sorted(registro.keys()):
                # Imprime la llave y una muestra de su contenido
                print(f"🔹 {key}: {str(registro[key])[:60]}")
            print("=" * 60)
        else:
            print("⚠️ La API respondió pero la lista está vacía.")
    else:
        print(f"❌ Error de conexión. Código de estado: {r.status_code}")

except Exception as e:
    print(f"❌ Ocurrió un error al conectar: {str(e)}")