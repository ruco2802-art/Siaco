# -*- coding: utf-8 -*-
"""
Desambiguación de números de artículo repetidos.

El caso que lo motivó: `Ley_1882_de_2018.md` tiene dos encabezados
`ARTÍCULO 4°`. El real adiciona el parágrafo 7 al art. 2 de la Ley 1150
(documentos tipo); el otro es el art. 4 de la Ley 1228 de 2008, transcrito
dentro del art. 17. La regla anterior —conservar la ocurrencia con más
texto— elegía el segundo, y el índice devolvía un texto sobre fajas viales
cuando se pedía la obligatoriedad de los documentos tipo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.src.indexador import (  # noqa: E402
    es_transcripcion,
    formatear_avisos,
    indexar_articulos,
)

_BIB = _ROOT / "biblioteca_normativa"

pytestmark = pytest.mark.skipif(
    not (_BIB / "indice.json").exists(),
    reason="biblioteca_normativa/indice.json no disponible",
)


@pytest.fixture(scope="module")
def indice():
    return json.loads((_BIB / "indice.json").read_text("utf-8"))


def _doc(indice, norma):
    return next(d for d in indice["documentos"] if d["norma"] == norma)


# ─── [X1] Transcripciones ────────────────────────────────────────────────────

def test_transcripcion_se_detecta_por_la_linea_inmediata():
    md = ("## ARTÍCULO 17. Modifíquese el artículo 4° de la Ley 1228, el cual "
          "quedará así:\n\n## ARTÍCULO 4°. No procederá indemnización.\n")
    assert es_transcripcion(md, md.index("## ARTÍCULO 4°"))


def test_un_articulo_lejos_del_anuncio_no_es_transcripcion():
    """
    El bug de la primera versión: con una ventana de caracteres, el art. 7 de
    la Ley 1882 caía porque alcanzaba el "quedará así:" del art. 6.
    """
    md = ("## ARTÍCULO 6°. Adiciónese un parágrafo, el cual quedará así:\n"
          "(...)\n\n**PARÁGRAFO.** No es obligatorio contar con disponibilidad.\n"
          "\n## ARTÍCULO 7°. Modifíquese el artículo 33 de la Ley 1508.\n")
    assert not es_transcripcion(md, md.index("## ARTÍCULO 7°"))


def test_cabecera_propia_con_modificado_por_no_es_transcripcion():
    """Ley 1150 art. 6 anuncia su propia modificación y sigue siendo suyo."""
    md = ("Texto anterior sin dos puntos.\n\n"
          "## ARTÍCULO 6°. Modificado por el Decreto 19 de 2012, artículo 221.\n")
    assert not es_transcripcion(md, md.index("## ARTÍCULO 6°"))


def test_la_transcripcion_no_gana_aunque_sea_mas_larga():
    md = ("## ARTÍCULO 4°. Adiciónese el parágrafo.\nCorto.\n\n"
          "## ARTÍCULO 17. Modifíquese el artículo 4° de la Ley 1228, "
          "el cual quedará así:\n\n"
          "## ARTÍCULO 4°. No procederá indemnización. " + "x" * 900 + "\n")
    arts, _ = indexar_articulos(md)
    a4 = next(a for a in arts if a["numero"] == "4")
    assert "Adiciónese el parágrafo" in md[a4["inicio"]:a4["fin"]]
    assert a4["ocurrencias_descartadas"][0]["motivo"] == "transcripcion"


# ─── [X2] Posición, no longitud ──────────────────────────────────────────────

def test_entre_ocurrencias_propias_gana_la_mas_tardia():
    """Índice al principio, articulado después."""
    md = ("## ARTÍCULO 5. Selección objetiva\n\n"
          "## ARTÍCULO 5. Selección objetiva. Es objetiva la selección en la "
          "cual la escogencia se haga al ofrecimiento más favorable.\n")
    arts, _ = indexar_articulos(md)
    a5 = next(a for a in arts if a["numero"] == "5")
    assert "Es objetiva la selección" in md[a5["inicio"]:a5["fin"]]
    assert a5["ocurrencias_descartadas"][0]["motivo"] == "ocurrencia_previa"


# ─── [X3] Divergencia ────────────────────────────────────────────────────────

def test_dos_articulos_distintos_con_el_mismo_numero_generan_aviso():
    md = ("## ARTÍCULO 9. Apoyo para la priorización de proyectos de inversión "
          "pública en las entidades territoriales del orden departamental.\n\n"
          "## ARTÍCULO 9. Banco Nacional de Programas y Proyectos. El Banco "
          "administra el registro de los proyectos viables.\n")
    _, avisos = indexar_articulos(md)
    assert any(a["tipo"] == "divergencia_alta" and a["numero"] == "9"
               for a in avisos)


def test_indice_y_cuerpo_del_mismo_articulo_no_generan_aviso():
    cuerpo = ("Es objetiva la selección en la cual la escogencia se haga al "
              "ofrecimiento más favorable a la entidad y a los fines que busca.")
    md = (f"## ARTÍCULO 5. Selección objetiva. {cuerpo}\n\n"
          f"## ARTÍCULO 5. Selección objetiva. {cuerpo} Y algo más.\n")
    _, avisos = indexar_articulos(md)
    assert not avisos


def test_formatear_avisos_es_vacio_sin_avisos():
    assert formatear_avisos("Ley X", []) == ""


# ─── Sobre la biblioteca real ────────────────────────────────────────────────

def test_ley_1882_art_4_es_el_de_documentos_tipo(indice):
    """D15: el caso concreto que la regla de longitud fallaba."""
    doc = _doc(indice, "Ley 1882 de 2018")
    texto = (_BIB / doc["archivo_md"]).read_text("utf-8")
    a4 = next(a for a in doc["articulos"] if a["numero"] == "4")
    cuerpo = texto[a4["inicio"]:a4["fin"]]
    assert "documentos tipo" in cuerpo.lower()
    assert "no procederá indemnización" not in cuerpo.lower()


def test_ley_1882_no_tiene_articulos_de_otras_leyes(indice):
    """Los arts. 25, 27, 32 y 33 transcritos son de las leyes 1508 y 1682."""
    doc = _doc(indice, "Ley 1882 de 2018")
    numeros = {a["numero"] for a in doc["articulos"]}
    assert numeros == {str(n) for n in range(1, 22)}


def test_toda_ocurrencia_descartada_queda_registrada(indice):
    """Auditar la decisión sin volver a abrir el PDF."""
    con_descartes = [
        (d["norma"], a["numero"], a["ocurrencias_descartadas"])
        for d in indice["documentos"]
        for a in d.get("articulos") or []
        if a.get("ocurrencias_descartadas")
    ]
    assert con_descartes, "Ninguna ocurrencia descartada: ¿se perdió el campo?"
    for norma, numero, descartes in con_descartes:
        for o in descartes:
            assert o["extracto"], f"{norma} art. {numero}: descarte sin extracto"
            assert o["motivo"] in {"transcripcion", "ocurrencia_previa"}
            assert isinstance(o["inicio"], int)


def test_reindexar_es_idempotente(indice):
    """Correr el indexador otra vez debe dar exactamente lo mismo."""
    for d in indice["documentos"]:
        if not d.get("archivo_md") or not (_BIB / d["archivo_md"]).exists():
            continue
        arts, _ = indexar_articulos(_BIB / d["archivo_md"])
        guardados = d.get("articulos") or []
        assert len(arts) == len(guardados), d["norma"]
        for nuevo, viejo in zip(arts, guardados):
            assert nuevo["numero"] == viejo["numero"], d["norma"]
            assert nuevo["inicio"] == viejo["inicio"], d["norma"]


def test_los_avisos_quedan_en_el_indice(indice):
    """El aviso que habría detectado la Ley 1882 el primer día."""
    doc = _doc(indice, "Ley 1882 de 2018")
    tipos = {a["tipo"] for a in doc.get("avisos_indexacion") or []}
    assert "solo_transcripciones" in tipos
