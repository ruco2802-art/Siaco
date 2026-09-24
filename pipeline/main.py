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

# La salida lleva caracteres de dibujo (─, ·, ✓). Redirigida a un archivo,
# Windows elige cp1252 y el pipeline muere en el PASO 1 con UnicodeEncodeError
# ANTES de llamar a la API: el arranque se pierde entero por un separador.
# reconfigure() es de Python 3.7+ y no depende de PYTHONIOENCODING.
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Asegurar que src/ sea importable aunque se ejecute desde cualquier directorio
sys.path.insert(0, str(Path(__file__).parent))

# Credenciales: misma convención que los scripts CLI del repo (evaluar_t12.py,
# evaluar_pliegos.py, scripts/ocr_resoluciones.py). override=True porque un valor
# obsoleto en el shell debe perder frente al .env del proyecto — el caso real fue
# un placeholder de 23 chars que producía 401 en cada chunk.
# La app de producción usa override=False para que las env vars de Railway ganen.
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

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
from src import registro

# ─── Perfiles de prueba ────────────────────────────────────────────────────

PERFIL_COMPLETO: dict = {
    "nombre": "Constructora ABCD SAS",
    "es_mipyme": True,
    "municipio_domicilio": "Paicol",
    "departamento_domicilio": "Huila",
    "financiero": {
        "indice_liquidez": 1.85,
        "indice_endeudamiento": 0.42,
        "capital_trabajo": 450_000_000.0,
        "patrimonio_neto": 1_200_000_000.0,
        "renta_operacional": 3_500_000_000.0,
        "ebitda": 420_000_000.0,
        "rentabilidad_patrimonio": 0.18,
        "rentabilidad_activo": 0.09,
        "roe": 0.18,
        "roa": 0.09,
        "cobertura_intereses": 3.2,
        "saldos_contratos_en_ejecucion": 800_000_000.0,
        "numero_profesionales_vinculados": 12,
        "ingresos_operacionales_ultimos_5_anos": [
            2_800_000_000.0, 3_100_000_000.0, 3_500_000_000.0,
            3_700_000_000.0, 4_000_000_000.0,
        ],
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
        "paz_salvo_municipal": True,
        "sin_inhabilidades": True,
        "sin_antecedentes_disciplinarios": True,
        "sin_antecedentes_penales": True,
        "sin_antecedentes_fiscales": True,
        "sin_redam": True,
        "sin_medidas_correctivas": True,
        "sin_insolvencia": True,
        "objeto_social_compatible": True,
        "sin_conflicto_interes": True,
        "sin_estudios_diseno_previos": True,
        "garantia_seriedad": True,
        "rut_vigente": True,
    },
    "tecnico": {
        "personal_disponible": 15,
        "equipos": ["excavadora", "volqueta", "compactador"],
        "certificaciones": ["ISO 9001"],
        "titulo_profesional": "ingeniero",
        "porcentaje_empleados_colombianos": 95.0,
    },
    "social": {
        "porcentaje_mujeres_nomina": 0.35,
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


def _repersistir_verificado(resultado: ResultadoExtraccion, ruta_salida: Path) -> None:
    """
    Reescribe el JSON de extracción con la verificación de citas aplicada.

    El PASO 3 persiste antes de que el PASO 4 verifique [I9], así que el
    archivo quedaba con `estado_verificacion='no_verificada'` en todos los
    requisitos. artefactos.py lee ese archivo: la app y el chat nunca veían el
    resultado de la verificación.

    Falla ruidosamente si tras verificar NINGÚN requisito cambió de estado —
    eso significa que la verificación no corrió, y el silencio es justo lo que
    dejó pasar este bug.
    """
    reqs = resultado.requisitos
    if not reqs:
        print("  Re-persistencia : omitida (0 requisitos)")
        return

    # Cero verificadas puede significar dos cosas distintas:
    #   a) la verificación no corrió (el bug que esto vigila), o
    #   b) corrió y ninguna cita coincide — información legítima, y lo normal
    #      en un conjunto pequeño o sintético.
    # Sólo (a) es implausible con un pliego real: Paicol da 89,4%. Se exige
    # una muestra mínima antes de tratarlo como error, y se avisa siempre.
    _MIN_MUESTRA_PARA_FALLAR = 20
    n_verificadas = sum(1 for r in reqs if r.estado_verificacion != "no_verificada")
    if n_verificadas == 0:
        if len(reqs) >= _MIN_MUESTRA_PARA_FALLAR:
            raise RuntimeError(
                f"verificar_citas() no marcó ninguno de los {len(reqs)} requisitos: "
                "todos siguen en 'no_verificada'. Con esa cantidad es implausible "
                "que ninguna cita coincida — la verificación no corrió o su salida "
                "no llega al resultado. No se re-persiste un archivo que afirmaría "
                "que nada está verificado."
            )
        print(f"  AVISO: 0 de {len(reqs)} citas verificadas. Con menos de "
              f"{_MIN_MUESTRA_PARA_FALLAR} requisitos puede ser legítimo; "
              "revisa si el markdown corresponde al pliego.")

    try:
        ruta_salida.write_text(resultado.model_dump_json(indent=2), encoding="utf-8")
    except OSError as exc:
        raise IOError(f"No se pudo re-persistir {ruta_salida}: {exc}") from exc

    from collections import Counter
    dist = Counter(r.estado_verificacion for r in reqs)
    con_pagina = sum(1 for r in reqs if r.pagina_origen is not None)
    print(f"  Re-persistido   → {ruta_salida}")
    print(f"  estado_verificacion: {dict(dist)}")
    print(f"  con pagina_origen  : {con_pagina}/{len(reqs)}")


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

    cobertura_g = ev.get("cobertura_global", 0.0)
    total_evaluados = ev.get("total_evaluados", 0)
    total_con_datos = ev.get("total_con_datos", 0)

    print(f"  Empresa         : {ev['empresa']}")
    print(f"  Mipyme          : {ev['es_mipyme']}")
    # Score sólo si cobertura >= 80 %: evita "100/100" con 2 de 20 req evaluados
    if cobertura_g >= 0.80:
        print(f"  Score global    : {ev['score_global']:.1f} / 100")
        print(f"  Veredicto       : {ev['veredicto'].upper()}")
    else:
        print(f"  Score global    : — (cobertura insuficiente: {cobertura_g*100:.0f}%)")
        print(f"  Evaluación incompleta — {total_con_datos} de {total_evaluados} "
              f"requisitos verificados")
        print(f"  Veredicto       : No es posible emitir un veredicto de habilitación")
    print(f"  Fórmula         : {ev['_formula']}")
    print()

    print(f"  {'Categoría':<16} {'Score':>6}  {'Cob%':>5}  {'Cumple':>6}  "
          f"{'No_cumple':>9}  {'Sin_dato':>8}  {'No_aplica':>9}  {'Peso':>5}")
    print(f"  {'─'*16} {'─'*6}  {'─'*5}  {'─'*6}  {'─'*9}  {'─'*8}  {'─'*9}  {'─'*5}")
    for cat, st in ev["desglose"].items():
        score_str = f"{st['score']:.1f}" if st["score"] is not None else "  N/A"
        cob_pct = f"{st['cobertura']*100:.0f}%" if st.get("cobertura") is not None else "  ?"
        print(
            f"  {cat:<16} {score_str:>6}  {cob_pct:>5}  {st['cumple']:>6}  "
            f"{st['no_cumple']:>9}  {st['dato_faltante']:>8}  {st['no_aplica']:>9}  {st['peso']:.2f}"
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

def main(pdf_path: Path, forzar: bool = False) -> None:
    print("=" * _ANCHO)
    print("PIPELINE MODULAR — PLIEGOS CONTRATACIÓN COLOMBIA")
    print("=" * _ANCHO)

    # [G1] El almacén antes que nada: si no hay respaldo hay que saberlo ANTES
    # de gastar, no después de perder la corrida.
    _estado = registro.estado_almacen()
    print(f"  Almacén: {_estado['ruta']}")
    if _estado["aviso"]:
        print(f"  AVISO  : {_estado['aviso']}")

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
    sha256_pliego = meta_p.get("sha256", "")
    nombre_resultado = f"{sha256_pliego or pdf_path.stem}_extraccion.json"
    ruta_salida = (
        Path(__file__).parent.parent
        / "resultados_evaluacion"
        / nombre_resultado
    )
    _validar_escritura(ruta_salida)
    print(f"  Resultado → {ruta_salida}")

    # [G1] GUARDA ANTES DE GASTAR. Si este pliego ya tiene extracción guardada
    # se reutiliza: volver a pagarla exige --forzar y queda en el historial.
    if sha256_pliego:
        registro.registrar_pliego(
            sha256_pliego, archivo=pdf_path.name, estado="parseado")
        registro.guardar_artefacto(
            sha256_pliego, "parseo",
            {"markdown": markdown, "metadata": meta_p},
            chars=len(markdown), paginas=meta_p.get("n_paginas"))

        permitido, motivo = registro.puede_extraer(sha256_pliego, forzar)
        print(f"  Guarda    : {motivo}")
        if not permitido:
            guardado = registro.cargar_artefacto(sha256_pliego, "extraccion")
            print(f"  Reutilizando {len(guardado.get('requisitos', []))} requisitos "
                  "ya pagados. El pipeline no llama a la API.")
            resultado = ResultadoExtraccion.model_validate(guardado)
            _reporte_extraccion(resultado, markdown, cobertura)
            return

    resultado = extraer(markdown, chunks, ruta_salida=ruta_salida, pliego_sha256=sha256_pliego)
    print(f"  Guardado  → {ruta_salida}")

    if sha256_pliego:
        # El artefacto CARO: requisitos crudos, tal como los devolvió el modelo.
        # No se guarda el consolidado — una versión nueva del catálogo
        # re-consolida desde aquí sin gastar API.
        datos = resultado.model_dump() if hasattr(resultado, "model_dump") else resultado
        mc = (datos.get("metadatos_corrida") or {})
        registro.guardar_artefacto(
            sha256_pliego, "extraccion", datos,
            costo_usd=mc.get("costo_usd", 0.0),
            requisitos=len(datos.get("requisitos") or []))
        registro.registrar_pliego(sha256_pliego, estado="extraido")

    # ── PASO 4: Verificación + reporte ───────────────────────────────────
    resultado = _reporte_extraccion(resultado, markdown, cobertura)

    # [I9-bis] Re-persistir con la verificación aplicada.
    #
    # PASO 3 guardó el JSON ANTES de que verificar_citas() y marcar_indices()
    # corrieran, así que el archivo que lee artefactos.py (y con él la app y el
    # chat) tenía estado_verificacion='no_verificada' y pagina_origen=None en
    # los 141 requisitos: el trabajo se hacía y el registro no lo reflejaba.
    # Sin esto no se puede afirmar "esta cita está verificada contra el
    # documento" ni decir en qué página buscarla.
    _repersistir_verificado(resultado, ruta_salida)

    # [G1-bis] El almacén también. El guardado del PASO 3 protege contra un
    # corte durante el reporte, pero conserva la versión ANTERIOR a
    # verificar_citas(): en la corrida de Ternera el disco quedó con 275/340
    # citas verificadas y el almacén con 0. Quien leyera del almacén no podría
    # afirmar que ninguna cita está verificada, que es lo contrario de la
    # verdad. Se sobrescribe con la versión verificada, mismo motivo que [I9].
    if sha256_pliego:
        datos_v = (resultado.model_dump() if hasattr(resultado, "model_dump")
                   else resultado)
        verificadas = sum(1 for r in (datos_v.get("requisitos") or [])
                          if r.get("cita_verificada"))
        registro.guardar_artefacto(
            sha256_pliego, "extraccion", datos_v,
            costo_usd=0.0,  # ya se contó en el PASO 3; no se duplica
            requisitos=len(datos_v.get("requisitos") or []),
            citas_verificadas=verificadas, verificacion_aplicada=True)
        print(f"  Almacén re-sincronizado con la verificación "
              f"({verificadas}/{len(datos_v.get('requisitos') or [])} citas)")

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

    # --forzar: vuelve a pagar una extracción que ya está guardada. Explícito
    # a propósito; queda anotado en el historial del pliego.
    main(pdf, forzar="--forzar" in sys.argv)
