# Estado del Pipeline — Pendientes y Decisiones

## Expediente de Proceso (PENDIENTE — alta prioridad)

**Qué es:** Un segundo eje de datos, ortogonal al perfil de empresa, que registra
el estado de los **requisitos procedimentales por oferta concreta**.

Los procedimentales no son atributos de la empresa: son eventos del proceso.
Ejemplos detectados en Paicol 2026:

| Requisito procedimental | Pregunta de seguimiento |
|---|---|
| Carta de presentación de la oferta (Formato 1) | ¿Se firmó y adjuntó? |
| Manifestación de interés como condición de procedibilidad | ¿Se presentó antes del cierre? |
| Plazo para manifestar interés | ¿Dentro de los 3 días hábiles? |
| Presentación de oferta mediante usuario SECOP II del consorcio | ¿Usuario SECOP correcto? |
| Manifestación de interés previa a la presentación | ¿Registro en SECOP II previo? |

**Diseño propuesto:**
```
ExpedienteOferta {
    proceso_id: str          # ID del proceso en SECOP II
    empresa_id: str          # NIT o referencia al perfil
    requisito_id: str        # nombre o hash del requisito
    estado: "pendiente" | "cumple" | "no_cumple" | "no_aplica"
    fecha_verificacion: str  # ISO-8601
    nota: str | None
}
```

El evaluador consultaría el expediente si está disponible; si no, marca
`no_evaluable` en lugar de `dato_faltante` (distingue "falta dato empresa"
de "no se ha registrado en este proceso").

**Por qué no está implementado todavía:**
Requiere decidir el backend de persistencia (Supabase / SQLite / JSON por proceso)
y el flujo de UX para que el usuario registre el estado durante el proceso de
evaluación. Impacto en cobertura: ~9 requisitos que pasarían de sin_dato a evaluados.

---

## Requisitos "sin_criterio_evaluable" — decisión pendiente

Estos 6 requisitos tienen umbral numérico pero no campo en el perfil aún:

| Requisito | Umbral | Categoría |
|---|---|---|
| Acto de creación de entidad estatal | ≤ 30 días | juridico → **no_aplica** siempre para privados |
| Participación mínima empresa mujeres en PP | ≥ 10 % | juridico → **no_aplica** para individuales |
| Porcentaje mínimo empleados colombianos | ≥ 40 % | tecnico → **ya resuelto** con `porcentaje_empleados_colombianos` |
| Porcentaje mínimo empleados colombianos (PP) | ≥ 40 % | tecnico → **no_aplica** para individuales |
| Plazo para manifestar interés | 3 días | documental → expediente de proceso |
| Tope máximo deducibles póliza RCE | ≤ 2.000 SMMLV | documental → expediente de proceso |

---

## Re-extracción Paicol 2026 (PENDIENTE — requiere créditos API)

Cuando los créditos estén disponibles, ejecutar desde `pipeline/`:

```
py main.py "../pliegos_evaluacion/29. PLIEGO DE CONDICIONES.pdf"
```

Objetivo: recuperar chunks 70-85 (4.5 MIPYME, ~$0.50 total), ROE del numeral 3.8,
y poblar `aplica_a` correctamente para requisitos de extranjeros y proponentes plurales.

Después copiar resultado como `paicol_2026_resultado.json`.

---

## Decisiones de diseño fijas

- `Score 100/100` con `DATO_INSUFICIENTE` no se muestra al usuario si `cobertura < 80 %`
- `no_aplica` está fuera del denominador de cobertura
- `es_proponente_plural: bool = False` en PerfilEmpresa — Mipymes individuales no cambian este valor
- `titulo_profesional: Literal["arquitecto","ingeniero","ninguno"]` — no agregar booleano separado
- Mapeos multi-campo (tiene_programa_transporte_sostenible, tiene_programacion_obra) **NO en el perfil** — son compromisos por oferta, no atributos de empresa
