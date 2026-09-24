# -*- coding: utf-8 -*-
"""
pipeline/src/clasificador.py — Clasificación y consolidación de requisitos.

Sin API. Trabaja sobre objetos Requisito ya extraídos.

Tres operaciones de consolidación:
  a) Deduplicar: mismo requisito en varias secciones → uno con todas las fuentes
  b) Fusionar fragmentos: sub-condiciones del mismo objeto → un requisito
  c) Descartar no-requisitos: notas, métodos de cálculo, referencias → reporte aparte

Más una cuarta operación post-consolidación:
  d) Fusionar causales 1.15 con habilitantes y reclasificar ítems dentro de 1.15

Invariantes:
  [C1] Ningún requisito se descarta silenciosamente — los descartados se registran.
  [C2] La clasificación no requiere API — solo numeral y palabras clave.
  [C3] Todo requisito sin clasificación clara queda "indeterminado" y se reporta.
  [C4] Un requisito con valor_umbral numérico NUNCA se descarta como
       no-requisito por patrón semántico: las notas interpretan, no fijan
       valores exigibles. Un patrón que quiera descartarlo es demasiado ancho.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from .extractor import Requisito


# ─── Tipos ────────────────────────────────────────────────────────────────────

EvidenciaCriticidad = Literal[
    "capitulo_habilitantes", "limitacion_participacion",
    "causal_rechazo", "capitulo_presentacion", "capitulo_puntaje", "inferido",
]

Criticidad = Literal["habilitante", "puntaje", "procedimental", "indeterminado"]


@dataclass
class ResultadoClasificacion:
    criticidad: Criticidad
    evidencia: EvidenciaCriticidad | None
    tiene_plazo: bool


@dataclass
class ConsolidacionResultado:
    antes_total: int
    despues_dedup: int
    despues_fusion: int
    despues_descarte: int
    despues_causales: int          # tras fusión de causales 1.15
    requisitos: list[Requisito]
    descartados: list[dict]        # [C1]
    grupos_fusionados: list[dict]  # top 10 para el reporte


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFC", texto).lower().strip()
    return re.sub(r"\s+", " ", t)


def _extraer_prefijo_numeral(numeral: str) -> str:
    """Extrae "3.5.1" de "3.5.1. CARACTERÍSTICAS DE LOS CONTRATOS..."."""
    s = numeral.strip()
    # Numeral con letras mayúsculas tipo "A.", "B.", "C.", "D."
    m = re.match(r'^([A-D])\.\s', s)
    if m:
        return m.group(1) + "."
    # Numeral numérico
    m = re.match(r'^([\d.]+)', s)
    if m:
        return m.group(1).rstrip(".")
    return ""


def _contiene(texto: str, *patrones: str) -> bool:
    t = _normalizar(texto)
    return any(re.search(p, t) for p in patrones)


# ─── P1: Corrección de numerales mal asignados por el extractor ──────────────

# IDL, NDE, RCI aparecen en el JSON con numeral 3.5.8 por artefacto del chunker;
# el texto real está en 3.6 CAPACIDAD FINANCIERA.
_CORRECCIONES_NUMERAL: list[tuple[str, str, str]] = [
    # (patron_nombre, patron_numeral_incorrecto, numeral_corregido)
    (r"[ií]ndice.{0,20}liquidez|liquidez.{0,20}activo",
     r"3\.5\.", "3.6 CAPACIDAD FINANCIERA"),
    (r"[ií]ndice.{0,20}endeudamiento|nivel.{0,20}endeudamiento",
     r"3\.5\.", "3.6 CAPACIDAD FINANCIERA"),
    (r"raz[oó]n.{0,20}cobertura|cobertura.{0,20}inter[eé]s",
     r"3\.5\.", "3.6 CAPACIDAD FINANCIERA"),
]


def _corregir_numerales(reqs: list[Requisito]) -> int:
    """
    Corrige ítems cuyo numeral es incorrecto por artefacto del chunker.
    Devuelve el número de correcciones aplicadas.
    """
    n = 0
    for req in reqs:
        nombre_n = _normalizar(req.nombre)
        for pat_nombre, pat_numeral, numeral_nuevo in _CORRECCIONES_NUMERAL:
            if (re.search(pat_nombre, nombre_n)
                    and re.search(pat_numeral, req.fuente_numeral)):
                req.fuente_numeral = numeral_nuevo
                n += 1
                break
    return n


# ─── Patrones de no-requisitos ─────────────────────────────────────────────

_NO_REQUISITO_PATRONES: list[tuple[str, str]] = [
    # (patron_en_nombre_o_numeral, motivo)
    (r"cronograma",                        "instruccion_temporal"),
    (r"moneda",                            "instruccion_general"),
    (r"indicacion de trm",                 "instruccion_general"),
    (r"conversion.{0,25}smmlv",            "metodo_calculo"),
    (r"ajuste.{0,25}smmlv",               "metodo_calculo"),
    (r"orden de prevalencia",              "nota_interpretativa"),
    (r"consideraciones para la validez",   "nota_interpretativa"),
    (r"documentos validos para",           "nota_interpretativa"),
    (r"documentos validos y aceptables",   "nota_interpretativa"),
    (r"^formato \d+\b",                    "referencia_documento"),
    (r"^formato \d+ [–-]",                 "referencia_documento"),
    (r"formato 3 experiencia$",            "referencia_documento"),
    (r"disponibilidad y condiciones funcionales", "instruccion_general"),
    (r"porcentaje total aiu",              "instruccion_calculo"),
    (r"^capitulo (iii|viii)\b",            "encabezado_capitulo"),
]


def _es_no_requisito(req: Requisito) -> tuple[bool, str]:
    """
    Detecta condiciones de aplicación, notas, referencias y encabezados.
    Retorna (es_no_req, motivo). [C1]

    [C4] SALVAGUARDA: un requisito con `valor_umbral` numérico NUNCA es un
    no-requisito. Las notas explican cómo interpretar algo; no fijan valores
    que haya que cumplir. Si un patrón semántico quiere descartar algo que
    trae umbral, el patrón es demasiado ancho — no el requisito una nota.

    Casos reales que esto rescata en Paicol (3 falsos positivos):
      · 'integrante principal mínimo 50%' [50] ← patrón 'consideraciones para
        la validez', que casaba por un fragmento ABSORBIDO, no por el propio
      · 'Disponibilidad y condiciones funcionales de la maquinaria' [20]
      · 'Garantía de seriedad - ampliación de vigencia' [3] ← patrón 'cronograma'
    """
    if req.valor_umbral is not None or req.umbrales_alternativos:
        return False, ""

    texto = _normalizar(req.nombre + " " + req.fuente_numeral)
    for patron, motivo in _NO_REQUISITO_PATRONES:
        if re.search(patron, texto):
            return True, motivo
    # Prefijo B. = conversión SMMLV (siempre método de cálculo)
    if _extraer_prefijo_numeral(req.fuente_numeral) == "B.":
        return True, "metodo_calculo"
    return False, ""


# ─── Clasificador ─────────────────────────────────────────────────────────────

# Palabras clave que marcan plazo en el requisito
_PALABRAS_PLAZO = [
    r"en firme", r"vigencia.{0,15}dias", r"dias.{0,20}antes del cierre",
    r"antes del cierre", r"fecha.{0,15}cierre", r"dias? calendar",
    r"\d+ dias?", r"plazo",
]

# Mapeo numeral-exacto (prefijo numérico sin título) → (criticidad, evidencia)
_NUMERALES_EXACTOS: dict[str, tuple[Criticidad, EvidenciaCriticidad]] = {
    "2.5":  ("habilitante",   "limitacion_participacion"),
    "1.14": ("habilitante",   "limitacion_participacion"),
    "1.15": ("procedimental", "causal_rechazo"),
    "1.4":  ("habilitante",   "capitulo_habilitantes"),
    "1.13": ("indeterminado", "inferido"),
    "1.7":  ("indeterminado", "inferido"),
    "8.1":  ("procedimental", "capitulo_presentacion"),
}

# Prefijos que implican clasificación por capítulo
_PREFIJOS_HABILITANTE = ("3.", "A.", "C.", "D.")
_PREFIJOS_PROCEDIMENTAL_CAP2 = ("2.",)   # excepto 2.5 (ya capturado arriba)
_PREFIJOS_PROCEDIMENTAL_GAR = ("7.",)    # garantías
_PREFIJOS_PUNTAJE = ("4.",)


def clasificar_requisito(req: Requisito) -> ResultadoClasificacion:
    """
    Clasifica un Requisito sin API.

    Orden de evaluación (del usuario):
      1. ¿Es limitación de participación? → habilitante
      2. ¿Está en el capítulo de habilitantes? → habilitante
      3. ¿Está en causales de rechazo o capítulo de presentación? → procedimental
      4. ¿Está en el capítulo de puntaje? → puntaje
      5. Ninguno → indeterminado [C3]
    """
    prefijo = _extraer_prefijo_numeral(req.fuente_numeral)
    nombre_norm = _normalizar(req.nombre)
    literal_norm = _normalizar(req.exigido_literal)

    # ── Paso 0: numeral exacto (mayor precedencia) ────────────────────────
    if prefijo in _NUMERALES_EXACTOS:
        crit, ev = _NUMERALES_EXACTOS[prefijo]
        return ResultadoClasificacion(
            criticidad=crit, evidencia=ev,
            tiene_plazo=_tiene_plazo(req),
        )

    # ── Paso 1: limitaciones de participación por palabra clave ──────────
    if _contiene(nombre_norm + " " + literal_norm,
                 r"limitaci[oó]n.{0,20}mipyme", r"limitad[ao].{0,20}mipyme",
                 r"s[oó]lo.{0,20}mipyme", r"inhabilidades e incompatibilidades",
                 r"conflicto de inter[eé]s"):
        return ResultadoClasificacion(
            criticidad="habilitante", evidencia="limitacion_participacion",
            tiene_plazo=_tiene_plazo(req),
        )

    # ── Paso 2: capítulo III habilitantes ─────────────────────────────────
    if any(prefijo.startswith(p) for p in _PREFIJOS_HABILITANTE):
        return ResultadoClasificacion(
            criticidad="habilitante", evidencia="capitulo_habilitantes",
            tiene_plazo=_tiene_plazo(req),
        )
    if _contiene(req.fuente_numeral,
                 r"cap[ií]tulo iii", r"requisitos habilitantes",
                 r"capacidad financiera", r"capacidad jur[ií]dica"):
        return ResultadoClasificacion(
            criticidad="habilitante", evidencia="capitulo_habilitantes",
            tiene_plazo=_tiene_plazo(req),
        )

    # ── Paso 3: capítulo de presentación / causales de rechazo ───────────
    if any(prefijo.startswith(p) for p in _PREFIJOS_PROCEDIMENTAL_CAP2):
        return ResultadoClasificacion(
            criticidad="procedimental", evidencia="capitulo_presentacion",
            tiene_plazo=_tiene_plazo(req),
        )
    if any(prefijo.startswith(p) for p in _PREFIJOS_PROCEDIMENTAL_GAR):
        return ResultadoClasificacion(
            criticidad="procedimental", evidencia="capitulo_presentacion",
            tiene_plazo=_tiene_plazo(req),
        )
    if _contiene(req.fuente_numeral, r"cap[ií]tulo viii", r"minuta"):
        return ResultadoClasificacion(
            criticidad="procedimental", evidencia="capitulo_presentacion",
            tiene_plazo=_tiene_plazo(req),
        )

    # ── Paso 4: capítulo de puntaje ───────────────────────────────────────
    if any(prefijo.startswith(p) for p in _PREFIJOS_PUNTAJE):
        return ResultadoClasificacion(
            criticidad="puntaje", evidencia="capitulo_puntaje",
            tiene_plazo=False,
        )
    if _contiene(req.fuente_numeral,
                 r"criterios de evaluaci[oó]n", r"asignaci[oó]n de puntaje",
                 r"factores de desempate"):
        return ResultadoClasificacion(
            criticidad="puntaje", evidencia="capitulo_puntaje",
            tiene_plazo=False,
        )

    # ── Paso 5: [C3] indeterminado → reportar ────────────────────────────
    return ResultadoClasificacion(
        criticidad="indeterminado", evidencia="inferido",
        tiene_plazo=_tiene_plazo(req),
    )


def _tiene_plazo(req: Requisito) -> bool:
    texto = _normalizar(req.nombre + " " + req.exigido_literal)
    return any(re.search(p, texto) for p in _PALABRAS_PLAZO)


# ─── Operación a: Deduplicar ──────────────────────────────────────────────────

def _clave_dedup(req: Requisito) -> str:
    """Clave normalizada para detectar duplicados exactos."""
    return _normalizar(req.nombre)[:80]


def deduplicar(reqs: list[Requisito]) -> tuple[list[Requisito], int]:
    """
    Elimina duplicados exactos (mismo nombre normalizado).
    Conserva el que tiene numeral más específico (más puntos = más profundo).
    Devuelve (lista_dedup, n_eliminados).
    """
    grupos: dict[str, list[Requisito]] = defaultdict(list)
    for r in reqs:
        grupos[_clave_dedup(r)].append(r)

    resultado: list[Requisito] = []
    eliminados = 0
    for clave, grupo in grupos.items():
        if len(grupo) == 1:
            resultado.append(grupo[0])
        else:
            grupo_ord = sorted(
                grupo,
                key=lambda r: len(r.fuente_numeral.split(".")),
                reverse=True,
            )
            primario = grupo_ord[0].model_copy()
            todas_fuentes = list(dict.fromkeys(
                [primario.fuente_numeral] + [r.fuente_numeral for r in grupo_ord[1:]]
            ))
            primario.numerales_fuentes = todas_fuentes
            # [B8] Mismo descarte que en fusionar_fragmentos: si un duplicado
            # trae el umbral y el elegido no, se perdía.
            _propagar_campos_evaluables(primario, grupo_ord)
            resultado.append(primario)
            eliminados += len(grupo) - 1

    return resultado, eliminados


# ─── Operación b: Fusionar fragmentos ────────────────────────────────────────

# Mapeo: prefijo_numeral → clave_objeto_canónico
# Misma clave = se fusionan en un solo requisito.
# "_descartar" = se pasan a la operación c de descarte.
#
# ORDEN IMPORTA: las reglas más específicas van primero.
#
# [B11] TODA ESTA TABLA ES FALLBACK. Sólo aplica cuando el catálogo de objetos
# (pipeline/data/catalogo_objetos.json) no reconoce el objeto del requisito.
# Las entradas "_descartar" en particular: **sólo aplican en el fallback por
# prefijo. Con objeto identificado por catálogo, no se evalúan. Eran parche de
# la agrupación gruesa anterior** — descartaban sub-numerales que ensuciaban la
# fusión por prefijo, y que en la práctica quedaban absorbidos en una bolsa sin
# llegar nunca a la etapa de descarte.
# No se borran: si el catálogo falla o no cubre un pliego, el fallback sigue
# completo y el comportamiento anterior se mantiene.
_CLAVE_FUSION: list[tuple[str, str]] = [
    # Experiencia (cap III) — específicas primero, luego la raíz 3.5
    ("3.5.1",   "experiencia_rup"),           # características → fusiona con RUP
    ("3.5.2",   "_descartar"),               # consideraciones interpretativas
    ("3.5.3",   "experiencia_unspsc"),
    ("3.5.4",   "_descartar"),               # método acreditación = instrucción
    ("3.5.5",   "_descartar"),               # documentos válidos = instrucción
    ("3.5.6",   "_descartar"),               # sub-req contratos subcontrato
    ("3.5.7",   "_descartar"),               # sub-req contratos entre particulares
    ("3.5.8",   "experiencia_relacion_presupuesto"),
    ("3.5",     "experiencia_rup"),           # 3.5 top-level y 3.5.x sin regla propia
    # Personas / representación — específicas primero
    ("3.3.2",   "persona_juridica_docs"),
    ("3.3.3",   "proponentes_plurales"),
    ("3.3",     "existencia_representacion"), # persona natural (3 variantes)
    # Seguridad social — un solo grupo para todas las variantes (3.4.1–3.4.4)
    ("3.4",     "seguridad_social"),
    # Capacidad residual (CRP) — incluye sub-factores A. y C.
    ("3.10.1",  "crp_calculo"),
    ("3.9.1",   "experiencia_rup"),           # RUP para evaluación financiera/orgzl
    ("3.9.2",   "proponentes_extranjeros"),   # conservar; evaluador los omite si nacional
    ("A.",      "crp_calculo"),               # CO: documentos para cálculo CRP
    ("C.",      "crp_calculo"),               # CF: documentos para cálculo CRP
    ("D.",      "ct_capacidad_tecnica"),
    # Garantías post-adjudicación
    ("7.1.",    "garantia_seriedad"),
    ("7.2.1",   "garantia_cumplimiento"),
    ("7.2.2",   "garantia_estabilidad"),
    # Puntaje
    ("4.1",     "puntaje_propuesta_economica"),
    ("4.2.4",   "puntaje_ambiental"),
    ("4.2.5",   "puntaje_social"),
    ("4.3.1.1", "puntaje_servicios_nacionales"),
    ("4.3.2",   "puntaje_componente_nacional"),
    ("4.4",     "puntaje_empresas_mujeres"),
    # Control ejecución
    ("8.1.",    "control_ejecucion"),
    # Opción 2 (fragmentos de criterio social)
    ("[Opción",  "opcion_criterio_social"),
]


def _clave_fusion_para(prefijo: str, fuente_numeral: str = "") -> str | None:
    for pat, clave in _CLAVE_FUSION:
        if prefijo and (prefijo.startswith(pat) or prefijo == pat.rstrip(".")):
            return clave
    # Fallback sin prefijo numérico: CAPÍTULO III → experiencia_rup
    # (el fuente_numeral dice "REQUISITOS HABILITANTES", no "RUP")
    if not prefijo:
        fn = _normalizar(fuente_numeral)
        if re.search(r"cap[ií]tulo iii", fn):
            return "experiencia_rup"
    return None


# ─── [B9] Coherencia de grupo — regla de seguridad ───────────────────────────
#
# _CLAVE_FUSION agrupa por prefijo de numeral, lo que asume que "todo lo que
# está bajo 3.5 habla de lo mismo". En los Documentos Tipo del CCE eso es falso
# por diseño: las secciones organizan por TEMA, no por requisito. Bajo 3.5
# (Experiencia) conviven el RUP, los formatos, el número de contratos, la
# participación en consorcio y las obras excluidas.
#
# Antes de fusionar un grupo grande se verifica que sus miembros hablen del
# mismo objeto. Si no, NO se fusiona.
#
# Asimetría de daño (criterio fijo): dos requisitos separados que deberían ser
# uno inflan el conteo — visible y corregible. Dos requisitos distintos
# fusionados producen un veredicto falso sobre uno de ellos — invisible y
# peligroso. Ante la duda, NO fusionar.

_MIN_FRAGMENTOS_PARA_VERIFICAR = 5   # grupos de ≤4 se fusionan sin verificar

# Palabras que no identifican un objeto: gramaticales o genéricas del dominio.
_VACIAS: frozenset[str] = frozenset({
    # gramaticales
    "de", "del", "la", "las", "el", "los", "un", "una", "unos", "unas",
    "y", "o", "u", "e", "en", "con", "sin", "por", "para", "a", "al",
    "que", "se", "su", "sus", "no", "si", "como", "mas", "menos", "cuando",
    "sobre", "ante", "tras", "entre", "hasta", "desde", "segun",
    # genéricas del dominio: aparecen en casi cualquier requisito
    "proponente", "proponentes", "contrato", "contratos", "contratacion",
    "documento", "documentos", "oferta", "ofertas", "proceso", "entidad",
    "formato", "formatos", "general", "generales", "minimo", "minima",
    "maximo", "maxima", "valor", "valores", "condicion", "condiciones",
    "tipo", "tipos", "numero", "requisito", "requisitos", "presentacion",
    "legal", "legales", "debe", "deben", "cierre", "plazo",
})


def _stems(nombre: str) -> set[str]:
    """
    Raíces significativas del nombre, sin tildes ni palabras vacías.

    Trunca a 6 caracteres para que las variantes morfológicas coincidan:
    extranjero/extranjeros/extranjera → 'extran'; financiero/financiera →
    'financ'. No es un stemmer lingüístico: es un prefijo estable y
    reproducible, sin dependencias.
    """
    limpio = re.sub(r"[^a-z0-9\s]", " ", _strip_tildes(_normalizar(nombre)))
    out: set[str] = set()
    for palabra in limpio.split():
        # Mínimo 3: las siglas del dominio son cortas y sí identifican objeto
        # (RUP, RUT, CGR, ROE, ROA, IDL, CRP). Filtrar por longitud las perdía.
        if len(palabra) < 3 or palabra in _VACIAS:
            continue
        out.add(palabra[:6])
    return out


def _strip_tildes(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


# [B10] Encabezados de capítulo de los Documentos Tipo del CCE. Aparecen en la
# mayoría de los nombres de una sección entera sin identificar ningún requisito
# concreto: bajo "Experiencia" conviven el nº de contratos, los valores mínimos
# y la subsanabilidad. Si el único término común de un grupo es uno de éstos,
# el grupo es una bolsa temática, no un requisito.
# Truncados a 6 caracteres para cubrir las variantes morfológicas (ver _stems).
_STEMS_GENERICOS: frozenset[str] = frozenset({
    "capaci",   # capacidad, capacidades
    "experi",   # experiencia, experiencias
    "requis",   # requisito, requisitos
    "docume",   # documento, documentos, documental
    "acredi",   # acreditación, acreditar
    "verifi",   # verificación, verificar
    "propon",   # proponente, proponentes
    "contra",   # contrato, contratos, contratación
    "oferta",   # oferta, ofertas
    "condic",   # condición, condiciones
    "genera",   # general, generales
    "presen",   # presentación, presentar
    "inform",   # información, informe
    "criter",   # criterio, criterios
})


def objeto_comun(miembros: list[Requisito]) -> str | None:
    """
    Raíz presente en la MAYORÍA de los nombres del grupo, o None.

    None ⇒ los miembros hablan de cosas distintas ⇒ el grupo está mal formado.
    Es una propiedad estructural, no una lista de casos conocidos: aplica a
    cualquier pliego.

    [B10] Los términos genéricos del CCE no cuentan como objeto: si lo único que
    comparte la mayoría es "capacidad" o "experiencia", el grupo es una bolsa
    temática. Se descartan y se busca si queda algún término específico.
    """
    if not miembros:
        return None
    conteo: dict[str, int] = defaultdict(int)
    for m in miembros:
        for stem in _stems(m.nombre):
            conteo[stem] += 1

    umbral = len(miembros) / 2          # mayoría estricta
    candidatos = [
        (n, s) for s, n in conteo.items()
        if n > umbral and s not in _STEMS_GENERICOS
    ]
    if not candidatos:
        return None
    # Más frecuente; a igualdad, la raíz más larga (más específica)
    candidatos.sort(key=lambda ns: (-ns[0], -len(ns[1])))
    return candidatos[0][1]


def grupo_es_coherente(miembros: list[Requisito]) -> tuple[bool, str | None]:
    """
    (coherente, objeto_comun). Los grupos pequeños se aceptan sin verificar:
    el riesgo de bolsa crece con el tamaño.
    """
    if len(miembros) < _MIN_FRAGMENTOS_PARA_VERIFICAR:
        return True, objeto_comun(miembros)
    obj = objeto_comun(miembros)
    return (obj is not None), obj


_RATIO_MAGNITUD_INCOMPATIBLE = 5.0


def magnitudes_incompatibles(valores: list[float]) -> bool:
    """
    True si los umbrales del grupo abarcan magnitudes que no pueden ser
    variantes de un mismo requisito.

    Señal de agrupación errónea: '30 días', '5 contratos' y '10 %' no son
    variantes de un mismo umbral. Las variantes reales de un requisito quedan
    cerca entre sí — mipyme 1,1 vs no-mipyme 1,2; contratos 5/6/7 — rara vez
    más de 5×. Por encima de ese factor los números miden cosas distintas.

    El campo `unidad` sería la señal directa, pero viene None en la mayoría de
    las extracciones; la magnitud es el proxy disponible.
    """
    vals = [abs(v) for v in valores if v]
    if len(vals) < 2:
        return False
    return max(vals) / min(vals) > _RATIO_MAGNITUD_INCOMPATIBLE


def umbrales_del_grupo(miembros: list[Requisito]) -> list[float]:
    """Valores de umbral distintos aportados por los miembros de un grupo."""
    return sorted({m.valor_umbral for m in miembros if m.valor_umbral is not None})


def _elegir_primario(miembros: list[Requisito], objeto: str | None) -> Requisito:
    """
    [B9] El nombre del grupo debe venir del objeto común, no del accidente de
    tener el numeral más profundo. Antes, 21 requisitos de experiencia se
    llamaban 'Exclusión de tipos de obras no válidas' por eso.
    """
    candidatos = miembros
    if objeto is not None:
        con_objeto = [m for m in miembros if objeto in _stems(m.nombre)]
        if con_objeto:
            candidatos = con_objeto
    return max(candidatos, key=lambda r: (
        len(r.fuente_numeral.split(".")),
        len(r.exigido_literal),
    ))


def _propagar_campos_evaluables(primario: Requisito, miembros: list[Requisito]) -> None:
    """
    [B8] Recoge de CUALQUIER miembro del grupo los campos que hacen evaluable
    el requisito. Modifica `primario` in-place.

    El primario aporta identidad (nombre, fuente_numeral, ubicación); el umbral
    puede venir de otro miembro. Antes se descartaba junto con el resto del
    miembro: 35 de 42 umbrales de Paicol se perdían así.

    Conflicto: si dos miembros traen umbrales DISTINTOS no se elige ninguno.
    Puede ser legítimo (variantes mipyme / no_mipyme) o un error de extracción;
    en ambos casos aplicar uno a ciegas daría un veredicto falso. Se conservan
    todos en `umbrales_alternativos`, se marca `conflicto_umbral` y se deja
    `valor_umbral=None` para que ningún consumidor que ignore la bandera pueda
    evaluar con un umbral arbitrario.
    """
    # ── Umbrales: recolectar todos los distintos, con su procedencia ──────
    candidatos: dict[tuple, dict] = {}
    for m in miembros:
        if m.valor_umbral is None:
            continue
        clave = (m.valor_umbral, m.operador, m.unidad)
        if clave not in candidatos:
            candidatos[clave] = {
                "valor_umbral":   m.valor_umbral,
                "operador":       m.operador,
                "unidad":         m.unidad,
                "fuente_numeral": m.fuente_numeral,
                "nombre":         m.nombre,
            }

    if len(candidatos) == 1:
        c = next(iter(candidatos.values()))
        primario.valor_umbral          = c["valor_umbral"]
        primario.operador              = c["operador"]
        primario.unidad                = c["unidad"]
        primario.fuente_umbral_numeral = c["fuente_numeral"]
        primario.conflicto_umbral      = False
    elif len(candidatos) > 1:
        primario.umbrales_alternativos = list(candidatos.values())
        primario.conflicto_umbral      = True
        primario.valor_umbral          = None   # nadie evalúa a ciegas
        primario.operador              = None
        primario.fuente_umbral_numeral = None

    # ── Criterio estructurado: el primero que lo traiga ───────────────────
    if primario.criterio is None:
        for m in miembros:
            if m.criterio is not None:
                primario.criterio = m.criterio
                break

    # ── Página de origen: sólo si el primario no la tiene ─────────────────
    if primario.pagina_origen is None:
        for m in miembros:
            if m.pagina_origen is not None:
                primario.pagina_origen = m.pagina_origen
                break


def _tiene_objeto_catalogo(req: Requisito) -> bool:
    """True si el catálogo de objetos reconoce el requisito. Nunca lanza."""
    try:
        from .catalogo import identificar_objeto
        return identificar_objeto(req) is not None
    except Exception:
        return False


def _clave_grupo(req: Requisito) -> tuple | None:
    """
    [B11] Clave de fusión, con el catálogo de objetos como fuente primaria.

    Precedencia:
      1. Catálogo: (objeto, aspecto, capítulo). Agrupa por SIGNIFICADO.
      2. Fallback `_CLAVE_FUSION` por prefijo de numeral —incluido `_descartar`—
         para lo que el catálogo no reconoce todavía.

    Los grupos del catálogo son semánticamente coherentes por construcción;
    los del fallback siguen pasando por `grupo_es_coherente()` [B9].
    Devuelve None cuando nada agrupa: el requisito queda solo [K1].
    """
    try:
        from .catalogo import clave_agrupacion
        k = clave_agrupacion(req)
    except Exception as exc:
        # Sin catálogo el pipeline sigue con el comportamiento anterior
        print(f"[CLASIFICADOR] Catálogo no disponible, usando prefijos: {exc}")
        k = None

    if k is not None:
        # [B11] `aspecto=None` NO agrupa. None no significa "comparten algo",
        # significa "ningún aspecto encajó". Agrupar por ausencia de
        # clasificación fue lo que formó un grupo de 11 con fechas de
        # ejecución, NSR-98/NSR-10, área construida, cesión y antigüedad de la
        # persona jurídica — cinco requisitos distintos bajo un solo veredicto.
        # Reconocer el objeto no basta: sin aspecto, el requisito queda solo.
        if k[1] is None:
            return None
        return ("cat", *k)

    prefijo = _extraer_prefijo_numeral(req.fuente_numeral)
    clave_pref = _clave_fusion_para(prefijo, req.fuente_numeral)
    if clave_pref is not None:
        return ("pref", clave_pref)
    return None


def fusionar_fragmentos(
    reqs: list[Requisito],
) -> tuple[list[Requisito], list[dict]]:
    """
    Agrupa sub-condiciones del mismo objeto en un solo Requisito.
    Devuelve (lista_fusionada, grupos_info_para_reporte).
    """
    grupos_fusion: dict[tuple, list[Requisito]] = defaultdict(list)
    sin_grupo: list[Requisito] = []

    # Marcado semántico que no depende de cómo se agrupó: se conserva aunque
    # el catálogo tome la clave primaria.
    _es_extranjero: dict[int, bool] = {}
    for r in reqs:
        pref = _extraer_prefijo_numeral(r.fuente_numeral)
        _es_extranjero[id(r)] = _clave_fusion_para(pref, r.fuente_numeral) == "proponentes_extranjeros"

    for r in reqs:
        clave = _clave_grupo(r)
        if clave is None:
            sin_grupo.append(r)
        else:
            grupos_fusion[clave].append(r)

    resultado: list[Requisito] = list(sin_grupo)
    grupos_info: list[dict] = []

    def _marcar(r: Requisito) -> Requisito:
        """Conserva aplica_a de extranjeros, agrupe quien agrupe [B11]."""
        if _es_extranjero.get(id(r)):
            r = r.model_copy()
            r.aplica_a = "extranjero_sin_domicilio"
        return r

    for clave, miembros in grupos_fusion.items():
        origen = clave[0]                      # "cat" | "pref"
        etiqueta = clave[1] if origen == "pref" else clave[1]

        if origen == "pref" and etiqueta == "_descartar":
            resultado.extend(miembros)
            continue

        if len(miembros) == 1:
            resultado.append(_marcar(miembros[0]))
            continue

        # ── [B9] Regla de seguridad, sólo para el fallback por prefijo ───────
        # Los grupos del catálogo son coherentes por construcción: comparten
        # objeto, aspecto y capítulo. La regla protege lo que el catálogo aún
        # no cubre, donde la clave sigue siendo el prefijo del numeral.
        if origen == "cat":
            coherente, objeto = True, None
        else:
            coherente, objeto = grupo_es_coherente(miembros)

        if not coherente:
            # Grupo mal formado: se dejan los miembros SEPARADOS.
            for m in miembros:
                resultado.append(_marcar(m))
            grupos_info.append({
                "clave": etiqueta,
                "n_originales": len(miembros),
                "numeral_primario": miembros[0].fuente_numeral,
                "nombres_fusionados": [m.nombre for m in miembros],
                "fusion_rechazada": True,
                "motivo": "sin_objeto_comun",
            })
            continue

        # Elegir primario. Con clave del catálogo el objeto ya está declarado,
        # así que se usa su alias como sesgo del nombre [B11]; con el fallback,
        # el objeto común que halló la regla [B9].
        if origen == "cat":
            from .catalogo import _stems_objeto_para  # type: ignore[attr-defined]
            objeto = _stems_objeto_para(clave[1])
        primario_base = _elegir_primario(miembros, objeto)
        primario = primario_base.model_copy()

        # Acumular fuentes únicas
        todas_fuentes = list(dict.fromkeys(
            m.fuente_numeral for m in miembros
        ))
        primario.numerales_fuentes = todas_fuentes

        # [B8] Recoger umbral/criterio/página de cualquier miembro antes de
        # descartar el resto. Sin esto el grupo pierde su base numérica.
        _propagar_campos_evaluables(primario, miembros)

        # Los nombres absorbidos siguen siendo buscables en el informe.
        primario.nombres_absorbidos = [
            m.nombre for m in miembros if m.nombre != primario.nombre
        ]

        # Marcar aplica_a para proponentes extranjeros
        if clave == "proponentes_extranjeros":
            primario.aplica_a = "extranjero_sin_domicilio"

        # Concatenar literales adicionales
        extras = [
            m.exigido_literal for m in miembros
            if m is not primario_base and m.exigido_literal not in primario.exigido_literal
        ]
        if extras:
            primario.exigido_literal = (
                primario.exigido_literal + "\n\n[Condiciones adicionales fusionadas:]\n"
                + "\n---\n".join(extras[:5])
            )

        resultado.append(primario)
        grupos_info.append({
            "clave":    clave,
            "n_originales": len(miembros),
            "numeral_primario": primario.fuente_numeral,
            "nombres_fusionados": [m.nombre for m in miembros],
        })

    grupos_info.sort(key=lambda g: g["n_originales"], reverse=True)
    return resultado, grupos_info


# ─── Operación c: Descartar no-requisitos ────────────────────────────────────

def descartar_no_requisitos(
    reqs: list[Requisito],
) -> tuple[list[Requisito], list[dict]]:
    """
    Separa condiciones de aplicación, notas y referencias.
    Devuelve (requisitos_válidos, descartados_con_motivo). [C1]
    """
    validos: list[Requisito] = []
    descartados: list[dict] = []

    for r in reqs:
        # [B11] La regla `_descartar` por numeral sólo aplica cuando el catálogo
        # NO reconoce el objeto. Era un parche de la agrupación gruesa: con la
        # fusión por prefijo esos sub-numerales quedaban absorbidos en una bolsa
        # y nunca llegaban aquí. El catálogo los hace visibles como requisitos
        # propios, y aplicar el parche los eliminaba — 24 requisitos y 8
        # umbrales, entre ellos "contratos acreditables (Mipyme) [6]" y
        # "proponente plural: integrante principal [50]".
        # Las notas interpretativas las atrapa _NO_REQUISITO_PATRONES, que actúa
        # sobre el NOMBRE y no depende de la numeración.
        if not _tiene_objeto_catalogo(r):
            prefijo = _extraer_prefijo_numeral(r.fuente_numeral)
            if _clave_fusion_para(prefijo, r.fuente_numeral) == "_descartar":
                descartados.append({
                    "numeral": r.fuente_numeral,
                    "nombre": r.nombre,
                    "motivo": "marcado_descartar_fusion",
                })
                continue

        es_no_req, motivo = _es_no_requisito(r)
        if es_no_req:
            descartados.append({
                "numeral": r.fuente_numeral,
                "nombre": r.nombre,
                "motivo": motivo,
            })
            continue

        validos.append(r)

    return validos, descartados


# ─── Operación d: Fusionar causales 1.15 con habilitantes ────────────────────

# Causales 1.15 de grupo (a): encontrar habilitante correspondiente y marcar.
# Causales de grupo (?): reclasificar como habilitantes autónomos.
_CAUSALES_RECLASIFICAR_HAB: list[str] = [
    r"insolvencia|ley 1116",          # → habilitante (capacidad jurídica)
    r"objeto social",                  # → habilitante (capacidad jurídica)
    r"personal profesional",           # → habilitante (capacidad técnica)
]

_CAUSALES_MATCH_HABILITANTE: list[tuple[str, str]] = [
    # (patron_causal, patron_habilitante_destino)
    (r"\brup\b",                      r"\brup\b"),
    (r"inhabilidad|incompatibilidad", r"inhabilidad|capacidad jur"),
    (r"conflicto de inter",           r"conflicto de inter"),
    (r"mipyme",                       r"mipyme|limitaci"),
]


def fusionar_causales_rechazo(
    reqs: list[Requisito],
    descartados: list[dict],
) -> tuple[list[Requisito], list[dict]]:
    """
    Post-consolidación para causales 1.15:
      - Grupo (a): fusiona con el habilitante correspondiente → marca
                   es_causal_rechazo_explicita = True en el habilitante.
      - Grupo (?): reclasifica insolvencia, objeto social, personal → habilitante.
      - Resto: permanece procedimental.
    """
    from_1_15 = [r for r in reqs if "1.15" in r.fuente_numeral]
    otros = [r for r in reqs if "1.15" not in r.fuente_numeral]

    habilitantes = [r for r in otros if r.criticidad == "habilitante"]

    reclasificados: list[Requisito] = []
    permanecen_proc: list[Requisito] = []

    for causal in from_1_15:
        texto = _normalizar(causal.nombre + " " + causal.exigido_literal[:300])

        # ── ¿Es candidato a habilitante autónomo? ────────────────────────
        es_hab_autonomo = any(re.search(p, texto) for p in _CAUSALES_RECLASIFICAR_HAB)
        if es_hab_autonomo:
            c = causal.model_copy()
            c.criticidad = "habilitante"
            c.evidencia_criticidad = "capitulo_habilitantes"
            reclasificados.append(c)
            continue

        # ── ¿Duplica un habilitante ya consolidado? ──────────────────────
        destino = None
        for pat_causal, pat_hab in _CAUSALES_MATCH_HABILITANTE:
            if re.search(pat_causal, texto):
                destino = next(
                    (h for h in habilitantes
                     if re.search(pat_hab, _normalizar(h.nombre + " " + h.exigido_literal[:150]))),
                    None,
                )
                if destino:
                    break

        if destino:
            destino.es_causal_rechazo_explicita = True
            # El nombre de la causal debe seguir siendo buscable en el informe:
            # un operador que no encuentre "inhabilidades" asume que no se revisó.
            if causal.nombre not in destino.nombres_absorbidos:
                destino.nombres_absorbidos.append(causal.nombre)
            descartados.append({
                "numeral": causal.fuente_numeral,
                "nombre": causal.nombre,
                "motivo": "fusionado_en_habilitante",
            })
        else:
            # Grupo (b)/(c) o sin correspondencia → queda como procedimental
            permanecen_proc.append(causal)

    resultado = otros + reclasificados + permanecen_proc
    return resultado, descartados


# ─── Pipeline completo ────────────────────────────────────────────────────────

def consolidar(reqs: list[Requisito]) -> ConsolidacionResultado:
    """
    Ejecuta: corrección de numerales → clasificación → dedup → fusión → descarte
    → fusión de causales 1.15.
    """
    total_antes = len(reqs)

    # 0. Corregir numerales mal asignados (IDL/NDE/RCI → 3.6)
    _corregir_numerales(reqs)

    # 1. Clasificar — in-place
    for req in reqs:
        clf = clasificar_requisito(req)
        req.criticidad = clf.criticidad
        req.evidencia_criticidad = clf.evidencia
        req.tiene_plazo = clf.tiene_plazo

    # 2. Deduplicar
    reqs_dedup, _ = deduplicar(reqs)
    despues_dedup = len(reqs_dedup)

    # 3. Fusionar fragmentos
    reqs_fusionados, grupos_info = fusionar_fragmentos(reqs_dedup)
    despues_fusion = len(reqs_fusionados)

    # 4. Descartar no-requisitos
    reqs_finales, descartados = descartar_no_requisitos(reqs_fusionados)
    despues_descarte = len(reqs_finales)

    # 5. Fusionar causales 1.15 con habilitantes [C1: descartados se amplía]
    reqs_finales, descartados = fusionar_causales_rechazo(reqs_finales, descartados)
    despues_causales = len(reqs_finales)

    return ConsolidacionResultado(
        antes_total=total_antes,
        despues_dedup=despues_dedup,
        despues_fusion=despues_fusion,
        despues_descarte=despues_descarte,
        despues_causales=despues_causales,
        requisitos=reqs_finales,
        descartados=descartados,
        grupos_fusionados=grupos_info[:10],
    )
