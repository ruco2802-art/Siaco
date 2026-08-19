# ESTADO DEL PIPELINE — 2026-08-18

Documento de referencia para retomar trabajo entre sesiones.
Actualizar en cada bloque significativo de trabajo.

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
