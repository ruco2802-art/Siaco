Crea el archivo CLAUDE.md en la raíz del proyecto con el siguiente contenido:

# SIACO — Guía para Claude Code

## Leer siempre antes de actuar
- Lee .claude/skills/ antes de escribir cualquier código
- Lee app.py, analizador.py y config.py para entender contexto actual

## Stack obligatorio
- Python 3.13, Streamlit 1.40.0 (NO actualizar)
- claude-sonnet-4-6, sentence-transformers all-MiniLM-L6-v2
- Sin bases de datos vectoriales externas
- SDK: anthropic>=1,<2 — el 1.x quitó `temperature`/`top_p`/`top_k` de las
  firmas de los métodos (no de la API). Las 14 llamadas que dependen del
  determinismo lo pasan como `extra_body={"temperature": 0.0}`.
  **Acople con la línea de modelo:** `extra_body={'temperature': 0.0}`
  funciona con la línea 4.6/4.5. Opus 4.7+ y Sonnet 5 rechazan valores
  no-default. Al migrar de modelo hay que quitarlo.

## Reglas críticas Streamlit
- st.form() en TODOS los widgets interactivos
- NUNCA st.rerun() ni st.spinner() dentro de loops Claude API
- Probar con: py -m streamlit run app.py después de cada módulo

## Arquitectura de carpetas
- /clientes/{id}/ → perfiles y documentos por cliente
- /biblioteca_normativa/ → RAG legal (NO modificar estructura)
- /reportes/ → PDFs generados
- /logs/ → logging automático

## Estilo de código
- Docstring en toda función nueva
- Manejo de excepciones en toda llamada API (timeout=30s, retry x2)
- Comentarios en español, nombres de variables/funciones en inglés
- Sin duplicar funciones existentes en analizador.py

## Diseño visual
- Tema dark: bg #0A0A0A, accent #C6F24E
- Fuentes: Inter + JetBrains Mono
- Si detectas mejoras de UX/UI que no rompen funcionalidad, impleméntalas

## Seguridad
- NUNCA hardcodear API keys
- Toda credencial via os.environ.get()
- .env y config.py en .gitignore

## Skills especializadas
- Consultar .claude/skills/skill_anti_rechazo.md antes
  de implementar cualquier lógica del generador de
  documentos de oferta (routers/generador_oferta.py)
  y del módulo de observaciones (routers/observaciones.py).
  Esta skill define la estructura, orden de foliación y
  constraints de calidad de todos los documentos generados.