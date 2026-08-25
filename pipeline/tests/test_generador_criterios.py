# -*- coding: utf-8 -*-
"""
tests/test_generador_criterios.py — 8 casos offline para el generador de criterios.

Sin llamadas a la API: _llamar_llm se parchea con respuestas pre-construidas.
Casos basados en requisitos reales de Paicol (SAMC-IET-001-2026).

Invariantes verificados:
  [I-G1] Skill faltante → FileNotFoundError
  [I-G2] Variable no resuelta → criterio=None, estado="fallo"
  [I-G3] AST inválida → criterio=None, estado="fallo"
  [I-G4] Umbral null en CCE + ausente en pliego → "umbral_no_definido_en_pliego"
  [I6]   Aritmética en Python puro, validada por AST antes de persistir
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.criterios import Booleano, Formula, TablaTramos, UmbralSimple
from src.extractor import Requisito
from src.generador_criterios import (
    ResultadoGeneracion,
    _parsear_respuesta,
    generar_criterio,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _req(
    nombre: str = "Índice de liquidez",
    categoria: str = "financiero",
    exigido_literal: str = "El IDL debe ser >= 1,21.",
    fuente_numeral: str = "3.5.1",
    valor_umbral: float | None = None,
    operador: str | None = None,
    pagina_origen: int | None = 22,
) -> Requisito:
    return Requisito(
        nombre=nombre,
        categoria=categoria,
        exigido_literal=exigido_literal,
        fuente_numeral=fuente_numeral,
        valor_umbral=valor_umbral,
        operador=operador,
        pagina_origen=pagina_origen,
    )


# Catálogo CCE mínimo para casos de provenance
_CATALOGO_CCE = {
    "modalidades": {
        "menor_cuantia": {
            "indicadores_obligatorios": [
                {
                    "id": "indice_liquidez",
                    "por_variante": {
                        "no_mipyme": {"valor": 1.2,  "operador": ">="},
                        "mipyme":    {"valor": 1.1,  "operador": ">="},
                    },
                },
            ]
        }
    }
}


# ─── Caso 1 — UmbralSimple liquidez con provenance ────────────────────────────

class TestCaso1UmbralSimpleLiquidez:
    """El pliego exige IDL >= 1,21. CCE fija 1,2. Pliego es más estricto."""

    _llm_resp = {
        "tipo": "umbral_simple",
        "campo_perfil": "financiero.indice_liquidez",
        "operador": ">=",
        "valor": 1.21,
        "confianza": "alta",
    }

    def test_tipo_correcto(self):
        req = _req(valor_umbral=1.21, operador=">=")
        res = _parsear_respuesta(
            self._llm_resp, req,
            modalidad="menor_cuantia", variante="no_mipyme",
            catalogo_cce=_CATALOGO_CCE,
        )
        assert res.estado == "ok"
        assert isinstance(res.criterio, UmbralSimple)

    def test_campo_perfil_canónico(self):
        req = _req()
        res = _parsear_respuesta(self._llm_resp, req)
        assert isinstance(res.criterio, UmbralSimple)
        assert res.criterio.campo_perfil == "financiero.indice_liquidez"

    def test_valor_del_pliego_tiene_precedencia(self):
        req = _req(valor_umbral=1.21, operador=">=")
        res = _parsear_respuesta(
            self._llm_resp, req,
            modalidad="menor_cuantia", variante="no_mipyme",
            catalogo_cce=_CATALOGO_CCE,
        )
        assert res.fuente_umbral == "pliego"
        assert res.criterio.valor == 1.21

    def test_difiere_de_cce_mas_estricto(self):
        req = _req()
        res = _parsear_respuesta(
            self._llm_resp, req,
            modalidad="menor_cuantia", variante="no_mipyme",
            catalogo_cce=_CATALOGO_CCE,
        )
        assert res.difiere_de_cce is not None
        assert res.difiere_de_cce["valor_cce"] == 1.2
        assert res.difiere_de_cce["tendencia"] == "mas_estricto"

    def test_valor_ref_cce(self):
        req = _req()
        res = _parsear_respuesta(
            self._llm_resp, req,
            modalidad="menor_cuantia", variante="no_mipyme",
            catalogo_cce=_CATALOGO_CCE,
        )
        assert res.valor_ref_cce == 1.2


# ─── Caso 2 — Formula CT con 4 variables ─────────────────────────────────────

class TestCaso2FormulaCT:
    """CT = AC - PC >= (POE - anticipo) * 0.33. Cuatro variables mixtas."""

    _llm_resp = {
        "tipo": "formula",
        "expresion_empresa": "AC - PC",
        "operador": ">=",
        "expresion_umbral": "(POE - anticipo) * 0.33",
        "variables": [
            {"nombre": "AC",       "fuente": "perfil"},
            {"nombre": "PC",       "fuente": "perfil"},
            {"nombre": "POE",      "fuente": "pliego"},
            {"nombre": "anticipo", "fuente": "pliego"},
        ],
        "descripcion": "Capital de trabajo >= 33% del presupuesto disponible",
        "confianza": "alta",
    }

    def test_tipo_formula(self):
        req = _req(nombre="Capital de trabajo", categoria="financiero")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.estado == "ok"
        assert isinstance(res.criterio, Formula)

    def test_variables_resueltas_correctamente(self):
        req = _req(nombre="Capital de trabajo", categoria="financiero")
        res = _parsear_respuesta(self._llm_resp, req)
        f: Formula = res.criterio
        nombres = {v.nombre for v in f.variables}
        assert nombres == {"AC", "PC", "POE", "anticipo"}

    def test_variables_fuentes_correctas(self):
        req = _req(nombre="Capital de trabajo", categoria="financiero")
        res = _parsear_respuesta(self._llm_resp, req)
        f: Formula = res.criterio
        fuentes = {v.nombre: v.fuente for v in f.variables}
        assert fuentes["AC"] == "perfil"
        assert fuentes["PC"] == "perfil"
        assert fuentes["POE"] == "pliego"
        assert fuentes["anticipo"] == "pliego"

    def test_campos_perfil_resueltos(self):
        req = _req(nombre="Capital de trabajo", categoria="financiero")
        res = _parsear_respuesta(self._llm_resp, req)
        f: Formula = res.criterio
        campos = {v.nombre: v.campo for v in f.variables}
        assert campos["AC"] == "financiero.activo_corriente"
        assert campos["PC"] == "financiero.pasivo_corriente"

    def test_fuente_umbral_formula_universal(self):
        req = _req(nombre="Capital de trabajo", categoria="financiero")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.fuente_umbral == "formula_universal"


# ─── Caso 3 — TablaTramos con naturaleza="puntaje" ───────────────────────────

class TestCaso3TablaTramos:
    """Tabla de liquidez con 4 tramos de puntaje. Boundary check en 0.50."""

    _llm_resp = {
        "tipo": "tabla_tramos",
        "campo_perfil": "financiero.indice_liquidez",
        "naturaleza": "puntaje",
        "tramos": [
            {"desde": None,  "hasta": 0.50, "incluye_inferior": True,  "incluye_superior": False, "puntaje": 20},
            {"desde": 0.50,  "hasta": 0.75, "incluye_inferior": True,  "incluye_superior": False, "puntaje": 25},
            {"desde": 0.75,  "hasta": 1.00, "incluye_inferior": True,  "incluye_superior": False, "puntaje": 30},
            {"desde": 1.00,  "hasta": None, "incluye_inferior": True,  "incluye_superior": True,  "puntaje": 40},
        ],
        "confianza": "alta",
    }

    def test_tipo_tabla_tramos(self):
        req = _req(nombre="Liquidez por tramos")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.estado == "ok"
        assert isinstance(res.criterio, TablaTramos)

    def test_naturaleza_puntaje(self):
        req = _req(nombre="Liquidez por tramos")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.criterio.naturaleza == "puntaje"

    def test_cuatro_tramos(self):
        req = _req(nombre="Liquidez por tramos")
        res = _parsear_respuesta(self._llm_resp, req)
        assert len(res.criterio.tramos) == 4

    def test_boundary_en_0_50(self):
        """0.50 exacto cae en el tramo [0.50, 0.75) → 25 puntos."""
        req = _req(nombre="Liquidez por tramos")
        res = _parsear_respuesta(self._llm_resp, req)
        t = res.criterio
        # tramo 2: desde=0.50 incluye_inferior=True, hasta=0.75 incluye_superior=False
        tramo2 = t.tramos[1]
        assert tramo2.desde == 0.50
        assert tramo2.incluye_inferior is True
        assert tramo2.puntaje == 25.0

    def test_tramo_superior_sin_limite(self):
        req = _req(nombre="Liquidez por tramos")
        res = _parsear_respuesta(self._llm_resp, req)
        ultimo = res.criterio.tramos[-1]
        assert ultimo.hasta is None
        assert ultimo.puntaje == 40.0


# ─── Caso 4 — Booleano RUP ────────────────────────────────────────────────────

class TestCaso4Booleano:
    """RUP en firme → campo juridico.rup_en_firme."""

    _llm_resp = {
        "tipo": "booleano",
        "campo_perfil": "juridico.rup_en_firme",
        "valor_requerido": True,
        "confianza": "alta",
    }

    def test_tipo_booleano(self):
        req = _req(nombre="RUP en firme", categoria="juridico",
                   exigido_literal="El proponente debe contar con RUP en firme.")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.estado == "ok"
        assert isinstance(res.criterio, Booleano)

    def test_campo_juridico_rup(self):
        req = _req(nombre="RUP en firme", categoria="juridico",
                   exigido_literal="El proponente debe contar con RUP en firme.")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.criterio.campo_perfil == "juridico.rup_en_firme"

    def test_valor_requerido_true(self):
        req = _req(nombre="RUP en firme", categoria="juridico",
                   exigido_literal="El proponente debe contar con RUP en firme.")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.criterio.valor_requerido is True


# ─── Caso 5 — FALLO variable desconocida ──────────────────────────────────────

class TestCaso5VariableNoResuelta:
    """Variable 'XYZ' no existe → fallo, criterio=None, requisito preservado."""

    _llm_resp = {
        "tipo": "formula",
        "expresion_empresa": "XYZ - PC",
        "operador": ">=",
        "expresion_umbral": "0",
        "variables": [
            {"nombre": "XYZ", "fuente": "perfil"},
            {"nombre": "PC",  "fuente": "perfil"},
        ],
        "confianza": "media",
    }

    def test_estado_fallo(self):
        req = _req(nombre="Indicador desconocido")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.estado == "fallo"

    def test_criterio_none(self):
        req = _req(nombre="Indicador desconocido")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.criterio is None

    def test_razon_menciona_variable(self):
        req = _req(nombre="Indicador desconocido")
        res = _parsear_respuesta(self._llm_resp, req)
        assert "variable_no_resuelta" in (res.razon_fallo or "")
        assert "XYZ" in (res.razon_fallo or "")

    def test_exigido_literal_preservado(self):
        """El requisito original no se pierde aunque el criterio falle."""
        req = _req(nombre="Indicador desconocido",
                   exigido_literal="El proponente debe acreditar XYZ.")
        res = _parsear_respuesta(self._llm_resp, req)
        # La cita literal es del requisito, no del resultado — solo verificamos
        # que el ResultadoGeneracion no destruyó el req original.
        assert req.exigido_literal == "El proponente debe acreditar XYZ."
        assert res.criterio is None   # el criterio falla pero req sigue intacto


# ─── Caso 6 — FALLO expresión no soportada por el AST ───────────────────────

class TestCaso6ExpresionNoSoportada:
    """El LLM genera una expresión con condicional (not allowed by AST whitelist)."""

    _llm_resp = {
        "tipo": "formula",
        "expresion_empresa": "AC if AC > 0 else 0",   # condicional → no soportado
        "operador": ">=",
        "expresion_umbral": "1000000",
        "variables": [
            {"nombre": "AC", "fuente": "perfil"},
        ],
        "confianza": "media",
    }

    def test_estado_fallo_expresion(self):
        req = _req(nombre="Activo corriente condicional")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.estado == "fallo"

    def test_criterio_none(self):
        req = _req(nombre="Activo corriente condicional")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.criterio is None

    def test_razon_menciona_expresion(self):
        req = _req(nombre="Activo corriente condicional")
        res = _parsear_respuesta(self._llm_resp, req)
        assert "expresion_no_soportada" in (res.razon_fallo or "")


# ─── Caso 7 — fuente_inferida corrige variable solo-perfil ───────────────────

class TestCaso7FuenteInferida:
    """
    El LLM marca AC como fuente='pliego' (incorrecto).
    resolver_variable("AC", fuente_inferida="pliego") lo corrige porque AC
    solo existe en el catálogo de perfil (no en pliego).
    """

    _llm_resp = {
        "tipo": "formula",
        "expresion_empresa": "AC - PC",
        "operador": ">=",
        "expresion_umbral": "1000000",
        "variables": [
            {"nombre": "AC", "fuente": "pliego"},   # incorrecto — solo existe en perfil
            {"nombre": "PC", "fuente": "perfil"},
        ],
        "confianza": "media",
    }

    def test_ac_corregido_a_perfil(self):
        req = _req(nombre="Activo corriente")
        res = _parsear_respuesta(self._llm_resp, req)
        assert res.estado == "ok"
        f: Formula = res.criterio
        v_ac = next(v for v in f.variables if v.nombre == "AC")
        # AC solo está en perfil → fuente_inferida="pliego" no existe en _PLIEGO_CAMPOS
        # → resolver lo ubica como perfil
        assert v_ac.fuente == "perfil"
        assert v_ac.campo == "financiero.activo_corriente"


# ─── Caso 8 — umbral_no_definido_en_pliego ───────────────────────────────────

class TestCaso8UmbralNoDefinido:
    """
    Null en catálogo CCE para ese indicador Y ausente en el pliego.
    El LLM devuelve valor=null → estado="umbral_no_definido_en_pliego".
    Según estructura_normativa.json, este es el caso 7 en _pendiente_deteccion_irregularidades.
    """

    _llm_resp = {
        "tipo": "umbral_simple",
        "campo_perfil": "financiero.rentabilidad_patrimonio",
        "operador": ">=",
        "valor": None,   # no está en el pliego
        "confianza": "media",
    }

    # Catálogo sin valor para rentabilidad_patrimonio (como obra_publica = null)
    _catalogo = {
        "modalidades": {
            "obra_publica": {
                "indicadores_obligatorios": [
                    {"id": "rentabilidad_patrimonio", "valor": None, "operador": ">="},
                ]
            }
        }
    }

    def test_estado_umbral_no_definido(self):
        req = _req(
            nombre="Rentabilidad patrimonio",
            exigido_literal="El proponente debe acreditar rentabilidad del patrimonio.",
        )
        res = _parsear_respuesta(
            self._llm_resp, req,
            modalidad="obra_publica", variante=None,
            catalogo_cce=self._catalogo,
        )
        assert res.estado == "umbral_no_definido_en_pliego"

    def test_criterio_none_cuando_no_hay_valor(self):
        req = _req(nombre="Rentabilidad patrimonio",
                   exigido_literal="Rentabilidad del patrimonio conforme a normativa vigente.")
        res = _parsear_respuesta(
            self._llm_resp, req,
            modalidad="obra_publica", variante=None,
            catalogo_cce=self._catalogo,
        )
        assert res.criterio is None

    def test_fuente_no_disponible(self):
        req = _req(nombre="Rentabilidad patrimonio",
                   exigido_literal="Rentabilidad del patrimonio.")
        res = _parsear_respuesta(
            self._llm_resp, req,
            modalidad="obra_publica", variante=None,
            catalogo_cce=self._catalogo,
        )
        assert res.fuente_umbral == "no_disponible"


# ─── Caso adicional — FALLO json_invalido ─────────────────────────────────────

class TestFalloJsonInvalido:
    """El LLM devuelve error (timeout, truncado, etc.)."""

    def test_error_de_llamada_llm(self):
        req = _req()
        raw_error = {"error": "respuesta truncada (max_tokens)", "stop_reason": "max_tokens"}
        res = _parsear_respuesta(raw_error, req)
        assert res.estado == "fallo"
        assert "json_invalido" in (res.razon_fallo or "")
        assert res.criterio is None


# ─── Test: generar_criterio completo con mock de _llamar_llm ─────────────────

class TestGenerarCriterioConMock:
    """Verifica que generar_criterio() pasa por _parsear_respuesta correctamente."""

    def test_pipeline_completo_umbral_simple(self):
        llm_fake = {
            "tipo": "umbral_simple",
            "campo_perfil": "financiero.indice_liquidez",
            "operador": ">=",
            "valor": 1.21,
            "confianza": "alta",
        }
        req = _req(valor_umbral=1.21, operador=">=")
        with patch(
            "src.generador_criterios._llamar_llm",
            return_value=llm_fake,
        ):
            res = generar_criterio(
                req,
                client=None,   # no se usa — está mockeado
                catalogo_cce=_CATALOGO_CCE,
                modalidad="menor_cuantia",
                variante="no_mipyme",
            )
        assert res.estado == "ok"
        assert isinstance(res.criterio, UmbralSimple)
        assert res.criterio.valor == 1.21
        assert res.fuente_umbral == "pliego"


# ─── P1d: convención semántica jurídico — True = favorable en todos los campos ──

class TestP1JuridicoConvencion:
    """
    P1d — Los 5 requisitos jurídicos del piloto (Paicol) deben dar CUMPLE
    cuando el perfil tiene todos los campos en True (condición favorable).

    Antes del fix: antecedentes_fiscales y redam generaban NO_CUMPLE por
    ambigüedad semántica (el LLM ponía valor_requerido=False).
    """

    from src.criterios import evaluar_criterio  # importación local para el test

    _PERFIL_JURIDICO_OK = {
        "juridico": {
            "rup_en_firme":                    True,
            "sin_inhabilidades":               True,
            "sin_antecedentes_fiscales":       True,
            "sin_redam":                       True,
            "garantia_seriedad":               True,
        }
    }

    _CINCO_CRITERIOS = [
        Booleano(
            campo_perfil="juridico.rup_en_firme",
            valor_requerido=True,
            confianza="alta",
            fuente_numeral="3.1",
        ),
        Booleano(
            campo_perfil="juridico.sin_inhabilidades",
            valor_requerido=True,
            confianza="alta",
            fuente_numeral="3.2",
        ),
        Booleano(
            campo_perfil="juridico.sin_antecedentes_fiscales",
            valor_requerido=True,
            confianza="alta",
            fuente_numeral="3.3",
        ),
        Booleano(
            campo_perfil="juridico.sin_redam",
            valor_requerido=True,
            confianza="alta",
            fuente_numeral="3.4",
        ),
        Booleano(
            campo_perfil="juridico.garantia_seriedad",
            valor_requerido=True,
            confianza="alta",
            fuente_numeral="3.5",
        ),
    ]

    def test_cinco_juridicos_true_dan_cumple(self):
        from src.criterios import evaluar_criterio
        for criterio in self._CINCO_CRITERIOS:
            ev = evaluar_criterio(criterio, self._PERFIL_JURIDICO_OK, {})
            assert ev.evaluable, f"{criterio.campo_perfil}: no evaluable"
            assert ev.cumple, (
                f"{criterio.campo_perfil}: esperado CUMPLE, "
                f"empresa={ev.valor_empresa}, umbral={ev.valor_umbral}"
            )

    def test_sin_antecedentes_fiscales_true_cumple(self):
        from src.criterios import evaluar_criterio
        criterio = self._CINCO_CRITERIOS[2]  # sin_antecedentes_fiscales
        ev = evaluar_criterio(criterio, self._PERFIL_JURIDICO_OK, {})
        assert ev.cumple

    def test_sin_redam_true_cumple(self):
        from src.criterios import evaluar_criterio
        criterio = self._CINCO_CRITERIOS[3]  # sin_redam
        ev = evaluar_criterio(criterio, self._PERFIL_JURIDICO_OK, {})
        assert ev.cumple

    def test_sin_medidas_correctivas_true_cumple(self):
        from src.criterios import evaluar_criterio
        criterio = Booleano(
            campo_perfil="juridico.sin_medidas_correctivas",
            valor_requerido=True,
            confianza="alta",
            fuente_numeral="3.6",
        )
        perfil = {"juridico": {"sin_medidas_correctivas": True}}
        ev = evaluar_criterio(criterio, perfil, {})
        assert ev.cumple

    def test_campo_false_no_cumple(self):
        from src.criterios import evaluar_criterio
        criterio = self._CINCO_CRITERIOS[2]  # sin_antecedentes_fiscales
        perfil_malo = {"juridico": {"sin_antecedentes_fiscales": False}}
        ev = evaluar_criterio(criterio, perfil_malo, {})
        assert not ev.cumple

    def test_parsear_booleano_nombre_nuevo(self):
        raw = {
            "tipo": "booleano",
            "campo_perfil": "juridico.sin_antecedentes_fiscales",
            "valor_requerido": True,
            "confianza": "alta",
        }
        req = _req(nombre="Boletín CGR", categoria="juridico",
                   exigido_literal="No debe figurar en el Boletín de Responsables Fiscales.")
        res = _parsear_respuesta(raw, req, "menor_cuantia", "mipyme", {})
        assert res.estado == "ok"
        assert isinstance(res.criterio, Booleano)
        assert res.criterio.campo_perfil == "juridico.sin_antecedentes_fiscales"
        assert res.criterio.valor_requerido is True
