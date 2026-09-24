# -*- coding: utf-8 -*-
"""
Mapa único de estados: Python y JavaScript no pueden divergir.

`app.js` replica `pipeline/src/estados.py` porque el navegador no importa
Python. Dos copias que se separan en silencio son peores que una sola mal
puesta: la pantalla diría una cosa y el informe firmado otra.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.src.estados import (  # noqa: E402
    ESTADOS,
    SIN_VEREDICTO,
    desde_fila,
    etiqueta,
    presentacion,
    texto_detalle,
)

_APP_JS = _ROOT / "static" / "app.js"
_REPORTES = _ROOT / "routers" / "reportes.py"


def _estados_de_app_js() -> dict[str, dict]:
    """Extrae el objeto ESTADOS de app.js sin ejecutar JavaScript."""
    texto = _APP_JS.read_text("utf-8")
    inicio = texto.index("const ESTADOS = {")
    fin = texto.index("\n};", inicio)
    cuerpo = texto[inicio + len("const ESTADOS = {"):fin]

    salida: dict[str, dict] = {}
    for linea in cuerpo.splitlines():
        linea = linea.strip().rstrip(",")
        if not linea or linea.startswith("//"):
            continue
        m = re.match(r"(\w+)\s*:\s*\{(.*)\}$", linea)
        if not m:
            continue
        campos: dict[str, str] = {}
        for par in re.finditer(r"(\w+)\s*:\s*'((?:[^'\\]|\\.)*)'", m.group(2)):
            campos[par.group(1)] = par.group(2)
        salida[m.group(1)] = campos
    return salida


# ─── Paridad ──────────────────────────────────────────────────────────────────

def test_app_js_replica_el_mapa_canonico():
    js = _estados_de_app_js()
    assert set(js) == set(ESTADOS), (
        f"Los estados difieren.\n  Python: {sorted(ESTADOS)}\n  app.js : {sorted(js)}"
    )
    for clave, py in ESTADOS.items():
        for campo in ("etiqueta", "icono", "forma", "clase", "detalle"):
            assert js[clave].get(campo, "") == py[campo], (
                f"'{clave}.{campo}' difiere: "
                f"Python={py[campo]!r} app.js={js[clave].get(campo)!r}"
            )


def test_las_cinco_etiquetas_son_las_acordadas():
    assert {k: v["etiqueta"] for k, v in ESTADOS.items()} == {
        "cumple": "CUMPLE",
        "no_cumple": "NO CUMPLE",
        "dato_faltante": "DATO FALTANTE",
        "revisar_manual": "REVISIÓN MANUAL",
        "no_aplica": "NO APLICA",
    }


def test_cada_estado_tiene_una_forma_distinta():
    """El informe se imprime en blanco y negro: el color no puede ser el único
    portador del significado."""
    formas = [v["forma"] for v in ESTADOS.values()]
    assert len(set(formas)) == len(formas), f"formas repetidas: {formas}"


# ─── Semántica ────────────────────────────────────────────────────────────────

def test_dato_faltante_no_es_un_incumplimiento():
    """El bug original: 8 de 14 indicadores de Paicol salían como ❌ / NO."""
    assert "dato_faltante" in SIN_VEREDICTO
    assert "revisar_manual" in SIN_VEREDICTO
    assert "no_cumple" not in SIN_VEREDICTO
    assert etiqueta("dato_faltante") == "DATO FALTANTE"
    assert "CUMPLE" not in etiqueta("dato_faltante").replace("DATO FALTANTE", "")


def test_desde_fila_prefiere_el_estado_real():
    assert desde_fila({"estado": "dato_faltante", "cumple": False}) == "dato_faltante"
    assert desde_fila({"estado": "revisar_manual"}) == "revisar_manual"


def test_desde_fila_tolera_resultados_viejos_del_historial():
    """Sin `estado`, un False es 'no cumple' — no se inventa dato_faltante."""
    assert desde_fila({"cumple": True}) == "cumple"
    assert desde_fila({"cumple": False}) == "no_cumple"
    assert desde_fila({}) == "no_cumple"


def test_un_estado_desconocido_no_revienta_ni_miente():
    pres = presentacion("estado_que_no_existe")
    assert pres["etiqueta"] == "SIN CLASIFICAR"
    assert "CUMPLE" not in pres["etiqueta"]


# ─── Detalle ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fila,esperado", [
    ({"estado": "dato_faltante", "documento_requerido": "Estados financieros"},
     "aporta: Estados financieros"),
    ({"estado": "no_cumple", "diferencia": -0.31}, "faltan 0.31"),
    ({"estado": "no_cumple", "diferencia": 0.5}, "excede en 0.5"),
    ({"estado": "revisar_manual", "umbrales_alternativos": ["6 contratos", "7 contratos"]},
     "alternativas: 6 contratos / 7 contratos"),
    ({"estado": "cumple"}, ""),
    ({"estado": "dato_faltante"}, ""),
    ({"estado": "revisar_manual", "umbrales_alternativos": []}, ""),
])
def test_texto_detalle(fila, esperado):
    assert texto_detalle(fila) == esperado


# ─── Los consumidores usan el mapa, no su propia copia ───────────────────────

def test_el_front_ya_no_colapsa_el_estado_a_un_booleano():
    texto = _APP_JS.read_text("utf-8")
    cuerpo = "\n".join(l for l in texto.splitlines() if not l.strip().startswith("//"))
    assert "row.cumple ? '✅'" not in cuerpo
    assert "estadoDeFila(row)" in cuerpo


def _fuente_de(ruta: Path, nombre: str) -> str:
    """
    Código de una función, sin docstring ni comentarios.

    Se lee con `ast` en vez de buscar en el archivo entero: los comentarios
    que EXPLICAN el bug corregido citan el código viejo, y una búsqueda por
    texto los confunde con el bug.
    """
    import ast

    arbol = ast.parse(ruta.read_text("utf-8"))
    fn = next(n for n in ast.walk(arbol)
              if isinstance(n, ast.FunctionDef) and n.name == nombre)
    cuerpo = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                             and isinstance(fn.body[0].value, ast.Constant)
                             and isinstance(fn.body[0].value.value, str)) else fn.body
    return "\n".join(ast.unparse(n) for n in cuerpo)


@pytest.mark.parametrize("funcion", ["_tabla_checklist", "_tabla_requisitos"])
def test_las_tablas_del_pdf_usan_el_mapa_no_un_booleano(funcion):
    codigo = _fuente_de(_REPORTES, funcion)
    assert "'SI' if" not in codigo and '"SI" if' not in codigo
    assert "desde_fila(item)" in codigo
    assert "etiqueta(estado)" in codigo


def test_reportes_importa_el_mapa_canonico():
    assert "from pipeline.src.estados import" in _REPORTES.read_text("utf-8")


@pytest.mark.parametrize("funcion", ["_tabla_checklist", "_tabla_requisitos"])
def test_el_pdf_no_dibuja_iconos(funcion):
    """
    Decisión: el informe es texto, tablas y etiquetas. Sin iconografía.

    `limpiar_texto_pdf` sí conoce los iconos, pero para SANEARLOS si llegan
    desde los agentes; queda fuera de esta comprobación a propósito.
    """
    codigo = _fuente_de(_REPORTES, funcion)
    for icono in ("✅", "❌", "⚠", "📋", "💰", "⚖", "[OK]", "[NO]"):
        assert icono not in codigo, f"el PDF no puede dibujar {icono}"


# ─── La cita fabricada ────────────────────────────────────────────────────────

def test_ningun_campo_de_norma_tiene_valor_por_defecto():
    """
    `auditoria.py` rellenaba la columna "Norma" con
    "Decreto 1082/2015 art. 2.2.1.2.1.5.8", que no existe. Un valor por
    defecto en un campo de cita es una cita fabricada por diseño.
    """
    texto = (_ROOT / "routers" / "auditoria.py").read_text("utf-8")
    for linea in texto.splitlines():
        if linea.strip().startswith("#"):
            continue
        m = re.search(r'"norma":\s*[\w.]+\.get\(\s*"norma"\s*,\s*(.+?)\)', linea)
        if m:
            assert m.group(1).strip() in ('""', "''"), (
                f"valor por defecto en un campo de norma: {linea.strip()}"
            )
