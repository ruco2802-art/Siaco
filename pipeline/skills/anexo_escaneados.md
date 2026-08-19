# Anexo: Documentos escaneados

Se aplica cuando la página proviene de un escaneo. Complementa las reglas
generales; no las reemplaza. R1 (solo lo impreso) y R2 (ilegible se marca)
siguen siendo absolutas y aquí importan más que nunca.

---

## El riesgo específico de un escaneo

En un escaneo la tinta se degrada. Vas a encontrar caracteres ambiguos,
manchas, líneas torcidas, texto desvanecido.

La tentación es completar con lo que "tiene sentido". **No lo hagas.**

Un pliego de contratación pública es un documento con efectos jurídicos. Una
cifra mal transcrita en un indicador financiero puede hacer que una empresa se
presente a un proceso del que sería rechazada, o que se abstenga de uno donde
califica.

Es preferible devolver `[ILEGIBLE]` diez veces que acertar nueve y equivocarse
una sin avisar.

---

## Reglas adicionales

### E1 — Números y símbolos: umbral de certeza más alto
Un dígito ambiguo se marca. No lo deduzcas por contexto.

Confusiones típicas del escaneo: `0/O`, `1/l/I`, `5/S`, `6/G`, `8/B`, `,/.`

Si dudas entre `1,21` y `1.21`, o entre `0,50` y `0.50`, marca la celda como
`[DUDOSO: 1,21]`. El separador decimal cambia el valor.

Nunca "arregles" un número porque el valor resultante te parezca más plausible.

### E2 — No completes desde tu conocimiento del dominio
Sabes cómo se ve una tabla de indicadores de un Documento Tipo. Ese
conocimiento sirve para **entender la disposición visual** — reconocer que una
fracción apilada es una celda.

No sirve para rellenar. Si ves `Rentabilidad sobre Patrim___` y el resto está
borroso, escribe lo legible y marca el corte. No completes "Patrimonio" aunque
sea evidente.

### E3 — Líneas torcidas
Un escaneo suele estar ligeramente rotado. Los bordes de tabla no son rectos.

Guíate por la **alineación del contenido**, no por las líneas. Si tres valores
están verticalmente alineados y forman una serie coherente, son una columna,
aunque el borde dibujado se desvíe.

### E4 — Sellos, firmas y anotaciones a mano
Si un sello o una firma se superpone a una celda, transcribe lo que se lee
debajo y añade `[SELLO SUPERPUESTO]`.

Las anotaciones manuscritas no forman parte de la tabla. No las transcribas
dentro de las celdas; regístralas en `observaciones`.

### E5 — Página ilegible completa
Si la calidad impide leer con confianza más del 40% de las celdas, no
devuelvas una tabla parcial que aparente estar completa. Devuelve:

```
{"pagina_pdf": N, "tablas": [], "calidad_insuficiente": true,
 "motivo": "descripción de lo observado"}
```

Es más útil un "no pude" explícito que una tabla con la mitad inventada.

---

## Campos adicionales de salida

Además de los campos del skill base, en documentos escaneados incluye:

```
"celdas_dudosas": 3,
"observaciones": "Sello de la alcaldía superpuesto en la fila 4. Página
                  ligeramente rotada. Sin efecto en la lectura del resto."
```

Y `confianza` se calibra distinto:
- `alta` — sin celdas dudosas ni ilegibles
- `media` — hasta 2 celdas marcadas
- `baja` — 3 o más celdas marcadas, o duda sobre la estructura de columnas

---

## Autoverificación adicional

Antes de responder, además de las comprobaciones del skill base:

1. ¿Completé algún número que en realidad no se lee con nitidez?
2. ¿Elegí un separador decimal por lógica en vez de por lo que veo?
3. ¿Completé alguna palabra cortada porque "es obvia"?
4. ¿Marqué todas las celdas donde tengo dudas reales?
5. Si la página está muy degradada, ¿debería haber declarado
   `calidad_insuficiente`?
