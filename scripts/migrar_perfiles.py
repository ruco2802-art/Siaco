#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/migrar_perfiles.py — convierte perfiles existentes al esquema canónico.

Soporta dos formatos de entrada:
  FORMATO A — clientes/cliente_XXX.json  (perfil plano con financiero anidado)
  FORMATO B — clientes/{id}/perfil.json  (solo metadatos de sesión, sin indicadores)

Uso:
  py scripts/migrar_perfiles.py [--dry-run] [--dir clientes]

El script NUNCA inventa valores: los campos sin equivalente en el formato viejo
quedan como null. El operador debe completar los campos manualmente o vía el
formulario del frontend.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Agregar pipeline y pipeline/src al path para importar el esquema canónico
_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root / "pipeline"))
sys.path.insert(0, str(_root / "pipeline" / "src"))

from perfil import PerfilEmpresa


def _detectar_formato(data: dict) -> str:
    """Retorna 'A' (plano con financiero) o 'B' (solo metadatos)."""
    if "id_cliente" in data or "documentacion_al_dia" in data:
        return "A"
    if "cliente_id" in data and "financiero" not in data:
        return "B"
    return "B"  # conservador


def _migrar_formato_a(data: dict) -> dict:
    """
    Convierte el formato plano antiguo (cliente_XXX.json) al canónico.

    Mapeos:
      financiero.razon_cobertura_interes → financiero.cobertura_intereses
      rup.tiene_rup                       → juridico.rup_en_firme
      documentacion_al_dia                → se descarta (sin granularidad)
    """
    financiero_viejo = data.get("financiero", {})
    rup_viejo = data.get("rup", {})

    perfil: dict = {
        "nombre": data.get("nombre", ""),
        "nit": data.get("nit"),
        "sector": data.get("sector"),
        "es_mipyme": data.get("es_mipyme", False),
    }

    if financiero_viejo:
        perfil["financiero"] = {
            "indice_liquidez": financiero_viejo.get("indice_liquidez") or financiero_viejo.get("liquidez"),
            "indice_endeudamiento": financiero_viejo.get("indice_endeudamiento") or financiero_viejo.get("endeudamiento"),
            "cobertura_intereses": (
                financiero_viejo.get("cobertura_intereses")
                or financiero_viejo.get("razon_cobertura_interes")
            ),
            "capital_trabajo": financiero_viejo.get("capital_trabajo"),
            "patrimonio_neto": financiero_viejo.get("patrimonio_neto") or financiero_viejo.get("patrimonio_liquido"),
            "renta_operacional": financiero_viejo.get("renta_operacional"),
            "ebitda": financiero_viejo.get("ebitda"),
            "rentabilidad_patrimonio": financiero_viejo.get("rentabilidad_patrimonio"),
            "rentabilidad_activo": financiero_viejo.get("rentabilidad_activo"),
        }

    if rup_viejo:
        perfil["juridico"] = {
            "rup_en_firme": rup_viejo.get("tiene_rup"),
        }

    return perfil


def _migrar_formato_b(data: dict) -> dict:
    """
    Convierte el perfil de sesión (clientes/{id}/perfil.json) al canónico.

    Solo recupera los metadatos básicos; los indicadores financieros/jurídicos
    quedan todos en None y deben completarse vía el formulario del frontend.
    """
    return {
        "nombre": data.get("nombre", data.get("cliente_id", "")),
        "nit": data.get("nit"),
        "sector": data.get("sector"),
        "es_mipyme": data.get("es_mipyme", False),
        # financiero, juridico, tecnico, experiencia, social → None (sin datos)
    }


def _migrar(data: dict, ruta: Path) -> tuple[dict, list[str]]:
    """Retorna (perfil_canonico, lista_de_campos_que_faltan)."""
    fmt = _detectar_formato(data)
    if fmt == "A":
        canonico = _migrar_formato_a(data)
    else:
        canonico = _migrar_formato_b(data)

    # Validar con el esquema canónico (falla ruidosamente si el nombre es vacío)
    perfil = PerfilEmpresa(**canonico)
    salida = perfil.model_dump()

    # Identificar campos null para el reporte
    faltantes: list[str] = []
    fin = salida.get("financiero") or {}
    for campo, val in fin.items():
        if val is None or val == []:
            faltantes.append(f"financiero.{campo}")
    if salida.get("juridico") is None:
        faltantes.append("juridico (bloque completo)")
    if salida.get("experiencia") is None:
        faltantes.append("experiencia (bloque completo)")
    if salida.get("social") is None:
        faltantes.append("social (bloque completo)")

    return salida, faltantes


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra perfiles al esquema canónico")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra cambios, no escribe")
    parser.add_argument("--dir", default="clientes", help="Directorio raíz de clientes")
    args = parser.parse_args()

    base = Path(args.dir)
    if not base.exists():
        print(f"[ERROR] Directorio no encontrado: {base}")
        sys.exit(1)

    archivos = list(base.glob("*.json")) + list(base.glob("*/perfil.json"))
    print(f"Archivos encontrados: {len(archivos)}\n")

    ok = err = 0
    for ruta in sorted(archivos):
        try:
            data = json.loads(ruta.read_text("utf-8"))
        except Exception as exc:
            print(f"  [ERROR lectura] {ruta}: {exc}")
            err += 1
            continue

        try:
            canonico, faltantes = _migrar(data, ruta)
        except Exception as exc:
            print(f"  [ERROR migración] {ruta}: {exc}")
            err += 1
            continue

        if args.dry_run:
            print(f"  [DRY-RUN] {ruta}")
            if faltantes:
                print(f"    Campos null tras migrar: {', '.join(faltantes[:6])}"
                      + (" ..." if len(faltantes) > 6 else ""))
        else:
            ruta.write_text(json.dumps(canonico, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [OK] {ruta}")
            if faltantes:
                print(f"    Campos null (llenar en formulario): {', '.join(faltantes[:6])}"
                      + (" ..." if len(faltantes) > 6 else ""))
        ok += 1

    print(f"\nMigrados: {ok} | Errores: {err}")
    if err:
        sys.exit(1)


if __name__ == "__main__":
    main()
