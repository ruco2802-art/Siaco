# -*- coding: utf-8 -*-
"""
main.py — orquestación del pipeline de pliegos.

Flujo: PDF → parser → chunker → extractor → verifier → evaluator → reporte.
Ejecutar desde pipeline/:  python main.py <ruta_pdf>
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

# Asegurar que src/ sea importable aunque se ejecute desde cualquier directorio
sys.path.insert(0, str(Path(__file__).parent))

from src.parser import parsear_pdf, ParserVacioError, ParserError, ParserTimeoutError
from src.chunker import chunkear, CoberturaIncompletaError
from src.extractor import extraer, ResultadoExtraccion
from src.verifier import (
    verificar_citas,
    marcar_indices,
    tasa_verificacion,
    estado_global,
    generar_aviso_verificacion,
)
from src.evaluator import cargar_perfil, evaluar_empresa, PerfilEmpresa

# ─── Perfiles de prueba ────────────────────────────────────────────────────

PERFIL_COMPLETO: dict = {
    "nombre": "Constructora ABCD SAS",
    "es_mipyme": True,
    "financiero": {
        "indice_liquidez": 1.85,
        "indice_endeudamiento": 0.42,
        "capital_trabajo": 450_000_000.0,
        "patrimonio_neto": 1_200_000_000.0,
        "renta_operacional": 3_500_000_000.0,
        "ebitda": 420_000_000.0,
        "rentabilidad_patrimonio": 0.18,
        "rentabilidad_activo": 0.09,
        "cobertura_intereses": 3.2,
    },
    "experiencia": {
        "valor_acumulado": 8_500_000_000.0,
        "valor_individual_max": 4_200_000_000.0,
        "objetos_similares": ["obra civil", "mantenimiento vial", "construcción"],
        "codigos_unspsc": ["72151501", "72151502", "72151601"],
        "contratos_acreditados": 3,
        "antiguedad_meses": 60,
    },
    "juridico": {
        "rup_en_firme": True,
        "camara_comercio": True,
        "paz_y_salvo_parafiscales": True,
        "paz_y_salvo_seguridad_social": True,
        "paz_y_salvo_impuestos": True,
        "sin_inhabilidades": True,
        "sin_antecedentes_disciplinarios": True,
        "sin_antecedentes_penales": True,
        "garantia_seriedad": True,
        "rut_vigente": True,
    },
    "tecnico": {
        "personal_disponible": 15,
        "equipos": ["excavadora", "volqueta", "compactador"],
        "certificaciones": ["ISO 9001"],
    },
}

PERFIL_INCOMPLETO: dict = {
    "nombre": "Empresa Sin Datos Financieros SAS",
    "es_mipyme": False,
    # Sin bloque "financiero" → dato_faltante en toda la categoría financiero
    # Sin bloque "juridico"   → dato_faltante en juridico y documental
    # Sin bloque "tecnico"    → dato_faltante en tecnico
    "experiencia": {
        "valor_acumulado": 2_000_000_000.0,
        # valor_individual_max ausente → dato_faltante para ese ítem
    },
}

# ─── utilidades internas ───────────────────────────────────────────────────

def _validar_escritura(ruta: Path) -> None:
    """
    [I9b] Verifica que ruta sea escribible ANTES del primer gasto de API.
    Crea el directorio si no existe, escribe un archivo de prueba y lo borra.
    Si falla → imprime error descriptivo y termina; nunca silenciosamente.
    """
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(".write_test")
        tmp.write_text("ok", encoding="utf-8")
        tmp.unlink()
    except Exception as exc:
        print(f"\n  [I9] ABORTANDO — ruta de salida no escribible.")
        print(f"       Ruta   : {ruta}")
        print(f"       Motivo : {exc}")
        print(f"       Ningún gasto de API se realizará.")
        sys.exit(1)


# ─── utilidades de reporte ─────────────────────────────────────────────────

_ANCHO = 72


def _sep(titulo: str = "") -> None:
    if titulo:
        relleno = _ANCHO - len(titulo) - 5
        print(f"\n{'─' * 3} {titulo} {'─' * max(0, relleno)}")
    else:
        print("─" * _ANCHO)


def _reporte_extraccion(
    resultado: ResultadoExtraccion,
    markdown: str,
    cobertura: float,
) -> ResultadoExtraccion:
    resultado = verificar_citas(resultado, markdown)  # [I7][I8]
    resultado = marcar_indices(resultado)              # [2.3]
    tasa = tasa_verificacion(resultado)
    estado = estado_global(          # [I4]
        errores=[],
        truncados=resultado.truncamientos,
        cobertura_pct=cobertura,
    )

    _sep("RESULTADO DE EXTRACCIÓN")
    print(f"  Entidad         : {resultado.entidad_publica or '(no detectada)'}")
    print(f"  Proceso         : {resultado.numero_proceso or '(no detectado)'}")
    print(f"  Estado global   : {estado.upper()}")
    print(f"  Cobertura       : {cobertura:.2f}%")
    print(f"  Chunks          : {resultado.chunks_procesados}/{resultado.chunks_totales} procesados")
    print(f"  Requisitos      : {len(resultado.requisitos)} extraídos")
    print(f"  Citas verific.  : {tasa:.1f}%")

    if resultado.truncamientos:
        print(f"  Truncamientos   : {', '.join(resultado.truncamientos)}")

    _sep("REQUISITOS POR CATEGORÍA")
    cnt = Counter(r.categoria for r in resultado.requisitos)
    for cat, n in sorted(cnt.items(), key=lambda x: -x[1]):
        print(f"  {cat:<16}  {n}")

    _sep("CHECKLIST CCE — NO ENCONTRADOS")
    if resultado.checklist_no_encontrados:
        for item in resultado.checklist_no_encontrados:
            print(f"  ✗  {item}")
    else:
        print("  Todos los ítems del checklist fueron encontrados.")

    if resultado.hallazgos_fuera_de_checklist:
        _sep(f"HALLAZGOS FUERA DE CHECKLIST ({len(resultado.hallazgos_fuera_de_checklist)})")
        for h in resultado.hallazgos_fuera_de_checklist:
            print(f"  →  {h}")

    no_verif = [r for r in resultado.requisitos if not r.cita_verificada]
    if no_verif:
        _sep(f"CITAS NO VERIFICADAS [I7] ({len(no_verif)})")
        for r in no_verif:
            print(f"  [{r.categoria}] {r.nombre}")
            print(f"        cita: {r.exigido_literal[:90]!r}")

    aviso = generar_aviso_verificacion(resultado)
    if aviso:
        _sep("AVISO VERIFICACIÓN MANUAL [FASE D]")
        print(aviso)

    return resultado


def _reporte_evaluacion(perfil_data: dict, requisitos: list, etiqueta: str) -> None:
    _sep(f"EVALUACIÓN: {etiqueta}")
    perfil: PerfilEmpresa = cargar_perfil(perfil_data)
    ev = evaluar_empresa(perfil, requisitos)

    print(f"  Empresa         : {ev['empresa']}")
    print(f"  Mipyme          : {ev['es_mipyme']}")
    print(f"  Score global    : {ev['score_global']:.1f} / 100")
    print(f"  Veredicto       : {ev['veredicto'].upper()}")
    print(f"  Fórmula         : {ev['_formula']}")
    print()

    print(f"  {'Categoría':<16} {'Score':>6}  {'Cumple':>6}  {'No_cumple':>9}  "
          f"{'Dato_falt':>9}  {'Peso':>5}")
    print(f"  {'─'*16} {'─'*6}  {'─'*6}  {'─'*9}  {'─'*9}  {'─'*5}")
    for cat, st in ev["desglose"].items():
        score_str = f"{st['score']:.1f}" if st["score"] is not None else "  N/A"
        print(
            f"  {cat:<16} {score_str:>6}  {st['cumple']:>6}  {st['no_cumple']:>9}  "
            f"{st['dato_faltante']:>9}  {st['peso']:.2f}"
        )

    # Mostrar dato_faltante para que sea visible la diferencia con el perfil completo
    faltantes = [i for i in ev["items"] if i["estado"] == "dato_faltante"]
    if faltantes:
        print(f"\n  dato_faltante ({len(faltantes)} ítems):")
        for i in faltantes[:8]:
            print(f"    - [{i['categoria']}] {i['requisito']}")
        if len(faltantes) > 8:
            print(f"    ... y {len(faltantes) - 8} más")

    no_cumple = [i for i in ev["items"] if i["estado"] == "no_cumple"]
    if no_cumple:
        print(f"\n  no_cumple ({len(no_cumple)} ítems):")
        for i in no_cumple[:5]:
            val = i.get("valor_empresa", "?")
            umb = i.get("umbral", "?")
            op  = i.get("operador", "?")
            print(f"    - {i['requisito']}: empresa={val} vs umbral {op} {umb}")


# ─── main ──────────────────────────────────────────────────────────────────

def main(pdf_path: Path) -> None:
    print("=" * _ANCHO)
    print("PIPELINE MODULAR — PLIEGOS CONTRATACIÓN COLOMBIA")
    print("=" * _ANCHO)

    # ── PASO 1: Parseo ────────────────────────────────────────────────────
    _sep("PASO 1 / PARSEO")
    print(f"  PDF: {pdf_path.name}")
    try:
        markdown, meta_p = parsear_pdf(pdf_path)
    except ParserVacioError as exc:
        print(f"  ERROR (parser vacío): {exc}")
        sys.exit(1)
    except ParserTimeoutError as exc:
        print(f"  ERROR (timeout): {exc}")
        sys.exit(1)
    except ParserError as exc:
        print(f"  ERROR (parser): {exc}")
        sys.exit(1)

    print(f"  Chars         : {meta_p['chars']:,}")
    print(f"  Páginas       : {meta_p['n_paginas']}")
    print(f"  OCR           : {meta_p['uso_ocr']}")
    print(f"  Tiempo        : {meta_p['tiempo_s']}s {'(desde caché)' if meta_p['desde_cache'] else ''}")

    # ── PASO 2: Chunking ──────────────────────────────────────────────────
    _sep("PASO 2 / CHUNKING")
    try:
        chunks, cobertura = chunkear(markdown)
    except CoberturaIncompletaError as exc:
        print(f"  ERROR (cobertura): {exc}")
        sys.exit(1)

    print(f"  Chunks        : {len(chunks)}")
    print(f"  Cobertura     : {cobertura:.2f}%")
    if chunks:
        lens = [len(c["texto"]) for c in chunks]
        print(f"  Chars/chunk   : min={min(lens):,}  max={max(lens):,}  avg={sum(lens)//len(lens):,}")

    # ── PASO 3: Extracción ────────────────────────────────────────────────
    _sep("PASO 3 / EXTRACCIÓN (todos los chunks)")
    print(f"  Modelo : claude-sonnet-4-6  |  max_tokens=8000 (fusible)")

    # [I9b] Validar escritura ANTES del primer gasto de API
    ruta_salida = (
        Path(__file__).parent.parent
        / "resultados_evaluacion"
        / f"{pdf_path.stem}_extraccion.json"
    )
    _validar_escritura(ruta_salida)
    print(f"  Resultado → {ruta_salida}")

    resultado = extraer(markdown, chunks, ruta_salida=ruta_salida)
    print(f"  Guardado  → {ruta_salida}")

    # ── PASO 4: Verificación + reporte ───────────────────────────────────
    resultado = _reporte_extraccion(resultado, markdown, cobertura)

    # ── PASO 5: Evaluación perfil completo ────────────────────────────────
    print()
    print("=" * _ANCHO)
    print("EVALUACIONES DE EMPRESA")
    print("=" * _ANCHO)

    _reporte_evaluacion(PERFIL_COMPLETO, resultado.requisitos, "PERFIL COMPLETO")

    print()
    _reporte_evaluacion(PERFIL_INCOMPLETO, resultado.requisitos,
                        "PERFIL INCOMPLETO (verifica dato_faltante)")

    print()
    print("=" * _ANCHO)
    print("FIN DEL PIPELINE")
    print("=" * _ANCHO)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # PDF de prueba por defecto (relativo a la raíz del proyecto)
        default = Path("../pliegos_evaluacion/16. PLIEGO DE CONDICIONES DEFINITIVO.pdf")
        if default.exists():
            pdf = default
        else:
            print("Uso: python main.py <ruta_al_pdf>")
            sys.exit(1)
    else:
        pdf = Path(sys.argv[1])

    main(pdf)
