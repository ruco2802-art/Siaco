# -*- coding: utf-8 -*-
"""
pipeline/importar_a_registro.py — Lleva al almacén lo que ya está en disco.

`.pipeline_cache/` y `resultados_evaluacion/` guardan trabajo pagado que
ningún registro conoce. Este importador los incorpora sin borrar nada:
copia, no mueve, para que el caché siga funcionando como caché.

Los resultados de extracción SIN `pliego_sha256` quedan fuera a propósito.
Emparejarlos por nombre de archivo o por número de chunks sería una
suposición, y una suposición sobre a qué PDF corresponden 218 requisitos es
justo el error que este registro existe para impedir. Se listan como
huérfanos para tratarlos aparte, con evidencia.

Uso:
    py -m pipeline.importar_a_registro            # previsualiza
    py -m pipeline.importar_a_registro --guardar  # escribe
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pipeline.src import registro

_REPO_ROOT = Path(__file__).parent.parent
_CACHE = _REPO_ROOT / ".pipeline_cache"
_RESULTADOS = _REPO_ROOT / "resultados_evaluacion"

# Número de proceso SECOP tal como aparece en la portada del pliego.
_RE_PROCESO = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ]{2,10}[-\s]?(?:SAMC|LP|MC|CM|SA|CD)[-\s]?\d{2,4}[-\s]?\d{4})\b")
_RE_ENTIDAD = re.compile(
    r"\b(ALCALD[IÍ]A\s+MUNICIPAL\s+DE\s+[A-ZÁÉÍÓÚÑ ]{3,40}"
    r"|MUNICIPIO\s+DE\s+[A-ZÁÉÍÓÚÑ ]{3,40}"
    r"|INSTITUTO\s+COLOMBIANO\s+DE\s+BIENESTAR\s+FAMILIAR)\b")


def _sondear(markdown: str) -> tuple[str, str]:
    """(numero_proceso, entidad) leídos de la portada. Vacío si no se ven."""
    cabeza = markdown[:6000]
    proc = _RE_PROCESO.search(cabeza)
    ent = _RE_ENTIDAD.search(cabeza)
    return (proc.group(1).strip() if proc else "",
            " ".join(ent.group(1).split()).title() if ent else "")


def importar(guardar: bool = False) -> dict:
    est = registro.estado_almacen()
    print("=" * 96)
    print(f"ALMACÉN: {est['ruta']}")
    if est["aviso"]:
        print(f"  AVISO: {est['aviso']}")
    print("=" * 96)

    importados, huerfanos = [], []

    # ── 1. Parseos ────────────────────────────────────────────────────────
    print("\nPARSEOS (.pipeline_cache) — artefacto `parseo`")
    for f in sorted(_CACHE.glob("*.json")):
        sha = f.stem
        datos = json.loads(f.read_text("utf-8"))
        meta = datos.get("metadata", {})
        proceso, entidad = _sondear(datos.get("markdown", ""))
        ya = registro.tiene_artefacto(sha, "parseo")
        print(f"  {sha[:12]}  {meta.get('archivo','?')[:42]:<42} "
              f"{'ya estaba' if ya else 'importar':<10} "
              f"proceso={proceso or '—':<18} entidad={entidad or '—'}")
        if guardar and not ya:
            registro.registrar_pliego(
                sha, archivo=meta.get("archivo", ""), entidad=entidad,
                numero_proceso=proceso, estado="parseado",
                origen="importado de .pipeline_cache",
            )
            registro.guardar_artefacto(
                sha, "parseo", datos,
                chars=len(datos.get("markdown", "")),
                tipo_pdf=meta.get("tablas_reparacion", {}).get("tipo_pdf", "?"),
            )
            importados.append(sha)

    # ── 2. Extracciones ───────────────────────────────────────────────────
    print("\nEXTRACCIONES (resultados_evaluacion) — artefacto `extraccion`")
    for f in sorted(_RESULTADOS.glob("*.json")):
        try:
            d = json.loads(f.read_text("utf-8"))
        except Exception:
            continue
        reqs = d.get("requisitos") or []
        if not reqs:
            continue
        mc = d.get("metadatos_corrida", {})
        sha = mc.get("pliego_sha256")
        if not sha:
            huerfanos.append((f.name, len(reqs), mc.get("costo_usd", 0.0),
                              mc.get("timestamp_utc", "")[:10]))
            continue
        ya = registro.tiene_artefacto(sha, "extraccion")
        print(f"  {sha[:12]}  {f.name[:42]:<42} reqs={len(reqs):<5} "
              f"{'ya estaba' if ya else 'importar'}")
        if guardar and not ya:
            registro.guardar_artefacto(
                sha, "extraccion", d,
                costo_usd=mc.get("costo_usd", 0.0), requisitos=len(reqs),
            )
            registro.registrar_pliego(sha, estado="extraido")
            importados.append(sha)

    # ── 3. Huérfanos ──────────────────────────────────────────────────────
    print(f"\nHUÉRFANOS — extracción pagada que NO se puede atribuir: {len(huerfanos)}")
    for nombre, n, costo, fecha in huerfanos:
        print(f"  {nombre[:52]:<52} reqs={n:<5} ${costo or 0:.2f}  {fecha}")
    if huerfanos:
        print("  → sin `pliego_sha256` no hay prueba de a qué PDF pertenecen.")
        print("    Emparejarlos exige evidencia (verificación de citas), no el nombre.")

    print()
    print(registro.resumen())
    if not guardar:
        print("\n(previsualización — nada escrito; usar --guardar)")
    return {"importados": importados, "huerfanos": huerfanos}


if __name__ == "__main__":
    importar("--guardar" in sys.argv)
