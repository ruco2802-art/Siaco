# -*- coding: utf-8 -*-
"""
pipeline/src/bibliotecario.py — Respaldo normativo de afirmaciones.

La tarjeta "Citas Normativas" del front no contiene citas: contiene frases del
agente filtradas por palabras clave ("Ley", "Decreto", "art."), y
`articulos_aplicables` es una copia literal de `razones_financiero`. En un
informe que se presenta a una entidad, eso es lo que sostiene la afirmación.

Este módulo resuelve el eje normativo con el mismo mecanismo que verifier.py
aplica a las citas del pliego: comparación literal contra el archivo fuente.

ESTÁNDAR: cita textual verificable, o `sin_respaldo`. No hay grados.

Invariantes:
  [N1] El fragmento se verifica contra el .md por comparación de texto
       normalizado, NUNCA con un modelo. Un modelo que audita tiende a aprobar.
  [N2] Una cita no verificada no se publica: el respaldo pasa a sin_respaldo y
       el intento queda en logs/citas_normativas_invalidas.jsonl.
  [N3] Sólo se cita lo que el índice marca citable=true. Si el texto existiera
       en un archivo fuera del índice, sigue siendo fallo crítico.
  [N4] Sin skill en disco no hay respaldo embebido: FileNotFoundError.
  [N6] Un defecto conocido del .md en el artículo citado viaja en la cita
       (`aviso_fuente`) hasta el resultado. Un aviso que se queda en el log no
       protege a quien firma el informe.
  [N5] Un fragmento ilegible se rechaza aunque sea literal. La comparación
       textual prueba que el fragmento existe en el archivo, no que el archivo
       se pueda leer: sin esto, un .md con la codificación rota aprobaría su
       propia basura como cita verbatim.
  [I2] stop_reason se revisa ANTES de json.loads.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

# Normalización compartida con verifier.py — no se duplica [CLAUDE.md]
from .verifier import _norm as _normalizar

_REPO_ROOT = Path(__file__).parent.parent.parent
_BIBLIOTECA = _REPO_ROOT / "biblioteca_normativa"
_INDICE = _BIBLIOTECA / "indice.json"
_SKILL = _REPO_ROOT / ".claude" / "skills" / "skill_bibliotecario_normativo.md"
_LOG_INVALIDAS = _REPO_ROOT / "logs" / "citas_normativas_invalidas.jsonl"

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4_000
_TIMEOUT = 60.0
_MAX_RETRIES = 2
_MAX_ARTICULOS_POR_RESPALDO = 3


# ─── Modelos ──────────────────────────────────────────────────────────────────

class Cita(BaseModel):
    norma: str
    articulo: str
    fragmento: str
    archivo: str
    pertinencia: str
    # Lo pone el verificador (Fase 2), nunca el modelo
    verificada: bool = False
    # [N6] Defecto conocido del .md en ESE artículo, si lo hay. Viaja hasta el
    # resultado: un aviso que se queda en el log no protege a nadie.
    aviso_fuente: str | None = None


class Respaldo(BaseModel):
    afirmacion: str
    # respaldo_parcial [R6]: la norma existe pero regula otro supuesto —
    # p. ej. fija el plazo para licitación y el proceso es de menor cuantía.
    # No es lo mismo que no encontrar nada.
    estado: Literal["respaldada", "respaldo_parcial", "sin_respaldo"]
    motivo: Literal[
        "norma_ausente", "articulo_no_pertinente", "afirmacion_no_normativa"
    ] | None = None
    detalle: str | None = None
    citas: list[Cita] = Field(default_factory=list)
    # Qué SÍ dice la norma, en contraste con la afirmación [R6]
    alcance_real: str | None = None
    # [R4] Normas que también respaldan, sin mezclarse con la principal.
    # Descartarlas perdía información útil para el documento de observaciones.
    normas_secundarias: list[Cita] = Field(default_factory=list)


# ─── [N4] Carga del skill ─────────────────────────────────────────────────────

# Marcadores estructurales obligatorios. La validación por longitud no detecta
# un truncamiento: un skill cortado a media regla medía ~2.000 chars y habría
# pasado un mínimo de 200. Lo que importa es que estén las secciones que
# definen el contrato de salida y el sesgo hacia declarar menos certeza.
_SECCIONES_OBLIGATORIAS: tuple[str, ...] = (
    "## Formato de salida",
    "## Autoverificación antes de responder",
    "R6 — Coincidencia parcial",
)


def cargar_skill(ruta: Path | None = None) -> str:
    """
    Texto del skill del bibliotecario.

    Mismo patrón que `reparar_con_modelo()` en tablas.py: obligatorio, sin
    fallback silencioso. Un prompt embebido de respaldo haría que el agente
    opere con instrucciones distintas a las revisadas, y eso es justo lo que
    el estándar de cita verificable existe para impedir.

    Se valida por SECCIONES, no por longitud: un skill truncado a media regla
    pasa cualquier mínimo de caracteres y deja al agente sin el formato de
    salida ni la regla de coincidencia parcial.
    """
    p = ruta or _SKILL
    if not p.exists():
        raise FileNotFoundError(
            f"Skill del bibliotecario no encontrada: {p}. "
            "Es obligatoria: sin ella no hay prompt de respaldo. "
            "Guarda skill_bibliotecario_normativo.md en .claude/skills/."
        )
    texto = p.read_text("utf-8").strip()

    faltantes = [s for s in _SECCIONES_OBLIGATORIAS if s not in texto]
    if faltantes:
        raise FileNotFoundError(
            f"Skill del bibliotecario incompleta: {p} ({len(texto):,} chars). "
            f"Faltan secciones obligatorias: {faltantes}. "
            "Un skill truncado deja al agente sin el contrato de salida; "
            "no se usa un prompt parcial."
        )
    return texto


# ─── Índice filtrado por modalidad y sector ───────────────────────────────────

# Variantes tomadas de _listar_documentos_relevantes() en analizador.py, que ya
# resuelve este filtrado. Se reutiliza la REGLA, no la extracción de texto: ahí
# se leen los PDF completos y aquí sólo hace falta el metadato del índice.
_VARIANTES_SECTOR: dict[str, list[str]] = {
    "educacion":     ["educacion", "educación", "educativo", "educativa"],
    "salud":         ["salud"],
    "deporte":       ["deporte", "cultura", "recreacion", "recreación"],
    "vivienda":      ["vivienda"],
    "institucional": ["institucional"],
}


def cargar_indice(ruta: Path | None = None) -> dict:
    p = ruta or _INDICE
    if not p.exists():
        raise FileNotFoundError(
            f"Índice de la biblioteca no encontrado: {p}. "
            "Ejecuta la generación del índice antes de usar el bibliotecario."
        )
    return json.loads(p.read_text("utf-8"))


def documentos_citables(
    modalidad: str = "",
    sector: str = "",
    indice: dict | None = None,
) -> list[dict]:
    """
    Documentos del índice que el bibliotecario puede citar para este proceso.

    Reglas (las de analizador.py, aplicadas al índice):
      · `citable=false` nunca entra [N3].
      · `modalidad=null` es transversal: entra siempre (Ley 80, Decreto 1082…).
      · Documento de otra modalidad: se omite.
      · `sector=null` entra siempre; con sector declarado, sólo si coincide
        con alguna variante del sector del proceso.
    """
    idx = indice or cargar_indice()
    claves = _VARIANTES_SECTOR.get((sector or "").lower(), [(sector or "").lower()])
    claves = [c for c in claves if c]

    salida: list[dict] = []
    for d in idx.get("documentos", []):
        if not d.get("citable"):
            continue
        mod = d.get("modalidad")
        if mod and modalidad and mod != modalidad:
            continue
        sec = d.get("sector")
        if sec and claves and not any(c in sec.lower() for c in claves):
            continue
        salida.append(d)
    return salida


def _catalogo_para_prompt(docs: list[dict]) -> str:
    """
    Normas disponibles con sus artículos (número + título), sin el texto.

    El modelo primero identifica QUÉ artículo necesita; el texto se le entrega
    en la segunda llamada. Pasar las normas completas de entrada serían ~1,9 M
    de caracteres sólo con la Ley 80 y el Decreto 1082.
    """
    lineas: list[str] = []
    for d in docs:
        gran = d.get("granularidad")
        lineas.append(f"\n### {d['norma']} ({d['tipo']})")
        if d.get("descripcion"):
            lineas.append(f"    {d['descripcion']}")
        lineas.append(f"    archivo: {d['archivo_md']} · granularidad: {gran}")
        arts = d.get("articulos") or []
        if not arts:
            lineas.append("    (citable como documento completo, sin articulado)")
            continue
        lineas.append(f"    artículos ({len(arts)}):")
        for a in arts:
            titulo = (a.get("titulo") or "").strip()
            lineas.append(f"      - {a['numero']}" + (f": {titulo[:90]}" if titulo else ""))
    return "\n".join(lineas)


def texto_articulo(archivo: str, numero: str, indice: dict | None = None) -> str | None:
    """
    Texto de un artículo leyendo el rango [inicio, fin) del índice.

    No se busca el encabezado en el .md: el índice ya resolvió cuál ocurrencia
    es la buena cuando un número aparecía varias veces. Ver las reglas [X1]
    [X2] [X3] en `indexador.py`.
    """
    idx = indice or cargar_indice()
    for d in idx.get("documentos", []):
        if d.get("archivo_md") != archivo or not d.get("citable"):
            continue
        for a in d.get("articulos") or []:
            if a["numero"] == numero:
                texto = (_BIBLIOTECA / archivo).read_text("utf-8")
                return texto[a["inicio"]:a["fin"]].strip()
    return None


def aviso_de_articulo(archivo: str, numero: str,
                      indice: dict | None = None) -> str | None:
    """
    [N6] Defecto conocido del `.md` que afecta a ESTE artículo.

    El indexador registra en `avisos_indexacion` los números que aparecen más
    de una vez con contenido distinto: el Decreto 1082 tiene 21, porque su
    `.md` trae dos `CAPÍTULO 3` bajo el mismo Título 6 y ambos numeran sus
    artículos `2.2.6.3.x`. Es un defecto de la fuente, no del indexador.

    Ese aviso tiene que llegar al resultado. Si se queda en el log, quien firma
    el informe no se entera de que el artículo citado tenía una ocurrencia
    alternativa con otro contenido.
    """
    idx = indice or cargar_indice()
    for d in idx.get("documentos", []):
        if d.get("archivo_md") != archivo:
            continue
        for aviso in d.get("avisos_indexacion") or []:
            if aviso.get("numero") != numero:
                continue
            if aviso.get("tipo") == "divergencia_alta":
                otras = len(aviso.get("ocurrencias") or [])
                return (
                    f"El archivo de {d['norma']} contiene {otras} artículos "
                    f"distintos numerados {numero} (similitud "
                    f"{aviso.get('similitud')}). Es un defecto de la fuente. "
                    "El índice tomó la ocurrencia más tardía: verifica el texto "
                    "antes de usar esta cita en un documento formal."
                )
            return f"Aviso de indexación en {d['norma']} art. {numero}: {aviso.get('tipo')}."
    return None


# ─── FASE 2 · Verificador — código, nunca un modelo [N1] ──────────────────────

# [N5] Detector de texto corrupto. La verificación literal sólo garantiza que
# el fragmento EXISTE en el archivo, no que el archivo sea legible: un .md con
# la codificación de fuente rota ("XQD¿GXFLD" por "una fiducia") se compara
# consigo mismo y pasa como verbatim. En español toda palabra lleva vocal, así
# que una palabra larga sin ninguna delata la corrupción.
#
# Calibrado sobre la biblioteca: 0 falsos positivos en Decreto 1082, Ley 1150,
# Ley 1882 y Ley 80; 2.220 aciertos en Ley 1474. Las siglas legítimas del
# corpus (SMMLV, SMLMV, DGCPTN, DGPPN, SMLDV) son mayúsculas de ≤6 letras y
# quedan exentas; el mojibake produce tokens largos de caja mixta.
_VOCALES_STR = "aeiouáéíóúüAEIOUÁÉÍÓÚÜ"
_VOCALES = set(_VOCALES_STR)
_TOKEN_LARGO = re.compile(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü¿½]{5,}")
# Racha de consonantes. El español no encadena cinco: "transcribir" llega a
# cuatro (nscr). Señal más sensible que la ausencia total de vocal, porque el
# mojibake suele conservar alguna: "SDWULPRQLR" (patrimonio) lleva una U y
# la primera señal lo dejaba pasar.
_RACHA_CONSONANTES = re.compile(rf"[^\W\d_{_VOCALES_STR}]{{5,}}", re.UNICODE)
_MAX_SIGLA = 6


def _es_sigla(palabra: str) -> bool:
    """SMMLV, SMLMV, DGCPTN, DGPPN, NSPSC: mayúscula corta, no corrupción."""
    return palabra.isupper() and len(palabra) <= _MAX_SIGLA


def palabras_ilegibles(texto: str) -> list[str]:
    """
    Palabras que delatan una codificación rota [N5]. Estricto: un solo acierto
    basta para rechazar un fragmento.

    Dos señales, ambas calibradas contra la biblioteca con 0 falsos positivos
    en Decreto 1082, Ley 1150, Ley 1882 y Ley 80:
      1. 5+ letras sin ninguna vocal      (2.220 aciertos en Ley 1474)
      2. racha de 5+ consonantes seguidas (7.146 aciertos en Ley 1474)
    """
    return [p for p in _TOKEN_LARGO.findall(texto)
            if not _es_sigla(p)
            and (not (set(p) & _VOCALES) or _RACHA_CONSONANTES.search(p))]


def proporcion_ilegible(texto: str) -> float:
    """
    Fracción de palabras largas corruptas. Mide el DOCUMENTO, no el fragmento.

    Un .md puede traer basura localizada —el sello escaneado al pie de una
    resolución— sin que la norma sea inservible: ahí basta con que [N5] impida
    citar esa zona. Lo que condena a un documento entero es la corrupción
    sistémica, como el 69% de artículos rotos de la Ley 1474.
    """
    largas = _TOKEN_LARGO.findall(texto)
    if not largas:
        return 0.0
    return len(palabras_ilegibles(texto)) / len(largas)


def _registrar_invalida(cita: Cita, afirmacion: str, motivo: str) -> None:
    """[N2] Todo fallo crítico queda en el log, con la cita que se intentó."""
    try:
        _LOG_INVALIDAS.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_INVALIDAS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "afirmacion": afirmacion,
                "norma":      cita.norma,
                "articulo":   cita.articulo,
                "archivo":    cita.archivo,
                "fragmento":  cita.fragmento[:400],
                "motivo":     motivo,
            }, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[BIBLIOTECARIO] No se pudo escribir {_LOG_INVALIDAS}: {exc}")


def verificar_cita(
    cita: Cita,
    afirmacion: str = "",
    indice: dict | None = None,
) -> bool:
    """
    True sólo si el fragmento existe LITERALMENTE en el archivo indexado.

    Mismo mecanismo que verifier.py con las citas del pliego: normalizar ambos
    lados y comprobar inclusión. Sin modelo [N1].

    Fallos críticos:
      · la norma no está en el índice con citable=true [N3]
      · el fragmento contiene texto corrupto e ilegible [N5]
      · el fragmento no aparece en el archivo (parafraseado o reconstruido)
    """
    idx = indice or cargar_indice()

    # [N3] ¿está la norma en el índice y es citable?
    doc = next(
        (d for d in idx.get("documentos", [])
         if d.get("citable") and (d.get("archivo_md") == cita.archivo
                                  or d.get("norma") == cita.norma)),
        None,
    )
    if doc is None:
        cita.verificada = False
        _registrar_invalida(cita, afirmacion, "norma_fuera_del_indice")
        return False

    ruta = _BIBLIOTECA / doc["archivo_md"]
    if not ruta.exists():
        cita.verificada = False
        _registrar_invalida(cita, afirmacion, "archivo_inexistente")
        return False

    fragmento = (cita.fragmento or "").strip()
    if len(fragmento) < 20:
        cita.verificada = False
        _registrar_invalida(cita, afirmacion, "fragmento_demasiado_corto")
        return False

    # [N5] Antes de comparar: ¿el fragmento es siquiera legible? Un .md con la
    # codificación rota coincide consigo mismo y pasaría como verbatim.
    ilegibles = palabras_ilegibles(fragmento)
    if ilegibles:
        cita.verificada = False
        _registrar_invalida(cita, afirmacion, "fragmento_ilegible")
        return False

    if _normalizar(fragmento) not in _normalizar(ruta.read_text("utf-8")):
        cita.verificada = False
        _registrar_invalida(cita, afirmacion, "fragmento_no_literal")
        return False

    cita.verificada = True
    # [N6] La cita es válida, pero si el .md tiene un defecto conocido en ese
    # artículo el aviso viaja con ella hasta el informe.
    cita.aviso_fuente = aviso_de_articulo(doc["archivo_md"], cita.articulo, idx)
    return True


def verificar_respaldo(respaldo: Respaldo, indice: dict | None = None) -> Respaldo:
    """
    Verifica cada cita y degrada el respaldo si alguna no resiste.

    [N2] Las citas no verificadas se descartan. Si no queda ninguna, el estado
    pasa a `sin_respaldo` con motivo `articulo_no_pertinente`: el sistema
    preferirá abstenerse antes que publicar una cita que no puede sostener.
    """
    idx = indice or cargar_indice()
    respaldo.citas = [
        c for c in respaldo.citas
        if verificar_cita(c, respaldo.afirmacion, idx)
    ]
    # [R4] Las secundarias son citas igual: se verifican con el mismo estándar.
    respaldo.normas_secundarias = [
        c for c in respaldo.normas_secundarias
        if verificar_cita(c, respaldo.afirmacion, idx)
    ]
    if respaldo.estado in ("respaldada", "respaldo_parcial") and not respaldo.citas:
        respaldo.estado = "sin_respaldo"
        respaldo.motivo = "articulo_no_pertinente"
        respaldo.detalle = (
            "Las citas propuestas no se encontraron literalmente en la "
            "biblioteca normativa y fueron descartadas."
        )
        respaldo.alcance_real = None
    return respaldo


# ─── FASE 1 · El agente ───────────────────────────────────────────────────────

def _cliente():
    import anthropic
    return anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        timeout=_TIMEOUT,
        max_retries=_MAX_RETRIES,
    )


def _texto_respuesta(resp) -> str:
    """[I2] stop_reason ANTES de parsear: max_tokens deja JSON truncado."""
    if getattr(resp, "stop_reason", None) == "max_tokens":
        raise ValueError(
            f"Respuesta truncada por max_tokens ({_MAX_TOKENS}). "
            "El JSON está incompleto: no se parsea."
        )
    return next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")


def _parsear_json(texto: str) -> dict:
    t = texto.strip()
    if "```" in t:
        for frag in t.split("```")[1::2]:
            limpio = frag.strip()
            if limpio.lower().startswith("json"):
                limpio = limpio[4:].strip()
            if limpio:
                t = limpio
                break
    return json.loads(t)


def _desenvolver(datos: dict) -> dict:
    """
    El skill especifica un envoltorio de lote: {"respaldos": [ {...} ]}.

    `buscar_respaldo()` procesa una afirmación por llamada (especificación
    1.2), así que se toma el primer elemento. Se acepta también el objeto
    desnudo, para no romper si el modelo omite el envoltorio.
    """
    if isinstance(datos.get("respaldos"), list) and datos["respaldos"]:
        primero = datos["respaldos"][0]
        return primero if isinstance(primero, dict) else datos
    return datos


def numero_de_articulo(articulo: str) -> str:
    """
    Número indexable a partir de la referencia del skill.

    [R3] permite precisión adicional en el mismo campo: "Artículo 5, parágrafo 1".
    El índice busca por número ("5", "9A", "2.2.1.1.1.3.1"), así que hay que
    extraerlo sin perder la numeración compuesta ni los sufijos.
    """
    s = (articulo or "").strip()
    s = re.sub(r"^\s*art[íi]culo\s+", "", s, flags=re.IGNORECASE)
    m = re.match(r"(\d+(?:\.\d+)+|\d+\s*\.?\s*[A-Z]\b|\d+)", s)
    if not m:
        return s
    return re.sub(r"[\s.]", "", m.group(1)) if re.match(r"^\d+\s*\.?\s*[A-Z]\b", m.group(1)) \
        else m.group(1).strip()


def buscar_respaldo(
    afirmacion: str,
    modalidad: str = "",
    sector: str = "",
    indice: dict | None = None,
    _client=None,
) -> Respaldo:
    """
    Norma que respalda una afirmación, con cita textual verificada.

    Dos llamadas al modelo, por necesidad y no por diseño:
      1. SELECCIÓN — recibe el catálogo (normas + números y títulos de
         artículo, sin texto) y dice qué artículos necesita. El catálogo
         completo son ~1,9 M de caracteres; no cabe ni conviene enviarlo.
      2. CITA — recibe el texto de los artículos elegidos (≤3) y extrae el
         fragmento literal. No puede citar lo que no ha leído.

    El skill y el catálogo van con cache_control: son constantes entre
    afirmaciones del mismo proceso.

    El resultado pasa siempre por `verificar_respaldo()`: lo que devuelve esta
    función ya tiene `verificada` puesto por código, no por el modelo.
    """
    skill = cargar_skill()
    idx = indice or cargar_indice()
    docs = documentos_citables(modalidad, sector, idx)

    if not docs:
        return Respaldo(
            afirmacion=afirmacion, estado="sin_respaldo", motivo="norma_ausente",
            detalle=f"Sin documentos citables para modalidad={modalidad!r} sector={sector!r}.",
        )

    client = _client or _cliente()
    catalogo = _catalogo_para_prompt(docs)

    # Bloques cacheables: skill + catálogo. Lo volátil (la afirmación) va aparte.
    sistema = [
        {"type": "text", "text": skill, "cache_control": {"type": "ephemeral"}},
        {"type": "text",
         "text": "NORMAS DISPONIBLES EN LA BIBLIOTECA (sólo estas se pueden citar):\n" + catalogo,
         "cache_control": {"type": "ephemeral"}},
    ]

    # ── Llamada 1: selección de artículos ─────────────────────────────────
    prompt_sel = (
        f"AFIRMACIÓN A RESPALDAR:\n{afirmacion}\n\n"
        "Indica qué artículos de las normas disponibles respaldan esta afirmación.\n"
        f"Máximo {_MAX_ARTICULOS_POR_RESPALDO}. Si ninguna norma de la biblioteca la "
        "respalda, dilo con estado sin_respaldo.\n\n"
        "Responde SÓLO con JSON:\n"
        '{"estado":"respaldada|sin_respaldo",'
        '"motivo":"norma_ausente|articulo_no_pertinente|afirmacion_no_normativa|null",'
        '"detalle":"...",'
        '"seleccion":[{"norma":"...","archivo":"...","articulo":"...","pertinencia":"..."}]}'
    )
    resp1 = client.messages.create(
        model=_MODEL, max_tokens=_MAX_TOKENS, system=sistema,
        messages=[{"role": "user", "content": prompt_sel}],
    )
    try:
        sel = _desenvolver(_parsear_json(_texto_respuesta(resp1)))
    except (ValueError, json.JSONDecodeError) as exc:
        return Respaldo(
            afirmacion=afirmacion, estado="sin_respaldo", motivo="articulo_no_pertinente",
            detalle=f"Selección no interpretable: {exc}",
        )

    if sel.get("estado") == "sin_respaldo" or not sel.get("seleccion"):
        return Respaldo(
            afirmacion=afirmacion, estado="sin_respaldo",
            motivo=sel.get("motivo") or "norma_ausente",
            detalle=sel.get("detalle"),
        )

    # ── Texto de los artículos elegidos (de disco, no del modelo) ─────────
    elegidos, bloques = [], []
    for s in sel["seleccion"][:_MAX_ARTICULOS_POR_RESPALDO]:
        num = numero_de_articulo(str(s.get("articulo", "")))
        t = texto_articulo(s.get("archivo", ""), num, idx)
        if t is None:
            continue
        elegidos.append(s)
        bloques.append(f"### {s.get('norma')} — artículo {s.get('articulo')}\n{t}")

    if not elegidos:
        return Respaldo(
            afirmacion=afirmacion, estado="sin_respaldo", motivo="norma_ausente",
            detalle="Los artículos seleccionados no existen en el índice.",
        )

    # ── Llamada 2: extracción del fragmento literal ───────────────────────
    prompt_cita = (
        f"AFIRMACIÓN:\n{afirmacion}\n\n"
        "TEXTO DE LOS ARTÍCULOS SELECCIONADOS:\n\n" + "\n\n".join(bloques) + "\n\n"
        "Extrae de cada artículo el fragmento EXACTO que respalda la afirmación, "
        "copiado carácter por carácter del texto anterior. No parafrasees, no "
        "corrijas la puntuación, no completes. Si un artículo no la respalda, "
        "omítelo.\n\n"
        "Responde SÓLO con JSON:\n"
        '{"estado":"respaldada|sin_respaldo","motivo":null,"detalle":null,'
        '"citas":[{"norma":"...","articulo":"...","fragmento":"...",'
        '"archivo":"...","pertinencia":"..."}]}'
    )
    resp2 = client.messages.create(
        model=_MODEL, max_tokens=_MAX_TOKENS, system=sistema,
        messages=[{"role": "user", "content": prompt_cita}],
    )
    try:
        out = _desenvolver(_parsear_json(_texto_respuesta(resp2)))
    except (ValueError, json.JSONDecodeError) as exc:
        return Respaldo(
            afirmacion=afirmacion, estado="sin_respaldo", motivo="articulo_no_pertinente",
            detalle=f"Extracción de cita no interpretable: {exc}",
        )

    def _citas(clave: str) -> list[Cita]:
        out_: list[Cita] = []
        for c in out.get(clave) or []:
            if not isinstance(c, dict):
                continue
            try:
                out_.append(Cita(
                    norma=str(c.get("norma", "")),
                    articulo=str(c.get("articulo", "")),
                    fragmento=str(c.get("fragmento", "")),
                    archivo=str(c.get("archivo", "")),
                    pertinencia=str(c.get("pertinencia", "")),
                ))
            except Exception:
                continue
        return out_

    citas = _citas("citas")
    # El modelo puede declarar respaldo_parcial [R6]; se respeta salvo que no
    # quede ninguna cita verificada, y eso lo decide verificar_respaldo().
    estado_modelo = out.get("estado")
    if citas:
        estado = "respaldo_parcial" if estado_modelo == "respaldo_parcial" else "respaldada"
    else:
        estado = "sin_respaldo"

    respaldo = Respaldo(
        afirmacion=afirmacion,
        estado=estado,
        motivo=None if citas else (out.get("motivo") or "articulo_no_pertinente"),
        detalle=out.get("detalle"),
        citas=citas,
        alcance_real=out.get("alcance_real") if estado == "respaldo_parcial" else None,
        normas_secundarias=_citas("normas_secundarias"),
    )
    # El veredicto final lo da el código, no el modelo
    return verificar_respaldo(respaldo, idx)
