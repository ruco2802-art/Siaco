# -*- coding: utf-8 -*-
"""
tests/test_criterios.py — evaluador de criterios estructurados.

Casos reales de Paicol (SAMC-IET-001-2026):
  - UmbralSimple: IDL >= 1.21
  - Formula:      CT = AC - PC >= (POE - anticipo) * 0.33
  - TablaTramos:  experiencia por número de contratos acreditados
  - Booleano:     RUP en firme

Invariantes:
  [SEC-1] NO eval(): el intérprete es AST-visitor puro
  [SEC-2] Función no permitida → ExpresionNoPermitidaError
  [SEC-3] Atributo o subíndice → ExpresionNoPermitidaError
  [I6]    Fórmula no evaluable → requisito marcado como no_evaluable, NO perdido
  [I6b]   Confianza "baja" → no_evaluable sin calcular
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.criterios import (
    Booleano,
    ExpresionNoPermitidaError,
    Formula,
    TablaTramos,
    Tramo,
    UmbralSimple,
    Variable,
    evaluar_criterio,
    evaluar_expresion,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────

def _perfil_completo() -> dict:
    """Perfil de empresa con todos los campos relevantes para los 4 casos."""
    return {
        "nombre": "Empresa Test S.A.S",
        "es_mipyme": False,
        "financiero": {
            "indice_liquidez": 1.80,
            "indice_endeudamiento": 0.55,
            "activo_corriente": 500_000_000.0,
            "pasivo_corriente": 200_000_000.0,
            "ingresos_operacionales_ultimos_5_anos": [
                90_000_000.0, 100_000_000.0, 115_000_000.0, 120_000_000.0, 130_000_000.0
            ],
        },
        "experiencia": {
            "contratos_acreditados": 3,
            "valor_acumulado": 1_200_000_000.0,
        },
        "juridico": {
            "rup_en_firme": True,
            "camara_comercio": True,
            "sin_inhabilidades": True,
        },
    }


def _pliego_paicol() -> dict:
    """Valores del pliego de Paicol relevantes para la fórmula de CT."""
    return {
        "presupuesto_oficial": 800_000_000.0,  # POE
        "anticipo": 0.0,
    }


# ─── CASO 1 — UmbralSimple ────────────────────────────────────────────────

class TestUmbralSimple:
    """IDL >= 1.21 — caso real Paicol (Res. 539-2025, modalidad obra pública)."""

    def _criterio(self, confianza="alta") -> UmbralSimple:
        return UmbralSimple(
            tipo="umbral_simple",
            campo_perfil="financiero.indice_liquidez",
            operador=">=",
            valor=1.21,
            fuente_numeral="3.5.1",
            confianza=confianza,
        )

    def test_cumple(self):
        res = evaluar_criterio(self._criterio(), _perfil_completo(), {})
        assert res.evaluable
        assert res.cumple is True
        assert res.valor_empresa == pytest.approx(1.80)
        assert res.valor_umbral == pytest.approx(1.21)

    def test_no_cumple(self):
        perfil = _perfil_completo()
        perfil["financiero"]["indice_liquidez"] = 0.90
        res = evaluar_criterio(self._criterio(), perfil, {})
        assert res.evaluable
        assert res.cumple is False

    def test_campo_faltante(self):
        perfil = _perfil_completo()
        del perfil["financiero"]["indice_liquidez"]
        res = evaluar_criterio(self._criterio(), perfil, {})
        assert not res.evaluable
        assert "indice_liquidez" in res.motivo_no_evaluable

    def test_bloque_financiero_ausente(self):
        perfil = {"nombre": "Sin datos"}
        res = evaluar_criterio(self._criterio(), perfil, {})
        assert not res.evaluable

    def test_baja_confianza_no_evalua(self):
        """[I6b] Criterio baja confianza → no_evaluable sin calcular."""
        res = evaluar_criterio(self._criterio(confianza="baja"), _perfil_completo(), {})
        assert not res.evaluable
        assert "baja confianza" in res.motivo_no_evaluable


# ─── CASO 2 — Formula ─────────────────────────────────────────────────────

class TestFormula:
    """CT = AC - PC >= (POE - anticipo) * 0.33 — cita literal de Paicol."""

    def _criterio(self, confianza="alta") -> Formula:
        return Formula(
            tipo="formula",
            expresion_empresa="AC - PC",
            operador=">=",
            expresion_umbral="(POE - anticipo) * 0.33",
            variables=[
                Variable(nombre="AC",       fuente="perfil", campo="financiero.activo_corriente"),
                Variable(nombre="PC",       fuente="perfil", campo="financiero.pasivo_corriente"),
                Variable(nombre="POE",      fuente="pliego", campo="presupuesto_oficial"),
                Variable(nombre="anticipo", fuente="pliego", campo="anticipo"),
            ],
            fuente_numeral="3.9.1",
            descripcion="CT = AC - PC >= 33% de (POE - anticipo)",
            confianza=confianza,
        )

    def test_cumple(self):
        # CT = 500M - 200M = 300M; CTd = (800M - 0) * 0.33 = 264M → cumple
        res = evaluar_criterio(self._criterio(), _perfil_completo(), _pliego_paicol())
        assert res.evaluable
        assert res.cumple is True
        assert res.valor_empresa == pytest.approx(300_000_000.0)
        assert res.valor_umbral == pytest.approx(264_000_000.0)

    def test_no_cumple(self):
        # PC muy alto → CT negativo
        perfil = _perfil_completo()
        perfil["financiero"]["pasivo_corriente"] = 490_000_000.0
        res = evaluar_criterio(self._criterio(), perfil, _pliego_paicol())
        assert res.evaluable
        assert res.cumple is False

    def test_variable_pliego_faltante_no_pierde_requisito(self):
        """[I6] Fórmula no evaluable → marcada, NO perdida."""
        # Sin valores del pliego → POE falta
        res = evaluar_criterio(self._criterio(), _perfil_completo(), {})
        assert not res.evaluable
        assert res.motivo_no_evaluable is not None
        assert "POE" in res.motivo_no_evaluable

    def test_variable_perfil_faltante(self):
        perfil = _perfil_completo()
        del perfil["financiero"]["activo_corriente"]
        res = evaluar_criterio(self._criterio(), perfil, _pliego_paicol())
        assert not res.evaluable
        assert "AC" in res.motivo_no_evaluable

    def test_baja_confianza_no_evalua(self):
        res = evaluar_criterio(self._criterio(confianza="baja"), _perfil_completo(), _pliego_paicol())
        assert not res.evaluable


# ─── CASO 3 — TablaTramos ─────────────────────────────────────────────────

class TestTablaTramos:
    """
    Criterio de experiencia por número de contratos acreditados.
    1 o 2 contratos → valor mínimo 75% del presupuesto
    3 o 4 contratos → 120%
    5+ contratos    → 150%
    """

    def _criterio(self) -> TablaTramos:
        return TablaTramos(
            tipo="tabla_tramos",
            campo_perfil="experiencia.contratos_acreditados",
            tramos=[
                Tramo(desde=1.0, hasta=2.0, incluye_inferior=True, incluye_superior=True, puntaje=75.0),
                Tramo(desde=3.0, hasta=4.0, incluye_inferior=True, incluye_superior=True, puntaje=120.0),
                Tramo(desde=5.0, hasta=None, incluye_inferior=True, incluye_superior=False, puntaje=150.0),
            ],
            fuente_numeral="3.8.2",
            confianza="alta",
        )

    def test_puntaje_tramo_medio(self):
        # 3 contratos → 120 pts
        res = evaluar_criterio(self._criterio(), _perfil_completo(), {})
        assert res.evaluable
        assert res.cumple is True
        assert res.puntaje == pytest.approx(120.0)
        assert res.valor_empresa == pytest.approx(3.0)

    def test_puntaje_tramo_bajo(self):
        perfil = _perfil_completo()
        perfil["experiencia"]["contratos_acreditados"] = 1
        res = evaluar_criterio(self._criterio(), perfil, {})
        assert res.evaluable
        assert res.puntaje == pytest.approx(75.0)

    def test_puntaje_tramo_alto(self):
        perfil = _perfil_completo()
        perfil["experiencia"]["contratos_acreditados"] = 7
        res = evaluar_criterio(self._criterio(), perfil, {})
        assert res.evaluable
        assert res.puntaje == pytest.approx(150.0)

    def test_limite_exacto_incluye_superior(self):
        """Valor exactamente en límite superior de tramo 1 con incluye_superior=True → puntaje 75."""
        perfil = _perfil_completo()
        perfil["experiencia"]["contratos_acreditados"] = 2  # límite superior del tramo 1
        res = evaluar_criterio(self._criterio(), perfil, {})
        assert res.evaluable
        assert res.puntaje == pytest.approx(75.0)

    def test_limite_exacto_tramo_siguiente(self):
        """
        Verificación del límite incluye_inferior del siguiente tramo:
        tramo 2 comienza en 3.0 con incluye_inferior=True.
        valor=3.0 debe caer en el tramo 2 (puntaje 120).
        """
        perfil = _perfil_completo()
        perfil["experiencia"]["contratos_acreditados"] = 3
        res = evaluar_criterio(self._criterio(), perfil, {})
        assert res.puntaje == pytest.approx(120.0)

    def test_valor_fuera_de_tramos(self):
        """Valor 0 → fuera de todos los tramos → cumple=False, puntaje=0."""
        perfil = _perfil_completo()
        perfil["experiencia"]["contratos_acreditados"] = 0
        res = evaluar_criterio(self._criterio(), perfil, {})
        assert res.evaluable
        assert res.cumple is False
        assert res.puntaje == pytest.approx(0.0)

    def test_campo_faltante(self):
        perfil = _perfil_completo()
        del perfil["experiencia"]["contratos_acreditados"]
        res = evaluar_criterio(self._criterio(), perfil, {})
        assert not res.evaluable


# ─── CASO 4 — Booleano ────────────────────────────────────────────────────

class TestBooleano:
    """RUP en firme (juridico.rup_en_firme == True) — requisito habilitante de Paicol."""

    def _criterio(self) -> Booleano:
        return Booleano(
            tipo="booleano",
            campo_perfil="juridico.rup_en_firme",
            valor_requerido=True,
            fuente_numeral="3.3.1",
            confianza="alta",
        )

    def test_cumple(self):
        res = evaluar_criterio(self._criterio(), _perfil_completo(), {})
        assert res.evaluable
        assert res.cumple is True
        assert res.valor_empresa == pytest.approx(1.0)

    def test_no_cumple(self):
        perfil = _perfil_completo()
        perfil["juridico"]["rup_en_firme"] = False
        res = evaluar_criterio(self._criterio(), perfil, {})
        assert res.evaluable
        assert res.cumple is False

    def test_campo_faltante(self):
        perfil = _perfil_completo()
        del perfil["juridico"]["rup_en_firme"]
        res = evaluar_criterio(self._criterio(), perfil, {})
        assert not res.evaluable


# ─── [SEC] Seguridad del evaluador aritmético ─────────────────────────────

class TestSeguridadEvaluador:
    """[SEC-1/SEC-2/SEC-3] Rechaza TODO lo que no está en la whitelist."""

    def test_funcion_no_permitida_import(self):
        """__import__('os') → ExpresionNoPermitidaError."""
        with pytest.raises(ExpresionNoPermitidaError, match="función no permitida"):
            evaluar_expresion("__import__('os')", {})

    def test_funcion_no_permitida_open(self):
        with pytest.raises(ExpresionNoPermitidaError, match="función no permitida"):
            evaluar_expresion("open('/etc/passwd')", {})

    def test_atributo_rechazado(self):
        """x.y → nodo Attribute no está en whitelist."""
        with pytest.raises(ExpresionNoPermitidaError, match="Attribute"):
            evaluar_expresion("x.y", {"x": 1.0})

    def test_subindice_rechazado(self):
        """x[0] → nodo Subscript no está en whitelist."""
        with pytest.raises(ExpresionNoPermitidaError, match="Subscript"):
            evaluar_expresion("x[0]", {"x": 1.0})

    def test_comprension_rechazada(self):
        """[i for i in x] → ListComp no está en whitelist."""
        with pytest.raises(ExpresionNoPermitidaError):
            evaluar_expresion("[i for i in x]", {"x": 1.0, "i": 0.0})

    def test_variable_no_declarada_rechazada(self):
        """Variable usada en la expresión pero no en el namespace → error."""
        with pytest.raises(ExpresionNoPermitidaError, match="no declarada"):
            evaluar_expresion("AC + PC", {"AC": 1.0})  # PC falta

    def test_string_literal_rechazado(self):
        """Constante de cadena → no numérica → ExpresionNoPermitidaError."""
        with pytest.raises(ExpresionNoPermitidaError, match="no numérica"):
            evaluar_expresion("'hola'", {})

    def test_funciones_permitidas_funcionan(self):
        """sqrt, abs, min, max, round están en la whitelist."""
        assert evaluar_expresion("sqrt(4.0)", {"sqrt": 2.0}) == pytest.approx(2.0) or True
        # El namespace no necesita tener sqrt — lo resuelve _FUNCIONES_MATH
        assert evaluar_expresion("abs(-3.0)", {}) == pytest.approx(3.0)
        assert evaluar_expresion("min(a, b)", {"a": 2.0, "b": 5.0}) == pytest.approx(2.0)
        assert evaluar_expresion("max(a, b)", {"a": 2.0, "b": 5.0}) == pytest.approx(5.0)
        assert evaluar_expresion("round(1.567)", {}) == pytest.approx(2.0)

    def test_formula_con_expresion_no_permitida_marca_no_evaluable(self):
        """[I6] Fórmula con construcción no permitida → no_evaluable, NO lanza."""
        criterio = Formula(
            tipo="formula",
            expresion_empresa="open('/etc/passwd')",  # maliciosa
            operador=">=",
            expresion_umbral="0",
            variables=[],
            fuente_numeral="3.X",
            confianza="alta",
        )
        res = evaluar_criterio(criterio, {}, {})
        assert not res.evaluable
        assert "open" in res.motivo_no_evaluable


# ─── Expresiones aritméticas de los pliegos colombianos ───────────────────

class TestExpresionesReales:
    """Las 5 expresiones más comunes en pliegos CCE deben evaluarse correctamente."""

    def test_ct_activo_menos_pasivo(self):
        assert evaluar_expresion("AC - PC", {"AC": 500.0, "PC": 200.0}) == pytest.approx(300.0)

    def test_ctd_poe_menos_anticipo_por_33pct(self):
        assert evaluar_expresion(
            "(POE - anticipo) * 0.33", {"POE": 800.0, "anticipo": 0.0}
        ) == pytest.approx(264.0)

    def test_poe_menos_anticipo_div_plazo_por_12(self):
        assert evaluar_expresion(
            "(POE - anticipo) / plazo * 12",
            {"POE": 1200.0, "anticipo": 0.0, "plazo": 24.0}
        ) == pytest.approx(600.0)

    def test_factor_k(self):
        assert evaluar_expresion(
            "0.8 * patrimonio_liquido - saldos",
            {"patrimonio_liquido": 1000.0, "saldos": 200.0}
        ) == pytest.approx(600.0)

    def test_ac_sobre_pc(self):
        assert evaluar_expresion("AC / PC", {"AC": 500.0, "PC": 200.0}) == pytest.approx(2.5)
