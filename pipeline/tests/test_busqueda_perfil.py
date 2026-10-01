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


def test_la_familia_abre_la_puerta_y_el_contenido_la_confirma():
    """
    [D40 corregido] Coincidir de FAMILIA no basta por sí solo: la familia
    `7215` incluye `721515` (albañilería) y `721540` (climatización), así que
    abrir sólo por familia devolvía refrigeración a una constructora.

    Y no se puede arbitrar con la semántica: medido sobre los procesos de
    prueba, «papelería» da coseno 0,32 contra la consulta de la constructora y
    «obra civil para adecuación de aulas» da 0,25. La semántica ordena, no
    decide.
    """
    fuente = Path(__file__).resolve().parents[2] / "analizador.py"
    codigo = fuente.read_text("utf-8")
    assert "mismo_sector = (score_familia == 1.0" in codigo
    assert "and score_keywords >= 2 / KEYWORDS_PARA_TOPE)" in codigo, (
        "una sola palabra genérica —«mantenimiento»— volvería a colar "
        "refrigeración en una constructora")
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
    assert '"avisos": avisos' in codigo, (
        "los avisos tienen que viajar en la respuesta, no sólo al log")
    assert 'logger.error("[BUSQUEDA] El scoring por perfil falló' in codigo
    # [D45] Y una sola función hace el scoring: arreglar una copia dejaba las
    # otras rotas, que es cómo el filtrado estuvo apagado sin que se notara.
    assert codigo.count("busqueda_hibrida_triple(") == 1, (
        "volvió a haber más de una copia del scoring")
    assert codigo.count("aplicar_scoring_perfil(") >= 4, (
        "los tres endpoints tienen que llamar a la función única")


# ── [D41] Las keywords vienen del sector, no de una constante ──────────────

def test_sin_sector_declarado_no_hay_keywords():
    """
    Un conjunto por defecto repetiría exactamente el error que esto corrige:
    las 54 palabras de climatización se inyectaban a todos los clientes.
    """
    from analizador import keywords_de_sector
    assert keywords_de_sector(None) == []
    assert keywords_de_sector("") == []
    assert keywords_de_sector("   ") == []


def test_un_sector_sin_lista_revisada_tampoco_recibe_keywords():
    """Las palabras deciden qué procesos ve un cliente: no se ponen a ojo."""
    from analizador import keywords_de_sector
    assert keywords_de_sector("tecnologia") == []
    assert keywords_de_sector("salud") == []


def test_cada_sector_recibe_las_suyas_y_no_las_de_otro():
    from analizador import keywords_de_sector
    obra = keywords_de_sector("obras_civiles")
    hvac = keywords_de_sector("hvac")
    assert "placa huella" in obra and "polideportivo" in obra
    assert "climatizacion" in hvac and "cuarto frio" in hvac
    # el defecto original: HVAC en el perfil de una constructora
    assert not any(k in obra for k in ("climatizacion", "hvac", "refrigeracion"))
    # y «aire» suelto salió de la lista: aparece en demasiados contextos ajenos
    assert "aire" not in hvac


def test_el_puntaje_de_keywords_se_normaliza_por_tope_no_por_tamano():
    """
    Antes era `matches / len(lista)`: una lista de 24 términos que describe
    bien el sector daba 0,04 por acierto y una de 5 daba 0,20. **El perfil que
    mejor se describía salía peor puntuado.**
    """
    from analizador import KEYWORDS_PARA_TOPE, puntaje_keywords
    assert KEYWORDS_PARA_TOPE == 3
    assert puntaje_keywords(0) == 0.0
    assert round(puntaje_keywords(1), 3) == 0.333
    assert round(puntaje_keywords(2), 3) == 0.667
    assert puntaje_keywords(3) == 1.0
    assert puntaje_keywords(9) == 1.0, "más de tres no puede pasar del tope"


def test_config_legacy_ya_no_alimenta_el_scoring():
    fuente = Path(__file__).resolve().parents[2] / "analizador.py"
    codigo = fuente.read_text("utf-8")
    # El nombre puede seguir en un comentario que explica el defecto; lo que
    # no puede volver es el IMPORT que lo alimentaba.
    assert "from config_legacy import KEYWORDS_HVAC" not in codigo, (
        "las keywords de un cliente concreto volvieron al scoring de todos")
    assert "keywords_de_sector(perfil_cliente.get(\"sector\"))" in codigo, (
        "las keywords dejaron de salir del sector declarado en el perfil")


# ── [D42] Un solo lector, una sola ruta ────────────────────────────────────

def test_el_evaluador_no_cae_al_perfil_de_sesion():
    """
    [D42b] `clientes/{cid}/perfil.json` es el perfil de SESIÓN —cliente_id,
    plan, contacto—. `PerfilEmpresa` lo validaba sin protestar, así que el
    evaluador leía CREDENCIALES y marcaba los 91 requisitos como
    `dato_faltante` sin decir que había leído el archivo equivocado.
    """
    import json

    from src.evaluator import cargar_perfil_por_cid

    base = Path(__file__).resolve().parents[2] / "clientes"
    # un cliente con perfil de sesión pero SIN perfil de empresa
    sesion = base / "_test_solo_sesion" / "perfil.json"
    sesion.parent.mkdir(parents=True, exist_ok=True)
    sesion.write_text(json.dumps(
        {"cliente_id": "_test_solo_sesion", "nombre": "_test_solo_sesion",
         "plan": "socio"}), encoding="utf-8")
    try:
        assert cargar_perfil_por_cid("_test_solo_sesion") is None, (
            "volvió el respaldo al perfil de sesión: el evaluador está "
            "leyendo credenciales y llamándolas perfil de empresa")
    finally:
        sesion.unlink(missing_ok=True)
        sesion.parent.rmdir()


def test_la_ruta_de_la_verdad_esta_definida_en_un_solo_sitio():
    """[D42c] Todos los módulos derivan la ruta del mismo sitio."""
    from src.perfil import ruta_perfil_cliente
    assert ruta_perfil_cliente("x").name == "x.json"
    assert ruta_perfil_cliente("x").parent.name == "clientes"


def test_no_quedan_copias_del_camino_de_lectura():
    """
    [D42c] Había tres: routers/perfil.py, gestor_documentos.py y
    routers/generador_oferta.py. «¿Qué perfil usa el sistema?» dependía de
    qué módulo preguntara.
    """
    raiz = Path(__file__).resolve().parents[2]
    for rel in ("gestor_documentos.py", "routers/generador_oferta.py"):
        codigo = (raiz / rel).read_text("utf-8")
        assert "/tmp/siaco/" not in codigo or "perfil.json" not in codigo, (
            f"{rel} vuelve a construir el camino de lectura por su cuenta")
        assert "from routers.perfil import _load_perfil" in codigo, (
            f"{rel} no delega en el lector único")


# ── [D42a] El selector de perfil ───────────────────────────────────────────

def test_el_selector_lista_los_perfiles_de_empresa_no_los_de_sesion():
    """
    `clientes/{cid}.json` son perfiles de empresa; `clientes/{cid}/` guarda el
    de sesión. Mezclarlos ofrecería «cliente_001» como si fuera una empresa.
    """
    from src.perfil import perfiles_disponibles
    perfiles = perfiles_disponibles()
    cids = {p["cid"] for p in perfiles}
    assert "demo_ejemplo" in cids
    for p in perfiles:
        assert p["nombre"], f"{p['cid']} sin nombre: el selector no se puede leer"


def test_el_perfil_activo_manda_sobre_el_de_la_sesion():
    """
    [D42a] Un operador maneja varios perfiles. Si la sesión decidiera, el
    selector no serviría para nada.
    """
    from src.perfil import cliente_id_activo
    assert cliente_id_activo({"cliente_id": "op", "perfil_activo": "demo_ejemplo"}) \
        == "demo_ejemplo"
    assert cliente_id_activo({"cliente_id": "op"}) == "op"
    assert cliente_id_activo({"id": "op"}) == "op"
    assert cliente_id_activo({}) == ""


def test_una_sola_funcion_resuelve_el_cliente_activo():
    """[I11] Si cada router lo resolviera a su manera, podrían discrepar."""
    raiz = Path(__file__).resolve().parents[2]
    for rel in ("routers/perfil.py", "routers/auditoria.py"):
        codigo = (raiz / rel).read_text("utf-8")
        assert 'sesion.get("cliente_id") or sesion.get("id") or ""' not in codigo \
            or "cliente_id_activo" in codigo, (
            f"{rel} resuelve el cliente por su cuenta, sin pasar por "
            "cliente_id_activo()")


def test_no_se_puede_buscar_ni_analizar_sin_perfil_elegido():
    js = (Path(__file__).resolve().parents[2] / "static" / "app.js").read_text("utf-8")
    assert "function exigePerfilActivo(" in js
    for fn in ("buscarContratos", "analizarConIA", "analizarPliego"):
        i = js.index(f"async function {fn}(")
        assert "exigePerfilActivo" in js[i:i + 400], (
            f"{fn} no exige perfil activo: devolvería resultados que no se "
            "pueden explicar")


def test_los_alias_de_sector_cubren_los_perfiles_existentes():
    """
    Los perfiles creados antes del desplegable traen el sector en texto libre.
    Sin alias se quedarían sin palabras clave y nadie lo notaría: el filtrado
    seguiría funcionando, peor.
    """
    from analizador import keywords_de_sector
    for libre in ("OBRA PUBLICA", "MANTENIMIENTO LOCATIVO Y OBRAS CIVILES",
                  "HVAC", "Climatización"):
        assert keywords_de_sector(libre), f"«{libre}» se queda sin keywords"


# ── El sector sin palabras clave se AVISA, no se calla ─────────────────────

def test_un_sector_sin_lista_produce_un_aviso_con_el_texto_exacto():
    """
    Quedarse en cero era invisible: la búsqueda seguía funcionando, peor, y
    nadie lo notaba. Es el mismo patrón que [I10] llevado al sitio donde el
    usuario puede corregirlo.
    """
    from analizador import estado_keywords_sector
    r = estado_keywords_sector("metalmecanica")
    assert r["estado"] == "sin_lista"
    assert r["n_terminos"] == 0
    assert r["aviso"] == ("El sector «metalmecanica» no tiene palabras clave "
                          "asociadas; el filtrado por contenido no se aplicará.")


def test_sin_sector_el_aviso_dice_otra_cosa():
    """No es lo mismo no declararlo que declararlo y que falte la lista."""
    from analizador import estado_keywords_sector
    for vacio in (None, "", "   "):
        r = estado_keywords_sector(vacio)
        assert r["estado"] == "sin_sector"
        assert "no declara sector" in r["aviso"]


def test_un_sector_con_lista_no_avisa():
    """Un aviso que sale siempre deja de leerse."""
    from analizador import estado_keywords_sector
    r = estado_keywords_sector("obras_civiles")
    assert r["estado"] == "ok" and r["aviso"] is None and r["n_terminos"] >= 20
    # y por alias también
    assert estado_keywords_sector("OBRA PUBLICA")["estado"] == "ok"


def test_el_aviso_viaja_al_guardar_y_al_buscar():
    raiz = Path(__file__).resolve().parents[2]
    perfil = (raiz / "routers" / "perfil.py").read_text("utf-8")
    assert "estado_keywords_sector" in perfil, "guardar no avisa"
    busqueda = (raiz / "routers" / "busqueda.py").read_text("utf-8")
    assert "estado_keywords_sector" in busqueda, "buscar no avisa"
    js = (raiz / "static" / "app.js").read_text("utf-8")
    assert "data.avisos" in js or "data.aviso_sector" in js, (
        "el aviso no llega a la pantalla")


def test_el_desplegable_y_las_listas_no_se_separan():
    """
    Una opción del desplegable sin lista deja al cliente sin filtrado por
    palabras, y una lista que el desplegable no ofrece es trabajo inútil.
    Las que no tienen lista lo DICEN en su propio texto.
    """
    import json
    import re

    raiz = Path(__file__).resolve().parents[2]
    datos = json.loads((raiz / "pipeline" / "data" / "keywords_sector.json")
                       .read_text("utf-8"))
    listas = {k for k, v in datos.items() if isinstance(v, list)}

    html = (raiz / "static" / "index.html").read_text("utf-8")
    i = html.index('id="p-sector"')
    # Hasta el </select>, no una ventana de N caracteres: con una ventana se
    # colaban las opciones del desplegable siguiente (notificaciones).
    bloque = html[i:html.index("</select>", i)]
    opciones = dict(re.findall(r'<option value="([^"]+)">([^<]*)</option>', bloque))

    assert not (listas - set(opciones)), (
        f"listas que el desplegable no ofrece: {sorted(listas - set(opciones))}")
    for valor, etiqueta in opciones.items():
        if valor not in listas:
            assert "sin palabras clave" in etiqueta.lower(), (
                f"la opción «{valor}» no tiene lista y no lo dice: el cliente "
                "la elegiría sin saber que pierde el filtrado por contenido")
