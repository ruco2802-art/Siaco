# Comparación de parsers de PDF — SIACO
PDF principal: `16. PLIEGO DE CONDICIONES DEFINITIVO.pdf`

> **Hallazgo de contexto:** este PDF es escaneado (cada página es una imagen).
> `page.get_text()` devuelve 0 chars por sí sola. El texto se extrae 100% vía OCR.
> Parser A usa Tesseract (igual que el sistema productivo). B y C usan sus propios mecanismos.
PDFs adicionales: `28.PLIEGO DEFINITIVO SAMC 023 DE 2026 OBRA AGRUPADA ATL Y BOL.pdf`, `21.Documento Base o Documento Definitivo.pdf`

## 1. Tabla resumen

| Métrica | A — PyMuPDF plano | B — pymupdf4llm | C — Docling |
|---|---|---|---|
| Chars extraídos | 191,479 | 183,514 | 0 |
| Tiempo parseo | 108.45s | 368.48s | 0s |
| Pico RAM | 5.1 MB | 267.8 MB | 0.0 MB |
| Encabezados detectados (total) | 89 | 33 | — |
| 2.12.1 como encabezado | ✓ | ✓ | ✗ |
| Términos 2.12.1 recuperados | 2/6 | 1/6 | 0/6 |

## 2. Integridad sección 2.12.1 — términos buscados

| Término | A | B | C |
|---|---|---|---|
| `RUT` | ✗ | ✗ | ✗ |
| `seguridad social` | ✗ | ✗ | ✗ |
| `paz y salvo` | ✗ | ✗ | ✗ |
| `existencia y representación` | ✓ | ✗ | ✗ |
| `antecedentes` | ✓ | ✓ | ✗ |
| `RUP` | ✗ | ✗ | ✗ |

## 3. Fragmento sección 3.1 — MATRIZ DE INDICADORES (primeros 2 500 chars)

### Parser A — PyMuPDF plano

```
3.175.000.00)
TIEMPO DURACIÓN CONTRATO VEINTICINCO (25) DÍAS CALENDARIO
FECHA 16 DE JUNIO DE 2026
L INTRODUCCIÓN

EL MUNICIPIO DE CRAVO NORTE pone a disposición de los interesados el presente proyecto de Pliego de
Condiciones para la selección del contratista encargado de ejecutar el contrato de “APOYO LÓGISTICO PARA LA
CONMEMORACION DEL DIA DEL LLANERO EN EL MUNICIPIO DE CRAVO NORTE, ARAUCA”, Los estudios y
documentos previos que incluyen el análisis del sector, el proyecto de Pliego de Condiciones y el Pliego de
Condiciones definitivo, así como cualquiera de sus anexos están a disposición del público en el Sistema Electrónico
de Contratación Pública -SECOP lo

La selección del contratista se realizará a través de Selección Abreviada de Menor Cuantía No. SAMC-CN-014-2026

La entidad evaluará las ofertas con base en las regías establecidas en el pliego de condiciones y en la normativa
aplicable.

El presente Proyecto de Pliego de Condiciones se esquematiza, teniendo en cuenta las variables señaladas en el
artículo 2.2.1.1.2,1.3 del Decreto 1082 de 2015 y el modelo guía o tipo confeccionado por la Agencia Pública de
Contratación Colombia Compra Eficiente.

CAPITULO |
ASPECTOS GENERALES DEL PROCESO

1.1 MARCO LEGAL Y RÉGIMEN APLICABLE Tanto el proceso de selección como el futuro contrato que se suscriba
como consecuencia de este proceso, se regirá en lo pertinente por la Constitución Política de Colombia, el Estatuto
General de la Contratación de la Administración Pública - Ley 80 de 1993, la Ley 1150 de 2007, la Ley 1474 de
2011, el Decreto — Ley 19 de 2012, el Decreto 1082 de 2015 y demás normas reglamentarias las normas
presupuestales distritales y nacionales, el pliego de condiciones, los estudios previos, el Código de Procedimiento
Administrativo y de lo Contencioso Administrativa y demás disposiciones que regulen la materia.

1.2 CONDICIONES DE PARTICIPACIÓN Para que la oferta económica y técnica pueda ser considerada, los
proponentes interesados en el presente Proceso de Selección deben presentar los documentos que se exigen
para acreditar el cumplimiento de los requisitos habilitantes.

1.3 IDIOMA Los documentos y las comunicaciones entregadas, enviadas o expedidas por los proponentes o por
terceros para efectos del proceso de contratación, o para ser tenidos en cuenta en el mismo, deben ser allegados en
español. Los documentos y comunicaciones en un idioma distinto deben ser presentados en su lengua original junto
con la traducción oficial al españo
```

### Parser B — pymupdf4llm

```
3.175.000.00)<br>MCTE|
|TIEMPO DURACIÓN CONTRATO<br>|.<br>VEINTICINCO (25) DÍAS CALENDARIO<br>|
|FECHA|16 DE JUNIO DE 2026|



###### I. INTRODUCCIÓN 

EL MUNICIPIO DE CRAVO NORTE pone a disposición de los interesados el presente proyecto de Pliego de Condiciones para la selección del contratista encargado de ejecutar el contrato de "APOYO LÓGISTICO PARA LA CONMEMORACION DEL DIA DEL LLANERO EN EL MUNICIPIO DE CRAVO NORTE, ARAUCA", LoS eStudiOS y documentos previos que incluyen el análisis del sector, el proyecto de Pliego de Condiciones y el Pliego de Condiciones definitivo, así como cualquiera de sus anexos están a disposición del público en el Sistema Electrónico de Contratación Pública -SECOP https://community.secop.gov.co/Public/Tendering/ContractNoticeManagement/Index?currentLanguage=esCO&Page=login&Country=CO&SkinName=CCE 

La selección del contratista se realizará a través de Selección Abreviada de Menor Cuantía No. SAMC-CN-014-2026 

La entidad evaluará las ofertas con base en las reglas establecidas en el pliego de condiciones y en la nomativa aplicable. 

El presente Proyecto de Pliego de Condiciones se esquematiza, teniendo en cuenta las variables señaladas en el ie Contratación Colombia Compra Eficiente. 

##### CAPITULO I ASPECTOS GENERALES DEL PROCESO 

- 1.1 MARCO LEGAL Y RÉGIMEN APLICABLE Tanto el proceso de selección como el futuro contrato que se suscriba ost  oi  oiia it  d  c e oi s oi ea  ca coito General de la Contratación de la Administración Pública - Ley 80 de 1993, la Ley 1150 de 2007, la Ley 1474 de 2011, el Decreto – Ley 19 de 2012, el Decreto 1082 de 2015 y demás nommas reglamentarias las normas presupuestales distritales y nacionales, el pliego de condiciones, los estudios previos, el Código de Procedimiento Administrativo y de lo Contencioso Administrativo y demás disposiciones que regulen la materia. 

- 1.2 CONDICIONES DE PARTICIPACIÓN Para que la oferta económica y técnica pueda ser considerada, los pdro s  oeo oe e ee cs  r ed e  oe sge para acreditar el cumplimiento de los requisitos habilitantes. 

1.3 IDiOMA Los documentos y las comunicaciones entregadas, enviadas o expedidas por los proponentes o por terceros para efectos del proceso de contratación, o para ser tenidos en cuenta en el mismo, deben ser allegados en español. Los documentos y comunicaciones en un idioma distinto deben ser presentados en su lengua original junto con la traducción oficial al español. 

Para que la traducción oficial de los documentos en id
```

### Parser C — Docling

```

```

## 4. Notas de ejecución

- **Parser C (Docling)**: ERROR — `Conversion failed for: 16. PLIEGO DE CONDICIONES DEFINITIVO.pdf with status: failure. Errors: InvalidCxxCompiler: Compiler: cl is not found.

Set TORCHDYNAMO_VERBOSE=1 for the internal stack trace (please do this especially if you're reporting a bug to PyTorch). For even more developer context, set `
