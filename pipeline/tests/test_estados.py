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

from pipeline.src.estados import _OPERADORES as _OPERADORES_PY  # noqa: E402
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
        for campo in ("etiqueta", "forma", "clase", "detalle"):
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


def test_ningun_estado_declara_un_glifo_unicode_como_icono():
    """
    Un glifo (✓ ✕ ? !) no es un sistema de iconos: hereda la métrica de la
    fuente y no se alinea igual entre plataformas. `forma` nombra la figura y
    `app.js` la dibuja en SVG de trazo consistente.
    """
    for clave, pres in ESTADOS.items():
        assert "icono" not in pres, f"{clave} declara un glifo como icono"
    js = _estados_de_app_js()
    for clave, campos in js.items():
        assert "icono" not in campos, f"app.js: {clave} declara un glifo"


def test_cada_forma_tiene_un_svg_dibujado_en_app_js():
    """[conexión] Una forma sin SVG cae al punto genérico y pierde el estado."""
    fuente = _APP_JS.read_text("utf-8")
    inicio = fuente.index("const _SVG_ESTADO = {")
    bloque = fuente[inicio:fuente.index("\n};", inicio)]
    for clave, pres in ESTADOS.items():
        assert f"'{pres['forma']}'" in bloque, (
            f"la forma '{pres['forma']}' de {clave} no tiene SVG en app.js"
        )


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


# ─── Iconografía: un solo trazo, y la vista migrada se queda migrada ─────────

_DESIGN = _ROOT / "DESIGN.md"


def test_un_solo_trazo_en_todos_los_iconos():
    """
    Un trazo distinto es un icono de otro sistema. La regla vive en
    DESIGN.md → «Iconografía de la APP»; esto la hace verificable.
    """
    trazos = set(re.findall(r'stroke-width="([\d.]+)"', _APP_JS.read_text("utf-8")))
    assert trazos == {"1.7"}, f"trazos distintos: {sorted(trazos)}"


def test_la_vista_de_auditoria_no_tiene_emoji():
    """
    Migrada el 2026-09-23. Las OTRAS vistas sí los tienen, deliberadamente
    (D24): la unidad de coherencia es la vista, no la aplicación. Lo que no
    se tolera es una pantalla con los dos vocabularios a la vez.
    """
    fuente = _APP_JS.read_text("utf-8")
    i = fuente.index("function renderAuditResult")
    j = fuente.index("\n}\n", i)
    emoji = re.findall(
        "[\U0001F000-\U0001FAFF☀-➿⬀-⯿]", fuente[i:j])
    assert not emoji, f"emoji de vuelta en la vista de auditoría: {emoji}"


def test_los_paneles_de_requisitos_no_tienen_emoji():
    fuente = _APP_JS.read_text("utf-8")
    i = fuente.index("const _SVG_ESTADO")
    j = fuente.index("function renderAuditResult")
    emoji = re.findall(
        "[\U0001F000-\U0001FAFF☀-➿⬀-⯿]", fuente[i:j])
    assert not emoji, f"emoji en los paneles nuevos: {emoji}"


def test_todo_icono_definido_se_usa_y_todo_usado_esta_definido():
    """Un icono usado sin definir no dibuja nada y la etiqueta queda desnuda."""
    fuente = _APP_JS.read_text("utf-8")
    i = fuente.index("const _SVG_ICONO")
    bloque = fuente[i:fuente.index("\n};", i)]
    definidos = set(re.findall(r"^  (\w+):", bloque, re.M))
    usados = set(re.findall(r"icono\('(\w+)'\)", fuente))
    assert usados - definidos == set(), f"usados sin definir: {usados - definidos}"
    assert definidos - usados == set(), f"definidos sin usar: {definidos - usados}"


def test_design_md_documenta_el_alcance_de_la_migracion():
    """
    [conexión] Sin el inventario, alguien lee la regla del trazo en seis meses
    y asume que toda la app cumple. Pasó con CLAUDE.md y el tema oscuro.
    """
    texto = _DESIGN.read_text("utf-8")
    assert "Iconografía de la APP" in texto
    assert "The Distinguishable-Shape Rule" in texto
    assert "1,7px" in texto
    # Declara explícitamente lo que NO está migrado
    assert "Qué vistas NO están migradas" in texto
    assert "landing.html" in texto


# ─── [N7] Literal ilegible ───────────────────────────────────────────────────

_ROTO = ("Si el plazo estimado del Contrato es mayor a 12 meses el cálculo de "
         "la CRPC deberá tener en cuenta: CRPC = %&'()\"*!+!,- - ,/0- /\"")

_SANOS = [
    "CT = AC - PC ≥ CTd",
    "IL = AC/PC ≥ 1,21",
    "Mipyme | 0,25",
    "el segmento correspondiente es el segmento [72**]**",
    "maquinaria con una edad menor a veinte (20) años",
    "10% del valor del contrato",
    "CRPC = Presupuesto oficial estimado - Anticipo",
    "Hasta 5 | 150%",
]


def test_detecta_el_literal_corrupto_real():
    """
    El caso de Paicol: la fórmula del CRPC salió del PDF con la codificación
    rota. Está marcada `no_verificada`, así que el sistema lo sabe — pero la
    cadena llegaría al informe como cita textual del pliego.
    """
    from pipeline.src.estados import literal_ilegible
    assert literal_ilegible(_ROTO)


@pytest.mark.parametrize("literal", _SANOS)
def test_no_marca_formulas_legitimas(literal):
    """Una fórmula usa símbolos; lo que delata la corrupción es encadenarlos."""
    from pipeline.src.estados import literal_ilegible
    assert not literal_ilegible(literal), f"falso positivo: {literal!r}"


def test_la_cita_corrupta_no_se_publica():
    from pipeline.src.estados import texto_cita
    salida = texto_cita({"exigido_literal": _ROTO,
                         "fuente_numeral": "3.10.1 CÁLCULO CRPC"})
    assert "texto no legible" in salida
    assert "3.10.1 CÁLCULO CRPC" in salida, "el aviso debe decir dónde buscar"
    assert "%&'()" not in salida, "la cadena corrupta llegó a la salida"


def test_la_cita_sana_pasa_intacta():
    from pipeline.src.estados import texto_cita
    assert texto_cita({"exigido_literal": "CT = AC - PC ≥ CTd",
                       "fuente_numeral": "3.7"}) == "CT = AC - PC ≥ CTd"


def test_sin_literal_no_inventa_aviso():
    from pipeline.src.estados import texto_cita
    assert texto_cita({"exigido_literal": "", "fuente_numeral": "3.7"}) == ""
    assert texto_cita({}) == ""


def test_app_js_replica_el_detector_de_ilegibles():
    """
    [paridad] Si el front usa otro criterio, la pantalla y el informe dirían
    cosas distintas sobre la misma cita.
    """
    fuente = _APP_JS.read_text("utf-8")
    assert "const _RACHA_SIMBOLOS = /" in fuente, (
        "debe ser un literal de regex: construirla desde un string obliga a "
        "escapar dos veces y ahí se rompe"
    )
    assert "function literalIlegible(" in fuente
    assert "function textoCita(" in fuente
    # El mismo juego de símbolos de fórmula exentos
    for simbolo in ("≥", "≤", "∗", "°"):
        assert simbolo in fuente.split("const _RACHA_SIMBOLOS = /")[1][:160], (
            f"el front no exime {simbolo}: marcaría fórmulas legítimas"
        )


def test_el_front_usa_textoCita_no_el_literal_crudo():
    fuente = _APP_JS.read_text("utf-8")
    cuerpo = "\n".join(l for l in fuente.splitlines()
                       if not l.strip().startswith("//"))
    i = cuerpo.index("function _filaRequisito")
    j = cuerpo.index("function pintarRequisitos")
    fila = cuerpo[i:j]
    assert "textoCita(req)" in fila
    assert "_esc(req.exigido_literal)" not in fila, (
        "la fila publica el literal crudo: una cita corrupta llegaría al informe"
    )


def test_reportes_importa_el_detector():
    """El PDF necesita el mismo criterio al construir el informe nuevo."""
    texto = _REPORTES.read_text("utf-8")
    assert "literal_ilegible" in texto and "texto_cita" in texto


# ─── [N8] Unidad del umbral vs texto del pliego ──────────────────────────────

# Los cuatro casos REALES medidos entre Paicol y Ternera. Los cuatro con
# unidad="meses": es el valor que el extractor pone por defecto cuando la
# magnitud es temporal y no la resuelve.
_DISCORDANTES = [
    ({"unidad": "meses", "valor_umbral": 20.0, "fuente_numeral": "4.1.4",
      "exigido_literal": "maquinaria con una edad menor a veinte (20) años"}, "años"),
    ({"unidad": "meses", "valor_umbral": 1.0, "fuente_numeral": "2.5",
      "exigido_literal": "acreditar como mínimo un año de existencia"}, "años"),
    ({"unidad": "meses", "valor_umbral": 3.0, "fuente_numeral": "1.6",
      "exigido_literal": "dentro de los tres (3) días hábiles siguientes"}, "días"),
    ({"unidad": "meses", "valor_umbral": 60.0, "fuente_numeral": "2.5",
      "exigido_literal": "con una antigüedad máxima de sesenta (60) días"}, "días"),
]

_CONCORDANTES = [
    {"unidad": "%", "valor_umbral": 10.0, "exigido_literal": "10% del valor del contrato"},
    {"unidad": "meses", "valor_umbral": 12.0, "exigido_literal": "plazo superior a doce (12) meses"},
    {"unidad": "smmlv", "valor_umbral": 150.0, "exigido_literal": "valor de 150 SMMLV"},
    {"unidad": "dias", "valor_umbral": 30.0, "exigido_literal": "treinta (30) días calendario"},
    # Sin umbral no hay veredicto que falsear
    {"unidad": "pesos", "valor_umbral": None, "exigido_literal": "CT = AC - PC ≥ CTd"},
    # Sin unidad declarada no se concluye nada
    {"unidad": "", "valor_umbral": 5.0, "exigido_literal": "cinco contratos"},
    # El literal no nombra unidad: puede venir de una tabla o un anexo
    {"unidad": "meses", "valor_umbral": 6.0, "exigido_literal": "según la Matriz 1"},
]


@pytest.mark.parametrize("fila,esperado", _DISCORDANTES)
def test_detecta_los_cuatro_casos_reales(fila, esperado):
    from pipeline.src.estados import unidad_discordante
    d = unidad_discordante(fila)
    assert d is not None, f"no detectó: {fila['exigido_literal']}"
    assert d["etiqueta_texto"] == esperado
    assert d["etiqueta_campo"] == "meses"


@pytest.mark.parametrize("fila", _CONCORDANTES)
def test_no_marca_unidades_correctas(fila):
    from pipeline.src.estados import unidad_discordante
    assert unidad_discordante(fila) is None, f"falso positivo: {fila}"


def test_el_motivo_no_promete_correccion():
    """
    Deducir que «20 meses» quería decir «20 años» sería inventar. El motivo
    tiene que decir que NO se corrige y dónde verificar.
    """
    from pipeline.src.estados import motivo_unidad_discordante, unidad_discordante
    fila = _DISCORDANTES[1][0]
    motivo = motivo_unidad_discordante(fila, unidad_discordante(fila))
    assert "no se corrige" in motivo.lower()
    assert "2.5" in motivo, "debe nombrar el numeral a verificar"
    assert "1.0 meses" in motivo and "años" in motivo, "debe mostrar AMBOS datos"


def test_el_detalle_distingue_las_dos_causas_de_revisar_manual():
    """Umbrales alternativos y unidad discordante son causas distintas."""
    from pipeline.src.estados import texto_detalle
    por_unidad = texto_detalle({
        "estado": "revisar_manual", "valor_umbral": 1.0,
        "unidad_registrada": "meses", "unidad_en_el_pliego": "años"})
    assert "registrado 1.0 meses" in por_unidad
    assert "el pliego dice años" in por_unidad

    por_alternativas = texto_detalle({
        "estado": "revisar_manual",
        "umbrales_alternativos": [">= 1.21", ">= 1.0"]})
    assert "alternativas:" in por_alternativas


def test_el_evaluador_manda_la_discordancia_a_revisar_manual():
    """[conexión] El detector sin el evaluador no protege a nadie."""
    fuente = (_ROOT / "pipeline" / "src" / "evaluator.py").read_text("utf-8")
    assert "unidad_discordante" in fuente
    i = fuente.index("unidad_discordante({")
    bloque = fuente[i:i + 1200]
    assert '"estado":     "revisar_manual"' in bloque
    assert "unidad_en_el_pliego" in bloque, "debe exponer AMBOS datos"
    assert "unidad_registrada" in bloque


def test_app_js_replica_el_detector_de_unidad():
    fuente = _APP_JS.read_text("utf-8")
    assert "function unidadDiscordante(" in fuente
    for familia in ("anios", "meses", "dias", "smmlv", "porcentaje", "metros2"):
        assert familia in fuente, f"el front no conoce la familia {familia}"
    # Y la fila lo usa
    i = fuente.index("function _filaRequisito")
    j = fuente.index("function pintarRequisitos")
    assert "unidadDiscordante(req)" in fuente[i:j]


# ─── Alternativas de umbral: dict -> texto legible ──────────────────────────

def test_las_alternativas_de_umbral_no_vuelcan_el_diccionario():
    """
    `umbrales_alternativos` es list[dict]. Un `str(dict)` metía 1.400 caracteres
    de `{'valor_umbral': 5.0, 'operador': '<=', ...}` en la tabla de un informe
    que se firma ante una entidad. Encontrado al maquetar la sección 7.
    """
    fila = {
        "estado": "revisar_manual",
        "umbrales_alternativos": [
            {"valor_umbral": 5.0, "operador": "<=", "unidad": "contratos",
             "fuente_numeral": "3.5.1.", "nombre": "Número máximo de contratos"},
            {"valor_umbral": 1.0, "operador": ">=", "unidad": "contratos",
             "nombre": "Al menos un contrato bajo NSR-10"},
        ],
    }
    texto = texto_detalle(fila)
    for prohibido in ("{", "}", "'", "valor_umbral", "operador", "fuente_numeral"):
        assert prohibido not in texto, f"el detalle filtra sintaxis de Python: {texto}"
    assert "≤ 5 contratos — Número máximo de contratos" in texto
    # concuerda en número: «≤ 1 contratos» en un documento firmado es un
    # descuido que el lector atribuye al análisis entero
    assert "≥ 1 contrato — Al menos un contrato bajo NSR-10" in texto
    assert texto.startswith("alternativas: ")


def test_una_alternativa_sin_nombre_ni_unidad_sigue_siendo_legible():
    fila = {"estado": "revisar_manual",
            "umbrales_alternativos": [{"valor_umbral": 2, "operador": ">="}]}
    assert texto_detalle(fila) == "alternativas: ≥ 2"


def test_una_unidad_desconocida_no_se_singulariza_a_ciegas():
    """
    Quitar la «-s» final como regla general produciría «mese» y «SMMLV» roto.
    Lo que no está en el mapa se deja exactamente como vino.
    """
    fila = {"estado": "revisar_manual",
            "umbrales_alternativos": [{"valor_umbral": 1, "operador": ">=",
                                       "unidad": "SMMLV"}]}
    assert texto_detalle(fila) == "alternativas: ≥ 1 SMMLV"
    fila["umbrales_alternativos"][0]["unidad"] = "meses"
    assert texto_detalle(fila) == "alternativas: ≥ 1 mes"


def test_una_alternativa_que_no_es_dict_no_rompe():
    fila = {"estado": "revisar_manual", "umbrales_alternativos": ["texto suelto"]}
    assert texto_detalle(fila) == "alternativas: texto suelto"


def test_app_js_replica_la_redaccion_de_alternativas():
    """
    Las dos copias tienen que redactar igual. `umbrales_alternativos` es una
    lista de OBJETOS: `join(' / ')` producía «[object Object]» en pantalla y
    `str(dict)` volcaba el diccionario entero en el PDF de producción
    (`routers/reportes.py`). El mismo defecto en cuatro sitios a la vez.
    """
    js = _APP_JS.read_text("utf-8")
    assert "function textoAlternativa(" in js, (
        "app.js no tiene la réplica de `_texto_alternativa()`: la pantalla "
        "volverá a mostrar [object Object]")
    assert "v.join(' / ')" not in js, (
        "app.js vuelve a unir los objetos sin redactarlos")
    assert "it.alts.map(a => `<li>${_esc(textoAlternativa(a))}" in js, (
        "el panel de revisión manual imprime la alternativa sin redactar")
    # los dos mapas, con los mismos pares
    for clave, valor in _OPERADORES_PY.items():
        assert f"'{clave}': '" in js or f'"{clave}": "' in js, (
            f"app.js no traduce el operador {clave!r}")
    assert "contratos: 'contrato'" in js, "app.js no singulariza «contratos»"
    assert "meses: 'mes'" in js, "app.js no singulariza «meses»"
