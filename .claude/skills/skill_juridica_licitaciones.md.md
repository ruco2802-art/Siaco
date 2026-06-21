🏆 Skill: Agente de Inteligencia Estratégica para Licitaciones SECOP II (v4.0)
1. Módulo de Vigilancia y Filtro de Viabilidad (Go/No-Go)
El agente debe automatizar la búsqueda y segmentación de oportunidades para evitar el error de participar en procesos donde no se cumplen los requisitos
.
Segmentación por Perfil: Configurar búsquedas basadas en palabras clave y códigos CPV/UNSPSC precisos
.
Cruce de Capacidades: Analizar automáticamente los indicadores del RUP (financieros y de experiencia) frente a las exigencias del pliego
.
Incentivos Estratégicos: Identificar procesos limitados a MiPymes o que otorgan puntaje por Emprendimiento de Mujeres (más del 50% de capital o personal directivo femenino) para dar prioridad a estas alertas
.
2. Inteligencia Competitiva y Benchmarking Económico
La IA debe analizar contra quién se compite y qué precios suelen ofertar para evitar "precios temerarios"
.
Análisis de la TRM: Calcular escenarios de probabilidad basados en los decimales de la TRM (Media Aritmética, Geométrica, Media Aritmética Alta o Menor Valor) para determinar el precio óptimo, no necesariamente el más bajo
.
Extracción de Datos de Competidores: Utilizar la sección de "Lista de Proveedores" en el área de trabajo de SECOP II para descargar el histórico de ofertas (archivos ZIP) y analizar las debilidades de la competencia
.
Análisis Estadístico: Predecir el número de proponentes basándose en procesos similares anteriores para ajustar la agresividad de la oferta económica
.
3. Generación de Documentación Técnica de Alto Valor
El agente debe guiar la creación de propuestas que no sean genéricas ("copiar y pegar"), sino personalizadas para la entidad
.
Diferenciación de Requisitos: Asegurar que los documentos habilitantes (subsanables como RUT o cédulas) estén completos, pero priorizar los ponderables (no subsanables como certificaciones de calidad o experiencia técnica adicional), ya que estos últimos son los que otorgan los puntos para ganar
.
Memoria Técnica "Efecto Wow": Incluir elementos que los evaluadores recordarán, como diagramas de arquitectura, videos demo en links ocultos de YouTube o podcasts de casos de éxito
.
Puntaje por Inclusión: Generar automáticamente el soporte para puntos por vinculación de personal con discapacidad (mínimo 1% de la planta o según pliego) e incentivo a la industria nacional
.
4. Estrategia Especializada para Software (RFI/RFQ/RFP)
Para licitaciones de servicios tecnológicos o SaaS, el agente debe gestionar ciclos de venta más complejos
.
Prueba de Concepto (PoC): Enfocar la demostración en un caso de uso particular descrito en el pliego, no solo en mostrar funcionalidades generales
.
Gestión de "Champions": Solicitar a la entidad perfiles de usuarios proactivos y constructivos durante los periodos de prueba para generar retroalimentación positiva que influya en el comité evaluador
.
Lema de Ejecución: Mantener toda la interacción enfocada (al grano del problema) y documentada (vía PDF o video) para mitigar la "memoria corta" de los compradores
.
5. 5. Auditoría de Cumplimiento y Gestión de Alertas
Un error administrativo puede anular meses de trabajo. El agente debe 
monitorear el proceso activamente hasta la adjudicación final.

5.1 Monitoreo de Mensajes de la Entidad en SECOP II
- Estrategia de detección: polling cada 2 horas via API pública SECOP II
  endpoint: https://datos.gov.co/resource/p6dx-8zbt.json
  filtro: $where=id_del_proceso='{proceso_id}' AND fecha_ultima_actualizacion > '{ultimo_chequeo}'
- Campos a monitorear por cambio: estado_del_proceso, fecha_limite_recepcion_ofertas,
  fecha_limite_manifestacion_interes, descripcion_del_procedimiento
- Si cualquier campo cambia vs registro anterior → alerta INMEDIATA al usuario
- Guardar snapshot del contrato en cada chequeo: /expedientes/{proceso_id}/snapshots/{timestamp}.json
- Comparar snapshots consecutivos con difflib.unified_diff() para detectar cambios exactos
- Alerta especial si estado cambia a "Suspendido" o "Cancelado" → notificación urgente

5.2 Detección de Adendas y Modificaciones
- Problema: SECOP II no tiene endpoint dedicado para adendas, se detectan por:
  1. Cambio en campo descripcion_del_procedimiento (longitud o contenido)
  2. Cambio en fechas límite (la entidad publica adenda y mueve fechas)
  3. Nuevo documento en urlproceso (si el campo está disponible)
- Cuando se detecta cambio: re-analizar contrato completo con agente_legal_rag()
  y notificar qué cambió específicamente y si afecta la viabilidad
- Registrar en historial: {fecha_cambio, campo_modificado, valor_anterior, valor_nuevo}

5.3 Checklist de Cierre Inteligente
Activar automáticamente 72h antes de fecha_limite_recepcion_ofertas:
- Verificar documentos en biblioteca cliente vs requisitos del pliego:
  □ RUP vigente (vence en más de 30 días desde fecha cierre)
  □ Certificados de experiencia que cubren el objeto y valor requerido
  □ Estados financieros del año inmediatamente anterior
  □ Paz y salvo parafiscales (SENA, ICBF, Caja Compensación)
  □ Certificado de existencia y representación legal (< 30 días)
  □ RUT actualizado
  □ Garantía de seriedad de la oferta (si la exige el pliego)
- Generar reporte de checklist en PDF con ✅/❌ por ítem
- Recomendación: "Presente su oferta mínimo 2 horas antes del cierre 
  para evitar saturación de la plataforma SECOP II"

5.4 Monitoreo del Cronograma del Proceso
Rastrear y alertar en cada fecha clave:
- T-72h manifestación de interés → "Prepare carta de intención"
- T-24h manifestación de interés → 🚨 URGENTE alerta roja
- T-72h cierre recepción ofertas → activar checklist 5.3
- T-24h cierre → 🚨 URGENTE "Última revisión de oferta"
- Publicación informe de evaluación → notificar, analizar si hay observaciones
  que presentar (plazo legal: generalmente 3 días hábiles según Decreto 1082)
- Publicación de subsanaciones → alerta inmediata, plazo puede ser 24-48h
- Fecha de adjudicación → registrar resultado en historial del cliente
- Fecha de firma de contrato → cerrar expediente, registrar lección aprendida

5.5 Gestor de Subsanaciones
- Si en informe de evaluación aparece el cliente como "NO HABILITADO":
  1. Extraer razones del informe (Claude analiza el PDF del informe)
  2. Cruzar con documentos en biblioteca del cliente
  3. Generar lista priorizada de documentos a subsanar
  4. Calcular tiempo disponible vs documentos faltantes
  5. Alerta: "Tiene X horas para subsanar. Documentos críticos: [lista]"
- Registrar en historial: qué se subsanó, si fue aceptado, lección para futuro

5.6 Implementación Técnica — monitor_secop.py
Crear módulo independiente que corre via Task Scheduler cada 2 horas:
- MonitorSecop clase con:
  check_proceso(proceso_id) → compara estado actual vs snapshot anterior
  detectar_cambios(snapshot_nuevo, snapshot_anterior) → dict de diferencias
  evaluar_urgencia(cambios, fechas) → nivel "rojo|amarillo|verde"
  notificar_cambio(cliente_id, cambios, urgencia) → via Notificador existente
- Integración con expedientes.json: solo monitorea procesos con estado interno
  "En seguimiento", "Documentando" u "Oferta preparada"
- Log detallado en /logs/monitor_{fecha}.log con cada chequeo y resultado
- Costo API estimado: 0 (solo consulta API SECOP II, no llama Claude 
  salvo cuando detecta cambio real)