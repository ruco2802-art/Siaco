import json
import os
import requests
from analizador import cargar_clientes, evaluar_filtros_duros

clientes = cargar_clientes()
cliente_obras = [c for c in clientes if "civil" in c["sector"].lower() or "obra" in c["sector"].lower()][0]
print(f"Cliente de prueba: {cliente_obras['nombre']}")

contratos_prueba = [
    {
        "nombre_del_procedimiento": "CONSERVACION ADECUACION Y MANTENIMIENTO DE LOS ESCENARIOS DEPORTIVOS DEL MUNICIPIO",
        "descripci_n_del_procedimiento": "mantenimiento adecuacion obra civil",
        "precio_base": "319971806",
        "departamento_entidad": "Casanare",
        "fase": "Presentación de oferta"
    },
    {
        "nombre_del_procedimiento": "CONSTRUCCION DE ESTRUCTURAS DE MITIGACION",
        "descripci_n_del_procedimiento": "construccion obra civil estructuras",
        "precio_base": "400770809",
        "departamento_entidad": "Valle del Cauca",
        "fase": "Presentación de oferta"
    }
]

for contrato in contratos_prueba:
    print(f"\nContrato: {contrato['nombre_del_procedimiento'][:60]}")
    resultado = evaluar_filtros_duros(contrato, cliente_obras)
    print(f"Resultado: {resultado}")