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
| **I10** | **Ningún campo que sostenga una afirmación tiene valor por defecto** | — | TestConcepto, TestEstados (`test_un_numero_sin_umbral_no_puede_salir_como_cumple`, `test_los_umbrales_proporcionales_siguen_sin_fijarse`) | **El más caro de violar** |

### I10 — La ausencia se declara; nunca se rellena

**Enunciado.** Ningún campo que sostenga una afirmación puede tener valor por
defecto. La ausencia se declara; nunca se rellena.

Se escribe como invariante y no como corrección puntual porque **los tres
errores más graves encontrados hasta hoy son el mismo patrón**, y aparecieron
de a uno, con meses de distancia:

| dato ausente | lo que el código producía | dónde |
|---|---|---|
| cita sin norma que la sostenga | **inventaba una** — `"Decreto 1082/2015 art. 2.2.1.2.1.5.8"`, inexistente | `routers/auditoria.py:154` · [D14] |
| umbral sin unidad en el texto | **ponía «meses»** cuando la magnitud parecía temporal | prompt de extracción · [D25] |
| valor sin umbral contra el que compararlo | **declaraba CUMPLE** — `bool(1.85)` es `True` | `evaluator._evaluar_item()` · [D31] |

En los tres, **ante la ausencia de un dato el código PRODUCE una respuesta en
vez de declarar que no sabe**. Los tres pasaron revisión de código y tests: no
fallan, responden. Por eso hace falta el invariante y no basta el criterio.

**Cómo se aplica.** Un campo que sostiene una afirmación es el que, si está
mal, hace que el informe afirme algo falso sobre la empresa o sobre la norma:
`criticidad`, `estado`, `valor_umbral`, `operador`, `unidad`, `norma`, `cita`,
`estado_verificacion`, `concepto`. Para esos:

- **vacío es un resultado válido** y se propaga hasta la pantalla y el informe;
- **un estado que nombra la ausencia** (`dato_faltante`, `revisar_manual`,
  `indeterminado`, `SIN CONCEPTO`) es preferible a cualquier valor plausible;
- **un booleano que responde SÍ o NO sí es una respuesta**; un número, un
  string no vacío o una lista con elementos **no lo son** por el hecho de
  existir. `bool(valor)` sobre algo que no es booleano es la firma del error.

**La prueba para saber si un default es legítimo:** si el campo vacío produjera
una frase en el informe del tipo «no se pudo determinar», el default está mal.
Si el campo vacío no cambia ninguna afirmación —un color, un orden, un ancho de
columna— el default es una comodidad y está bien.

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
| N7 | **Un `exigido_literal` corrupto llegaba al informe como cita textual** | La fórmula del CRPC de Paicol salió del PDF con la codificación rota: `CRPC = %&'()"*!+!,- - ,/0-`. Estaba marcada `no_verificada`, así que el sistema lo sabía, **pero la cadena se publicaba igual** en pantalla y habría ido al informe firmado como «cita textual del pliego». Mismo principio que [N5] con la Ley 1474: que una cadena exista en el documento no la hace legible, y aquí además es la cita que sostiene la afirmación ante una entidad | **CORREGIDO 2026-09-24** — `literal_ilegible()` y `texto_cita()` en `estados.py`; el front replica el detector y el PDF lo importa. Señal: **racha de 3+ símbolos que no pertenecen a una fórmula**, o 4+ de los que sí pueden aparecer. El ratio de caracteres no alfabéticos NO servía —el roto está en 8,6% y un literal sano de tabla (`Mipyme \| 0,25`) llega a 7,7%. Calibrado: **1 de 218 en Paicol, 0 de 340 en Ternera**, cero falsos positivos sobre 8 fórmulas legítimas. En vez de la cadena se muestra «texto no legible en el documento fuente — revisar numeral X», que dice dónde buscarlo |
| N8 | **La unidad del umbral podía contradecir el texto del pliego sin que nadie lo viera** | El extractor pone `unidad="meses"` **por defecto** cuando la magnitud es temporal y no la resuelve. **4 casos reales** entre los dos pliegos, los cuatro con «meses»: *maquinaria con edad menor a veinte (20) **años*** → `20.0 meses`; *plazo de subsanación de tres (3) **días hábiles*** → `3.0 meses`; *mínimo un **año** de existencia para Mipyme* → `1.0 meses`; *antigüedad máxima en **días*** → `60.0 meses` (30×). El de la Mipyme es el peor: daría por válida a una empresa de seis meses, y **un falso positivo —decirle al cliente que califica cuando va a ser rechazado— es peor que un falso negativo** | **CORREGIDO 2026-09-24** — `unidad_discordante()` en `estados.py` [N8]; el evaluador manda esos requisitos a **`revisar_manual`** y expone `unidad_registrada` y `unidad_en_el_pliego`. Pantalla y PDF muestran **AMBOS** datos. Es **DETECCIÓN, NO CORRECCIÓN**: el valor no se toca, porque deducir que «20 meses» quería decir «20 años» sería inventar. Sólo dispara con evidencia en los dos lados: sin umbral, sin unidad declarada, o si el literal no nombra unidad, no se concluye nada. Calibrado: 1 de 154 en Paicol y 3 de 253 en Ternera, cero falsos positivos sobre 7 casos concordantes |
| D25 | **DEUDA DEL PROMPT — la unidad se pone por defecto en vez de dejarse vacía** | Es la causa raíz de [N8], que sólo lo detecta. **El patrón**: el extractor asume «meses» cuando la magnitud es temporal y no resuelve cuál — los 4 casos medidos lo tienen. **Es el mismo error que la cita normativa fabricada de `auditoria.py:154`**: un valor por defecto en un campo que debe venir del documento no es una comodidad, es un dato inventado con apariencia de dato extraído. **QUÉ CAMBIAR**: el prompt debe tomar la unidad del MISMO texto del que saca el valor, y **dejarla vacía si no la resuelve** — nunca un valor por defecto. Un campo vacío es correcto; uno inventado es un error grave (`PRODUCT.md`, principio 1) | **ABIERTA — se aplica en la PRÓXIMA re-extracción, junto a D20.** Mientras no se aplique, [N8] contiene el daño: los 4 casos van a `revisar_manual` en vez de producir un veredicto falso |
| D24 | **172 emoji en las vistas de la app sin migrar a SVG** | `DESIGN.md` prohíbe emoji como iconos y `operate.md` exige un solo vocabulario por superficie. La vista de **resultado de auditoría** se migró el 2026-09-23 (14 → 0, con 9 iconos funcionales de trazo 1,7px). Quedan 172: `index.html` 99 · expedientes 7 · búsqueda SECOP 9 · calculadora APU 12 · estrategia de precio 5 · análisis de pliego 4 · observaciones 4 · admin 4 · perfil 5 · resto 23. `landing.html` ya cumple con cero. **La mezcla entre vistas es deliberada**: la unidad de coherencia es la VISTA, no la aplicación — quien lee el informe no mira la búsqueda al mismo tiempo. Lo que no se tolera es una pantalla con los dos vocabularios a la vez. Inventario completo por vista en `DESIGN.md` → «Iconografía de la APP» | **NO ES TAREA ABIERTA. Condición de disparo: cuando se rediseñe una vista, sus emoji se migran a SVG EN EL MISMO TRABAJO.** No se abre una tarea de migración; se migra al tocar la pantalla. **Y lo nuevo nace en SVG**: la deuda cubre lo existente, no autoriza añadir un emoji más |
| D23 | **Migrar la APP al tema claro del sistema de papel** | La landing usa «El Expediente Habilitado» (manila `#ECE3D0`, rojo foliación `#B23324`) y la app usa tema oscuro (`#0A0A0A`, lima `#C6F24E`). **No es deuda de diseño**: es decisión deliberada del 2026-09-23, documentada en `CLAUDE.md`, `PRODUCT.md → Surfaces` y `DESIGN.md → Surfaces`. El tema oscuro está justificado por uso —el analista lee tablas densas dos horas seguidas— y por el modelo de agencia, en el que la app la opera el equipo y el cliente recibe el documento | **NO ABIERTA. Condición de disparo: que los CLIENTES pasen a usar la app directamente en vez de recibir el informe.** Mientras el modelo sea de agencia, migrar no aporta y cuesta rehacer `style.css` entero. Si la condición no se cumple, esta entrada no se ejecuta |
| D20 | **DEUDA — el prompt de extracción deja sin clasificar la criticidad cuando el numeral es un encabezado de sección** | Ternera dejó **29 de 253 requisitos consolidados en `indeterminado` (11,5%)**, contra el 1,9% de Paicol. **No es un problema del catálogo**: identifica el objeto en 28 de los 29 (9× EXPERIENCIA_CONTRATOS, 4× APU, 2× CAPACIDAD_RESIDUAL, 2× COBERTURA_INTERESES…). `criticidad` la fija el extractor, y estos 29 vienen de chunks cuyo `fuente_numeral` es un **encabezado de sección** sin jerarquía numérica —`EXPERIENCIA ESPECIFICA:`, `E. Saldos contratos en ejecución`, `8.2. ANÁLISIS DE PRECIOS UNITARIOS`— donde el contexto no sugiere la criticidad y el modelo la omite. **QUÉ CAMBIAR**: el prompt debe exigir criticidad *también* cuando el contexto de sección no la sugiera, razonando desde el contenido del requisito en vez de dejar el campo sin clasificar. **NO se deriva de la `categoria` del catálogo**: sería reintroducir B6 en el campo que decide si la empresa puede ofertar, y el default a `indeterminado` existe precisamente para no afirmar lo que el modelo no dijo | **ABIERTA — se aplica en la PRÓXIMA re-extracción, no en una corrida dedicada.** El 11,5% queda bajo el umbral del 20% de `aviso_clasificacion`, así que no bloquea ningún análisis |
| D21 | **PENDIENTE — no hay camino de notificación en producción** | `notificador.py::enviar_gmail()` funciona, pero su único llamador es `app.py:738`, el Streamlit legacy que no se sirve. La FastAPI no tiene endpoint de alertas (ya anotado en `PENDIENTES.md:45`). `GMAIL_USER`/`GMAIL_APP_PASSWORD` vacías **no rompen nada porque no hay nada que romper**, y el método lanza `ValueError` explícito, sin degradación silenciosa. Si se quieren avisos de cierre de proceso, falta CONSTRUIR el camino, no configurar el correo | **ABIERTO** |
| D22 | **RESUELTO — `LLAMA_CPP_BINARY` se perdió y no hacía falta** | La variable desapareció en una edición fallida del `.env`. **Cero referencias en el repositorio**: era de un experimento abandonado y el binario nunca se instaló. El timeout que se añadió para el caso de llama.cpp colgado sigue activo: `_convertir_con_timeout()` en `parser.py:204`, con `PARSER_TIMEOUT_S` (defecto 300 s) y fallback automático a Claude vision. Con `PARSER_OCR_BACKEND=claude` en el `.env`, un escaneado nuevo salta marker/surya directamente en vez de esperar los 300 s | **CERRADO 2026-09-23** |
| D16 | **6 normas que el sistema necesita y no tiene** | **Ley 1437/2011 CPACA** (recurso de reposición contra la adjudicación; E11 la necesita, pero mientras no esté ese caso mide correctamente la abstención), Ley 590/2000 y Decreto 1074/2015 (Mipyme), Ley 2069/2020 (limitación a Mipyme, E12), Ley 1116/2006 (insolvencia, E13), Ley 2097/2021 (REDAM, E14) | **ABIERTO — descargar y extraer** |
| N12 | **Los avisos de indexación se quedaban en el log** | El Decreto 1082 tiene 21 números de artículo con dos contenidos distintos (dos `CAPÍTULO 3` bajo el Título 6). El aviso quedaba en `avisos_indexacion` y nunca llegaba a quien firma el informe | **CORREGIDO 2026-09-16** — `aviso_de_articulo()` y el campo `Cita.aviso_fuente`, que el verificador rellena al aprobar una cita [N6]. El aviso viaja hasta el reporte de evaluación, que lo imprime bajo la cita. Un aviso que se queda en el log no protege a nadie |
| D19 | **PENDIENTE — el índice y el skill no distinguen NORMA de DOCTRINA** | El Manual del CCE (CCE-EICP-MA-04 v3) se guardó el 2026-09-16 en `biblioteca_normativa/doctrina/` con `tipo: "doctrina"` y `citable:false`. Un manual **orienta a las entidades pero no las vincula**: presentado como fundamento jurídico, la entidad puede responder que no es norma. Hoy el bibliotecario sólo conoce citable sí/no, así que la doctrina queda fuera por completo. Para usarla haría falta un nivel intermedio: citable como APOYO, nunca como fundamento, y marcado como tal en el documento | **ABIERTA — decisión de diseño, no bug** |
| N13 | **Verificación externa de la sustitución del art. 2.2.1.1.1.5.3** | La corrección del artículo de indicadores financieros no descansa sólo en coherencia interna: el Manual oficial del CCE, descargado de colombiacompra.gov.co y ajeno a este repositorio, dice literalmente *"artículo 2.2.1.1.1.5.3. del Decreto 1082 de 2015, son indicadores de la capacidad financiera los siguientes"* y confirma que **no fija umbral numérico alguno**. Una fuente independiente valida el reemplazo | **CONFIRMADO 2026-09-16** |
| D18 | **La «Resolución 196/2016 CCE» no existe** | Se citaba en 5 sitios de `prompts.py` como base de TODOS los umbrales financieros. Buscada en colombiacompra.gov.co: no aparece en el listado de resoluciones ni en el **Manual para determinar y verificar los requisitos habilitantes (CCE-EICP-MA-04 v3, 46 pp.)**, que descargué y revisé. El Manual **no fija umbral numérico alguno** y remite al `Decreto 1082 art. 2.2.1.1.1.5.3` para los indicadores, que es exactamente el artículo que ahora cita `prompts.py`. Conclusión: era otra cita inventada, como el `2.2.1.2.1.5.8`. Los umbrales (IDL ≥ 1,0, NDE ≤ 0,80) los fija la entidad o el Documento Tipo de la modalidad, no una norma nacional | **CERRADO 2026-09-16 — no hay nada que descargar.** Los 5 sitios pasan de `[norma no disponible]` a decir que la referencia no existe. Pendiente de decisión: si añadir el Manual del CCE a la biblioteca, teniendo en cuenta que **es una guía, no una norma** |
| N11 | **Nuestro propio prompt caía en la trampa de E06** | `prompts.py` instruía al agente jurídico a escribir *"No cumple RUP activo exigido por Ley 80/1993 art. 22"*. El art. 22 está **derogado por el art. 32 de la Ley 1150 de 2007**, y es exactamente el caso de control E06 de la evaluación del bibliotecario: diseñamos una trampa para medir si el agente lee lo que cita, y el sistema que la diseñó llevaba meses cayendo en ella. **Razón por la que el auditor permanente [N9] se queda**: la revisión por lectura encontró este error una vez; el auditor lo habría encontrado cada día. No lo detectó el auditor —el art. 22 existe— pero sí lo detectó la lectura que el auditor hizo posible al reducir el ruido | **CORREGIDO 2026-09-16** — sustituido por `Ley 1150/2007 art. 6`, con un aviso explícito de no citar nunca el art. 22 |
| D26 | **CONDICIÓN CONOCIDA DEL DESPLIEGUE — el informe en PDF necesita Chromium en la imagen** | Decisión del 2026-09-27: el informe se maqueta por la **vía (b), HTML + CSS de impresión**, renderizado con Chromium/Edge headless (`--print-to-pdf`). En local no cuesta nada (Edge y Chrome ya están). En Railway hay que añadir Chromium a la imagen: **~280-350 MB** con el buildpack de Playwright o `apt-get chromium`. Las alternativas se midieron y no sirven: WeasyPrint **no instala limpio en Windows** (necesita GTK/pango/cairo) y soporta peor `@page`; wkhtmltopdf está archivado desde 2023, con WebKit viejo sin grid ni variables CSS. La vía (a) con fpdf2 funciona hoy sin tocar el despliegue, pero maqueta en aritmética de milímetros y no comparte hoja de estilos con el resto de la familia documental: el coste se multiplica por cada documento | **NO ES BLOQUEO Y NO ES TAREA ABIERTA.** Es una condición que se paga **cuando haya despliegue**, y condicionar hoy la maquetación a un despliegue sin fecha es al revés: cuando llegue habrá opciones que hoy no existen. **Condición de disparo: el primer despliegue que deba generar el PDF en servidor.** Hasta entonces se genera en local, que es donde opera la agencia |
| D27 | **EL PASO 3 DE LA CADENA NO EXISTE — el sistema no puede producir ni un hallazgo documental** | La cadena del servicio son cuatro pasos: qué exige el pliego · si la empresa cumple · **qué le falta** · si alcanza a conseguirlo. Medido en Paicol el 2026-09-27 con `concepto.origen_dato_faltante()`: de los **38 requisitos habilitantes documentales sin dato, 38 son `no_preguntado` y 0 son `le_falta`**. Ninguno dice «le falta esto»; todos dicen «no sabemos». Con el perfil de prueba COMPLETO — no es que la empresa no respondiera, es que el perfil **no tiene campo** para esos conceptos. **Lo que lo activa** son los 6 campos documentales que aparecen en los DOS pliegos más `CAPACIDAD_JURIDICA`: `RUP`, `EXISTENCIA_REPRESENTACION`, `ESTADOS_FINANCIEROS`, `SEGURIDAD_SOCIAL`, `DOCUMENTO_IDENTIDAD`, `SUBCONTRATACION`, `CAPACIDAD_JURIDICA`. **NO es una mejora del formulario: es lo que habilita una parte del servicio.** Mientras no exista, la sección 6 del informe sólo puede decir *«Debe confirmar que cuenta con estos documentos»* —honesto, porque no afirma ni que los tenga ni que le falten— y la distinción interna (hallazgo confirmado vs. pendiente de captura) se declara en la sección 9 de trazabilidad, que es donde va lo nuestro | **PARCIALMENTE RESUELTA 2026-09-28** — `PerfilDocumental` con los seis documentos y `capacidad_juridica`, formulario en la pestaña Documentos, y `Documento{tiene, fecha_expedicion}` con evaluación de vigencia. **El sistema ya produce hallazgos**: `tiene=False` da NO CUMPLE con motivo, y un pliego con vigencia distingue «lo tiene vigente» de «lo tiene vencido». **Pero sólo 6 de los 34 de Paicol pasan a veredicto**, porque lo que los pliegos preguntan sobre tres de los seis objetos NO es lo que el campo contesta [D32]: `EXISTENCIA_REPRESENTACION` pide la DURACIÓN de la sociedad, `SEGURIDAD_SOCIAL` pide declaraciones de persona natural y `SUBCONTRATACION` es una obligación de ejecución. Faltan campos, no enrutado. Sigue **ABIERTA** para el resto ~~es alcance de producto~~ El código ya la mide y la declara: `resumen_origenes()['produce_hallazgos']` es `False` hoy, y un test lo fija para que el día que cambie se note |
| D34 | **Los 28 que siguen sin dato después de [D27], y qué campo necesita cada grupo** | Medido el 2026-09-28 con los siete campos poblados. **9 `EXPERIENCIA_CONTRATOS`** y **2 `FECHAS_EJECUCION`** — cambian en cada oferta, NO van al perfil: los captura el análisis. **4 `CAPACIDAD_RESIDUAL`** — se calcula, no se responde. **3 `SEGURIDAD_SOCIAL`** — necesitan `regimen_pensional_representante`, `exento_cotizacion_pension` y `tiene_personal_a_cargo`, que son tres preguntas distintas y ninguna es «está al día». **2 `EXISTENCIA_REPRESENTACION`** — necesitan `duracion_sociedad_hasta: date`, que es el campo que de verdad contesta «la sociedad dura más que el plazo + 1 año». **2 `UNSPSC`** — el campo existe (`codigos_unspsc`) pero falta el criterio de comparación de conjuntos contra los códigos del pliego. **1 `CONDICION_MIPYME`** — el pliego pide Mipyme **domiciliada en Paicol**, y `es_mipyme` sola no contesta el domicilio. **1 `SUBCONTRATACION`**, **1 `AUTORIZACION_ORGANO_SOCIAL`**, **1 `SUBSANABILIDAD`** (regla) y **3 sin objeto de catálogo** | **ABIERTA — el siguiente campo con mejor relación es `duracion_sociedad_hasta`**: una sola fecha resuelve 2 requisitos en Paicol y aparece en los dos pliegos. Los 9 de experiencia NO se resuelven con campos del perfil y no deben intentarse |
| D35 | **UNA CAPACIDAD COMPLETA DESCONECTADA: el catálogo normativo de umbrales no puede aplicarse — décimo caso del patrón** | No son «nueve variables sin poblar»: es que **todo el catálogo normativo de umbrales está construido y es inalcanzable por falta del dato de entrada**. `estructura_normativa.json` define los juegos de umbrales por **rango de presupuesto** (rango 1 <4.000 SMMLV, rango 2 ≥4.000) × **variante Mipyme/no-Mipyme**, y `seleccionar_rango_umbrales()` sabe elegir entre los cuatro. Para elegir necesita `presupuesto_oficial` y `smmlv_anio`, que llegan en `valores_pliego`. **`valores_pliego` llega siempre vacío**, así que la función devuelve `None`, `clave_umbrales` se queda en `umbral_no_determinable` y **el pipeline NUNCA elige juego de umbrales por rango y variante**. Los indicadores financieros se evalúan contra el umbral que traiga cada requisito, nunca contra el juego que le correspondería a la empresa por su tamaño y al proceso por su cuantía. **Es el décimo caso del patrón «construido y sin conectar»** —el campo `icono`, `reparar_markdown()`, `consolidar()`, `marcar_indices()`, `notificador.enviar_gmail()`, `generar_aviso_verificacion()`, las Matriz 2 [D4]…— y el de mayor alcance hasta ahora, porque no es un módulo sino una capacidad de producto entera. **QUÉ SE PUEDE EXTRAER DEL PLIEGO Y QUÉ NO**: van en la portada y son extraíbles — `presupuesto_oficial_estimado` (Paicol lo trae como `\$129.998.987` en la tabla del CDP), `plazo_meses` (Paicol «DOS MESES (02)»; Ternera NO, ver abajo), `porcentaje_anticipo`; **se derivan** — `valor_anticipo` (presupuesto × porcentaje) y `capital_trabajo_demandado` (fórmula CTd, que el pliego trae escrita); **NO salen del pliego** — `valor_smmlv_anio`, que es una constante anual del país — **es trivial de resolver: son cifras públicas, una por año, y basta una tabla en el repo. NO debe bloquear a las otras**, y desbloquea por sí solo la mitad de `seleccionar_rango_umbrales()`, y `saldos_contratos_en_ejecucion_pliego`, que lo declara el proponente. **`plazo_meses` se parte por pliego**: en Paicol está en el markdown («DOS MESES … (02)», tabla descolocada pero palabras adyacentes) y es cambio de prompt; en Ternera **no está** y es hueco del parseo | **ABIERTA — con auditor.** `pipeline/tests/test_variables_pliego.py` falla si aparece una variable huérfana sin registrar y exige que cada una diga qué haría falta. **No es fallo silencioso**: el código se niega a poner un default, que es [I10] bien aplicado, y el informe declara `umbral_no_determinable`. Pero mientras siga así, el trabajo de las Matriz 1, `estructura_normativa.json` y `seleccionar_rango_umbrales()` no produce nada |
| D36 | **LAS «CITAS NO VERIFICADAS» MIDEN FRAGILIDAD DEL VERIFICADOR, NO ERRORES DE EXTRACCIÓN — 0 de 8 fabricadas** | Revisadas una por una el 2026-09-28 las 6 de Ternera y las 2 de Paicol que fallaban por «texto ausente». **Ninguna está fabricada**: en las 8 el texto es del pliego. Las causas, por frecuencia: **(a) 3 casos — un PUNTO FINAL que el extractor añade.** Coinciden 296 de 297, 248 de 249 y 239 de 240 caracteres; lo único que falla es el punto con el que el extractor cierra la frase y el pliego no tiene. **(b) 1 caso — un MARCADOR DE IMAGEN del parser en mitad de la frase**: el markdown trae `![](_page_46_picture_0.jpeg)` entre «…de la fecha de corte de los» y «mismos». **(c) 1 caso — un MARCADOR DE LISTA**: el pliego dice «j. el porcentaje de participación» y la cita omite la «j.». **(d) 1 caso — MARKUP `**` que `_norm()` no quita.** **(e) 1 caso — una TABLA aplanada a prosa**: el pliego tiene la tabla UNSPSC con cabecera y guiones, y la cita la reescribe en línea (ver [D37]). **(f) 1 caso — el ÚNICO problema real de contenido: la cita ELIDE un pasaje con «...»** — dice «cualquier interesado**...** advierte que se dejó de incluir» donde el pliego dice «cualquier interesado, durante el traslado del informe de evaluación, o la entidad, en uso de la potestad verificadora, advierte…». No es falso, pero **contradice la Full-Citation Rule**, que el propio informe promete en la sección 2. `_norm()` en `verifier.py` normaliza símbolos, tildes y espacios, pero **no quita markup, marcadores de imagen ni de lista**, y exige coincidencia exacta de principio a fin | **CORREGIDO 2026-09-28** — `_sin_markup()` en `verifier.py` quita marcadores de imagen `![](…)`, etiquetas HTML, énfasis, tuberías de tabla y viñetas de lista **anidadas** (`- j. el porcentaje…` dejaba la «j.» dentro); `_coincide()` tolera **exactamente un punto final sobrante**, no «los últimos caracteres» —una palabra distinta al final sigue fallando, porque puede invertir el sentido del requisito—. **Medido sobre los fragmentos crudos: Paicol 23→18 citas no verificadas, Ternera 65→31.** Sobre los habilitantes consolidados del informe, el **«texto ausente» baja a CERO en los dos pliegos**: lo que quedaba era artefacto nuestro. `causa_no_verificada()` devuelve ahora cuatro causas y `cita_elidida()` detecta la elisión. **PENDIENTE**: el prompt debe prohibir «...» en `exigido_literal` —Ternera tiene **9** citas elididas sobre los crudos— y va con [D20] y [D25]; y los artefactos guardados conservan el `estado_verificacion` viejo hasta que se migren, así que el informe RE-VERIFICA al generarse. ~~el informe NO está desacreditado, pero la sección 9 dice algo que no es.** Hoy presenta las 6 de Ternera como «puede ser un error de extracción», y 5 de 6 son artefactos nuestros. **Dos arreglos separados**: (1) el verificador debe limpiar markup, `![](…)` y marcadores de lista, y tolerar un punto final de más — eso recupera 6 de las 8; (2) el prompt debe prohibir la elipsis «...» en `exigido_literal`, que va con [D20] y [D25]. **Hasta arreglarlo, el informe de Ternera se puede mostrar**: las citas son correctas |
| D37 | **LA TABLA UNSPSC — Paicol la tiene completa, Ternera la perdió entera** | Verificado el 2026-09-28 sobre el markdown reparado de los dos. **CORRIGE lo que registré antes**: dije que la lista de códigos «no sobrevive a la extracción» y que estaba truncada, y **en Paicol es falso**. **PAICOL** — la tabla está **completa y bien formada** en el markdown: `| Clasificación UNSPSC | Descripción |` con dos filas, `72151300` (pintura residencial) y `72151900` (albañilería y mampostería), y **esos dos son los únicos códigos de 8 dígitos de todo el documento**: la lista no está truncada, el pliego sólo exige dos. El extractor **aplanó la tabla a prosa** pero conservó los dos códigos. **Es cambio de PROMPT**: que los capture como campo estructurado (`codigos_unspsc_exigidos: list[str]`) en vez de prosa, y va junto a [D20] y [D25]. **TERNERA** — la tabla **no está**: cero códigos de 8 dígitos en todo el markdown, y el texto salta de «en alguno de los siguientes códigos:» directamente al encabezado «1.5. RECURSOS QUE RESPALDAN…». **Es el módulo de tablas**, no el extractor: su metadata de reparación registra 25 tablas, 22 rotas detectadas, 14 reparadas con pdfplumber, 1 con modelo, 1 rechazada y **6 con `calidad_insuficiente`** | **RESPUESTA SOBRE TERNERA: el detector NUNCA VIO la tabla — el peor de los dos casos.** `detectar_tablas_rotas()` y `_contar_bloques_tabla()` trabajan **sobre el markdown**, escaneando líneas que empiezan por `|`. La tabla UNSPSC no está en el markdown, así que **no entró en `tablas_totales` (25) ni en ninguna categoría**: las 22 rotas detectadas cuadran exactamente con 14 pdfplumber + 1 modelo + 1 rechazada + 6 calidad insuficiente, y las 3 restantes son sanas. **La tabla se perdió ANTES del módulo de reparación**, en la conversión PDF→markdown, y el módulo sólo puede arreglar tablas que llegaron. Es una tabla perdida **sin registro**: nada en la metadata delata que faltaba. **Hace falta un control de que las tablas del PDF llegan al markdown**, no sólo de que las que llegaron estén bien. **ABIERTA, partida en dos.** El criterio de comparación de conjuntos **sigue sin construirse**, y la razón cambia: no es que la lista esté incompleta —en Paicol no lo está— sino que **no hay forma automática de saber si lo está**, y un «no solapa» contra una lista truncada le diría a un contratista que no califica por experiencia cuando sí califica: el peor error posible del sistema. Con `codigos_unspsc_exigidos` estructurado, la completitud deja de ser una suposición y el criterio se puede construir para los pliegos que lo traigan |
| D27-TECHO | **EL TECHO DE D27 — 16 de 35 alcanzables por perfil, 19 nunca** | Medido el 2026-09-28 sobre Paicol. **La línea de partida es 35, no 34**: al corregir las unidades de vigencia (los pliegos escriben «días calendario»), «RUP en firme con vigencia máxima 30 días» dejó de ser un CUMPLE sin comprobar y volvió a la lista. El descuadre era un defecto, no un error de conteo. **RESUELTOS HOY — 6**: `CAPACIDAD_JURIDICA` 2 · `ESTADOS_FINANCIEROS` 2 · `DOCUMENTO_IDENTIDAD` 1 · `RUP` 1. **ALCANZABLES con campos que faltan — 10**: `SEGURIDAD_SOCIAL` 3 (necesita `regimen_pensional_representante`, `exento_cotizacion_pension` y `tiene_personal_a_cargo`: tres preguntas distintas, ninguna es «está al día») · `EXISTENCIA_REPRESENTACION` 2 (`duracion_sociedad_hasta` ya construido, esperando el plazo del pliego) · `UNSPSC` 2 (el campo EXISTE, falta el criterio de comparación de conjuntos) · `CONDICION_MIPYME` 1 (`es_mipyme` y `municipio_domicilio` EXISTEN, falta el criterio conjunto: el pliego pide Mipyme **domiciliada en Paicol**) · `AUTORIZACION_ORGANO_SOCIAL` 1 · `SUBCONTRATACION` 1. **NO ALCANZABLES POR PERFIL, NUNCA — 19**: `EXPERIENCIA_CONTRATOS` 9 y `FECHAS_EJECUCION` 2 (los contratos que se aportan A ESTE proceso: cambian en cada oferta) · `CAPACIDAD_RESIDUAL` 4 (se CALCULA con el presupuesto del proceso y los saldos del momento) · 3 sin objeto de catálogo · `SUBSANABILIDAD` 1 (regla del pliego) | **ÉSTE ES EL DATO PARA PROMETER AL CLIENTE: el formulario puede llegar a responder 16 de 35 (46%). Los otros 19 (54%) NO son un hueco del formulario** — son datos del PROCESO, no de la empresa, y los captura el análisis de cada oferta. **D27 no se cierra con más campos: tiene techo.** Prometer «el formulario resolverá todos los documentales» sería prometer algo que no depende de construir nada |
| D28 | **SESGO DE MUESTRA en la especificación del formulario — dos pliegos, los dos de obra pública** | La lista de campos salió de cruzar Paicol y Ternera: **27 objetos distintos, 11 en los dos pliegos y 16 en uno solo**. La de 11 es sólida (aparece dos veces). La de 16 **puede ser artefacto de tener sólo dos muestras del mismo sector**: con un pliego de otro sector, parte de esos 16 pasaría a básico y la proporción cambiaría. **Cómo validarla**: ICBF está parseado y sin extraer (~$1), es de otro sector y separaría mejor lo básico de lo complementario | **ABIERTA — anotada, no programada.** No se corre ahora. Condición de disparo: antes de construir el formulario definitivo con los 16 complementarios; los 11 básicos no necesitan esperar |
| D29 | **El catálogo asigna objeto por coincidencia de palabra en dos casos medidos** | Encontrado el 2026-09-27 al clasificar los requisitos que la heurística del formulario no pudo tipificar. (a) Ternera numeral 3.1: *«los requisitos habilitantes serán acreditados por cada uno de los integrantes de la figura asociativa»* → catalogado como **`ENDEUDAMIENTO`**; el literal no habla de endeudamiento, habla de proponentes plurales. (b) Ternera numeral 1.15 (causales de rechazo): *«personal profesional sin los requisitos mínimos»* → catalogado como **`PERSONAL_PROFESIONAL`**; es texto de una causal de rechazo, no un requisito de personal. **No es fallo del clasificador de criticidad ni del extractor: es el catálogo eligiendo objeto por alias suelto.** Impacto hoy: los dos van a la sección de documentos del informe con un objeto que no les corresponde | **ABIERTA — 2 casos de 81 medidos (2,5%).** No bloquea: el informe imprime el `nombre` y el literal, no el objeto del catálogo. Se corrige revisando los alias de esos dos objetos, no añadiendo reglas nuevas |
| D30 | **El lookup del perfil enruta por `categoria` y pierde campos que sí existen** | `_valor_perfil()` elige el mapa de palabras clave según `req.categoria`, así que un requisito de RUP que el extractor clasificó como `experiencia` o `financiero` **no alcanza `PerfilJuridico.rup_en_firme`, que existe**. Medido en Paicol: de los 38 sin dato, **2 son este caso** —«RUP vigente y en firme antes del cierre» (categoría `experiencia`) y «RUP vigente y en firme para evaluación financiera y organizacional» (categoría `financiero`)—. Se buscaron los 38 contra los cuatro mapas ignorando la categoría: 10 dieron coincidencia, pero **8 son colisiones espurias** (`plazo`→`antiguedad_meses`, `certificacion`→`certificaciones`, `personal`→`personal_disponible`), lo que confirma que la coincidencia de subcadena entre mapas **no es señal fiable** y por eso NO se convirtió en un origen automático: habría producido 8 datos inventados con apariencia de dato medido. **La solución no es más palabras clave: es enrutar por el `objeto` del catálogo**, que ya identifica el concepto con independencia de la categoría que le puso el extractor y de cómo lo redacte el pliego | **RESUELTA 2026-09-27** — `catalogo.objeto_para_evaluar()` (sólo coincidencia por NOMBRE, nunca por el literal: eso inmuniza contra D29) + `evaluator.CAMPO_POR_OBJETO` con `ASPECTO_REQUERIDO`. Los 2 casos de RUP se resuelven. **De los 38 sin dato, 3 salen de la lista**: 2 a CUMPLE (los RUP) y 1 a `revisar_manual` (capacidad organizacional, por D31). Quedan 35. El resto NO es enrutado: son conceptos sin campo en el perfil, que es D27. Ver D32 por qué el mapa no se amplió más. ~~Se resuelve junto a D27~~, porque el formulario nuevo necesita exactamente esa clave. Los 2 casos quedan hoy como `no_preguntado`, que es conservador: pide confirmar un documento que la empresa probablemente tiene, y eso no afirma nada falso |
| D31 | **PRESENCIA PRESENTADA COMO CUMPLIMIENTO — 11 de los 47 habilitantes en CUMPLE de Paicol** | Encontrado el 2026-09-27 al implementar D30. `_evaluar_item()` cerraba con `cumple = bool(valor)` cuando el requisito no traía umbral numérico. `bool(1.85)` es `True`, así que **«Índice de liquidez» salía CUMPLE sin haber comparado 1,85 contra nada**: el umbral del pliego no se extrajo. Lo mismo con capital de trabajo (450.000.000), cobertura de intereses (3,2), rentabilidad del activo (0,09), capacidad organizacional (4.000.000.000) y personal (15). **Es el mismo error de clase que la cita fabricada y la unidad por defecto**: un valor con apariencia de medición. Y era el peor de los tres, porque afirmaba ante el cliente que cumplía un requisito HABILITANTE. **No lo introdujo D30: estaba en producción y el informe lo entregaba.** | **CORREGIDO 2026-09-27** — un BOOLEANO sigue siendo una respuesta (el perfil afirma que lo tiene o que no); un NÚMERO sin umbral pasa a `revisar_manual` con el motivo explícito, porque el dato de la empresa existe y lo que falta es leer el numeral del pliego: **tarea del OPERADOR, no del cliente**. Efecto en Paicol: habilitantes en CUMPLE 47 -> 28, `revisar_manual` 4 -> 14, puntos abiertos 17 -> 29. El concepto NO cambia (VIABLE CON SALVEDADES): sigue sin haber incumplidos |
| D32 | **Un mapa objeto->campo sin filtro de aspecto fabrica veredictos** | Al implementar D30 la primera versión cubría 30 objetos y resolvía 11 de los 38 sin dato. **9 de esos 11 eran falsos**: `EXISTENCIA_REPRESENTACION -> camara_comercio` daba CUMPLE a «duración de la persona jurídica no inferior al plazo del contrato más un año» (tener el certificado no dice cuánto dura la sociedad); `SEGURIDAD_SOCIAL -> paz_y_salvo_seguridad_social` lo daba a «declaración juramentada de no obligación de aportes» (estar al día no es no tener obligación); `UNSPSC -> bool(codigos_unspsc)` lo daba a «los contratos deben estar clasificados en ALGUNO DE ESTOS códigos» (tener códigos no dice que sean ésos). **Se probó filtrar por el `aspecto` del catálogo y NO separa**: bajo `acreditacion` conviven «Certificación de pagos de seguridad social» —que el campo sí contesta— y la declaración juramentada —que no—. **Los dos ejes del catálogo sirven para AGRUPAR, no para decidir un veredicto**: una bolsa mal formada se revisa, un CUMPLE falso se entrega | **CONTENIDO 2026-09-27** — el mapa se recortó a los indicadores numéricos (donde el campo ES la magnitud que el pliego compara, y un emparejamiento malo sale como número disparatado, no como CUMPLE silencioso) y al `RUP` **sólo en aspecto `vigencia`**. `ASPECTO_REQUERIDO` deja la puerta para los que necesiten el filtro. **Añadir un objeto exige comprobar que el campo contesta la pregunta con CUALQUIER aspecto**, no que suene parecido |
| D33 | **AUDITORÍA I10 — siete sitios más con el mismo patrón** | Búsqueda hecha el 2026-09-27 tras escribir I10, porque los tres primeros aparecieron de a uno y con meses de distancia. **(a) `routers/auditoria.py:176` — `subsanable` por defecto `True`. El PEOR de los nuevos**: el extractor deja el campo en `null` A PROPÓSITO (su prompt dice *«subsanable=true solo si el fragmento lo dice EXPLÍCITAMENTE»*), y la API lo convertía en `True`, así que la pantalla ponía la etiqueta «Subsanable» y el PDF escribía «Si» sobre un habilitante del que el pliego no dijo nada. Decirle a un cliente que puede subsanar algo que no puede es perder la oferta. **(b) `routers/auditoria.py:172` — los requisitos jurídicos no llevaban `estado`**: la mitad financiera de la misma tabla sí lo llevaba, así que un `dato_faltante` jurídico llegaba como `cumple=False` y se pintaba NO CUMPLE — el bug original que `estados.py` existe para impedir, vivo en la otra mitad. **(c) `routers/reportes.py:331` — `subsanable` por defecto «Si» en el PDF.** **(d) `routers/calculadora.py:336` — `dias` por defecto **30***: un mes completo de costo laboral inventado en el Excel de la oferta. **(e) `cantidad` por defecto **1*** en `routers/calculadora.py:335`, `routers/generador_oferta.py:319` y `calculadora_apu.py:176`, usada en el total. **(f) `unidad` por defecto **«und»*** en `calculadora_apu.py:213`, `routers/generador_oferta.py:318` y `routers/calculadora.py:307` — mismo patrón que [D25], en el documento que se presenta con la oferta. **(g) `evaluar_tarea7.py:151,309` — `estado` por defecto `"completo"`**, script sin llamador en producción | **(a), (b) y (c) CORREGIDOS 2026-09-27** — `subsanable` viaja sin valor y la pantalla no pinta etiqueta, el PDF escribe guion; los jurídicos llevan `estado`. **(d), (e) y (f) ABIERTOS — la calculadora y el generador de oferta necesitan su propia verificación**, no se tocan de paso: mueven dinero en un documento que se presenta. **(g) ABIERTO, sin impacto** |

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
