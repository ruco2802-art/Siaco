# -*- coding: utf-8 -*-
"""
src/perfil.py — esquema canónico de PerfilEmpresa.

ÚNICA fuente de verdad: el frontend y el pipeline importan desde aquí.
No dupliques estas clases en evaluator.py, routers/perfil.py ni en ningún otro módulo.

Convención semántica — bloque jurídico:
  True SIEMPRE significa condición favorable para ofertar, sin excepción.
  Ejemplos: sin_inhabilidades=True → no tiene inhabilidades (puede ofertar).
            sin_redam=True → no figura en REDAM (puede ofertar).
  Esta convención elimina la ambigüedad entre "tengo el certificado" y "estoy
  reportado"; todos los evaluadores y el skill generacion_criterios.md la asumen.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError


# ─── Capacidad financiera ──────────────────────────────────────────────────

class PerfilFinanciero(BaseModel):
    # Indicadores de liquidez y solvencia (requeridos por Res. 539/540/541)
    indice_liquidez: float | None = None
    indice_endeudamiento: float | None = None
    cobertura_intereses: float | None = None
    # Balance básico
    capital_trabajo: float | None = None
    activo_corriente: float | None = None
    pasivo_corriente: float | None = None
    patrimonio_neto: float | None = None
    # Rentabilidad
    renta_operacional: float | None = None
    ebitda: float | None = None
    rentabilidad_patrimonio: float | None = None  # ROE (Utilidad neta / Patrimonio)
    rentabilidad_activo: float | None = None      # ROA (Utilidad operacional / Activo total)
    roe: float | None = None  # alias explícito cuando el pliego usa "ROE" como término
    roa: float | None = None  # alias explícito cuando el pliego usa "ROA" como término
    # Capacidad residual (Factor K)
    ingresos_operacionales_ultimos_5_anos: list[float] = Field(default_factory=list)
    saldos_contratos_en_ejecucion: float | None = None  # Σ(valor × % pendiente)
    numero_profesionales_vinculados: int | None = None


# ─── Experiencia ───────────────────────────────────────────────────────────

class PerfilExperiencia(BaseModel):
    valor_acumulado: float | None = None
    valor_individual_max: float | None = None
    objetos_similares: list[str] = Field(default_factory=list)
    codigos_unspsc: list[str] = Field(default_factory=list)
    contratos_acreditados: int | None = None
    antiguedad_meses: int | None = None


# ─── Habilitación jurídica ─────────────────────────────────────────────────

class PerfilJuridico(BaseModel):
    # Documentos de existencia y representación
    rup_en_firme: bool | None = None
    rup_fecha_expedicion: str | None = None        # ISO-8601 o "YYYY-MM-DD"
    camara_comercio: bool | None = None
    camara_comercio_fecha: str | None = None
    rut_vigente: bool | None = None
    rut_fecha: str | None = None
    # Paz y salvos
    paz_y_salvo_parafiscales: bool | None = None
    paz_y_salvo_seguridad_social: bool | None = None
    paz_y_salvo_impuestos: bool | None = None
    paz_salvo_municipal: bool | None = None
    paz_salvo_municipal_fecha: str | None = None
    # Antecedentes y registros (True = condición favorable, ver convención del módulo)
    sin_inhabilidades: bool | None = None
    sin_antecedentes_disciplinarios: bool | None = None
    sin_antecedentes_penales: bool | None = None
    sin_antecedentes_fiscales: bool | None = None
    sin_antecedentes_fiscales_fecha: str | None = None
    sin_redam: bool | None = None
    sin_redam_fecha: str | None = None
    sin_medidas_correctivas: bool | None = None
    # Otros
    garantia_seriedad: bool | None = None


# ─── Capacidad técnica ─────────────────────────────────────────────────────

class PerfilTecnico(BaseModel):
    personal_disponible: int | None = None
    equipos: list[str] = Field(default_factory=list)
    certificaciones: list[str] = Field(default_factory=list)


# ─── Componente social ─────────────────────────────────────────────────────

class PerfilSocial(BaseModel):
    porcentaje_mujeres_nomina: float | None = None
    porcentaje_discapacidad: float | None = None
    personas_reincorporadas: int | None = None
    poblacion_etnica: bool | None = None


# ─── Perfil canónico ───────────────────────────────────────────────────────

class PerfilEmpresa(BaseModel):
    # Identificación
    nombre: str
    nit: str | None = None
    sector: str | None = None
    municipio_domicilio: str | None = None
    departamento_domicilio: str | None = None
    es_mipyme: bool = False
    tamano_empresa: Literal["micro", "pequena", "mediana", "grande"] | None = None
    es_empresa_de_mujeres: bool = False
    # Bloques de capacidad
    financiero: PerfilFinanciero | None = None
    experiencia: PerfilExperiencia | None = None
    juridico: PerfilJuridico | None = None
    tecnico: PerfilTecnico | None = None
    social: PerfilSocial | None = None


def cargar_perfil(data: dict) -> PerfilEmpresa:
    """
    Valida y construye el PerfilEmpresa desde un dict (leído de Supabase o disco).

    Si un bloque completo falta (financiero, juridico, etc.) el campo queda None;
    los requisitos de esa categoría recibirán estado 'dato_faltante' en el evaluador.
    Los campos desconocidos del dict se ignoran (migración progresiva).
    """
    try:
        return PerfilEmpresa(**data)
    except ValidationError as exc:
        raise ValueError(
            f"Perfil de empresa inválido — corrígelo antes de continuar:\n{exc}"
        ) from exc
