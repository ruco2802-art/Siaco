# Advertencia de verificación manual — especificación

Bloque que aparece en el reporte de análisis cuando alguna parte del documento
se reconstruyó sin verificación exacta contra la fuente.

## Cuándo aparece

- El documento no tiene capa de texto (escaneado), o
- Alguna tabla se reparó por la vía del modelo, o
- Hay requisitos con `estado_verificacion = "degradada"`

No aparece cuando todo el análisis proviene de texto nativo verificado.

## Principio

El abogado no necesita saber que el documento es escaneado. Necesita saber
**qué revisar, en qué página, y por qué**.

Un aviso genérico ("verifique las citas") se ignora. Una lista de cinco
citas concretas con su ubicación se revisa en diez minutos.

---

## Formato

```
⚠ VERIFICACIÓN MANUAL RECOMENDADA

Este documento fue publicado como imagen escaneada, sin texto seleccionable.
Las citas señaladas abajo se reconstruyeron mediante lectura del documento y
no pudieron confrontarse carácter por carácter contra el original.

El contenido de los requisitos es confiable. Lo que no podemos garantizar es
la literalidad exacta de la redacción.

REQUISITOS A VERIFICAR — 4 de 27

┌────────────────────────────────────────────────────────────┐
│ 1. Capital de trabajo                          pág. 43     │
│    Numeral 3.7                                             │
│    Citado:  "CT = AC - PC ≥ CTd"                           │
│    Motivo:  fórmula reconstruida desde tabla escaneada     │
│    Revisar: que los símbolos y el operador coincidan       │
├────────────────────────────────────────────────────────────┤
│ 2. Índice de liquidez — tramos de puntaje      pág. 50     │
│    Numeral 3.10.2 literal C                                │
│    Citado:  "0,76 – 1,00 → 30 puntos"                      │
│    Motivo:  2 celdas con separador decimal dudoso          │
│    Revisar: que los tramos y puntajes correspondan         │
└────────────────────────────────────────────────────────────┘

Los 23 requisitos restantes tienen cita verificada contra el documento.
```

---

## Reglas de redacción

**Ordena por criticidad.** Primero los habilitantes (un error impide ofertar),
después los de puntaje, al final los procedimentales.

**Di qué revisar, no solo que revise.** "Confirme que el umbral es 1,21 y no
1.21" es accionable. "Verifique esta cita" no lo es.

**Da la página siempre.** Es lo que convierte la advertencia en una tarea de
minutos en lugar de una relectura completa.

**Nunca ocultes el conteo.** Si son 15 de 27, dilo. Un usuario que descubre
por su cuenta que la mitad no estaba verificada pierde la confianza en todo
el análisis.

**No te disculpes ni infles el lenguaje.** El sistema hizo su trabajo: leyó un
documento que la entidad publicó en un formato deficiente y señaló con
precisión dónde está el límite de su certeza. Eso es una función, no una
falla.

---

## Lo que NO debe decir

- "El análisis puede contener errores" — vago, alarma sin orientar
- "Se recomienda revisar el documento original" — eso anula el valor del
  análisis
- Ocultar que hubo reconstrucción para que el reporte se vea más limpio

---

## Campos necesarios en el modelo de datos

Cada requisito debe poder responder:

```python
estado_verificacion: Literal["verificada", "degradada", "no_verificada"]
motivo_degradacion: str | None      # por qué no se pudo verificar
pagina_origen: int | None           # dónde buscar en el PDF
criticidad: Literal["habilitante", "puntaje", "procedimental"]
```

`pagina_origen` y `criticidad` no existen todavía en el esquema `Requisito`.
Hay que añadirlos: sin página, el abogado no sabe dónde buscar; sin
criticidad, no se puede ordenar la lista por lo que más importa.
