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
