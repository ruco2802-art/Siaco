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
    # [D27] El perfil tiene el certificado de existencia, pero los dos pliegos
    # preguntan por la DURACIÓN de la sociedad, que ningún campo contesta.
    assert concepto.origen_dato_faltante(
        _req("Duración de la persona jurídica no inferior al plazo del contrato",
             categoria="juridico"), p) == "no_preguntado"


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
    # aspecto `vigencia`: el campo contesta la pregunta. Devuelve el Documento
    # entero, no el booleano, porque la fecha decide la vigencia [D27].
    doc = _valor_por_objeto(
        _req("RUP vigente y en firme antes del cierre", categoria="experiencia"), p)
    assert doc is not _SIN_MAPA and doc.tiene is True
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


# ── 6 · [D27] Documentos: el paso 3 de la cadena ───────────────────────────

def _perfil_doc(**docs):
    from src.perfil import PerfilEmpresa
    return PerfilEmpresa.model_validate({"nombre": "X", "documentos": docs})


def _req_doc(nombre="RUP vigente y en firme antes del cierre",
             categoria="experiencia", **extra):
    return Requisito.model_validate(
        {"nombre": nombre, "categoria": categoria, "criticidad": "habilitante",
         "exigido_literal": "x", "fuente_numeral": "1", **extra})


def test_el_sistema_ya_puede_producir_un_hallazgo_documental():
    """
    EL PUNTO DE [D27]. Antes de esto, `tiene=False` no existía como respuesta
    posible: los 34 documentales de Paicol eran «no sabemos». Un cliente que
    dice que NO tiene el RUP tiene que producir NO CUMPLE, que es el paso 3 de
    la cadena y el valor del servicio.
    """
    from src.evaluator import _evaluar_item
    r = _evaluar_item(_req_doc(), _perfil_doc(rup={"tiene": False}))
    assert r["estado"] == "no_cumple"
    assert "no cuenta con este documento" in r["motivo"]


def test_no_haber_preguntado_sigue_siendo_distinto_de_no_tenerlo():
    from src.evaluator import _evaluar_item
    r = _evaluar_item(_req_doc(), _perfil_doc())
    assert r["estado"] == "dato_faltante"


def test_tenerlo_basta_cuando_el_pliego_no_exige_vigencia():
    from src.evaluator import _evaluar_item
    r = _evaluar_item(_req_doc(), _perfil_doc(rup={"tiene": True}))
    assert r["estado"] == "cumple"


def test_tenerlo_sin_fecha_no_es_cumplir_si_el_pliego_exige_vigencia():
    """
    [I10] Con `tiene=True` y sin fecha, dar por vigente el documento sería
    presumir un dato que nadie dio. Falta la fecha, y eso se dice.
    """
    from src.evaluator import _evaluar_item
    req = _req_doc("RUP en firme con vigencia máxima 30 días",
                   valor_umbral=30, operador="<=", unidad="dias")
    r = _evaluar_item(req, _perfil_doc(rup={"tiene": True}))
    assert r["estado"] == "dato_faltante"
    assert "fecha de expedición" in r["documento_requerido"]


def test_lo_tiene_pero_vencido_se_distingue_de_lo_tiene_vigente():
    from datetime import date

    from src.evaluator import _evaluar_item
    req = _req_doc("RUP en firme con vigencia máxima 30 días",
                   valor_umbral=30, operador="<=", unidad="dias")
    hoy = date(2026, 9, 28)

    vigente = _evaluar_item(
        req, _perfil_doc(rup={"tiene": True, "fecha_expedicion": "2026-09-10"}),
        fecha_referencia=hoy)
    assert vigente["estado"] == "cumple"
    assert vigente["valor_empresa"] == 18

    vencido = _evaluar_item(
        req, _perfil_doc(rup={"tiene": True, "fecha_expedicion": "2026-06-01"}),
        fecha_referencia=hoy)
    assert vencido["estado"] == "no_cumple"
    assert "expedido hace 119 días" in vencido["motivo"]
    assert "admite hasta 30" in vencido["motivo"]


def test_sin_vigencia_exigida_no_se_inventa_un_plazo_de_30_dias():
    """
    [I10] Un pliego que no fija vigencia no la exige. Suponer 30 días
    inventaría un incumplimiento sobre un documento que está bien.
    """
    from datetime import date

    from src.evaluator import _evaluar_item
    r = _evaluar_item(
        _req_doc(),  # sin valor_umbral
        _perfil_doc(rup={"tiene": True, "fecha_expedicion": "2019-01-01"}),
        fecha_referencia=date(2026, 9, 28))
    assert r["estado"] == "cumple"


def test_una_fecha_mal_escrita_no_tumba_la_evaluacion():
    from src.evaluator import _evaluar_item
    req = _req_doc("RUP con vigencia 30 días", valor_umbral=30,
                   operador="<=", unidad="dias")
    r = _evaluar_item(
        req, _perfil_doc(rup={"tiene": True, "fecha_expedicion": "ayer"}))
    assert r["estado"] == "dato_faltante"


def test_la_migracion_funciona_por_cualquier_camino_de_construccion():
    """
    La migración vivía en `cargar_perfil()` y cualquier otro camino la perdía:
    el mismo perfil daba veredictos distintos según cómo se hubiera cargado.
    Ahora es un validador del modelo.
    """
    from src.perfil import PerfilEmpresa, cargar_perfil
    data = {"nombre": "X", "juridico": {"rup_en_firme": True,
                                        "rup_fecha_expedicion": "2026-09-10"}}
    for construir in (PerfilEmpresa.model_validate, cargar_perfil,
                      lambda d: PerfilEmpresa(**d)):
        p = construir(data)
        assert p.documentos.rup.tiene is True, construir
        assert p.documentos.rup.fecha_expedicion == "2026-09-10"


def test_lo_que_el_cliente_responde_manda_sobre_el_campo_antiguo():
    from src.perfil import PerfilEmpresa
    p = PerfilEmpresa.model_validate({
        "nombre": "X",
        "juridico": {"rup_en_firme": False},
        "documentos": {"rup": {"tiene": True}},
    })
    assert p.documentos.rup.tiene is True


def test_seguridad_social_no_contesta_lo_que_paicol_pregunta():
    """
    [D32] Los tres requisitos de seguridad social de Paicol son de persona
    natural —pensión de vejez, exención de cotización, no obligación de
    aportes— y «está al día en seguridad social» no contesta ninguno. Tienen
    que quedarse en `no_preguntado`, no producir un CUMPLE falso.
    """
    from src.evaluator import CAMPO_POR_OBJETO
    for objeto in ("SEGURIDAD_SOCIAL", "EXISTENCIA_REPRESENTACION",
                   "SUBCONTRATACION"):
        assert objeto not in CAMPO_POR_OBJETO, (
            f"{objeto} entró al mapa: comprueba que el campo contesta la "
            "pregunta del pliego con CUALQUIER aspecto, no que suene parecido")


def test_un_criterio_de_puntaje_clasificado_como_habilitante_no_se_evalua():
    """
    [D20] «Mayor puntaje CF por pasivo corriente igual a cero» está en el
    capítulo de habilitantes, pero su literal dice «la Entidad debe otorgar el
    mayor puntaje». Evaluarlo daba un CUMPLE falso sobre algo que el informe
    presenta como habilitante. No se excluye en silencio: va a revisión manual,
    que es tarea del operador y sale en el informe.
    """
    from src.evaluator import _evaluar_item
    r = _evaluar_item(
        _req_doc("Mayor puntaje CF por pasivo corriente igual a cero",
                 categoria="financiero"),
        _perfil_doc(estados_financieros={"tiene": True}))
    assert r["estado"] == "revisar_manual"
    assert "reparte puntaje" in r["motivo"]


def test_los_pliegos_dicen_dias_calendario_no_dias():
    """
    Paicol y Ternera escriben «días calendario» en los cinco requisitos de
    vigencia que tienen. Comparar contra {"dias"} dejaba la vigencia muerta.
    """
    from src.evaluator import _dias_de_vigencia_exigidos
    r = _req_doc(valor_umbral=30, operador="<=", unidad="días calendario")
    assert _dias_de_vigencia_exigidos(r) == 30


def test_los_dias_habiles_no_se_convierten_a_calendario():
    """
    [I10] Convertirlos exige saber los festivos del periodo. Estimarlos
    produciría un vencimiento inventado; sin calendario, no se evalúa.
    """
    from src.evaluator import _dias_de_vigencia_exigidos
    assert _dias_de_vigencia_exigidos(
        _req_doc(valor_umbral=5, operador="<=", unidad="días hábiles")) is None


def test_un_plazo_en_anos_no_es_antiguedad_de_documento():
    """«Vigencia amparo estabilidad de obra: 5 años» es cobertura de garantía."""
    from src.evaluator import _dias_de_vigencia_exigidos
    assert _dias_de_vigencia_exigidos(
        _req_doc(valor_umbral=5, operador=">=", unidad="años")) is None


def test_el_formulario_conserva_el_tri_estado_hasta_el_perfil():
    """
    El viaje completo: formulario -> PerfilBody -> PerfilEmpresa. Si alguna
    capa aplasta `None` a `False`, cada casilla sin marcar se convierte en un
    hallazgo falso contra la empresa. El puente de la API es donde más fácil
    se pierde, porque ahí los campos vacíos ya se normalizan a None.
    """
    js = (Path(__file__).resolve().parents[2] / "static" / "app.js").read_text("utf-8")
    assert "buildDocumentosBody" in js, "el formulario no envía el bloque documental"
    assert "v === 'true' ? true : v === 'false' ? false : null" in js, (
        "app.js dejó de distinguir «sin responder» de «no lo tiene»")

    html = (Path(__file__).resolve().parents[2] / "static" / "index.html").read_text("utf-8")
    assert '<option value="">Sin responder</option>' in html, (
        "la opción vacía tiene que ser la PRIMERA de cada select: un formulario "
        "cuyo valor por defecto sea «No» inventa incumplimientos")
    for clave in ("d-rup-tiene", "d-rup-fecha", "d-capacidad-juridica",
                  "d-documento-identidad-tiene"):
        assert f'id="{clave}"' in html, f"falta el campo {clave} en el formulario"
