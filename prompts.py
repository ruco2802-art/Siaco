# -*- coding: utf-8 -*-
"""
Constantes de skills para inyección en prompts de agentes IA.
Derivadas de .claude/skills/ — actualizadas junio 2026.
"""

SMMLV_2026 = 1_750_905  # COP

SKILL_FINANCIERO = f"""
=== MARCO FINANCIERO SAFE-L — CONTRATACIÓN PÚBLICA COLOMBIA (obligatorio aplicar) ===

VALORES DE REFERENCIA 2026:
• SMMLV 2026: ${SMMLV_2026:,} COP
• Mínima cuantía: < 28 SMMLV → < $49.025.340 COP
• Anticipo máximo legal: 50% (Ley 1474/2011 art. 91)

INDICADORES HABILITANTES (Decreto 1082/2015 art. 2.2.1.2.1.5.8 + Resolución 196/2016 CCE):

IDL — Índice de Liquidez = Activo Corriente / Pasivo Corriente
  • Pliego Tipo infraestructura: IDL ≥ 1.0
  • IDL < 1.0 = ALERTA CRÍTICA — pasivos superan activos corrientes → rechazo automático
  • Sector transporte mayor cuantía: IDL ≥ 1.2

NDE — Índice de Endeudamiento = Pasivo Total / Activo Total
  • Pliego Tipo: NDE ≤ 0.80 (máximo aceptable)
  • Sector transporte contratos grandes: puede flexibilizarse hasta 0.85 si K residual cubre
  • Base legal: Resolución 196/2016 CCE, Matrices de indicadores por sector

RCI — Razón de Cobertura de Intereses = EBIT / Gastos Financieros
  • RCI < 1.0 = ANORMAL Y MUY MALO → incapacidad de cubrir obligaciones financieras
  • RCI ≥ 1.5 = ACEPTABLE para licitaciones públicas
  • RCI ≥ 3.0 = BUENO — fortalece la oferta
  • MiPyme: RCI puede ser N/A si no tiene deuda con intereses

CAPACIDAD RESIDUAL K (Resolución 196/2016 CCE, art. 3):
  K = (0.8 × Patrimonio Líquido) − Σ(valor_contratos_en_ejecución × %_pendiente_de_ejecutar)
  • K debe ser ≥ valor del contrato a licitar
  • Si K insuficiente → recomendar consorcio para sumar patrimonios
  • Nota: el anticipo reduce el capital de trabajo demandado → recalcular si hay anticipo

CRITERIOS MIPYME (Ley 590/2000, Decreto 1074/2015 art. 2.2.1.13.2):
  • IDL, RCI y rentabilidad se flexibilizan si proponente es MiPyme registrada
  • Participación mínima en consorcio para aportar: ≥ 10% del valor
  • Experiencia: hasta 2 contratos adicionales en RUP (máximo 7 contratos acreditables)

CUANDO EMITAS CONCEPTO: Cita siempre el artículo o norma específica que respalda la evaluación.
  • Si cumple: "Cumple IDL según Decreto 1082/2015 art. 2.2.1.2.1.5.8"
  • Si no cumple: "No cumple NDE (valor X > 0.80 máximo Pliego Tipo — Resolución 196/2016 CCE)"
===
"""

SKILL_JURIDICO = """
=== MARCO JURÍDICO — CONTRATACIÓN PÚBLICA COLOMBIA (obligatorio aplicar) ===

JERARQUÍA NORMATIVA APLICABLE:
1. Ley 80/1993 — Estatuto General de Contratación Pública (base principal)
2. Ley 1150/2007 — Eficiencia y transparencia (art. 5: subsanabilidad; art. 4: Pliegos Tipo)
3. Decreto 1082/2015 — DUR Contratación (art. 2.2.1.2.1.2.5: plazos; art. 2.2.1.2.1.5.8: habilitantes)
4. Ley 1474/2011 — Estatuto Anticorrupción (art. 91: anticipo máximo 50%)
5. Ley 1437/2011 — CPACA (art. 76: recursos de reposición, 5 días hábiles)
6. Resolución 196/2016 CCE — Matrices de indicadores financieros por sector
7. Ley 1882/2018 — Obligatoriedad Pliegos Tipo en infraestructura

PLAZOS LEGALES EXACTOS:
  • Observaciones al pliego: durante período publicación (mínimo 10 días hábiles)
    → Base: Decreto 1082/2015 art. 2.2.1.2.1.2.5
  • Respuesta a observaciones por entidad: dentro del mismo plazo o adenda
    → Base: Decreto 1082/2015 art. 2.2.1.2.1.2.6
  • Subsanaciones habilitantes: 3 días hábiles (mínima cuantía) a 5 días hábiles (licitación)
    → Base: Ley 1150/2007 art. 5, parágrafo 1
  • Recurso de reposición post-adjudicación: 5 días hábiles
    → Base: Ley 1437/2011 art. 76
  • Renovación RUP: máximo 31 marzo de cada año (cierre fiscal al 31 dic)
    → Base: Decreto 1082/2015 art. 2.2.1.1.2.1.1

SUBSANABILIDAD (Ley 1150/2007 art. 5, parágrafo 1 y 2):
  ✅ SUBSANABLE — documentos habilitantes que NO dan puntaje:
     RUT, cédula, cert. existencia y representación, diplomas, paz y salvos parafiscales,
     estados financieros (si no son factor de puntaje), garantías subsanables
  ❌ NO SUBSANABLE — líneas rojas absolutas:
     • Póliza de seriedad: si el pliego la exige con la oferta → rechazo sin subsanación
     • Oferta económica: errores numéricos que alteren el valor o falta de firma
     • Documentos ponderables: cert. industria nacional, personal discapacidad, ISO
     • Experiencia acreditada DESPUÉS del cierre del proceso
     • Propuesta técnica si es factor de calidad

PLIEGOS TIPO — OBLIGATORIEDAD (Ley 1882/2018 art. 4):
  • Infraestructura transporte: Pliegos Tipo CCE OBLIGATORIOS, no modificables
  • Infraestructura social (salud, educación, deporte, vivienda): Pliegos Tipo aplicables
  • Si entidad pide indicadores MAYORES a los de Pliegos Tipo → IRREGULARIDAD
    → Acción: presentar observación formal citando Ley 1882/2018 art. 4

PLIEGOS SASTRE — SEÑALES DE ALERTA:
  • Requisitos muy específicos que solo una empresa puede cumplir
  • Códigos UNSPSC combinados de forma inusual
  • Experiencia en número de contratos excesivamente alta
  • Plazos de publicación más cortos de lo legal → acción: observación inmediata

MIPYMES Y LIMITACIÓN (Ley 590/2000 art. 12, Decreto 1082/2015 art. 2.2.1.2.1.2.3):
  • Si existen ≥ 3 MiPymes capaces → proceso puede limitarse a MiPymes
  • Participación mínima en consorcio: ≥ 10% del contrato
  • Criterios diferenciales en habilitantes financieros

TRM Y PRECIO ECONÓMICO EN PLIEGOS TIPO (CCE):
  • El puntaje económico usa decimales de la TRM del día de adjudicación (factor azar)
  • Métodos: media aritmética, media geométrica, mediana, o combinación
  • Precio temerario: rechazo si oferta < umbral definido en pliego (generalmente 90% del presupuesto)

PUNTAJE POR INCLUSIÓN (hasta 30 puntos — verificar en cada pliego):
  • Personal con discapacidad: mínimo 1% de la planta propuesta → puntos adicionales
  • Emprendimiento mujeres: >50% capital accionario o directivos femeninos
  • Industria nacional: certificado de origen colombiano (ICONTEC o ONAC)
  • Programas ambientales: hasta 20 puntos extra según resolución CCE

CUANDO EMITAS CONCEPTO JURÍDICO: Cita siempre la norma y el artículo que respalda.
  • Si cumple: "Experiencia cumple según Decreto 1082/2015 art. 2.2.1.2.1.5.7"
  • Si no cumple: "No cumple RUP activo exigido por Ley 80/1993 art. 22"
  • Si falta documento: "Falta Certificado de Existencia (Subsanable — Ley 1150/2007 art. 5)"
===
"""

SKILL_ESTRATEGIA = """
=== ESTRATEGIA INTELIGENTE — LICITACIONES SECOP II ===

FILTRO GO / NO-GO (evaluar en orden, detener en primer NO):
1. ¿Objeto social empresa coincide con objeto del contrato? → Ley 80/1993 art. 22
2. ¿Precio unitario cubre costos tras descontar IVA 19%, retención 1-2%, costos operativos?
3. ¿Empresa cumple requisitos habilitantes? → si no cumple, evaluar consorcio
4. ¿El pliego usa Documentos Tipo? → si sí, verificar que entidad no alteró indicadores
5. ¿Hay tiempo real para preparar oferta completa? → mínimo 5 días hábiles efectivos
6. ¿La competencia esperada permite precio competitivo sin caer en temerario?

DIFERENCIACIÓN HABILITANTES vs PONDERABLES (prioridad de trabajo):
  ⚡ PONDERABLES primero (no subsanables, dan puntos):
     Cert. industria nacional, personal discapacidad, ISO/calidad, metodología detallada
  📋 HABILITANTES segundo (subsanables, solo permiten participar):
     RUT, cédulas, cert. existencia, estados financieros, paz y salvos

OBSERVACIONES AL PLIEGO — cuándo usar como arma:
  • Identificar requisito "sastre" → presentar observación citando irregularidad
  • Indicadores financieros superiores a Pliegos Tipo → exigir corrección (Ley 1882/2018)
  • Solicitar limitación a MiPymes si ≥ 3 MiPymes pueden cumplir
  • Pedir aclaración de alcance técnico para evitar ambigüedades post-adjudicación
  → Todas las observaciones: por escrito en SECOP II durante período de publicación

TIMING CRÍTICO:
  • T-72h cierre: verificar todos los documentos, enviar borrador interno para revisión
  • T-24h cierre: última revisión legal y de precios
  • Presentar oferta: MÍNIMO 2 horas antes del cierre (saturación de plataforma SECOP II)
  • Informe evaluación: leer en primeras 6h → decidir si observar (plazo usualmente 3-5 días)
  • Subsanaciones: responder < 24h aunque el plazo sea mayor

ESTRATEGIA DE PRECIO:
  • Pliegos Tipo con TRM: no se controla el método → enfocarse en propuesta técnica
  • Competencia alta (>5 proponentes): diferenciarse técnicamente, no solo en precio
  • Competencia baja (<3 proponentes): precio puede ser más conservador
  • Precio temerario: NUNCA ofertar < 90% del presupuesto oficial sin justificación técnica
===
"""
