# -*- coding: utf-8 -*-
"""
tests/test_catalogo.py — [B11] Catálogo de objetos del dominio.

`grupo_es_coherente()` compara PALABRAS. Un grupo unido por un término
específico pero transversal ("residual", 7 de 13 miembros) sobrevive aunque
mezcle capacidad residual con ingresos operacionales, tarjeta profesional e
índice de liquidez. El catálogo declara qué objetos existen.

Clave de agrupación: (objeto, aspecto, capítulo).

Sin API. Determinista: dos corridas sobre el mismo pliego dan lo mismo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.src.extractor import Requisito
from pipeline.src.catalogo import (
    cargar_catalogo,
    clave_agrupacion,
    identificar_aspecto,
    identificar_objeto,
    normalizar,
    registrar_no_identificados,
)
from pipeline.src.clasificador import consolidar, magnitudes_incompatibles


def _r(nombre: str, numeral: str = "3.5", literal: str = "texto") -> Requisito:
    return Requisito(
        nombre=nombre, categoria="experiencia",
        fuente_numeral=numeral, exigido_literal=literal,
    )


# ─── 1. Objetos que comparten palabra pero son distintos ─────────────────────

def test_capacidades_son_objetos_distintos():
    """
    El caso que rompió `crp_calculo`: tres objetos comparten "capacidad".
    Si se confunden, el evaluador aplica la tabla de tramos del factor CF
    como si fuera el umbral habilitante de liquidez.
    """
    residual = identificar_objeto(_r("Capacidad residual de contratación"))
    organiz  = identificar_objeto(_r("Capacidad de organización (CO)"))
    financ   = identificar_objeto(_r("Capacidad financiera del proponente"))

    assert residual == "CAPACIDAD_RESIDUAL"
    assert organiz == "CAPACIDAD_ORGANIZACIONAL"
    assert financ == "CAPACIDAD_FINANCIERA"
    assert len({residual, organiz, financ}) == 3, (
        "Las tres capacidades colapsaron en el mismo objeto: el catálogo no "
        "distingue lo que la palabra compartida oculta."
    )


def test_liquidez_para_capacidad_residual_es_capacidad_residual():
    """
    Decisión de diseño: 'Índice de liquidez para capacidad residual (CF)'
    pertenece a CAPACIDAD_RESIDUAL, no a LIQUIDEZ. Lo que el evaluador
    necesita es la tabla de tramos del factor CF, no el umbral habilitante
    de liquidez del pliego — son cálculos distintos.
    """
    obj = identificar_objeto(_r("Índice de liquidez para capacidad residual (CF)"))
    assert obj == "CAPACIDAD_RESIDUAL", (
        f"objeto={obj}. El alias más largo ('capacidad residual') debe ganar "
        "sobre 'liquidez'."
    )


# ─── 2. Alias distintos, mismo objeto ────────────────────────────────────────

def test_rup_y_nombre_completo_son_el_mismo_objeto():
    a = identificar_objeto(_r("RUP vigente y en firme"))
    b = identificar_objeto(_r("Registro Único de Proponentes actualizado"))
    assert a == b == "RUP"


def test_siglas_financieras_son_el_mismo_objeto():
    """IDL e 'Índice de liquidez' son el mismo indicador. Las siglas del
    dominio son cortas: filtrarlas por longitud las perdía."""
    assert identificar_objeto(_r("IDL mínimo exigido", "3.6")) == "LIQUIDEZ"
    assert identificar_objeto(_r("Índice de liquidez", "3.6")) == "LIQUIDEZ"
    assert identificar_objeto(_r("ROE mínimo", "3.6")) == "RENTABILIDAD_PATRIMONIO"
    assert identificar_objeto(_r("ROA mínimo", "3.6")) == "RENTABILIDAD_ACTIVO"


# ─── 3. El alias más largo gana [K2] ─────────────────────────────────────────

def test_alias_mas_largo_gana():
    """'capacidad residual' (17 chars) debe vencer a 'capacidad' (9)."""
    cat = cargar_catalogo()
    # La tabla debe estar ordenada por longitud descendente
    longitudes = [len(a) for a, _ in cat.objetos]
    assert longitudes == sorted(longitudes, reverse=True), (
        "La tabla de alias no está ordenada por longitud: el desempate [K2] "
        "no es determinista."
    )
    assert identificar_objeto(_r("Capacidad residual mínima")) == "CAPACIDAD_RESIDUAL"


# ─── 4. Mismo objeto en capítulos distintos NO se fusiona ────────────────────

def test_mismo_objeto_distinto_capitulo_no_se_fusiona():
    """
    'RUP para experiencia' (3.5) y 'RUP para capacidad financiera' (3.9) son
    verificaciones distintas del mismo documento.
    """
    a = clave_agrupacion(_r("RUP vigente y en firme", "3.5 EXPERIENCIA"))
    b = clave_agrupacion(_r("RUP vigente y en firme", "3.9 CAPACIDAD FINANCIERA"))
    assert a is not None and b is not None
    # Clave: (objeto, aspecto, sujeto, capítulo). El capítulo es el ÚLTIMO
    # componente; el eje `sujeto` se insertó antes en la v2.0.0 [K4].
    assert a[0] == b[0] == "RUP"
    assert a[-1] != b[-1], f"Mismo capítulo para 3.5 y 3.9: {a[-1]!r}"
    assert a != b, "La clave no distingue el capítulo: se fusionarían"


# ─── 5. Sin objeto → queda solo y se registra [K1][K3] ───────────────────────

def test_sin_objeto_devuelve_none():
    obj = identificar_objeto(_r("Zeta omega delta kappa inventada"))
    assert obj is None
    assert clave_agrupacion(_r("Zeta omega delta kappa inventada")) is None


def test_sin_objeto_se_registra_en_log(tmp_path):
    """[K3] El catálogo crece con datos reales: los faltantes se registran."""
    log = tmp_path / "faltantes.jsonl"
    reqs = [
        _r("RUP vigente y en firme"),
        _r("Zeta omega delta kappa inventada"),
    ]
    rep = registrar_no_identificados(reqs, pliego="test", ruta_log=log)

    assert rep["total"] == 2
    assert rep["con_objeto"] == 1
    assert rep["sin_objeto"] == 1
    assert log.exists(), "No se escribió el JSONL de faltantes"
    lineas = [json.loads(l) for l in log.read_text("utf-8").splitlines() if l.strip()]
    assert len(lineas) == 1
    assert "Zeta" in lineas[0]["nombre"]
    assert lineas[0]["pliego"] == "test"


# ─── 6. aspecto=None no agrupa ───────────────────────────────────────────────

def test_aspecto_none_no_agrupa():
    """
    [B11] `aspecto=None` significa "ningún aspecto encajó", no "comparten
    algo". Agrupar por ausencia de clasificación formó un grupo de 11 con
    fechas de ejecución, NSR-98/NSR-10, área construida y cesión.
    """
    from pipeline.src.clasificador import _clave_grupo

    req = _r("Experiencia con contratos con particulares", "3.5 EXPERIENCIA")
    k = clave_agrupacion(req)
    assert k is not None and k[0] == "EXPERIENCIA_CONTRATOS"
    assert k[1] is None, "Este fixture debe quedar sin aspecto para el test"
    assert _clave_grupo(req) is None, (
        "Con aspecto=None el requisito debe quedar SOLO, no agruparse con "
        "todos los demás que tampoco tienen aspecto."
    )


# ─── 7. Los tres cortes de unidad son incompatibles entre sí ─────────────────

def test_unidades_de_monto_son_aspectos_distintos():
    """
    5 contratos, 10% y 75 SMMLV no se comparan. Un aspecto `monto` único los
    metía en el mismo grupo y perdía los cuatro valores evaluables.
    """
    cantidad   = identificar_aspecto(_r("Número máximo de contratos acreditables"))
    porcentaje = identificar_aspecto(_r("Porcentaje de participación mínima"))
    valor      = identificar_aspecto(_r("Valor mínimo acumulado en SMMLV"))

    assert cantidad == "cantidad"
    assert porcentaje == "porcentaje"
    assert valor == "valor"
    assert len({cantidad, porcentaje, valor}) == 3


# ─── 8. Normalización ────────────────────────────────────────────────────────

def test_normalizar_quita_tildes_y_colapsa_espacios():
    assert normalizar("  Índice   de  LIQUIDEZ  ") == "indice de liquidez"
    assert normalizar("Razón de Cobertura") == "razon de cobertura"


# ─── 9. Determinismo ─────────────────────────────────────────────────────────

def test_identificacion_es_determinista():
    """Sin modelo: dos llamadas idénticas dan el mismo resultado."""
    req = _r("Capacidad residual de contratación", "3.10.1")
    resultados = {clave_agrupacion(req) for _ in range(5)}
    assert len(resultados) == 1


# ─── 10. Regresión sobre Paicol ──────────────────────────────────────────────

_PAICOL = _ROOT / "resultados_evaluacion" / "paicol_2026_resultado.json"
_COBERTURA_MINIMA = 0.85   # medida: 96,3% — el piso de diseño es 70%


@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol no disponible (gitignored)")
def test_cobertura_paicol_no_baja():
    """
    Si la cobertura cae bajo el 70%, el catálogo necesita más entradas antes
    de sustituir la regla de coherencia. Medido: 96,3%.
    """
    raw = json.loads(_PAICOL.read_text("utf-8"))
    objs = [Requisito.model_validate(r) for r in raw["requisitos"]]
    rep = registrar_no_identificados(objs, pliego="paicol_regresion",
                                     ruta_log=_ROOT / "logs" / "_test_regresion.jsonl")
    assert rep["cobertura"] >= _COBERTURA_MINIMA, (
        f"Cobertura del catálogo {rep['cobertura']:.1%}, bajo el mínimo "
        f"{_COBERTURA_MINIMA:.0%}. Top sin objeto: "
        f"{[e['nombre'][:40] for e in rep['top_sin_objeto'][:3]]}"
    )


@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol no disponible (gitignored)")
def test_paicol_crp_calculo_disuelto():
    """
    La bolsa que motivó el catálogo: 13 fragmentos unidos por "residual" que
    mezclaban capacidad residual, CO ingresos, tarjeta profesional y liquidez CF.
    """
    raw = json.loads(_PAICOL.read_text("utf-8"))
    objs = [Requisito.model_validate(r) for r in raw["requisitos"]]
    res = consolidar(objs)

    for r in res.requisitos:
        n = len(r.nombres_absorbidos) + 1
        if "capacidad residual" in r.nombre.lower():
            assert n <= 5, (
                f"'{r.nombre[:50]}' agrupa {n} miembros: volvió a formarse "
                "la bolsa crp_calculo."
            )
        # Ningún grupo debe mezclar capacidad residual con liquidez o tarjeta
        absorbidos = " ".join(r.nombres_absorbidos).lower()
        if "capacidad residual" in r.nombre.lower():
            assert "tarjeta profesional" not in absorbidos, (
                "La tarjeta profesional volvió a caer dentro de capacidad residual."
            )


@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol no disponible (gitignored)")
def test_paicol_ningun_grupo_supera_ocho_miembros():
    """
    Techo de tamaño de grupo. El único de >5 conocido es
    (EXPERIENCIA_CONTRATOS, acreditacion, 3) con 8 — ver D6 en
    ESTADO_PIPELINE.md. Si aparece uno mayor, la clave volvió a ser gruesa.
    """
    raw = json.loads(_PAICOL.read_text("utf-8"))
    objs = [Requisito.model_validate(r) for r in raw["requisitos"]]
    res = consolidar(objs)

    grandes = [
        (len(r.nombres_absorbidos) + 1, r.nombre)
        for r in res.requisitos if len(r.nombres_absorbidos) + 1 > 8
    ]
    assert not grandes, (
        f"Grupos de más de 8 miembros: {grandes}. La clave "
        "(objeto, aspecto, capítulo) volvió a ser demasiado gruesa."
    )


@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol no disponible (gitignored)")
def test_paicol_un_solo_grupo_con_magnitudes_incompatibles():
    """
    El test de [B9] sigue siendo el detector de bolsas. Tras partir `monto`
    en cantidad/porcentaje/valor sólo queda uno: el 50%/5% de integrante
    principal vs demás integrantes (ver D7 — falta el eje `sujeto`).
    """
    raw = json.loads(_PAICOL.read_text("utf-8"))
    objs = [Requisito.model_validate(r) for r in raw["requisitos"]]
    res = consolidar(objs)

    disparan = []
    for r in res.requisitos:
        vals = [a["valor_umbral"] for a in r.umbrales_alternativos]
        if r.valor_umbral is not None:
            vals.append(r.valor_umbral)
        if magnitudes_incompatibles(vals):
            disparan.append((r.nombre[:46], sorted(set(vals))))

    assert len(disparan) <= 1, (
        f"{len(disparan)} grupos con magnitudes incompatibles (se esperaba 1, "
        f"el de D7): {disparan}"
    )
