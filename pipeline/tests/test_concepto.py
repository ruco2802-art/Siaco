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
    # el perfil no tiene ningún campo para la cédula del representante legal
    assert concepto.origen_dato_faltante(
        _req("Fotocopia del documento de identificación del representante legal"),
        p) == "no_preguntado"


def test_el_enrutado_por_objeto_alcanza_un_campo_que_la_categoria_escondia():
    """
    [D30] «RUP vigente y en firme» viene con `categoria='experiencia'`, así que
    el mapa por palabra clave no llegaba a `PerfilJuridico.rup_en_firme`. El
    dato EXISTE: no es un campo que falte, es uno que desperdiciábamos.
    """
    from src.perfil import PerfilEmpresa
    p = PerfilEmpresa.model_validate({"nombre": "X"})
    origen = concepto.origen_dato_faltante(
        _req("RUP vigente y en firme antes del cierre", categoria="experiencia"), p)
    assert origen == "campo_sin_respuesta", (
        "el enrutado por objeto no alcanza el RUP clasificado como experiencia")


def test_el_enrutado_no_usa_el_objeto_que_sale_solo_del_literal():
    """
    [D29] `identificar_objeto()` cae al literal cuando el nombre no basta, y
    ahí acierta por proximidad. Eso vale para AGRUPAR —un grupo mal formado se
    revisa— pero no para un VEREDICTO, que se le presenta al cliente como un
    hecho sobre su empresa.
    """
    from src.catalogo import identificar_objeto, objeto_para_evaluar
    req = _req("Requisitos habilitantes en proponentes plurales por cada integrante",
               categoria="juridico")
    req.exigido_literal = (
        "los requisitos habilitantes serán acreditados por cada uno de los "
        "integrantes de la figura asociativa; índice de endeudamiento y "
        "liquidez se calculan de forma ponderada")
    assert identificar_objeto(req) == "ENDEUDAMIENTO"   # el de agrupar
    assert objeto_para_evaluar(req) is None             # el de evaluar, no


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


def test_el_enrutado_no_aplica_fuera_del_aspecto_que_el_campo_contesta():
    """
    `rup_en_firme` contesta «el RUP está vigente y en firme». NO contesta «el
    RUP acredita la condición de Mipyme», que es otra pregunta sobre el mismo
    documento. Un mapa objeto->campo sin este filtro producía 9 CUMPLE falsos
    de 11 en Paicol — medido antes de recortarlo.
    """
    from src.evaluator import _SIN_MAPA, _valor_por_objeto
    from src.perfil import PerfilEmpresa
    p = PerfilEmpresa.model_validate(
        {"nombre": "X", "juridico": {"rup_en_firme": True}})
    # aspecto `vigencia`: el campo contesta la pregunta
    assert _valor_por_objeto(
        _req("RUP vigente y en firme antes del cierre",
             categoria="experiencia"), p) is True
    # otro aspecto sobre el mismo objeto: la ruta NO se aplica
    assert _valor_por_objeto(
        _req("RUP en firme (acreditación condición Mipyme)",
             categoria="juridico"), p) is _SIN_MAPA


def test_un_numero_sin_umbral_no_puede_salir_como_cumple():
    """
    `bool(1.85)` es True, así que «Índice de liquidez» salía CUMPLE sin haber
    comparado 1,85 contra nada. 11 de los 47 habilitantes en CUMPLE de Paicol
    venían de ahí. El dato de la empresa existe; falta el umbral del pliego,
    que es lectura y por tanto tarea del OPERADOR.
    """
    from src.evaluator import _evaluar_item
    from src.perfil import PerfilEmpresa
    p = PerfilEmpresa.model_validate(
        {"nombre": "X", "financiero": {"indice_liquidez": 1.85}})
    r = _evaluar_item(_req("Índice de liquidez", categoria="financiero"), p)
    assert r["estado"] == "revisar_manual", (
        f"un número sin umbral volvió a salir como {r['estado']}")
    assert r["valor_empresa"] == 1.85
    assert "no dejó un umbral" in r["motivo"]


def test_un_booleano_sin_umbral_si_es_una_respuesta():
    """El perfil afirma que lo tiene o que no: eso se puede sostener."""
    from src.evaluator import _evaluar_item
    from src.perfil import PerfilEmpresa
    si = PerfilEmpresa.model_validate({"nombre": "X", "juridico": {"sin_redam": True}})
    no = PerfilEmpresa.model_validate({"nombre": "X", "juridico": {"sin_redam": False}})
    req = _req("Certificado REDAM", categoria="juridico")
    assert _evaluar_item(req, si)["estado"] == "cumple"
    assert _evaluar_item(req, no)["estado"] == "no_cumple"


# ── 4 · La cuarta categoría: reglas del pliego ─────────────────────────────

def test_una_regla_del_pliego_no_es_hueco_de_nadie():
    """
    «Subsanabilidad de experiencia insuficiente» no es un dato de la empresa ni
    un campo que falte: es una regla del procedimiento. Hoy contaminaba las dos
    listas — pedía confirmación al cliente y contaba como limitación nuestra.
    """
    from src.perfil import PerfilEmpresa
    p = PerfilEmpresa.model_validate({"nombre": "X"})
    assert concepto.origen_dato_faltante(
        _req("Subsanabilidad de experiencia insuficiente",
             categoria="experiencia"), p) == "no_se_responde_con_un_campo"
    assert concepto.ORIGENES["no_se_responde_con_un_campo"]["dueno"] == "nadie"


def test_unspsc_no_es_una_regla_aunque_lo_parezca():
    """
    En la primera lectura lo clasificamos como regla. No lo es:
    `PerfilExperiencia.codigos_unspsc` existe y «los contratos deben estar
    clasificados en alguno de estos códigos» se responde comparando conjuntos.
    Le falta el criterio de comparación, que es [D27], no esta categoría.
    """
    assert "UNSPSC" not in concepto.OBJETOS_REGLA


def test_el_resumen_cuenta_las_reglas_aparte():
    filas = ([{"origen": "no_preguntado"}] * 30
             + [{"origen": "no_se_responde_con_un_campo"}] * 5)
    r = concepto.resumen_origenes(filas)
    assert r["reglas"] == 5
    assert r["pendientes_de_captura"] == 30


# ── 5 · Por qué falló una verificación ─────────────────────────────────────

def test_una_cita_con_simbolo_transformado_no_es_un_error_de_extraccion():
    """
    El «≥» del pliego llega como «>=» al extraerse, así que la comparación
    literal falla aunque la cita sea exactamente la del pliego. Decirle al
    cliente «cita no verificada» ahí es jerga que asusta sin informar.
    """
    from src.verifier import causa_no_verificada
    assert causa_no_verificada(
        "Capital de trabajo ≥ 450.000.000") == "simbolo_transformado"
    assert causa_no_verificada("A − B ∗ C") == "simbolo_transformado"


def test_una_cita_sin_simbolos_que_no_verifica_si_hay_que_revisarla():
    from src.verifier import causa_no_verificada
    assert causa_no_verificada(
        "Los contratos aportados deben estar clasificados") == "texto_ausente"
