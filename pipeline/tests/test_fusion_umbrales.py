# -*- coding: utf-8 -*-
"""
tests/test_fusion_umbrales.py — [B8] La fusión no debe perder umbrales.

Los tests previos de fusionar_fragmentos() verificaban que el TEXTO se
conservara. Nadie probó el UMBRAL: 35 de 42 umbrales numéricos de Paicol se
descartaban al elegir un primario sin valor_umbral.

Patrón del defecto: la prueba verificaba que la función hiciera lo que dice su
nombre (fusionar), no que conservara todo lo que importa.

Sin API. Sin disco (salvo el test de regresión sobre Paicol, que se salta si
el archivo no está disponible).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.src.extractor import Requisito
from pipeline.src.clasificador import fusionar_fragmentos, consolidar
from pipeline.src.evaluator import evaluar_empresa, PerfilEmpresa


def _req(
    nombre: str,
    numeral: str,
    umbral: float | None = None,
    operador: str | None = None,
    unidad: str | None = None,
    literal: str = "texto del requisito",
    pagina: int | None = None,
) -> Requisito:
    return Requisito(
        nombre=nombre,
        categoria="financiero",
        fuente_numeral=numeral,
        exigido_literal=literal,
        valor_umbral=umbral,
        operador=operador,
        unidad=unidad,
        pagina_origen=pagina,
    )


def _fusionar_grupo(miembros: list[Requisito]) -> Requisito:
    """Fusiona y devuelve el requisito resultante del grupo crp_calculo."""
    salida, _ = fusionar_fragmentos(miembros)
    assert len(salida) == 1, f"Se esperaba 1 requisito fusionado, salieron {len(salida)}"
    return salida[0]


# ─── 1. Primario sin umbral + miembro con umbral ─────────────────────────────

def test_umbral_de_miembro_no_primario_se_conserva():
    """
    Caso real del grupo 'ingresos operacionales':
      A (3.10.1)    literal largo, SIN umbral   ← elegido primario
      B (3.10.1 A)  USD 125.000, umbral=125000  ← se descartaba
    El umbral de B debe sobrevivir en el resultado.
    """
    primario_esperado = _req(
        "Zeta organizativa", "3.10.1",
        literal="Texto extenso que hace de este el primario por longitud del literal. " * 4,
    )
    portador = _req(
        "Omega numerica", "3.10.1 A",
        umbral=125_000.0, operador=">=", unidad="USD",
        literal="corto",
    )

    r = _fusionar_grupo([primario_esperado, portador])

    assert r.valor_umbral == 125_000.0, (
        f"El umbral se perdió: valor_umbral={r.valor_umbral}. "
        "fusionar_fragmentos() está descartando los campos evaluables de los "
        "miembros no-primarios."
    )
    assert r.operador == ">="
    assert r.unidad == "USD"
    assert r.conflicto_umbral is False


def test_umbral_conserva_su_fuente_numeral():
    """El umbral propagado debe recordar de qué numeral salió, para poder citarlo."""
    primario = _req("Zeta organizativa", "3.10.1", literal="largo " * 30)
    portador = _req("Omega", "3.10.1 A", umbral=125_000.0, operador=">=", literal="c")

    r = _fusionar_grupo([primario, portador])

    assert r.fuente_umbral_numeral == "3.10.1 A", (
        f"fuente_umbral_numeral={r.fuente_umbral_numeral!r}. "
        "Sin trazabilidad no se puede citar de dónde salió el umbral."
    )


# ─── 2. Primario con umbral + miembro sin él ─────────────────────────────────

def test_umbral_del_primario_no_se_pierde():
    """Si el primario trae el umbral y otro miembro no, el del primario queda."""
    primario = _req(
        "Zeta organizativa", "3.10.1",
        umbral=125_000.0, operador=">=",
        literal="Texto extenso para que sea el primario. " * 5,
    )
    otro = _req("Zeta de soporte", "3.10.1 A", literal="c")

    r = _fusionar_grupo([primario, otro])

    assert r.valor_umbral == 125_000.0
    assert r.operador == ">="
    assert r.conflicto_umbral is False


# ─── 3. Dos miembros con umbrales DISTINTOS → conflicto ──────────────────────

def test_umbrales_distintos_marcan_conflicto():
    """
    Caso real: 'Número máximo de contratos acreditables' vale 5 (general),
    6 (mipyme) y 7 (mipyme + empresa de mujeres). No se elige ninguno.
    """
    primario = _req(
        "Kappa maxima admisible", "3.5.1",
        literal="Texto largo del primario. " * 6,
    )
    v5 = _req("Kappa general", "3.5.1 A", umbral=5.0, operador="<=", literal="c")
    v6 = _req("Kappa reducida", "3.5.1 B", umbral=6.0, operador="<=", literal="c")

    r = _fusionar_grupo([primario, v5, v6])

    assert r.conflicto_umbral is True, (
        "Dos umbrales distintos deben marcar conflicto_umbral=True, "
        "no elegir uno en silencio."
    )
    assert len(r.umbrales_alternativos) == 2, (
        f"umbrales_alternativos tiene {len(r.umbrales_alternativos)} entradas; "
        "deben conservarse ambos."
    )
    valores = {a["valor_umbral"] for a in r.umbrales_alternativos}
    assert valores == {5.0, 6.0}
    # Ninguna rama debe poder evaluar a ciegas
    assert r.valor_umbral is None, (
        "Con conflicto, valor_umbral debe quedar None: un consumidor que ignore "
        "la bandera daría un veredicto falso."
    )


def test_umbrales_iguales_no_son_conflicto():
    """Dos miembros con el MISMO umbral no son conflicto: es el mismo dato repetido."""
    primario = _req("Sigma temporal", "3.3", literal="Texto largo. " * 6)
    a = _req("Sigma temporal A", "3.3 A", umbral=30.0, operador="<=", unidad="días", literal="c")
    b = _req("Sigma temporal B", "3.3 B", umbral=30.0, operador="<=", unidad="días", literal="c")

    r = _fusionar_grupo([primario, a, b])

    assert r.conflicto_umbral is False
    assert r.valor_umbral == 30.0


# ─── 4. El criterio estructurado se propaga ──────────────────────────────────

def test_criterio_de_miembro_se_propaga():
    """Si un miembro trae un objeto Criterio y el primario no, debe propagarse."""
    from pipeline.src.criterios import UmbralSimple

    criterio = UmbralSimple(
        campo_perfil="financiero.indice_liquidez",
        operador=">=", valor=1.2,
        fuente_numeral="3.10.1 A", confianza="alta",
    )
    primario = _req("Zeta indicadora", "3.10.1", literal="Texto largo. " * 6)
    portador = _req("Zeta detalle", "3.10.1 A", literal="c")
    portador.criterio = criterio

    r = _fusionar_grupo([primario, portador])

    assert r.criterio is not None, (
        "El objeto Criterio del miembro no-primario se perdió en la fusión."
    )
    assert r.criterio.campo_perfil == "financiero.indice_liquidez"


def test_pagina_origen_se_propaga_si_falta():
    """Si el primario no tiene página y un miembro sí, se propaga."""
    primario = _req("Zeta basica", "3.10.1", literal="Texto largo. " * 6)
    portador = _req("Zeta anexa", "3.10.1 A", literal="c", pagina=42)

    r = _fusionar_grupo([primario, portador])
    assert r.pagina_origen == 42


# ─── 5. El evaluador NO evalúa un requisito en conflicto ─────────────────────

def test_evaluador_reporta_conflicto_sin_evaluar():
    """conflicto_umbral=True ⇒ estado 'revisar_manual', nunca cumple/no_cumple."""
    req = _req("Kappa maxima", "3.5.1")
    req.conflicto_umbral = True
    req.umbrales_alternativos = [
        {"valor_umbral": 5.0, "operador": "<=", "unidad": None,
         "fuente_numeral": "3.5.1 A", "nombre": "general"},
        {"valor_umbral": 6.0, "operador": "<=", "unidad": None,
         "fuente_numeral": "3.5.1 B", "nombre": "mipyme"},
    ]

    perfil = PerfilEmpresa(
        nombre="Test SAS", es_mipyme=True,
        financiero={"indice_liquidez": 1.5},
    )
    ev = evaluar_empresa(perfil, [req])
    item = ev["items"][0]

    assert item["estado"] == "revisar_manual", (
        f"estado={item['estado']!r}: el evaluador está resolviendo un umbral "
        "ambiguo en vez de reportarlo."
    )
    assert len(item["umbrales_alternativos"]) == 2
    # No debe contarse como cumplido en el score
    assert ev["desglose"]["financiero"]["cumple"] == 0
    assert ev["desglose"]["financiero"]["no_cumple"] == 0


# ─── 6. Regresión numérica sobre Paicol ──────────────────────────────────────

_PAICOL = _ROOT / "resultados_evaluacion" / "paicol_2026_resultado.json"


def _contar_valores(reqs: list[Requisito]) -> tuple[int, int]:
    """(umbrales directos, umbrales guardados como alternativa)."""
    directos = sum(1 for r in reqs if r.valor_umbral is not None)
    alternativas = sum(len(r.umbrales_alternativos) for r in reqs)
    return directos, alternativas


@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol_2026_resultado.json no disponible (gitignored)")
def test_regresion_paicol_fusion_no_pierde_umbrales():
    """
    [B8] Alcance de la corrección: la FUSIÓN no debe descartar umbrales.

    Antes: 42 crudos → 17 tras fusión (25 perdidos al elegir primario).
    Ahora: 42 crudos → 38 valores (17 directos + 21 alternativas).

    Los 4 de diferencia son valores IDÉNTICOS dentro de un mismo grupo
    (varios fragmentos con "30 días"), que colapsan en una sola entrada.
    Eso es deduplicación correcta, no pérdida.
    """
    from pipeline.src import clasificador as K

    raw = json.loads(_PAICOL.read_text("utf-8"))
    crudos = raw["requisitos"]
    n_crudos = sum(1 for r in crudos if r.get("valor_umbral") is not None)
    assert n_crudos == 42, f"El fixture cambió: {n_crudos} umbrales"

    objs = [Requisito.model_validate(r) for r in crudos]
    K._corregir_numerales(objs)
    for r in objs:
        c = K.clasificar_requisito(r)
        r.criticidad = c.criticidad

    dedup, _ = K.deduplicar(objs)
    d_dedup, a_dedup = _contar_valores(dedup)
    assert d_dedup + a_dedup == 42, (
        f"La deduplicación perdió umbrales: {d_dedup + a_dedup} de 42."
    )

    fus, _ = K.fusionar_fragmentos(dedup)
    d_fus, a_fus = _contar_valores(fus)

    # El invariante es que no se pierda ninguna FIRMA distinta
    # (valor, operador, unidad) — no el número de ocurrencias, que baja
    # legítimamente cuando la agrupación cambia y firmas idénticas colapsan.
    # Con el catálogo de objetos [B11] la agrupación es más fina: 42 → 36
    # ocurrencias, pero las 28 firmas distintas se conservan íntegras.
    firmas_crudo = {
        (r.get("valor_umbral"), r.get("operador"), r.get("unidad"))
        for r in crudos if r.get("valor_umbral") is not None
    }
    firmas_fus: set = set()
    for r in fus:
        if r.valor_umbral is not None:
            firmas_fus.add((r.valor_umbral, r.operador, r.unidad))
        for a in r.umbrales_alternativos:
            firmas_fus.add((a["valor_umbral"], a["operador"], a["unidad"]))

    perdidas = firmas_crudo - firmas_fus
    assert not perdidas, (
        f"{len(perdidas)} firmas de umbral desaparecieron en la fusión: "
        f"{sorted(perdidas)[:5]}. fusionar_fragmentos() está descartando "
        "campos evaluables."
    )
    assert d_fus + a_fus >= 34, (
        f"Sólo {d_fus + a_fus} ocurrencias de umbral tras la fusión "
        f"({d_fus} directos + {a_fus} alternativas); se esperaban >=34."
    )


@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol_2026_resultado.json no disponible (gitignored)")
def test_regresion_paicol_descartes_con_umbral_quedan_trazados():
    """
    [C1] Los requisitos descartados por regla `_descartar` que traían umbral
    deben quedar registrados, no desaparecer en silencio.

    En Paicol son 6 (variantes de 'contratos acreditables' para proponente
    plural y mipyme). Es una vía de pérdida DISTINTA de [B8]: no la causa la
    elección de primario sino las reglas de descarte de _CLAVE_FUSION.
    """
    raw = json.loads(_PAICOL.read_text("utf-8"))
    objs = [Requisito.model_validate(r) for r in raw["requisitos"]]
    res = consolidar(objs)

    nombres_finales     = {r.nombre for r in res.requisitos}
    nombres_descartados = {d["nombre"] for d in res.descartados}
    # Un miembro absorbido por la fusión no va a `descartados`: queda trazado
    # en numerales_fuentes del primario que lo absorbió.
    numerales_absorbidos = {
        n for r in res.requisitos for n in r.numerales_fuentes
    }

    huerfanos = [
        r["nombre"] for r in raw["requisitos"]
        if r.get("valor_umbral") is not None
        and r["nombre"] not in nombres_finales
        and r["nombre"] not in nombres_descartados
        and r.get("fuente_numeral") not in numerales_absorbidos
    ]
    assert not huerfanos, (
        f"{len(huerfanos)} requisitos con umbral desaparecieron sin quedar "
        f"trazados ni en descartados ni en numerales_fuentes (viola C1): "
        f"{huerfanos[:5]}"
    )

    # Los descartados por regla `_descartar` que traían umbral: vía de pérdida
    # distinta de [B8]. Deben estar registrados con motivo.
    descartados_con_umbral = [
        d for d in res.descartados
        if any(r["nombre"] == d["nombre"] and r.get("valor_umbral") is not None
               for r in raw["requisitos"])
    ]
    for d in descartados_con_umbral:
        assert d.get("motivo"), f"Descarte sin motivo registrado: {d['nombre']}"


@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol_2026_resultado.json no disponible (gitignored)")
def test_regresion_paicol_umbrales_clave_sobreviven():
    """Los 4 casos citados como perdidos deben sobrevivir a la consolidación."""
    raw = json.loads(_PAICOL.read_text("utf-8"))
    objs = [Requisito.model_validate(r) for r in raw["requisitos"]]
    res = consolidar(objs)

    def _valores_presentes() -> set[float]:
        vals: set[float] = set()
        for r in res.requisitos:
            if r.valor_umbral is not None:
                vals.add(r.valor_umbral)
            for a in r.umbrales_alternativos:
                vals.add(a["valor_umbral"])
        return vals

    presentes = _valores_presentes()
    for etiqueta, valor in [
        ("Capacidad de organización CO", 125_000.0),
        ("Experiencia valor mínimo (1-2 contratos)", 75.0),
        ("Garantía de seriedad", 10.0),
        ("Porcentaje de participación", 100.0),
    ]:
        assert valor in presentes, (
            f"El umbral de '{etiqueta}' ({valor}) no sobrevivió a la consolidación."
        )
