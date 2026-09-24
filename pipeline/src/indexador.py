# -*- coding: utf-8 -*-
"""
pipeline/src/indexador.py — Construcción del índice de artículos.

Determina el rango [inicio, fin) de cada artículo dentro de un `.md`. Todo en
código: el modelo no decide qué ocurrencia de un número es la buena.

REGLAS DE DESAMBIGUACIÓN, en orden
==================================

**1. Transcripción de otra norma [X1].** Un encabezado precedido de
"…quedará así:" no es un artículo de este documento: es el articulado de OTRA
norma, reproducido dentro de un artículo modificatorio.

    ## ARTÍCULO 17. Modifíquese el artículo 4° de la Ley 1228 de 2008,
       el cual quedará así:
    ## ARTÍCULO 4°. No procederá indemnización...     <- Ley 1228, no Ley 1882

La Ley 1882 de 2018 tiene 8 de estas. Tres chocaban con artículos reales
(4, 5 y 10) y las otras cinco hacían creer que la ley tiene artículos 25, 27,
32 y 33, que pertenecen a las leyes 1508 y 1682.

**2. Posición, no longitud [X2].** Si tras excluir transcripciones un número
sigue repetido, gana la ocurrencia MÁS TARDÍA: los índices y tablas de
contenido van al principio, el articulado después.

    La regla anterior —conservar la ocurrencia con MÁS TEXTO— se escribió
    para el índice duplicado de la Ley 80, donde el índice es corto y el
    cuerpo largo. No generaliza: cuando son dos artículos distintos, la
    longitud no dice nada sobre cuál es el bueno. En la Ley 1882 elegía el
    equivocado, y el art. 4 del índice devolvía un texto sobre fajas viales
    en vez de la obligatoriedad de los documentos tipo.

**3. Divergencia alta [X3].** Si dos ocurrencias que sobreviven comparten
menos del 50% de su contenido, no son un índice y su cuerpo: son artículos
distintos con el mismo número, y el `.md` tiene un defecto de origen. Se
registra `divergencia_alta` para que se vea, en vez de elegir en silencio.

Cada artículo conserva `ocurrencias_descartadas` con la posición y los
primeros 100 caracteres de cada alternativa, para poder auditar la decisión
sin volver a abrir el PDF.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from pathlib import Path

# Encabezado de artículo. Sólo MAYÚSCULA o Capitalizado: la minúscula
# ("del artículo 5 de la Ley 1150") es una referencia cruzada, no un
# encabezado. Numeración compuesta (2.2.1.5.6) y sufijos (9A, 17B) se
# preservan: cortar en el primer punto colapsaba artículos distintos.
_RE_ENCABEZADO = re.compile(
    r"^##\s+(?:ART[IÍ]CULO|Art[ií]culo)\s+"
    r"(\d+(?:\.\d+)+|\d+\s*[oº°]?(?:\s*\.\s*[A-Z]\b)?|[A-ZÁÉÍÓÚ]+)",
    re.M,
)

# [X1] Lo que ANTECEDE al encabezado anuncia la transcripción de otra norma.
# Se mira el texto previo, nunca el encabezado mismo: un artículo puede decir
# "Modificado por el Decreto 19 de 2012" en su propia cabecera y seguir
# siendo un artículo de esta norma (Ley 1150 art. 6).
_RE_TRANSCRIPCION = re.compile(
    r"(?:qued(?:ar[áa]n?|en?)\s+as[íi]|as[íi])\s*:\s*$", re.I | re.M)

_MIN_SIMILITUD = 0.50


def _normalizar_numero(bruto: str) -> str:
    """'9 . A' -> '9A' · '1o' -> '1' · '2.2.1.5' se conserva."""
    s = re.sub(r"\s+", "", bruto)
    s = re.sub(r"[oº°]$", "", s)
    return s.replace(".", "") if re.fullmatch(r"\d+\.[A-Z]", s) else s


def es_transcripcion(texto: str, inicio: int) -> bool:
    """
    [X1] ¿El encabezado en `inicio` reproduce el articulado de otra norma?

    Se mira SÓLO la última línea no vacía anterior, no una ventana de
    caracteres: con una ventana de 260 el art. 7 de la Ley 1882 quedaba
    excluido porque alcanzaba el "quedará así:" del art. 6, que está tres
    párrafos más arriba. La transcripción sigue INMEDIATAMENTE al anuncio.
    """
    lineas = texto[:inicio].splitlines()
    for linea in reversed(lineas):
        if linea.strip():
            return bool(_RE_TRANSCRIPCION.search(linea.rstrip()))
    return False


def _similitud(a: str, b: str) -> float:
    na = re.sub(r"\s+", " ", a).strip().lower()[:3000]
    nb = re.sub(r"\s+", " ", b).strip().lower()[:3000]
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _resumen(texto: str, o: dict) -> dict:
    return {
        "inicio": o["inicio"],
        "chars": o["chars"],
        "extracto": " ".join(texto[o["inicio"]:o["inicio"] + 100].split()),
    }


def indexar_articulos(md: str | Path) -> tuple[list[dict], list[dict]]:
    """
    (artículos, avisos) para un markdown.

    Cada artículo: {numero, inicio, fin, chars, titulo, ocurrencias_descartadas}
    Cada aviso:    {numero, tipo, similitud, ocurrencias}
    """
    texto = md.read_text("utf-8") if isinstance(md, Path) else md

    marcas = list(_RE_ENCABEZADO.finditer(texto))
    crudos: list[dict] = []
    for i, m in enumerate(marcas):
        ini = m.start()
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        salto = texto.find("\n", ini)
        linea = texto[ini: salto if salto > 0 else fin]
        titulo = re.sub(
            r"^##\s+(?:ART[IÍ]CULO|Art[ií]culo)\s+\S+\s*[\.\-–—:]*\s*", "", linea)
        crudos.append({
            "numero": _normalizar_numero(m.group(1)),
            "inicio": ini, "fin": fin, "chars": fin - ini,
            "titulo": titulo.strip()[:120],
            "transcripcion": es_transcripcion(texto, ini),
        })

    por_numero: dict[str, list[dict]] = defaultdict(list)
    for a in crudos:
        por_numero[a["numero"]].append(a)

    elegidos: list[dict] = []
    avisos: list[dict] = []
    for numero, todas in por_numero.items():
        # [X1] Las transcripciones no son artículos de este documento.
        propias = [a for a in todas if not a["transcripcion"]]
        transcritas = [a for a in todas if a["transcripcion"]]
        if not propias:
            # Todas eran transcripciones: el número no existe en esta norma.
            avisos.append({
                "numero": numero, "tipo": "solo_transcripciones",
                "similitud": None,
                "ocurrencias": [_resumen(texto, a) for a in todas],
            })
            continue

        # [X2] Entre las propias, gana la más tardía.
        ganadora = max(propias, key=lambda a: a["inicio"])
        descartadas = [a for a in todas if a["inicio"] != ganadora["inicio"]]

        if len(propias) > 1:
            # [X3] ¿Son el mismo artículo o dos distintos?
            sim = min(
                _similitud(texto[a["inicio"]:a["fin"]], texto[b["inicio"]:b["fin"]])
                for i, a in enumerate(propias) for b in propias[i + 1:]
            )
            if sim < _MIN_SIMILITUD:
                avisos.append({
                    "numero": numero, "tipo": "divergencia_alta",
                    "similitud": round(sim, 3),
                    "ocurrencias": [_resumen(texto, a) for a in propias],
                })

        ganadora = dict(ganadora)
        ganadora.pop("transcripcion", None)
        ganadora["ocurrencias_descartadas"] = [
            {**_resumen(texto, a),
             "motivo": "transcripcion" if a["transcripcion"] else "ocurrencia_previa"}
            for a in descartadas
        ]
        elegidos.append(ganadora)

    elegidos.sort(key=lambda a: a["inicio"])
    return elegidos, avisos


def formatear_avisos(norma: str, avisos: list[dict]) -> str:
    """[X3] Texto legible para el reporte de construcción del índice."""
    if not avisos:
        return ""
    filas = [f"  {norma}: {len(avisos)} aviso(s)"]
    for a in avisos:
        sim = f"similitud={a['similitud']}" if a["similitud"] is not None else ""
        filas.append(f"    art. {a['numero']} — {a['tipo']} {sim}")
        for o in a["ocurrencias"]:
            filas.append(f"       off {o['inicio']:>8} {o['chars']:>6} ch  "
                         f"{o['extracto'][:74]}")
    return "\n".join(filas)
