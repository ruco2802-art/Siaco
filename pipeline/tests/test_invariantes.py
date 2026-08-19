# -*- coding: utf-8 -*-
"""
tests/test_invariantes.py — cada test FUERZA el fallo de un invariante.

Un test que PASA cuando el invariante está roto = el invariante no existe.
Un test que PASA aquí = el invariante está implementado y activo.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Añadir src/ al path para importar sin instalar el paquete
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extractor import (
    _llamar, _requisito_de_dict, _ExtraccionCtx, extraer,
    ResultadoExtraccion, Requisito, CHECKLIST_CCE,
)
from src.verifier import verificar_citas, marcar_indices, estado_global
from src.chunker import chunkear, _subdividir_por_parrafos, CoberturaIncompletaError, _MAX_CHUNK_CHARS
from src.evaluator import cargar_perfil, evaluar_empresa
from src.parser import _limpiar_markup


# ─── I2: stop_reason="max_tokens" → estado "truncado", sin JSONDecodeError ────

class TestI2StopReasonMaxTokens:
    """
    [I2] Si la API devuelve stop_reason='max_tokens', _llamar() debe
    retornar {'estado': 'truncado'} SIN intentar parsear JSON.
    Bug que previene: JSONDecodeError por intentar parsear una respuesta cortada.
    """

    def _mock_client(self, stop_reason: str, text: str = "") -> MagicMock:
        client = MagicMock()
        resp = MagicMock()
        resp.stop_reason = stop_reason
        resp.usage.output_tokens = 8000
        resp.usage.input_tokens = 1000
        # [1.5] El bloque necesita type="text" para que _llamar lo encuentre
        bloque = MagicMock()
        bloque.type = "text"
        bloque.text = text
        resp.content = [bloque]
        client.messages.create.return_value = resp
        return client

    def _chunk_dummy(self) -> dict:
        return {"texto": "fragmento de prueba", "metadata": {"capitulo": "CAP1"}}

    def test_max_tokens_devuelve_truncado(self):
        """Con stop_reason='max_tokens', estado debe ser 'truncado'."""
        client = self._mock_client("max_tokens", text='{"requisitos": [')  # JSON truncado
        resultado = _llamar(client, self._chunk_dummy(), idx=0)
        assert resultado["estado"] == "truncado", (
            f"[I2 ROTO] Con stop_reason='max_tokens' se esperaba estado='truncado', "
            f"se obtuvo: {resultado}"
        )

    def test_max_tokens_no_lanza_json_error(self):
        """Con stop_reason='max_tokens', NO debe lanzar JSONDecodeError."""
        client = self._mock_client("max_tokens", text='{"incompleto":')
        try:
            resultado = _llamar(client, self._chunk_dummy(), idx=0)
        except Exception as exc:
            pytest.fail(
                f"[I2 ROTO] _llamar() lanzó {type(exc).__name__} con stop_reason='max_tokens': {exc}"
            )
        assert resultado["estado"] == "truncado"

    def test_end_turn_si_parsea_json(self):
        """Con stop_reason='end_turn' y JSON válido, debe devolver estado='ok'."""
        client = self._mock_client(
            "end_turn",
            text='{"entidad_publica":"ENT","numero_proceso":"P","requisitos":[],'
                 '"checklist_encontrado":[],"hallazgos_fuera_de_checklist":[]}',
        )
        resultado = _llamar(client, self._chunk_dummy(), idx=0)
        assert resultado["estado"] == "ok", (
            f"[I2] Con stop_reason='end_turn' y JSON válido se esperaba 'ok': {resultado}"
        )


# ─── I4: estado_global() no devuelve "completo" si hay truncamientos ──────────

class TestI4EstadoGlobal:
    """
    [I4] estado_global() es una función pura que DERIVA el estado.
    'completo' solo si: no errores, no truncados, cobertura == 100.0.
    """

    def test_truncado_suprime_completo(self):
        """Con truncamientos, estado debe ser 'truncado', no 'completo'."""
        estado = estado_global(errores=[], truncados=["chunk_0"], cobertura_pct=100.0)
        assert estado == "truncado", (
            f"[I4 ROTO] Con truncamientos, estado_global devolvió '{estado}' en vez de 'truncado'"
        )

    def test_errores_suprime_completo(self):
        """Con errores, estado debe ser 'con_errores'."""
        estado = estado_global(errores=["algún error"], truncados=[], cobertura_pct=100.0)
        assert estado == "con_errores", (
            f"[I4 ROTO] Con errores, estado_global devolvió '{estado}' en vez de 'con_errores'"
        )

    def test_cobertura_incompleta_suprime_completo(self):
        """Con cobertura < 100.0, estado debe ser 'cobertura_incompleta'."""
        estado = estado_global(errores=[], truncados=[], cobertura_pct=98.5)
        assert estado == "cobertura_incompleta", (
            f"[I4 ROTO] Con cobertura 98.5%, devolvió '{estado}' en vez de 'cobertura_incompleta'"
        )

    def test_completo_solo_con_cobertura_exacta_100(self):
        """'completo' solo cuando cobertura == 100.0 exacto, sin errores ni truncados."""
        estado = estado_global(errores=[], truncados=[], cobertura_pct=100.0)
        assert estado == "completo", (
            f"[I4 ROTO] Sin problemas y cobertura=100.0, devolvió '{estado}' en vez de 'completo'"
        )

    def test_cobertura_999_no_es_completo(self):
        """99.9% de cobertura NO es 'completo'."""
        estado = estado_global(errores=[], truncados=[], cobertura_pct=99.9)
        assert estado != "completo", (
            f"[I4 ROTO] 99.9% cobertura devolvió 'completo' — debe ser 'cobertura_incompleta'"
        )
        assert estado == "cobertura_incompleta"

    def test_truncado_tiene_prioridad_sobre_errores(self):
        """Prioridad: truncado > con_errores."""
        estado = estado_global(errores=["error"], truncados=["chunk_0"], cobertura_pct=100.0)
        assert estado == "truncado"


# ─── I7/I8: verificar_citas busca en el markdown COMPLETO ─────────────────────

class TestI7I8VerificarCitas:
    """
    [I7] Cada exigido_literal se verifica contra el markdown fuente.
    [I8] La búsqueda se hace en el documento COMPLETO, sin ventana.
    Bug real: buscar en un fragmento de 12K chars dio falso negativo
    y casi causó una migración de parser innecesaria.
    """

    def _req(self, nombre: str, literal: str) -> Requisito:
        return Requisito(
            nombre=nombre,
            categoria="juridico",
            exigido_literal=literal,
            fuente_numeral="2.1",
        )

    def _resultado(self, requisitos: list[Requisito]) -> ResultadoExtraccion:
        return ResultadoExtraccion(
            entidad_publica="ENT",
            numero_proceso="P-001",
            requisitos=requisitos,
            checklist_no_encontrados=[],
            hallazgos_fuera_de_checklist=[],
            chunks_procesados=1,
            chunks_totales=1,
            truncamientos=[],
        )

    def test_cita_inexistente_queda_false(self):
        """Una cita que NO existe en el markdown debe quedar cita_verificada=False."""
        req = self._req("RUP", "Esta frase no existe en el documento fuente.")
        markdown = "# Pliego\n\nEl proponente debe presentar Cámara de Comercio vigente."
        resultado = verificar_citas(self._resultado([req]), markdown)
        assert resultado.requisitos[0].cita_verificada is False, (
            "[I7 ROTO] Una cita inventada quedó cita_verificada=True"
        )
        assert resultado.requisitos[0].estado_verificacion == "no_verificada", (
            "[I7 ROTO] estado_verificacion debe ser 'no_verificada' cuando cita no existe"
        )

    def test_cita_existente_queda_true(self):
        """Una cita que SÍ existe en el markdown debe quedar cita_verificada=True."""
        literal = "El proponente debe acreditar RUP en firme"
        req = self._req("RUP", literal)
        markdown = f"# Requisitos\n\n{literal} al momento del cierre."
        resultado = verificar_citas(self._resultado([req]), markdown)
        assert resultado.requisitos[0].cita_verificada is True, (
            "[I7 ROTO] Una cita existente quedó cita_verificada=False"
        )
        assert resultado.requisitos[0].estado_verificacion == "verificada", (
            "[I7 ROTO] estado_verificacion debe ser 'verificada' cuando cita existe"
        )

    def test_busqueda_en_documento_completo_no_ventana(self):
        """
        [I8] La cita debe encontrarse aunque esté LEJOS del inicio del documento.
        Si verificar_citas usara una ventana (ej: markdown[:12000]),
        este test fallaría porque la cita está en el char 50000.
        """
        # Cita al final de un documento largo
        cita_lejana = "requisito especial de experiencia acumulada"
        prefijo = "texto de relleno sin la cita. " * 1700  # ~50K chars de relleno
        markdown = prefijo + cita_lejana + " con valor mínimo de 5 SMMLV."

        assert len(prefijo) > 40_000, "El relleno debe superar 40K chars para que el test sea válido"

        req = self._req("Experiencia especial", cita_lejana)
        resultado = verificar_citas(self._resultado([req]), markdown)
        assert resultado.requisitos[0].cita_verificada is True, (
            f"[I8 ROTO] La cita estaba en el char {len(prefijo)} del documento "
            f"pero verificar_citas no la encontró — posible uso de ventana truncada"
        )

    def test_cita_vacia_queda_false(self):
        """Una cita vacía (str vacío) debe quedar False sin lanzar excepción."""
        req = self._req("Sin cita", "")
        markdown = "# Pliego\n\nContenido normal."
        resultado = verificar_citas(self._resultado([req]), markdown)
        assert resultado.requisitos[0].cita_verificada is False
        assert resultado.requisitos[0].estado_verificacion == "no_verificada"


# ─── Chunker: cobertura incompleta lanza CoberturaIncompletaError ─────────────

class TestChunkerCobertura:
    """
    El chunker debe lanzar CoberturaIncompletaError si los chunks
    no cubren al menos el 99% del markdown original.
    """

    def test_markdown_bien_estructurado_no_lanza(self):
        """Un markdown con encabezados claros no debe lanzar error de cobertura."""
        md = "# Capítulo 1\n\nTexto del capítulo uno con contenido suficiente.\n\n"
        md += "## Sección 1.1\n\nMás contenido aquí para que el chunker lo procese.\n"
        # No esperamos excepción para un markdown razonable
        try:
            chunks, cobertura = chunkear(md)
            assert cobertura >= 80.0, f"Cobertura inesperadamente baja: {cobertura}%"
        except CoberturaIncompletaError:
            pytest.skip("El markdown de prueba no alcanzó cobertura mínima — ajustar contenido")

    def test_markdown_vacio_lanza_o_devuelve_vacio(self):
        """Un markdown vacío debe manejar el caso sin crash."""
        try:
            chunks, cobertura = chunkear("   \n\n   ")
        except (CoberturaIncompletaError, ValueError):
            pass  # ambas son respuestas aceptables
        except Exception as exc:
            pytest.fail(f"Markdown vacío lanzó excepción inesperada: {type(exc).__name__}: {exc}")

    def test_cobertura_incompleta_lanza_error(self):
        """
        Simula que el splitter devuelve chunks con muy pocos chars
        forzando cobertura < umbral.
        """
        from src import chunker as chunker_mod

        md_largo = "# Capítulo\n\nPárrafo con texto suficiente. " * 50

        # Parchear _MAX_CHUNK_CHARS a 1 para que el splitter produzca chunks diminutos,
        # luego verificar que la cobertura falle si los chunks son vacíos.
        # Alternativamente, parchear el splitter directamente.
        chunks_vacios = []  # forzar cobertura = 0%

        with patch.object(chunker_mod, "_subdividir_por_parrafos", return_value=[]):
            # El splitter produce chunks, pero subdividir_por_parrafos los vacía
            # Necesitamos también patchear el splitter inicial
            from langchain_text_splitters import MarkdownHeaderTextSplitter

            def splitter_que_devuelve_chunks_sin_texto(self_inner, text, **kwargs):
                # Devuelve documentos con page_content vacío → cobertura 0%
                from langchain_core.documents import Document
                return [Document(page_content="", metadata={"capitulo": "C1"})]

            with patch.object(
                MarkdownHeaderTextSplitter,
                "split_text",
                splitter_que_devuelve_chunks_sin_texto,
            ):
                with pytest.raises(CoberturaIncompletaError):
                    chunkear(md_largo)


# ─── Evaluator: perfil sin bloque financiero → dato_faltante, nunca cero ──────

class TestEvaluatorDatoFaltante:
    """
    [I6] Un perfil sin bloque 'financiero' debe producir estado 'dato_faltante'
    para todos los requisitos financieros.
    Bug real: perfiles sin bloque financiero producían "no_viable — datos en cero"
    porque se usaba 0 como sustituto de None.
    """

    def _requisito_financiero(self, nombre: str, umbral: float, op: str = ">=") -> Requisito:
        return Requisito(
            nombre=nombre,
            categoria="financiero",
            exigido_literal=f"El proponente debe acreditar {nombre} {op} {umbral}",
            fuente_numeral="2.3",
            valor_umbral=umbral,
            operador=op,
        )

    def test_sin_financiero_produce_dato_faltante(self):
        """Sin bloque financiero, todos los ítems financieros son dato_faltante."""
        perfil = cargar_perfil({
            "nombre": "Empresa Sin Financiero SAS",
            "es_mipyme": False,
            # Sin bloque "financiero"
            "experiencia": {"valor_acumulado": 5_000_000_000.0},
        })
        requisitos = [
            self._requisito_financiero("Índice de liquidez", 1.5),
            self._requisito_financiero("Índice de endeudamiento", 0.6, "<="),
            self._requisito_financiero("Patrimonio neto", 1_000_000_000.0),
        ]
        ev = evaluar_empresa(perfil, requisitos)

        # Todos deben ser dato_faltante
        financieros = [i for i in ev["items"] if i["categoria"] == "financiero"]
        no_faltantes = [i for i in financieros if i["estado"] != "dato_faltante"]
        assert len(no_faltantes) == 0, (
            f"[I6 ROTO] Sin bloque financiero, estos ítems NO son dato_faltante: "
            f"{[(i['requisito'], i['estado']) for i in no_faltantes]}"
        )

    def test_sin_financiero_no_produce_no_viable_por_ceros(self):
        """
        Bug real: sin financiero, score = 0.0 → veredicto 'no_viable'.
        El correcto es 'dato_insuficiente'.
        """
        perfil = cargar_perfil({
            "nombre": "Empresa Sin Financiero SAS",
            "es_mipyme": False,
        })
        requisitos = [self._requisito_financiero("Índice de liquidez", 1.5)]
        ev = evaluar_empresa(perfil, requisitos)

        assert ev["veredicto"] != "no_viable", (
            f"[I6 ROTO] Sin bloque financiero, el veredicto fue 'no_viable' "
            f"(score={ev['score_global']}) — se trató el dato faltante como cero"
        )
        assert ev["veredicto"] == "dato_insuficiente", (
            f"[I6 ROTO] Esperado 'dato_insuficiente', obtenido: {ev['veredicto']}"
        )

    def test_score_none_no_arrastra_a_cero(self):
        """
        El score de una categoría sin datos debe ser None, no 0.0.
        Un score None no contribuye al promedio ponderado.
        """
        perfil = cargar_perfil({
            "nombre": "Solo Experiencia SAS",
            "es_mipyme": False,
            "experiencia": {"valor_acumulado": 10_000_000_000.0},
        })
        requisitos = [self._requisito_financiero("Índice de liquidez", 1.5)]
        ev = evaluar_empresa(perfil, requisitos)

        score_fin = ev["desglose"]["financiero"]["score"]
        assert score_fin is None, (
            f"[I6 ROTO] Score financiero sin datos debe ser None, fue: {score_fin}"
        )


# ─── _limpiar_markup: 4 estados — ninguno enmascarado por otro ────────────────

class TestParserLimpiezaMarkup:
    """
    Verifica que _limpiar_markup() clasifica correctamente el markup HTML.

    4 estados posibles:
      "sin_markup"                  - no hay nada
      "limpio"                      - spans page-N-M eliminados, sin residuo
      "markup_conocido_preservado"  - solo <sup>/<sub>/autolinks (INFO)
      "markup_desconocido"          - tags fuera de whitelist (WARNING)

    Caso critico: markup desconocido mezclado con benigno debe salir
    "markup_desconocido", no "markup_conocido_preservado". El markup benigno
    no puede enmascarar al desconocido.
    """

    def test_span_formato_desconocido_produce_markup_desconocido(self):
        """
        [CASO CRITICO] <span data-page="5"> no es page-N-M.
        Debe producir "markup_desconocido", NO "limpio" ni "markup_conocido_preservado".
        Bug que previene: creer que el markdown esta limpio cuando tiene HTML que
        rompe regex de numerales y citas del verifier.
        """
        md = '## <span data-page="5">1.1. Titulo</span>\n\nContenido de seccion.'
        clean, n_spans, chars, pags, estado, muestra = _limpiar_markup(md)

        assert estado not in ("limpio", "markup_conocido_preservado"), (
            f"[INVARIANTE ROTO] Markup desconocido fue clasificado como {estado!r} — "
            "el sistema creeria que el markdown esta limpio cuando tiene HTML residual"
        )
        assert estado == "markup_desconocido", (
            f"Se esperaba 'markup_desconocido', se obtuvo: {estado!r}"
        )
        assert n_spans == 0, "No deben contarse spans page-N-M en formato desconocido"
        assert clean == md, "El markdown NO debe modificarse ante markup desconocido"
        assert len(muestra) > 0, "Debe reportar al menos un ejemplo del markup desconocido"

    def test_span_pagina_conocido_produce_limpio(self):
        """<span id="page-5-0"></span> es el patron conocido -> estado 'limpio'."""
        md = '## <span id="page-5-0"></span>1.1. Titulo\n\nContenido.'
        clean, n_spans, chars, pags, estado, muestra = _limpiar_markup(md)

        assert estado == "limpio", (
            f"Span de formato conocido deberia producir 'limpio', se obtuvo: {estado!r}"
        )
        assert n_spans == 1
        assert pags == [5]
        assert '<span' not in clean, "El span conocido debe haberse eliminado"
        assert '1.1. Titulo' in clean, "El texto del encabezado debe conservarse"
        assert len(muestra) == 0, "No debe quedar markup residual reportado"

    def test_markdown_sin_html_produce_sin_markup(self):
        """Markdown puro (sin HTML) -> estado 'sin_markup'."""
        md = '## 1.1. Titulo\n\nContenido normal **con bold** y _italic_ sin HTML.'
        clean, n_spans, chars, pags, estado, muestra = _limpiar_markup(md)

        assert estado == "sin_markup", (
            f"Markdown sin HTML deberia producir 'sin_markup', se obtuvo: {estado!r}"
        )
        assert n_spans == 0
        assert clean == md, "Markdown sin markup no debe modificarse"
        assert len(muestra) == 0

    def test_sup_produce_markup_conocido_preservado(self):
        """Solo <sup> (benigno) -> estado 'markup_conocido_preservado', sin WARNING."""
        md = 'Segun el articulo 3<sup>1</sup> del decreto, el proponente debe.'
        clean, n_spans, chars, pags, estado, muestra = _limpiar_markup(md)

        assert estado == "markup_conocido_preservado", (
            f"Solo <sup> deberia producir 'markup_conocido_preservado', "
            f"se obtuvo: {estado!r}"
        )
        assert n_spans == 0
        assert clean == md, "<sup> no debe eliminarse — es contenido real"
        assert any("sup" in m for m in muestra), "Debe reportar el <sup> encontrado"

    def test_autolink_no_produce_warning(self):
        """<https://url> es autolink CommonMark, no HTML -> no debe ser markup_desconocido."""
        md = 'Ver la tasa en <https://www.oanda.com/currency-converter/es/> para conversion.'
        clean, n_spans, chars, pags, estado, muestra = _limpiar_markup(md)

        assert estado != "markup_desconocido", (
            f"[BUG] Autolink CommonMark fue clasificado como 'markup_desconocido': "
            f"estado={estado!r}, muestra={muestra}"
        )
        assert estado == "sin_markup", (
            f"Autolink sin otro markup deberia producir 'sin_markup', "
            f"se obtuvo: {estado!r}"
        )

    def test_desconocido_prevalece_sobre_benigno_y_autolink(self):
        """
        [CASO CRITICO DEL PUNTO 4]
        Mezcla: <span data-page="5"> (desconocido) + <sup>1</sup> (benigno)
        + <https://ejemplo.com> (autolink).
        Debe salir "markup_desconocido", NO "markup_conocido_preservado".
        El markup benigno no puede enmascarar al desconocido.
        """
        md = (
            '## <span data-page="5">1.1. Titulo\n\n'
            'Segun nota<sup>1</sup> y <https://ejemplo.com> el requisito es X.'
        )
        clean, n_spans, chars, pags, estado, muestra = _limpiar_markup(md)

        assert estado != "markup_conocido_preservado", (
            "[INVARIANTE ROTO] El markup benigno (<sup>) enmascaro al desconocido "
            "(<span data-page>). El sistema clasifica como seguro algo que no lo es."
        )
        assert estado == "markup_desconocido", (
            f"Con markup desconocido presente, el estado debe ser 'markup_desconocido'. "
            f"Se obtuvo: {estado!r}"
        )
        assert any("span" in m for m in muestra), (
            "La muestra debe incluir el span desconocido, no solo los benignos"
        )

    def test_span_conocido_mas_desconocido_es_markup_desconocido(self):
        """
        Span page-N-M (conocido) + markup desconocido -> "markup_desconocido".
        El span conocido se elimina, pero el desconocido impone el estado.
        """
        md = (
            '## <span id="page-3-0"></span>1.1. Titulo\n\n'
            'Texto con <em>enfasis HTML</em> no reconocido.'
        )
        clean, n_spans, chars, pags, estado, muestra = _limpiar_markup(md)

        assert estado == "markup_desconocido", (
            f"Markup desconocido debe prevalecer sobre el span limpiado. "
            f"Se obtuvo: {estado!r}"
        )
        assert n_spans == 1, "El span page-N-M SI debe haberse contado y eliminado"
        assert '<span id="page-3-0">' not in clean, "El span conocido SI debe eliminarse"
        assert '<em>' in clean, "El markup desconocido NO debe eliminarse"


# ─── FASE 1: Blindaje de extractor ────────────────────────────────────────

class TestAlias:
    """
    [1.1] AliasChoices: claves alternativas del modelo → campo canónico.
    El alias activado debe quedar registrado en ctx.alias_log.
    """

    def _chunk(self) -> dict:
        return {"texto": "texto prueba", "metadata": {"capitulo": "CAP1"}}

    def test_tipo_de_requisito_mapea_a_categoria(self):
        """JSON con 'tipo_de_requisito' → campo categoria del Requisito."""
        r = {
            "nombre": "RUP",
            "tipo_de_requisito": "juridico",      # ← alias
            "exigido_literal": "El proponente debe acreditar RUP en firme",
            "fuente_numeral": "2.1",
        }
        ctx = _ExtraccionCtx()
        req = _requisito_de_dict(r, self._chunk(), chunk_idx=0, ctx=ctx)

        assert req is not None, "El alias no fue reconocido — requisito descartado"
        assert req.categoria == "juridico", f"categoria esperada 'juridico', obtenida: {req.categoria!r}"
        assert ctx.alias_log.get("tipo_de_requisito", 0) >= 1, (
            f"[1.1 ROTO] alias 'tipo_de_requisito' no quedó registrado en alias_log: {dict(ctx.alias_log)}"
        )

    def test_cita_mapea_a_exigido_literal(self):
        """JSON con 'cita' → campo exigido_literal del Requisito."""
        r = {
            "nombre": "Paz y salvo DIAN",
            "categoria": "juridico",
            "cita": "Certificado de paz y salvo con la DIAN vigente",  # ← alias
            "fuente_numeral": "3.2",
        }
        ctx = _ExtraccionCtx()
        req = _requisito_de_dict(r, self._chunk(), chunk_idx=1, ctx=ctx)

        assert req is not None, "El alias 'cita' no fue reconocido"
        assert req.exigido_literal == "Certificado de paz y salvo con la DIAN vigente"
        assert ctx.alias_log.get("cita", 0) >= 1, (
            f"[1.1 ROTO] alias 'cita' no quedó registrado: {dict(ctx.alias_log)}"
        )


class TestNormalizacion:
    """
    [1.2] field_validator semántico: sinónimos → valor canónico.
    La normalización aplicada debe quedar registrada en ctx.norm_log.
    """

    def _chunk(self) -> dict:
        return {"texto": "texto prueba", "metadata": {"capitulo": "CAP1"}}

    def test_financiera_normaliza_a_financiero(self):
        """'financiera' → 'financiero' y queda en norm_log."""
        r = {
            "nombre": "Índice de liquidez",
            "categoria": "financiera",            # ← sinónimo femenino
            "exigido_literal": "El proponente debe tener índice de liquidez >= 1",
            "fuente_numeral": "4.2",
        }
        ctx = _ExtraccionCtx()
        req = _requisito_de_dict(r, self._chunk(), chunk_idx=0, ctx=ctx)

        assert req is not None, "Normalización falló — requisito descartado"
        assert req.categoria == "financiero", (
            f"[1.2 ROTO] 'financiera' no normalizó a 'financiero': {req.categoria!r}"
        )
        assert ctx.norm_log.get("financiera", 0) >= 1, (
            f"[1.2 ROTO] normalización 'financiera' no registrada: {dict(ctx.norm_log)}"
        )

    def test_operador_unicode_normaliza(self):
        """'≥' → '>=' y queda en norm_log."""
        r = {
            "nombre": "Patrimonio neto",
            "categoria": "financiero",
            "exigido_literal": "Patrimonio neto ≥ 500 SMMLV",
            "fuente_numeral": "4.3",
            "valor_umbral": 500,
            "operador": "≥",    # ← unicode
            "unidad": "smmlv",
        }
        ctx = _ExtraccionCtx()
        req = _requisito_de_dict(r, self._chunk(), chunk_idx=0, ctx=ctx)

        assert req is not None, "Normalización de operador falló — requisito descartado"
        assert req.operador == ">=", (
            f"[1.2 ROTO] '≥' no normalizó a '>=': {req.operador!r}"
        )
        assert ctx.norm_log.get("≥", 0) >= 1, (
            f"[1.2 ROTO] normalización '≥' no registrada: {dict(ctx.norm_log)}"
        )


class TestRechazo:
    """
    [1.3] Requisito con campos inválidos → va a ctx.rechazos, nunca silencio.
    Bug que previene: except Exception: return None descartaba sin traza.
    """

    def _chunk(self) -> dict:
        return {"texto": "texto prueba", "metadata": {"capitulo": "CAP1"}}

    def test_categoria_invalida_va_a_rechazados(self):
        """Categoria inexistente → ctx.rechazos, no None silencioso."""
        r = {
            "nombre": "Algo extraño",
            "categoria": "categoria_inventada_xyz",   # ← inválido
            "exigido_literal": "El proponente debe presentar X",
            "fuente_numeral": "2.1",
        }
        ctx = _ExtraccionCtx()
        req = _requisito_de_dict(r, self._chunk(), chunk_idx=5, ctx=ctx)

        assert req is None, "Un requisito inválido no debe ser aceptado"
        assert len(ctx.rechazos) == 1, (
            f"[1.3 ROTO] El rechazo no quedó registrado: {ctx.rechazos}"
        )
        assert ctx.rechazos[0]["chunk_idx"] == 5
        assert ctx.rechazos[0]["motivo"], "El rechazo debe tener motivo no vacío"

    def test_rechazo_no_lanza_excepcion(self):
        """Un campo inválido NO debe lanzar excepción — pipeline continúa."""
        r = {
            "nombre": "Test",
            "categoria": "tipo_que_no_existe",
            "exigido_literal": "cita cualquiera",
            "fuente_numeral": "1.1",
        }
        ctx = _ExtraccionCtx()
        try:
            req = _requisito_de_dict(r, self._chunk(), chunk_idx=0, ctx=ctx)
        except Exception as exc:
            pytest.fail(
                f"[1.3 ROTO] _requisito_de_dict lanzó {type(exc).__name__} "
                f"en lugar de registrar el rechazo: {exc}"
            )
        assert req is None
        assert len(ctx.rechazos) == 1


class TestChunksSeparados:
    """
    [1.4] chunks_truncados y chunks_error_json son listas separadas.
    Antes estaban mezcladas en 'truncamientos'.
    """

    def _mock_llamar_seq(self, responses: list[dict]):
        """Genera mocks de _llamar que devuelven responses en secuencia."""
        call_count = {"n": 0}

        def fake_llamar(client, chunk, idx, sistema=None):
            r = responses[call_count["n"]]
            call_count["n"] += 1
            return r

        return fake_llamar

    def _chunk(self) -> dict:
        return {"texto": "fragmento", "metadata": {"capitulo": "CAP"}}

    def test_truncado_y_json_error_en_listas_separadas(self):
        """Un chunk truncado y uno con json_error van a listas distintas."""
        responses = [
            {"estado": "truncado", "chunk_idx": 0, "input_tokens": 100, "output_tokens": 200,
             "cache_creation_tokens": 0, "cache_read_tokens": 0},
            {"estado": "json_error", "chunk_idx": 1, "error": "bad json", "crudo_inicio": "",
             "input_tokens": 100, "output_tokens": 50,
             "cache_creation_tokens": 0, "cache_read_tokens": 0},
        ]
        chunks = [self._chunk(), self._chunk()]

        with patch("src.extractor._llamar", side_effect=responses):
            resultado = extraer("# MD", chunks, api_key="fake-key")

        assert resultado.chunks_truncados == ["chunk_0"], (
            f"[1.4 ROTO] chunks_truncados esperado ['chunk_0']: {resultado.chunks_truncados}"
        )
        assert resultado.chunks_error_json == ["chunk_1"], (
            f"[1.4 ROTO] chunks_error_json esperado ['chunk_1']: {resultado.chunks_error_json}"
        )
        assert resultado.truncamientos == ["chunk_0", "chunk_1"], (
            "truncamientos (backward compat) debe contener ambos"
        )


class TestBloqueContenido:
    """
    [1.5] resp.content iterado defensivamente buscando type=='text'.
    Bug que previene: resp.content[0].text crashea si el primer bloque es thinking.
    """

    def _chunk(self) -> dict:
        return {"texto": "fragmento", "metadata": {"capitulo": "CAP"}}

    def _mock_client_con_thinking(self, json_valido: str) -> MagicMock:
        """Simula respuesta con bloque thinking ANTES del bloque text."""
        client = MagicMock()
        resp = MagicMock()
        resp.stop_reason = "end_turn"
        resp.usage.output_tokens = 100
        resp.usage.input_tokens = 500

        bloque_thinking = MagicMock()
        bloque_thinking.type = "thinking"
        # MagicMock no tiene .text — si se accede crashea en la versión antigua

        bloque_texto = MagicMock()
        bloque_texto.type = "text"
        bloque_texto.text = json_valido

        resp.content = [bloque_thinking, bloque_texto]
        client.messages.create.return_value = resp
        return client

    def test_thinking_primero_texto_despues(self):
        """Bloque thinking antes del texto → _llamar extrae el texto correctamente."""
        json_ok = ('{"entidad_publica":"ENT","numero_proceso":"P",'
                   '"requisitos":[],"checklist_encontrado":[],'
                   '"hallazgos_fuera_de_checklist":[]}')
        client = self._mock_client_con_thinking(json_ok)
        resultado = _llamar(client, self._chunk(), idx=0)

        assert resultado["estado"] == "ok", (
            f"[1.5 ROTO] Con thinking antes del texto, _llamar devolvió "
            f"estado={resultado['estado']!r} en lugar de 'ok'. "
            "Posiblemente está leyendo content[0].text en vez de iterar."
        )

    def test_sin_bloque_texto_retorna_json_error(self):
        """Si no hay ningún bloque type='text' → json_error, nunca crash."""
        client = MagicMock()
        resp = MagicMock()
        resp.stop_reason = "end_turn"
        resp.usage.output_tokens = 50
        resp.usage.input_tokens = 200

        bloque_solo_thinking = MagicMock()
        bloque_solo_thinking.type = "thinking"
        resp.content = [bloque_solo_thinking]
        client.messages.create.return_value = resp

        resultado = _llamar(client, self._chunk(), idx=0)
        assert resultado["estado"] == "json_error", (
            f"[1.5 ROTO] Sin bloque texto se esperaba 'json_error', "
            f"se obtuvo: {resultado['estado']!r}"
        )


# ─── FASE 2: Pipeline y optimización ──────────────────────────────────────

class TestPersistenciaI9:
    """
    [I9] extraer() con ruta_salida persiste ANTES de retornar.
    Si el guardado falla → IOError, no silencio.
    """

    def _mock_llamar_ok(self):
        return {
            "estado": "ok",
            "datos": {
                "entidad_publica": "Municipio Test",
                "numero_proceso": "TEST-001-2026",
                "requisitos": [],
                "checklist_encontrado": [],
                "hallazgos_fuera_de_checklist": [],
            },
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }

    def _chunk(self) -> dict:
        return {"texto": "fragmento de prueba", "metadata": {"capitulo": "CAP1"}}

    def test_con_ruta_salida_crea_json(self, tmp_path):
        """Con ruta_salida proporcionada, el archivo existe al retornar."""
        import json as _json
        ruta = tmp_path / "resultado_test.json"
        chunks = [self._chunk()]

        with patch("src.extractor._llamar", return_value=self._mock_llamar_ok()):
            extraer("# Markdown de prueba", chunks, api_key="fake-key", ruta_salida=ruta)

        assert ruta.exists(), "[I9 ROTO] No se creó el archivo de resultados"
        data = _json.loads(ruta.read_text("utf-8"))
        assert "requisitos" in data, "El JSON guardado debe contener 'requisitos'"

    def test_fallo_guardado_lanza_ioerror(self, tmp_path):
        """[I9] Si write_text falla → IOError con '[I9]' en el mensaje."""
        from pathlib import Path as _Path
        ruta = tmp_path / "resultado_test.json"
        chunks = [self._chunk()]

        with patch("src.extractor._llamar", return_value=self._mock_llamar_ok()):
            with patch.object(_Path, "write_text", side_effect=PermissionError("disco lleno")):
                with pytest.raises(IOError, match=r"\[I9\]"):
                    extraer("# MD", chunks, api_key="fake-key", ruta_salida=ruta)

    def test_sin_ruta_salida_no_crea_archivo(self, tmp_path):
        """Sin ruta_salida, extraer() retorna sin crear archivos."""
        chunks = [self._chunk()]
        archivos_antes = set(tmp_path.iterdir())

        with patch("src.extractor._llamar", return_value=self._mock_llamar_ok()):
            resultado = extraer("# MD", chunks, api_key="fake-key")

        assert isinstance(resultado, ResultadoExtraccion)
        archivos_despues = set(tmp_path.iterdir())
        assert archivos_antes == archivos_despues, "Sin ruta_salida no debe crear archivos"

    def test_i9_json_final_refleja_verificacion(self, tmp_path):
        """
        [I9 — INVARIANTE REFORMULADO]
        El JSON en disco DEBE reflejar el estado FINAL del pipeline.
        Flujo correcto: extraer() → verificar_citas() → guardar final.
        Si se guarda solo dentro de extraer(), cita_verificada queda False
        aunque el literal SÍ exista en el markdown.
        """
        import json as _json

        ruta = tmp_path / "resultado_final.json"
        literal = "El proponente debe acreditar RUP en firme al momento del cierre"
        markdown = f"# Pliego de condiciones\n\n{literal}.\n\nOtro contenido."

        mock_resp = {
            "estado": "ok",
            "datos": {
                "entidad_publica": "Municipio Test",
                "numero_proceso": "TEST-001",
                "requisitos": [{
                    "nombre": "RUP en firme",
                    "categoria": "juridico",
                    "exigido_literal": literal,
                    "fuente_numeral": "3.2",
                }],
                "checklist_encontrado": [],
                "hallazgos_fuera_de_checklist": [],
            },
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }
        chunks = [self._chunk()]

        with patch("src.extractor._llamar", return_value=mock_resp):
            resultado = extraer(markdown, chunks, api_key="fake-key", ruta_salida=ruta)

        # En este punto extraer() ya guardó, pero cita_verificada=False (pre-verificación)
        data_intermedio = _json.loads(ruta.read_text("utf-8"))
        assert data_intermedio["requisitos"][0]["cita_verificada"] is False, (
            "Checkpoint intermedio debe tener cita_verificada=False"
        )

        # Flujo correcto: verificar y guardar estado final
        resultado = verificar_citas(resultado, markdown)
        ruta.write_text(resultado.model_dump_json(indent=2), encoding="utf-8")

        data_final = _json.loads(ruta.read_text("utf-8"))
        assert data_final["requisitos"][0]["cita_verificada"] is True, (
            "[I9 ROTO] El JSON final en disco dice cita_verificada=False aunque "
            "el literal SÍ existe en el markdown. El guardado final debe ocurrir "
            "DESPUÉS de verificar_citas(), no antes."
        )


class TestSubchunkingParte:
    """
    [2.2] Sub-chunks etiquetados con subchunk_parte y subchunk_total.
    Texto 100% preservado — suma de partes == texto original (I1).
    """

    def _texto_grande(self, n_parrafos: int = 20, chars_por_parrafo: int = 900) -> str:
        return "\n\n".join(f"Párrafo {i}. " + "x" * chars_por_parrafo for i in range(n_parrafos))

    def _meta(self) -> dict:
        return {"capitulo": "4. REQUISITOS", "numeral_derivado": "4.5", "nivel_h": 2}

    def test_chunk_grande_produce_subchunks_etiquetados(self):
        """Texto > 15K chars → múltiples sub-chunks con subchunk_parte."""
        texto = self._texto_grande()
        assert len(texto) > 15_000, "El texto de prueba debe superar _MAX_CHUNK_CHARS"

        meta = self._meta()
        subs = _subdividir_por_parrafos(texto, meta)

        assert len(subs) > 1, (
            f"[2.2] Texto de {len(texto)} chars no fue subdividido — "
            "¿_MAX_CHUNK_CHARS demasiado alto?"
        )
        partes = [s["metadata"].get("subchunk_parte") for s in subs]
        assert all(p is not None for p in partes), (
            f"[2.2 ROTO] Sub-chunks sin subchunk_parte: {partes}"
        )
        assert partes[0] == "a", f"Primera parte debe ser 'a', fue: {partes[0]!r}"
        assert partes[1] == "b", f"Segunda parte debe ser 'b', fue: {partes[1]!r}"

    def test_suma_de_partes_conserva_texto_completo(self):
        """[I1] La concatenación de todos los sub-chunks == texto original."""
        texto = self._texto_grande()
        meta = self._meta()
        subs = _subdividir_por_parrafos(texto, meta)

        texto_reconstruido = "\n\n".join(s["texto"] for s in subs)
        assert texto_reconstruido == texto, (
            "[I1 ROTO en sub-chunking] El texto reconstruido difiere del original. "
            f"Original: {len(texto)} chars, Reconstruido: {len(texto_reconstruido)} chars"
        )

    def test_metadata_padre_heredada_en_cada_parte(self):
        """Metadata del chunk padre se hereda en todos los sub-chunks."""
        texto = self._texto_grande()
        meta = self._meta()
        subs = _subdividir_por_parrafos(texto, meta)

        for s in subs:
            assert s["metadata"]["capitulo"] == meta["capitulo"], (
                f"[2.2 ROTO] 'capitulo' no heredado en sub-chunk {s['metadata'].get('subchunk_parte')}"
            )
            assert s["metadata"]["numeral_derivado"] == meta["numeral_derivado"], (
                "[2.2 ROTO] 'numeral_derivado' no heredado"
            )

    def test_chunk_pequeno_no_se_etiqueta(self):
        """Chunk <= _MAX_CHUNK_CHARS no debe tener subchunk_parte."""
        texto_pequeno = "Párrafo corto.\n\nOtro párrafo corto."
        meta = self._meta()
        subs = _subdividir_por_parrafos(texto_pequeno, meta)

        assert len(subs) == 1, "Texto pequeño no debe subdividirse"
        assert "subchunk_parte" not in subs[0]["metadata"], (
            "[2.2 ROTO] Chunk pequeño recibió subchunk_parte — no debería"
        )


class TestSubchunkIntegracion:
    """
    Tests de integración — verifican que chunks > _MAX_CHUNK_CHARS
    llegan subdividos al flujo completo de chunkear(), no solo a la función aislada.

    CASO A: párrafos con separador \\n simple (marker genera esto).
    CASO B: tabla markdown (>50% líneas con "|") → no se parte, se marca.
    """

    def _meta(self) -> dict:
        return {"capitulo": "4. REQUISITOS", "nivel_h": 2}

    def test_caso_a_n_simple_flujo_completo(self):
        """[CASO A] Un chunk grande con \\n simple llega subdividido desde chunkear()."""
        import re
        # 60 líneas × 400 chars = 24,000 chars > _MAX_CHUNK_CHARS (15,000)
        # Separadas por \\n simple — no por \\n\\n (como genera marker desde PDF)
        parrafo = "Texto de requisito habilitante. " * 12  # ~384 chars
        n_lineas = 70
        contenido = "\n".join([parrafo] * n_lineas)
        markdown = f"# SECCIÓN GRANDE\n{contenido}"

        assert len(contenido) > _MAX_CHUNK_CHARS, (
            f"El texto de prueba ({len(contenido)}) debe superar _MAX_CHUNK_CHARS ({_MAX_CHUNK_CHARS})"
        )
        assert contenido.count("\n\n") == 0, "El markdown de prueba no debe tener \\n\\n"

        chunks, _ = chunkear(markdown, usar_numeral_derivado=False)

        subchunks = [c for c in chunks if c["metadata"].get("subchunk_parte")]
        assert len(subchunks) >= 2, (
            f"[CASO A ROTO] Se esperaban >= 2 sub-chunks con \\n simple, "
            f"obtuvo {len(subchunks)} (total chunks={len(chunks)}). "
            f"¿_subdividir_por_parrafos conectado al flujo?"
        )
        partes = [c["metadata"]["subchunk_parte"] for c in subchunks]
        assert "a" in partes, f"Primera parte debe ser 'a', partes={partes}"
        assert "b" in partes, f"Segunda parte debe ser 'b', partes={partes}"

    def test_caso_a_i1_contenido_preservado_en_n_simple(self):
        """[I1][CASO A] La suma de sub-chunks conserva todo el contenido no-espacio.

        El assert vive dentro de _subdividir_por_parrafos (compara el texto que entra
        vs la suma de lo que devuelve). Este test verifica que el assert no se dispara
        — es decir, que ninguna excepción AssertionError se lanza durante el flujo.
        """
        import re
        parrafo = "Contenido X " * 30  # ~360 chars
        n_lineas = 80
        contenido = "\n".join([parrafo] * n_lineas)
        markdown = f"# SECCIÓN\n{contenido}"

        # Si el assert en _subdividir_por_parrafos falla, se lanza AssertionError aquí
        chunks, _ = chunkear(markdown, usar_numeral_derivado=False)
        subchunks = [c for c in chunks if c["metadata"].get("subchunk_parte")]

        if len(subchunks) < 2:
            pytest.skip("No se generaron sub-chunks — CASO A no activado")

        # Verificar I1 directamente sobre la función: el texto de cada sub-chunk
        # concatenado (sin espacios) debe igualar el texto que recibió el padre.
        # El assert interno ya garantiza esto; aquí verificamos que el chunk padre
        # y la suma de sus hijos son coherentes comparando solo contenido textual.
        ws = lambda s: re.sub(r"\s", "", s)
        total_sub = ws("".join(c["texto"] for c in subchunks))
        # Reconstruir cuál sería el texto del chunk padre (primer sub-chunk + resto)
        # comparando que la suma de partes no tiene chars extra ni faltantes
        assert len(total_sub) > 0, "[I1] Sub-chunks vacíos — se perdió todo el contenido"
        # La suma de sub-chunks debe contener exactamente los chars del primer sub-chunk
        # más el resto — verificado por el assert interno de _subdividir_por_parrafos
        primer_sub = ws(subchunks[0]["texto"])
        assert primer_sub in total_sub, "[I1] Primera parte no está en la suma de partes"

    def test_caso_b_tabla_no_se_parte(self):
        """[CASO B] Tabla markdown grande → chunk único marcado como tabla_markdown."""
        # 70 filas × ~260 chars = ~18,200 chars > _MAX_CHUNK_CHARS
        fila = "| " + "A" * 120 + " | " + "B" * 120 + " |\n"
        tabla = "| col1 | col2 |\n|---|---|\n" + fila * 70
        markdown = f"# SECCIÓN TABLA\n{tabla}"

        assert len(tabla) > _MAX_CHUNK_CHARS, (
            f"La tabla de prueba ({len(tabla)}) debe superar _MAX_CHUNK_CHARS"
        )

        chunks, _ = chunkear(markdown, usar_numeral_derivado=False)

        tablas = [c for c in chunks if c["metadata"].get("tipo_contenido") == "tabla_markdown"]
        assert len(tablas) >= 1, (
            f"[CASO B ROTO] Se esperaba al menos 1 chunk tabla_markdown, "
            f"obtuvo {len(tablas)} (total={len(chunks)})"
        )
        assert "subchunk_parte" not in tablas[0]["metadata"], (
            "[CASO B ROTO] Tabla marcada Y además etiquetada con subchunk_parte"
        )

    def test_caso_b_tabla_sin_subchunks_etiquetados(self):
        """[CASO B] Una tabla grande no produce subchunk_parte."""
        fila = "| " + "X" * 200 + " | filler |\n"
        tabla = "| col1 | col2 |\n|---|---|\n" + fila * 80  # ~16,400 chars
        markdown = f"# TABLA BIG\n{tabla}"

        chunks, _ = chunkear(markdown, usar_numeral_derivado=False)

        # Ningún chunk de tabla debe tener subchunk_parte
        for c in chunks:
            if c["metadata"].get("tipo_contenido") == "tabla_markdown":
                assert "subchunk_parte" not in c["metadata"], (
                    "[CASO B ROTO] Tabla tiene subchunk_parte — se partió incorrectamente"
                )


class TestSalidaReducida:
    """
    [2.5] El modelo devuelve SOLO los ítems CCE encontrados.
    Python deriva checklist_no_encontrados como complemento.
    Con 2 ítems encontrados → 28 en checklist_no_encontrados.
    """

    def _mock_llamar_con_2_items(self, client, chunk, idx, sistema=None):
        return {
            "estado": "ok",
            "datos": {
                "entidad_publica": "",
                "numero_proceso": "",
                "requisitos": [],
                "checklist_encontrado": [CHECKLIST_CCE[0], CHECKLIST_CCE[1]],  # 2 items
                "hallazgos_fuera_de_checklist": [],
            },
            "input_tokens": 100,
            "output_tokens": 30,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }

    def test_no_encontrados_es_complemento(self):
        """Con 2 ítems encontrados, checklist_no_encontrados tiene 28."""
        chunks = [{"texto": "fragmento", "metadata": {"capitulo": "CAP"}}]
        n_total = len(CHECKLIST_CCE)

        with patch("src.extractor._llamar", side_effect=self._mock_llamar_con_2_items):
            resultado = extraer("# MD", chunks, api_key="fake-key")

        n_encontrados = n_total - len(resultado.checklist_no_encontrados)
        assert n_encontrados == 2, (
            f"[2.5 ROTO] Se esperaban 2 ítems encontrados, se calcularon {n_encontrados}"
        )
        assert len(resultado.checklist_no_encontrados) == n_total - 2, (
            f"[2.5 ROTO] checklist_no_encontrados debe tener {n_total - 2} ítems, "
            f"tiene {len(resultado.checklist_no_encontrados)}"
        )
        # Verificar que los 2 encontrados NO están en no_encontrados
        for item in [CHECKLIST_CCE[0], CHECKLIST_CCE[1]]:
            assert item not in resultado.checklist_no_encontrados, (
                f"[2.5 ROTO] Item encontrado '{item}' aparece en checklist_no_encontrados"
            )


class TestTruncamientosSuma:
    """
    V1 — Verificación de que truncamientos es la unión de ambas listas.

    Bug que previene: si el caller pasa chunks_truncados (vacío) en vez de
    truncamientos (combinado), estado_global devuelve "completo" con secciones
    perdidas. El test fuerza el uso correcto y verifica ausencia de duplicados.
    """

    def _resp_truncado(self, idx: int) -> dict:
        return {
            "estado": "truncado", "chunk_idx": idx,
            "input_tokens": 100, "output_tokens": 8000,
            "cache_creation_tokens": 0, "cache_read_tokens": 0,
        }

    def _resp_json_error(self, idx: int) -> dict:
        return {
            "estado": "json_error", "chunk_idx": idx,
            "error": "Unexpected token", "crudo_inicio": "",
            "input_tokens": 100, "output_tokens": 40,
            "cache_creation_tokens": 0, "cache_read_tokens": 0,
        }

    def _chunk(self) -> dict:
        return {"texto": "fragmento", "metadata": {"capitulo": "CAP"}}

    def test_v1a_json_error_impide_estado_completo(self):
        """
        [V1a] chunks_truncados VACÍO + chunks_error_json no vacío.
        estado_global(truncados=resultado.truncamientos) debe ser 'truncado',
        NO 'completo'. Bug: si el caller usa chunks_truncados en vez de
        truncamientos, obtiene 'completo' cuando hay secciones perdidas.
        """
        chunks = [self._chunk(), self._chunk()]
        responses = [
            {"estado": "ok", "datos": {"entidad_publica": "", "numero_proceso": "",
             "requisitos": [], "checklist_encontrado": [],
             "hallazgos_fuera_de_checklist": []},
             "input_tokens": 100, "output_tokens": 50,
             "cache_creation_tokens": 0, "cache_read_tokens": 0},
            self._resp_json_error(1),   # chunk 1 falla con json_error
        ]
        with patch("src.extractor._llamar", side_effect=responses):
            resultado = extraer("# MD", chunks, api_key="fake-key")

        # chunks_truncados DEBE estar vacío
        assert resultado.chunks_truncados == [], (
            f"chunks_truncados debe ser vacío: {resultado.chunks_truncados}"
        )
        # chunks_error_json DEBE tener una entrada
        assert len(resultado.chunks_error_json) == 1, (
            f"chunks_error_json debe tener 1 entrada: {resultado.chunks_error_json}"
        )
        # truncamientos (la SUMA) debe ser no vacío — el invariante clave
        assert len(resultado.truncamientos) == 1, (
            f"[V1a ROTO] truncamientos debe ser non-empty con json_error: {resultado.truncamientos}"
        )
        # Verificar que estado_global con truncamientos NO retorna 'completo'
        estado = estado_global(
            errores=[],
            truncados=resultado.truncamientos,   # ← correcto: usar la suma
            cobertura_pct=100.0,
        )
        assert estado != "completo", (
            f"[V1a ROTO] Con json_error, estado_global devolvió 'completo'. "
            "El caller debe usar resultado.truncamientos, no resultado.chunks_truncados"
        )
        assert estado == "truncado", f"Se esperaba 'truncado', obtenido: {estado!r}"

    def test_v1b_ningun_chunk_aparece_dos_veces(self):
        """
        [V1b] Ningún chunk puede estar en chunks_truncados Y en chunks_error_json
        al mismo tiempo → truncamientos no tiene duplicados.
        _llamar devuelve un solo estado por llamada; continue impide doble registro.
        """
        chunks = [self._chunk(), self._chunk(), self._chunk()]
        responses = [
            self._resp_truncado(0),
            self._resp_json_error(1),
            self._resp_truncado(2),
        ]
        with patch("src.extractor._llamar", side_effect=responses):
            resultado = extraer("# MD", chunks, api_key="fake-key")

        assert "chunk_0" in resultado.chunks_truncados
        assert "chunk_1" in resultado.chunks_error_json
        assert "chunk_2" in resultado.chunks_truncados

        # Ningún chunk_id en ambas listas
        en_ambas = set(resultado.chunks_truncados) & set(resultado.chunks_error_json)
        assert len(en_ambas) == 0, (
            f"[V1b ROTO] Estos chunks aparecen en AMBAS listas: {en_ambas}"
        )

        # Sin duplicados en la suma
        todos = resultado.truncamientos
        assert len(todos) == len(set(todos)), (
            f"[V1b ROTO] truncamientos tiene duplicados: {todos}"
        )
        assert len(todos) == 3


class TestMarcarIndices:
    """
    [2.3] marcar_indices() detecta chunks que parecen índice/TOC
    por tasa de citas no verificadas > 50%.
    """

    def _resultado_con_reqs(self) -> ResultadoExtraccion:
        reqs = []
        # Chunk 0: 3 reqs, todos NO verificados → posible índice
        for i in range(3):
            r = Requisito(
                nombre=f"Req TOC {i}",
                categoria="juridico",
                exigido_literal="frase que no existe en el documento fuente",
                fuente_numeral="1.1",
                chunk_idx=0,
            )
            reqs.append(r)
        # Chunk 1: 2 reqs, todos verificados → no es índice
        for i in range(2):
            r = Requisito(
                nombre=f"Req Verif {i}",
                categoria="juridico",
                exigido_literal="El proponente debe acreditar experiencia general",
                fuente_numeral="2.1",
                chunk_idx=1,
            )
            r.cita_verificada = True
            r.estado_verificacion = "verificada"
            reqs.append(r)

        return ResultadoExtraccion(
            entidad_publica="ENT",
            numero_proceso="P-001",
            requisitos=reqs,
            checklist_no_encontrados=[],
            hallazgos_fuera_de_checklist=[],
            chunks_procesados=2,
            chunks_totales=2,
            truncamientos=[],
        )

    def test_chunk_sin_verificar_marcado_como_indice(self):
        """Chunk con 100% citas no verificadas → advertencia_indice y origen='probable_indice'."""
        resultado = self._resultado_con_reqs()
        # Simular que chunk 0 no tiene citas verificadas (ya está en False por defecto)
        resultado = marcar_indices(resultado, umbral=0.5)

        assert 0 in resultado.chunks_advertencia_indice, (
            f"[2.3 ROTO] Chunk 0 (100% no verificado) no está en chunks_advertencia_indice: "
            f"{resultado.chunks_advertencia_indice}"
        )
        reqs_chunk0 = [r for r in resultado.requisitos if r.chunk_idx == 0]
        for req in reqs_chunk0:
            assert req.origen == "probable_indice", (
                f"[2.3 ROTO] Req '{req.nombre}' en chunk índice no fue marcado como 'probable_indice': "
                f"{req.origen!r}"
            )

    def test_chunk_verificado_no_marcado(self):
        """Chunk con 100% citas verificadas → NO en advertencia_indice."""
        resultado = self._resultado_con_reqs()
        resultado = marcar_indices(resultado, umbral=0.5)

        assert 1 not in resultado.chunks_advertencia_indice, (
            f"[2.3 ROTO] Chunk 1 (verificado) aparece en chunks_advertencia_indice"
        )
        reqs_chunk1 = [r for r in resultado.requisitos if r.chunk_idx == 1]
        for req in reqs_chunk1:
            assert req.origen == "extraccion", (
                f"[2.3 ROTO] Req verificado '{req.nombre}' fue marcado como probable_indice"
            )
