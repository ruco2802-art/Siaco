# -*- coding: utf-8 -*-
"""
El concepto del informe: la escala de cuatro grados y el origen de cada dato
que falta.

Dos ideas gobiernan este módulo.

**Primera: el concepto se degrada, no se promedia.** NO VIABLE es un hecho
medido —un requisito habilitante resultó incumplido—, no una duda. VIABLE CON
SALVEDADES es la ausencia de ese hecho con puntos abiertos. SIN CONCEPTO es la
confesión de que la información no alcanza. Un informe que dice VIABLE cuando
no verificó la mitad de los habilitantes afirma algo que no sabe.

**Segunda: «no hay dato» reúne dos cosas opuestas.** Que el perfil no tenga la
respuesta puede ser un HALLAZGO sobre la empresa o un HUECO NUESTRO, y la
diferencia no es cosmética: el primero es el servicio que se vende, el segundo
es una limitación de nuestro formulario. Hoy el evaluador los produce iguales.
`origen_dato_faltante()` los separa; `FRASE_CLIENTE` decide qué se le dice al
cliente, que es lo mismo en los dos casos —*debe confirmar*— porque no
afirmamos ni que lo tenga ni que le falte. La distinción viaja al informe en la
sección de trazabilidad, no en la de documentos: ahí es donde va lo nuestro.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

# ── La escala ──────────────────────────────────────────────────────────────

ESCALA: dict[str, dict[str, str]] = {
    "no_viable": {
        "etiqueta": "NO VIABLE",
        "clase": "concepto-no-viable",
        "definicion": "Un requisito habilitante resultó incumplido.",
    },
    "con_salvedades": {
        "etiqueta": "VIABLE CON SALVEDADES",
        "clase": "concepto-con-salvedades",
        "definicion": ("Ningún requisito habilitante resultó incumplido, pero "
                       "quedan puntos sin resolver que debe verificar."),
    },
    "viable": {
        "etiqueta": "VIABLE",
        "clase": "concepto-viable",
        "definicion": ("Todos los requisitos habilitantes con umbral "
                       "verificable se resolvieron y ninguno quedó abierto."),
    },
    "sin_concepto": {
        "etiqueta": "SIN CONCEPTO",
        "clase": "concepto-sin-concepto",
        "definicion": ("La información disponible no alcanza para "
                       "pronunciarse."),
    },
}

ORDEN_GRAVEDAD: tuple[str, ...] = ("no_viable", "sin_concepto",
                                   "con_salvedades", "viable")

# ── Los umbrales que NO están fijados ──────────────────────────────────────
#
# UMBRAL_SIN_CONCEPTO es la proporción de habilitantes numéricos resueltos por
# debajo de la cual no habría base para pronunciarse. Queda en None a
# propósito:
#
#   umbral pendiente de calibrar con perfiles reales; con 13 habilitantes
#   numéricos cada requisito vale 7,7 puntos y cualquier corte queda a un
#   requisito de distancia.
#
# Es decir: el único caso medido (Paicol, 7/13 = 53,8%) cae a 3,8 puntos del
# 50% que se propuso, que es menos de lo que mueve un solo requisito. Un umbral
# así no separa casos, los decide por azar de redondeo.
#
# CONDICIÓN PARA FIJARLO: tres o cuatro análisis con perfiles de clientes
# reales. Hasta entonces `sin_concepto` sólo lo emiten las condiciones
# ABSOLUTAS de abajo, que no requieren calibración porque no son proporciones.
UMBRAL_SIN_CONCEPTO: float | None = None

# UMBRAL_VIABLE tenía el mismo defecto (se propuso 0,80 = 10,4 de 13
# requisitos, un corte que no cae en un número entero de requisitos), así que
# tampoco se fija. Mientras sea None, VIABLE exige la condición absoluta:
# CERO puntos abiertos y TODOS los habilitantes numéricos resueltos. No es un
# umbral, es la ausencia de duda — y errar por exceso de rigor no puede
# producir un falso VIABLE.
UMBRAL_VIABLE: float | None = None


def emitir(
    n_hab_numericos: int,
    n_resueltos: int,
    n_incumplidos: int,
    n_abiertos: int,
) -> dict[str, Any]:
    """
    Emite el concepto a partir de cuatro conteos. Python puro: ninguna decisión
    de veredicto sale de un modelo [I6].

    Devuelve `concepto`, `etiqueta`, `definicion`, `motivo` (la razón concreta,
    con los números de este caso) y `tasa_resueltos`.
    """
    tasa = n_resueltos / n_hab_numericos if n_hab_numericos else 0.0

    if n_incumplidos > 0:
        clave = "no_viable"
        motivo = (
            "1 requisito habilitante resultó incumplido" if n_incumplidos == 1
            else f"{n_incumplidos} requisitos habilitantes resultaron incumplidos")
    # ── Condiciones ABSOLUTAS de sin_concepto: no son proporciones, así que no
    #    dependen de un umbral por calibrar.
    elif n_hab_numericos == 0:
        clave, motivo = "sin_concepto", (
            "el pliego no dejó ningún requisito habilitante con umbral "
            "numérico verificable: no hay nada que medir")
    elif n_resueltos == 0:
        clave, motivo = "sin_concepto", (
            f"no se pudo resolver ninguno de los {n_hab_numericos} requisitos "
            "habilitantes con umbral numérico")
    # ── El umbral proporcional, si algún día se fija.
    elif UMBRAL_SIN_CONCEPTO is not None and tasa < UMBRAL_SIN_CONCEPTO:
        clave, motivo = "sin_concepto", (
            f"sólo se resolvió el {tasa:.0%} de los habilitantes numéricos, "
            f"por debajo del {UMBRAL_SIN_CONCEPTO:.0%} exigido")
    elif (n_abiertos > 0
          or n_resueltos < n_hab_numericos
          or (UMBRAL_VIABLE is not None and tasa < UMBRAL_VIABLE)):
        partes = []
        if n_abiertos:
            partes.append(f"{n_abiertos} punto{'s' if n_abiertos > 1 else ''} "
                          f"sin resolver")
        if n_resueltos < n_hab_numericos:
            partes.append(f"{n_hab_numericos - n_resueltos} de "
                          f"{n_hab_numericos} habilitantes numéricos sin datos "
                          "para medirlos")
        clave = "con_salvedades"
        motivo = ("ningún habilitante resultó incumplido, pero quedan "
                  + " y ".join(partes))
    else:
        clave, motivo = "viable", (
            f"los {n_hab_numericos} habilitantes numéricos se resolvieron y no "
            "quedó ningún punto abierto")

    return {
        "concepto": clave,
        "etiqueta": ESCALA[clave]["etiqueta"],
        "clase": ESCALA[clave]["clase"],
        "definicion": ESCALA[clave]["definicion"],
        "motivo": motivo,
        "tasa_resueltos": tasa,
        "umbral_sin_concepto_activo": UMBRAL_SIN_CONCEPTO is not None,
        "umbral_viable_activo": UMBRAL_VIABLE is not None,
    }


# ── El origen de un dato que falta ─────────────────────────────────────────

ORIGENES: dict[str, dict[str, str]] = {
    "le_falta": {
        "etiqueta": "LE FALTA",
        "dueno": "cliente",
        "que_es": "hallazgo",
        "interno": ("el perfil responde que NO lo tiene — es un hallazgo sobre "
                    "la empresa, el valor del análisis"),
    },
    "campo_sin_respuesta": {
        "etiqueta": "SIN RESPONDER",
        "dueno": "cliente",
        "que_es": "hueco del perfil",
        "interno": ("el perfil tiene el campo y quedó vacío — falta "
                    "completarlo, no falta construirlo"),
    },
    "no_preguntado": {
        "etiqueta": "NO PREGUNTADO",
        "dueno": "nosotros",
        "que_es": "hueco nuestro",
        "interno": ("el formulario del perfil no tiene ningún campo para este "
                    "concepto — es una limitación nuestra, no un dato de la "
                    "empresa"),
    },
    "no_se_responde_con_un_campo": {
        "etiqueta": "CONDICIÓN DEL PLIEGO",
        "dueno": "nadie",
        "que_es": "regla, no pregunta",
        "interno": ("no es un dato de la empresa ni un campo que falte: es una "
                    "regla del procedimiento, y ningún perfil podría "
                    "responderla"),
    },
}

# Objetos del catálogo que son REGLAS del pliego, no preguntas sobre la
# empresa. No son hueco nuestro —no hay campo que construir— ni tarea del
# cliente —no hay nada que confirmar—, y hoy contaminan las dos listas.
#
# Medido sobre Paicol y Ternera: de los 9 requisitos que la heurística del
# formulario no pudo tipificar, **5 son reglas**:
#
#   «Subsanabilidad de experiencia insuficiente»          (Paicol 3.5.8)
#   «Cumplimiento de todos los requisitos habilitantes»   (Ternera 3.1)
#   «Máximo de actividades exigidas»                      (Paicol 3.5.1)
#       — este último es un límite a la ENTIDAD: ni siquiera es un requisito
#         del oferente
#   «Requisitos habilitantes en proponentes plurales»     (Ternera 3.1)
#   «Condiciones técnicas no inferiores al Anexo»         (Ternera 1.15)
#       — texto de una causal de rechazo
#
# `UNSPSC` **NO entra**, aunque en la primera lectura lo pusimos aquí:
# `PerfilExperiencia.codigos_unspsc` existe y «los contratos deben estar
# clasificados en alguno de estos códigos» se responde comparando conjuntos.
# No es una regla: es un requisito que necesita un criterio de comparación
# que todavía no está escrito. Pertenece a [D27], no a esta categoría.
#
# COBERTURA HONESTA: sólo dos de las cinco tienen un objeto de catálogo
# fiable con el que reconocerlas. De las otras tres, dos vienen de objetos
# MAL asignados [D29] y una no tiene objeto. Reconocerlas todas exige que el
# extractor las marque en origen —un campo `es_regla_del_pliego`—, que es un
# cambio de prompt y se aplica en la próxima re-extracción junto a [D20] y
# [D25]. Hasta entonces esta categoría reconoce lo que puede y **no adivina
# el resto**: lo que no reconoce se queda en `no_preguntado`, que pide
# confirmar un documento de más y no afirma nada falso.
OBJETOS_REGLA: frozenset[str] = frozenset({
    "SUBSANABILIDAD",
    "CRITERIOS_DESEMPATE",
    "FORMA_OFERTA",
    "VERACIDAD_INFORMACION",
    "PRESENTACION_MULTIPLE",
    "IDIOMA_DOCUMENTOS",
    "CONVERSION_MONEDA",
    "CONVERSION_SMMLV",
})

# Lo que ve el cliente es lo mismo en los tres casos en que no hay veredicto:
# no afirmamos que lo tenga ni que le falte, y le damos una tarea, no una
# disculpa. La palabra «formulario» no aparece: el cliente no sabe que existe
# y no es su problema.
FRASE_CLIENTE = "Debe confirmar que cuenta con estos documentos"


def origen_dato_faltante(req: Any, perfil: Any) -> str:
    """
    Separa las dos razones por las que un requisito llega a `dato_faltante`.

    - `no_se_responde_con_un_campo` — es una REGLA del pliego. Ni hueco
                         nuestro ni tarea del cliente: ningún perfil podría
                         responderla.
    - `no_preguntado`  — el perfil no tiene ningún campo para este concepto.
                         Hueco NUESTRO.
    - `campo_sin_respuesta` — el campo existe y está vacío. Hueco del perfil.

    `le_falta` NO se devuelve aquí: cuando el perfil responde que no lo tiene,
    el evaluador produce `no_cumple`, no `dato_faltante`. Está en `ORIGENES`
    porque el informe cuenta los tres juntos en la sección de trazabilidad.
    """
    try:
        from .catalogo import objeto_para_evaluar
        if objeto_para_evaluar(req) in OBJETOS_REGLA:
            return "no_se_responde_con_un_campo"
    except Exception:
        pass
    from .evaluator import campo_del_perfil
    return "campo_sin_respuesta" if campo_del_perfil(req) else "no_preguntado"


def resumen_origenes(
    filas: Iterable[dict],
    clave: str = "origen",
) -> dict[str, Any]:
    """
    Cuenta los orígenes para la sección de trazabilidad: cuántos son hallazgo
    confirmado y cuántos están pendientes de captura en el perfil.

    `hallazgos` cuenta los `le_falta` que el informe haya añadido a la lista;
    hoy son 0 por construcción y ese cero es el dato relevante, no un vacío.
    """
    cuenta = Counter(f.get(clave) for f in filas)
    total = sum(cuenta.values())
    hallazgos = cuenta.get("le_falta", 0)
    return {
        "total": total,
        "por_origen": dict(cuenta),
        "hallazgos": hallazgos,
        "pendientes_de_captura": cuenta.get("no_preguntado", 0),
        "sin_responder": cuenta.get("campo_sin_respuesta", 0),
        "reglas": cuenta.get("no_se_responde_con_un_campo", 0),
        "produce_hallazgos": hallazgos > 0,
    }


def como_json() -> dict[str, Any]:
    """La escala y los orígenes para el front, sin duplicar literales."""
    return {
        "escala": ESCALA,
        "orden_gravedad": list(ORDEN_GRAVEDAD),
        "origenes": ORIGENES,
        "frase_cliente": FRASE_CLIENTE,
        "umbral_sin_concepto": UMBRAL_SIN_CONCEPTO,
        "umbral_viable": UMBRAL_VIABLE,
    }
