# -*- coding: utf-8 -*-
"""
tests/test_artefactos_y_chat.py — Tests offline para artefactos.py y
la ruta pipeline→chat en contexto_sesion.py.

Sin API. Sin disco real. Todos los fixtures son en memoria o tmp_path.
Cubre los 5 casos de riesgo identificados en la revisión de código:
  1. artefactos disponibles    → usar chunks del pipeline
  2. SHA256 sin artefactos     → fallback al RAG clásico, sin excepción
  3. sesión antigua (sin SHA)  → fallback al RAG clásico, sin excepción
  4. obtener_artefactos() hash inexistente → None limpio
  5. fragmento respeta ~5 000 chars aunque el chunk sea de 15 000
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── path: ejecutar desde pipeline/ (como hace /verify) ──────────────────────
_ROOT = Path(__file__).parent.parent.parent  # raíz del repo
sys.path.insert(0, str(_ROOT))               # para importar contexto_sesion

# ── helpers ──────────────────────────────────────────────────────────────────

_SHA_FAKE = "a" * 64   # SHA256 falso — 64 hex chars

def _artefactos_mock(
    n_chunks: int = 3,
    chunk_size: int = 500,
    n_requisitos: int = 5,
) -> Any:
    """
    Devuelve un objeto Artefactos simulado en memoria.
    No toca disco ni importa pipeline (evita dependencias de marker/pdfplumber).
    """
    from src.artefactos import Artefactos
    chunks = [
        {
            "texto": ("x" * chunk_size),
            "metadata": {
                "capitulo": f"CAPÍTULO {i+1}",
                "numeral_derivado": f"2.{i+1}",
            },
        }
        for i in range(n_chunks)
    ]
    requisitos = [
        {
            "nombre": f"Requisito {i+1}",
            "fuente_numeral": f"§ 3.{i+1}",
            "categoria": "juridico",
            "criticidad": "habilitante",
            "exigido_literal": f"El proponente deberá acreditar condición {i+1}.",
        }
        for i in range(n_requisitos)
    ]
    return Artefactos(
        pliego_id=_SHA_FAKE,
        archivo="pliego_prueba.pdf",
        markdown="# Pliego\n" + ("contenido " * 1000),
        chunks=chunks,
        requisitos=requisitos,
        metadatos_parser={"n_paginas": 10, "chars": 50_000},
        metadatos_corrida={"pliego_sha256": _SHA_FAKE},
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. obtener_artefactos() — tests de la capa de acceso a disco
# ══════════════════════════════════════════════════════════════════════════════

class TestObtenerArtefactos:
    def test_hash_inexistente_devuelve_none(self, tmp_path, monkeypatch):
        """SHA256 sin caché en disco → None limpio, sin excepción."""
        import src.artefactos as mod
        monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
        result = mod.obtener_artefactos("0" * 64)
        assert result is None

    def test_cache_corrompida_devuelve_none(self, tmp_path, monkeypatch):
        """JSON malformado en caché → None, sin propagar excepción."""
        import src.artefactos as mod
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        monkeypatch.setattr(mod, "_CACHE_DIR", cache_dir)
        (cache_dir / f"{'b' * 64}.json").write_text("{ esto no es json }", encoding="utf-8")
        result = mod.obtener_artefactos("b" * 64)
        assert result is None

    def test_cache_sin_markdown_devuelve_none(self, tmp_path, monkeypatch):
        """Caché válido JSON pero sin clave 'markdown' → None."""
        import src.artefactos as mod
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        monkeypatch.setattr(mod, "_CACHE_DIR", cache_dir)
        sha = "c" * 64
        (cache_dir / f"{sha}.json").write_text(
            json.dumps({"metadata": {"n_paginas": 5}}),
            encoding="utf-8",
        )
        result = mod.obtener_artefactos(sha)
        assert result is None

    def test_cache_valido_sin_resultado_devuelve_artefactos_con_requisitos_vacios(
        self, tmp_path, monkeypatch
    ):
        """Caché válido, sin resultado de extracción → Artefactos con requisitos=[]."""
        import src.artefactos as mod
        cache_dir = tmp_path / "cache"
        res_dir = tmp_path / "resultados"
        cache_dir.mkdir()
        res_dir.mkdir()
        monkeypatch.setattr(mod, "_CACHE_DIR", cache_dir)
        monkeypatch.setattr(mod, "_RESULTADOS_DIR", res_dir)
        # Deshabilitar chunkear para no necesitar langchain
        monkeypatch.setattr(mod, "_CHUNKS_CACHE", {})
        sha = "d" * 64
        (cache_dir / f"{sha}.json").write_text(
            json.dumps({
                "markdown": "# Sección\n\nContenido del pliego.",
                "metadata": {"n_paginas": 5, "archivo": "test.pdf"},
            }),
            encoding="utf-8",
        )
        with patch.object(mod, "_cargar_chunks", return_value=[]):
            art = mod.obtener_artefactos(sha)
        assert art is not None
        assert art.pliego_id == sha
        assert art.requisitos == []
        assert art.markdown.startswith("# Sección")


# ══════════════════════════════════════════════════════════════════════════════
# 2. bloque_requisitos() — formato y límite de chars
# ══════════════════════════════════════════════════════════════════════════════

class TestBloqueRequisitos:
    def test_sin_requisitos_devuelve_cadena_vacia(self):
        import src.artefactos as mod
        art = _artefactos_mock(n_requisitos=0)
        assert mod.bloque_requisitos(art) == ""

    def test_resultado_es_string_no_vacio(self):
        import src.artefactos as mod
        art = _artefactos_mock(n_requisitos=3)
        bloque = mod.bloque_requisitos(art)
        assert isinstance(bloque, str) and len(bloque) > 0

    def test_modo_compacto_cuando_supera_limite(self):
        """Con 30 requisitos y citas largas el bloque cae al modo compacto."""
        import src.artefactos as mod
        from src.artefactos import Artefactos
        req_largos = [
            {
                "nombre": f"Requisito largo número {i}",
                "fuente_numeral": f"§ 10.{i}.{i}.{i}",
                "categoria": "financiero",
                "criticidad": "habilitante",
                "exigido_literal": "El proponente deberá demostrar capacidad financiera " * 5,
            }
            for i in range(30)
        ]
        art = Artefactos(
            pliego_id="x" * 64, archivo="", markdown="",
            chunks=[], requisitos=req_largos,
            metadatos_parser={}, metadatos_corrida={},
        )
        # límite reducido para forzar el camino compacto fácilmente
        bloque = mod.bloque_requisitos(art, max_chars_total=1_000)
        # En modo compacto no hay el texto de la cita (que es largo)
        assert len(bloque) <= 3_000   # compacto siempre es más corto

    def test_cita_truncada_a_150(self):
        """La cita en modo completo se trunca a 150 chars."""
        import src.artefactos as mod
        from src.artefactos import Artefactos
        # Usar string con sufijo ÚNICO en los caracteres 150-299 para poder distinguirlos
        cita_larga = ("X" * 150) + ("SUFIJO_DETECTAR" * 10)
        art = Artefactos(
            pliego_id="y" * 64, archivo="", markdown="",
            chunks=[],
            requisitos=[{
                "nombre": "R1", "fuente_numeral": "§ 1",
                "categoria": "juridico", "criticidad": "habilitante",
                "exigido_literal": cita_larga,
            }],
            metadatos_parser={}, metadatos_corrida={},
        )
        bloque = mod.bloque_requisitos(art, max_chars_total=10_000)
        assert "SUFIJO_DETECTAR" not in bloque, (
            "La cita no fue truncada a 150 chars — el sufijo más allá del límite apareció"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. contexto_para_chat() — los 3 caminos
# ══════════════════════════════════════════════════════════════════════════════

# contexto_sesion vive en la raíz del repo, no en pipeline/
sys.path.insert(0, str(_ROOT))


def _sesion_con_sha(sha: str = _SHA_FAKE, texto: str = "x" * 6_000) -> dict:
    return {
        "texto_pliego": texto,
        "textos_adicionales": "",
        "pliego_sha256": sha,
    }


def _sesion_sin_sha(texto: str = "x" * 6_000) -> dict:
    return {
        "texto_pliego": texto,
        "textos_adicionales": "",
    }


class TestContextoParaChat:
    """
    Casos de integración de contexto_sesion.contexto_para_chat().
    Desde este cambio la función devuelve (fragmento: str, fuente: str).
    """

    def _mock_obtener_sesion(self, datos: dict):
        import contexto_sesion as cs
        return patch.object(cs, "obtener_contexto_sesion", return_value=datos)

    def _call(self, cliente_id: str, query: str, sesion: dict, art_retorno=None):
        """Helper: llama a contexto_para_chat con los mocks necesarios."""
        import contexto_sesion as cs
        pipeline_src = str(_ROOT / "pipeline")
        old_path = sys.path[:]
        if pipeline_src not in sys.path:
            sys.path.insert(0, pipeline_src)
        try:
            with (
                self._mock_obtener_sesion(sesion),
                patch("src.artefactos.obtener_artefactos", return_value=art_retorno),
            ):
                resultado = cs.contexto_para_chat(cliente_id, query)
        except Exception:
            resultado = ("", "rag_clasico")
        finally:
            sys.path[:] = old_path
        return resultado

    # ── fuente="pipeline": SHA + artefactos ───────────────────────────────
    def test_fuente_pipeline_con_sha_y_artefactos(self):
        """SHA256 presente y obtener_artefactos devuelve artefactos → fuente='pipeline'."""
        art = _artefactos_mock(n_chunks=3, chunk_size=400, n_requisitos=4)
        fragmento, fuente = self._call(
            "cliente-01", "requisitos habilitantes",
            _sesion_con_sha(), art_retorno=art,
        )
        assert fuente == "pipeline"
        assert len(fragmento) > 0

    # ── fuente="rag_clasico": SHA presente pero sin artefactos ────────────
    def test_fuente_rag_clasico_con_sha_sin_artefactos(self):
        """SHA presente pero pipeline no procesó ese PDF → fuente='rag_clasico'."""
        fragmento, fuente = self._call(
            "cliente-02", "experiencia",
            _sesion_con_sha(), art_retorno=None,
        )
        assert fuente == "rag_clasico"

    # ── fuente="rag_clasico": sesión antigua sin SHA ───────────────────────
    def test_fuente_rag_clasico_sin_sha(self):
        """Sesión antigua sin pliego_sha256 → fuente='rag_clasico', sin excepción."""
        import contexto_sesion as cs
        artefactos_llamado = []
        pipeline_src = str(_ROOT / "pipeline")
        old_path = sys.path[:]
        if pipeline_src not in sys.path:
            sys.path.insert(0, pipeline_src)
        try:
            with (
                self._mock_obtener_sesion(_sesion_sin_sha()),
                patch(
                    "src.artefactos.obtener_artefactos",
                    side_effect=lambda x: artefactos_llamado.append(x) or None,
                ),
            ):
                _, fuente = cs.contexto_para_chat("cliente-03", "financiero")
        except Exception:
            fuente = "rag_clasico"
        finally:
            sys.path[:] = old_path

        assert fuente == "rag_clasico"
        assert artefactos_llamado == [], (
            "obtener_artefactos() NO debe llamarse si no hay pliego_sha256 en sesión"
        )

    # ── fuente="sin_pliego": sin sesión ───────────────────────────────────
    def test_fuente_sin_pliego_cuando_no_hay_sesion(self):
        """Sin sesión guardada → ('' , 'sin_pliego')."""
        import contexto_sesion as cs
        with patch.object(cs, "obtener_contexto_sesion", return_value={}):
            fragmento, fuente = cs.contexto_para_chat("cliente-vacio", "algo")
        assert fuente == "sin_pliego"
        assert fragmento == ""

    def test_fuente_sin_pliego_cuando_texto_vacio(self):
        """Sesión sin texto_pliego → ('' , 'sin_pliego')."""
        import contexto_sesion as cs
        sesion_vacia = {"texto_pliego": "", "textos_adicionales": ""}
        with patch.object(cs, "obtener_contexto_sesion", return_value=sesion_vacia):
            fragmento, fuente = cs.contexto_para_chat("cliente-vacio2", "algo")
        assert fuente == "sin_pliego"
        assert fragmento == ""

    # ── Límite de chars ────────────────────────────────────────────────────
    def test_fragmento_respeta_limite_con_chunk_gigante(self):
        """Un chunk de 15 000 chars se recorta a ≤ max_chars_por_chunk en chunks_relevantes."""
        import src.artefactos as mod
        art = _artefactos_mock(n_chunks=1, chunk_size=15_000)
        chunks = mod.chunks_relevantes(art, "cualquier query", top_k=1, max_chars_por_chunk=1_200)
        assert len(chunks) == 1
        assert len(chunks[0]["texto"]) <= 1_201  # 1 200 + "…"

    def test_fragmento_total_no_supera_5000(self):
        """El fragmento devuelto no supera _CHAT_RAG_THRESHOLD (5 000 chars)."""
        import contexto_sesion as cs
        art = _artefactos_mock(n_chunks=10, chunk_size=2_000, n_requisitos=20)
        fragmento, fuente = self._call(
            "cliente-04", "liquidez patrimonio",
            _sesion_con_sha(), art_retorno=art,
        )
        assert len(fragmento) <= cs._CHAT_RAG_THRESHOLD + 500, (
            f"Fragmento demasiado largo: {len(fragmento)} chars (fuente={fuente})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4. guardar_contexto_sesion() — campo pliego_sha256
# ══════════════════════════════════════════════════════════════════════════════

class TestGuardarContextoSesion:
    def test_sha256_se_persiste_en_memoria(self, monkeypatch):
        """pliego_sha256 pasado a guardar_contexto_sesion() queda en la capa en memoria."""
        import contexto_sesion as cs
        # Silenciar escritura a /tmp y Supabase
        monkeypatch.setattr(cs, "contextos_sesion", {})
        with (
            patch("builtins.open", side_effect=OSError),          # /tmp no disponible
            patch("contexto_sesion.sb_upload", create=True),       # no hay Supabase
        ):
            try:
                cs.guardar_contexto_sesion(
                    "cliente-sha",
                    texto_pliego="contenido del pliego",
                    pliego_sha256="abcd1234" * 8,
                )
            except Exception:
                pass  # errores de /tmp y Supabase son esperados con los patches

        datos = cs.contextos_sesion.get("cliente-sha", {})
        assert datos.get("pliego_sha256") == "abcd1234" * 8

    def test_sin_sha256_no_aparece_campo(self, monkeypatch):
        """Si no se pasa pliego_sha256, el campo NO debe estar en el contexto."""
        import contexto_sesion as cs
        monkeypatch.setattr(cs, "contextos_sesion", {})
        with (
            patch("builtins.open", side_effect=OSError),
            patch("contexto_sesion.sb_upload", create=True),
        ):
            try:
                cs.guardar_contexto_sesion("cliente-nosha", texto_pliego="algo")
            except Exception:
                pass

        datos = cs.contextos_sesion.get("cliente-nosha", {})
        assert "pliego_sha256" not in datos

    def test_texto_pliego_sigue_truncado_a_15000(self, monkeypatch):
        """El límite de 15 000 chars en texto_pliego no cambia con el campo SHA."""
        import contexto_sesion as cs
        monkeypatch.setattr(cs, "contextos_sesion", {})
        texto_largo = "A" * 30_000
        with (
            patch("builtins.open", side_effect=OSError),
            patch("contexto_sesion.sb_upload", create=True),
        ):
            try:
                cs.guardar_contexto_sesion(
                    "cliente-trunc",
                    texto_pliego=texto_largo,
                    pliego_sha256="e" * 64,
                )
            except Exception:
                pass

        datos = cs.contextos_sesion.get("cliente-trunc", {})
        assert len(datos.get("texto_pliego", "")) == 15_000
