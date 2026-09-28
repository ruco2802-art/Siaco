# -*- coding: utf-8 -*-
"""
src/evaluator.py — contraste perfil ↔ requisitos, Python puro.

[I6] Todas las comparaciones numéricas y el score se calculan aquí,
     nunca en el LLM ni en ningún otro módulo.
[I4] veredicto se deriva de score_global + flags; nunca se asigna a mano.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any, Callable

from pydantic import BaseModel

from .estados import motivo_unidad_discordante, unidad_discordante
from .extractor import Requisito
from .perfil import (  # esquema canónico — única fuente de verdad
    Documento,
    PerfilEmpresa,
    PerfilFinanciero,
    PerfilExperiencia,
    PerfilJuridico,
    PerfilTecnico,
    PerfilSocial,
    cargar_perfil,
)

# Re-exportar para que los imports existentes de evaluator sigan funcionando
__all__ = [
    "PerfilEmpresa", "PerfilFinanciero", "PerfilExperiencia",
    "PerfilJuridico", "PerfilTecnico", "PerfilSocial",
    "cargar_perfil", "cargar_perfil_por_cid", "evaluar_empresa", "seleccionar_rango_umbrales",
]


def _strip_accents(s: str) -> str:
    """Elimina diacríticos: 'representación' → 'representacion'."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


# ─── Selección de rango × variante (estructura_normativa.json) ─────────────

def seleccionar_rango_umbrales(
    presupuesto_cop: float | None,
    smmlv_anio: float | None,
    es_mipyme: bool,
) -> str | None:
    """
    Determina el juego de umbrales aplicable según presupuesto y tipo de
    proponente.

    La estructura normativa CCE (estructura_normativa.json) define:
      - Rango 1: >0 hasta <4.000 SMMLV
      - Rango 2: >=4.000 SMMLV
    combinado con variante mipyme / no_mipyme.

    Retorna: "rango_1_mipyme" | "rango_1_no_mipyme" |
             "rango_2_mipyme" | "rango_2_no_mipyme"
    Retorna None si faltan datos para determinarlo.

    Nunca aplica un default: usar umbrales de no-MIPYME a una MIPYME produce
    resultados falsos.
    """
    if presupuesto_cop is None or smmlv_anio is None or smmlv_anio <= 0:
        return None
    presupuesto_smmlv = presupuesto_cop / smmlv_anio
    rango = "rango_1" if presupuesto_smmlv < 4_000 else "rango_2"
    variante = "mipyme" if es_mipyme else "no_mipyme"
    return f"{rango}_{variante}"


# ─── Score y pesos ─────────────────────────────────────────────────────────

_PESOS: dict[str, float] = {
    "juridico":    0.30,
    "financiero":  0.35,
    "tecnico":     0.15,
    "experiencia": 0.15,
    "documental":  0.05,
}

# [I6] verificado en código: los pesos son la fórmula, no una caja negra
_suma_pesos = sum(_PESOS.values())
assert abs(_suma_pesos - 1.0) < 1e-9, (
    f"Los pesos del evaluador no suman 1.0 ({_suma_pesos}). "
    "Corrige _PESOS antes de continuar."
)


# ─── Comparador numérico ───────────────────────────────────────────────────

def _comparar(valor: float, umbral: float, operador: str) -> bool:
    """[I6] Comparación en Python puro. El LLM nunca hace este cálculo."""
    if operador == ">=":
        return valor >= umbral
    if operador == "<=":
        return valor <= umbral
    if operador == "==":
        return valor == umbral
    if operador == "!=":
        return valor != umbral
    raise ValueError(f"Operador no reconocido: {operador!r}")


# ─── Mapeo nombre del requisito → campo del perfil ─────────────────────────
# Cada entrada: (keyword_en_nombre_lower, extractor_lambda)
# Se usa la PRIMERA coincidencia.

def _ingresos_recientes(p: PerfilFinanciero) -> float | None:
    """Último año de ingresos operacionales, o None si la lista está vacía."""
    return p.ingresos_operacionales_ultimos_5_anos[-1] if p.ingresos_operacionales_ultimos_5_anos else None


_MAP_FIN: list[tuple[str, Callable[[PerfilFinanciero], Any]]] = [
    ("liquidez",                     lambda p: p.indice_liquidez),
    ("endeudamiento",                lambda p: p.indice_endeudamiento),
    ("capital de trabajo",           lambda p: p.capital_trabajo),
    ("patrimonio",                   lambda p: p.patrimonio_neto),
    ("renta",                        lambda p: p.renta_operacional),
    ("ebitda",                       lambda p: p.ebitda),
    ("rentabilidad del patrimonio",  lambda p: p.rentabilidad_patrimonio or p.roe),
    ("rentabilidad del activo",      lambda p: p.rentabilidad_activo or p.roa),
    ("roe",                          lambda p: p.roe or p.rentabilidad_patrimonio),
    ("roa",                          lambda p: p.roa or p.rentabilidad_activo),
    ("cobertura",                    lambda p: p.cobertura_intereses),
    ("ingresos operacionales",       _ingresos_recientes),
    ("capacidad de organizaci",      _ingresos_recientes),  # "CO" en pliegos
    ("saldo",                        lambda p: p.saldos_contratos_en_ejecucion),
    ("profesional",                  lambda p: float(p.numero_profesionales_vinculados)
                                              if p.numero_profesionales_vinculados is not None else None),
]

_MAP_EXP: list[tuple[str, Callable[[PerfilExperiencia], Any]]] = [
    ("acumulado",                   lambda p: p.valor_acumulado),
    ("individual",                  lambda p: p.valor_individual_max),
    ("contratos acreditables",      lambda p: p.contratos_acreditados),
    ("contratos acreditados",       lambda p: p.contratos_acreditados),
    ("numero maximo",               lambda p: p.contratos_acreditados),
    ("antigüedad",                  lambda p: p.antiguedad_meses),
    ("antiguedad",                  lambda p: p.antiguedad_meses),
    ("plazo",                       lambda p: p.antiguedad_meses),
]

_MAP_JUR: list[tuple[str, Callable[[PerfilJuridico], Any]]] = [
    ("rup",                         lambda p: p.rup_en_firme),
    ("camara",                      lambda p: p.camara_comercio),
    ("cámara",                      lambda p: p.camara_comercio),
    ("parafiscal",                  lambda p: p.paz_y_salvo_parafiscales),
    ("seguridad social",            lambda p: p.paz_y_salvo_seguridad_social),
    ("impuesto",                    lambda p: p.paz_y_salvo_impuestos),
    ("paz y salvo municipal",       lambda p: p.paz_salvo_municipal),
    ("paz y salvo",                 lambda p: p.paz_y_salvo_parafiscales),
    ("municipal",                   lambda p: p.paz_salvo_municipal),
    ("inhabilidad",                 lambda p: p.sin_inhabilidades),
    ("incompatibilidad",            lambda p: p.sin_inhabilidades),
    ("disciplinario",               lambda p: p.sin_antecedentes_disciplinarios),
    ("judicial",                    lambda p: p.sin_antecedentes_penales),
    ("penal",                       lambda p: p.sin_antecedentes_penales),
    ("fiscal",                      lambda p: p.sin_antecedentes_fiscales),
    ("redam",                       lambda p: p.sin_redam),
    ("medidas correctivas",         lambda p: p.sin_medidas_correctivas),
    ("garantia",                    lambda p: p.garantia_seriedad),
    ("garantía",                    lambda p: p.garantia_seriedad),
    ("rut",                         lambda p: p.rut_vigente),
    # Declaraciones habilitantes
    ("insolvencia",                 lambda p: p.sin_insolvencia),
    ("conflicto de",                lambda p: p.sin_conflicto_interes),
    ("objeto social",               lambda p: p.objeto_social_compatible),
    ("estudios y dise",             lambda p: p.sin_estudios_diseno_previos),
    ("existencia",                  lambda p: p.camara_comercio),
    ("representacion",              lambda p: p.camara_comercio),
    ("boletin",                     lambda p: p.sin_antecedentes_fiscales),
    ("boletín",                     lambda p: p.sin_antecedentes_fiscales),
    ("antecedente",                 lambda p: p.sin_antecedentes_disciplinarios),
]


_MAP_TEC: list[tuple[str, Callable[[Any], Any]]] = [
    ("titulo",                      lambda p: None if p.titulo_profesional is None
                                              else (p.titulo_profesional != "ninguno")),
    ("colombianos",                 lambda p: p.porcentaje_empleados_colombianos),
    ("personal",                    lambda p: p.personal_disponible),
    ("equipo",                      lambda p: bool(p.equipos)),
    ("certificacion",               lambda p: bool(p.certificaciones)),
]


# ── [D30] Enrutado por OBJETO del catálogo ─────────────────────────────────
#
# El lookup por palabra clave elige el mapa según `req.categoria`, así que un
# requisito de RUP que el extractor clasificó como `experiencia` no alcanzaba
# `PerfilJuridico.rup_en_firme`, **que existe**. No es un campo que falte: es
# un dato que ya tenemos y desperdiciábamos.
#
# La solución NO es añadir palabras clave. Se midió: buscando los 38 sin dato
# de Paicol contra los cuatro mapas ignorando la categoría, 10 daban
# coincidencia y 8 eran espurias (`plazo`→`antiguedad_meses`,
# `certificacion`→`certificaciones`). Habría producido datos inventados con
# apariencia de medidos.
#
# El objeto del catálogo identifica el concepto con independencia de la
# categoría que le puso el extractor y de cómo lo redacte el pliego. Se usa
# `objeto_para_evaluar()`, que sólo acepta la coincidencia por NOMBRE: ver
# allí por qué el respaldo por literal no puede decidir un veredicto [D29].
#
# El mapa cubre SÓLO los objetos que corresponden a UN campo sin ambigüedad.
# `EXPERIENCIA_CONTRATOS` cubre valor acumulado, individual y número de
# contratos a la vez, así que no entra y lo sigue resolviendo el mapa por
# palabra clave, que sí los distingue. Lo que no está aquí no se adivina.
_SIN_MAPA = object()


def _fin(nombre: str):
    return lambda p: getattr(p.financiero, nombre) if p.financiero else None


def _jur(nombre: str):
    return lambda p: getattr(p.juridico, nombre) if p.juridico else None


def _doc(nombre: str):
    """Devuelve el `Documento` entero, no su booleano: la fecha decide vigencia."""
    return lambda p: getattr(p.documentos, nombre) if p.documentos else None


# MEDIDO antes de fijar este mapa. Una primera versión cubría 30 objetos y
# resolvía 11 de los 38 sin dato de Paicol — pero **9 de esos 11 eran falsos**:
#
#   EXISTENCIA_REPRESENTACION -> camara_comercio
#       «Duración de la persona jurídica no inferior al plazo del contrato más
#        un año». Tener el certificado NO dice cuánto dura la sociedad.
#   SEGURIDAD_SOCIAL -> paz_y_salvo_seguridad_social
#       «Declaración juramentada de no obligación de aportes». Estar al día NO
#        es lo mismo que no tener obligación.
#   UNSPSC -> bool(codigos_unspsc)
#       «los contratos deben estar clasificados en ALGUNO DE ESTOS códigos».
#        Tener códigos no dice que sean ésos.
#
# Se probó filtrar por el `aspecto` del catálogo y NO separa: bajo
# `acreditacion` conviven «Certificación de pagos de seguridad social» —que el
# campo sí contesta— y la declaración juramentada —que no—. Los dos ejes del
# catálogo sirven para AGRUPAR, donde una bolsa mal formada se revisa; no para
# decidir un veredicto que se le presenta al cliente como un hecho.
#
# Así que el mapa queda en lo que se puede defender uno por uno:
#
#   - los INDICADORES NUMÉRICOS, donde el campo es literalmente la magnitud
#     que el pliego compara, y donde un emparejamiento equivocado sale como
#     número disparatado y no como un CUMPLE silencioso;
#   - el RUP **sólo en el aspecto `vigencia`**, que es el caso que [D30]
#     demuestra: «RUP vigente y en firme» clasificado como `experiencia` o
#     `financiero` no alcanzaba `rup_en_firme`, que existe.
#
# Lo que no está aquí sigue en `dato_faltante`, que pide confirmación y no
# afirma nada. Añadir un objeto exige comprobar que el campo contesta la
# pregunta con cualquier aspecto, no que suene parecido.
CAMPO_POR_OBJETO: dict[str, Callable[[PerfilEmpresa], Any]] = {
    "LIQUIDEZ": _fin("indice_liquidez"),
    "ENDEUDAMIENTO": _fin("indice_endeudamiento"),
    "COBERTURA_INTERESES": _fin("cobertura_intereses"),
    "CAPITAL_TRABAJO": _fin("capital_trabajo"),
    "PATRIMONIO": _fin("patrimonio_neto"),
    "RENTABILIDAD_ACTIVO": lambda p: (p.financiero.rentabilidad_activo
                                      or p.financiero.roa) if p.financiero else None,
    "RENTABILIDAD_PATRIMONIO": lambda p: (p.financiero.rentabilidad_patrimonio
                                          or p.financiero.roe) if p.financiero else None,
    "INGRESOS_OPERACIONALES": lambda p: (_ingresos_recientes(p.financiero)
                                         if p.financiero else None),
    "CAPACIDAD_ORGANIZACIONAL": lambda p: (_ingresos_recientes(p.financiero)
                                           if p.financiero else None),
    "RUP": _doc("rup"),
    # [D27] Los documentos. Cada uno responde SOLO lo suyo — ver el aspecto
    # exigido abajo, que es lo que impide que «tiene el certificado» conteste
    # «la sociedad dura lo suficiente» [D32].
    "ESTADOS_FINANCIEROS": _doc("estados_financieros"),
    "DOCUMENTO_IDENTIDAD": _doc("documento_identidad"),
    "CAPACIDAD_JURIDICA": lambda p: (p.documentos.capacidad_juridica
                                     if p.documentos else None),
}

# [D34] `EXISTENCIA_REPRESENTACION` se evalúa aparte, no por este mapa: lo
# que los pliegos preguntan es la DURACIÓN de la sociedad contra el plazo
# del contrato, y eso necesita un dato del PLIEGO además del perfil.
OBJETO_DURACION_SOCIEDAD = "EXISTENCIA_REPRESENTACION"

# Objetos cuyo campo sólo contesta UN aspecto concreto. Fuera de él, el mapa no
# se aplica: «RUP en firme (acreditación condición Mipyme)» pregunta por la
# inscripción como Mipyme, no por que el RUP esté en firme.
#
# [D27] `EXISTENCIA_REPRESENTACION`, `SEGURIDAD_SOCIAL` y `SUBCONTRATACION`
# **no están** en el mapa aunque el perfil ya tenga su campo, y no es un olvido:
# en los dos pliegos medidos, lo que se pregunta sobre ellos NO es lo que el
# campo contesta.
#
#   EXISTENCIA_REPRESENTACION  «duración de la persona jurídica no inferior al
#                              plazo del contrato más un año» — tener el
#                              certificado no dice cuánto dura la sociedad.
#                              Haría falta un campo `duracion_sociedad_hasta`.
#   SEGURIDAD_SOCIAL           «pensión de vejez o indemnización sustitutiva»,
#                              «exención de cotización», «declaración de no
#                              obligación de aportes por no tener personal» —
#                              estar al día no contesta ninguna de las tres.
#   SUBCONTRATACION            «obligación de informar subcontratos a la
#                              Entidad» — es una regla del contrato durante la
#                              ejecución, no un documento que se aporte.
#
# Se quedan en `no_preguntado`, que pide confirmar y no afirma nada. Añadirlas
# daría un CUMPLE falso sobre un requisito habilitante [D32].
ASPECTO_REQUERIDO: dict[str, frozenset[str]] = {
    "RUP": frozenset({"vigencia"}),
}


def _valor_por_objeto(req: Requisito, perfil: PerfilEmpresa) -> Any:
    """
    Valor del perfil por el objeto del catálogo, o `_SIN_MAPA` si no hay ruta.

    `_SIN_MAPA` y `None` NO son lo mismo: sin ruta se prueba el mapa por
    palabra clave; con ruta y valor `None` el campo existe y está vacío, y
    caer al mapa reintroduciría la ambigüedad que este enrutado elimina.
    """
    try:
        from .catalogo import identificar_aspecto, objeto_para_evaluar
        objeto = objeto_para_evaluar(req)
        fn = CAMPO_POR_OBJETO.get(objeto or "")
        if fn is None:
            return _SIN_MAPA
        permitidos = ASPECTO_REQUERIDO.get(objeto or "")
        if permitidos is not None and identificar_aspecto(req) not in permitidos:
            return _SIN_MAPA
    except Exception:
        return _SIN_MAPA   # sin catálogo utilizable, el camino de antes
    return fn(perfil)


def _valor_perfil(req: Requisito, perfil: PerfilEmpresa) -> Any:
    """
    Busca el valor del perfil correspondiente al requisito.
    Retorna None cuando el dato falta — NUNCA retorna 0 como sustituto.
    (Bug real: perfiles sin bloque financiero producían "NO VIABLE — datos en cero".)
    """
    # [D30] El objeto del catálogo primero: no depende de `categoria`.
    por_objeto = _valor_por_objeto(req, perfil)
    if por_objeto is not _SIN_MAPA:
        return por_objeto

    nombre_l = req.nombre.lower()
    # sin tildes — permite que keywords sin acento capturen nombres con acento y viceversa
    nombre_n = _strip_accents(nombre_l)

    if req.categoria == "financiero":
        if perfil.financiero is None:
            return None
        for kw, fn in _MAP_FIN:
            if _strip_accents(kw) in nombre_n:
                return fn(perfil.financiero)
        return None

    if req.categoria == "experiencia":
        if perfil.experiencia is None:
            return None
        for kw, fn in _MAP_EXP:
            if _strip_accents(kw) in nombre_n:
                return fn(perfil.experiencia)
        return None

    if req.categoria in ("juridico", "documental"):
        if perfil.juridico is None:
            return None
        for kw, fn in _MAP_JUR:
            if _strip_accents(kw) in nombre_n:
                return fn(perfil.juridico)
        return None

    if req.categoria == "tecnico":
        if perfil.tecnico is None:
            return None
        for kw, fn in _MAP_TEC:
            if _strip_accents(kw) in nombre_n:
                return fn(perfil.tecnico)
        return None

    return None


# Qué mapa gobierna cada categoría. Lo consume `concepto.py` para distinguir
# «el perfil tiene el campo y está vacío» de «el formulario no lo pregunta»:
# sin esta tabla habría que duplicar las palabras clave y se desincronizarían.
MAPAS_POR_CATEGORIA: dict[str, list] = {
    "financiero": _MAP_FIN,
    "experiencia": _MAP_EXP,
    "juridico": _MAP_JUR,
    "documental": _MAP_JUR,
    "tecnico": _MAP_TEC,
}


def campo_del_perfil(req: Requisito) -> str | None:
    """
    Devuelve la palabra clave del mapa que captura este requisito, o None si
    ninguna lo captura.

    None significa **que el perfil no tiene ningún campo para este concepto**:
    no es que la empresa no haya respondido, es que no se le preguntó. Los dos
    casos llegan al evaluador como `valor is None` y producen el mismo
    `dato_faltante`; esta función es la que los separa.
    """
    # El MISMO filtro que usa el enrutado, o el origen se reportaría mal: un
    # requisito que la ruta no aplica no es «campo sin responder».
    if _valor_por_objeto(req, PerfilEmpresa(nombre="")) is not _SIN_MAPA:
        from .catalogo import objeto_para_evaluar
        return f"objeto:{objeto_para_evaluar(req)}"
    nombre_n = _strip_accents(req.nombre.lower())
    for kw, _fn in MAPAS_POR_CATEGORIA.get(req.categoria or "", []):
        if _strip_accents(kw) in nombre_n:
            return kw
    return None


# Unidades en las que un pliego expresa la vigencia de un documento.
#
# Los pliegos NO escriben «días» a secas: Paicol y Ternera dicen «días
# calendario» en los cinco requisitos de vigencia que tienen. Una comparación
# exacta contra {"dias"} no disparaba nunca y la vigencia quedaba muerta.
#
# «días hábiles» queda FUERA a propósito [I10]: convertirlos a calendario
# exige saber los festivos del periodo, y estimarlos produciría un vencimiento
# inventado. Sin calendario laboral, el requisito se queda sin evaluar, que es
# lo correcto.
_UNIDADES_DIAS = {"dia", "dias", "dia calendario", "dias calendario",
                  "dia(s) calendario", "dias calendarios"}
_UNIDADES_MESES = {"mes", "meses", "mes calendario", "meses calendario"}


def _dias_de_vigencia_exigidos(req: Requisito) -> int | None:
    """
    Días máximos de antigüedad que el pliego admite para el documento, o None
    si no lo dice. **Sin valor por defecto** [I10]: un pliego que no fija
    vigencia no la exige, y suponer 30 días inventaría un incumplimiento.

    Devuelve None también cuando la unidad es en días HÁBILES o en años: los
    hábiles necesitan calendario de festivos, y un plazo en años casi siempre
    es la cobertura de una garantía, no la antigüedad de un documento.
    """
    if req.valor_umbral is None:
        return None
    unidad = _strip_accents(str(req.unidad or "").strip().lower())
    if "habil" in unidad:
        return None
    if unidad in _UNIDADES_DIAS:
        return int(req.valor_umbral)
    if unidad in _UNIDADES_MESES:
        return int(req.valor_umbral * 30)
    return None


def _evaluar_documento(
    req: Requisito,
    doc: "Documento",
    fecha_referencia: date | None = None,
) -> dict:
    """
    Veredicto de un documento. Las cuatro salidas y por qué cada una:

        tiene is None   -> `dato_faltante`   no se le preguntó o no respondió
        tiene is False  -> `no_cumple`       **HALLAZGO**: el análisis confirma
                                             que le falta. Es el paso 3 de la
                                             cadena y el valor del servicio.
        tiene, sin vigencia exigida -> `cumple`
        tiene, con vigencia exigida -> depende de la fecha:
            sin fecha   -> `dato_faltante`   lo tiene, pero no se sabe si
                                             sigue vigente. Decir `cumple` aquí
                                             sería presumir vigencia [I10]
            vencido     -> `no_cumple`       con los días de exceso
            vigente     -> `cumple`
    """
    base = {
        "requisito": req.nombre,
        "categoria": req.categoria,
        "fuente_numeral": req.fuente_numeral,
    }
    if doc.tiene is None:
        return {**base, "estado": "dato_faltante",
                "documento_requerido": req.nombre}
    if doc.tiene is False:
        return {**base, "estado": "no_cumple",
                "valor_empresa": False,
                "motivo": "la empresa indica que no cuenta con este documento"}

    dias_max = _dias_de_vigencia_exigidos(req)
    if dias_max is None:
        return {**base, "estado": "cumple", "valor_empresa": True}

    dias = doc.dias_desde_expedicion(fecha_referencia)
    if dias is None:
        return {
            **base, "estado": "dato_faltante", "valor_empresa": True,
            "documento_requerido": (
                f"fecha de expedición de «{req.nombre}» — el pliego lo exige "
                f"con menos de {dias_max} días"),
        }
    if dias > dias_max:
        return {
            **base, "estado": "no_cumple", "valor_empresa": dias,
            "umbral": dias_max, "operador": "<=", "unidad": "dias",
            "diferencia": dias_max - dias,
            "motivo": (f"expedido hace {dias} días; el pliego admite hasta "
                       f"{dias_max}"),
        }
    return {**base, "estado": "cumple", "valor_empresa": dias,
            "umbral": dias_max, "operador": "<=", "unidad": "dias"}


# ─── Criterios que no necesitan campos nuevos ─────────────────────────────
#
# Los dos usan datos que el perfil YA tiene. Los dos son **asimétricos**, y en
# direcciones opuestas: cada uno sólo puede afirmar uno de los dos veredictos,
# porque del otro lado el perfil no alcanza. Un criterio simétrico forzado aquí
# produciría un CUMPLE que nadie comprobó [D32].

_RX_UNSPSC = re.compile(r"\b\d{8}\b")


def _codigos_unspsc_del_pliego(req: Requisito) -> list[str]:
    """Códigos de 8 dígitos que el literal del requisito conserva."""
    return _RX_UNSPSC.findall(req.exigido_literal or "")


def _evaluar_unspsc(req: Requisito, perfil: PerfilEmpresa) -> dict:
    """
    «Los Contratos aportados deben estar clasificados en alguno de los
    siguientes códigos».

    **No se construye el criterio de comparación**, y la razón no es el
    criterio sino el dato: la lista de códigos del pliego **no sobrevive a la
    extracción**. Medido sobre los dos pliegos: de 6 requisitos de UNSPSC,
    **sólo 1 conserva códigos** (Paicol, 72151300 y 72151900) y ese mismo está
    truncado —el literal acaba en «:» o a media lista—. Los otros 5 traen cero.

    Con la lista incompleta, «los códigos de la empresa no están entre los del
    pliego» no es un hallazgo: es «no están entre los que logramos leer». El
    perfil de prueba lo ilustra: tiene 72151501/72151502/72151601 y no solapa
    con los dos códigos extraídos, pero basta que la lista real incluyera
    721515 para que sí solape.

    Va a `revisar_manual` nombrando el dato que falta, que es del PLIEGO y por
    tanto tarea del OPERADOR, no del cliente.
    """
    codigos_pliego = _codigos_unspsc_del_pliego(req)
    de_la_empresa = ((perfil.experiencia.codigos_unspsc or [])
                     if perfil.experiencia else [])
    base = {"requisito": req.nombre, "categoria": req.categoria,
            "fuente_numeral": req.fuente_numeral, "estado": "revisar_manual"}
    if not codigos_pliego:
        return {**base, "motivo": (
            "la lista de códigos UNSPSC del pliego no sobrevivió a la "
            "extracción: léela en el numeral y compárala contra los "
            f"{len(de_la_empresa)} códigos de la empresa")}
    return {**base, "motivo": (
        f"del pliego se extrajeron {len(codigos_pliego)} códigos "
        f"({', '.join(codigos_pliego[:4])}) y la empresa tiene "
        f"{len(de_la_empresa)}, pero la lista del pliego puede estar "
        "incompleta: confírmala en el numeral antes de descartar")}


def _evaluar_limitacion_mipyme(req: Requisito, perfil: PerfilEmpresa) -> dict:
    """
    «La convocatoria será limitada a Mipymes colombianas domiciliadas en el
    Municipio de X».

    Criterio CONJUNTO —las dos condiciones, no una— y **asimétrico**:

    - Si la empresa es Mipyme Y está domiciliada en ese municipio, **cumple**
      la limitación pase lo que pase. Ese lado es seguro.
    - Si NO lo es, **no se declara incumplimiento**: la limitación a Mipyme
      sólo se materializa cuando un número mínimo de Mipymes manifiesta
      interés (Decreto 1082/2015 art. 2.2.1.2.4.2.2), y eso se sabe después
      del plazo de manifestaciones, no al analizar el pliego. Paicol tiene de
      hecho dos requisitos procedimentales sobre esa manifestación. Declarar
      NO CUMPLE aquí sería descartar una oferta por una limitación que puede
      no llegar a aplicarse.
    """
    base = {"requisito": req.nombre, "categoria": req.categoria,
            "fuente_numeral": req.fuente_numeral}
    m = re.search(r"[Mm]unicipio\s+de\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñ]*"
                  r"(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]*)?)",
                  req.exigido_literal or "")
    if not m:
        return {**base, "estado": "revisar_manual", "motivo": (
            "el literal no dice a qué municipio limita la convocatoria: "
            "léelo en el numeral")}
    municipio = m.group(1).strip()
    propio = (perfil.municipio_domicilio or "").strip()
    if perfil.es_mipyme and propio and _strip_accents(propio.lower()) == \
            _strip_accents(municipio.lower()):
        return {**base, "estado": "cumple",
                "valor_empresa": f"Mipyme domiciliada en {propio}",
                "umbral": f"Mipyme domiciliada en {municipio}"}
    falta = []
    if not perfil.es_mipyme:
        falta.append("la empresa no está registrada como Mipyme")
    if not propio:
        falta.append("el perfil no dice el municipio de domicilio")
    elif _strip_accents(propio.lower()) != _strip_accents(municipio.lower()):
        falta.append(f"la empresa está domiciliada en {propio}, no en {municipio}")
    return {**base, "estado": "revisar_manual", "motivo": (
        " y ".join(falta) + ". NO es un incumplimiento: la limitación a Mipyme "
        "sólo se aplica si un mínimo de Mipymes manifiesta interés, y eso se "
        "sabe al cierre del plazo de manifestaciones")}


def _pregunta_por_duracion(req: Requisito) -> bool:
    """
    Si el requisito pregunta por cuánto dura la sociedad. Se mira el NOMBRE,
    no el objeto del catálogo: bajo `EXISTENCIA_REPRESENTACION` conviven la
    duración y el certificado, que son preguntas distintas [D32].
    """
    n = _strip_accents((req.nombre or "").lower())
    return "duracion" in n and ("plazo" in n or "contrato" in n)


def _evaluar_duracion_sociedad(
    req: Requisito,
    hasta: str,
    plazo_meses: float | None,
    fecha_referencia: date | None = None,
) -> dict:
    """
    ¿Dura la sociedad al menos el plazo del contrato más un año?

    Necesita DOS datos de fuentes distintas: la duración, que da el cliente, y
    el plazo del contrato, que da el pliego. Si falta el del pliego, el
    requisito NO vuelve a «no se le preguntó al cliente» —el cliente ya
    respondió— sino que nombra el dato que falta y de quién es. Es la
    diferencia entre una tarea del cliente y una del operador.
    """
    base = {"requisito": req.nombre, "categoria": req.categoria,
            "fuente_numeral": req.fuente_numeral}
    try:
        vence = date.fromisoformat(str(hasta)[:10])
    except (TypeError, ValueError):
        return {**base, "estado": "dato_faltante",
                "documento_requerido": "fecha de duración de la sociedad"}

    if plazo_meses is None:
        return {
            **base, "estado": "revisar_manual",
            "valor_empresa": vence.isoformat(),
            "motivo": ("la sociedad está constituida hasta "
                       f"{vence.isoformat()}, pero el análisis no pudo extraer "
                       "el plazo del contrato del pliego: compáralo a mano "
                       "contra el plazo más un año"),
        }

    hoy = fecha_referencia or date.today()
    # El plazo corre desde la suscripción del acta de inicio, que no se conoce:
    # se mide desde hoy, que es la lectura MÁS EXIGENTE y por tanto la segura.
    dias_exigidos = int(plazo_meses * 30) + 365
    dias_restantes = (vence - hoy).days
    if dias_restantes >= dias_exigidos:
        return {**base, "estado": "cumple", "valor_empresa": vence.isoformat(),
                "umbral": dias_exigidos, "operador": ">=", "unidad": "dias"}
    return {
        **base, "estado": "no_cumple", "valor_empresa": vence.isoformat(),
        "umbral": dias_exigidos, "operador": ">=", "unidad": "dias",
        "diferencia": dias_restantes - dias_exigidos,
        "motivo": (f"la sociedad dura hasta {vence.isoformat()}; el pliego "
                   f"exige el plazo del contrato ({plazo_meses:g} meses) más "
                   "un año"),
    }


def _evaluar_item(
    req: Requisito,
    perfil: PerfilEmpresa,
    valores_pliego: dict | None = None,
    fecha_referencia: date | None = None,
) -> dict:
    """
    Evalúa un requisito individual.

    Si req.criterio no es None, lo evalúa con el criterio estructurado (criterios.py).
    Si es None, usa el lookup por nombre (comportamiento anterior).
    [I6] Python puro: ninguna lógica de evaluación sale del LLM.
    """
    # ORDEN DE LOS GUARDAS — `aplica_a` va PRIMERO, y no es cosmético: si el
    # requisito no le rige a esta empresa no hay nada que evaluar, y cualquier
    # guarda por delante produce un veredicto sobre algo que no le aplica.
    # Encontrado midiendo: `no_aplica` bajó de 14 a 13 en Paicol cuando los
    # criterios nuevos se colaron por delante de este filtro.
    if req.aplica_a == "mipyme" and not perfil.es_mipyme:
        return {"requisito": req.nombre, "estado": "no_aplica", "categoria": req.categoria}
    if req.aplica_a == "no_mipyme" and perfil.es_mipyme:
        return {"requisito": req.nombre, "estado": "no_aplica", "categoria": req.categoria}

    # [D20/D32] Un requisito cuyo propio NOMBRE anuncia que reparte puntaje no
    # es un habilitante, por mucho que el extractor lo haya clasificado así
    # —«Mayor puntaje CF por pasivo corriente igual a cero» está en el capítulo
    # de habilitantes y su `evidencia_criticidad` es `capitulo_habilitantes`,
    # pero el literal dice «la Entidad debe otorgar el mayor puntaje»—.
    #
    # NO se excluye en silencio: va a `revisar_manual`, que es tarea del
    # OPERADOR y aparece en el informe. Esconderlo dejaría el defecto de
    # clasificación invisible; evaluarlo producía un CUMPLE falso sobre lo que
    # el informe presenta como habilitante.
    #
    # Medido sobre los dos pliegos: 1 de 184 habilitantes, y es el caso. Se
    # probaron antes dos contenciones más amplias y ninguna separa — el
    # `aspecto` del catálogo mezcla los tres requisitos de estados financieros,
    # y buscar «la Entidad» como sujeto de la obligación acierta 2 de 4 porque
    # «la Entidad rechazará» suele ser la CONSECUENCIA de un deber del
    # proponente, no un deber de la entidad.
    if (req.criticidad == "habilitante"
            and "puntaje" in _strip_accents((req.nombre or "").lower())):
        return {
            "requisito": req.nombre,
            "categoria": req.categoria,
            "fuente_numeral": req.fuente_numeral,
            "estado": "revisar_manual",
            "motivo": ("el nombre del requisito anuncia que reparte puntaje, "
                       "pero viene clasificado como habilitante: decide cuál "
                       "de las dos cosas es antes de usarlo"),
        }

    # [D34] La duración de la sociedad: el único requisito que necesita un dato
    # del perfil Y uno del pliego a la vez.
    if (_pregunta_por_duracion(req)
            and perfil.documentos is not None
            and perfil.documentos.duracion_sociedad_hasta):
        return _evaluar_duracion_sociedad(
            req, perfil.documentos.duracion_sociedad_hasta,
            (valores_pliego or {}).get("plazo_meses"), fecha_referencia)

    # Criterios que leen el literal del pliego además del perfil.
    _objeto = None
    try:
        from .catalogo import objeto_para_evaluar as _oe
        _objeto = _oe(req)
    except Exception:
        pass
    if _objeto == "UNSPSC":
        return _evaluar_unspsc(req, perfil)
    if _objeto == "CONDICION_MIPYME" and "limitac" in _strip_accents(
            (req.nombre or "").lower()):
        return _evaluar_limitacion_mipyme(req, perfil)
    # Extranjero sin domicilio → no aplica si la empresa es nacional (mipyme o con municipio)
    if req.aplica_a == "extranjero_sin_domicilio":
        es_nacional = perfil.es_mipyme or (perfil.municipio_domicilio is not None)
        if es_nacional:
            return {"requisito": req.nombre, "estado": "no_aplica", "categoria": req.categoria}

    # ── Inferencia de no_aplica por nombre — complementa aplica_a de extracciones previas
    _nl = req.nombre.lower()

    # Proponente plural → no aplica si la empresa es individual
    if not perfil.es_proponente_plural:
        _KW_PLURAL = (
            "proponente plural", "consorci", "unión temporal", "union temporal",
            "integrantes del proponente", "integrante de un proponente",
        )
        if any(kw in _nl for kw in _KW_PLURAL):
            return {"requisito": req.nombre, "estado": "no_aplica", "categoria": req.categoria}

    # Entidad estatal → nunca aplica a empresas privadas
    _KW_ESTATAL = ("entidad estatal", "acto de creación")
    if any(kw in _nl for kw in _KW_ESTATAL):
        return {"requisito": req.nombre, "estado": "no_aplica", "categoria": req.categoria}

    # Extranjero → no aplica si la empresa tiene municipio colombiano
    # "trato nacional" y "formato 9a" se omiten: también aplican a nacionales (opciones 1/2)
    if perfil.municipio_domicilio is not None:
        _KW_EXTRANJERO = (
            "extranjero sin domicilio",  # aplica_a explícito del extractor
            "para extranjero",           # Formato 9A opción 3, UNSPSC para extranjeros sin domicilio
            "proponente extranjero",     # nombre explícito del tipo de oferente
            "formato 9b",               # Incorporación de componente nacional en servicios extranjeros
        )
        if any(kw in _nl for kw in _KW_EXTRANJERO):
            return {"requisito": req.nombre, "estado": "no_aplica", "categoria": req.categoria}

    # ── [B8] Conflicto de umbral: el pliego define más de un valor ─────────
    # Ocurre cuando la fusión encuentra umbrales distintos entre los fragmentos
    # (p. ej. variantes mipyme / no_mipyme) o cuando la extracción discrepa.
    # Elegir uno daría un veredicto falso a un cliente: se reporta para revisión.
    if getattr(req, "conflicto_umbral", False):
        return {
            "requisito":  req.nombre,
            "estado":     "revisar_manual",
            "categoria":  req.categoria,
            "fuente_numeral": req.fuente_numeral,
            "umbrales_alternativos": getattr(req, "umbrales_alternativos", []),
            "motivo": (
                "El pliego define más de un umbral para este requisito. "
                "Verifica cuál aplica a tu tipo de proponente antes de ofertar."
            ),
        }

    # [N8] La unidad del umbral contradice la que nombra el pliego. El
    # extractor pone "meses" por defecto cuando la magnitud es temporal y no
    # resuelve cuál: "mínimo un AÑO de existencia" quedó como 1.0 meses, que
    # daría por válida a una empresa de seis meses. Ese falso positivo —decirle
    # al cliente que califica cuando va a ser rechazado— es peor que un falso
    # negativo, así que el requisito se reporta en vez de evaluarse.
    #
    # DETECCIÓN, no corrección: el valor no se toca. Deducir que "20 meses"
    # quería decir "20 años" sería inventar.
    _disc = unidad_discordante({
        "unidad": req.unidad, "valor_umbral": req.valor_umbral,
        "exigido_literal": req.exigido_literal,
        "fuente_numeral": req.fuente_numeral,
    })
    if _disc is not None:
        return {
            "requisito":  req.nombre,
            "estado":     "revisar_manual",
            "categoria":  req.categoria,
            "fuente_numeral": req.fuente_numeral,
            # Ambos datos, para que el operador vea la discrepancia y decida
            "unidad_registrada": _disc["etiqueta_campo"],
            "unidad_en_el_pliego": _disc["etiqueta_texto"],
            "valor_umbral": req.valor_umbral,
            "motivo": motivo_unidad_discordante({
                "valor_umbral": req.valor_umbral,
                "fuente_numeral": req.fuente_numeral,
            }, _disc),
        }

    # ── Camino con criterio estructurado ───────────────────────────────────
    if req.criterio is not None:
        from .criterios import evaluar_criterio
        res = evaluar_criterio(req.criterio, perfil.model_dump(), valores_pliego or {})
        base = {
            "requisito":      req.nombre,
            "categoria":      req.categoria,
            "fuente_numeral": getattr(req.criterio, "fuente_numeral", req.fuente_numeral),
            "pagina_origen":  getattr(req.criterio, "pagina_origen", req.pagina_origen),
        }
        if not res.evaluable:
            return {**base, "estado": "no_evaluable", "motivo": res.motivo_no_evaluable}
        r = {**base, "estado": "cumple" if res.cumple else "no_cumple"}
        if res.valor_empresa is not None:
            r["valor_empresa"] = res.valor_empresa
        if res.valor_umbral is not None:
            r["umbral"] = res.valor_umbral
        if res.puntaje is not None:
            r["puntaje"] = res.puntaje
        return r

    # ── Camino existente: lookup por nombre ────────────────────────────────
    valor = _valor_perfil(req, perfil)

    # dato_faltante: el campo no existe en el perfil — nunca tratar como 0
    if valor is None:
        return {
            "requisito": req.nombre,
            "estado": "dato_faltante",
            "categoria": req.categoria,
            "umbral": req.valor_umbral,
            "operador": req.operador,
            "unidad": req.unidad,
        }

    # [D27] Un documento se evalúa distinto de un número o un booleano: son dos
    # preguntas encadenadas —¿lo tiene? y ¿sigue vigente?— y el umbral del
    # pliego, cuando lo hay, se aplica a la ANTIGÜEDAD de la fecha, no a un
    # valor del perfil. Va ANTES de la comparación numérica porque si no, un
    # requisito con vigencia («RUP con máximo 30 días») intentaba `float()`
    # sobre el documento y salía por la rama de «valor no numérico».
    if isinstance(valor, Documento):
        return _evaluar_documento(req, valor, fecha_referencia)

    # Comparación numérica
    if req.valor_umbral is not None and req.operador is not None:
        try:
            cumple = _comparar(float(valor), req.valor_umbral, req.operador)
        except (TypeError, ValueError):
            return {
                "requisito": req.nombre,
                "estado": "dato_faltante",
                "categoria": req.categoria,
                "nota": f"valor del perfil no es numérico: {valor!r}",
            }
        return {
            "requisito": req.nombre,
            "estado": "cumple" if cumple else "no_cumple",
            "categoria": req.categoria,
            "valor_empresa": valor,
            "umbral": req.valor_umbral,
            "operador": req.operador,
            "unidad": req.unidad,
        }

    # Sin umbral numérico.
    #
    # Un BOOLEANO sí es una respuesta: el perfil afirma que tiene el documento
    # o que no lo tiene, y eso se puede sostener.
    #
    # Un NÚMERO, no. `bool(1.85)` es True, así que «Índice de liquidez» salía
    # como CUMPLE sin haber comparado 1,85 contra nada: el umbral del pliego no
    # se extrajo. Medido en Paicol el 2026-09-27: **11 de los 47 habilitantes
    # en CUMPLE venían de aquí**, y el informe se los presentaba al cliente
    # como requisitos satisfechos. El dato de la empresa existe; lo que falta
    # es el umbral, que es lectura del pliego y por tanto tarea del OPERADOR.
    if isinstance(valor, bool):
        return {
            "requisito": req.nombre,
            "estado": "cumple" if valor else "no_cumple",
            "categoria": req.categoria,
            "valor_empresa": valor,
        }
    return {
        "requisito": req.nombre,
        "estado": "revisar_manual",
        "categoria": req.categoria,
        "valor_empresa": valor,
        "motivo": (f"la empresa registra {valor}, pero el pliego no dejó un "
                   "umbral numérico extraíble contra el que compararlo: hay que "
                   "leer el numeral"),
    }


def _stats_categoria(items: list[dict]) -> dict:
    """Desglose de una categoría con fórmula visible. [I6]"""
    _estados_skip = {"no_aplica"}
    # revisar_manual [B8]: hay umbral, pero ambiguo. No cuenta como cumple ni
    # como no_cumple — el score no puede afirmar nada sobre este requisito.
    _estados_sin_dato = {"dato_faltante", "no_evaluable", "revisar_manual"}
    evaluados = [i for i in items if i["estado"] not in _estados_skip]
    con_datos = [i for i in evaluados if i["estado"] not in _estados_sin_dato]
    cumple = sum(1 for i in con_datos if i["estado"] == "cumple")
    no_cumple = sum(1 for i in con_datos if i["estado"] == "no_cumple")
    dato_faltante = sum(1 for i in evaluados if i["estado"] in _estados_sin_dato)

    # score = None cuando no hay datos — nunca 0.0
    score = (cumple / len(con_datos) * 100.0) if con_datos else None
    # cobertura: fracción de req evaluados que tienen dato
    cobertura = (len(con_datos) / len(evaluados)) if evaluados else 0.0

    return {
        "score": score,
        "cumple": cumple,
        "no_cumple": no_cumple,
        "dato_faltante": dato_faltante,
        "no_aplica": sum(1 for i in items if i["estado"] == "no_aplica"),
        "evaluados": len(evaluados),
        "cobertura": round(cobertura, 3),
    }


# ─── API pública ───────────────────────────────────────────────────────────

def evaluar_empresa(
    perfil: PerfilEmpresa,
    requisitos: list[Requisito],
    valores_pliego: dict | None = None,
    fecha_referencia: date | None = None,
) -> dict:
    """
    Contrastá el perfil con los requisitos habilitantes.

    [I6] Score calculado con fórmula explícita (_PESOS) en Python puro.
    [I4] veredicto se deriva de score_global + flags; no se asigna directamente.

    Retorna un dict con: empresa, es_mipyme, score_global, veredicto,
    desglose (por categoría), items (detalle de cada requisito).
    """
    # [D27] La vigencia de un documento se mide contra una fecha, así que el
    # mismo perfil y el mismo pliego pueden dar veredictos distintos en días
    # distintos. La fecha usada viaja en el resultado para que el informe la
    # declare: un CUMPLE por vigencia sin decir contra qué fecha se midió no es
    # reproducible.
    fecha_referencia = fecha_referencia or date.today()

    # ── Determinar rango × variante ANTES de evaluar ──────────────────────
    # Si no se puede determinar → "umbral_no_determinable" (nunca un default).
    # Un pliego contiene hasta 4 juegos: (rango_1|rango_2) × (mipyme|no_mipyme).
    clave_umbrales: str = "umbral_no_determinable"
    if valores_pliego:
        clave = seleccionar_rango_umbrales(
            presupuesto_cop=valores_pliego.get("presupuesto_oficial"),
            smmlv_anio=valores_pliego.get("smmlv_anio"),
            es_mipyme=perfil.es_mipyme,
        )
        if clave is not None:
            clave_umbrales = clave

    por_cat: dict[str, list[dict]] = {cat: [] for cat in _PESOS}

    for req in requisitos:
        cat = req.categoria if req.categoria in _PESOS else "documental"
        por_cat[cat].append(
            _evaluar_item(req, perfil, valores_pliego, fecha_referencia))

    desglose: dict[str, dict] = {}
    score_num = 0.0
    peso_num = 0.0
    hay_dato_faltante = False
    hay_no_cumple = False

    for cat, peso in _PESOS.items():
        items = por_cat[cat]
        stats = _stats_categoria(items)
        stats["peso"] = peso
        desglose[cat] = stats

        if stats["dato_faltante"] > 0:
            hay_dato_faltante = True
        if stats["no_cumple"] > 0:
            hay_no_cumple = True
        if stats["score"] is not None:
            score_num += stats["score"] * peso
            peso_num += peso

    # [I6] fórmula: media ponderada solo de categorías con datos
    score_global = (score_num / peso_num) if peso_num > 0 else 0.0

    # cobertura global: total requisitos con dato / total evaluados (ex no_aplica)
    total_evaluados = sum(s["evaluados"] for s in desglose.values())
    total_con_datos = sum(s["cumple"] + s["no_cumple"] for s in desglose.values())
    cobertura_global = (total_con_datos / total_evaluados) if total_evaluados > 0 else 0.0

    # [I4] veredicto derivado — nunca asignado a mano
    if hay_dato_faltante:
        veredicto = "dato_insuficiente"
    elif score_global >= 70.0 and not hay_no_cumple:
        veredicto = "viable"
    elif score_global < 50.0:
        veredicto = "no_viable"
    else:
        veredicto = "condicional"

    todos_items = [i for items in por_cat.values() for i in items]

    return {
        "empresa": perfil.nombre,
        "es_mipyme": perfil.es_mipyme,
        "clave_umbrales": clave_umbrales,
        "score_global": round(score_global, 2),
        "cobertura_global": round(cobertura_global, 3),
        "total_evaluados": total_evaluados,
        "total_con_datos": total_con_datos,
        "veredicto": veredicto,
        "desglose": desglose,
        "items": todos_items,
        # [D27] Contra qué fecha se midió la vigencia de los documentos. Sin
        # esto, un CUMPLE por vigencia no es reproducible.
        "fecha_referencia": fecha_referencia.isoformat(),
        "_formula": "score = Σ(score_cat × peso_cat) / Σ(peso_cat con datos)",
        "_pesos": _PESOS,
    }


# ─── Carga de perfil desde disco (para uso en routers) ─────────────────────

def cargar_perfil_por_cid(cid: str, base_dir: str | None = None) -> PerfilEmpresa | None:
    """
    Carga el perfil de un cliente desde disco y retorna PerfilEmpresa.

    Busca en orden:
      1. clientes/{cid}.json          (formato plano — JSON canónico)
      2. clientes/{cid}/perfil.json   (formato directorio — sesión web)

    Retorna None si no existe el archivo; el evaluador marcará todo como
    dato_faltante. Lanza ValueError si el archivo existe pero el JSON es inválido.

    Nunca retorna 0 para campos faltantes: los campos ausentes son None.
    """
    import json
    from pathlib import Path

    if base_dir is None:
        _repo = Path(__file__).parent.parent.parent
        _base = _repo / "clientes"
    else:
        _base = Path(base_dir)

    for ruta in [_base / f"{cid}.json", _base / cid / "perfil.json"]:
        if ruta.exists():
            try:
                data = json.loads(ruta.read_text("utf-8"))
            except Exception as exc:
                raise ValueError(f"JSON inválido en {ruta}: {exc}") from exc
            return cargar_perfil(data)

    return None
