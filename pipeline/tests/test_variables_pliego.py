# -*- coding: utf-8 -*-
"""
Auditor de VARIABLES DEL PLIEGO declaradas y sin quien las pueble.

Existe por el mismo motivo que el auditor de funciones sin llamador: en este
repositorio, **construir algo y no conectarlo es el defecto más repetido**.
Ya van nueve casos —el campo `icono`, `reparar_markdown()`, `consolidar()`,
`marcar_indices()`, `notificador.enviar_gmail()`, `generar_aviso_verificacion()`
y ahora las variables del pliego—, y todos comparten la firma: el código pasa
los tests, no rompe nada, y no hace nada.

`resolucion_variables.py` declara nueve variables del pliego y sabe resolver
fórmulas con ellas (`CTd = (POE - Anticipo) / …`). **Nadie las puebla desde el
pliego.** Las dos que aparecen escritas en el repositorio lo están en la
calculadora APU y el generador de oferta, que son otro subsistema y no
alimentan a `evaluar_empresa()`.

Consecuencia medible: `valores_pliego` llega siempre vacío, así que
`seleccionar_rango_umbrales()` devuelve `None` y `clave_umbrales` se queda en
`"umbral_no_determinable"`. Eso NO es un fallo silencioso —el código se niega
a poner un default, que es lo correcto [I10]— pero significa que el pipeline
nunca elige juego de umbrales por rango y variante.

El test no exige arreglarlo: exige que la lista de huérfanas **no crezca sin
que alguien lo note**.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.resolucion_variables import _PLIEGO_CAMPOS  # noqa: E402

_RAIZ = Path(__file__).resolve().parents[2]

# Huérfanas CONOCIDAS al 2026-09-28. Cada una con lo que haría falta para
# poblarla. Quitar una de aquí exige haberla cableado de verdad.
HUERFANAS_CONOCIDAS: dict[str, str] = {
    "presupuesto_oficial_estimado": "está en la portada del pliego; el extractor no lo captura",
    "valor_smmlv_anio": "es una constante anual; bastaría una tabla en el repo",
    "porcentaje_anticipo": "está en el pliego; sin extraer",
    "valor_anticipo": "se deriva de presupuesto × porcentaje_anticipo",
    "capital_trabajo_demandado": "se calcula con la fórmula CTd, que necesita POE y anticipo",
    "saldos_contratos_en_ejecucion_pliego": "lo declara el proponente, no el pliego",
    "plazo_dias": "variante de plazo_meses; misma fuente y mismo bloqueo",
    # [D35] plazo_meses: en Paicol SÍ está en el markdown («DOS MESES (02)»)
    # aunque en una tabla descolocada, así que un cambio de prompt lo
    # capturaría. En Ternera NO está: su tabla de portada no sobrevivió al
    # parseo, y ahí ningún prompt puede recuperarlo.
    "plazo_meses": "[D35] extraíble en Paicol con cambio de prompt; en Ternera falta en el markdown",
    "valor_contrato": "sólo lo puebla la calculadora APU, que es otro subsistema",
}


def _fuentes_de_produccion() -> list[Path]:
    """Ficheros donde una variable del pliego podría poblarse de verdad."""
    patrones = ("pipeline/src/*.py", "pipeline/*.py", "routers/*.py", "*.py")
    return [f for pat in patrones for f in _RAIZ.glob(pat)
            if "test" not in f.name and f.name != "resolucion_variables.py"]


def test_las_variables_del_pliego_huerfanas_no_crecen():
    """
    Si aparece una variable declarada que nadie puebla y no está en la lista,
    el test falla. Es la única forma de que el décimo caso no pase inadvertido
    como pasaron los nueve anteriores.
    """
    canonicas = sorted(set(_PLIEGO_CAMPOS.values()))
    fuentes = [(f, f.read_text("utf-8", errors="replace"))
               for f in _fuentes_de_produccion()]

    huerfanas = []
    for var in canonicas:
        rx = re.compile(rf'["\']{re.escape(var)}["\']\s*:|\b{re.escape(var)}\s*=')
        if not any(rx.search(texto) for _f, texto in fuentes):
            huerfanas.append(var)

    nuevas = set(huerfanas) - set(HUERFANAS_CONOCIDAS)
    assert not nuevas, (
        f"variables del pliego declaradas que NADIE puebla y que no estaban "
        f"registradas: {sorted(nuevas)}. O se cablean, o se añaden a "
        f"HUERFANAS_CONOCIDAS diciendo qué haría falta.")


def test_toda_huerfana_conocida_declara_que_le_falta():
    """Una lista de pendientes sin el motivo es una lista que nadie retoma."""
    for var, motivo in HUERFANAS_CONOCIDAS.items():
        assert var in set(_PLIEGO_CAMPOS.values()), (
            f"{var} ya no está declarada: quítala de HUERFANAS_CONOCIDAS")
        assert len(motivo) > 25, f"{var}: el motivo no dice qué haría falta"


def test_el_pipeline_no_inventa_un_juego_de_umbrales_sin_los_datos():
    """
    [I10] La consecuencia de que las variables estén vacías tiene que ser
    declarar que no se pudo determinar, nunca elegir un juego por defecto:
    aplicar umbrales de no-Mipyme a una Mipyme produce resultados falsos.
    """
    from src.evaluator import seleccionar_rango_umbrales
    assert seleccionar_rango_umbrales(None, None, True) is None
    assert seleccionar_rango_umbrales(100_000_000, None, True) is None
    assert seleccionar_rango_umbrales(100_000_000, 0, True) is None
