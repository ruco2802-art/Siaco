# -*- coding: utf-8 -*-
"""
pipeline/src/auditor_citas.py — Audita las citas normativas de los prompts.

El conocimiento normativo del sistema vive en DOS sitios: los `.md` de
`.claude/skills/` y los fallbacks embebidos de `prompts.py`. Sólo se revisaba
el primero, y los cuatro artículos inventados que alimentaban al agente
financiero estaban en el segundo.

Lo que esto SÍ comprueba:
  · la norma citada está en el índice con `citable=true`
  · el artículo citado existe en esa norma

Lo que NO puede comprobar: que el artículo DIGA lo que el prompt afirma. Eso
exige leerlo. `Decreto 1082 art. 2.2.1.2.1.2.5` existe y regula la subasta
inversa, y se citó durante meses como base del plazo de observaciones.

Por eso una línea puede declararse exenta con `[no-citable]`, `[norma no
disponible en la biblioteca: ...]` o `[cita pendiente de verificar]`. Esas
marcas cubren dos casos legítimos: el registro de qué falta descargar, y las
ADVERTENCIAS —"no cites el art. 22, está derogado"— que nombran una norma
justamente para prohibirla. Sin la marca, el auditor no puede distinguir una
advertencia de una cita, y obligaría a borrar el aviso.
"""
from __future__ import annotations

import re
from pathlib import Path

from .bibliotecario import cargar_indice

_REPO_ROOT = Path(__file__).parent.parent.parent

# Fuentes de conocimiento normativo. TODAS, no las que uno recuerda.
#
# `routers/` entró después de encontrar que auditoria.py rellenaba la columna
# "Norma" de cada fila financiera con "Decreto 1082/2015 art. 2.2.1.2.1.5.8",
# un artículo inexistente, y salía así en pantalla y en el PDF. El auditor no
# lo veía porque nadie había puesto los routers en esta lista.
FUENTES: tuple[str, ...] = (
    "prompts.py",
    "analizador.py",
    "routers/auditoria.py",
    "routers/reportes.py",
    "routers/observaciones.py",
    "routers/generador_oferta.py",
    "routers/chat.py",
    ".claude/skills/skill_financiera_SAFE_L.md",
    ".claude/skills/skill_juridica_licitaciones.md",
    ".claude/skills/skill_licitaciones_estrategia.md",
    ".claude/skills/skill_anti_rechazo.md",
    ".claude/skills/skill_bibliotecario_normativo.md",
)

# Cómo escriben las normas los prompts: "Ley 1150/2007", "Decreto 1082 de 2015"
_RE_NORMA = re.compile(
    r"(?:Ley|Decreto|Resoluci[oó]n)\s+[\d\.]+\s*(?:/|\s+de\s+)\s*\d{4}", re.I)
_RE_ART = re.compile(r"art(?:[íi]culo)?s?\.?\s*(\d+(?:\.\d+)*[A-Z]?)", re.I)

# Una línea marcada así declara que la referencia no es citable: es un
# registro de lo que falta, no una cita.
_MARCAS_EXENTAS = ("[no-citable]",
                   "[norma no disponible en la biblioteca",
                   "[cita pendiente de verificar]")

_ALIAS = {
    "ley 80 1993": "Ley 80 de 1993",
    "ley 1150 2007": "Ley 1150 de 2007",
    "ley 1474 2011": "Ley 1474 de 2011",
    "ley 1882 2018": "Ley 1882 de 2018",
    "ley 2022 2020": "Ley 2022 de 2020",
    "decreto 1082 2015": "Decreto 1082 de 2015",
}


def _canonizar(bruto: str) -> str | None:
    s = re.sub(r"[/,]", " ", bruto.lower())
    s = re.sub(r"\bde\b", " ", s)
    return _ALIAS.get(re.sub(r"\s+", " ", s).strip())


def auditar_citas(indice: dict | None = None,
                  raiz: Path | None = None) -> list[dict]:
    """
    Citas que no resisten el índice. Lista vacía = todas verifican.

    Cada hallazgo: {archivo, linea, cita, problema, texto}.
    """
    idx = indice or cargar_indice()
    base = raiz or _REPO_ROOT
    citables = {d["norma"]: d for d in idx["documentos"] if d.get("citable")}
    no_citables = {d["norma"] for d in idx["documentos"] if not d.get("citable")}

    hallazgos: list[dict] = []
    for rel in FUENTES:
        ruta = base / rel
        if not ruta.exists():
            hallazgos.append({"archivo": rel, "linea": 0, "cita": rel,
                              "problema": "fuente_inexistente", "texto": ""})
            continue

        for n, linea in enumerate(ruta.read_text("utf-8").splitlines(), 1):
            if any(m in linea for m in _MARCAS_EXENTAS):
                continue
            normas = list(_RE_NORMA.finditer(linea))
            for i, mn in enumerate(normas):
                # Los artículos que siguen a esta norma, hasta la siguiente
                fin = normas[i + 1].start() if i + 1 < len(normas) else len(linea)
                arts = _RE_ART.findall(linea[mn.end():fin])
                canon = _canonizar(mn.group(0))

                def anotar(problema: str, art: str | None = None) -> None:
                    hallazgos.append({
                        "archivo": rel, "linea": n,
                        "cita": mn.group(0) + (f" art. {art}" if art else ""),
                        "problema": problema, "texto": linea.strip()[:120],
                    })

                if canon is None:
                    anotar("norma_fuera_del_indice")
                    continue
                if canon in no_citables:
                    anotar("norma_no_citable")
                    continue
                numeros = {a["numero"] for a in citables[canon].get("articulos") or []}
                for art in arts:
                    if art not in numeros:
                        anotar("articulo_inexistente", art)
    return hallazgos


def formatear(hallazgos: list[dict]) -> str:
    if not hallazgos:
        return "Todas las citas normativas verifican contra el índice."
    filas = [f"{len(hallazgos)} cita(s) que no resisten el índice:"]
    for h in hallazgos:
        filas.append(f"  {h['archivo']}:{h['linea']}  {h['cita']}  "
                     f"[{h['problema']}]\n      {h['texto']}")
    return "\n".join(filas)


if __name__ == "__main__":
    print(formatear(auditar_citas()))
