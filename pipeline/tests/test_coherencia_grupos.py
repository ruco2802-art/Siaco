# -*- coding: utf-8 -*-
"""
tests/test_coherencia_grupos.py — [B9] Los grupos de fusión deben ser coherentes.

_CLAVE_FUSION agrupa por prefijo de numeral, lo que asume que todo lo que cae
bajo "3.5" habla de lo mismo. En los Documentos Tipo del CCE eso es falso por
diseño: las secciones organizan por TEMA, no por requisito.

Consecuencia medida en Paicol antes de la corrección: 21 requisitos de
experiencia fusionados bajo el nombre "Exclusión de tipos de obras no válidas",
y 16 documentos societarios bajo "Acto de creación de entidad estatal" — que el
evaluador marcaba no_aplica, descartando 15 exigencias reales para una PYME.

Sin API.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.src.extractor import Requisito
from pipeline.src.clasificador import (
    consolidar,
    fusionar_fragmentos,
    grupo_es_coherente,
    objeto_comun,
    magnitudes_incompatibles,
)


def _r(nombre: str, numeral: str, umbral: float | None = None,
       operador: str | None = None) -> Requisito:
    return Requisito(
        nombre=nombre, categoria="experiencia", fuente_numeral=numeral,
        exigido_literal=f"Literal de {nombre}.", valor_umbral=umbral, operador=operador,
    )


# [B11] Estos tests prueban el FALLBACK por prefijo y la regla de coherencia
# `grupo_es_coherente()`, que sólo actúan cuando el catálogo de objetos no
# reconoce el requisito. Los fixtures usan términos inventados ("Zeta",
# "Omega") en vez de vocabulario real del dominio: con nombres reales la clave
# primaria la da el catálogo y esta ruta no se ejercitaría.
# La agrupación por catálogo se prueba en test_catalogo.py.


# ─── a) Grupo grande SIN objeto común → no se fusiona ────────────────────────

def test_grupo_sin_objeto_comun_no_se_fusiona():
    """
    Reproduce la bolsa `experiencia_rup` de Paicol en pequeño: fragmentos que
    comparten numeral pero hablan de cosas distintas.
    """
    miembros = [
        _r("Zeta vigencia maxima treinta", "3.5.1", 30.0, "<="),
        _r("Omega tope superior quinquenal", "3.5.1", 5.0, "<="),
        _r("Delta participativa territorial", "3.5.1", 10.0, ">="),
        _r("Kappa actividades sectoriales", "3.5.1", 3.0, "<="),
        _r("Lambda exclusiones tipificadas", "3.5.1"),
        _r("Sigma terminaciones anticipadas", "3.5.1"),
    ]
    coherente, obj = grupo_es_coherente(miembros)
    assert coherente is False, (
        f"El grupo se consideró coherente con objeto={obj!r}. Sus miembros "
        "no comparten ningún término: no son fragmentos de un requisito."
    )

    salida, _ = fusionar_fragmentos(miembros)
    assert len(salida) == len(miembros), (
        f"Se fusionaron {len(miembros)} fragmentos incoherentes en {len(salida)}. "
        "Ante la duda NO se fusiona: fusionar requisitos distintos produce un "
        "veredicto falso sobre uno de ellos."
    )


# ─── b) Grupo grande CON objeto común → sí se fusiona ────────────────────────

def test_grupo_con_objeto_comun_si_se_fusiona():
    """5 fragmentos que comparten un objeto son un solo requisito."""
    miembros = [
        _r("Zeta vigente y en firme", "3.5.1"),
        _r("Zeta expedida con antelacion maxima", "3.5.1", 30.0, "<="),
        _r("Zeta renovada anualmente", "3.5.1"),
        _r("Zeta de la sucursal foranea", "3.5.1"),
        _r("Diligenciamiento de la Zeta", "3.5.1"),
    ]
    coherente, obj = grupo_es_coherente(miembros)
    assert coherente is True, "Cinco fragmentos sobre la misma Zeta deben fusionarse"
    assert obj is not None and obj.startswith("zeta")

    salida, _ = fusionar_fragmentos(miembros)
    assert len(salida) == 1, f"Se esperaba 1 requisito fusionado, salieron {len(salida)}"


def test_grupos_pequenos_se_fusionan_sin_verificar():
    """Con ≤4 fragmentos el riesgo de bolsa es bajo; no se aplica la regla."""
    miembros = [
        _r("Existencia y representación - persona natural colombiana", "3.3"),
        _r("Existencia y representación - persona natural extranjera", "3.3"),
        _r("Existencia y representación - extranjera con residencia", "3.3"),
    ]
    coherente, _ = grupo_es_coherente(miembros)
    assert coherente is True


# ─── c) Magnitudes incompatibles → señal de agrupación errónea ───────────────

def test_magnitudes_incompatibles_detecta():
    """30 días, 5 contratos y 10% no son variantes de un mismo umbral."""
    assert magnitudes_incompatibles([30.0, 5.0, 10.0]) is True
    assert magnitudes_incompatibles([1.1, 1.2]) is False
    assert magnitudes_incompatibles([5.0]) is False
    assert magnitudes_incompatibles([]) is False


_PAICOL = _ROOT / "resultados_evaluacion" / "paicol_2026_resultado.json"

# Bolsa que sigue sin atraparse tras [B10]: `crp_calculo` sobrevive porque sus
# miembros comparten "residual" (7 de 13), un término específico y no genérico,
# aunque el grupo mezcle capacidad residual con CO ingresos, tarjeta profesional
# e índice de liquidez CF. Requiere el catálogo de objetos (ver ESTADO_PIPELINE).
# El test falla si aparece un grupo incoherente FUERA de esta lista.
_BOLSAS_CONOCIDAS = {"crp_calculo"}


@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol no disponible (gitignored)")
def test_no_aparecen_bolsas_nuevas_con_umbrales_incompatibles():
    """
    Ningún grupo fusionado debe aportar umbrales de magnitudes incompatibles,
    salvo las bolsas ya conocidas. Detecta regresiones sin revisión manual.
    """
    raw = json.loads(_PAICOL.read_text("utf-8"))
    objs = [Requisito.model_validate(r) for r in raw["requisitos"]]
    res = consolidar(objs)

    incoherentes: list[str] = []
    for r in res.requisitos:
        valores = [a["valor_umbral"] for a in r.umbrales_alternativos]
        if r.valor_umbral is not None:
            valores.append(r.valor_umbral)
        if magnitudes_incompatibles(valores):
            incoherentes.append(f"{r.nombre[:50]} (umbrales: {sorted(set(valores))})")

    # Traducir a claves de grupo conocidas es frágil; se comprueba el conteo.
    assert len(incoherentes) <= len(_BOLSAS_CONOCIDAS), (
        f"Aparecieron {len(incoherentes)} grupos con umbrales de magnitudes "
        f"incompatibles, más de las {len(_BOLSAS_CONOCIDAS)} bolsas conocidas:\n  "
        + "\n  ".join(incoherentes)
    )


# ─── d) Regresión Paicol: RUP y "exclusión de obras" separados ───────────────

@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol no disponible (gitignored)")
def test_paicol_rup_separado_de_exclusion_obras():
    """
    El caso que originó [B9]: 21 fragmentos de experiencia fusionados bajo
    'Exclusión de tipos de obras no válidas', incluido el RUP.
    """
    raw = json.loads(_PAICOL.read_text("utf-8"))
    objs = [Requisito.model_validate(r) for r in raw["requisitos"]]
    res = consolidar(objs)

    for r in res.requisitos:
        nombre_l = r.nombre.lower()
        fuentes = " ".join(r.numerales_fuentes).lower()
        if "exclusi" in nombre_l and "obras" in nombre_l:
            assert len(r.numerales_fuentes) <= 4, (
                f"'{r.nombre[:50]}' absorbió {len(r.numerales_fuentes)} numerales: "
                "volvió a formarse la bolsa de experiencia."
            )
        del fuentes

    con_rup = [r for r in res.requisitos if "rup" in r.nombre.lower().split()]
    assert con_rup, "El RUP desapareció como requisito propio tras consolidar"


@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol no disponible (gitignored)")
def test_paicol_documentos_societarios_separados():
    """
    'Acto de creación de entidad estatal' arrastraba 15 documentos societarios
    que SÍ aplican a una PYME privada. El evaluador los marcaba no_aplica.
    """
    raw = json.loads(_PAICOL.read_text("utf-8"))
    objs = [Requisito.model_validate(r) for r in raw["requisitos"]]
    res = consolidar(objs)

    nombres = [r.nombre.lower() for r in res.requisitos]
    for etiqueta, aguja in [
        ("objeto social",          "objeto social"),
        ("revisor fiscal",         "revisor fiscal"),
        ("autorización del órgano", "órgano social"),
    ]:
        assert any(aguja in n for n in nombres), (
            f"'{etiqueta}' no existe como requisito propio: sigue absorbido "
            "en la bolsa de documentos societarios."
        )

    acto = [r for r in res.requisitos if "acto de creaci" in r.nombre.lower()]
    if acto:
        assert len(acto[0].numerales_fuentes) <= 4, (
            f"'Acto de creación de entidad estatal' absorbió "
            f"{len(acto[0].numerales_fuentes)} numerales."
        )


# ─── e) El nombre del grupo viene del objeto común ───────────────────────────

def test_nombre_del_grupo_corresponde_al_objeto_comun():
    """
    Antes el nombre lo fijaba el fragmento con numeral más profundo y literal
    más largo — por accidente. Debe venir del objeto que comparte la mayoría.
    """
    miembros = [
        _r("Zeta vigente y en firme", "3.5.1"),
        _r("Zeta expedida con antelacion maxima", "3.5.1", 30.0, "<="),
        _r("Zeta renovada anualmente", "3.5.1"),
        _r("Zeta de la sucursal foranea", "3.5.1"),
        # Literal larguísimo: bajo la regla vieja se quedaba con el nombre
        Requisito(
            nombre="Apreciaciones sobre la validez instrumental",
            categoria="experiencia", fuente_numeral="3.5.1.9",
            exigido_literal="Texto extenso que antes ganaba la elección de primario. " * 20,
        ),
    ]
    salida, _ = fusionar_fragmentos(miembros)
    assert len(salida) == 1
    assert "zeta" in salida[0].nombre.lower(), (
        f"El grupo se llama '{salida[0].nombre}'. El nombre debe venir del "
        "objeto común (Zeta), no del fragmento con el literal más largo."
    )


def test_objeto_comun_ignora_palabras_genericas():
    """'proponente' y 'contrato' aparecen en casi todo: no identifican un objeto."""
    miembros = [
        _r("Contrato del proponente para obra", "3.5.1"),
        _r("Contrato del proponente para servicio", "3.5.1"),
        _r("Contrato del proponente para suministro", "3.5.1"),
        _r("Contrato del proponente para consultoría", "3.5.1"),
        _r("Contrato del proponente para interventoría", "3.5.1"),
    ]
    assert objeto_comun(miembros) is None, (
        "Palabras genéricas del dominio no deben contar como objeto común."
    )


# ─── f) B8 sigue intacto: los umbrales se propagan ───────────────────────────

def test_b8_sigue_funcionando_tras_b9():
    """La regla de coherencia no debe romper la propagación de umbrales."""
    miembros = [
        _r("Zeta vigente y en firme", "3.5.1"),
        _r("Zeta expedida con antelacion maxima", "3.5.1", 30.0, "<="),
        _r("Zeta renovada anualmente", "3.5.1"),
        _r("Zeta de la sucursal foranea", "3.5.1"),
        _r("Diligenciamiento de la Zeta", "3.5.1"),
    ]
    salida, _ = fusionar_fragmentos(miembros)
    assert len(salida) == 1
    assert salida[0].valor_umbral == 30.0, (
        "El umbral del miembro no-primario se perdió: B9 rompió B8."
    )
    assert salida[0].fuente_umbral_numeral == "3.5.1"


@pytest.mark.skipif(not _PAICOL.exists(), reason="paicol no disponible (gitignored)")
def test_b8_paicol_umbrales_no_bajan_tras_b9():
    """Tras B9 deben conservarse al menos tantos valores de umbral como antes."""
    raw = json.loads(_PAICOL.read_text("utf-8"))
    objs = [Requisito.model_validate(r) for r in raw["requisitos"]]
    res = consolidar(objs)
    directos = sum(1 for r in res.requisitos if r.valor_umbral is not None)
    alts = sum(len(r.umbrales_alternativos) for r in res.requisitos)
    assert directos + alts >= 32, (
        f"Sólo {directos + alts} valores de umbral conservados "
        f"({directos} directos + {alts} alternativas); antes de B9 eran 32."
    )
    # B9 debe AUMENTAR los evaluables directamente: menos fusiones espurias
    assert directos >= 20, (
        f"Sólo {directos} umbrales evaluables directamente; se esperaban ≥20 "
        "al deshacer las fusiones incoherentes."
    )
