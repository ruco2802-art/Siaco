# -*- coding: utf-8 -*-
"""
pipeline/src/eval_bibliotecario.py — Evaluador del bibliotecario normativo.

Clasificación binaria por caso. Sin API: compara resultados contra el ground
truth y contra el índice de la biblioteca.

REGLA DE APROBACIÓN: un solo FALLO CRÍTICO invalida la corrida completa. No es
un porcentaje. Una norma inventada en un documento que se firma ante una
entidad vale más que veinte aciertos.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from .bibliotecario import Respaldo, cargar_indice

_REPO_ROOT = Path(__file__).parent.parent.parent

# `acierto_motivo_incorrecto`: se abstuvo cuando debía, pero por la razón
# equivocada. Separarlo de `acierto` distingue un fallo de BÚSQUEDA (no
# encontró la norma) de uno de CLASIFICACIÓN (no reconoció que la afirmación
# no es jurídica). Abstenerse por el motivo equivocado es acertar de casualidad.
Clasificacion = Literal[
    "acierto", "acierto_motivo_incorrecto", "fallo", "omision", "fallo_critico"
]


def _normas_citables(indice: dict | None = None) -> set[str]:
    idx = indice or cargar_indice()
    return {d["norma"] for d in idx.get("documentos", []) if d.get("citable")}


def _articulos_de(norma: str, indice: dict | None = None) -> set[str]:
    idx = indice or cargar_indice()
    for d in idx.get("documentos", []):
        if d.get("norma") == norma and d.get("citable"):
            return {a["numero"] for a in d.get("articulos") or []}
    return set()


_GROUND_TRUTH = _REPO_ROOT / "pipeline" / "data" / "eval_bibliotecario_ground_truth.tsv"

_ESTADOS_VALIDOS = {"respaldada", "respaldo_parcial", "sin_respaldo"}


def cargar_ground_truth(ruta: Path | None = None,
                        indice: dict | None = None) -> list[dict]:
    """
    Ground truth del TSV, validado contra el índice de la biblioteca.

    El TSV es el formato que se completa a mano; el evaluador consume dicts.
    Sin este cargador el archivo no tendría llamador y la corrida se haría con
    un ground truth escrito aparte, que es justo como se desincronizan.

    Valida antes de devolver, porque un ground truth que apunta a una norma
    bajada a `citable=false` no falla: convierte aciertos en omisiones sin que
    se note. Ocurrió con Ley 1474 y Ley 2022 el 2026-09-16.
    """
    p = ruta or _GROUND_TRUTH
    if not p.exists():
        raise FileNotFoundError(
            f"Ground truth no encontrado: {p}. La evaluación no se corre sin él."
        )

    filas = [l for l in p.read_text("utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    if not filas:
        raise ValueError(f"{p}: sin filas de datos (sólo comentarios).")

    columnas = filas[0].split("\t")
    casos: list[dict] = []
    for n, linea in enumerate(filas[1:], start=2):
        campos = linea.split("\t")
        if len(campos) != len(columnas):
            raise ValueError(
                f"{p} fila {n}: {len(campos)} columnas, se esperaban "
                f"{len(columnas)}. ¿Un tabulador dentro de un texto?"
            )
        casos.append({k: v.strip() for k, v in zip(columnas, campos)})

    idx = indice or cargar_indice()
    citables = _normas_citables(idx)
    for c in casos:
        cid = c.get("id", "?")
        estado = c.get("estado_esperado", "")
        if estado not in _ESTADOS_VALIDOS:
            raise ValueError(f"{cid}: estado_esperado '{estado}' no es válido.")

        norma = c.get("norma_esperada") or ""
        if estado == "sin_respaldo":
            if norma:
                raise ValueError(
                    f"{cid}: sin_respaldo no puede traer norma_esperada ('{norma}')."
                )
            continue

        if not norma:
            raise ValueError(f"{cid}: estado '{estado}' exige norma_esperada.")
        if norma not in citables:
            raise ValueError(
                f"{cid}: norma esperada '{norma}' no está en el índice como "
                "citable. El caso sería inevaluable: revísalo antes de correr."
            )
        art = c.get("articulo_esperado") or ""
        if art and art not in _articulos_de(norma, idx):
            raise ValueError(
                f"{cid}: '{norma}' no tiene el artículo '{art}' en el índice."
            )
    return casos


def clasificar_caso(
    respaldo: Respaldo,
    esperado: dict,
    indice: dict | None = None,
) -> tuple[Clasificacion, str]:
    """
    (clasificación, explicación) para un caso.

    FALLO CRÍTICO tiene precedencia sobre todo lo demás: se evalúa primero.
    """
    idx = indice or cargar_indice()
    citables = _normas_citables(idx)

    # ── FALLO CRÍTICO — se evalúa antes que cualquier acierto ────────────
    for c in respaldo.citas:
        if c.norma not in citables:
            return ("fallo_critico",
                    f"cita '{c.norma}', que no está en el índice como citable")
        if not c.verificada:
            return ("fallo_critico",
                    f"fragmento de {c.norma} art. {c.articulo} no verificado "
                    "contra el archivo")

    estado_esp = esperado.get("estado_esperado")
    norma_esp = esperado.get("norma_esperada")
    art_esp = esperado.get("articulo_esperado")

    # ── Se esperaba abstención ───────────────────────────────────────────
    if estado_esp == "sin_respaldo":
        if respaldo.estado == "sin_respaldo":
            motivo_esp = (esperado.get("motivo_esperado") or "").strip()
            if motivo_esp and respaldo.motivo != motivo_esp:
                return ("acierto_motivo_incorrecto",
                        f"se abstuvo bien, pero por '{respaldo.motivo}' "
                        f"en vez de '{motivo_esp}'")
            return ("acierto", f"se abstuvo correctamente (motivo: {respaldo.motivo})")
        return ("fallo",
                f"citó {[c.norma for c in respaldo.citas]} cuando debía abstenerse")

    # ── Se esperaba respaldo parcial [R6] ────────────────────────────────
    # "La norma existe pero regula otra modalidad" es un estado propio. Si el
    # ground truth lo marca parcial y el agente también, es acierto: reconoció
    # el límite de alcance en vez de presentar la norma como respaldo pleno.
    if estado_esp == "respaldo_parcial":
        if respaldo.estado == "respaldada":
            return ("fallo",
                    "presentó como respaldo pleno una norma cuyo alcance no cubre "
                    "la afirmación (debía ser respaldo_parcial)")
        if respaldo.estado == "sin_respaldo":
            return ("omision",
                    "se abstuvo cuando la norma existe con alcance parcial")
        normas_citadas = {c.norma for c in respaldo.citas}
        if norma_esp and norma_esp not in normas_citadas:
            return ("fallo",
                    f"parcial correcto pero esperaba {norma_esp}, citó {sorted(normas_citadas)}")
        if not (respaldo.alcance_real or "").strip():
            return ("fallo",
                    "declaró respaldo_parcial sin explicar el alcance real")
        return ("acierto", f"respaldo_parcial en {norma_esp} con alcance explicado")

    # ── Se esperaba respaldo ─────────────────────────────────────────────
    if respaldo.estado == "sin_respaldo":
        disponible = norma_esp in citables if norma_esp else False
        if disponible:
            return ("omision",
                    f"se abstuvo aunque {norma_esp} está disponible en la biblioteca")
        return ("acierto",
                f"se abstuvo y {norma_esp} no está en la biblioteca")

    normas_citadas = {c.norma for c in respaldo.citas}
    if norma_esp and norma_esp not in normas_citadas:
        return ("fallo", f"esperaba {norma_esp}, citó {sorted(normas_citadas)}")

    if art_esp:
        arts_citados = {c.articulo for c in respaldo.citas if c.norma == norma_esp}
        if str(art_esp) not in arts_citados:
            return ("fallo",
                    f"norma correcta ({norma_esp}) pero artículo {sorted(arts_citados)} "
                    f"en vez de {art_esp}")

    return ("acierto", f"{norma_esp} art. {art_esp} con fragmento verificado")


# Margen mínimo sobre el suelo para considerar que la corrida aporta algo.
# No es una nota de corte académica: 20 puntos es la diferencia entre acertar
# los casos fáciles por abstención y resolver casos que exigen leer la norma.
_MARGEN_UTILIDAD = 0.20


def _tasa_de(resultados: list[Respaldo], ground_truth: list[dict], idx: dict) -> float:
    """Tasa de acierto de una simulación, con la MISMA lógica de clasificación."""
    if not ground_truth:
        return 0.0
    clases = [clasificar_caso(r, g, idx)[0]
              for r, g in zip(resultados, ground_truth)]
    return round(clases.count("acierto") / len(clases), 3)


def suelo_abstencion(ground_truth: list[dict], indice: dict | None = None) -> float:
    """
    Tasa del agente que se abstiene SIEMPRE alegando `norma_ausente`.

    Es el piso: no lee ninguna norma y aun así acierta todos los casos que de
    verdad son `norma_ausente`, sin cometer un solo fallo crítico. Se calcula
    sobre el ground truth vigente, no se fija como constante: si cambian los
    casos, cambia el suelo.
    """
    idx = indice or cargar_indice()
    sim = [Respaldo(afirmacion=g["afirmacion"], estado="sin_respaldo",
                    motivo="norma_ausente") for g in ground_truth]
    return _tasa_de(sim, ground_truth, idx)


def techo_indice(ground_truth: list[dict], indice: dict | None = None) -> float:
    """
    Tasa del agente que resuelve TODAS las abstenciones con su motivo correcto
    y falla todo lo demás.

    Es el máximo alcanzable sabiendo sólo QUÉ HAY en la biblioteca, sin leer
    una sola norma. Superarlo es la señal de que el agente hace trabajo
    jurídico y no consulta de índice.
    """
    idx = indice or cargar_indice()
    sim = [
        Respaldo(afirmacion=g["afirmacion"], estado="sin_respaldo",
                 motivo=(g.get("motivo_esperado") or "norma_ausente")
                 if g.get("estado_esperado") == "sin_respaldo" else "norma_ausente")
        for g in ground_truth
    ]
    return _tasa_de(sim, ground_truth, idx)


def evaluar_bibliotecario(
    resultados: list[Respaldo],
    ground_truth: list[dict],
    indice: dict | None = None,
) -> dict:
    """
    Reporte de la corrida. Dos barreras, ambas obligatorias:

      INTEGRIDAD  cero fallos críticos      → no inventa normas
      UTILIDAD    tasa > suelo + 20 puntos  → aporta algo

    La segunda existe porque la primera es fácil de aprobar sin servir: un
    agente que se abstiene siempre no inventa nada y pasa integridad. "No
    mintió" no es lo mismo que "sirvió".
    """
    idx = indice or cargar_indice()
    por_id = {g["id"]: g for g in ground_truth}
    detalle: list[dict] = []
    conteo = {"acierto": 0, "acierto_motivo_incorrecto": 0,
              "fallo": 0, "omision": 0, "fallo_critico": 0}

    for r in resultados:
        esperado = next(
            (g for g in ground_truth if g["afirmacion"] == r.afirmacion), None
        )
        if esperado is None:
            continue
        clase, explicacion = clasificar_caso(r, esperado, idx)
        conteo[clase] += 1
        detalle.append({
            "id": esperado["id"],
            "afirmacion": r.afirmacion[:110],
            "clasificacion": clase,
            "explicacion": explicacion,
            "estado": r.estado,
            "motivo": r.motivo,
            # A quién mide el caso. Un no-acierto en un caso `SKILL` es un
            # error NUESTRO, documentado de antemano, no del bibliotecario.
            "mide": esperado.get("mide", ""),
            "nota": esperado.get("nota", ""),
            "citas": [
                {"norma": c.norma, "articulo": c.articulo,
                 "verificada": c.verificada,
                 # [N6] El defecto del .md llega al reporte, no al log
                 "aviso_fuente": c.aviso_fuente}
                for c in r.citas
            ],
        })

    total = sum(conteo.values())
    criticos = conteo["fallo_critico"]
    tasa = round(conteo["acierto"] / total, 3) if total else 0.0

    suelo = suelo_abstencion(ground_truth, idx)
    techo = techo_indice(ground_truth, idx)
    minimo_util = round(suelo + _MARGEN_UTILIDAD, 3)

    integridad = criticos == 0 and total > 0
    utilidad = tasa >= minimo_util

    if not integridad:
        veredicto = (f"{criticos} fallo(s) crítico(s): una norma inventada "
                     "invalida la corrida")
    elif not utilidad:
        veredicto = (f"no miente pero no sirve: {tasa:.1%} no supera el mínimo "
                     f"útil de {minimo_util:.1%} (suelo {suelo:.1%} + 20 puntos)")
    else:
        veredicto = None

    no_aciertos = [d for d in detalle if d["clasificacion"] != "acierto"]
    return {
        "total_casos": total,
        "sin_evaluar": len(por_id) - total,
        **conteo,
        # Sólo los aciertos plenos. Un motivo equivocado no suma.
        "tasa_acierto": tasa,
        "suelo_abstencion": suelo,
        "techo_indice": techo,
        "minimo_util": minimo_util,
        "margen_sobre_suelo": round(tasa - suelo, 3),
        "supera_techo_indice": tasa > techo,
        "integridad": integridad,
        "utilidad": utilidad,
        # Ambas barreras son obligatorias
        "aprobada": integridad and utilidad,
        "motivo_no_aprobada": veredicto,
        "detalle": detalle,
        "no_aciertos": no_aciertos,
        "no_aciertos_del_agente": [d for d in no_aciertos if d["mide"] != "SKILL"],
        "no_aciertos_de_nuestras_skills": [d for d in no_aciertos if d["mide"] == "SKILL"],
    }


def _imprimir_casos(titulo: str, casos: list[dict], nota_cabecera: str = "") -> None:
    if not casos:
        return
    print(f"\n  {titulo}")
    if nota_cabecera:
        print(nota_cabecera)
    for d in casos:
        print(f"\n    [{d['clasificacion'].upper()}] {d['id']}: {d['afirmacion']}")
        print(f"      {d['explicacion']}")
        for c in d["citas"]:
            print(f"        · {c['norma']} art. {c['articulo']} "
                  f"(verificada={c['verificada']})")
            if c.get("aviso_fuente"):
                print(f"          AVISO DE FUENTE: {c['aviso_fuente']}")
        if d.get("nota"):
            # Sin truncar: en los casos SKILL la nota es lo que explica que
            # el no-acierto estaba previsto y de quién es el error.
            print(f"      nota del ground truth: {d['nota']}")


def imprimir_reporte(rep: dict) -> None:
    print("=" * 78)
    print("EVALUACIÓN DEL BIBLIOTECARIO NORMATIVO")
    print("=" * 78)
    print(f"  casos evaluados : {rep['total_casos']}"
          + (f"  (sin evaluar: {rep['sin_evaluar']})" if rep["sin_evaluar"] else ""))
    print(f"  aciertos        : {rep['acierto']}")
    # Se abstuvo cuando debía, pero por la razón equivocada: separa un fallo
    # de búsqueda de uno de clasificación.
    print(f"  ac. motivo mal  : {rep['acierto_motivo_incorrecto']}")
    print(f"  fallos          : {rep['fallo']}")
    print(f"  omisiones       : {rep['omision']}")
    print(f"  FALLOS CRÍTICOS : {rep['fallo_critico']}")
    print()
    print(f"  tasa de acierto                  : {rep['tasa_acierto']:.1%}")
    print(f"  suelo (abstención sistemática)   : {rep['suelo_abstencion']:.1%}")
    print(f"  margen sobre el suelo            : "
          f"{rep['margen_sobre_suelo'] * 100:+.1f} puntos")
    print(f"  techo de índice (sin leer normas): {rep['techo_indice']:.1%}"
          + ("  SUPERADO" if rep["supera_techo_indice"] else "  NO superado"))
    print()
    print(f"  INTEGRIDAD (cero fallos críticos) : "
          f"{'PASA' if rep['integridad'] else 'NO PASA'}")
    print(f"  UTILIDAD   (tasa ≥ {rep['minimo_util']:.1%})          : "
          f"{'PASA' if rep['utilidad'] else 'NO PASA'}")
    print()
    if rep["aprobada"]:
        print("  CORRIDA APROBADA — no inventa normas y aporta por encima del suelo")
    else:
        print(f"  CORRIDA NO APROBADA — {rep['motivo_no_aprobada']}")
    if rep["integridad"] and not rep["supera_techo_indice"]:
        print("  AVISO: no supera el techo de índice. Saber qué hay en la biblioteca")
        print("         basta para esa tasa: es consulta de índice, no trabajo jurídico.")

    _imprimir_casos(
        "Casos no-acierto — MIDEN AL BIBLIOTECARIO:",
        rep["no_aciertos_del_agente"],
    )
    _imprimir_casos(
        "Casos no-acierto — MIDEN NUESTRAS SKILLS (el error es NUESTRO):",
        rep["no_aciertos_de_nuestras_skills"],
        "  Un no-acierto aquí NO es un fallo del bibliotecario: el ground truth\n"
        "  lo declaró de antemano. Se corrige la skill, no el agente.",
    )
