# -*- coding: utf-8 -*-
"""
Tests de la escala de cuatro grados y del origen de los datos que faltan.

Lo que estos tests protegen, más allá de que las funciones corran:

1. Que los umbrales sigan sin fijarse. Si alguien pone un número en
   `UMBRAL_SIN_CONCEPTO` sin haber medido tres o cuatro perfiles reales, el
   test falla y le recuerda la condición.
2. Que `no_viable` no dependa de ningún umbral: un incumplimiento manda,
   aunque todo lo demás esté resuelto.
3. Que `no_preguntado` se distinga de `campo_sin_respuesta`, que es la
   diferencia entre un hueco nuestro y un dato de la empresa.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import concepto  # noqa: E402
from src.extractor import Requisito  # noqa: E402


# ── 1 · Los umbrales no están fijados ──────────────────────────────────────

def test_los_umbrales_proporcionales_siguen_sin_fijarse():
    """
    Condición para fijarlos: tres o cuatro análisis con perfiles de clientes
    reales. Con 13 habilitantes numéricos cada requisito vale 7,7 puntos y
    cualquier corte queda a un requisito de distancia del único caso medido.
    """
    assert concepto.UMBRAL_SIN_CONCEPTO is None, (
        "UMBRAL_SIN_CONCEPTO se fijó. Sólo es legítimo con 3-4 perfiles reales "
        "medidos; con un solo caso el corte cae a menos de un requisito de "
        "distancia y decide por redondeo.")
    assert concepto.UMBRAL_VIABLE is None, (
        "UMBRAL_VIABLE se fijó. Mientras sea None, VIABLE exige la condición "
        "absoluta (cero abiertos, todo resuelto), que no necesita calibración.")


def test_el_concepto_declara_si_el_umbral_estaba_activo():
    """El informe tiene que poder decir con qué reglas se emitió."""
    r = concepto.emitir(n_hab_numericos=13, n_resueltos=7,
                        n_incumplidos=0, n_abiertos=5)
    assert r["umbral_sin_concepto_activo"] is False
    assert r["umbral_viable_activo"] is False


# ── 2 · La escala ──────────────────────────────────────────────────────────

def test_un_incumplimiento_manda_sobre_todo_lo_demas():
    """NO VIABLE es un hecho medido: no lo diluye tener todo resuelto."""
    r = concepto.emitir(n_hab_numericos=13, n_resueltos=13,
                        n_incumplidos=1, n_abiertos=0)
    assert r["concepto"] == "no_viable"
    assert "1 requisito habilitante resultó incumplido" in r["motivo"]


def test_sin_habilitantes_numericos_no_hay_concepto():
    """Condición absoluta, no proporción: no había nada que medir."""
    r = concepto.emitir(0, 0, 0, 0)
    assert r["concepto"] == "sin_concepto"
    assert "nada que medir" in r["motivo"]


def test_cero_resueltos_no_da_concepto_aunque_no_haya_umbral():
    r = concepto.emitir(n_hab_numericos=13, n_resueltos=0,
                        n_incumplidos=0, n_abiertos=0)
    assert r["concepto"] == "sin_concepto"
    assert "ninguno de los 13" in r["motivo"]


def test_paicol_sale_con_salvedades_y_el_motivo_trae_los_numeros():
    """El caso real: 0 incumplidos, 7/13 resueltos, 17 puntos abiertos."""
    r = concepto.emitir(n_hab_numericos=13, n_resueltos=7,
                        n_incumplidos=0, n_abiertos=17)
    assert r["concepto"] == "con_salvedades"
    assert "17 puntos sin resolver" in r["motivo"]
    assert "6 de 13" in r["motivo"]
    assert r["tasa_resueltos"] == pytest.approx(7 / 13)


def test_viable_exige_cero_abiertos_y_todo_resuelto():
    assert concepto.emitir(13, 13, 0, 0)["concepto"] == "viable"
    # un solo punto abierto ya degrada
    assert concepto.emitir(13, 13, 0, 1)["concepto"] == "con_salvedades"
    # un solo habilitante sin medir, también
    assert concepto.emitir(13, 12, 0, 0)["concepto"] == "con_salvedades"


def test_la_escala_tiene_los_cuatro_grados_y_el_orden_de_gravedad():
    assert set(concepto.ESCALA) == {"viable", "con_salvedades", "no_viable",
                                    "sin_concepto"}
    assert concepto.ORDEN_GRAVEDAD[0] == "no_viable"
    assert concepto.ORDEN_GRAVEDAD[-1] == "viable"
    for clave, pres in concepto.ESCALA.items():
        assert pres["etiqueta"].isupper(), clave
        assert pres["definicion"].endswith("."), clave


# ── 3 · El origen del dato que falta ───────────────────────────────────────

def _req(nombre: str, categoria: str = "documental") -> Requisito:
    return Requisito.model_validate(
        {"nombre": nombre, "categoria": categoria, "criticidad": "habilitante",
         "exigido_literal": "x", "fuente_numeral": "1"})


def test_un_concepto_que_el_perfil_si_captura_es_campo_sin_respuesta():
    from src.perfil import PerfilEmpresa
    p = PerfilEmpresa.model_validate({"nombre": "X"})
    assert concepto.origen_dato_faltante(
        _req("RUP vigente y en firme"), p) == "campo_sin_respuesta"


def test_un_concepto_que_el_perfil_no_captura_es_hueco_nuestro():
    from src.perfil import PerfilEmpresa
    p = PerfilEmpresa.model_validate({"nombre": "X"})
    # el formulario no pregunta por la clasificación UNSPSC de los contratos
    assert concepto.origen_dato_faltante(
        _req("Clasificación UNSPSC de contratos"), p) == "no_preguntado"


def test_la_frase_al_cliente_no_menciona_el_formulario():
    """
    El cliente no sabe que existe un formulario y no le importa. Recibe una
    tarea, no una disculpa nuestra.
    """
    frase = concepto.FRASE_CLIENTE.lower()
    for prohibida in ("formulario", "perfil", "pendiente de", "no preguntad",
                      "nuestro", "sistema"):
        assert prohibida not in frase, (
            f"la frase al cliente menciona «{prohibida}»: {concepto.FRASE_CLIENTE}")
    assert "confirmar" in frase


def test_los_origenes_declaran_de_quien_es_el_hueco():
    assert concepto.ORIGENES["no_preguntado"]["dueno"] == "nosotros"
    assert concepto.ORIGENES["le_falta"]["dueno"] == "cliente"
    assert concepto.ORIGENES["le_falta"]["que_es"] == "hallazgo"


def test_el_resumen_dice_explicitamente_que_hoy_no_hay_hallazgos():
    """
    38 de 38 en `no_preguntado` significa que el sistema no puede producir
    todavía NI UN hallazgo documental. El resumen tiene que decirlo, no
    dejarlo en un cero silencioso.
    """
    filas = [{"origen": "no_preguntado"}] * 38
    r = concepto.resumen_origenes(filas)
    assert r["total"] == 38
    assert r["hallazgos"] == 0
    assert r["produce_hallazgos"] is False
    assert r["pendientes_de_captura"] == 38


def test_el_resumen_detecta_el_primer_hallazgo():
    filas = [{"origen": "no_preguntado"}] * 10 + [{"origen": "le_falta"}]
    r = concepto.resumen_origenes(filas)
    assert r["hallazgos"] == 1
    assert r["produce_hallazgos"] is True


def test_como_json_expone_los_umbrales_nulos():
    j = concepto.como_json()
    assert j["umbral_sin_concepto"] is None
    assert j["frase_cliente"] == concepto.FRASE_CLIENTE
    assert len(j["escala"]) == 4
