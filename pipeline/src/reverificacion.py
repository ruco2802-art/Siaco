# -*- coding: utf-8 -*-
"""
pipeline/src/reverificacion.py — re-verifica citas de artefactos ya guardados.

POR QUÉ EXISTE. El verificador cambió [D36]: dejó de fallar por markup,
marcadores de imagen y viñetas anidadas, y pasó a tolerar un punto final
sobrante. Los artefactos guardados conservaban el `estado_verificacion`
calculado con el anterior, así que el informe —que re-verifica al generarse—
decía «0 citas con texto ausente» mientras la app seguía mostrando las viejas.

**Dos verdades sobre el mismo pliego es exactamente [G1-bis]**: lo que ya pasó
cuando el almacén decía 0 de 340 verificadas y el disco tenía 275. La lección
registrada entonces fue que el trabajo hecho y el registro tienen que contarlo
igual, y esto lo aplica.

NO CUESTA API. `verificar_citas()` es una función pura sobre texto: compara el
literal contra el markdown que ya está en `.pipeline_cache`. Re-verificar es
aritmética, no una corrida.

QUÉ GUARDA. Además de los campos de cada requisito, escribe en
`metadatos_corrida` un bloque `reverificacion` con la versión del verificador,
la fecha y el antes/después, para que **se sepa por qué cambiaron los números**
sin tener que deducirlo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import registro
from .verifier import (
    VERSION_VERIFICADOR,
    _coincide,
    _norm,
    causa_no_verificada,
    cita_elidida,
)

_CACHE = Path(__file__).resolve().parents[2] / ".pipeline_cache"


def markdown_de(sha256: str) -> str | None:
    """
    El markdown del pliego desde la caché de parseo, o None si no está.

    Se busca por el `sha256` de la metadata y no por el nombre del archivo:
    la caché los nombra por sha, pero un archivo copiado a mano podría no
    seguir esa convención y el sha es lo que identifica al pliego.
    """
    directo = _CACHE / f"{sha256}.json"
    if directo.exists():
        return json.loads(directo.read_text("utf-8")).get("markdown")
    for f in _CACHE.glob("*.json"):
        try:
            d = json.loads(f.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (d.get("metadata") or {}).get("sha256") == sha256:
            return d.get("markdown")
    return None


def reverificar(sha256: str, *, guardar: bool = True) -> dict[str, Any]:
    """
    Re-verifica las citas del artefacto de extracción de un pliego.

    Devuelve el resumen del antes/después. Con `guardar=False` no toca nada:
    sirve para medir antes de decidir.

    **No sobreescribe `degradada`**, que la asigna FASE C para tablas
    escaneadas y no depende de esta comparación.
    """
    art = registro.cargar_artefacto(sha256, "extraccion")
    if not art or not art.get("requisitos"):
        return {"sha256": sha256, "estado": "sin_extraccion"}
    md = markdown_de(sha256)
    if md is None:
        return {"sha256": sha256, "estado": "sin_markdown"}

    md_norm = _norm(md)
    reqs = art["requisitos"]
    antes = sum(1 for r in reqs if r.get("estado_verificacion") == "verificada")
    causas: dict[str, int] = {}
    elididas = 0

    for r in reqs:
        lit = r.get("exigido_literal") or ""
        if cita_elidida(lit):
            elididas += 1
        if not lit:
            r["cita_verificada"] = False
            r["cita_verificada_parcial"] = False
            if r.get("estado_verificacion") != "degradada":
                r["estado_verificacion"] = "no_verificada"
            r["causa_no_verificada"] = "texto_ausente"
            causas["texto_ausente"] = causas.get("texto_ausente", 0) + 1
            continue

        ln = _norm(lit)
        ok = _coincide(ln, md_norm)
        r["cita_verificada"] = ok
        if ok:
            r["cita_verificada_parcial"] = False
            if r.get("estado_verificacion") != "degradada":
                r["estado_verificacion"] = "verificada"
                r["motivo_degradacion"] = None
            # Una cita puede verificar Y estar elidida: el pasaje omitido no
            # impide que lo que queda sea textual. Se marca igual.
            r["causa_no_verificada"] = "cita_elidida" if cita_elidida(lit) else None
        else:
            frag = ln[:60]
            parcial = len(frag) >= 15 and frag in md_norm
            r["cita_verificada_parcial"] = parcial
            if r.get("estado_verificacion") != "degradada":
                r["estado_verificacion"] = "no_verificada"
            causa = causa_no_verificada(lit, parcial)
            r["causa_no_verificada"] = causa
            causas[causa] = causas.get(causa, 0) + 1

    despues = sum(1 for r in reqs if r.get("estado_verificacion") == "verificada")
    resumen = {
        "sha256": sha256,
        "estado": "reverificado",
        "requisitos": len(reqs),
        "verificadas_antes": antes,
        "verificadas_despues": despues,
        "recuperadas": despues - antes,
        "causas": causas,
        "citas_elididas": elididas,
        "version_verificador": VERSION_VERIFICADOR,
    }

    if guardar:
        meta = art.setdefault("metadatos_corrida", {})
        # Se ACUMULA el historial: una re-verificación que borrase la anterior
        # dejaría el mismo hueco que venimos cerrando.
        historial = meta.setdefault("reverificacion", [])
        historial.append({
            "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "version_verificador": VERSION_VERIFICADOR,
            "verificadas_antes": antes,
            "verificadas_despues": despues,
            "causas": causas,
            "citas_elididas": elididas,
        })
        registro.guardar_artefacto(sha256, "extraccion", art)
        registro.anotar(
            sha256, "reverificacion",
            f"verificador v{VERSION_VERIFICADOR}: {antes} -> {despues} citas verificadas")
    return resumen


def reverificar_todos(*, guardar: bool = True) -> list[dict[str, Any]]:
    """Todos los pliegos del registro que tengan extracción y markdown."""
    return [reverificar(sha, guardar=guardar)
            for sha in sorted(registro.cargar_registro_pliegos())]


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # El almacén vive donde diga SIACO_DATA_DIR; sin cargar el .env, el
    # registro apunta al respaldo local vacío y la migración no ve nada.
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)
    except ImportError:
        pass
    seco = "--dry-run" in sys.argv
    print(f"verificador v{VERSION_VERIFICADOR}"
          f"{'  (simulación, no guarda)' if seco else ''}\n")
    for r in reverificar_todos(guardar=not seco):
        if r["estado"] != "reverificado":
            print(f"  {r['sha256'][:12]}  {r['estado']}")
            continue
        print(f"  {r['sha256'][:12]}  {r['requisitos']:>4} requisitos  "
              f"verificadas {r['verificadas_antes']} -> {r['verificadas_despues']}  "
              f"(+{r['recuperadas']})")
        for k, v in sorted(r["causas"].items(), key=lambda kv: -kv[1]):
            print(f"                  {v:>4}  {k}")
        if r["citas_elididas"]:
            print(f"                  {r['citas_elididas']:>4}  con elisión «...»")
