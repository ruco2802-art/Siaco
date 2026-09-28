# -*- coding: utf-8 -*-
"""
src/evaluator.py — contraste perfil ↔ requisitos, Python puro.

[I6] Todas las comparaciones numéricas y el score se calculan aquí,
     nunca en el LLM ni en ningún otro módulo.
[I4] veredicto se deriva de score_global + flags; nunca se asigna a mano.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Callable

from pydantic import BaseModel

from .estados import motivo_unidad_discordante, unidad_discordante
from .extractor import Requisito
from .perfil import (  # esquema canónico — única fuente de verdad
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


def _valor_perfil(req: Requisito, perfil: PerfilEmpresa) -> Any:
    """
    Busca el valor del perfil correspondiente al requisito.
    Retorna None cuando el dato falta — NUNCA retorna 0 como sustituto.
    (Bug real: perfiles sin bloque financiero producían "NO VIABLE — datos en cero".)
    """
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
    nombre_n = _strip_accents(req.nombre.lower())
    for kw, _fn in MAPAS_POR_CATEGORIA.get(req.categoria or "", []):
        if _strip_accents(kw) in nombre_n:
            return kw
    return None


def _evaluar_item(
    req: Requisito,
    perfil: PerfilEmpresa,
    valores_pliego: dict | None = None,
) -> dict:
    """
    Evalúa un requisito individual.

    Si req.criterio no es None, lo evalúa con el criterio estructurado (criterios.py).
    Si es None, usa el lookup por nombre (comportamiento anterior).
    [I6] Python puro: ninguna lógica de evaluación sale del LLM.
    """
    # Respeta aplica_a
    if req.aplica_a == "mipyme" and not perfil.es_mipyme:
        return {"requisito": req.nombre, "estado": "no_aplica", "categoria": req.categoria}
    if req.aplica_a == "no_mipyme" and perfil.es_mipyme:
        return {"requisito": req.nombre, "estado": "no_aplica", "categoria": req.categoria}
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

    # Sin umbral numérico: check de presencia/booleano
    if isinstance(valor, bool):
        cumple = valor
    else:
        cumple = bool(valor)
    return {
        "requisito": req.nombre,
        "estado": "cumple" if cumple else "no_cumple",
        "categoria": req.categoria,
        "valor_empresa": valor,
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
) -> dict:
    """
    Contrastá el perfil con los requisitos habilitantes.

    [I6] Score calculado con fórmula explícita (_PESOS) en Python puro.
    [I4] veredicto se deriva de score_global + flags; no se asigna directamente.

    Retorna un dict con: empresa, es_mipyme, score_global, veredicto,
    desglose (por categoría), items (detalle de cada requisito).
    """
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
        por_cat[cat].append(_evaluar_item(req, perfil, valores_pliego))

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
