# ESTADO DEL PIPELINE — 2026-08-18

Documento de referencia para retomar trabajo entre sesiones.
Actualizar en cada bloque significativo de trabajo.

---

## Entorno y arranque — INTÉRPRETE EXPLÍCITO

El arranque se ha roto tres veces por ambigüedad de entorno. Hay **tres**
intérpretes en la máquina y sólo uno sirve para la app:

| intérprete | ruta | fastapi | sirve para |
|---|---|---|---|
| `py` (por defecto) | `.venv_parsers\Scripts\python.exe` | **no** | nada de la app |
| `py -3.14` | `C:\Python314\python.exe` | **no** | nada |
| **`py -3.13`** | `%LOCALAPPDATA%\Programs\Python\Python313\python.exe` | **0.138.0** | **todo** |

`py` a secas resuelve a `.venv_parsers`, que tiene `anthropic 1.4.0`,
`pydantic` y los parsers, pero **no** `fastapi` ni `uvicorn`. Python 3.13
tiene el conjunto completo —fastapi, uvicorn, anthropic, fpdf2, pymupdf,
pdfplumber, marker-pdf, torch, sentence-transformers, pytest— así que **no
hace falta instalar nada ni crear un venv nuevo**.

**Arranque de la app (el único comando correcto):**

```
py -3.13 -m uvicorn main:app --port 8000 --reload
```

**Tests:**

```
py -3.13 -m pytest pipeline/tests/ -q
```

Advertencia sobre el SDK: `.venv_parsers` tiene `anthropic 1.4.0` y 3.13
tiene `0.121.0`. Ambos aceptan `extra_body={"temperature": 0.0}`, así que las
14 llamadas deterministas funcionan en los dos. **Lo que se ejecuta en
producción es 3.13**; si se migra de modelo, la deuda D1 se evalúa contra esa
versión. Correr los tests en un intérprete y la app en otro es cómo se
detectó tarde la rotura del SDK (B14).

---

## Módulos — estado de conexión al flujo

Leyenda: `[C]` = conectado al flujo de producción · `[EXT]` = punto de extensión sin llamador · `[TODO]` = diseñado, sin implementar

```
pipeline/main.py
  parsear_pdf()               [C]  ← parser.py, llamado desde main.py PASO 1
  chunkear()                  [C]  ← chunker.py, llamado desde main.py PASO 2
  extraer()                   [C]  ← extractor.py, llamado desde main.py PASO 3
  verificar_citas()           [C]  ← verifier.py, llamado desde main.py PASO 4
  marcar_indices()            [C]  ← verifier.py, llamado desde main.py PASO 4
  tasa_verificacion()         [C]  ← verifier.py, llamado desde main.py PASO 4
  generar_aviso_verificacion()[C]  ← verifier.py, llamado desde main.py PASO 4 (FASE D)
  estado_global()             [C]  ← verifier.py, llamado desde main.py PASO 4
  cargar_perfil()             [C]  ← evaluator.py, llamado desde main.py PASO 5
  evaluar_empresa()           [C]  ← evaluator.py, llamado desde main.py PASO 5
  seleccionar_rango_umbrales()[C]  ← evaluator.py, llamado DENTRO de evaluar_empresa()

  reparar_markdown()          [C]  ← tablas.py, llamado desde parser.py
                                     NOTA: efecto nulo en TIPO C (0 reparaciones,
                                     localizar_pagina() devuelve 0 chars en escaneados)
  reparar_con_modelo()       [EXT] ← tablas.py, inalcanzable en TIPO C (pagina_no_localizada)
  _matrix_ratio_entero()     [EXT] ← tablas.py, API Anthropic normaliza internamente

pipeline/src/criterios.py     [C]  ← UmbralSimple, Formula, TablaTramos, Booleano + evaluador AST
pipeline/src/perfil.py        [C]  ← PerfilEmpresa + cargar_perfil()
  cargar_perfil_por_cid()     [C]  ← evaluator.py, llamado desde routers/auditoria.py

pipeline/src/clasificador.py
  clasificar_requisito()      [C]  ← llamado DENTRO de consolidar()
  consolidar()                [C]  ← artefactos.py::_consolidar_requisitos() (2026-09-07)
                                     Antes [EXT]: construido, testeado y SIN llamador.
                                     Test de conexión: test_flujo_consolidacion.py

pipeline/src/observaciones_filtro.py
  ObservacionCandidato        [EXT] ← modelo + triple filtro; no importado en producción
  aplicar_filtro_1()          [EXT] ← F1 aritmético; punto de extensión para routers/
  aplicar_filtro_2()          [EXT] ← F2 verificación de citas
  ejecutar_filtros()          [EXT] ← pipeline F1+F2
  confirmar() / descartar()   [EXT] ← F3, transición de estado para la UI

pipeline/src/fallo_log.py
  mensaje_usuario()           [EXT] ← B1 para el abogado; pendiente conectar al extractor
  registrar_fallo()           [EXT] ← B2 JSONL; pendiente conectar al extractor
  reporte_agregado()          [EXT] ← B2 lectura y agregación; no llamado aún
  imprimir_reporte()          [EXT] ← CLI helper

Generador de criterios        [TODO] ← diseñado (ver sección camino crítico), NO implementado
                                        hoy criterio=None en TODOS los requisitos extraídos
```

---

## Métricas medidas (corridas con costo real, no estimadas)

| Pliego | Tipo | Chunks | Requisitos | Citas verif. | Ground truth | Costo |
|---|---|---|---|---|---|---|
| 29. PLIEGO DE CONDICIONES (Paicol) | A (nativo) | 85 | 215 deduplicados | 89,0% | 14/14 | $1,05 |
| 16. PLIEGO DEFINITIVO (Cravo Norte) | C (escaneado) | 254 | 363 | 91,7% | — | ~$1,89 OCR incl. |

**Cobertura de chunking (5 pliegos en caché, medido 2026-08-18):**

| Archivo | Cobertura | Chunks | % con numeral |
|---|---|---|---|
| ICBF-SAMC-001-2026-CAQU.pdf | 100,1% | 96 | 85% |
| TRANSPORTE AMBIENTAL ok.pdf | 100,3% | 84 | 42% |
| 29. PLIEGO DE CONDICIONES.pdf | 100,2% | 85 | 85% |
| SAMC-IET-001-2026.pdf | 100,2% | 104 | 89% |
| 16. PLIEGO DEFINITIVO (Cravo Norte) | 100,2% | 254 | 52% |

Todos ≥ 99%. Sin alertas.

**OCR Resoluciones CCE (2026-08-18, $0,149 real):**
- Res-539 (14 págs), Res-540 (12 págs), Res-541 (11 págs)
- 0 tablas extraídas — correcto: son texto jurídico narrativo puro
- Los umbrales financieros están en Matrices, no en resoluciones

---

## Invariantes I1–I9 — cobertura de tests

| Invariante | Descripción | Test integración | Test unitario | Riesgo |
|---|---|---|---|---|
| I1 | Ningún chunk ni markdown se trunca | TestSubchunkIntegracion | TestSubchunkingParte | Bajo |
| I2 | stop_reason=max_tokens → truncado, sin JSONDecodeError | TestI2StopReasonMaxTokens | — | **Solo integración** |
| I4 | estado_global() siempre derivado, nunca asignado | TestI4EstadoGlobal | — | **Solo integración** |
| I5 | fuente_numeral del chunk tiene precedencia sobre el modelo | TestAlias, TestNormalizacion | — | **Solo integración** |
| I6 | Evaluación numérica en Python puro, nunca en el LLM | — | TestSeguridadEvaluador, TestExpresionesReales | **SOLO UNITARIO** ⚠️ |
| I7/I8 | verificar_citas() busca en markdown completo, no ventana | TestI7I8VerificarCitas | — | **Solo integración** |
| I9 | Corridas con costo persisten resultado ANTES de retornar | TestMainPersistencia (E2E) | TestPersistenciaI9 | Bajo |
| I9b | Aborta ANTES de gastar si ruta no escribible | TestMainValidacionEscritura | — | **Solo integración** |
| 2.3 | marcar_indices() conectado al flujo | TestMainMarcarIndicesConectado | TestMarcarIndices | Bajo |
| FASE D | generar_aviso_verificacion() se muestra | TestMainAvisoVerificacion | — | **Solo integración** |

⚠️ **I6 solo tiene test unitario** — el invariante más crítico (no usar eval()) no tiene test de integración que verifique que la ruta de producción no llama al modelo para aritmética. Este es el tipo de gap que dejó pasar bugs tres veces.

**Suite completa: 112/112 pasando (2026-08-18)**

---

## Camino crítico para un score funcional

En orden estricto de dependencia:

1. **Generador de criterios desde el pliego** ← diseñado, NO implementado.
   Es el eslabón que falta: hoy `criterio=None` en todos los requisitos extraídos.
   El diseño está en la sesión anterior:
   - Fase 1: clasificación (UmbralSimple/Formula/TablaTramos/Booleano)
   - Fase 2: extracción estructurada (structured outputs viables vía `anyOf`)
   - Fase 3: resolución de variables (diccionario de sinónimos: AC→activo_corriente, etc.)
   - Provenance: `fuente_umbral` + `valor_ref_cce` + `diff_vs_cce`
   - Sin criterio → requisito no se pierde; queda con `criterio=None` + cita literal

2. **Campos [TODO-FORM] en el formulario web** — faltan en el frontend:
   - Financiero: `ebitda`, `rentabilidad_patrimonio`, `rentabilidad_activo`,
     `renta_operacional`, `patrimonio_neto`
   - Experiencia: `valor_acumulado`, `valor_individual_max`, `contratos_acreditados`,
     `antiguedad_meses`
   - Jurídico: 10 campos booleanos individuales (parafiscales, inhabilidades, etc.)
   - Técnico: completo (`personal_disponible`, `equipos`, `certificaciones`)

3. **Ejecutar scripts/migrar_perfiles.py** — unifica los 3 esquemas de perfil
   incompatibles: `PerfilBody` (API), `clientes/XXX.json` (antiguo),
   `PerfilEmpresa` (pipeline)

4. **Conectar fallo_log.py al extractor** — `registrar_fallo()` debe llamarse
   desde `extractor.py` cuando `criterio=None`; `mensaje_usuario()` debe llegar
   al reporte. Hoy los fallos son invisibles.

5. **Score de competitividad desde pesos del Capítulo IV** — los requisitos
   habilitantes ya se evalúan (cumple/no cumple); falta ponderar los criterios
   de selección (puntaje) del Capítulo IV para calcular un score comparativo.

6. **Catálogo de tiempos de gestión** — nunca construido. Necesario para
   estimar viabilidad temporal de un proceso: tiempo de respuesta CCE,
   plazos publicación, ventana de observaciones.

7. **Prueba A/B structured outputs vs método actual** — 20-30 requisitos
   reales de Paicol y Cravo Norte; medir % criterios bien tipados,
   % variables correctamente mapeadas, % requisitos que quedan sin criterio.
   Structured outputs: viable (anyOf + $defs soportados), no adoptado todavía.

---

## Bugs abiertos

| ID | Descripción | Impacto | Estado |
|---|---|---|---|
| B1 | OCR no instrumentado: `_ocr_con_claude()` no reporta tokens ni costo | No se puede auditar gasto real del OCR del flujo principal (extractor) | Abierto |
| B2 | `pagina_origen` aproximado en TIPO C | Aviso muestra página inicio del chunk, no de la cita exacta | Parcialmente resuelto (estimación por `---`) |
| B3 | Separador `---` del OCR puede coincidir con `---` de Markdown | En secciones con `---` como regla horizontal, el conteo de páginas se desvía | Abierto |
| B4 | `reparar_markdown()` corre en TIPO C sin efecto ni aviso en stdout | Tiempo perdido (~mínimo) | Documentado en docstring |
| B5 | `clientes/` estaba trackeado en git | Datos de empresa en repo público | **CORREGIDO 2026-08-18** (git rm --cached) |
| B6 | `criticidad` tenía default `"habilitante"` en `extractor.py` | Un pliego sin clasificar producía 218 habilitantes falsos y score inflado en silencio | **CORREGIDO 2026-09-07** (default → `"indeterminado"`) |
| B7 | `consolidar()` sin llamador en producción | Auditoría y chat veían 218 fragmentos en vez de 61 consolidados | **CORREGIDO 2026-09-07** (conectado en `artefactos.py`) |
| B8 | `fusionar_fragmentos()` descarta `valor_umbral`/`operador` de miembros no-primarios | 35 de 42 umbrales numéricos de Paicol se perdían al consolidar | **CORREGIDO 2026-09-07** — `_propagar_campos_evaluables()` recoge umbral/criterio/página de cualquier miembro; conflictos van a `umbrales_alternativos` + `conflicto_umbral`. Paicol: 42 → 32 valores conservados (antes 7); 1 solo valor desaparece (50.0, descartado por regla `_descartar`) |
| B9 | `_CLAVE_FUSION` agrupa por prefijo de numeral y barre requisitos distintos al mismo grupo | En Paicol: `experiencia_rup` fusionaba 21 requisitos bajo el nombre "Exclusión de tipos de obras no válidas"; `persona_juridica_docs` fusionaba 16 documentos societarios bajo "Acto de creación de entidad estatal", que el evaluador marcaba `no_aplica` descartando 15 exigencias reales para una PYME privada | **MITIGADO 2026-09-07** — regla de seguridad `grupo_es_coherente()`: un grupo de ≥5 fragmentos sin objeto común no se fusiona. Nombre del grupo derivado del objeto, no del literal más largo. Paicol: 61 → 99 requisitos, 28 → 60 habilitantes; umbrales evaluables 11 → 24. **Causa raíz sigue abierta** (ver B10) |
| B10 | Bolsas temáticas que la regla de objeto común no atrapa | Un grupo cuyos miembros comparten una palabra genérica del dominio sobrevive aunque hable de cosas distintas | **MITIGADO 2026-09-07** — `_STEMS_GENERICOS`: los encabezados de capítulo del CCE (capacidad, experiencia, requisito, documento, acreditación, verificación, proponente, contrato, oferta, condiciones, general, presentación, información, criterio) no cuentan como objeto común. Disolvió `experiencia_relacion_presupuesto` (7). Paicol: 99 → 105 requisitos, 60 → 66 habilitantes, umbrales evaluables 24 → 28, `revisar_manual` 1 → 0 |
| B11 | `crp_calculo` sobrevive por un término específico pero transversal | 13 fragmentos unidos por "residual" (7 de 13, no genérico): mezcla capacidad residual con CO ingresos operacionales, tarjeta profesional, índice de liquidez CF y estados financieros. La regla de términos genéricos no aplica porque "residual" SÍ nombra un objeto real — sólo que el grupo contiene además otros cuatro | **ABIERTO** — requiere el catálogo de objetos del dominio (diseño en la sección de camino crítico). Es la única bolsa conocida que queda en Paicol |
| D1 | **DEUDA TÉCNICA — `extra_body={"temperature": 0.0}` acopla el código a la línea de modelo 4.6/4.5** | 14 llamadas pasan el determinismo por `extra_body` porque el SDK 1.x quitó `temperature` de las firmas pero la API lo sigue honrando en Sonnet 4.6. **Condición de disparo: cuando se cambie de modelo.** Opus 4.7+ devuelve 400 ante cualquier petición que lleve un parámetro de muestreo (incluido el valor por defecto); Sonnet 5 rechaza valores no-default. Al migrar hay que quitar los 14 `extra_body` y decidir si el determinismo se sustituye por otra vía. Documentado en `CLAUDE.md` (stack) y en `_MODEL` de `extractor.py` | **ABIERTA — revisar al migrar de modelo** |
| B15 | `pipeline/main.py` no cargaba credenciales | Único entrypoint del repo sin `load_dotenv`: dependía del env ambiente. Con un `ANTHROPIC_API_KEY` obsoleto en el shell (placeholder de 23 chars) daba 401 en cada chunk, sin explicar por qué. Convenciones del repo: los scripts CLI usan `override=True` (el `.env` gana sobre un shell viejo), la app de producción `override=False` (las env vars de Railway ganan) | **CORREGIDO 2026-09-09** — `load_dotenv(..., override=True)`, convención de script CLI |
| D6 | **DEUDA — el aspecto `acreditacion` es demasiado ancho** | `(EXPERIENCIA_CONTRATOS, acreditacion, 3)` agrupa 8 miembros que son tres cosas distintas: **medio de prueba** (RUP, certificación de subcontrato, facturación entre particulares), **emisor válido** (prohibición de auto certificaciones, de certificaciones de interventor) y **contenido mínimo** (información requerida por contrato). Partición propuesta: `medio_prueba` / `emisor` / `contenido`. **No produce afirmación falsa hoy**: ningún miembro aporta umbral, así que el veredicto "aporta la experiencia documentada" es correcto para los 8 | **ABIERTA — disparo: si algún miembro del grupo llega a traer umbral, o si el mismo patrón aparece en otro pliego** |
| D7 | **DEUDA — falta el eje `sujeto` (líder / integrante) en el catálogo** | `(EXPERIENCIA_CONTRATOS, porcentaje, 3)` fusiona "integrante principal mínimo 50%" con "demás integrantes mínimo 5%": mismo objeto, misma unidad, pero **dos umbrales para dos sujetos distintos**. Es el único grupo donde `magnitudes_incompatibles()` dispara. Comportamiento actual seguro: `conflicto_umbral` → `revisar_manual`, se reporta en vez de resolverse a ciegas. Un tercer eje por un caso único en un solo pliego sería generalización prematura | **ABIERTA — disparo: si el eje sujeto aparece en un segundo pliego, evaluar añadirlo** |
| D8 | **MEJORA FUTURA — resolver variantes de umbral con el perfil** | 4 de los 5 `conflicto_umbral` de Paicol son variantes reales del pliego, no bolsas: 6 vs 7 contratos según mipyme/mipyme+mujer; 75/120/150 SMMLV según nº de contratos acreditados. Hoy van a `revisar_manual`. **El evaluador ya conoce el perfil** y podría resolverlas: si el cliente es Mipyme aplica el umbral de 6; si acredita 3 contratos aplica los 120 SMMLV. Los datos ya están disponibles — es lo que haría el sistema útil en vez de devolver "revisar" | **ABIERTA — no implementar antes de conectar lo existente** |
| D4 | **PENDIENTE — las Matriz 2 no están en el repo** | `estructura_normativa.json` se construyó leyendo los `.docx` de Matriz 2 (mínima, menor cuantía, licitación), pero los archivos nunca se guardaron en `biblioteca_normativa/`. Sólo están las 15 Matriz 1 (Experiencia). El contenido esencial —nombres oficiales de indicadores y umbrales— ya está en el JSON, así que no bloquea, pero la fuente primaria no es verificable desde el repo | **ABIERTO** |
| D5 | **PENDIENTE — `Resolucion-539-de-2025.md` está vacío (23 bytes)** | El OCR de las resoluciones CCE produjo un markdown sin contenido útil. El `.pdf` y el `_tablas.json` sí existen. Detectado al buscar nombres canónicos de indicadores para el catálogo de objetos | **ABIERTO** |
| D3 | **PENDIENTE — placeholder de `ANTHROPIC_API_KEY` en el shell del desarrollador** | El shell exporta un valor de 23 chars (`sk-ant-...`) que no es una clave válida y que **oculta** la real del `.env` en cualquier proceso que use `override=False` o no cargue dotenv. `pipeline/main.py` ya está cubierto por B15, pero conviene quitarlo del perfil del shell para que no reaparezca en otro entrypoint | **ABIERTO — acción del operador** |
| D2 | **PENDIENTE — el entorno se desvió del manifiesto sin aviso** | `requirements.txt` pinneaba `anthropic==0.99.0` mientras el venv tenía 1.4.0 instalado; nada lo detectó y el resultado fue que ninguna función de IA operaba. Igual con `langchain-text-splitters` y `pdfplumber`, que el código importa y el manifiesto no listaba. Vale un chequeo que compare lo instalado contra `requirements.txt` y falle si difieren en versión mayor (ejecutable en el arranque o como test de la suite) | **ABIERTO** |
| B14 | **`anthropic` 1.4.0 rompe TODAS las llamadas a Claude del repo** | El SDK se actualizó a 1.x el 2026-09-06 (major version que elimina parámetros deprecados). `Messages.create()` ya no acepta `temperature`, que se usa en **19 llamadas de 15 archivos**: `extractor.py`, `parser.py`, `tablas.py`, `generador_criterios.py`, `routers/auditoria.py`, `routers/observaciones.py`, `routers/busqueda.py`, `analizador.py` (×4), `app.py` (×2), `competidor.py` (×2), `agente_secop.py`, `evaluar_t12.py`, `escrapeador_pliegos.py`. Falla con `TypeError` en el wrapper del SDK, antes de enviar la petición — no se gasta API, pero **ninguna función de IA opera**. `analizador_pipeline.py` es el único módulo no afectado (no usa `temperature`) | **ABIERTO** — decisión pendiente: quitar `temperature` en los 19 sitios (cambia el determinismo de extracción y evaluación, hoy en 0.0) o fijar `anthropic<1.0` en `requirements.txt` |
| B13 | `parser.py` usa `_CACHE_DIR = Path(".pipeline_cache")` — ruta **relativa** al directorio de trabajo | La caché de parseo sólo se encuentra si el proceso corre desde la raíz del repo. Desde `pipeline/` (o desde cualquier otro cwd) la caché falla en silencio y el parser exige `marker-pdf`, que no está instalado ni en `.venv_parsers` ni en Railway. Afecta al flujo de auditoría: si el proceso de FastAPI no arranca con cwd en la raíz, todo PDF ya cacheado se re-parsea o falla | **ABIERTO** — usar ruta absoluta derivada de `__file__`, como hace `artefactos.py` |
| B12 | Nombres absorbidos al fusionar desaparecían del informe | `fusionar_causales_rechazo()` absorbía "inhabilidades" en "Capacidad jurídica" sin dejar rastro buscable: un operador que no encuentra el término asume que no se revisó y lo verifica a mano. En Paicol son 5 casos (2 de inhabilidades, 3 de RUP) | **CORREGIDO 2026-09-07** — campo `nombres_absorbidos: list[str]` en `Requisito`, poblado tanto en la fusión de causales como en la de fragmentos (16 requisitos lo llevan en Paicol) |
| N5 | **Verificación literal aprobaba texto corrupto** | La comparación normalizada prueba que el fragmento existe en el archivo, no que el archivo sea legible: un `.md` con la codificación de fuente rota coincide consigo mismo, así que `"XQD¿GXFLDRXQSDWULPRQLR"` habría pasado como cita verbatim en un informe firmado ante una entidad | **CORREGIDO 2026-09-16** — `palabras_ilegibles()` en `bibliotecario.py` [N5], dos señales calibradas con 0 falsos positivos sobre las normas sanas: 5+ letras sin vocal, y racha de 5+ consonantes. Siglas en mayúscula de ≤6 chars exentas (SMMLV, SMLMV, DGCPTN, DGPPN, NSPSC). `proporcion_ilegible()` mide el documento; `verificar_cita()` rechaza el fragmento |
| N6 | **Texto derogado citable como si estuviera vigente** | Distinto de N5 y más sutil: el texto derogado del `.md` es legible y literal, así que el verificador lo aprueba sin objeción. El art. 5 de la Ley 1150 conservaba la redacción anterior del parágrafo 1° («hasta la adjudicación»), sustituida por la Ley 1882 de 2018 («hasta el término de traslado del informe de evaluación»). Un informe podía citar verbatim una regla que ya no rige | **CORREGIDO 2026-09-16** — los 8 bloques `Texto inicial…` de `Ley_1150_de_2007.md` llevan `> [DEROGADO] ` en cada línea, así que un fragmento limpio ya no coincide. El `.md` pasó de 89.273 a 91.977 chars y los offsets se re-indexaron en la misma operación: 32 artículos, rangos contiguos, cada uno empieza en su encabezado. Tests de regresión sobre los offsets y sobre ambos fragmentos |
| N7 | **El motivo de la abstención no se evaluaba** | `clasificar_caso()` aceptaba cualquier `motivo` en una abstención correcta, así que E18 —que mide si el agente distingue «esto no es una afirmación jurídica» de «no encontré la norma»— no evaluaba nada | **CORREGIDO 2026-09-16** — clase propia `acierto_motivo_incorrecto`: no suma en `tasa_acierto` y no invalida la corrida, pero separa un fallo de BÚSQUEDA de uno de CLASIFICACIÓN. El skill ya definía los tres motivos, así que la exigencia era coherente con lo que se le pide |
| N8 | **"Aprobada" sólo medía que no mintiera** | La condición de aprobación era `cero fallos críticos`. Un agente que se abstiene siempre no inventa ninguna norma, así que aprobaba — y en el ground truth vigente saca 33,3% sin leer una sola norma | **CORREGIDO 2026-09-16** — dos barreras obligatorias: **INTEGRIDAD** (cero fallos críticos) y **UTILIDAD** (tasa ≥ suelo + 20 puntos). `suelo_abstencion()` y `techo_indice()` se calculan sobre el ground truth vigente con la misma `clasificar_caso()`, no son constantes. Veredicto propio para el caso intermedio: *"no miente pero no sirve"* |
| D13 | **El mínimo útil quedaba por debajo del techo de índice** | Con E03 en `sin_respaldo`, abstenerse correctamente en los 10 casos daba 55,6% sin leer una norma, y eso pasaba la barrera de utilidad (53,3%) | **RESUELTO 2026-09-16 sin tocar el umbral** — al corregir `skill_financiera_SAFE_L` y pasar E03 a `respaldada`, quedan 9 abstenciones: el techo de índice baja a 50,0% y el mínimo útil (53,3%) lo supera. La barrera ya excluye la consulta de índice por sí sola |
| D9 | **PENDIENTE — re-extraer la Ley 1474 de 2011 de otra fuente** | Codificación de fuente rota en el PDF de minsalud: 94 de 136 artículos ilegibles (69%); el detector [N5] mide 0,195 sobre el documento. Bajada a `citable:false` el 2026-09-16. Vale re-extraerla: su **art. 88** modificó el numeral 2 del art. 5 de la Ley 1150, y su **art. 91** es el que `skill_financiera_SAFE_L` cita (mal) para el tope de anticipo | **ABIERTO** |
| D10 | **PENDIENTE — re-extraer la Ley 2022 de 2020** | OCR defectuoso pese a tener capa de texto: el art. 1 quedó truncado a 88 chars sin el articulado que modifica, y el art. 2 trae basura (`publjcé.~dón`, `GREGaRIO ELJACH`). El detector [N5] no la marca porque su ruido conserva vocales — se detectó leyendo el texto. Bajada a `citable:false` el 2026-09-16. Es la norma de **obligatoriedad de documentos tipo**: sin ella el caso E04 de la evaluación no tiene respaldo posible | **ABIERTO** |
| D11 | **PENDIENTE — basura de OCR localizada en la Resolución 336 de 2021** | Dos zonas corruptas al pie (sellos escaneados). Proporción 0,0022: corrupción **localizada, no sistémica**, así que la norma sigue citable y [N5] impide citar esas zonas concretas. No requiere acción salvo que crezca | **ABIERTO — sin impacto hoy** |
| D12 | **Tres citas erróneas en el marco normativo de los agentes** | (a) anticipo 50% atribuido a Ley 1474/2011 art. 91, que regula la fiducia de manejo, no el tope; (b) plazo de subsanación de "3 días hábiles según Decreto 1082", inexistente en los 1.048 artículos; (c) "10 días hábiles" de observaciones sin distinguir modalidad | **CORREGIDO 2026-09-16** — en `prompts.py` (L33, L77, L83-84, L87-88) y en `skill_financiera_SAFE_L.md`, `skill_licitaciones_estrategia.md`, `skill_juridica_licitaciones.md.md`. Anticipo → **Ley 80/1993 art. 40, parágrafo**; subsanación → **sin número de días**, límite hasta el traslado del informe de evaluación (Ley 1150/2007 art. 5 par. 1 mod. Ley 1882/2018 art. 5); observaciones → **Decreto 1082/2015 art. 2.2.1.1.2.1.4**, 10 días en licitación y 5 en selección abreviada y concurso de méritos, sobre el PROYECTO de pliego |
| D14 | **El marco normativo de `prompts.py` no estaba verificado — 16 citas no resistían** | Las citas que alimentan a los agentes financiero y jurídico **no viven en las skills `.md` sino en los fallbacks embebidos de `prompts.py`**. 4 artículos no existían, 5 apuntaban a un artículo que existe pero regula otra cosa, 7 citaban normas ausentes de la biblioteca | **CORREGIDO 2026-09-16** — 19 sustituciones en `prompts.py` más las skills. Regla aplicada: ninguna cita se sustituye por otra no verificada contra la biblioteca; lo que no se pudo verificar se marcó, no se reemplazó por memoria |
| N9 | **Sólo se auditaba una de las dos fuentes normativas** | La primera auditoría de skills devolvió casi nada porque `prompts.py` no estaba en la lista. Los 4 artículos inventados llevaban meses en producción | **CORREGIDO 2026-09-16** — `pipeline/src/auditor_citas.py` recorre las 6 fuentes y comprueba, por cada cita: (a) la norma está en el índice como citable, (b) el artículo existe. `test_auditor_citas.py` lo fija en la suite, con dos pruebas de saboteo. **No puede comprobar que el artículo DIGA lo correcto** —eso exige lectura— pero atrapa las dos primeras categorías de forma permanente |
| D15 | **El índice elegía la ocurrencia equivocada de un artículo repetido** | `Ley_1882_de_2018.md` tiene dos encabezados `ARTÍCULO 4°`: el real (adiciona el parágrafo 7 al art. 2 de la Ley 1150 — documentos tipo) y el art. 4 de la **Ley 1228 de 2008 transcrito dentro del art. 17**. La regla «conservar la ocurrencia con más texto» elegía el segundo | **CORREGIDO 2026-09-16** — `pipeline/src/indexador.py` con tres reglas en orden: **[X1]** un encabezado precedido de «…quedará así:» es articulado de OTRA norma transcrito, no un artículo de este documento; **[X2]** entre las propias gana la MÁS TARDÍA (índices al principio, articulado después); **[X3]** si dos supervivientes comparten <50% de contenido se registra `divergencia_alta`. Cada artículo lleva `ocurrencias_descartadas` con posición, extracto de 100 chars y motivo. Ley 1882: 25 → 21 artículos (desaparecen los 25, 27, 32 y 33, que son de las leyes 1508 y 1682). Ley 80 y Ley 1150 sin cambios. 13 tests en `test_indexador.py` |
| N10 | **La regla de posición por sí sola no arreglaba la Ley 1882** | Se propuso sustituir «más texto» por «más tardía». Medido antes de aplicar: ambas reglas eligen la MISMA ocurrencia equivocada en los arts. 4, 5 y 10, porque la transcripción va después del artículo modificatorio y además suele ser más larga. Y la Ley 80 —el caso que motivó la regla de longitud— **ya no tiene duplicados**: los eliminó el arreglo previo del regex de encabezados | **RESUELTO 2026-09-16 con una tercera regla**: excluir transcripciones ANTES de desempatar. La posición sigue haciendo falta para el caso índice/cuerpo, así que las dos conviven |
| D17 | **ABIERTO — 21 duplicados sin resolver en el Decreto 1082** | El `.md` contiene dos `CAPÍTULO 3` distintos bajo el Título 6 («DE LA GESTIÓN DE RECURSOS…» y «DE LA FORMULACIÓN, EVALUACIÓN PREVIA…»), ambos numerando sus artículos `2.2.6.3.x`. Son artículos genuinamente distintos con el mismo número: defecto de la fuente (EVA Gestor Normativo), no del indexador. Similitudes de 0,04 a 0,18. `[X2]` elige el más tardío y `[X3]` deja los 21 avisos en `avisos_indexacion`. **Ninguna de nuestras citas los toca** salvo `2.2.1.2.4.2.8`, que no usamos | **ABIERTO — registrado y visible, no silencioso** |
| D16 | **6 normas que el sistema necesita y no tiene** | **Ley 1437/2011 CPACA** (recurso de reposición contra la adjudicación; E11 la necesita, pero mientras no esté ese caso mide correctamente la abstención), Ley 590/2000 y Decreto 1074/2015 (Mipyme), Ley 2069/2020 (limitación a Mipyme, E12), Ley 1116/2006 (insolvencia, E13), Ley 2097/2021 (REDAM, E14) | **ABIERTO — descargar y extraer** |
| N12 | **Los avisos de indexación se quedaban en el log** | El Decreto 1082 tiene 21 números de artículo con dos contenidos distintos (dos `CAPÍTULO 3` bajo el Título 6). El aviso quedaba en `avisos_indexacion` y nunca llegaba a quien firma el informe | **CORREGIDO 2026-09-16** — `aviso_de_articulo()` y el campo `Cita.aviso_fuente`, que el verificador rellena al aprobar una cita [N6]. El aviso viaja hasta el reporte de evaluación, que lo imprime bajo la cita. Un aviso que se queda en el log no protege a nadie |
| D19 | **PENDIENTE — el índice y el skill no distinguen NORMA de DOCTRINA** | El Manual del CCE (CCE-EICP-MA-04 v3) se guardó el 2026-09-16 en `biblioteca_normativa/doctrina/` con `tipo: "doctrina"` y `citable:false`. Un manual **orienta a las entidades pero no las vincula**: presentado como fundamento jurídico, la entidad puede responder que no es norma. Hoy el bibliotecario sólo conoce citable sí/no, así que la doctrina queda fuera por completo. Para usarla haría falta un nivel intermedio: citable como APOYO, nunca como fundamento, y marcado como tal en el documento | **ABIERTA — decisión de diseño, no bug** |
| N13 | **Verificación externa de la sustitución del art. 2.2.1.1.1.5.3** | La corrección del artículo de indicadores financieros no descansa sólo en coherencia interna: el Manual oficial del CCE, descargado de colombiacompra.gov.co y ajeno a este repositorio, dice literalmente *"artículo 2.2.1.1.1.5.3. del Decreto 1082 de 2015, son indicadores de la capacidad financiera los siguientes"* y confirma que **no fija umbral numérico alguno**. Una fuente independiente valida el reemplazo | **CONFIRMADO 2026-09-16** |
| D18 | **La «Resolución 196/2016 CCE» no existe** | Se citaba en 5 sitios de `prompts.py` como base de TODOS los umbrales financieros. Buscada en colombiacompra.gov.co: no aparece en el listado de resoluciones ni en el **Manual para determinar y verificar los requisitos habilitantes (CCE-EICP-MA-04 v3, 46 pp.)**, que descargué y revisé. El Manual **no fija umbral numérico alguno** y remite al `Decreto 1082 art. 2.2.1.1.1.5.3` para los indicadores, que es exactamente el artículo que ahora cita `prompts.py`. Conclusión: era otra cita inventada, como el `2.2.1.2.1.5.8`. Los umbrales (IDL ≥ 1,0, NDE ≤ 0,80) los fija la entidad o el Documento Tipo de la modalidad, no una norma nacional | **CERRADO 2026-09-16 — no hay nada que descargar.** Los 5 sitios pasan de `[norma no disponible]` a decir que la referencia no existe. Pendiente de decisión: si añadir el Manual del CCE a la biblioteca, teniendo en cuenta que **es una guía, no una norma** |
| N11 | **Nuestro propio prompt caía en la trampa de E06** | `prompts.py` instruía al agente jurídico a escribir *"No cumple RUP activo exigido por Ley 80/1993 art. 22"*. El art. 22 está **derogado por el art. 32 de la Ley 1150 de 2007**, y es exactamente el caso de control E06 de la evaluación del bibliotecario: diseñamos una trampa para medir si el agente lee lo que cita, y el sistema que la diseñó llevaba meses cayendo en ella. **Razón por la que el auditor permanente [N9] se queda**: la revisión por lectura encontró este error una vez; el auditor lo habría encontrado cada día. No lo detectó el auditor —el art. 22 existe— pero sí lo detectó la lectura que el auditor hizo posible al reducir el ruido | **CORREGIDO 2026-09-16** — sustituido por `Ley 1150/2007 art. 6`, con un aviso explícito de no citar nunca el art. 22 |

---

## Decisiones tomadas — no re-litigar

| Decisión | Razón |
|---|---|
| **marker + pdfplumber para nativos; Claude OCR para escaneados** | marker/pdfplumber son gratis y precisos en TIPO A/B. Claude OCR solo cuando no hay texto extraíble. |
| **El módulo de reparación de tablas NO aplica a TIPO C** | `localizar_pagina()` requiere texto nativo de pdfplumber; en escaneados devuelve 0 chars. 31 detecciones en Cravo Norte son FP del detector calibrado para marker. |
| **Umbrales CCE solo existen en mínima y menor cuantía; licitación es plantilla** | La Matriz 2 de licitación (DT-Licitacion-Version-2.zip) tiene celdas vacías — cada entidad llena sus valores según estudio del sector. El 1,21 de Paicol es de Paicol, no del CCE. |
| **Precedencia de umbrales: PLIEGO > CATÁLOGO > "no disponible"** | El catálogo CCE es referencia y piso normativo; la entidad puede exigir más. El evaluador toma el valor del pliego cuando existe. |
| **Sin eval(), solo evaluador AST restringido** | eval() es inyectable. El intérprete AST tiene whitelist explícita de nodos y funciones. Ver `criterios.py:_interpretar()`. |
| **Structured outputs: viable, no adoptado, queda como feature flag** | anyOf + $defs soportados para la unión discriminada Criterio. Riesgo: constrained decoding puede cambiar calidad de extracción. Requiere prueba A/B antes de adoptar. |
| **operador_inferido: true en tablas mipyme de CCE** | Las tablas de mipyme en Res-540/541 omiten el símbolo relacional (aparecen "1,1" y "0,70" sin ≥/≤). El operador se infiere por lógica financiera; debe ser auditable. |
| **Ninguna observación nace "confirmada"** | Una observación al pliego es un acto jurídico. El triple filtro (aritmético + citas + humano) es obligatorio antes de presentarla a una entidad. |

---

## Estructura normativa CCE — estado del catálogo

Archivo: `biblioteca_normativa/estructura_normativa.json` v2.1.0

| Modalidad | Estado | Valores CCE | Rangos |
|---|---|---|---|
| Obra pública (licitación) | Confirmado | Todos null — plantilla pura | 2 rangos × 2 variantes |
| Menor cuantía | Confirmado | Solo liquidez (1,1/1,2) | Sin rangos |
| Mínima cuantía | Confirmado | 3 indicadores completos | Sin rangos |

Mínima cuantía es **opcional** (entidad puede o no exigir capacidad financiera cuando no hay pago contra entrega).

ZIP de menor/mínima cuantía no descargables sin navegador (JS requerido en colombiacompra.gov.co). Datos confirmados por lectura directa de los .docx extraídos del ZIP de licitación.

---

## Dependencias del pipeline — estado en el entorno de la app (Railway)

El pipeline corre completo en local con `.venv_parsers`. El entorno de la app en Railway
**no tiene instaladas** las dependencias pesadas. Detalle:

| Dependencia | Rol en el pipeline | Peso aprox. | Instalada en app |
|---|---|---|---|
| `pdfplumber` | Detección y reparación de tablas (TIPO A/B) | ~30 MB | ❌ |
| `langchain-text-splitters` | Chunker por cabeceras Markdown | ~5 MB | ❌ |
| `marker-pdf` | Conversión PDF→Markdown con layout | ~200 MB (sin torch) | ❌ |
| `surya-ocr` | Motor OCR de marker para escaneados | ~800 MB + modelos | ❌ |
| `torch` | Dependencia transitiva de marker y surya | ~1.5 GB | Parcial (sentence-transformers) |

**Para PDF nativos (TIPO A/B — texto seleccionable):** las únicas dependencias faltantes son
`pdfplumber` y `langchain-text-splitters`. marker usa pypdfium2 en modo solo-texto cuando no
hay OCR necesario. Peso adicional: ~35 MB. **Viable para añadir a Railway sin cambiar el tier.**

**Para PDF escaneados (TIPO C):** el full stack. marker necesita surya + torch completo.
Peso total: ~2.5 GB. Requiere instancia dedicada o endpoint separado.

### Estrategia de aislamiento (pendiente implementar)

Para que marker no cargue torch en el proceso de FastAPI (conflicto con uvicorn + gunicorn
en producción), el parser para TIPO C debe correr en subprocess separado:

```python
# Patrón a usar cuando se implemente soporte Railway para escaneados:
result = subprocess.run(
    ["py", "-3.13", "pipeline/main.py", "--pdf-only", str(pdf_path)],
    capture_output=True, timeout=900  # 15 min para escaneados
)
```

El resultado se persiste en `.pipeline_cache/{sha256}.json` — la función `parsear_pdf()`
ya tiene esta caché, así que el subprocess solo corre una vez por PDF.

### Limitación conocida en el flujo actual (2026-09-07)

`routers/auditoria.py` — endpoint `POST /api/auditoria/analizar`:
- Llama a `extraer_texto_documento(raw_pliego, filename)` para validar el pliego
- Si el PDF es escaneado → devuelve `SCANNED_PDF_MARKER` → HTTP 422 antes de lanzar el pipeline
- El pipeline podría procesarlo con marker, pero la validación lo rechaza antes de llegar
- **Impacto:** PDF escaneados no pueden analizarse vía el endpoint (igual que antes)
- **Próximo paso:** detectar scaneados por heurística (< 200 chars extraídos) en vez de
  rechazar, y permitir que el pipeline intente con marker antes de devolver error
