# -*- coding: utf-8 -*-
"""
tests/test_main.py — end-to-end del orquestador main.py.

Estos tests prueban el FLUJO, no las funciones aisladas.
Las funciones individuales (extraer, verificar_citas, etc.) pasan sus propios
tests; lo que falló antes es que el orquestador nunca las encadenaba con
ruta_salida. Aquí se fija exactamente eso.

[I9a] main() siempre pasa ruta_salida a extraer() — resultado nunca se pierde
[I9b] Ruta no escribible → sys.exit(1) ANTES de invocar extraer() (sin gasto de API)
[FASE D] generar_aviso_verificacion() se muestra cuando hay citas sin verificar
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# pipeline/ al path para importar main y src.*
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extractor import Requisito, ResultadoExtraccion

# ─── helpers ───────────────────────────────────────────────────────────────

_META_DUMMY = {
    "chars": 200,
    "n_paginas": 3,
    "uso_ocr": False,
    "tiempo_s": 0.1,
    "desde_cache": True,
}

# Markdown que contiene la cita de los requisitos "verificados"
_MD = "## Sección\n\ndebe presentar certificado de existencia y representación legal"


def _resultado_minimo(n_no_verif: int = 0) -> ResultadoExtraccion:
    """ResultadoExtraccion construido sin API. Las citas verificadas sí aparecen en _MD."""
    verificadas = [
        Requisito(
            nombre=f"Certificado de existencia {i}",
            categoria="juridico",
            exigido_literal="debe presentar certificado de existencia",
            fuente_numeral=f"3.{i}",
        )
        for i in range(3)
    ]
    no_verificadas = [
        Requisito(
            nombre=f"Requisito sin cita {i}",
            categoria="financiero",
            exigido_literal="texto que no existe en el markdown fuente",
            fuente_numeral=f"4.{i}",
            criticidad="habilitante",
        )
        for i in range(n_no_verif)
    ]
    return ResultadoExtraccion(
        entidad_publica="Municipio de Prueba",
        numero_proceso="MP-001-2026",
        requisitos=verificadas + no_verificadas,
        checklist_no_encontrados=[],
        hallazgos_fuera_de_checklist=[],
        chunks_procesados=5,
        chunks_totales=5,
        truncamientos=[],
    )


# ─── (a) I9a — resultado queda en disco ────────────────────────────────────

class TestMainPersistencia:
    """
    [I9a] main() siempre pasa ruta_salida a extraer() y el archivo queda en disco.

    Bug que previene: main() no pasaba ruta_salida y el resultado de una corrida
    de $1.89 se perdió al terminar el proceso. Los tests de extraer() pasaban
    porque prueban la función aislada, no el flujo completo.
    """

    def test_a_archivo_creado_en_resultados_evaluacion(self, tmp_path):
        """
        main() con extractor simulado → existe un archivo JSON en resultados_evaluacion/.
        El artefacto se limpia al final del test.
        """
        import main as _main

        pdf = tmp_path / "_test_main_a.pdf"
        pdf.write_bytes(b"%PDF")

        resultado = _resultado_minimo()
        ruta_capturada: list[Path | None] = []

        def fake_extraer(markdown, chunks, api_key=None, ruta_salida=None, pliego_sha256=""):
            ruta_capturada.append(ruta_salida)
            if ruta_salida is not None:
                ruta_salida.parent.mkdir(parents=True, exist_ok=True)
                ruta_salida.write_text(resultado.model_dump_json(), encoding="utf-8")
            return resultado

        with (
            patch("main.parsear_pdf", return_value=(_MD, _META_DUMMY)),
            patch("main.chunkear", return_value=([{"texto": _MD, "metadata": {"capitulo": "TEST"}}], 100.0)),
            patch("main.extraer", side_effect=fake_extraer),
            patch("main._reporte_evaluacion"),  # evaluación no es el foco aquí
        ):
            _main.main(pdf)

        # ruta_salida NO fue None
        assert len(ruta_capturada) == 1, "extraer() no fue invocada"
        ruta = ruta_capturada[0]
        assert ruta is not None, (
            "[I9a ROTO] main() no pasó ruta_salida a extraer() — "
            "una corrida con costo de API perdería su resultado"
        )

        # El archivo existe en disco con contenido válido
        assert ruta.exists(), f"[I9a] Archivo no encontrado en disco: {ruta}"
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        assert datos["entidad_publica"] == "Municipio de Prueba"
        assert datos["numero_proceso"] == "MP-001-2026"

        ruta.unlink(missing_ok=True)


# ─── (b) I9b — aborta antes de gastar si la ruta no es escribible ──────────

class TestMainValidacionEscritura:
    """
    [I9b] Ruta no escribible → sys.exit(1) ANTES de invocar extraer().

    Esta es la propiedad central: si no se puede guardar el resultado, no se
    realiza ninguna llamada a la API. La validación ocurre en _validar_escritura()
    antes del PASO 3 / EXTRACCIÓN.
    """

    def test_b_aborta_antes_de_llamar_a_extraer(self, tmp_path):
        """
        PermissionError al escribir el archivo de prueba → sys.exit(1).
        extraer() no debe haber sido invocado ni una sola vez.
        """
        import main as _main

        pdf = tmp_path / "_test_main_b.pdf"
        pdf.write_bytes(b"%PDF")

        with (
            patch("main.parsear_pdf", return_value=(_MD, _META_DUMMY)),
            patch("main.chunkear", return_value=([{"texto": _MD, "metadata": {}}], 100.0)),
            # Simula disco protegido: la escritura del archivo de prueba falla
            patch.object(Path, "write_text", side_effect=PermissionError("disco protegido contra escritura")),
            patch("main.extraer") as mock_extraer,
        ):
            with pytest.raises(SystemExit) as exc_info:
                _main.main(pdf)

        assert exc_info.value.code == 1, (
            "[I9b] El proceso debe terminar con código 1 cuando la ruta no es escribible"
        )
        mock_extraer.assert_not_called()  # ← propiedad clave: sin gasto de API


# ─── (c) FASE D — aviso de verificación se muestra ─────────────────────────

class TestMainAvisoVerificacion:
    """
    [FASE D] generar_aviso_verificacion() se invoca cuando hay citas sin verificar.

    verificar_citas() corre sin mock — valida que las citas no presentes en el
    markdown producen estado_verificacion='no_verificada' y activan el aviso.
    """

    def test_c_aviso_aparece_con_citas_no_verificadas(self, tmp_path, capsys):
        """
        Con 2 requisitos cuya cita no aparece en el markdown, el bloque FASE D
        se imprime en stdout con el encabezado 'AVISO VERIFICACIÓN MANUAL [FASE D]'.
        """
        import main as _main

        pdf = tmp_path / "_test_main_c.pdf"
        pdf.write_bytes(b"%PDF")

        # 3 requisitos verificables + 2 cuyas citas no están en _MD
        resultado = _resultado_minimo(n_no_verif=2)
        ruta_capturada: list[Path | None] = []

        def fake_extraer(markdown, chunks, api_key=None, ruta_salida=None, pliego_sha256=""):
            ruta_capturada.append(ruta_salida)
            if ruta_salida is not None:
                ruta_salida.parent.mkdir(parents=True, exist_ok=True)
                ruta_salida.write_text(resultado.model_dump_json(), encoding="utf-8")
            return resultado

        with (
            patch("main.parsear_pdf", return_value=(_MD, _META_DUMMY)),
            patch("main.chunkear", return_value=([{"texto": _MD, "metadata": {"capitulo": "TEST"}}], 100.0)),
            patch("main.extraer", side_effect=fake_extraer),
            patch("main._reporte_evaluacion"),
        ):
            _main.main(pdf)

        salida = capsys.readouterr().out

        assert "AVISO VERIFICACIÓN MANUAL [FASE D]" in salida, (
            "[FASE D ROTO] El encabezado del aviso no apareció en stdout.\n"
            f"Salida real:\n{salida[-800:]}"
        )
        assert "VERIFICACIÓN MANUAL REQUERIDA" in salida, (
            "[FASE D] El cuerpo del aviso (generar_aviso_verificacion) no se imprimió"
        )
        assert "Requisito sin cita" in salida, (
            "[FASE D] Los nombres de requisitos no verificados deben aparecer en el aviso"
        )

        # Limpieza
        if ruta_capturada and ruta_capturada[0] is not None:
            ruta_capturada[0].unlink(missing_ok=True)


# ─── (d) marcar_indices está conectado al flujo ────────────────────────────

class TestMainMarcarIndicesConectado:
    """
    [2.3] marcar_indices() se invoca desde _reporte_extraccion().

    Bug que previene: la función existía, tenía tests, pero main.py no la
    llamaba — los requisitos de chunks que parecen TOC nunca se marcaban
    como 'probable_indice', y el aviso podía listar ítems que son entradas
    de índice, no exigencias reales.
    """

    def test_d_chunks_indice_quedan_marcados(self, tmp_path, capsys):
        """
        Un chunk con >50% de sus requisitos sin verificar queda marcado
        como 'probable_indice' — evidencia de que marcar_indices() corrió.
        """
        import main as _main
        from src.extractor import Requisito, ResultadoExtraccion

        pdf = tmp_path / "_test_main_d.pdf"
        pdf.write_bytes(b"%PDF")

        # Construir un resultado donde chunk_idx=0 tiene 3/3 requisitos no verificados.
        # Con >=3 requisitos y >50% no verificados, marcar_indices los marca como probable_indice.
        req_no_verif = [
            Requisito(
                nombre=f"Entrada de índice {i}",
                categoria="juridico",
                exigido_literal=f"3.{i} CAPACIDAD JURÍDICA..... {i * 10}",  # estilo TOC
                fuente_numeral=f"3.{i}",
            )
            for i in range(3)
        ]
        for r in req_no_verif:
            r.chunk_idx = 0  # todos del mismo chunk

        resultado = ResultadoExtraccion(
            entidad_publica="Municipio Test",
            numero_proceso="MT-001",
            requisitos=req_no_verif,
            checklist_no_encontrados=[],
            hallazgos_fuera_de_checklist=[],
            chunks_procesados=5,
            chunks_totales=5,
            truncamientos=[],
        )

        ruta_capturada: list = []

        def fake_extraer(markdown, chunks, api_key=None, ruta_salida=None, pliego_sha256=""):
            ruta_capturada.append(ruta_salida)
            if ruta_salida is not None:
                ruta_salida.parent.mkdir(parents=True, exist_ok=True)
                ruta_salida.write_text(resultado.model_dump_json(), encoding="utf-8")
            return resultado

        # El markdown NO contiene las citas TOC → todas quedarán no_verificadas
        md = "## Sección\n\nTexto real del pliego sin índice."

        with (
            patch("main.parsear_pdf", return_value=(md, _META_DUMMY)),
            patch("main.chunkear", return_value=([{"texto": md, "metadata": {"capitulo": "S"}}], 100.0)),
            patch("main.extraer", side_effect=fake_extraer),
            patch("main._reporte_evaluacion"),
        ):
            _main.main(pdf)

        marcados = [r for r in resultado.requisitos if r.origen == "probable_indice"]
        assert len(marcados) == 3, (
            "[2.3 ROTO] marcar_indices() no corrió o no marcó los requisitos TOC. "
            f"origen actual: {[r.origen for r in resultado.requisitos]}"
        )

        if ruta_capturada and ruta_capturada[0] is not None:
            ruta_capturada[0].unlink(missing_ok=True)
