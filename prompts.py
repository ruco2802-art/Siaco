# -*- coding: utf-8 -*-
"""
Constantes de skills para inyección en prompts de agentes IA.
Fuente canónica: .claude/skills/*.md (versionados en git, desplegados en Railway).
Fallback: constantes hardcoded — se usan si los .md no están disponibles en disco.
"""
from pathlib import Path

SMMLV_2026 = 1_750_905  # COP

_SKILLS_DIR = Path(__file__).parent / ".claude" / "skills"


def _cargar_skill(nombre_archivo: str, fallback: str) -> str:
    """Carga skill desde disco. Devuelve fallback si el archivo no existe o no es legible."""
    try:
        p = _SKILLS_DIR / nombre_archivo
        if p.is_file():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass
    return fallback


# ── Fallbacks hardcoded (resúmenes — el .md original tiene más contenido) ───────

_FALLBACK_FINANCIERO = f"""
=== MARCO FINANCIERO SAFE-L — CONTRATACIÓN PÚBLICA COLOMBIA (obligatorio aplicar) ===

VALORES DE REFERENCIA 2026:
• SMMLV 2026: ${SMMLV_2026:,} COP
• Mínima cuantía: < 28 SMMLV → < $49.025.340 COP
• Anticipo máximo legal: 50% (Ley 80/1993 art. 40, parágrafo — "su monto no
  podrá exceder del cincuenta por ciento (50%) del valor del respectivo contrato")

INDICADORES HABILITANTES (Decreto 1082/2015 art. 2.2.1.1.1.5.3 — define los
indicadores; las cámaras de comercio los verifican y certifican en el RUP):
  índice de liquidez · índice de endeudamiento · razón de cobertura de intereses
  rentabilidad del patrimonio · rentabilidad del activo
⚠ El art. 2.2.1.1.1.5.3 define QUÉ se mide, NO los umbrales. Los umbrales los
  fija la entidad en el pliego (art. 2.2.1.1.1.6.2: debe atender al riesgo, al
  valor del contrato y al análisis del sector, y "no debe limitarse a la
  aplicación mecánica de fórmulas financieras").
  Los valores de referencia siguientes NO tienen respaldo normativo. La
  "Resolución 196/2016 CCE" que se citaba NO EXISTE [no-citable]: el Manual
  oficial del CCE sobre requisitos habilitantes (CCE-EICP-MA-04 v3) no la
  menciona y remite a este mismo art. 2.2.1.1.1.5.3. Ninguna norma nacional
  fija estos umbrales: los fija la entidad, o el Documento Tipo de la
  modalidad. Úsalos como orientación y verifica SIEMPRE el umbral del pliego.
  (El Manual está en la biblioteca como DOCTRINA, no citable: orienta a las
  entidades pero no las vincula, así que no sirve de fundamento jurídico.)

IDL — Índice de Liquidez = Activo Corriente / Pasivo Corriente
  • Pliego Tipo infraestructura: IDL ≥ 1.0
  • IDL < 1.0 = ALERTA CRÍTICA — pasivos superan activos corrientes → rechazo automático
  • Sector transporte mayor cuantía: IDL ≥ 1.2

NDE — Índice de Endeudamiento = Pasivo Total / Activo Total
  • Pliego Tipo: NDE ≤ 0.80 (máximo aceptable)
  • Sector transporte contratos grandes: puede flexibilizarse hasta 0.85 si K residual cubre
  • Umbral del pliego concreto. No hay norma nacional que lo fije. [no-citable]

RCI — Razón de Cobertura de Intereses = EBIT / Gastos Financieros
  • RCI < 1.0 = ANORMAL Y MUY MALO → incapacidad de cubrir obligaciones financieras
  • RCI ≥ 1.5 = ACEPTABLE para licitaciones públicas
  • RCI ≥ 3.0 = BUENO — fortalece la oferta
  • MiPyme: RCI puede ser N/A si no tiene deuda con intereses

CAPACIDAD RESIDUAL K (Decreto 1082/2015 art. 2.2.1.1.1.6.4 — documentos para
acreditarla y factores: Experiencia, Capacidad Financiera, Capacidad Técnica,
Capacidad de Organización y saldos de contratos en ejecución. La metodología
de cálculo la define Colombia Compra Eficiente):
⚠ La fórmula siguiente es de dominio, no del decreto. La metodología oficial
  la define Colombia Compra Eficiente en su Manual, que no es norma. [no-citable]
  K = (0.8 × Patrimonio Líquido) − Σ(valor_contratos_en_ejecución × %_pendiente_de_ejecutar)
  • K debe ser ≥ valor del contrato a licitar
  • Si K insuficiente → recomendar consorcio para sumar patrimonios
  • Nota: el anticipo reduce el capital de trabajo demandado → recalcular si hay anticipo

CRITERIOS MIPYME (regla de dominio — sin cita normativa verificable):
  • IDL, RCI y rentabilidad se flexibilizan si proponente es MiPyme registrada
  • Participación mínima en consorcio para aportar: ≥ 10% del valor
  • Experiencia: hasta 2 contratos adicionales en RUP (máximo 7 contratos acreditables)

CUANDO EMITAS CONCEPTO: Cita siempre el artículo o norma específica que respalda la evaluación.
  • Si cumple: "Cumple el índice de liquidez exigido en el pliego. El indicador
    está definido en el Decreto 1082/2015 art. 2.2.1.1.1.5.3"
  • Si no cumple: "No cumple el índice de endeudamiento: X supera el máximo
    exigido en el pliego" — cita el UMBRAL DEL PLIEGO, no una resolución que
    no está en la biblioteca
===
"""

_FALLBACK_JURIDICO = """
=== MARCO JURÍDICO — CONTRATACIÓN PÚBLICA COLOMBIA (obligatorio aplicar) ===

JERARQUÍA NORMATIVA APLICABLE:
1. Ley 80/1993 — Estatuto General de Contratación Pública (base principal)
2. Ley 1150/2007 — Eficiencia y transparencia (art. 5: selección objetiva y
   subsanabilidad; art. 6: RUP; art. 2 parágrafo 7, adicionado por la Ley
   1882/2018 art. 4: documentos tipo obligatorios; art. 4: distribución de riesgos)
3. Decreto 1082/2015 — DUR Contratación (art. 2.2.1.1.2.1.4: plazo de
   observaciones al proyecto de pliego; art. 2.2.1.1.1.5.3: indicadores
   habilitantes; art. 2.2.1.1.1.6.2: cómo los determina la entidad;
   art. 2.2.1.1.1.7.1: publicidad en el SECOP)
4. [no-citable] Ley 1474/2011 — Estatuto Anticorrupción (art. 91: obligación de constituir
   fiducia o patrimonio autónomo para el MANEJO del anticipo — NO fija el tope;
   el tope del 50% está en Ley 80/1993 art. 40, parágrafo)
5. [norma no disponible en la biblioteca: Ley 1437/2011 — CPACA]
   El recurso de reposición contra la adjudicación no tiene respaldo citable.
6. La "Resolución 196/2016 CCE" NO EXISTE [no-citable] — cita inventada. Los
   indicadores están en el Decreto 1082 art. 2.2.1.1.1.5.3; los umbrales los
   fija la entidad o el Documento Tipo. [no-citable]
7. Ley 1882/2018 — su art. 4 adicionó el parágrafo 7 al art. 2 de la Ley
   1150/2007 (documentos tipo); su art. 5 modificó el art. 5 de la Ley 1150
   (subsanabilidad). Cita la Ley 1150 con el parágrafo, no la Ley 1882 sola.

PLAZOS LEGALES EXACTOS:
  • Observaciones al PROYECTO de pliego — el plazo depende de la modalidad:
      · licitación pública ................ 10 días hábiles
      · selección abreviada .............. 5 días hábiles
      · concurso de méritos .............. 5 días hábiles
    → Base: Decreto 1082/2015 art. 2.2.1.1.2.1.4
    ⚠ Este artículo regula el PROYECTO de pliego, no el pliego definitivo.
      Nunca afirmes "10 días hábiles" sin decir la modalidad: para todo lo que
      no sea licitación pública, el plazo es 5.
  • Respuesta a observaciones por la entidad: [cita pendiente de verificar]
    Ningún artículo del Decreto 1082 en la biblioteca fija este plazo.
  • Subsanación de requisitos habilitantes: NO hay un número de días fijado
    por ley. El plazo lo fija la entidad en el pliego. El límite legal es hasta
    el término de traslado del informe de evaluación que corresponda a cada
    modalidad, salvo mínima cuantía y subasta.
    → Base: Ley 1150/2007 art. 5, parágrafo 1 (modificado por Ley 1882/2018 art. 5)
    ⚠ NO afirmes "3 días hábiles": ese plazo no existe en ninguna norma.
  • Recurso de reposición post-adjudicación: [norma no disponible en la
    biblioteca: Ley 1437/2011 art. 76 — CPACA]. No lo cites como fundamento. [no-citable]
  • Renovación del RUP: a más tardar el QUINTO DÍA HÁBIL DEL MES DE ABRIL de
    cada año; de lo contrario cesan los efectos del RUP.
    → Base: Decreto 1082/2015 art. 2.2.1.1.1.5.1
    ⚠ No es el 31 de marzo.

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

DOCUMENTOS TIPO — OBLIGATORIEDAD (Ley 1150/2007 art. 2, parágrafo 7,
adicionado por la Ley 1882/2018 art. 4):
  • Infraestructura transporte: Pliegos Tipo CCE OBLIGATORIOS, no modificables
  • Infraestructura social (salud, educación, deporte, vivienda): Pliegos Tipo aplicables
  • Si entidad pide indicadores MAYORES a los de Pliegos Tipo → IRREGULARIDAD
    → Acción: presentar observación formal citando Ley 1150/2007 art. 2, parágrafo 7

PLIEGOS SASTRE — SEÑALES DE ALERTA:
  • Requisitos muy específicos que solo una empresa puede cumplir
  • Códigos UNSPSC combinados de forma inusual
  • Experiencia en número de contratos excesivamente alta
  • Plazos de publicación más cortos de lo legal → acción: observación inmediata

MIPYMES Y LIMITACIÓN (regla de dominio — [cita pendiente de verificar]:
Ley 590/2000 art. 12 no está en la biblioteca [no-citable] y el art. 2.2.1.2.1.2.3 del
Decreto 1082 no regula esta materia):
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
  • Si cumple: "La experiencia acreditada en el RUP cumple lo exigido. Los
    requisitos habilitantes que certifica el RUP están en el Decreto
    1082/2015 art. 2.2.1.1.1.5.3"
  • Si no cumple: "No cumple la inscripción vigente en el RUP exigida por la
    Ley 1150/2007 art. 6"
    ⚠ NUNCA cites el art. 22 de la Ley 80/1993: fue DEROGADO por el art. 32
      de la Ley 1150/2007.
  • Si falta documento: "Falta Certificado de Existencia (Subsanable — Ley 1150/2007 art. 5)"
===
"""

_FALLBACK_ESTRATEGIA = """
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

# ── Carga desde disco (fuente canónica) con fallback ─────────────────────────

SKILL_FINANCIERO: str = _cargar_skill("skill_financiera_SAFE_L.md", _FALLBACK_FINANCIERO)
SKILL_JURIDICO: str   = _cargar_skill("skill_juridica_licitaciones.md", _FALLBACK_JURIDICO)
SKILL_ESTRATEGIA: str = _cargar_skill("skill_licitaciones_estrategia.md", _FALLBACK_ESTRATEGIA)
SKILL_ANTI_RECHAZO: str = _cargar_skill("skill_anti_rechazo.md", "")
