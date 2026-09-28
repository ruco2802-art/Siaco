---
name: SIACO
description: Inteligencia de contratación pública, en el mundo del expediente habilitado
colors:
  paper: "#ECE3D0"
  paper-hi: "#F4EDDD"
  paper-lo: "#E3D8C0"
  kraft: "#D9C6A2"
  kraft-deep: "#C7B084"
  ink: "#211C15"
  ink-2: "#5E5647"
  ink-3: "#6B5F45"
  foliation-red: "#B23324"
  foliation-red-deep: "#8C2519"
  official-navy: "#1E3A5F"
  official-navy-2: "#2E547E"
  navy-deep: "#16304F"
  navy-panel: "#1F3E64"
  navy-edge: "#33567F"
  on-navy: "#E9E2D3"
  on-navy-2: "#BFCBDA"
  accent-gold: "#F5C95C"
  red-field: "#A82E20"
  on-red: "#FBF3E4"
  seal-gold: "#9C7A2E"
  rule-line: "#C6B187"
  rule-line-soft: "#D8CAA9"
typography:
  display:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "clamp(2.5rem, 5.4vw, 4.1rem)"
    fontWeight: 900
    lineHeight: 1.04
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "clamp(1.9rem, 4.3vw, 3.1rem)"
    fontWeight: 900
    lineHeight: 1.04
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "1.28rem"
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  body:
    fontFamily: "'Public Sans', system-ui, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 400
    lineHeight: 1.62
    letterSpacing: "normal"
  label:
    fontFamily: "'JetBrains Mono', ui-monospace, monospace"
    fontSize: "0.72rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.14em"
rounded:
  xs: "2px"
  sm: "3px"
  md: "6px"
  lg: "8px"
spacing:
  xs: "8px"
  sm: "14px"
  md: "24px"
  lg: "40px"
  section: "clamp(64px, 9vw, 120px)"
  edge: "clamp(18px, 5.5vw, 84px)"
components:
  button-primary:
    backgroundColor: "{colors.foliation-red}"
    textColor: "{colors.paper-hi}"
    rounded: "{rounded.sm}"
    padding: "0.85em 1.5em"
  button-primary-hover:
    backgroundColor: "{colors.foliation-red-deep}"
    textColor: "{colors.paper-hi}"
  button-solid:
    backgroundColor: "{colors.official-navy}"
    textColor: "{colors.paper-hi}"
    rounded: "{rounded.sm}"
    padding: "0.85em 1.5em"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0.85em 1.5em"
  field:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "11px 13px"
  card-slip:
    backgroundColor: "{colors.paper-hi}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
    padding: "26px 24px 24px"
  fee-card:
    backgroundColor: "{colors.navy-panel}"
    textColor: "{colors.on-navy}"
    rounded: "{rounded.lg}"
    padding: "32px"
---

# Design System: SIACO

## Overview

**Creative North Star: "El Expediente Habilitado"**

SIACO es un fólder de licitación pública que se arma solo. La interfaz toma el caos de un pliego de 200 páginas y lo devuelve como un expediente ordenado: foliado, con pestañas, verificado y —cuando la empresa califica— estampado con un sello rojo que dice HABILITADO. Todo el sistema visual vive en el mundo de la oficialidad administrativa colombiana: papel manila, tinta de foliación en rojo, sellos de caucho, formularios reglados y numeración de folios. No es la estética SaaS oscura con acento neón (de donde venía la versión anterior, y donde vive toda la competencia), ni la landing corporativa azul-blanco intercambiable, ni el papel crema con serifa editorial. Es un documento oficial que respira confianza porque *parece* el trámite que el cliente ya conoce, solo que resuelto.

La densidad es de documento, no de dashboard: líneas regladas, márgenes marcados, datos en monoespaciada tabular. El color se compromete a escala de página: campos enteros de manila durante el recorrido y dos campos saturados al cierre (azul para el modelo, rojo para la acción), en vez de acentos dispersos sobre un fondo neutro. La personalidad es seria pero cálida: la autoridad de un sello notarial sin la frialdad de una plataforma.

**Key Characteristics:**
- Fondo de papel manila cálido, no blanco ni oscuro; la luz es de escritorio, de día.
- Rojo de foliación reservado para sellos, veredictos y la acción principal.
- Iconografía dibujada a mano en trazo fino y consistente; cero emojis.
- Numeración de folios y etiquetas en monoespaciada como dato real, no como disfraz "técnico".
- Un solo momento de motion con autoría: el sello HABILITADO que se estampa.
- Dos campos de color al cierre: azul para el modelo de negocio, rojo para la acción.

## Colors

Paleta de documento oficial cálido: manila como terreno, rojo de foliación como voz de autoridad, azul oficial como contrapunto de confianza.

### Primary
- **Rojo de Foliación** (#B23324): la voz de autoridad del sistema. Sellos (HABILITADO, RECIBIDO), veredictos, la acción principal (CTA) y el acento del margen reglado. Su versión profunda (#8C2519) es solo para hover.

### Secondary
- **Azul Oficial** (#1E3A5F): confianza institucional. Iconos dibujados, enlaces y la columna "SIACO" de la matriz comparativa. Su versión clara (#2E547E) es para hover.

### Campos de color (secciones a pantalla completa)
La página cierra con **dos** campos de color consecutivos, cada uno con un trabajo distinto, y ambos con superficies **sólidas** (nunca lavados translúcidos, que ensucian el campo):
- **Campo Azul** (#16304F) para el modelo de honorarios: paneles sólidos (#1F3E64), reglas (#33567F), texto (#E9E2D3) y secundario (#BFCBDA); títulos y cifras en blanco puro, cifras de comisión en dorado (#F5C95C). El azul le da al modelo de negocio la jerarquía que necesita para no pasar desapercibido.
- **Campo Rojo** (#A82E20) para el llamado a la acción: texto blanco puro, secundario (#FBF3E4) y botón blanco con sombra cálida.

### Neutral
- **Papel Manila** (#ECE3D0): el terreno de casi toda la página, con grano sutil.
- **Papel Claro** (#F4EDDD): documentos, tarjetas y paneles que se levantan del fondo.
- **Papel Hundido** (#E3D8C0): secciones alternas (problema, herramientas) para marcar ritmo.
- **Kraft** (#D9C6A2) y **Kraft Profundo** (#C7B084): pestañas, cabeceras de tarjeta y bordes del fólder.
- **Tinta** (#211C15): texto principal. **Tinta 2** (#5E5647) secundario, **Tinta 3** (#6B5F45) terciario/etiquetas —matizadas del papel, nunca gris puro.
- **Línea Reglada** (#C6B187 / suave #D8CAA9): filas de matriz, márgenes y divisiones punteadas.

### Named Rules
**The Foliation-Red Rule.** El rojo de foliación no es decoración: aparece solo donde hay un acto oficial —un sello, un veredicto, la acción principal o el margen del documento. Si el rojo no marca autoridad, sobra.

**The Warm-Ground Rule.** El fondo es papel bajo luz de día. Ni blanco clínico ni oscuro de dashboard: el terreno siempre es un tono de manila.

**The Earned-Field Rule.** Un campo de color a pantalla completa se reserva para contenido que debe entenderse sí o sí: el modelo de honorarios (azul) y el llamado a la acción (rojo). Cada campo adicional le resta golpe al siguiente, así que ninguna otra sección puede reclamar uno.

**The Solid-Field Rule.** Sobre un campo de color (azul o rojo), las superficies son sólidas y el texto principal es blanco puro. Nada de `rgba()` translúcido para paneles ni para texto: enturbia el campo y baja el contraste.

## Typography

**Display Font:** Archivo (con system-ui, sans-serif)
**Body Font:** Public Sans (con system-ui, sans-serif)
**Label/Mono Font:** JetBrains Mono (con ui-monospace, monospace)

**Character:** Archivo aporta la autoridad de un grotesco oficial —titulares densos y condensados, como un rótulo administrativo. Public Sans (linaje de tipografía de gobierno) mantiene el cuerpo legible y sin pretensiones. JetBrains Mono da a los folios, códigos y cifras el carácter de dato mecanografiado. El emparejamiento evita deliberadamente la serifa editorial, que arrastraría el mundo hacia lo bibliográfico.

### Hierarchy
- **Display** (900, clamp(2.5rem, 5.4vw, 4.1rem), 1.04): el titular del hero, como título de carátula del expediente.
- **Headline** (900, clamp(1.9rem, 4.3vw, 3.1rem), 1.04): títulos de sección; `em` va en rojo de foliación.
- **Title** (800, 1.28rem, 1.2): pasos, herramientas, perfiles.
- **Body** (400, 1.05rem, 1.62): párrafos; medida ≤ 62ch.
- **Label** (500, 0.72rem, +0.14em, MAYÚSCULAS): metadatos, folios, pestañas y etiquetas de campo en monoespaciada.

### Named Rules
**The Foliation-Number Rule.** La monoespaciada se usa para folios, códigos, fechas e indicadores —dato o medida real— nunca como cosmética "técnica" sobre texto corriente.

## Layout

Ancho máximo de contenido 1180px, con márgenes fluidos `clamp(18px, 5.5vw, 84px)`. Ritmo vertical por sección `clamp(64px, 9vw, 120px)`. El hero es una rejilla de dos columnas (texto + dossier) que colapsa a una sola bajo 880px. Las rejillas de tres (problema, proceso) y de dos (perfiles) colapsan a una columna bajo 760px. La cabecera fija de 66px oculta las pestañas de navegación bajo 900px y el enlace de sesión bajo 560px, dejando siempre visible la marca y la acción principal. Regla de espaciado: grupos apretados, separación generosa, y más aire encima de un título que debajo.

## Elevation & Depth

Sistema mayormente plano con levantamientos suaves y cálidos: los elementos son hojas de papel sobre un escritorio, no tarjetas flotantes de vidrio. Toda sombra lleva desplazamiento y desenfoque en tono cálido (nunca halo de cero desplazamiento). La profundidad también se logra por capas tonales de papel (hundido → base → claro) y por bordes reglados, no solo por sombra.

### Shadow Vocabulary
- **Levantamiento** (`box-shadow: 0 2px 4px rgba(60,44,20,.10), 0 14px 34px rgba(60,44,20,.16)`): el fólder del dossier y elementos hover destacados.
- **Levantamiento leve** (`box-shadow: 0 1px 2px rgba(60,44,20,.10), 0 6px 16px rgba(60,44,20,.12)`): tarjetas, notas y botones en reposo.

### Named Rules
**The Warm-Shadow Rule.** Las sombras se tiñen de marrón cálido (`rgba(60,44,20,…)`), nunca de negro puro: son la sombra del papel bajo lámpara.

## Shapes

Esquinas pequeñas y administrativas: 2–3px en botones, campos, notas y sellos; 6px en tarjetas y la matriz; 8px en el fólder y las tarjetas de honorarios. El fólder tiene una esquina superior izquierda apenas mayor (6px) para insinuar la pestaña. Los sellos son rectángulos de borde grueso (2–3.5px) ligeramente rotados, con un anillo interior fino. El lenguaje de forma es reglado y recto —líneas continuas y punteadas— antes que curvo.

## Components

### Buttons
- **Shape:** esquinas rectas (3px), tipografía Archivo 800.
- **Primary (sello rojo):** fondo rojo de foliación (#B23324), texto papel; sombra leve. Es la acción "oficial".
- **Solid (azul):** fondo azul oficial (#1E3A5F), texto papel; para acciones secundarias de peso (nav "Solicitar demo").
- **Ghost:** transparente con borde de tinta 2px; al hover invierte a fondo tinta / texto papel.
- **Hover / Focus:** elevación de −2px y sombra al hover; foco visible con anillo azul oficial de 2.5px y offset.

### Cards / Containers
- **Notas de problema (slips):** papel claro, esquina 2px, sombra leve, borde línea suave; encabezadas por un "sello de rechazo" rojo rotado (−3°).
- **Fólder del dossier:** kraft con pestaña "EXPEDIENTE"; dentro, un "documento" en papel claro con margen reglado rojo y la matriz de habilitación.
- **Tarjetas de honorarios:** sobre el campo azul, paneles sólidos (#1F3E64) con borde de regla; cifra grande en Archivo blanco, tramos de comisión en tabla con foliación dorada y numerales tabulares.
- **Tira "cómo se cobra":** tres pasos numerados (mientras trabajamos / si gana / si no gana) sobre el campo azul, que explicitan el modelo de agencia antes de mostrar las cifras.
- **Internal Padding:** 26–30px.

### Inputs / Fields
- **Style:** fondo papel, borde línea reglada 1.5px, esquina 3px; etiqueta en monoespaciada mayúscula.
- **Focus:** borde azul oficial + halo `0 0 0 3px rgba(30,58,95,.14)`.

### Navigation
- Cabecera fija translúcida con blur; marca = sello circular SIACO + nombre. Pestañas de sección como lengüetas (borde inferior al hover). Acción principal como botón sello rojo. Al hacer scroll gana sombra y el borde vira a kraft profundo.

### Matriz comparativa (signature)
- Tabla reglada dentro de marco de tinta; cabeceras en Archivo mayúscula; la columna SIACO va con cabecera azul oficial sólida y celdas con lavado azul. Cumple = check azul, no cumple = cruz tinta terciaria.

### Sello / Estampa (signature)
- Rótulo Archivo 900 en rojo (o azul), borde grueso 3–3.5px, esquina 8px, rotado ~−9°, con subtítulo en monoespaciada y un anillo interior fino. Es el veredicto del sistema; el HABILITADO del hero es el único elemento con animación de "estampado", y es **re-activable** (clic o Enter) y enfocable por teclado.

### Gramática de movimiento

El movimiento pertenece al mundo del expediente: hojas que llegan, márgenes que se marcan, cifras que se liquidan y un sello que cae. Nunca efectos sueltos.

- **Estampado** (`cubic-bezier(.2,.9,.25,1)`, 550ms): el sello HABILITADO cae desde arriba con desenfoque y rebota una vez. Es el único momento espectacular de la página; al terminar libera el `transform` para que el hover responda.
- **Revelado escalonado** (`cubic-bezier(.16,1,.3,1)`, 700ms): las secciones entran desde abajo. Dentro de un grupo (notas, pasos, índice, tramos) cada elemento se retrasa 60–100ms, como hojas que se apilan.
- **Avance de lectura:** una regla de foliación roja de 2px bajo la barra de navegación crece con el scroll.
- **Liquidación de cifra:** la cuota mensual cuenta hasta su valor con ease-out cúbico al entrar en pantalla.
- **Respuesta al cursor:** el índice de herramientas marca un margen rojo de 3px y desplaza la fila; el botón principal se "entinta" desde el borde izquierdo; las notas se levantan y giran levemente; las pestañas de paso bajan 3px.
- **Regla de accesibilidad:** todo el contenido es visible sin JS, y `prefers-reduced-motion: reduce` desactiva la clase de animación por completo.

## Do's and Don'ts

### Do:
- **Do** mantener el fondo en un tono de papel manila (#ECE3D0 y familia); la luz es de escritorio, de día.
- **Do** reservar el rojo de foliación (#B23324) para sellos, veredictos, margen del documento y la acción principal.
- **Do** usar la monoespaciada para folios, códigos, fechas e indicadores reales.
- **Do** dibujar los iconos en SVG, trazo fino consistente (~1.7px), en azul oficial o tinta.
- **Do** comprometer el color a escala de campo: la sección "Modelo" es un bloque azul entero, no un acento.
- **Do** limitar el motion a un momento con autoría (el sello) y revelados sobrios; contenido visible sin JS.
- **Do** escalonar la entrada dentro de un grupo (60–100ms por elemento), como hojas que se apilan.
- **Do** usar superficies sólidas y texto blanco puro sobre los campos de color (azul #16304F, rojo #A82E20).

### Don't:
- **Don't** volver a la estética SaaS oscura con acento neón, ni al azul-blanco corporativo intercambiable, ni al crema + serifa editorial.
- **Don't** usar emojis como iconos.
- **Don't** poner "eyebrows"/kickers sueltos sobre los títulos (la barra de folio sí es información: numera la sección).
- **Don't** usar tinta terciaria por debajo de #6B5F45 para texto pequeño (rompe el contraste AA sobre papel).
- **Don't** usar serifa de display ni sombras negras de cero desplazamiento.
- **Don't** apoyar tarjetas iguales de icono+título+texto como estructura de página; preferir índices reglados y pestañas del expediente.
- **Don't** usar paneles o texto en `rgba()` translúcido sobre un campo de color: ensucia el campo y baja el contraste.
- **Don't** repartir efectos de hover sueltos sin gramática; cada respuesta al cursor imita un gesto del expediente (marcar margen, entintar, levantar hoja).

---

## Surfaces: una identidad, tres soportes

SIACO se ve en tres sitios y **no comparten fondo a propósito**. Un banco no usa
el mismo fondo en su app que en sus estados de cuenta impresos, y nadie duda de
que es el mismo banco.

| | LANDING | APP | DOCUMENTOS |
|---|---|---|---|
| función | vender la agencia | operar dos horas seguidas | firmarse ante una entidad |
| quién lo ve | prospecto | analista de SIACO | cliente y entidad contratante |
| fondo | papel manila `#ECE3D0` | oscuro `#0A0A0A` | blanco de impresión |
| densidad | editorial, aireada | alta, tablas densas | de documento oficial |
| acento | rojo foliación `#B23324` | lima `#C6F24E` | tinta + rojo foliación |
| estado | **no se toca** | sólo se añaden tarjetas | se construye ahora |

**Lo que viaja entre las tres:**

- **Tipografía.** Archivo para titulares, Public Sans para cuerpo, JetBrains Mono
  para dato tabular. Sin excepciones.
- **Jerarquía y ritmo.** Cómo se titula, cuánto aire va encima de un título frente
  a debajo, la medida de lectura de 62ch o menos.
- **Tono.** Preciso y auditable, sin prometer lo que el sistema no garantiza.
- **Logotipo** y su tratamiento.
- **El ROL del acento**, no su valor hexadecimal (ver la regla siguiente).

### The Travelling-Accent Rule

El acento cumple **el mismo trabajo** en las tres superficies —marcar el acto
oficial: un veredicto, un sello, la acción principal— pero **su valor cambia con
el soporte**, porque un color no se comporta igual sobre papel que sobre negro.

Medido:

| color | vs blanco | vs tinta `#211C15` | gris al imprimir en B/N |
|---|---|---|---|
| `#C6F24E` | **1,30:1** | 13,06:1 | **88%** |
| `#ECE3D0` papel | 1,28:1 | 13,26:1 | 89% |
| `#B23324` | 6,19:1 | 2,73:1 | **38%** |
| `#1E3A5F` | 11,50:1 | 1,47:1 | 23% |

`#C6F24E` sobre blanco da **1,30:1** —por debajo del 3:1 que exige un elemento
gráfico— y al imprimir en blanco y negro cae a un **88% de gris, indistinguible
del papel manila (89%)**. En pantalla oscura es excelente: 13:1 contra la tinta.
Por eso es el acento de la APP y **nunca** el de un documento.

En DOCUMENTOS el rol lo asume el **rojo de foliación `#B23324`**: 6,19:1 sobre
blanco y 38% de gris, que sobrevive a la fotocopia. Es además el acento de la
landing, así que el eje impreso y el comercial ya coinciden.

## Iconografía de la APP: inventario

**Esto es un inventario, no una nota.** La app tiene DOS vocabularios de icono
conviviendo, y la mezcla **es deliberada**: se migra por vista completa, no
símbolo por símbolo. Sin este inventario, alguien lee la regla del trazo en seis
meses, asume que toda la app cumple y deshace la decisión — que es exactamente
lo que pasó con `CLAUDE.md` y el tema oscuro.

### La regla del trazo

Todo icono de la app se dibuja en **SVG inline**, lienzo **16×16**, trazo
**1,7px**, `stroke-linecap` y `stroke-linejoin` redondeados, `fill="none"` salvo
en las masas deliberadas (el círculo lleno de `cumple`, el punto de la
interrogación). El color siempre viene de `currentColor`: un icono nunca declara
el suyo, así hereda el del estado o la criticidad que lo contiene.

Un trazo distinto es un icono de otro sistema. Verificable:
`grep -o 'stroke-width="[\d.]*"' static/app.js | sort -u` debe devolver un solo
valor.

### The Distinguishable-Shape Rule

Los iconos de ESTADO se rigen por una exigencia que los funcionales no tienen:
**cada estado debe distinguirse de los demás sin color**. El informe se imprime
en blanco y negro y no todo el mundo separa rojo de verde, así que el color es
refuerzo y la forma es el portador.

| estado | forma | por qué esa |
|---|---|---|
| `cumple` | círculo lleno | masa sólida: la única forma rellena del juego |
| `no_cumple` | cruz | dos diagonales, sin curvas |
| `dato_faltante` | interrogación | pregunta, no negación: no afirma incumplimiento |
| `revisar_manual` | triángulo | señal de atención, pide acción humana |
| `no_aplica` | guion | trazo horizontal único, el más neutro |

`pipeline/src/estados.py` es la fuente canónica del campo `forma`; `app.js` mapea
cada nombre a su SVG. Un test verifica que las cinco formas son distintas entre
sí y que cada una tiene SVG dibujado: una forma sin SVG cae al punto genérico y
el estado se pierde.

Los iconos FUNCIONALES (`financiero`, `juridico`, `documento`, `tabla`, `riesgo`,
`norma`, `adjunto`, `plan`, `descargar`) rotulan una sección o una acción y viven
en un mapa aparte. No pasan por la regla de forma distinguible porque su texto
adyacente ya los identifica.

### Qué vistas están migradas

| vista | archivo | estado | emoji |
|---|---|---|---|
| **Resultado de auditoría** | `app.js::renderAuditResult` + los tres paneles de requisitos | **MIGRADA** 2026-09-23 | **0** |

Es la vista del veredicto: la que el analista lee y de la que sale el informe
firmado. Nueve iconos funcionales más las cinco formas de estado.

### Qué vistas NO están migradas

Siguen con emoji, de forma consistente dentro de cada una. **172 ocurrencias**:

| vista | función / zona | emoji |
|---|---|---|
| Expedientes | `loadExpedientes` | 7 |
| Estrategia de precio | `calcularEstrategiaPrecio` | 5 |
| Análisis de pliego (progreso) | `analizarPliego` | 4 |
| Observaciones | `generarObservaciones` | 4 |
| Admin de clientes | `cargarListaClientes` | 4 |
| Búsqueda SECOP | `renderBusquedaResult`, `renderTabla`, `renderTablaAvanzada` | 9 |
| Extracción de pliego | `extraerPliego` | 3 |
| Calculadora APU | `apu_*` (8 funciones) | 12 |
| Perfil | `loadPerfil`, `_savePerfilImpl`, `loadDocumentos`, `_uploadDocImpl` | 5 |
| Resto de `app.js` | 14 funciones más | 20 |
| **`index.html`** | 31 en botones · 60 en encabezados y estados vacíos · 5 en títulos · 3 en pestañas | **99** |

`landing.html` tiene **cero**: ya cumple con SVG dibujado.

### Por qué la mezcla es deliberada

**La unidad de coherencia es la VISTA, no la aplicación.** Un usuario que lee el
informe de viabilidad no está mirando la búsqueda SECOP al mismo tiempo, así que
dos pantallas con vocabularios distintos no se comparan entre sí. Lo que no se
tolera es una pantalla con los dos a la vez.

Migrar 7 de 186 símbolos habría creado un **tercer** frente —emoji, SVG nuevo y
una vista a medias— en vez de cerrar uno. Migrar los 186 de golpe significa
construir 47 iconos y tocar nav, pestañas, botones y estados vacíos de todas las
vistas, con riesgo real de romper el progreso por fases, la búsqueda y el
descarte por perfil.

### Regla para lo nuevo

**Cualquier vista o componente que se construya desde hoy usa SVG.** La deuda
registrada cubre lo existente; no autoriza añadir un emoji más. Y cuando se
rediseñe una vista de la tabla anterior, sus emoji se migran en el mismo trabajo:
no es una tarea aparte, es parte de tocar esa pantalla. Ver `ESTADO_PIPELINE.md`
→ D24.

## Documentos

Superficie nueva. El informe de viabilidad es la pieza que el cliente se lleva y
que **el analista de SIACO firma ante una entidad**. Se imprime, se fotocopia, se
adjunta a un expediente. Eso manda sobre cualquier consideración de pantalla.

### Reglas propias

**The Photocopy Rule.** Todo significado debe sobrevivir a una fotocopia en
blanco y negro. El color es refuerzo, nunca el único portador: cada estado lleva
además **etiqueta de texto** (`CUMPLE`, `DATO FALTANTE`) y **forma**
distinguible. Si al pasar la página a grises se pierde una distinción, el diseño
está mal.

**The No-Icon Rule.** Sin iconografía. Ni emojis, ni SVG dibujados, ni
`[OK]`/`[NO]`. La jerarquía se hace con tipografía y espaciado. Un icono en un
documento que se presenta a una entidad lo hace parecer material promocional, no
un concepto técnico.

**The Full-Citation Rule.** La cita textual del pliego **no se trunca**. Es lo
que sostiene cada afirmación: un requisito habilitante con su cita cortada a 35
caracteres es indefendible. Si no cabe en la página, se pagina; no se recorta.

**The Scope-Footer Rule.** Cada documento declara su alcance en el pie. Un
informe sin alcance declarado invita a leerlo como más completo de lo que es.

### Tokens

| rol | valor | nota |
|---|---|---|
| papel | `#FFFFFF` | blanco de impresión, no manila: es tinta sobre hoja |
| texto | `#211C15` tinta | 16,91:1 |
| texto secundario | `#5E5647` tinta 2 | metadatos, notas al pie |
| acento / veredicto | `#B23324` rojo foliación | 6,19:1 · 38% en B/N |
| contrapunto | `#1E3A5F` azul oficial | encabezados de tabla |
| regla | `#C6B187` línea reglada | filas, divisiones |
| fondo de fila tenue | `#F4EDDD` papel claro | alternancia de tabla |

Las tramas de fondo por estado (`#F2FAF2`, `#FDF0F0`, `#FDF8EB`, `#F0F6FD`) son
**refuerzo sobre la etiqueta**, no sustituto. Todas caen entre 94% y 98% de gris
al imprimir: informan en color y desaparecen sin romper nada.

### Tipografía impresa

| nivel | fuente | uso |
|---|---|---|
| título de documento | Archivo 900, 20pt | «INFORME DE VIABILIDAD» |
| sección | Archivo 800, 13pt, mayúsculas | «REQUISITOS HABILITANTES» |
| subsección | Archivo 700, 11pt | nombre del requisito |
| cuerpo | Public Sans 400, 9,5pt, 1,45 | concepto, razones |
| **cita del pliego** | Public Sans 400, 9pt, cursiva, sangrada | texto literal, con su numeral |
| dato tabular | JetBrains Mono 8,5pt | numerales, umbrales, fechas |
| etiqueta de estado | JetBrains Mono 8pt, mayúsculas | `CUMPLE`, `DATO FALTANTE` |
| pie | Public Sans 400, 7,5pt | alcance, foliación |

### El informe de viabilidad: nueve secciones

El orden no es de conveniencia. **La limitación va antes del concepto** [P5,
ISA 700]: quien lee un veredicto ya no lee igual las salvedades que vienen
después.

| # | sección | de quién es |
|---|---|---|
| 1 | Identificación | qué documento es y con qué versiones se produjo |
| 2 | Alcance y limitaciones | **antes del concepto**, no después |
| 3 | Concepto | la escala de cuatro grados, con su motivo numérico |
| 4 | Requisitos habilitantes | cita textual sin truncar, con numeral |
| 5 | Causales de rechazo | transcritas literalmente: su redacción es lo que se puede observar |
| 6 | Documentos que debe confirmar | **tareas del CLIENTE** |
| 7 | Puntos que requieren decisión | **tareas del OPERADOR** |
| 8 | Procedimentales y de puntaje | el resto del pliego |
| 9 | Trazabilidad | **lo nuestro**: qué no sabemos y por qué |

**Las secciones 6 y 7 son dos listas con dueños distintos.** Confundirlas es
pedirle al cliente que resuelva algo nuestro, o quedarnos nosotros con una
tarea que es suya. Por eso **la columna de tiempo de gestión va en la 6 y sólo
en la 6**: en la 7 no hay nada que gestionar, hay que decidir.

**La sección 9 es donde va lo nuestro.** Un documento que falta puede ser un
hallazgo sobre la empresa o un hueco de nuestro formulario. Al cliente se le
pide lo mismo en los dos casos —*«Debe confirmar que cuenta con estos
documentos»*, sin mencionar nunca el formulario, que no es asunto suyo— porque
no afirmamos ni que lo tenga ni que le falte. La diferencia se declara en la 9,
contada: cuántos son hallazgo confirmado y cuántos están pendientes de captura.

### Pie y foliación: por qué no son CSS

[The Scope-Footer Rule] pide el alcance en el pie de toda página, y un informe
de 21 folios que se fotocopia necesita numerarlos. **Chromium no implementa las
cajas de margen de `@page`**, así que `content: counter(page)` no existe en el
motor que renderiza, y `position: fixed` no lo sustituye: se coloca fuera del
área imprimible y se superpone al contenido de la página siguiente —medido, el
pie pisando la cabecera de tabla de dos folios—.

El pie y el folio **se estampan sobre el PDF ya renderizado**. Eso añade lo que
el CSS no podía dar de ninguna forma: **«folio N de M»**, con el total. En un
documento que se adjunta a un expediente, saber cuántas páginas debería haber
es lo que delata una fotocopia incompleta.

### Familia documental

Cuatro documentos previstos. **Sólo el primero se construye ahora**; los otros
tres se declaran para que compartan estructura desde el principio en vez de
divergir cuando se hagan.

1. **Informe de viabilidad** — ¿puede y le conviene ofertar? *Se construye ahora.*
2. **Observaciones al pliego** — cuando se integre el bibliotecario normativo.
3. **Propuesta de servicios** — comercial, después.
4. **Comunicaciones** — cartas y oficios, después.

**Elementos comunes a los cuatro:**

- **Encabezado**: logotipo SIACO, tipo de documento, entidad y número de proceso,
  fecha y **versión del análisis** (versión del catálogo y de la biblioteca: un
  informe reproducible dice con qué se produjo).
- **Quién firma**: nombre y rol del analista. El modelo es de agencia; el
  documento tiene autor humano responsable.
- **Numeración de páginas**: `folio N de M`, en monoespaciada.
- **Pie de alcance**: ver abajo.

### Pie de alcance

Aprobado por el fundador el 2026-09-23.

> Este informe analiza el pliego de condiciones identificado en el encabezado y
> los datos del perfil de la empresa disponibles a la fecha indicada. El análisis
> cubrió el X% de los requisitos del pliego; los no evaluados se señalan en el
> bloque de revisión manual. Cada requisito se cita textualmente del pliego con su
> numeral; las citas marcadas como no verificadas no pudieron confrontarse contra
> el documento fuente. Un requisito señalado como DATO FALTANTE no significa
> incumplimiento: significa que la información no estaba disponible para
> evaluarlo. El análisis no sustituye el criterio profesional del abogado o
> contador responsable.

**El X% se rellena con `cobertura_global` del evaluador**, que es
`total_con_datos / total_evaluados`: cuántos requisitos se pudieron evaluar
contra el perfil de la empresa. **No con la cobertura del catálogo**, que mide
otra cosa —qué fracción de los requisitos extraídos reconoce el catálogo de
objetos— y es un dato interno del pipeline que al cliente no le dice nada.

⚠ **Trampa de nombres.** En la respuesta de la API ese valor viaja como
`cobertura_pliego` (`routers/auditoria.py:509`), que sugiere «cobertura del
pliego» y NO lo es: contiene la cobertura de la EVALUACIÓN. El campo del
catálogo vive aparte, en `consolidacion.catalogo.cobertura`. Quien rellene este
pie debe tomar `cobertura_pliego`/`cobertura_global`, no el del catálogo.

Dos cosas que hace esta redacción, por si se reescribe: **declara la cobertura**
—un informe que no la declara parece completo, y si un día no lo está nadie se
entera; es la misma decisión que se tomó con el score que marcaba 100 sobre el
23% de los requisitos— y **distingue `DATO FALTANTE` de incumplimiento**, que es
la afirmación falsa que el sistema no puede permitirse.

Se quitó a propósito «ni garantiza la adjudicación del proceso»: nadie espera que
un análisis de requisitos garantice ganar una licitación, y la aclaración sonaba
a letra pequeña restando seriedad al resto.

### Do's and Don'ts de documentos

**Do:**
- **Do** imprimir una prueba en blanco y negro antes de dar por bueno un cambio.
- **Do** dar a los habilitantes la cita textual completa; son lo que responde
  «¿me pueden sacar?».
- **Do** comprimir procedimentales y puntaje en tabla de tres columnas
  (numeral, nombre, estado): son contexto, no el veredicto.
- **Do** separar las causales de rechazo en su propio bloque.
- **Do** declarar los umbrales alternativos cuando el pliego define más de uno,
  en vez de elegir por el cliente.

**Don't:**
- **Don't** usar `#C6F24E` en un documento: 1,30:1 sobre blanco y 88% de gris.
- **Don't** usar iconos, emojis ni `[OK]`/`[NO]`.
- **Don't** truncar una cita del pliego.
- **Don't** apoyar un estado sólo en el color de fondo de la fila.
- **Don't** presentar `DATO FALTANTE` ni `REVISIÓN MANUAL` como incumplimiento.
