# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

SIACO tiene **dos audiencias con el mismo peso** (confirmado con el fundador):

1. **Equipo interno (agencia).** Fundador (tecnología), abogado y contador, ambos con
   experiencia en sector público. Operan SIACO para detectar, analizar y decidir sobre
   procesos de contratación en nombre de los clientes. Situación de uso: sesiones de
   trabajo enfocadas, con criterio experto en el loop. Su trabajo (job): reducir el ciclo
   de detección + análisis + decisión a ~2 horas por cliente.

2. **Clientes contratistas (MiPymes).** Empresas del sur de Colombia que aspiran a
   contratos públicos, con poca o ninguna experiencia en la jerga del sector. Entran con
   su login (tienen cuenta y plan) a consultar sus procesos, análisis y resultados.
   Situación de uso: revisión ocasional de "¿a qué me puedo presentar y cumplo?".

Además existe una **audiencia de captación** en la superficie pública (landing + flujo de
solicitud de demo): prospectos que aún no son clientes y evalúan si contratar la agencia.

## Product Purpose

SIACO es una plataforma de inteligencia de contratación pública sobre **SECOP II
(Colombia)**. Su función central es analizar pliegos de condiciones y determinar si una
empresa cumple los **requisitos habilitantes** (jurídicos, financieros y técnicos) para
presentarse a un proceso, y apoyar la construcción de la oferta.

El éxito se mide en resultados de negocio del cliente: procesos detectados a tiempo,
análisis correctos de habilitación (sin omitir requisitos ni inventarlos), y contratos
efectivamente adjudicados — no en métricas de uso de software.

## Positioning

**Modelo de agencia, no SaaS.** El mercado colombiano tiene 12+ competidores en modelo
SaaS (Fromus, LicitarUS, LicitIA, Highteck, Licitum, PresuCosto, entre otros) a
~$199.000 COP/mes, concentrados en ciudades principales. SIACO no compite como producto:
es la **herramienta interna** que apalanca el trabajo de un equipo experto.

Diferenciadores que un competidor no puede copiar fácilmente:

- **Foco geográfico en el sur de Colombia** (Caquetá, Huila, Tolima), zona desatendida
  por las plataformas grandes.
- **Humano experto en el loop por diseño** (abogado + contador con experiencia pública),
  no como limitación temporal. Baja el umbral de calidad exigido al software y sube la
  confianza del cliente.
- **Modelo de ingresos alineado al resultado:** fee de acompañamiento descontable del
  porcentaje de éxito sobre contratos adjudicados.

## Operating Context

- **Fuente de datos:** API de SECOP II; documentos = pliegos de condiciones (PDF, a
  menudo escaneados), adendas y anexos (matrices de experiencia e indicadores).
- **Marco normativo:** biblioteca de Colombia Compra Eficiente (resoluciones, matrices).
  El pliego manda sobre la normativa; la norma solo sirve para contrastar, nunca para
  completar huecos.
- **Flujo del equipo:** detección de procesos → análisis de habilitación → análisis de
  precios/oferta → decisión, con el objetivo de ~2 h por cliente.
- **Roles en el sistema:** `admin` (el equipo, crea y gestiona clientes) y `cliente`
  (acceso a sus propios procesos, con plan asociado).

## Capabilities and Constraints

**Módulos existentes:**

- Búsqueda de contratos (filtra SECOP II por perfil: índices financieros, UNSPSC, RUP,
  capacidad de contratación).
- Análisis de pliegos (extracción de requisitos habilitantes + contraste normativo +
  observaciones al pliego).
- Seguimiento / expedientes de procesos de interés.
- Análisis de precios unitarios (APU): costos, mano de obra, flujo de caja, precio mínimo
  y máximo de oferta.
- Análisis de competidores: histórico de adjudicaciones por entidad + modelo Monte Carlo
  para estimar el precio con mayor probabilidad de adjudicación.
- Generación de borradores: ofertas, observaciones al pliego y documentos para MiPymes
  sin experiencia en la jerga del sector.

**Stack (restricción técnica del incumbente):** Python 3.13, FastAPI (`main.py` +
`routers/`), Anthropic Claude Sonnet, sentence-transformers, PyMuPDF, Tesseract OCR,
fpdf2. Frontend en HTML/CSS/JS estático servido desde `static/` (`landing.html`,
`index.html`, `app.js`, `style.css`). API bajo prefijo `/api`.

**Estado de calidad (en curso, no oculto al usuario):** el reto abierto del motor es la
**cobertura** de requisitos, no la alucinación (falsos positivos ya en cero). El diseño
de UI debe poder comunicar honestamente el estado del análisis (completo / degradado /
fallido), no aparentar completitud. Ver `ESTADO_PIPELINE.md` y `Documentos SIACO/
SIACO_contexto.md`.

**Undecididos de producto (no inventar):** tamaño típico de contrato y tasa de
adjudicación anual del segmento; de esos dos números depende la viabilidad económica.

## Brand Commitments

- **Nombre fijo: "SIACO"** (Sistema Inteligente de Análisis de Contratación). Es lo único
  de la identidad que el fundador declaró fijo.
- **Identidad visual abierta a replantearse.** La implementación actual usa tema oscuro
  (fondo `#0A0A0A`, acento verde lima `#C6F24E`) con Inter + JetBrains Mono; se registra
  como evidencia del estado actual, **no** como restricción vinculante. Las decisiones de
  mundo visual se toman en new-work / DESIGN.md, no aquí.
- **Registro de voz (derivado de la función):** el producto traduce la jerga de la
  contratación pública a lenguaje claro para MiPymes; la comunicación debe ser precisa y
  auditable, sin prometer resultados que el sistema no puede garantizar.

## Evidence on Hand

- **Documentos de contexto reales:** `README.md`, `ESTADO_PIPELINE.md`, y
  `C:\Users\aleja\Desktop\Documentos SIACO\SIACO_contexto.md` (fuente más actual).
- **Evaluación contra ground truth a ciegas** (5 pliegos, SIACO vs. NotebookLM como línea
  base): documenta el reto de cobertura y cero falsos positivos tras correcciones. Datos
  en `resultados_evaluacion/` y `Evaluacion_SIACO_vs_NotebookLM.xlsx`.
- **Material comercial:** landing pública, flujo `/api/solicitud-demo`, correos de
  prospección (`Documentos SIACO/correos_prospeccion_siaco_final.xlsx`) y documentos para
  clientes (`SIACO_Formulario_Cliente`, `SIACO_Guia_RUP`, `SIACO_Minima_Cuantia`).
- **Clientes de referencia en el repo:** perfiles de ejemplo (`clientes/cliente_001`,
  `cliente_002`, `cliente_003`) por sector (HVAC, obras, transporte).
- **Ausencias a respetar (no fabricar):** testimonios, número de clientes reales,
  contratos ya ganados, benchmarks de mercado o precios de la agencia no confirmados. La
  validación de negocio con contratistas del sur está **pendiente**.

## Product Principles

1. **El pliego manda sobre la normativa.** Un campo vacío es correcto; uno inventado es un
   error grave. Aplica también a la UI: no rellenar ni aparentar datos que no existen.
   **Regla operativa [I10]: ningún campo que sostenga una afirmación puede tener valor
   por defecto. La ausencia se declara; nunca se rellena.** Los tres errores más graves
   encontrados —cita sin norma que se inventa, umbral sin unidad que se pone en «meses»,
   valor sin umbral que se declara CUMPLE— son el mismo patrón: ante la falta de un dato,
   el código produce una respuesta en vez de decir que no sabe. Ver `ESTADO_PIPELINE.md`
   → I10 para cómo se aplica.
2. **Ningún fallo silencioso.** Si el análisis se degrada, la interfaz debe decirlo — el
   aviso llega a la pantalla del usuario, no solo a los logs.
3. **El experto en el loop es una fortaleza, no un parche.** El producto potencia el
   criterio humano del equipo; no lo reemplaza ni lo esconde.
4. **Distinguir "no está" de "no lo revisé".** La confianza del cliente se gana mostrando
   con honestidad la cobertura y los límites de cada análisis.
5. **Claridad sobre jerga.** El valor para MiPymes está en traducir la complejidad de la
   contratación pública a decisiones entendibles.

## Audience, Purpose and Constraint

Precisado el 2026-09-23. No reemplaza a *Users* ni a *Product Purpose*: los cierra
en una frase cada uno, para que una decisión de diseño pueda resolverse sin leer
el documento entero.

**PÚBLICO.** Contratistas PYME colombianos y sus abogados. Modelo de agencia: **el
analista de SIACO firma el informe ante el cliente**. No es un producto que el
cliente opera solo; es el trabajo de un equipo experto, apalancado por software.

**PROPÓSITO.** Decidir si una empresa **puede** y **le conviene** ofertar. Las dos
mitades importan, y **hoy sólo la primera está construida**:

- **«puede»** = habilitación: requisitos, umbrales, causales de rechazo. Es lo que
  el pipeline resuelve, con cita y numeral.
- **«le conviene»** = precio, competencia y capacidad residual. Existen piezas
  sueltas —APU, Monte Carlo de competidores, calculadora de flujo de caja— pero
  **el score de competitividad no está construido**.

Consecuencia para el diseño: ni la interfaz ni el informe pueden presentar un
veredicto de conveniencia. Un «CONDICIONAL» que el usuario lea como «me conviene
a medias» estaría prometiendo un cálculo que no existe. Mientras el score no
exista, el producto responde «¿puede ofertar?» y deja la conveniencia al criterio
del analista.

**RESTRICCIÓN CENTRAL.** Cada afirmación debe poder defenderse con **numeral y
cita textual del pliego**. Es la restricción que gobierna las demás: si una
pantalla o un informe presenta algo que no se puede sostener con una cita, el
diseño está mal, por bien que se vea.

**TONO.** Rigor y claridad. Herramienta profesional, no producto de consumo. Se
traduce la jerga de la contratación pública sin banalizarla.

**ANTI-REFERENCIAS.** Lo que SIACO no es, dicho para poder rechazar propuestas
concretas:

- dashboards SaaS genéricos —donde vive toda la competencia
- gradientes
- iconos decorativos
- mascotas o personajes
- métricas de vanidad: el éxito se mide en contratos adjudicados, no en uso

## Surfaces

Tres superficies, **fondos distintos por decisión deliberada** (2026-09-23). La
identidad viaja en tipografía, jerarquía, tono, logotipo y el *rol* del acento;
el fondo y la densidad cambian con el trabajo de cada una. Ver
`DESIGN.md → Surfaces` y *The Travelling-Accent Rule*.

| superficie | trabajo | fondo | estado |
|---|---|---|---|
| **LANDING** | captación de prospectos | papel manila | cerrada, no se toca |
| **APP** | operar 2 h por cliente | oscuro | se le añaden tarjetas |
| **DOCUMENTOS** | firmarse ante una entidad | blanco de impresión | se construye |

El tema oscuro de la app **no es deuda de diseño**: está justificado por uso —el
analista lee tablas densas durante horas— y por el modelo de agencia, en el que
la app la opera el equipo, no el cliente. Lo que el cliente recibe es el
documento. Migrar la app al tema claro sólo tendría sentido si los clientes
pasaran a usarla directamente; queda registrado con esa condición de disparo en
`ESTADO_PIPELINE.md` (D23), no como pendiente abierto.

## Accessibility & Inclusion

Requisito específico del producto: **lenguaje claro en español** para usuarios MiPymes sin
experiencia en la jerga del sector público. La interfaz debe ser comprensible para
usuarios no expertos y considerar contextos de menor familiaridad digital propios del
segmento (sur de Colombia). No se ha establecido un estándar formal de accesibilidad
(p. ej. WCAG nivel objetivo); queda como decisión abierta.
