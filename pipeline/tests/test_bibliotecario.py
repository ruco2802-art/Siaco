# -*- coding: utf-8 -*-
"""
tests/test_bibliotecario.py — Bibliotecario normativo, offline.

Sin API: todas las salidas del modelo están simuladas. Lo que se prueba es el
VERIFICADOR, que es código, y el comportamiento ante fallos.

Estándar bajo prueba: cita textual verificable, o sin_respaldo. No hay grados.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.src.bibliotecario import (
    Cita,
    aviso_de_articulo,
    Respaldo,
    buscar_respaldo,
    cargar_indice,
    cargar_skill,
    documentos_citables,
    texto_articulo,
    palabras_ilegibles,
    proporcion_ilegible,
    verificar_cita,
    verificar_respaldo,
)
from pipeline.src.eval_bibliotecario import (
    cargar_ground_truth,
    clasificar_caso,
    evaluar_bibliotecario,
    imprimir_reporte,
    suelo_abstencion,
    techo_indice,
)

_BIB = _ROOT / "biblioteca_normativa"
_INDICE_OK = (_BIB / "indice.json").exists()

pytestmark = pytest.mark.skipif(
    not _INDICE_OK, reason="biblioteca_normativa/indice.json no disponible"
)


@pytest.fixture(scope="module")
def indice():
    return cargar_indice()


def _skill_valida(tmp_path: Path) -> Path:
    """
    Skill mínima que PASA la validación por secciones.

    Los tests que ejercitan el manejo de respuestas del modelo necesitan
    superar `cargar_skill()`; lo que se prueba ahí es el parseo, no el skill.
    """
    p = tmp_path / "skill.md"
    p.write_text(
        "# Skill: Bibliotecario normativo\n\n"
        "## Rol\nBuscas y citas.\n\n"
        "### R6 — Coincidencia parcial\nUsa respaldo_parcial.\n\n"
        "## Formato de salida\nSolo JSON.\n\n"
        "## Autoverificación antes de responder\n1. ¿Es copia exacta?\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture(scope="module")
def fragmento_real(indice):
    """Un fragmento literal del art. 5 de la Ley 1150, tomado del archivo."""
    doc = next(d for d in indice["documentos"] if d["norma"] == "Ley 1150 de 2007")
    texto = texto_articulo(doc["archivo_md"], "5", indice)
    assert texto, "No se pudo leer el art. 5 de la Ley 1150"
    # Un tramo del cuerpo, no el encabezado
    cuerpo = texto.split("\n", 1)[1].strip()
    return doc, cuerpo[:180]


# ─── 1. Fragmento verbatim → verificada=True ─────────────────────────────────

def test_fragmento_verbatim_se_verifica(indice, fragmento_real):
    doc, frag = fragmento_real
    cita = Cita(norma=doc["norma"], articulo="5", fragmento=frag,
                archivo=doc["archivo_md"], pertinencia="define requisitos habilitantes")
    assert verificar_cita(cita, "afirmación de prueba", indice) is True
    assert cita.verificada is True


# ─── 2. Fragmento parafraseado → verificada=False + log ──────────────────────

def test_fragmento_parafraseado_no_se_verifica(indice, tmp_path, monkeypatch):
    import pipeline.src.bibliotecario as B
    log = tmp_path / "invalidas.jsonl"
    monkeypatch.setattr(B, "_LOG_INVALIDAS", log)

    doc = next(d for d in indice["documentos"] if d["norma"] == "Ley 1150 de 2007")
    cita = Cita(
        norma=doc["norma"], articulo="5",
        # Plausible, con las palabras correctas, pero NO literal
        fragmento="La capacidad juridica y la experiencia del proponente seran "
                  "verificadas como requisitos habilitantes sin asignacion de puntaje.",
        archivo=doc["archivo_md"], pertinencia="parafraseado",
    )
    assert verificar_cita(cita, "afirmación X", indice) is False
    assert cita.verificada is False

    assert log.exists(), "El fallo crítico no se registró"
    lineas = [json.loads(l) for l in log.read_text("utf-8").splitlines() if l.strip()]
    assert len(lineas) == 1
    assert lineas[0]["motivo"] == "fragmento_no_literal"
    assert lineas[0]["afirmacion"] == "afirmación X"


# ─── 3. Norma ausente del índice → fallo crítico ─────────────────────────────

def test_norma_fuera_del_indice_es_fallo_critico(indice, tmp_path, monkeypatch):
    import pipeline.src.bibliotecario as B
    log = tmp_path / "invalidas.jsonl"
    monkeypatch.setattr(B, "_LOG_INVALIDAS", log)

    cita = Cita(
        norma="Ley 1437 de 2011", articulo="74",
        fragmento="Contra los actos definitivos procederá el recurso de reposición.",
        archivo="Ley_1437_de_2011.md", pertinencia="recursos",
    )
    assert verificar_cita(cita, "plazo de reposición", indice) is False
    lineas = [json.loads(l) for l in log.read_text("utf-8").splitlines() if l.strip()]
    assert lineas[0]["motivo"] == "norma_fuera_del_indice"


def test_resoluciones_escaneadas_no_son_citables(indice):
    """Las Res. CCE 539/540/541 tienen citable=false: no se pueden citar."""
    citables = {d["norma"] for d in indice["documentos"] if d["citable"]}
    for r in ("Resolución CCE 539 de 2025", "Resolución CCE 540 de 2025",
              "Resolución CCE 541 de 2025"):
        assert r not in citables, f"{r} no debería ser citable (escaneada)"


# ─── 4. Respaldo degradado cuando ninguna cita resiste ───────────────────────

def test_respaldo_sin_citas_verificadas_pasa_a_sin_respaldo(indice, tmp_path, monkeypatch):
    import pipeline.src.bibliotecario as B
    monkeypatch.setattr(B, "_LOG_INVALIDAS", tmp_path / "x.jsonl")

    r = Respaldo(
        afirmacion="X", estado="respaldada",
        citas=[Cita(norma="Ley 80 de 1993", articulo="5",
                    fragmento="Texto que no existe en ninguna parte del archivo indexado.",
                    archivo="Ley_80_de_1993.md", pertinencia="p")],
    )
    out = verificar_respaldo(r, indice)
    assert out.estado == "sin_respaldo"
    assert out.motivo == "articulo_no_pertinente"
    assert out.citas == []


# ─── 5. Clasificación del evaluador ──────────────────────────────────────────

def test_sin_respaldo_con_norma_ausente_es_acierto(indice):
    r = Respaldo(afirmacion="A", estado="sin_respaldo", motivo="norma_ausente")
    clase, _ = clasificar_caso(
        r, {"estado_esperado": "sin_respaldo", "norma_esperada": "Ley 1437 de 2011"}, indice
    )
    assert clase == "acierto"


def test_sin_respaldo_con_norma_disponible_es_omision(indice):
    r = Respaldo(afirmacion="A", estado="sin_respaldo", motivo="norma_ausente")
    clase, _ = clasificar_caso(
        r, {"estado_esperado": "respaldada", "norma_esperada": "Ley 1150 de 2007",
            "articulo_esperado": "5"}, indice
    )
    assert clase == "omision"


def test_cita_no_verificada_es_fallo_critico(indice):
    r = Respaldo(
        afirmacion="A", estado="respaldada",
        citas=[Cita(norma="Ley 1150 de 2007", articulo="5", fragmento="x" * 40,
                    archivo="Ley_1150_de_2007.md", pertinencia="p", verificada=False)],
    )
    clase, _ = clasificar_caso(
        r, {"estado_esperado": "respaldada", "norma_esperada": "Ley 1150 de 2007",
            "articulo_esperado": "5"}, indice
    )
    assert clase == "fallo_critico"


def test_articulo_equivocado_es_fallo(indice, fragmento_real):
    doc, frag = fragmento_real
    r = Respaldo(
        afirmacion="A", estado="respaldada",
        citas=[Cita(norma="Ley 1150 de 2007", articulo="9", fragmento=frag,
                    archivo=doc["archivo_md"], pertinencia="p", verificada=True)],
    )
    clase, _ = clasificar_caso(
        r, {"estado_esperado": "respaldada", "norma_esperada": "Ley 1150 de 2007",
            "articulo_esperado": "5"}, indice
    )
    assert clase == "fallo"


def test_un_fallo_critico_invalida_la_corrida(indice, fragmento_real):
    doc, frag = fragmento_real
    gt = [
        {"id": "A1", "afirmacion": "buena", "estado_esperado": "respaldada",
         "norma_esperada": "Ley 1150 de 2007", "articulo_esperado": "5"},
        {"id": "A2", "afirmacion": "mala", "estado_esperado": "respaldada",
         "norma_esperada": "Ley 1150 de 2007", "articulo_esperado": "5"},
    ]
    resultados = [
        Respaldo(afirmacion="buena", estado="respaldada",
                 citas=[Cita(norma="Ley 1150 de 2007", articulo="5", fragmento=frag,
                             archivo=doc["archivo_md"], pertinencia="p", verificada=True)]),
        Respaldo(afirmacion="mala", estado="respaldada",
                 citas=[Cita(norma="Ley 9999 de 2099", articulo="1", fragmento="y" * 40,
                             archivo="inventada.md", pertinencia="p", verificada=True)]),
    ]
    rep = evaluar_bibliotecario(resultados, gt, indice)
    assert rep["acierto"] == 1
    assert rep["fallo_critico"] == 1
    assert rep["aprobada"] is False, "Un fallo crítico debe invalidar la corrida"


# ─── 6. [N4] Skill ausente → error explícito, sin respaldo embebido ──────────

def test_skill_ausente_lanza_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Skill del bibliotecario"):
        cargar_skill(tmp_path / "no_existe.md")


def test_skill_minima_sin_secciones_lanza_error(tmp_path):
    p = tmp_path / "skill.md"
    p.write_text("# demasiado corta", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="incompleta"):
        cargar_skill(p)


def test_buscar_respaldo_sin_skill_no_llama_al_modelo(monkeypatch, tmp_path):
    """Sin skill no se gasta API: el error ocurre antes de construir el cliente."""
    import pipeline.src.bibliotecario as B
    monkeypatch.setattr(B, "_SKILL", tmp_path / "ausente.md")
    llamadas = []
    monkeypatch.setattr(B, "_cliente", lambda: llamadas.append(1))
    with pytest.raises(FileNotFoundError):
        buscar_respaldo("cualquier afirmación", "obra_publica", "educacion")
    assert not llamadas, "Se intentó crear el cliente sin skill"


# ─── 7. [I2] stop_reason=max_tokens → no JSONDecodeError ─────────────────────

def test_max_tokens_no_produce_jsondecodeerror(monkeypatch, tmp_path):
    import pipeline.src.bibliotecario as B

    monkeypatch.setattr(B, "_SKILL", _skill_valida(tmp_path))

    resp = MagicMock()
    resp.stop_reason = "max_tokens"
    resp.content = [SimpleNamespace(type="text", text='{"estado":"respaldada","selec')]
    cliente = MagicMock()
    cliente.messages.create.return_value = resp

    out = buscar_respaldo("afirmación", "", "", _client=cliente)
    assert out.estado == "sin_respaldo"
    assert "truncada" in (out.detalle or "").lower()


def test_json_invalido_degrada_a_sin_respaldo(monkeypatch, tmp_path):
    import pipeline.src.bibliotecario as B
    monkeypatch.setattr(B, "_SKILL", _skill_valida(tmp_path))

    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [SimpleNamespace(type="text", text="Lo siento, no puedo responder.")]
    cliente = MagicMock()
    cliente.messages.create.return_value = resp

    out = buscar_respaldo("afirmación", "", "", _client=cliente)
    assert out.estado == "sin_respaldo"


# ─── 8. Filtrado del índice por modalidad y sector ───────────────────────────

def test_transversales_entran_siempre(indice):
    docs = documentos_citables("obra_publica", "educacion", indice)
    normas = {d["norma"] for d in docs}
    assert "Ley 80 de 1993" in normas
    assert "Decreto 1082 de 2015" in normas


def test_otro_sector_se_omite(indice):
    docs = documentos_citables("obra_publica", "salud", indice)
    normas = {d["norma"] for d in docs}
    assert not any("220 de 2021" in n for n in normas), (
        "Un documento del sector educación no debe ofrecerse para el sector salud"
    )


def test_no_citables_nunca_entran(indice):
    for mod in ("obra_publica", "menor_cuantia", "minima_cuantia", ""):
        normas = {d["norma"] for d in documentos_citables(mod, "", indice)}
        assert not any("CCE 53" in n or "CCE 54" in n for n in normas)


# ─── 9. El catálogo del prompt no lleva el texto de las normas ───────────────

def test_skill_real_del_repo_carga(indice):
    """El skill guardado en .claude/skills/ debe pasar la validación."""
    texto = cargar_skill()
    assert "## Formato de salida" in texto
    assert "R6 — Coincidencia parcial" in texto
    assert len(texto) > 4_000


def test_skill_sin_formato_de_salida_es_incompleta(tmp_path):
    """
    Validación por SECCIONES: un skill cortado a media regla pesa miles de
    caracteres y pasaría cualquier mínimo de longitud.
    """
    p = tmp_path / "skill.md"
    p.write_text(
        "# Skill: Bibliotecario normativo\n\n## Rol\n" + ("texto de relleno. " * 200)
        + "\n### R5 — sin_respaldo es una respuesta válida\n"
          "Si ninguna norma de los documentos entregados respalda la afirmación:",
        encoding="utf-8",
    )
    assert len(p.read_text("utf-8")) > 2_000, "el fixture debe superar el mínimo viejo"
    with pytest.raises(FileNotFoundError, match="incompleta"):
        cargar_skill(p)


# ─── 10. [R6] respaldo_parcial ────────────────────────────────────────────────

def test_respaldo_parcial_con_alcance_es_acierto(indice, fragmento_real):
    doc, frag = fragmento_real
    r = Respaldo(
        afirmacion="A", estado="respaldo_parcial",
        alcance_real="La norma fija el plazo para licitación; el proceso es de menor cuantía.",
        citas=[Cita(norma="Ley 1150 de 2007", articulo="5", fragmento=frag,
                    archivo=doc["archivo_md"], pertinencia="p", verificada=True)],
    )
    clase, _ = clasificar_caso(
        r, {"estado_esperado": "respaldo_parcial", "norma_esperada": "Ley 1150 de 2007"}, indice
    )
    assert clase == "acierto"


def test_respaldo_parcial_sin_alcance_es_fallo(indice, fragmento_real):
    """Declarar parcial sin explicar el alcance no informa nada."""
    doc, frag = fragmento_real
    r = Respaldo(
        afirmacion="A", estado="respaldo_parcial", alcance_real=None,
        citas=[Cita(norma="Ley 1150 de 2007", articulo="5", fragmento=frag,
                    archivo=doc["archivo_md"], pertinencia="p", verificada=True)],
    )
    clase, _ = clasificar_caso(
        r, {"estado_esperado": "respaldo_parcial", "norma_esperada": "Ley 1150 de 2007"}, indice
    )
    assert clase == "fallo"


def test_respaldo_pleno_cuando_se_esperaba_parcial_es_fallo(indice, fragmento_real):
    doc, frag = fragmento_real
    r = Respaldo(
        afirmacion="A", estado="respaldada",
        citas=[Cita(norma="Ley 1150 de 2007", articulo="5", fragmento=frag,
                    archivo=doc["archivo_md"], pertinencia="p", verificada=True)],
    )
    clase, expl = clasificar_caso(
        r, {"estado_esperado": "respaldo_parcial", "norma_esperada": "Ley 1150 de 2007"}, indice
    )
    assert clase == "fallo"
    assert "pleno" in expl


def test_parcial_sin_citas_verificadas_degrada(indice, tmp_path, monkeypatch):
    import pipeline.src.bibliotecario as B
    monkeypatch.setattr(B, "_LOG_INVALIDAS", tmp_path / "x.jsonl")
    r = Respaldo(
        afirmacion="A", estado="respaldo_parcial", alcance_real="algo",
        citas=[Cita(norma="Ley 80 de 1993", articulo="5",
                    fragmento="Texto inexistente en el archivo indexado, suficientemente largo.",
                    archivo="Ley_80_de_1993.md", pertinencia="p")],
    )
    out = verificar_respaldo(r, indice)
    assert out.estado == "sin_respaldo"
    assert out.alcance_real is None


# ─── 11. [R4] normas_secundarias se verifican con el mismo estándar ──────────

def test_normas_secundarias_se_verifican(indice, tmp_path, monkeypatch, fragmento_real):
    import pipeline.src.bibliotecario as B
    monkeypatch.setattr(B, "_LOG_INVALIDAS", tmp_path / "x.jsonl")
    doc, frag = fragmento_real
    r = Respaldo(
        afirmacion="A", estado="respaldada",
        citas=[Cita(norma="Ley 1150 de 2007", articulo="5", fragmento=frag,
                    archivo=doc["archivo_md"], pertinencia="principal")],
        normas_secundarias=[
            Cita(norma="Ley 1150 de 2007", articulo="5", fragmento=frag,
                 archivo=doc["archivo_md"], pertinencia="secundaria buena"),
            Cita(norma="Ley 80 de 1993", articulo="1",
                 fragmento="Fragmento inventado que no aparece en el archivo de la ley 80.",
                 archivo="Ley_80_de_1993.md", pertinencia="secundaria mala"),
        ],
    )
    out = verificar_respaldo(r, indice)
    assert len(out.citas) == 1
    assert len(out.normas_secundarias) == 1, "La secundaria no literal debía descartarse"
    assert out.normas_secundarias[0].verificada is True


# ─── 12. Integración con el formato del skill ────────────────────────────────

def test_numero_de_articulo_normaliza_la_referencia():
    from pipeline.src.bibliotecario import numero_de_articulo
    assert numero_de_articulo("Artículo 5") == "5"
    assert numero_de_articulo("Artículo 5, parágrafo 1") == "5"
    assert numero_de_articulo("Artículo 2.2.1.1.1.3.1") == "2.2.1.1.1.3.1"
    assert numero_de_articulo("artículo 91") == "91"
    assert numero_de_articulo("9") == "9"


def test_envoltorio_respaldos_del_skill_se_desenvuelve():
    """El skill especifica {"respaldos": [...]}; se procesa una por llamada."""
    from pipeline.src.bibliotecario import _desenvolver
    lote = {"respaldos": [{"estado": "sin_respaldo", "motivo": "norma_ausente"}]}
    assert _desenvolver(lote)["motivo"] == "norma_ausente"
    # Objeto desnudo: se acepta igual
    desnudo = {"estado": "respaldada", "citas": []}
    assert _desenvolver(desnudo)["estado"] == "respaldada"


def test_catalogo_no_incluye_texto_de_las_normas(indice):
    from pipeline.src.bibliotecario import _catalogo_para_prompt
    docs = documentos_citables("obra_publica", "educacion", indice)
    cat = _catalogo_para_prompt(docs)
    # El art. 5 de la Ley 1150 son ~7.000 chars; el catálogo entero debe ser
    # mucho menor que la suma de los documentos (1,9 M de chars).
    total_biblioteca = sum(d["chars"] for d in docs)
    assert len(cat) < total_biblioteca / 10, (
        f"El catálogo pesa {len(cat):,} chars sobre {total_biblioteca:,} de "
        "biblioteca: parece llevar texto de las normas."
    )
    assert "de la selección objetiva" not in cat.lower() or len(cat) < 200_000


# ─── 14. [N5] Legibilidad del fragmento ──────────────────────────────────────

def test_detecta_palabras_ilegibles():
    """Mojibake real de Ley_1474_de_2011.md antes de bajarla a no citable."""
    # Mojibake real de Ley_1474_de_2011.md. Conserva una U, así que la señal
    # de "sin vocal" no lo atrapa: lo atrapa la racha de consonantes.
    roto = "XQD¿GXFLDRXQSDWULPRQLR autónomo irrevocable para el manejo"
    assert palabras_ilegibles(roto)
    sin_vocal_sola = "QWLGDGHV territoriales"
    assert palabras_ilegibles(sin_vocal_sola)


def test_no_marca_ilegible_una_sigla_legitima():
    """SMMLV aparece 42 veces en normas sanas: no puede ser un falso positivo."""
    sano = ("El valor del contrato no supera los 1.000 SMMLV ni los "
            "límites del SMLMV fijados por el DGCPTN.")
    assert palabras_ilegibles(sano) == []


# Corrupción sistémica. Ley 1474 medía 0,50 con este detector; la basura
# localizada de la Resolución 336 (dos zonas de OCR al pie) mide 0,0015 y no
# inutiliza la norma: [N5] impide citar esas zonas y el resto sigue sirviendo.
_MAX_ILEGIBLE_DOC = 0.02


def test_ninguna_norma_citable_esta_sistemicamente_corrupta(indice):
    """
    Barrera de regresión: si alguien vuelve a marcar citable una norma con la
    codificación rota, esto falla. La verificación literal no la detectaría.
    """
    sucias = []
    for d in indice["documentos"]:
        if not d.get("citable") or not (d.get("articulos") or []):
            continue
        texto = (_BIB / d["archivo_md"]).read_text("utf-8")
        pct = proporcion_ilegible(texto)
        if pct > _MAX_ILEGIBLE_DOC:
            sucias.append((d["norma"], round(pct, 4)))
    assert not sucias, f"Normas citables con corrupción sistémica: {sucias}"


def test_ley_1474_seria_rechazada_si_la_marcaran_citable(indice):
    """El caso que motivó [N5]: si vuelve a entrar, esto lo detecta."""
    d = next(x for x in indice["documentos"] if x["norma"] == "Ley 1474 de 2011")
    assert d["citable"] is False
    texto = (_BIB / d["archivo_md"]).read_text("utf-8")
    assert proporcion_ilegible(texto) > _MAX_ILEGIBLE_DOC


def test_fragmento_ilegible_no_se_verifica_aunque_sea_literal(tmp_path, monkeypatch):
    """
    El agujero que [N5] cierra: el fragmento ESTÁ en el archivo, así que la
    comparación literal lo aprueba. Debe rechazarse por ilegible.
    """
    import pipeline.src.bibliotecario as B

    md = tmp_path / "ley_rota.md"
    basura = ("## ARTÍCULO 91. Anticipos. En los contratos de obra el contratista "
              "deberá constituir XQD¿GXFLDRXQSDWULPRQLRDXWyQRPR para el manejo.")
    md.write_text(basura, encoding="utf-8")
    monkeypatch.setattr(B, "_BIBLIOTECA", tmp_path)

    idx = {"documentos": [{"norma": "Ley rota", "archivo_md": "ley_rota.md",
                           "citable": True, "articulos": []}]}
    cita = Cita(
        norma="Ley rota", articulo="91",
        fragmento="deberá constituir XQD¿GXFLDRXQSDWULPRQLRDXWyQRPR para el manejo",
        archivo="ley_rota.md", pertinencia="x",
    )
    # El fragmento sí está en el archivo: sin [N5] pasaría como verbatim
    assert cita.fragmento in basura
    assert verificar_cita(cita, "afirmación", idx) is False
    assert cita.verificada is False


# ─── 15. Cargador del ground truth ───────────────────────────────────────────

def test_ground_truth_carga_y_valida(indice):
    casos = cargar_ground_truth(indice=indice)
    assert len(casos) == 18
    assert {c["id"] for c in casos} == {f"E{n:02d}" for n in range(1, 19)}
    for c in casos:
        assert c["estado_esperado"] in {"respaldada", "respaldo_parcial", "sin_respaldo"}


def test_ground_truth_coincide_con_los_casos_de_la_evaluacion(indice):
    """
    [conexión] Las afirmaciones del TSV deben ser las mismas del JSON: el
    evaluador empareja por texto de afirmación, así que una divergencia deja
    casos sin evaluar en silencio.
    """
    casos_json = json.loads(
        (_ROOT / "pipeline/data/eval_bibliotecario.json").read_text("utf-8")
    )["casos"]
    por_id = {c["id"]: " ".join(c["afirmacion"].split()) for c in casos_json}
    for c in cargar_ground_truth(indice=indice):
        assert c["afirmacion"] == por_id[c["id"]], (
            f"{c['id']}: la afirmación del TSV no coincide con la del JSON"
        )


def test_ground_truth_rechaza_norma_no_citable(tmp_path, indice):
    """Si el ground truth apunta a una norma bajada, la corrida no arranca."""
    p = tmp_path / "gt.tsv"
    p.write_text(
        "# comentario\n"
        "id\tafirmacion\testado_esperado\tnorma_esperada\tarticulo_esperado\n"
        "E01\tx\trespaldada\tLey 1474 de 2011\t91\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no está en el índice como citable"):
        cargar_ground_truth(p, indice=indice)


def test_ground_truth_rechaza_sin_respaldo_con_norma(tmp_path, indice):
    p = tmp_path / "gt.tsv"
    p.write_text(
        "id\tafirmacion\testado_esperado\tnorma_esperada\tarticulo_esperado\n"
        "E01\tx\tsin_respaldo\tLey 1150 de 2007\t5\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no puede traer norma_esperada"):
        cargar_ground_truth(p, indice=indice)


def test_ground_truth_rechaza_articulo_inexistente(tmp_path, indice):
    p = tmp_path / "gt.tsv"
    p.write_text(
        "id\tafirmacion\testado_esperado\tnorma_esperada\tarticulo_esperado\n"
        "E01\tx\trespaldada\tLey 1150 de 2007\t9999\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no tiene el artículo"):
        cargar_ground_truth(p, indice=indice)


# ─── 16. Verificación del motivo en la abstención ────────────────────────────

def _sin_respaldo(motivo: str) -> Respaldo:
    return Respaldo(afirmacion="x", estado="sin_respaldo", motivo=motivo)


def test_abstencion_con_motivo_correcto_es_acierto(indice):
    esperado = {"id": "E18", "estado_esperado": "sin_respaldo",
                "motivo_esperado": "afirmacion_no_normativa"}
    clase, _ = clasificar_caso(_sin_respaldo("afirmacion_no_normativa"),
                               esperado, indice)
    assert clase == "acierto"


def test_abstencion_con_motivo_equivocado_no_es_acierto(indice):
    """
    E18: 'esto no es una afirmación jurídica' vs 'no encontré la norma'. Sin
    verificar el motivo, ese caso no evalúa nada: cualquier abstención pasaba.
    """
    esperado = {"id": "E18", "estado_esperado": "sin_respaldo",
                "motivo_esperado": "afirmacion_no_normativa"}
    clase, explicacion = clasificar_caso(_sin_respaldo("norma_ausente"),
                                         esperado, indice)
    assert clase == "acierto_motivo_incorrecto"
    assert "afirmacion_no_normativa" in explicacion


def test_sin_motivo_esperado_no_se_exige(indice):
    """Un caso del ground truth sin motivo declarado no penaliza."""
    esperado = {"id": "X", "estado_esperado": "sin_respaldo", "motivo_esperado": ""}
    clase, _ = clasificar_caso(_sin_respaldo("norma_ausente"), esperado, indice)
    assert clase == "acierto"


def test_motivo_incorrecto_no_cuenta_en_la_tasa_de_acierto(indice):
    resultados = [
        Respaldo(afirmacion="a", estado="sin_respaldo", motivo="norma_ausente"),
        Respaldo(afirmacion="b", estado="sin_respaldo", motivo="norma_ausente"),
    ]
    gt = [
        {"id": "A", "afirmacion": "a", "estado_esperado": "sin_respaldo",
         "motivo_esperado": "norma_ausente"},
        {"id": "B", "afirmacion": "b", "estado_esperado": "sin_respaldo",
         "motivo_esperado": "afirmacion_no_normativa"},
    ]
    rep = evaluar_bibliotecario(resultados, gt, indice)
    assert rep["acierto"] == 1
    assert rep["acierto_motivo_incorrecto"] == 1
    assert rep["tasa_acierto"] == 0.5
    # No es un fallo crítico: la INTEGRIDAD se mantiene. La aprobación ya no
    # depende sólo de eso — con 50% frente a un suelo de 50% no hay utilidad.
    assert rep["integridad"] is True
    assert rep["utilidad"] is False
    assert {d["id"] for d in rep["no_aciertos"]} == {"B"}


# ─── 17. El bloque derogado del art. 5 de la Ley 1150 ────────────────────────

def test_texto_derogado_del_art_5_no_se_puede_citar(indice):
    """
    El agujero que motivó marcar el .md: el texto derogado ('hasta la
    adjudicación') es legible y literal, así que la comparación lo aprobaba.
    Marcado línea por línea, un fragmento limpio ya no coincide.
    """
    doc = next(d for d in indice["documentos"] if d["norma"] == "Ley 1150 de 2007")
    cita = Cita(
        norma="Ley 1150 de 2007", articulo="5",
        fragmento=("podrán ser solicitados por las entidades en cualquier "
                   "momento, hasta la adjudicación"),
        archivo=doc["archivo_md"], pertinencia="E02",
    )
    assert verificar_cita(cita, "E02", indice) is False


def test_texto_vigente_del_art_5_si_se_puede_citar(indice):
    """La marcación no puede haber roto el texto que sí está vigente."""
    doc = next(d for d in indice["documentos"] if d["norma"] == "Ley 1150 de 2007")
    cita = Cita(
        norma="Ley 1150 de 2007", articulo="5",
        fragmento=("deberán ser entregados por los proponentes hasta el término "
                   "de traslado del informe de evaluación"),
        archivo=doc["archivo_md"], pertinencia="E02",
    )
    assert verificar_cita(cita, "E02", indice) is True


def test_los_offsets_de_la_ley_1150_siguen_alineados(indice):
    """
    Marcar el .md movió todos los rangos. Si alguien lo vuelve a editar sin
    re-indexar, los artículos dejan de empezar en su encabezado.
    """
    doc = next(d for d in indice["documentos"] if d["norma"] == "Ley 1150 de 2007")
    texto = (_BIB / doc["archivo_md"]).read_text("utf-8")
    arts = doc["articulos"]
    assert len(arts) == 32
    assert doc["chars"] == len(texto)
    assert arts[-1]["fin"] == len(texto)
    for a in arts:
        assert texto[a["inicio"]:a["fin"]].lstrip().startswith("## "), a["numero"]
    for x, y in zip(arts, arts[1:]):
        assert x["fin"] == y["inicio"]


# ─── 18. Las dos barreras de aprobación ──────────────────────────────────────

def _gt_sintetico() -> list[dict]:
    """3 abstenciones + 1 respaldo. Suelo = 3/4; techo = 3/4."""
    return [
        {"id": "A", "afirmacion": "a", "mide": "bibliotecario",
         "estado_esperado": "sin_respaldo", "motivo_esperado": "norma_ausente"},
        {"id": "B", "afirmacion": "b", "mide": "bibliotecario",
         "estado_esperado": "sin_respaldo", "motivo_esperado": "norma_ausente"},
        {"id": "C", "afirmacion": "c", "mide": "bibliotecario",
         "estado_esperado": "sin_respaldo", "motivo_esperado": "norma_ausente"},
        {"id": "D", "afirmacion": "d", "mide": "bibliotecario",
         "estado_esperado": "respaldada", "norma_esperada": "Ley 1150 de 2007",
         "articulo_esperado": "5"},
    ]


def test_el_suelo_se_calcula_del_ground_truth_no_es_constante(indice):
    """Si cambia el ground truth, cambia el suelo."""
    assert suelo_abstencion(_gt_sintetico(), indice) == 0.75
    reducido = _gt_sintetico()[:1] + _gt_sintetico()[3:]
    assert suelo_abstencion(reducido, indice) == 0.5


def test_el_suelo_del_ground_truth_real(indice):
    """
    Derivado del ground truth, no fijado a mano: cambiar un caso mueve los dos
    puntos de referencia y la prueba debe seguirlos, no caducar.
    """
    gt = cargar_ground_truth(indice=indice)
    abstenciones = [g for g in gt if g["estado_esperado"] == "sin_respaldo"]
    norma_ausente = [g for g in abstenciones
                     if g["motivo_esperado"] == "norma_ausente"]
    # Suelo: sólo acierta los que de verdad son `norma_ausente`
    assert suelo_abstencion(gt, indice) == pytest.approx(
        len(norma_ausente) / len(gt), abs=0.001)
    # Techo de índice: acierta TODAS las abstenciones, con su motivo
    assert techo_indice(gt, indice) == pytest.approx(
        len(abstenciones) / len(gt), abs=0.001)


def test_techo_de_indice_es_mayor_o_igual_que_el_suelo(indice):
    gt = cargar_ground_truth(indice=indice)
    assert techo_indice(gt, indice) >= suelo_abstencion(gt, indice)


def test_abstencion_sistematica_pasa_integridad_pero_no_utilidad(indice):
    """
    El hallazgo que motivó la segunda barrera: no inventar nada no basta.
    """
    gt = cargar_ground_truth(indice=indice)
    sim = [Respaldo(afirmacion=g["afirmacion"], estado="sin_respaldo",
                    motivo="norma_ausente") for g in gt]
    rep = evaluar_bibliotecario(sim, gt, indice)
    assert rep["integridad"] is True
    assert rep["utilidad"] is False
    assert rep["aprobada"] is False
    assert "no miente pero no sirve" in rep["motivo_no_aprobada"]
    assert rep["margen_sobre_suelo"] == 0.0
    assert rep["supera_techo_indice"] is False


def test_una_norma_inventada_invalida_aunque_la_tasa_sea_alta(indice):
    """INTEGRIDAD no se compensa con UTILIDAD."""
    gt = cargar_ground_truth(indice=indice)
    sim = [Respaldo(afirmacion=g["afirmacion"], estado="sin_respaldo",
                    motivo=(g["motivo_esperado"] or "norma_ausente")) for g in gt]
    sim[0] = Respaldo(
        afirmacion=gt[0]["afirmacion"], estado="respaldada",
        citas=[Cita(norma="Ley 9999 de 2099", articulo="1", fragmento="x" * 40,
                    archivo="inventada.md", pertinencia="x", verificada=True)],
    )
    rep = evaluar_bibliotecario(sim, gt, indice)
    assert rep["fallo_critico"] == 1
    assert rep["integridad"] is False
    assert rep["aprobada"] is False


def test_los_casos_de_skill_se_separan_en_el_reporte(indice):
    """
    Los casos `mide=SKILL` (E09, E10) están diseñados para fallar: el error es
    de nuestras skills. Si aparecieran mezclados con los del agente, pierden su
    propósito. E03 fue uno hasta que se corrigió la skill el 2026-09-16.
    """
    gt = cargar_ground_truth(indice=indice)
    sim = [Respaldo(afirmacion=g["afirmacion"], estado="sin_respaldo",
                    motivo="norma_ausente") for g in gt]
    rep = evaluar_bibliotecario(sim, gt, indice)
    ids_skill = {d["id"] for d in rep["no_aciertos_de_nuestras_skills"]}
    ids_agente = {d["id"] for d in rep["no_aciertos_del_agente"]}
    esperados = {g["id"] for g in gt if g["mide"] == "SKILL"}
    assert ids_skill <= esperados
    assert not (ids_skill & ids_agente)
    assert ids_skill | ids_agente == {d["id"] for d in rep["no_aciertos"]}
    # La nota viaja al reporte: es lo que explica de quién es el error
    for d in rep["no_aciertos_de_nuestras_skills"]:
        assert d["nota"], f"{d['id']} sin nota que explique el fallo previsto"


def test_el_reporte_imprime_las_dos_barreras(indice, capsys):
    gt = cargar_ground_truth(indice=indice)
    sim = [Respaldo(afirmacion=g["afirmacion"], estado="sin_respaldo",
                    motivo="norma_ausente") for g in gt]
    imprimir_reporte(evaluar_bibliotecario(sim, gt, indice))
    salida = capsys.readouterr().out
    assert "suelo (abstención sistemática)" in salida
    assert "margen sobre el suelo" in salida
    assert "techo de índice" in salida
    assert "INTEGRIDAD" in salida and "UTILIDAD" in salida
    assert "MIDEN NUESTRAS SKILLS" in salida


# ─── 19. [N6] El aviso de la fuente viaja con la cita ────────────────────────

def test_aviso_de_articulo_con_defecto_conocido(indice):
    """
    El Decreto 1082 trae dos CAPÍTULO 3 bajo el Título 6 y ambos numeran sus
    artículos 2.2.6.3.x. Quien firma el informe tiene que enterarse.
    """
    doc = next(d for d in indice["documentos"] if d["norma"] == "Decreto 1082 de 2015")
    aviso = aviso_de_articulo(doc["archivo_md"], "2.2.6.3.1", indice)
    assert aviso and "2 artículos distintos" in aviso


def test_articulo_sano_no_lleva_aviso(indice):
    doc = next(d for d in indice["documentos"] if d["norma"] == "Decreto 1082 de 2015")
    assert aviso_de_articulo(doc["archivo_md"], "2.2.1.1.2.1.4", indice) is None


def test_la_cita_verificada_arrastra_el_aviso(indice):
    """[N6] No basta con registrarlo: tiene que llegar al resultado."""
    doc = next(d for d in indice["documentos"] if d["norma"] == "Decreto 1082 de 2015")
    texto = texto_articulo(doc["archivo_md"], "2.2.6.3.1", indice) or ""
    fragmento = " ".join(texto.split("\n", 1)[1].split())[:140]
    cita = Cita(norma="Decreto 1082 de 2015", articulo="2.2.6.3.1",
                fragmento=fragmento, archivo=doc["archivo_md"],
                pertinencia="prueba")
    assert verificar_cita(cita, "afirmación", indice) is True
    assert cita.aviso_fuente, "la cita verificada perdió el aviso de la fuente"


def test_el_manual_del_cce_es_doctrina_y_no_se_puede_citar(indice):
    """
    Un manual orienta pero no vincula. Si el bibliotecario lo cita como
    fundamento ante una entidad, esta puede responder que no es norma.
    """
    manual = next((d for d in indice["documentos"]
                   if d.get("tipo") == "doctrina"), None)
    assert manual is not None, "el Manual del CCE no está en el índice"
    assert manual["citable"] is False
    assert manual["norma"] not in {
        d["norma"] for d in documentos_citables("obra_publica", "educacion", indice)
    }


# ─── [D36] El verificador deja de fallar por artefactos nuestros ────────────

def test_el_verificador_limpia_lo_que_pone_el_markdown():
    """
    De 8 citas marcadas «no verificadas», 5 fallaban por markup, marcadores de
    imagen o viñetas que el pliego impreso no tiene. Medido: re-verificando los
    fragmentos crudos, Paicol pasa de 23 a 18 y Ternera de 65 a 31.
    """
    from pipeline.src.verifier import _norm
    fuente = _norm("texto **importante** con ![](_page_46_picture_0.jpeg) imagen\n"
                   "- j. el porcentaje de participación en el valor ejecutado")
    assert "jpeg" not in fuente
    assert "**" not in fuente
    assert fuente.startswith("texto importante con imagen")
    assert "j. el porcentaje" not in fuente, "la viñeta anidada sigue dentro"


def test_la_limpieza_no_se_come_contenido_legitimo():
    """Un año, un decimal o un guion interno no son marcadores."""
    from pipeline.src.verifier import _norm
    assert _norm("2026 fue el año") == "2026 fue el ano"
    assert _norm("el índice 1.85 es suficiente") == "el indice 1.85 es suficiente"
    # el guion INTERNO de una palabra no es un marcador de lista
    assert _norm("sub-contratación permitida") == "sub-contratacion permitida"


def test_se_tolera_un_punto_final_sobrante_y_nada_mas():
    """
    3 de las 8 coincidían en 296 de 297, 248 de 249 y 239 de 240 caracteres, y
    lo único que sobraba era el punto con el que el extractor cierra la frase.

    La tolerancia es EXACTAMENTE esa: una cita que difiera en la última
    palabra tiene que seguir fallando, porque una palabra cambiada al final
    puede invertir el sentido de un requisito.
    """
    from pipeline.src.verifier import _coincide
    fuente = "el proponente debera acreditar su capacidad juridica"
    assert _coincide("el proponente debera acreditar su capacidad juridica.", fuente)
    assert _coincide("el proponente debera acreditar su capacidad juridica", fuente)
    # una palabra distinta al final NO pasa
    assert not _coincide("el proponente debera acreditar su capacidad tecnica", fuente)
    # dos puntos tampoco: la tolerancia no es «los últimos caracteres»
    assert not _coincide("el proponente debera acreditar su capacidad juridica..", fuente)


def test_una_cita_con_elipsis_se_detecta_y_no_pasa_por_literal():
    """
    [The Full-Citation Rule] El informe promete en su sección 2 que la cita es
    textual. Una que omite un pasaje con «...» hace que el documento se
    contradiga a sí mismo. Ternera tiene 9.
    """
    from pipeline.src.verifier import causa_no_verificada, cita_elidida
    assert cita_elidida("cualquier interesado... advierte que se dejó")
    assert cita_elidida("cualquier interesado… advierte")
    assert cita_elidida("el texto [...] continúa")
    assert not cita_elidida("el índice 1.85 y el 0.42 son suficientes")
    # la elisión manda sobre las demás causas: es la que se le señala al cliente
    assert causa_no_verificada("x ≥ y ... z", parcial=True) == "cita_elidida"


def test_las_cuatro_causas_se_separan_por_a_quien_alarman():
    from pipeline.src.verifier import causa_no_verificada
    assert causa_no_verificada("valor ≥ 100") == "simbolo_transformado"
    assert causa_no_verificada("texto normal", parcial=True) == "artefacto_de_extraccion"
    assert causa_no_verificada("texto normal", parcial=False) == "texto_ausente"
