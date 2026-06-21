from analizador import cargar_clientes, evaluar_filtros_duros

clientes = cargar_clientes()

contrato = {
    "nombre_del_procedimiento": "CONSERVACION ADECUACION Y MANTENIMIENTO DE LOS ESCENARIOS DEPORTIVOS",
    "descripci_n_del_procedimiento": "mantenimiento adecuacion obra civil escenarios",
    "precio_base": "319971806",
    "departamento_entidad": "Casanare",
    "fase": "Presentación de oferta"
}

print("Probando contrato:", contrato["nombre_del_procedimiento"][:60])
for cliente in clientes:
    resultado = evaluar_filtros_duros(contrato, cliente)
    print(f"\nCliente: {cliente['nombre']}")
    print(f"Resultado: {resultado}")
    from analizador import analizar_cliente_vs_licitacion

print("\n--- ANALISIS IA ---")
for cliente in clientes:
    resultado_filtro = evaluar_filtros_duros(contrato, cliente)
    if resultado_filtro["viable"]:
        print(f"\nAnalizando con Claude: {cliente['nombre']}")
        analisis = analizar_cliente_vs_licitacion(contrato, cliente)
        print(f"Resultado IA: {analisis}")