# -*- coding: utf-8 -*-
"""
pipeline/src/catalogo.py — Catálogo de objetos del dominio.

Resuelve [B11]. `grupo_es_coherente()` compara PALABRAS: un grupo unido por un
término específico pero transversal ("residual", 7 de 13 miembros) sobrevive
aunque mezcle capacidad residual con ingresos operacionales, tarjeta
profesional e índice de liquidez. El catálogo declara qué objetos existen.

Sin API, sin modelo: tabla auditable en `pipeline/data/catalogo_objetos.json`.
Determinista y reproducible — dos corridas sobre el mismo pliego dan lo mismo.

Clave de agrupación: (objeto, aspecto, capitulo)
  · objeto   — de qué habla el requisito (RUP, LIQUIDEZ, GARANTIA_SERIEDAD)
  · aspecto  — qué se exige sobre él (vigencia, monto, formato…), opcional
  · capitulo — mismo objeto en capítulos distintos NO se fusiona: "RUP para
               experiencia" (3.5) y "RUP para capacidad financiera" (3.9) son
               verificaciones distintas del mismo documento.

Invariantes:
  [K1] Ante la duda, NO fusionar. Sin objeto ⇒ el requisito queda solo.
  [K2] Gana el alias MÁS LARGO ("capacidad residual" vence a "capacidad").
  [K3] Todo requisito sin objeto se registra — el catálogo crece con datos
       reales, nunca por anticipación.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .extractor import Requisito

_REPO_ROOT = Path(__file__).parent.parent.parent
_RUTA_CATALOGO = Path(__file__).parent.parent / "data" / "catalogo_objetos.json"
_RUTA_LOG = _REPO_ROOT / "logs" / "objetos_no_identificados.jsonl"


# ─── Normalización ────────────────────────────────────────────────────────────

def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes, espacios colapsados. Conserva dígitos y guiones."""
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9\s\-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ─── Carga del catálogo ───────────────────────────────────────────────────────

@dataclass
class Catalogo:
    # (alias_normalizado, objeto) ordenado por longitud de alias descendente [K2]
    objetos: list[tuple[str, str]] = field(default_factory=list)
    aspectos: list[tuple[str, str]] = field(default_factory=list)
    # [K4] Lista de (alias, sujeto) en ORDEN DE PRIORIDAD del catálogo, no por
    # longitud: un requisito de "persona natural extranjera" es de
    # persona_natural, porque el tipo de persona es el eje que separa la bolsa.
    # `extranjero` sólo gana cuando no se nombra tipo de persona.
    sujetos: list[tuple[str, str]] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    # objeto → ficha completa, para reportes
    fichas: dict[str, dict] = field(default_factory=dict)

    @property
    def n_objetos(self) -> int:
        return len(self.fichas)


_CACHE: Catalogo | None = None


def cargar_catalogo(ruta: Path | None = None, recargar: bool = False) -> Catalogo:
    """Carga y ordena el catálogo. Cachea salvo `recargar=True` (para tests)."""
    global _CACHE
    if _CACHE is not None and not recargar and ruta is None:
        return _CACHE

    p = ruta or _RUTA_CATALOGO
    raw = json.loads(p.read_text("utf-8"))

    objetos: list[tuple[str, str]] = []
    fichas: dict[str, dict] = {}
    for ficha in raw.get("objetos", []):
        nombre = ficha["objeto"]
        fichas[nombre] = ficha
        for alias in ficha.get("alias", []):
            objetos.append((normalizar(alias), nombre))

    aspectos: list[tuple[str, str]] = []
    for ficha in raw.get("aspectos", []):
        for alias in ficha.get("alias", []):
            aspectos.append((normalizar(alias), ficha["aspecto"]))

    # [K4] El orden del eje `sujeto` es la PRIORIDAD declarada en el catálogo.
    # Aquí NO se ordena por longitud: "persona natural" (15 chars) debe ganar a
    # "sin domicilio en colombia" (25) cuando ambos aparecen en el mismo
    # requisito, y la regla de alias más largo haría lo contrario.
    sujetos: list[tuple[str, str]] = []
    for ficha in raw.get("sujetos", []):
        for alias in ficha.get("alias", []):
            sujetos.append((normalizar(alias), ficha["sujeto"]))

    # [K2] alias más largo primero
    objetos.sort(key=lambda oa: -len(oa[0]))
    aspectos.sort(key=lambda aa: -len(aa[0]))

    cat = Catalogo(objetos=objetos, aspectos=aspectos, sujetos=sujetos,
                   meta=raw.get("_meta", {}), fichas=fichas)
    if ruta is None:
        _CACHE = cat
    return cat


# ─── Identificación ───────────────────────────────────────────────────────────

_MAX_CHARS_LITERAL = 200


def _buscar(texto_norm: str, tabla: list[tuple[str, str]]) -> str | None:
    """Primer alias de la tabla (ya ordenada por longitud) presente en el texto."""
    for alias, etiqueta in tabla:
        if alias in texto_norm:
            return etiqueta
    return None


def identificar_objeto(req: Requisito, cat: Catalogo | None = None) -> str | None:
    """
    Objeto del requisito, o None si el catálogo no lo reconoce.

    Busca en el NOMBRE primero; si no encuentra, en los primeros 200 caracteres
    de `exigido_literal`. [K2] gana el alias más largo.
    """
    cat = cat or cargar_catalogo()
    hallado = _buscar(normalizar(req.nombre), cat.objetos)
    if hallado:
        return hallado
    literal = (req.exigido_literal or "")[:_MAX_CHARS_LITERAL]
    return _buscar(normalizar(literal), cat.objetos)


def identificar_aspecto(req: Requisito, cat: Catalogo | None = None) -> str | None:
    """Aspecto del requisito (qué se exige sobre el objeto), o None."""
    cat = cat or cargar_catalogo()
    return _buscar(normalizar(req.nombre), cat.aspectos)


def _capitulo(req: Requisito) -> str:
    """
    Sección del requisito, para no fusionar el mismo objeto entre secciones.

    Usa los DOS primeros componentes del numeral: "3.5.1. CARACTERÍSTICAS…"
    → "3.5". Con sólo el capítulo ("3") el RUP de experiencia (3.5) y el RUP
    de capacidad financiera (3.9) caían en la misma clave y se fusionaban,
    cuando son verificaciones distintas del mismo documento.

    Sin numeral numérico, devuelve el prefijo en mayúsculas ("A.", "B.") o "".
    """
    s = (req.fuente_numeral or "").strip()
    m = re.match(r"^(\d+)\.(\d+)", s)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    m = re.match(r"^(\d+)", s)
    if m:
        return m.group(1)
    m = re.match(r"^([A-Z])\.", s)
    if m:
        return m.group(1)
    return ""


def identificar_sujeto(req: Requisito, cat: Catalogo | None = None) -> str | None:
    """
    [K4] A QUIÉN se le exige: persona natural, jurídica, extranjero,
    proponente plural o entidad estatal. None si no se nombra ninguno.

    Existe porque la clave de tres ejes fusionaba requisitos de sujetos
    distintos bajo un solo veredicto. En Ternera formó cuatro bolsas, tres de
    ellas CON umbral: "existencia y representación — persona jurídica
    extranjera" (6.0) arrastraba dos requisitos de persona natural, y
    "seguridad social — persona natural" (30.0) arrastraba uno de personas
    jurídicas. El umbral del primario se presentaba como si aplicara a los
    cinco.

    Ante la duda, None: es más seguro dejar un requisito solo que atribuirle
    un sujeto y fusionarlo con otro que no le corresponde.
    """
    cat = cat or cargar_catalogo()
    # Recorre en el orden del catálogo, que es la prioridad [K4]
    return _buscar(normalizar(req.nombre), cat.sujetos)


def clave_agrupacion(
    req: Requisito, cat: Catalogo | None = None
) -> tuple[str, str | None, str | None, str] | None:
    """
    (objeto, aspecto, sujeto, capitulo) o None si no hay objeto identificable.

    [K1] None ⇒ el llamador NO debe fusionar este requisito.

    `sujeto=None` no impide agrupar: dos requisitos del mismo objeto y aspecto
    se fusionan aunque ninguno nombre sujeto, porque los une el objeto, no la
    ausencia de sujeto. Lo que el eje hace es SEPARAR: un requisito de persona
    natural nunca se fusiona con uno de persona jurídica.
    """
    cat = cat or cargar_catalogo()
    objeto = identificar_objeto(req, cat)
    if objeto is None:
        return None
    return (objeto, identificar_aspecto(req, cat),
            identificar_sujeto(req, cat), _capitulo(req))


def _stems_objeto_para(objeto: str, cat: Catalogo | None = None) -> str | None:
    """
    Raíz de 6 caracteres del alias más largo del objeto, para que
    `clasificador._elegir_primario()` prefiera un miembro cuyo nombre
    mencione el objeto en vez del que tenga el literal más largo.

    Devuelve None si el objeto no está en el catálogo.
    """
    cat = cat or cargar_catalogo()
    ficha = cat.fichas.get(objeto)
    if not ficha:
        return None
    alias = max(ficha.get("alias") or [""], key=len)
    palabras = [p for p in normalizar(alias).split() if len(p) >= 3]
    if not palabras:
        return None
    # La palabra más larga del alias es la más distintiva
    return max(palabras, key=len)[:6]


# ─── [K3] Registro de faltantes ───────────────────────────────────────────────

def registrar_no_identificados(
    reqs: list[Requisito],
    pliego: str = "",
    ruta_log: Path | None = None,
) -> dict:
    """
    Registra en JSONL los requisitos sin objeto y devuelve el reporte agregado.

    El reporte es lo que se revisa para hacer crecer el catálogo: cobertura y
    los nombres sin objeto más frecuentes.
    """
    cat = cargar_catalogo()
    sin_objeto = [r for r in reqs if identificar_objeto(r, cat) is None]

    p = ruta_log or _RUTA_LOG
    if sin_objeto:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).isoformat()
            with p.open("a", encoding="utf-8") as f:
                for r in sin_objeto:
                    f.write(json.dumps({
                        "timestamp":      ts,
                        "pliego":         pliego,
                        "nombre":         r.nombre,
                        "categoria":      r.categoria,
                        "fuente_numeral": r.fuente_numeral,
                    }, ensure_ascii=False) + "\n")
        except Exception as exc:
            # No interrumpir la consolidación por un fallo de log
            print(f"[CATALOGO] No se pudo escribir {p}: {exc}")

    total = len(reqs)
    con_objeto = total - len(sin_objeto)
    con_aspecto = sum(
        1 for r in reqs
        if identificar_objeto(r, cat) is not None and identificar_aspecto(r, cat) is not None
    )

    from collections import Counter
    top = Counter(r.nombre for r in sin_objeto).most_common(10)

    return {
        "total":              total,
        "con_objeto":         con_objeto,
        "con_objeto_y_aspecto": con_aspecto,
        "solo_objeto":        con_objeto - con_aspecto,
        "sin_objeto":         len(sin_objeto),
        "cobertura":          round(con_objeto / total, 3) if total else 0.0,
        "objetos_en_catalogo": cat.n_objetos,
        "top_sin_objeto":     [{"nombre": n, "frecuencia": c} for n, c in top],
    }


def imprimir_reporte(rep: dict) -> None:
    """Reporte legible para stdout del pipeline."""
    print(f"  Cobertura del catálogo : {rep['cobertura']:.1%} "
          f"({rep['con_objeto']}/{rep['total']}) — {rep['objetos_en_catalogo']} objetos")
    print(f"    objeto + aspecto     : {rep['con_objeto_y_aspecto']}")
    print(f"    solo objeto          : {rep['solo_objeto']}")
    print(f"    sin objeto           : {rep['sin_objeto']}")
    if rep["cobertura"] < 0.70:
        print("  ⚠ Cobertura bajo el 70%: el catálogo necesita más entradas "
              "antes de sustituir la regla de coherencia.")
    if rep["top_sin_objeto"]:
        print("  Top nombres sin objeto:")
        for e in rep["top_sin_objeto"]:
            print(f"    {e['frecuencia']}×  {e['nombre'][:66]}")
