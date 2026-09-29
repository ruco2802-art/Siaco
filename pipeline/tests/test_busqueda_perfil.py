# -*- coding: utf-8 -*-
"""
Tests del filtrado de procesos por perfil del cliente.

Viven aquí y no en los tests del pipeline porque lo que protegen es una
decisión de producto: **qué procesos se le muestran a un cliente y por qué**.
Un filtro que descarta de más deja pasar una oportunidad; uno que descarta de
menos hace que el sistema parezca sin criterio.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from analizador import DIGITOS_UNSPSC, normalizar_codigos_unspsc  # noqa: E402


# ── [D39] Las dos formas del campo ─────────────────────────────────────────

def test_codigos_unspsc_acepta_lista_y_cadena_igual():
    """
    El esquema canónico declara `list[str]`; el formulario web manda una
    cadena separada por comas. Las dos son legítimas y **tienen que dar el
    mismo resultado**: antes, la lista producía prefijos basura (`"['7"`) y
    pasaban 0 de 10 procesos, en silencio.
    """
    lista = normalizar_codigos_unspsc(["72151500", "72141100", "72101500"])
    cadena = normalizar_codigos_unspsc("72151500,72141100,72101500")
    assert lista == cadena == ["721515", "721411", "721015"]


def test_la_conversion_de_lista_a_texto_no_deja_prefijos_basura():
    """El caso exacto que fallaba: `str(lista)` con corchetes y comillas."""
    assert normalizar_codigos_unspsc(str(["72151500", "72141100"])) == \
        ["721515", "721411"]


def test_formas_raras_no_producen_codigos_invalidos():
    assert normalizar_codigos_unspsc(None) == []
    assert normalizar_codigos_unspsc("") == []
    assert normalizar_codigos_unspsc("   ,  ,") == []
    # un código demasiado corto no da una clase: se descarta en vez de
    # inventar un prefijo que casaría con media base de datos
    assert normalizar_codigos_unspsc("7215") == []
    assert normalizar_codigos_unspsc(["7215", "72151500"]) == ["721515"]
    # separadores alternativos y duplicados
    assert normalizar_codigos_unspsc("72151500; 72151501") == ["721515"]


# ── [D40] Seis dígitos, no cuatro ──────────────────────────────────────────

def test_se_comparan_seis_digitos_la_clase_no_la_familia():
    """
    En UNSPSC 4 dígitos son la FAMILIA y 6 la CLASE. Con 4, `7215` cubría a la
    vez `72151500` (albañilería) y `72154000` (climatización), y una
    constructora traía procesos de refrigeración con puntaje 1,00.
    """
    assert DIGITOS_UNSPSC == 6, (
        "bajar a 4 vuelve a mezclar albañilería con aire acondicionado; "
        "subir a 8 exige que el pliego use el mismo código de producto que "
        "el RUP, y casi nunca coincide")
    obra = normalizar_codigos_unspsc("72151500")
    hvac = normalizar_codigos_unspsc("72154000")
    assert obra != hvac, "6 dígitos tienen que separar albañilería de HVAC"
    assert obra[0][:4] == hvac[0][:4] == "7215", (
        "con 4 dígitos serían el mismo: eso era el defecto")


def test_una_coincidencia_de_clase_ya_no_pasa_sola():
    """
    [D40] Antes `score_unspsc == 1.0` pasaba sin mirar nada más: una
    similitud se convertía en certeza. Ahora pesa mucho (0,45) pero necesita
    sumar con keywords o semántica.
    """
    fuente = Path(__file__).resolve().parents[2] / "analizador.py"
    codigo = fuente.read_text("utf-8")
    assert "pasa = score_final > 0.50 or score_keywords > 0.60" in codigo
    assert "or score_unspsc == 1.0" not in codigo, (
        "volvió el paso incondicional por UNSPSC")


# ── [D39] El fallo del scoring no se calla ─────────────────────────────────

def test_el_fallo_del_scoring_se_reporta_no_se_traga():
    """
    Un `except Exception: pass` convertía cualquier fallo en «no hay filtrado
    por perfil» sin decirlo: el operador veía todos los procesos sin saber
    que su perfil no se había aplicado.
    """
    fuente = Path(__file__).resolve().parents[2] / "routers" / "busqueda.py"
    codigo = fuente.read_text("utf-8")
    assert "pass  # fallback: all contratos_pre are relevant" not in codigo
    assert "aviso_scoring" in codigo, (
        "el aviso tiene que viajar en la respuesta, no sólo al log")
    assert 'logger.error("[BUSQUEDA] El scoring por perfil falló' in codigo
