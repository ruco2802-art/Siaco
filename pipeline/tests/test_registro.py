# -*- coding: utf-8 -*-
"""
Almacén y registro de corridas [G1].

Se perdieron dos corridas pagadas —404 requisitos de Paicol y 363 de Cravo
Norte por $1,61— porque nada las registró. Estos tests cubren las tres cosas
que lo habrían impedido: que la corrida quede anotada, que la segunda no
vuelva a pagar, y que la falta de respaldo se vea.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.src import registro  # noqa: E402

SHA = "a" * 64
OTRO = "b" * 64


@pytest.fixture
def almacen(tmp_path, monkeypatch):
    """Almacén aislado por test. Nunca toca el almacén real."""
    monkeypatch.setenv("SIACO_DATA_DIR", str(tmp_path))
    return tmp_path


# ─── Una corrida queda anotada ────────────────────────────────────────────────

def test_corrida_simulada_deja_entrada_y_artefactos(almacen):
    registro.registrar_pliego(
        SHA, archivo="29. PLIEGO DE CONDICIONES.pdf",
        entidad="Municipio de Paicol", numero_proceso="SAMC-001-2026",
        modalidad="obra_publica", estado="parseado")
    registro.guardar_artefacto(SHA, "parseo", {"markdown": "x" * 500})
    registro.guardar_artefacto(
        SHA, "extraccion",
        {"requisitos": [{"nombre": "Índice de liquidez"}]},
        costo_usd=1.06, requisitos=1)

    entrada = registro.pliego_registrado(SHA)
    assert entrada is not None
    assert entrada["archivo"] == "29. PLIEGO DE CONDICIONES.pdf"
    assert entrada["entidad"] == "Municipio de Paicol"
    assert entrada["costo_usd"] == 1.06
    assert set(entrada["artefactos"]) == {"parseo", "extraccion"}
    assert entrada["versiones"]["catalogo_objetos"]

    # Y los archivos están realmente en disco, no sólo en el índice
    assert registro.ruta_artefacto(SHA, "parseo").exists()
    assert registro.ruta_artefacto(SHA, "extraccion").exists()
    recuperado = registro.cargar_artefacto(SHA, "extraccion")
    assert recuperado["requisitos"][0]["nombre"] == "Índice de liquidez"


def test_el_costo_se_acumula_entre_artefactos(almacen):
    registro.guardar_artefacto(SHA, "extraccion", {"requisitos": []}, costo_usd=1.06)
    registro.guardar_artefacto(SHA, "conceptos", {"financiero": "x"}, costo_usd=0.06)
    assert registro.pliego_registrado(SHA)["costo_usd"] == 1.12


def test_solo_se_persiste_lo_caro(almacen):
    """La consolidación se regenera sin API: guardarla ataría el histórico."""
    with pytest.raises(ValueError, match="no es un artefacto caro"):
        registro.guardar_artefacto(SHA, "consolidacion", {"x": 1})  # type: ignore[arg-type]


# ─── [G1] Guarda antes de gastar ──────────────────────────────────────────────

def test_segunda_corrida_del_mismo_sha_no_permite_extraer(almacen):
    """El caso que evita volver a pagar $1,06 por lo mismo."""
    permitido, motivo = registro.puede_extraer(SHA)
    assert permitido is True and "Sin extracción previa" in motivo

    registro.guardar_artefacto(SHA, "extraccion", {"requisitos": [1, 2, 3]},
                               costo_usd=1.06)

    permitido, motivo = registro.puede_extraer(SHA)
    assert permitido is False
    assert "Ya existe extracción" in motivo and "reutiliza" in motivo


def test_forzar_permite_reextraer_y_queda_anotado(almacen):
    registro.guardar_artefacto(SHA, "extraccion", {"requisitos": []})
    permitido, motivo = registro.puede_extraer(SHA, forzar=True)
    assert permitido is True and "forzada" in motivo

    historial = registro.pliego_registrado(SHA)["historial"]
    assert any(h["evento"] == "re_extraccion_forzada" for h in historial), (
        "volver a pagar tiene que dejar rastro"
    )


def test_la_guarda_no_confunde_pliegos_distintos(almacen):
    registro.guardar_artefacto(SHA, "extraccion", {"requisitos": []})
    permitido, _ = registro.puede_extraer(OTRO)
    assert permitido is True


# ─── Sin respaldo: aviso visible ──────────────────────────────────────────────

def test_sin_siaco_data_dir_avisa(monkeypatch):
    monkeypatch.delenv("SIACO_DATA_DIR", raising=False)
    estado = registro.estado_almacen()
    assert estado["respaldado"] is False
    assert estado["aviso"] and "SIN respaldo" in estado["aviso"]
    assert "Paicol" in estado["aviso"], "el aviso debe recordar por qué existe"
    assert estado["aviso"] in registro.resumen()


def test_con_siaco_data_dir_no_avisa(almacen):
    estado = registro.estado_almacen()
    assert estado["respaldado"] is True
    assert estado["aviso"] is None
    assert str(almacen) == estado["ruta"]


def test_el_almacen_vive_fuera_del_repositorio(almacen):
    registro.guardar_artefacto(SHA, "parseo", {"markdown": "x"})
    ruta = registro.ruta_artefacto(SHA, "parseo")
    assert _ROOT not in ruta.parents, "el almacén no puede caer dentro del repo"


# ─── Público vs privado ───────────────────────────────────────────────────────

def test_artefactos_publicos_y_evaluaciones_privadas_no_se_mezclan(almacen):
    registro.guardar_artefacto(SHA, "parseo", {"markdown": "x"})
    registro.registrar_evaluacion(SHA, "cliente_001", veredicto="viable",
                                  resultado={"score": 88})

    publico = almacen / "publico"
    privado = almacen / "privado"
    assert registro.ruta_artefacto(SHA, "parseo").is_relative_to(publico)
    assert (registro.dir_evaluacion("cliente_001", SHA) / "resultado.json"
            ).is_relative_to(privado)
    # Ningún dato de cliente en el árbol público
    assert "cliente_001" not in json.dumps(
        registro.cargar_registro_pliegos(), ensure_ascii=False)


def test_una_evaluacion_se_reabre_sin_recalcular(almacen):
    """El historial guardaba dos scores; reabrir exigía volver a pagar."""
    resultado = {"score": 88, "tabla_comparativa": [{"requisito": "IDL"}]}
    registro.registrar_evaluacion(SHA, "cliente_001", veredicto="viable",
                                  resultado=resultado)
    assert registro.cargar_evaluacion("cliente_001", SHA) == resultado


def test_reevaluar_reemplaza_y_no_duplica(almacen):
    registro.registrar_evaluacion(SHA, "cliente_001", veredicto="viable")
    registro.registrar_evaluacion(SHA, "cliente_001", veredicto="no_viable")
    evals = registro.evaluaciones_de("cliente_001")
    assert len(evals) == 1 and evals[0]["veredicto"] == "no_viable"


def test_cada_cliente_ve_solo_lo_suyo(almacen):
    registro.registrar_evaluacion(SHA, "cliente_001", veredicto="viable",
                                  resultado={"score": 88})
    registro.registrar_evaluacion(SHA, "cliente_002", veredicto="no_viable",
                                  resultado={"score": 41})
    assert [e["cliente_id"] for e in registro.evaluaciones_de("cliente_001")] \
        == ["cliente_001"]
    assert registro.cargar_evaluacion("cliente_002", SHA) is not None
    assert registro.cargar_evaluacion("cliente_003", SHA) is None


# ─── Portafolio de demostración ───────────────────────────────────────────────

def test_el_portafolio_no_expone_clientes_reales(almacen):
    """Enseñar la evaluación de un cliente a un prospecto es filtrar sus datos."""
    registro.registrar_pliego(SHA, archivo="paicol.pdf")
    registro.registrar_evaluacion(SHA, "cliente_001", veredicto="viable",
                                  resultado={"score": 88})

    items = registro.portafolio()
    assert len(items) == 1
    assert items[0]["demo"] is False, "sin perfil ficticio no es presentable"
    assert "cliente_001" not in json.dumps(items, ensure_ascii=False)
    assert "88" not in json.dumps(items)


def test_el_portafolio_muestra_el_perfil_ficticio(almacen):
    registro.registrar_pliego(SHA, archivo="paicol.pdf", entidad="Paicol")
    registro.registrar_evaluacion(SHA, registro.CLIENTE_DEMO,
                                  veredicto="viable", resultado={"score": 88})
    item = registro.portafolio()[0]
    assert item["demo"] is True
    assert item["veredicto"] == "viable"
    assert item["entidad"] == "Paicol"


# ─── Robustez ─────────────────────────────────────────────────────────────────

def test_un_registro_corrupto_no_tumba_el_sistema(almacen):
    registro.registrar_pliego(SHA)
    (almacen / "publico" / "registro_pliegos.json").write_text("{roto", "utf-8")
    assert registro.cargar_registro_pliegos() == {}
    registro.registrar_pliego(OTRO)
    assert OTRO in registro.cargar_registro_pliegos()


def test_la_escritura_del_registro_es_atomica(almacen):
    """Sin temporal + replace, un corte deja ilegible el índice de lo pagado."""
    registro.registrar_pliego(SHA, archivo="uno.pdf")
    ruta = almacen / "publico" / "registro_pliegos.json"
    assert json.loads(ruta.read_text("utf-8"))[SHA]["archivo"] == "uno.pdf"
    assert not list(ruta.parent.glob("*.tmp")), "quedaron temporales sin limpiar"


# ─── [G1-bis] El almacén y el disco no pueden divergir ───────────────────────
#
# Tercera aparición del mismo patrón: "el trabajo se hace y el registro no lo
# refleja".
#   1. [I9]      el JSON del PASO 3 se escribía antes de verificar_citas()
#   2. [I9-bis]  se re-persistió el disco… pero no el almacén
#   3. [G1-bis]  la corrida de Ternera dejó 275/340 en disco y 0/340 en el
#                almacén. Quien leyera del almacén concluiría que ninguna cita
#                está verificada, que es lo contrario de la verdad.
#
# No basta con que cada destino guarde bien por separado: hay que comprobar que
# guardan LO MISMO.

def _tasa(datos: dict) -> float:
    reqs = datos.get("requisitos") or []
    if not reqs:
        return 0.0
    return sum(1 for r in reqs if r.get("cita_verificada")) / len(reqs)


def test_almacen_y_disco_tienen_la_misma_tasa_de_verificacion(almacen, tmp_path):
    """
    Corrida simulada completa: extracción → persistencia → verificación →
    re-persistencia en LOS DOS destinos.
    """
    # 1 · Extracción: nada verificado todavía
    crudo = {
        "requisitos": [
            {"nombre": f"Requisito {i}", "exigido_literal": f"texto {i}",
             "cita_verificada": False}
            for i in range(10)
        ],
        "metadatos_corrida": {"costo_usd": 1.06},
    }
    disco = tmp_path / "extraccion.json"
    disco.write_text(json.dumps(crudo, ensure_ascii=False), encoding="utf-8")
    registro.guardar_artefacto(SHA, "extraccion", crudo, costo_usd=1.06)

    # 2 · Verificación: 7 de 10 resisten
    verificado = json.loads(json.dumps(crudo))
    for r in verificado["requisitos"][:7]:
        r["cita_verificada"] = True

    # 3 · Re-persistencia en LOS DOS destinos, como hace pipeline/main.py
    disco.write_text(json.dumps(verificado, ensure_ascii=False), encoding="utf-8")
    registro.guardar_artefacto(SHA, "extraccion", verificado, costo_usd=0.0,
                               verificacion_aplicada=True)

    en_disco = json.loads(disco.read_text("utf-8"))
    en_almacen = registro.cargar_artefacto(SHA, "extraccion")
    assert _tasa(en_disco) == _tasa(en_almacen) == 0.7, (
        f"divergencia: disco {_tasa(en_disco):.1%} vs "
        f"almacén {_tasa(en_almacen):.1%}"
    )
    # Y el costo no se contó dos veces
    assert registro.pliego_registrado(SHA)["costo_usd"] == 1.06


def test_el_almacen_sin_resincronizar_se_detecta(almacen, tmp_path):
    """
    Prueba de saboteo: si `[G1-bis]` se quitara, este test debe fallar.
    Simula la corrida de Ternera tal como ocurrió.
    """
    crudo = {"requisitos": [{"nombre": "x", "cita_verificada": False}] * 10}
    registro.guardar_artefacto(SHA, "extraccion", crudo)

    verificado = {"requisitos": [{"nombre": "x", "cita_verificada": True}] * 10}
    disco = tmp_path / "extraccion.json"
    disco.write_text(json.dumps(verificado), encoding="utf-8")
    # A propósito NO se re-sincroniza el almacén

    assert _tasa(json.loads(disco.read_text("utf-8"))) == 1.0
    assert _tasa(registro.cargar_artefacto(SHA, "extraccion")) == 0.0, (
        "el escenario de la divergencia ya no se reproduce"
    )


def test_pipeline_main_resincroniza_el_almacen():
    """
    [conexión] El arreglo tiene que estar en el entrypoint, no sólo aquí.
    Un test que valide el patrón sin que el pipeline lo aplique no protege.
    """
    src = (_ROOT / "pipeline" / "main.py").read_text("utf-8")
    i_repersistir = src.index("_repersistir_verificado(resultado, ruta_salida)")
    resto = src[i_repersistir:]
    assert "G1-bis" in resto, "falta la re-sincronización del almacén"
    assert "citas_verificadas=verificadas" in resto
    # Y después de la verificación, no antes
    assert resto.index("guardar_artefacto") > 0
