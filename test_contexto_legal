# -*- coding: utf-8 -*-
"""
Script de prueba: verifica qué chunks recupera el RAG híbrido
(keywords + embeddings semánticos) para una consulta dada,
SIN llamar a la API de Anthropic.

La primera ejecución descargará el modelo de embeddings
(~80MB, all-MiniLM-L6-v2) y puede tardar un poco más.

Uso:
    py test_contexto_legal.py
"""

from analizador import obtener_contexto_legal, buscar_chunks_relevantes

# Modifica estos valores para probar distintas combinaciones
MODALIDAD = "infraestructura_obra_publica"
SECTOR = "educacion"
CONSULTA = "Contratación de obras de infraestructura para institución educativa, mantenimiento de aulas y baterías sanitarias"

print(f"Modalidad: {MODALIDAD}")
print(f"Sector:    {SECTOR}")
print(f"Consulta:  {CONSULTA}")
print("=" * 70)

print("\nBuscando chunks relevantes (puede tardar unos segundos la primera vez)...\n")
chunks = buscar_chunks_relevantes(MODALIDAD, SECTOR, CONSULTA, top_k=8)

print(f"Chunks recuperados: {len(chunks)}\n")
for i, c in enumerate(chunks, 1):
    print(f"--- Chunk {i} | score={c['score']:.3f} | {c['archivo']} (carpeta: {c['carpeta']}) ---")
    print(c["texto"][:300].replace("\n", " "))
    print()

print("=" * 70)
print("\nCONTEXTO FORMATEADO QUE RECIBIRÍA EL AGENTE LEGAL:\n")
contexto = obtener_contexto_legal(MODALIDAD, SECTOR, consulta=CONSULTA, top_k=8)
print(f"Longitud total: {len(contexto):,} caracteres\n")
print(contexto[:2000])
print("\n... (truncado)")