# /verify — Verificación del pipeline sin costo de API

Ejecuta en orden y reporta. **NO consumas API en ningún paso.**
Si algún paso requiere API para completarse, PARA y repórtalo.

---

## Paso 1 — Tests

```
py -m pytest pipeline/tests/ -v --tb=short
```

Reporta: número de tests pasados/fallidos. Si alguno falla, PARA aquí
e informa cuál y por qué antes de continuar.

---

## Paso 2 — Chunker sobre pliegos en caché

Para cada entrada en `.pipeline_cache/`, carga el markdown y ejecuta `chunkear()`.

```python
import json, sys
from pathlib import Path
sys.path.insert(0, 'pipeline')
from pipeline.src.chunker import chunkear

for f in Path('.pipeline_cache').glob('*.json'):
    d = json.loads(f.read_text('utf-8'))
    md = d['markdown']
    archivo = d['metadata'].get('archivo', f.name)
    try:
        chunks, cob = chunkear(md)
        con_numeral = sum(1 for c in chunks if c['metadata'].get('numeral_derivado'))
        pct_num = con_numeral / len(chunks) * 100 if chunks else 0
        print(f"{archivo}: {cob:.1f}% cobertura | {len(chunks)} chunks | {pct_num:.0f}% con numeral")
    except Exception as exc:
        print(f"{archivo}: ERROR — {exc}")
```

Reporta: cobertura_pct, nº chunks, % chunks con numeral_derivado.
Alerta si cobertura < 99%.

---

## Paso 3 — Detector de tablas por documento

Para cada entrada en `.pipeline_cache/`:

```python
import json, sys
from pathlib import Path
sys.path.insert(0, 'pipeline')
from pipeline.src.tablas import detectar_tablas_rotas

for f in Path('.pipeline_cache').glob('*.json'):
    d = json.loads(f.read_text('utf-8'))
    md = d['markdown']
    archivo = d['metadata'].get('archivo', f.name)
    tipo = d['metadata'].get('tablas_reparacion', {}).get('tipo_pdf', '?')
    rotas = detectar_tablas_rotas(md)
    meta_t = d['metadata'].get('tablas_reparacion', {})
    total = meta_t.get('tablas_totales', '?')
    print(f"{archivo} [{tipo}]: {total} totales | {len(rotas)} detectadas rotas")
```

Reporta: totales vs rotas por documento. Nota si el documento es TIPO C
(escaneado): las tablas "rotas" son falsos positivos del detector calibrado
para marker — no requieren acción.

---

## Paso 4 — Auditoría de funciones sin llamador

Lista funciones públicas en `pipeline/src/` que no tienen llamador en
código de producción (excluyendo tests). Para cada una indica el estado:
`conectada`, `punto_de_extension`, o `BUG`.

Funciones actualmente auditadas (actualizar si cambia):

| Función | Archivo | Estado | Nota |
|---|---|---|---|
| `parsear_pdf` | parser.py | conectada | llamada desde main.py |
| `chunkear` | chunker.py | conectada | llamada desde main.py |
| `extraer` | extractor.py | conectada | llamada desde main.py |
| `verificar_citas` | verifier.py | conectada | llamada desde main.py |
| `marcar_indices` | verifier.py | conectada | llamada desde main.py |
| `tasa_verificacion` | verifier.py | conectada | llamada desde main.py |
| `generar_aviso_verificacion` | verifier.py | conectada | llamada desde main.py |
| `estado_global` | verifier.py | conectada | llamada desde main.py |
| `cargar_perfil` | evaluator.py | conectada | llamada desde main.py |
| `evaluar_empresa` | evaluator.py | conectada | llamada desde main.py |
| `reparar_markdown` | tablas.py | conectada | llamada desde parser.py |
| `reparar_con_modelo` | tablas.py | punto_de_extension | TIPO A/B only; inalcanzable en TIPO C (pagina_no_localizada) |
| `_matrix_ratio_entero` | tablas.py | punto_de_extension | API Anthropic normaliza internamente; 4406 tokens idénticos 2x/3x/4x |

---

## Paso 5 — Criterio de fallo

PARA y reporta si:
- Algún test falla
- Cobertura del chunker < 99% en cualquier documento cacheado
- Una función listada como `conectada` no tiene llamador en producción

Si todo pasa: reporta "VERIFY OK" con el resumen de cada paso.
