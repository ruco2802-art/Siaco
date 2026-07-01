# SKILL: Sistema Anti-Rechazo SIACO v2.0
# Propósito: Garantizar que una MiPyme presente una oferta 
# impecable en SECOP II, eliminando errores de forma que 
# causan rechazo antes de la evaluación de fondo.

## MÓDULO 0 — ANÁLISIS PREVIO DE VIABILIDAD (Go/No-Go)
Ejecutar ANTES de cualquier generación de documentos.

1. Extraer del pliego:
   - Requisitos habilitantes financieros (IDL, NDE, RCI, K residual)
   - Requisitos de experiencia (valor mínimo, número de contratos, CIIU)
   - Causales de rechazo explícitas (leer sección específica del pliego)
   - Criterios de ponderación (factor económico, técnico, calidad)
   - Cronograma clave (fecha cierre, evaluación, adjudicación)

2. Cruzar con perfil del cliente:
   - Si IDL cliente < IDL exigido → ALERTA BLOQUEANTE
   - Si experiencia cliente < experiencia exigida → ALERTA BLOQUEANTE
   - Si K residual < K exigido → ALERTA BLOQUEANTE
   - Si RUP vence antes del cierre → ALERTA BLOQUEANTE

3. Resultado Go/No-Go:
   - GO: proceder con generación de documentos
   - NO-GO: explicar exactamente qué impide participar 
     y qué acciones tomaría para remediarlo 
     (consorcio, subsanación, tramitar RUP, etc.)
   - CONDICIONAL: puede participar con observaciones 
     o si corrige X antes del cierre

## MÓDULO 1 — PARSER RAG DEL PLIEGO
Extraer y estructurar la información crítica:

Campos obligatorios a extraer:
- objeto_contrato
- valor_presupuesto_oficial
- plazo_ejecucion
- forma_pago (anticipo % + actas)
- modalidad_seleccion
- metodo_calificacion_economica 
  (media aritmética/geométrica/menor valor)
- requisitos_habilitantes: {financieros, juridicos, tecnicos}
- causales_rechazo_explicitas (citar textualmente)
- documentos_requeridos (lista completa del pliego)
- fecha_cierre_observaciones
- fecha_cierre_ofertas

Si un campo no se encuentra en el pliego usar: 
[NO_ESPECIFICADO_EN_PLIEGO] — nunca inventar.
Si un dato del perfil del cliente falta usar:
[INSERTAR_POR_USUARIO] — nunca inventar.

## MÓDULO 2 — VERIFICACIÓN DE VIGENCIAS
Antes de generar documentos, verificar:

□ RUP: fecha_vencimiento > fecha_cierre_ofertas
  → Si vence antes: ALERTA "RUP vence el [fecha], 
    debe renovarlo antes del [fecha_cierre]"
    
□ Cámara de Comercio: fecha_expedicion < 30 días al cierre
  → Si tiene más de 30 días: ALERTA "Solicite nuevo 
    certificado de existencia antes de presentar"

□ Paz y salvos (SENA, ICBF, Caja): < 30 días expedición
  → Recordatorio automático en checklist

□ Estados financieros: deben ser del último año fiscal cerrado

## MÓDULO 3 — GENERADOR DE DOCUMENTOS
Generar en este orden de foliación exacto:

FOLIO 1 — Carta de Presentación
Requisitos críticos asegurados:
- Declaraciones bajo gravedad de juramento (5 mínimo)
- Ausencia de inhabilidades e incompatibilidades 
  (Ley 80 art. 8 y 9)
- Paz y salvo parafiscales declarado
- Valor en números Y en letras (sin redondeo)
- Validez de la oferta: mínimo hasta fecha de adjudicación
- Firma representante legal con datos completos

FOLIO 2 — Documentos Jurídicos [el usuario los aporta]
Checklist con instrucciones de obtención:
□ RUT actualizado (dian.gov.co — gratuito)
□ Certificado existencia y representación legal 
  (Cámara de Comercio — máx 30 días)
□ Cédula representante legal (fotocopia)
□ Antecedentes disciplinarios (procuraduria.gov.co)
□ Antecedentes fiscales (contraloria.gov.co)
□ Antecedentes penales representante legal 
  (policía nacional)

FOLIO 3 — Formatos de Experiencia
Estructura según RUP y pliegos tipo CCE:
Tabla: No | Contratante | Objeto | Código UNSPSC | 
Valor ($) | Valor SMMLV | Fecha inicio | Fecha fin | 
% participación | Certificado No.

Nota automática: "Contratos con certificados adjuntos 
como Folios [X] al [Y] de la presente oferta"

FOLIO 4 — Capacidad Financiera
Cálculo exacto según Decreto 1082/2015:
IDL = Activo Corriente / Pasivo Corriente = [valor]
NDE = Pasivo Total / Activo Total = [valor]
RCI = Utilidad Operacional / Gastos Financieros = [valor]
K = (0.80 × Patrimonio Líquido) - Vc = [valor]

Comparativa vs exigido:
Indicador | Exigido | Cliente | Cumple
IDL      | ≥ X.X   | X.XX    | ✅/❌

FOLIO 5 — Capacidad Organizacional
ROE = Utilidad Neta / Patrimonio = [%]
ROA = Utilidad Neta / Activo Total = [%]
"Firmado por [nombre contador/revisor fiscal] 
con Tarjeta Profesional No. [TP]"

FOLIO 6 — Propuesta Técnica y Metodológica
[Plantilla estructurada — el usuario completa el contenido]
Secciones:
1. Entendimiento del objeto contractual
2. Metodología de ejecución
3. Cronograma de actividades (hitos)
4. Equipo de trabajo propuesto (perfiles requeridos por pliego)
5. Plan de calidad (si aplica)

FOLIO 7 — Propuesta Económica (Formulario APU)
Estructura exacta pliegos tipo CCE obras:
No | Ítem | Unidad | Cantidad | Precio Unit. | Total
[ítems de la calculadora APU de SIACO]
Subtotal costos directos
A. Administración __% = $
I. Imprevistos __% = $
U. Utilidad __% = $
Subtotal AIU
VALOR TOTAL SIN IVA
IVA __% = $
VALOR TOTAL OFERTA = $
VALOR EN LETRAS: [número a letras completo, sin redondeo]

FOLIO 8 — Certificaciones Parafiscales [usuario aporta]
□ Paz y salvo SENA (certificado.sena.edu.co)
□ Paz y salvo ICBF (portal ICBF)  
□ Paz y salvo Caja de Compensación Familiar
□ Planilla de pago seguridad social último mes

FOLIO 9 — Garantía de Seriedad [usuario aporta]
Instrucciones automáticas:
"Solicite a su aseguradora una póliza de seriedad por:
- Valor: [% especificado en pliego] del presupuesto oficial
  = $[valor calculado automáticamente]
- Vigencia: hasta [fecha adjudicación + 3 meses estimado]
- Tomador: [nombre empresa] NIT [NIT]
- Beneficiario: [nombre entidad] NIT [NIT entidad]
- Amparando: Seriedad de la oferta proceso [código]"

## MÓDULO 4 — VALIDADOR DE ENTREGA
Verificación final antes de presentar en SECOP II:

REGLAS ANTI-RECHAZO:
□ Valor oferta ≤ Presupuesto oficial (si supera = rechazo automático)
□ Valor en letras coincide con valor en números
□ Todos los campos del formulario económico suman correctamente
□ RUP vigente a la fecha de cierre
□ Carta de presentación firmada por representante legal del RUP
□ Ningún documento con fecha posterior al cierre del proceso
□ Garantía de seriedad con valores correctos
□ Todos los documentos nombrados sin espacios ni 
  caracteres especiales:
  01_Carta_Presentacion.pdf
  02_RUT.pdf
  03_Camara_Comercio.pdf
  04_Cedula_Representante.pdf
  05_Experiencia_Contratos.pdf
  06_Capacidad_Financiera.pdf
  07_Propuesta_Tecnica.pdf
  08_Propuesta_Economica.pdf
  09_Paz_Salvo_SENA.pdf
  10_Paz_Salvo_ICBF.pdf
  11_Paz_Salvo_Caja.pdf
  12_Garantia_Seriedad.pdf

INSTRUCCIÓN FINAL AL USUARIO:
"Presente su oferta en SECOP II con mínimo 2 horas 
de anticipación al cierre. Cargue los documentos en 
el orden del índice anterior. Si la plataforma presenta 
errores técnicos, tome captura de pantalla como evidencia 
y comuníquese con la Mesa de Ayuda de Colombia Compra 
Eficiente: (601) 7956600."

## DIRECTRICES OPERATIVAS (CONSTRAINTS)
1. Marco normativo: Ley 80/1993, Ley 1150/2007, 
   Decreto 1082/2015, pliegos tipo CCE vigentes 2026
2. NUNCA inventar datos — usar marcadores [INSERTAR_X]
3. NUNCA generar contenido técnico específico de la obra 
   (metodología, cronograma) — solo la estructura
4. Citar el artículo y decreto exacto en cada requisito
5. Si hay contradicción entre el pliego y la norma, 
   alertar y recomendar observación
6. Lenguaje formal jurídico, Times New Roman 12pt, 
   interlineado 1.5, márgenes 2.5cm
7. Cada documento con encabezado: 
   [empresa] | [proceso] | Folio X de Y
8. Pie de página: "Generado con SIACO — 
   Verifique con asesor jurídico antes de presentar"
