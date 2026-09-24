# -*- coding: utf-8 -*-
"""
pipeline/src/registro.py — Almacén y registro de corridas.

Se perdieron dos corridas pagadas: 404 requisitos de Paicol en agosto y 363 de
Cravo Norte por $1,61. No se perdieron por un fallo, sino porque nada las
registró: el resultado quedó en `resultados_evaluacion/` con un nombre
inventado y sin el SHA256 del pliego, así que ningún proceso posterior pudo
volver a encontrarlo.

PRINCIPIO: guardar lo CARO, recalcular lo BARATO.

  CARO — cuesta API o minutos de OCR, nunca se pierde:
    · `parseo`      markdown del parser/OCR
    · `extraccion`  requisitos CRUDOS, tal como los devolvió el modelo
    · `conceptos`   conceptos de los agentes financiero y jurídico
    · `respaldos`   respuestas del bibliotecario normativo

  BARATO — se regenera sin API a partir de lo anterior:
    consolidación, clasificación, evaluación contra un perfil, PDF.

Se guardan los requisitos CRUDOS, no los consolidados: una versión nueva del
catálogo re-consolida desde ahí sin gastar un peso. Guardar el consolidado
ataría el histórico a la versión del catálogo del día en que se corrió.

PÚBLICO vs PRIVADO
==================
Los artefactos de un pliego son información pública de SECOP y se comparten
entre clientes: dos empresas que miran el mismo proceso reutilizan la misma
extracción. Las evaluaciones contra un perfil contienen datos de la empresa
—estados financieros, experiencia, RUP— y son privadas. Viven en subárboles
distintos para que la separación sea estructural y no dependa de recordarla.

Ninguno de los dos va al repositorio: el almacén vive FUERA, en
`SIACO_DATA_DIR`.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_REPO_ROOT = Path(__file__).parent.parent.parent

# Sin SIACO_DATA_DIR el almacén cae aquí, dentro del repo pero ignorado por
# git. Funciona, pero no hay respaldo: `estado_almacen()` lo avisa.
_RESPALDO_AUSENTE = _REPO_ROOT / "_datos_siaco"

Artefacto = Literal["parseo", "extraccion", "conceptos", "respaldos"]

# Qué justifica conservar cada artefacto. Lo que no está aquí se recalcula.
_ARTEFACTOS_CAROS: dict[str, str] = {
    "parseo":     "markdown del parser/OCR — minutos de cómputo o una llamada de OCR",
    "extraccion": "requisitos crudos del modelo — el gasto principal de API",
    "conceptos":  "conceptos de los agentes financiero y jurídico — API",
    "respaldos":  "respaldos del bibliotecario normativo — API",
}


# ─── Ubicación del almacén ────────────────────────────────────────────────────

def data_dir() -> Path:
    """Raíz del almacén. `SIACO_DATA_DIR` si está definida."""
    bruto = os.environ.get("SIACO_DATA_DIR", "").strip()
    return Path(bruto).expanduser() if bruto else _RESPALDO_AUSENTE


def estado_almacen() -> dict[str, Any]:
    """
    Dónde está el almacén y si hay respaldo. Lo consume el arranque.

    Sin `SIACO_DATA_DIR` el almacén queda dentro del repositorio: git lo ignora
    y ninguna copia externa lo protege. Es exactamente cómo se perdieron las
    dos corridas anteriores, así que el arranque tiene que decirlo en voz alta.
    """
    configurado = bool(os.environ.get("SIACO_DATA_DIR", "").strip())
    raiz = data_dir()
    return {
        "ruta": str(raiz),
        "configurado": configurado,
        "existe": raiz.exists(),
        "respaldado": configurado,
        "aviso": None if configurado else (
            f"SIACO_DATA_DIR no está definida: el almacén usará {raiz}, dentro "
            "del repositorio y SIN respaldo. Así se perdieron las corridas de "
            "Paicol y Cravo Norte. Apúntala a una carpeta sincronizada."
        ),
    }


def _publico() -> Path:
    return data_dir() / "publico"


def _privado() -> Path:
    return data_dir() / "privado"


def dir_pliego(sha256: str) -> Path:
    """Carpeta de artefactos de un pliego. Pública: son datos de SECOP."""
    return _publico() / "pliegos" / sha256


def dir_evaluacion(cliente_id: str, sha256: str) -> Path:
    """Carpeta de una evaluación. Privada: lleva datos de la empresa."""
    return _privado() / "evaluaciones" / cliente_id / sha256


_REGISTRO_PLIEGOS = "registro_pliegos.json"
_REGISTRO_EVALUACIONES = "registro_evaluaciones.json"


# ─── Lectura y escritura atómicas ─────────────────────────────────────────────

def _leer(ruta: Path, por_defecto: Any) -> Any:
    if not ruta.exists():
        return por_defecto
    try:
        return json.loads(ruta.read_text("utf-8"))
    except Exception as exc:
        print(f"[REGISTRO] {ruta} ilegible ({exc}); se usa el valor por defecto.")
        return por_defecto


def _escribir(ruta: Path, datos: Any) -> None:
    """
    Escritura atómica: temporal en el mismo directorio y `replace`.

    Un registro a medio escribir por un corte a mitad de `json.dump` dejaría
    ilegible el índice de todo lo pagado.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(ruta.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ruta)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Versiones vigentes, para saber qué se puede reprocesar ───────────────────

def versiones() -> dict[str, str]:
    """
    Versiones de lo que influye en el resultado.

    Sirven para responder «¿este análisis se hizo con el catálogo viejo?» sin
    volver a correrlo. El catálogo y el índice cambian el resultado aunque los
    requisitos crudos sean los mismos.
    """
    def _v(ruta: Path) -> str:
        d = _leer(ruta, {})
        return (d.get("_meta") or {}).get("version", "?")

    skills = _REPO_ROOT / ".claude" / "skills"
    return {
        "catalogo_objetos": _v(_REPO_ROOT / "pipeline" / "data" / "catalogo_objetos.json"),
        "biblioteca_normativa": _v(_REPO_ROOT / "biblioteca_normativa" / "indice.json"),
        "skills": ",".join(sorted(
            f"{p.stem}:{p.stat().st_size}" for p in skills.glob("*.md")
        )) if skills.exists() else "?",
    }


# ─── Registro de pliegos (público) ────────────────────────────────────────────

def cargar_registro_pliegos() -> dict[str, dict]:
    return _leer(_publico() / _REGISTRO_PLIEGOS, {})


def pliego_registrado(sha256: str) -> dict | None:
    return cargar_registro_pliegos().get(sha256)


def registrar_pliego(
    sha256: str,
    *,
    archivo: str = "",
    entidad: str = "",
    numero_proceso: str = "",
    modalidad: str = "",
    sector: str = "",
    costo_usd: float = 0.0,
    estado: str = "parseado",
    **extra: Any,
) -> dict:
    """
    Crea o actualiza la entrada de un pliego. El SHA256 es la identidad.

    El costo se ACUMULA: un pliego puede pagar parseo, extracción y respaldos
    en momentos distintos, y lo que interesa es el total invertido en él.
    """
    registro = cargar_registro_pliegos()
    entrada = registro.get(sha256) or {
        "sha256": sha256,
        "primera_vez": _ahora(),
        "costo_usd": 0.0,
        "artefactos": {},
        "historial": [],
    }
    entrada.update({
        k: v for k, v in {
            "archivo": archivo, "entidad": entidad,
            "numero_proceso": numero_proceso, "modalidad": modalidad,
            "sector": sector, "estado": estado,
        }.items() if v
    })
    entrada["actualizado"] = _ahora()
    entrada["costo_usd"] = round(entrada.get("costo_usd", 0.0) + (costo_usd or 0.0), 4)
    entrada["versiones"] = versiones()
    entrada.update(extra)

    registro[sha256] = entrada
    _escribir(_publico() / _REGISTRO_PLIEGOS, registro)
    return entrada


# ─── Artefactos ───────────────────────────────────────────────────────────────

def ruta_artefacto(sha256: str, nombre: Artefacto) -> Path:
    return dir_pliego(sha256) / f"{nombre}.json"


def tiene_artefacto(sha256: str, nombre: Artefacto) -> bool:
    return ruta_artefacto(sha256, nombre).exists()


def guardar_artefacto(
    sha256: str,
    nombre: Artefacto,
    datos: Any,
    *,
    costo_usd: float = 0.0,
    **meta: Any,
) -> Path:
    """Persiste un artefacto caro y lo anota en el registro."""
    if nombre not in _ARTEFACTOS_CAROS:
        raise ValueError(
            f"'{nombre}' no es un artefacto caro. Sólo se persiste "
            f"{sorted(_ARTEFACTOS_CAROS)}: lo demás se recalcula sin API."
        )
    ruta = ruta_artefacto(sha256, nombre)
    _escribir(ruta, datos)

    registro = cargar_registro_pliegos()
    entrada = registro.get(sha256) or {}
    if not entrada:
        registrar_pliego(sha256)
        registro = cargar_registro_pliegos()
        entrada = registro[sha256]
    entrada.setdefault("artefactos", {})[nombre] = {
        "ruta": str(ruta.relative_to(data_dir())),
        "guardado": _ahora(),
        "bytes": ruta.stat().st_size,
        **meta,
    }
    entrada["actualizado"] = _ahora()
    entrada["costo_usd"] = round(entrada.get("costo_usd", 0.0) + (costo_usd or 0.0), 4)
    registro[sha256] = entrada
    _escribir(_publico() / _REGISTRO_PLIEGOS, registro)
    return ruta


def cargar_artefacto(sha256: str, nombre: Artefacto) -> Any | None:
    ruta = ruta_artefacto(sha256, nombre)
    return _leer(ruta, None) if ruta.exists() else None


# ─── [G1] Guarda antes de gastar ──────────────────────────────────────────────

def puede_extraer(sha256: str, forzar: bool = False) -> tuple[bool, str]:
    """
    [G1] ¿Se puede llamar a la API para extraer este pliego?

    Devuelve (permitido, motivo). Si ya hay extracción guardada, NO se
    re-extrae: se reutiliza. Volver a pagar por lo mismo exige `forzar=True`,
    y queda anotado en el historial del pliego.
    """
    if tiene_artefacto(sha256, "extraccion"):
        if not forzar:
            entrada = pliego_registrado(sha256) or {}
            cuando = (entrada.get("artefactos", {}).get("extraccion", {})
                      .get("guardado", "?"))
            return False, (
                f"Ya existe extracción para {sha256[:12]} (guardada {cuando}). "
                "Se reutiliza. Para volver a pagarla, usa forzar=True."
            )
        anotar(sha256, "re_extraccion_forzada",
               "Se re-extrajo un pliego que ya tenía extracción guardada.")
        return True, "Re-extracción forzada, anotada en el historial."
    return True, "Sin extracción previa."


def anotar(sha256: str, evento: str, detalle: str = "") -> None:
    """Deja rastro de una decisión en el historial del pliego."""
    registro = cargar_registro_pliegos()
    entrada = registro.get(sha256)
    if entrada is None:
        entrada = registrar_pliego(sha256)
        registro = cargar_registro_pliegos()
        entrada = registro[sha256]
    entrada.setdefault("historial", []).append(
        {"fecha": _ahora(), "evento": evento, "detalle": detalle}
    )
    registro[sha256] = entrada
    _escribir(_publico() / _REGISTRO_PLIEGOS, registro)


# ─── Registro de evaluaciones (privado) ───────────────────────────────────────

def cargar_registro_evaluaciones() -> list[dict]:
    return _leer(_privado() / _REGISTRO_EVALUACIONES, [])


def registrar_evaluacion(
    sha256: str,
    cliente_id: str,
    *,
    veredicto: str = "",
    resultado: dict | None = None,
    pdf: bytes | None = None,
    **extra: Any,
) -> dict:
    """
    Guarda una evaluación contra un perfil. PRIVADA: lleva datos del cliente.

    Reemplaza la entrada anterior del mismo (pliego, cliente): lo que interesa
    es el último análisis, y el pliego conserva su historial aparte.
    """
    destino = dir_evaluacion(cliente_id, sha256)
    destino.mkdir(parents=True, exist_ok=True)

    entrada: dict[str, Any] = {
        "sha256": sha256,
        "cliente_id": cliente_id,
        "fecha": _ahora(),
        "veredicto": veredicto,
        "versiones": versiones(),
        **extra,
    }
    if resultado is not None:
        _escribir(destino / "resultado.json", resultado)
        entrada["ruta_resultado"] = str((destino / "resultado.json").relative_to(data_dir()))
    if pdf:
        ruta_pdf = destino / "informe.pdf"
        ruta_pdf.write_bytes(pdf)
        entrada["ruta_pdf"] = str(ruta_pdf.relative_to(data_dir()))

    registro = [e for e in cargar_registro_evaluaciones()
                if not (e.get("sha256") == sha256 and e.get("cliente_id") == cliente_id)]
    registro.append(entrada)
    _escribir(_privado() / _REGISTRO_EVALUACIONES, registro)
    return entrada


def evaluaciones_de(cliente_id: str) -> list[dict]:
    """Evaluaciones de un cliente, la más reciente primero."""
    return sorted(
        (e for e in cargar_registro_evaluaciones() if e.get("cliente_id") == cliente_id),
        key=lambda e: e.get("fecha", ""), reverse=True,
    )


def cargar_evaluacion(cliente_id: str, sha256: str) -> dict | None:
    """Resultado guardado, sin recalcular nada."""
    return _leer(dir_evaluacion(cliente_id, sha256) / "resultado.json", None)


# ─── Portafolio de demostración ───────────────────────────────────────────────

# Perfil ficticio. Nunca se enseña a un prospecto la evaluación de otro
# cliente: es información financiera de un tercero.
CLIENTE_DEMO = "demo_constructora_ficticia"


def portafolio() -> list[dict]:
    """
    Pliegos analizados que se pueden mostrar sin gastar API.

    Sólo evaluaciones del perfil ficticio. Un pliego sin evaluación demo
    aparece igualmente, con `demo=False`, para saber qué falta preparar.
    """
    evals = {e["sha256"]: e for e in evaluaciones_de(CLIENTE_DEMO)}
    salida = []
    for sha, p in cargar_registro_pliegos().items():
        ev = evals.get(sha)
        salida.append({
            "sha256": sha,
            "archivo": p.get("archivo", ""),
            "entidad": p.get("entidad", ""),
            "numero_proceso": p.get("numero_proceso", ""),
            "modalidad": p.get("modalidad", ""),
            "estado": p.get("estado", ""),
            "costo_usd": p.get("costo_usd", 0.0),
            "tiene_extraccion": "extraccion" in (p.get("artefactos") or {}),
            "demo": ev is not None,
            "veredicto": (ev or {}).get("veredicto", ""),
            "ruta_pdf": (ev or {}).get("ruta_pdf", ""),
        })
    return sorted(salida, key=lambda x: (not x["demo"], x["archivo"]))


def resumen() -> str:
    """Estado del almacén en texto, para el arranque y la línea de comandos."""
    est = estado_almacen()
    pliegos = cargar_registro_pliegos()
    evals = cargar_registro_evaluaciones()
    total = sum(p.get("costo_usd", 0.0) for p in pliegos.values())
    con_extraccion = sum(1 for p in pliegos.values()
                         if "extraccion" in (p.get("artefactos") or {}))
    filas = [
        f"Almacén: {est['ruta']}",
        f"  respaldo configurado : {'sí' if est['respaldado'] else 'NO'}",
        f"  pliegos registrados  : {len(pliegos)} ({con_extraccion} con extracción)",
        f"  evaluaciones         : {len(evals)}",
        f"  invertido en API     : ${total:.2f}",
    ]
    if est["aviso"]:
        filas.append(f"  AVISO: {est['aviso']}")
    return "\n".join(filas)


if __name__ == "__main__":
    print(resumen())
