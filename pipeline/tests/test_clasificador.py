# -*- coding: utf-8 -*-
"""
tests/test_clasificador.py — Tests offline del clasificador y consolidador.

Sin API. Todos los fixtures son Requisito con fuente_numeral conocida.
"""
from __future__ import annotations
import pytest
from src.extractor import Requisito
from src.clasificador import (
    clasificar_requisito,
    consolidar,
    deduplicar,
    descartar_no_requisitos,
    fusionar_fragmentos,
    _es_no_requisito,
    _extraer_prefijo_numeral,
    _tiene_plazo,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _req(numeral: str, nombre: str, literal: str = "texto de prueba",
         categoria: str = "juridico") -> Requisito:
    return Requisito(
        nombre=nombre, categoria=categoria,
        exigido_literal=literal, fuente_numeral=numeral,
    )


# ─── Tests de extraer_prefijo_numeral ─────────────────────────────────────────

class TestExtraerPrefijo:
    def test_numeral_simple(self):
        assert _extraer_prefijo_numeral("3.5.1. CARACTERÍSTICAS") == "3.5.1"

    def test_numeral_con_punto_final(self):
        assert _extraer_prefijo_numeral("3.2 CAPACIDAD JURÍDICA") == "3.2"

    def test_letra_a(self):
        assert _extraer_prefijo_numeral("A. Capacidad de organización") == "A."

    def test_letra_b(self):
        assert _extraer_prefijo_numeral("B. Conversión a SMMLV") == "B."

    def test_capitulo_texto(self):
        # Capítulo sin número → prefijo vacío
        assert _extraer_prefijo_numeral("CAPÍTULO III REQUISITOS") == ""

    def test_numeral_con_punto_extra(self):
        assert _extraer_prefijo_numeral("7.1.GARANTÍA") == "7.1"


# ─── Tests de clasificar_requisito ────────────────────────────────────────────

class TestClasificarHabilitante:
    def test_numeral_3_es_habilitante(self):
        r = _req("3.2 CAPACIDAD JURÍDICA", "Capacidad jurídica")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "habilitante"
        assert clf.evidencia == "capitulo_habilitantes"

    def test_numeral_3_5_es_habilitante(self):
        r = _req("3.5.1. CARACTERÍSTICAS DE LOS CONTRATOS", "Experiencia")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "habilitante"

    def test_numeral_a_es_habilitante(self):
        r = _req("A. Capacidad de organización (CO):", "CO Ingresos")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "habilitante"

    def test_numeral_c_es_habilitante(self):
        r = _req("C. Capacidad financiera (CF):", "IDL CRP")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "habilitante"


class TestClasificarLimitacion:
    def test_2_5_es_habilitante_limitacion(self):
        r = _req("2.5 LIMITACIÓN A MIPYME", "Limitación Mipyme Paicol")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "habilitante"
        assert clf.evidencia == "limitacion_participacion"

    def test_1_14_conflicto_interes(self):
        r = _req("1.14 CONFLICTO DE INTERÉS", "Ausencia de conflicto de interés")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "habilitante"
        assert clf.evidencia == "limitacion_participacion"

    def test_keyword_mipyme_en_literal(self):
        r = _req("2.1 CARTA", "Condición Mipyme",
                 "Limitación a Mipyme colombianas domiciliadas en el municipio")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "habilitante"
        assert clf.evidencia == "limitacion_participacion"

    def test_keyword_inhabilidades_en_nombre(self):
        r = _req("1.15 CAUSALES", "Inhabilidades e incompatibilidades")
        clf = clasificar_requisito(r)
        # 1.15 → procedimental por numeral exacto (tiene precedencia)
        assert clf.criticidad == "procedimental"
        assert clf.evidencia == "causal_rechazo"


class TestClasificarProcedimental:
    def test_numeral_2_es_procedimental(self):
        r = _req("2.1 CARTA DE PRESENTACIÓN", "Carta de presentación")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "procedimental"
        assert clf.evidencia == "capitulo_presentacion"

    def test_numeral_1_15_causal_rechazo(self):
        r = _req("1.15 CAUSALES DE RECHAZO", "No presentación múltiple")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "procedimental"
        assert clf.evidencia == "causal_rechazo"

    def test_numeral_7_es_procedimental(self):
        r = _req("7.1.GARANTÍA DE SERIEDAD", "Garantía de seriedad")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "procedimental"

    def test_numeral_8_es_procedimental(self):
        r = _req("8.1. INFORMACIÓN PARA EL CONTROL", "Hojas de vida personal")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "procedimental"
        assert clf.evidencia == "capitulo_presentacion"


class TestClasificarPuntaje:
    def test_numeral_4_es_puntaje(self):
        r = _req("4.2.4.1. CRITERIOS AMBIENTALES", "Criterios ambientales")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "puntaje"
        assert clf.evidencia == "capitulo_puntaje"

    def test_numeral_4_3_puntaje(self):
        r = _req("4.3.1.1 ACREDITACIÓN DEL PUNTAJE", "Servicios nacionales puntaje")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "puntaje"


class TestClasificarIndeterminado:
    def test_numeral_1_13_moneda(self):
        r = _req("1.13 MONEDA", "Presentación en pesos colombianos")
        clf = clasificar_requisito(r)
        assert clf.criticidad == "indeterminado"


# ─── Tests de tiene_plazo ─────────────────────────────────────────────────────

class TestTienePlazo:
    def test_rup_en_firme(self):
        r = _req("3.5 EXPERIENCIA", "RUP en firme al cierre del proceso",
                 "El RUP debe estar en firme antes del cierre.")
        assert _tiene_plazo(r)

    def test_30_dias_calendario(self):
        r = _req("3.3.2", "Cámara de comercio",
                 "Vigencia máxima 30 días calendario antes del cierre.")
        assert _tiene_plazo(r)

    def test_sin_plazo(self):
        r = _req("3.2", "Capacidad jurídica",
                 "El proponente debe acreditar capacidad jurídica.")
        assert not _tiene_plazo(r)


# ─── Tests de _es_no_requisito ────────────────────────────────────────────────

class TestEsNoRequisito:
    def test_cronograma_es_no_req(self):
        r = _req("1.7.CRONOGRAMA DEL PROCESO", "Idioma de documentos y comunicaciones")
        es, motivo = _es_no_requisito(r)
        assert es
        assert "temporal" in motivo

    def test_ajuste_smmlv_es_no_req(self):
        r = _req("B. Conversión a SMMLV", "Ajuste de valores en SMMLV")
        es, motivo = _es_no_requisito(r)
        assert es
        assert "calculo" in motivo

    def test_orden_prevalencia_es_no_req(self):
        r = _req("3.5.5. DOCUMENTOS VÁLIDOS", "Orden de prevalencia de documentos")
        es, motivo = _es_no_requisito(r)
        assert es
        assert "interpretativa" in motivo

    def test_formato_es_no_req(self):
        r = _req("CAPÍTULO III", "Formato 3 Experiencia")
        es, motivo = _es_no_requisito(r)
        assert es
        assert "documento" in motivo

    def test_requisito_normal_no_es_no_req(self):
        r = _req("3.2 CAPACIDAD", "Capacidad jurídica para celebrar contratos")
        es, _ = _es_no_requisito(r)
        assert not es


# ─── Tests de deduplicar ──────────────────────────────────────────────────────

class TestDeduplicar:
    def test_elimina_duplicado_exacto(self):
        reqs = [
            _req("3.9.1 NACIONALES", "RUP vigente y en firme antes del cierre"),
            _req("3.5 EXPERIENCIA",  "RUP vigente y en firme antes del cierre"),
        ]
        resultado, n_elim = deduplicar(reqs)
        assert len(resultado) == 1
        assert n_elim == 1

    def test_conserva_fuentes(self):
        reqs = [
            _req("3.9.1 NACIONALES", "RUP vigente y en firme"),
            _req("3.5 EXPERIENCIA",  "RUP vigente y en firme"),
        ]
        resultado, _ = deduplicar(reqs)
        assert len(resultado[0].numerales_fuentes) == 2

    def test_no_elimina_distintos(self):
        reqs = [
            _req("3.2", "Capacidad jurídica"),
            _req("3.5", "Experiencia mínima"),
        ]
        resultado, n_elim = deduplicar(reqs)
        assert len(resultado) == 2
        assert n_elim == 0


# ─── Tests de fusionar_fragmentos ────────────────────────────────────────────

class TestFusionarFragmentos:
    def test_fusiona_mismo_grupo(self):
        """
        Fallback por prefijo [B11]: nombres que el catálogo de objetos NO
        reconoce se agrupan por `_CLAVE_FUSION`. Se usa un término inventado
        ('Zeta') para aislar esta ruta — con nombres del dominio real la clave
        primaria la da el catálogo, que es lo que prueba test_catalogo.py.
        """
        reqs = [
            _req("3.5.1. CARACTERÍSTICAS", "Zeta habilitante primera", categoria="experiencia"),
            _req("3.5.1. CARACTERÍSTICAS", "Zeta habilitante segunda", categoria="experiencia"),
            _req("3.5.1. CARACTERÍSTICAS", "Zeta habilitante tercera", categoria="experiencia"),
        ]
        resultado, grupos = fusionar_fragmentos(reqs)
        exp_resultados = [r for r in resultado if r.fuente_numeral.startswith("3.5.1")]
        assert len(exp_resultados) == 1
        assert len(grupos) >= 1
        assert grupos[0]["n_originales"] == 3

    def test_preserva_fuentes(self):
        reqs = [
            _req("3.5.8. RELACIÓN PRESUPUESTO 1-2 CONTRATOS", "Valor mínimo 1-2 contratos", categoria="experiencia"),
            _req("3.5.8. RELACIÓN PRESUPUESTO 3-4 CONTRATOS", "Valor mínimo 3-4 contratos", categoria="experiencia"),
        ]
        resultado, _ = fusionar_fragmentos(reqs)
        fus = [r for r in resultado if "3.5.8" in r.fuente_numeral]
        assert len(fus) == 1
        assert len(fus[0].numerales_fuentes) == 2

    def test_no_fusiona_distintos_grupos(self):
        reqs = [
            _req("3.5.1. CARACTERÍSTICAS", "Experiencia contratos", categoria="experiencia"),
            _req("3.5.8. RELACIÓN", "Relación vs presupuesto", categoria="experiencia"),
        ]
        resultado, _ = fusionar_fragmentos(reqs)
        # Ambos grupos distintos → 2 requisitos
        assert len(resultado) == 2


# ─── Tests de descartar_no_requisitos ────────────────────────────────────────

class TestDescartarNoRequisitos:
    def test_descarta_smmlv(self):
        reqs = [
            _req("B. Conversión a Salarios", "Conversión de valores a SMMLV"),
            _req("3.2 CAPACIDAD", "Capacidad jurídica"),
        ]
        validos, descartados = descartar_no_requisitos(reqs)
        assert len(validos) == 1
        assert len(descartados) == 1

    def test_descartados_reportados(self):
        reqs = [_req("1.7.CRONOGRAMA", "Idioma de documentos")]
        _, descartados = descartar_no_requisitos(reqs)
        assert len(descartados) == 1
        assert "numeral" in descartados[0]
        assert "motivo" in descartados[0]

    def test_nada_descartado_en_capitulo_3(self):
        reqs = [
            _req("3.2 CAPACIDAD", "Capacidad jurídica"),
            _req("3.7 CAPITAL", "Capital de trabajo mínimo", categoria="financiero"),
        ]
        validos, descartados = descartar_no_requisitos(reqs)
        assert len(validos) == 2
        assert len(descartados) == 0


# ─── Test integración: consolidar ────────────────────────────────────────────

class TestConsolidar:
    def test_clasifica_y_reduce(self):
        reqs = [
            _req("3.2 CAPACIDAD JURÍDICA", "Capacidad jurídica"),
            _req("4.2.5 CRITERIO SOCIAL",  "Criterio social", categoria="tecnico"),
            _req("2.1 CARTA",              "Carta de presentación"),
            _req("1.7.CRONOGRAMA",         "Idioma de documentos"),  # no-req
            _req("B. Conversión",          "Ajuste SMMLV"),          # no-req
        ]
        res = consolidar(reqs)
        assert res.antes_total == 5
        # Al menos 1 descartado (no-req)
        assert res.despues_descarte < res.antes_total
        # Habilitante y puntaje clasificados
        crits = {r.criticidad for r in res.requisitos}
        assert "habilitante" in crits
        assert "puntaje" in crits

    def test_invariante_c1_descartados_registrados(self):
        reqs = [
            _req("1.7.CRONOGRAMA", "Idioma de documentos"),
            _req("B. Conversión", "SMMLV ajuste"),
        ]
        res = consolidar(reqs)
        # [C1] Todos los no-requisitos aparecen en descartados
        assert len(res.descartados) == len(reqs)
        assert all("motivo" in d for d in res.descartados)

    def test_invariante_c3_indeterminados_preservados(self):
        reqs = [_req("[Opción 2.", "Porcentaje empleados")]
        res = consolidar(reqs)
        indet = [r for r in res.requisitos if r.criticidad == "indeterminado"]
        assert len(indet) == 1  # [C3] no se descarta
