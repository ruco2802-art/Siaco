# -*- coding: utf-8 -*-
"""
pipeline/src/tablas.py — Detección y reparación de tablas fragmentadas por marker.

CAUSA RAÍZ DEL PROBLEMA:
    marker con disable_ocr=True agrupa columnas por posición horizontal de texto,
    ignorando los bordes vectoriales del PDF. El resultado: cada palabra en su
    propia celda ("| Cualquiera | de | las | clases |"). pdfplumber lee los
    bordes directamente y produce celdas completas.

TIPOS DE PDF (clasificación de la FASE 0, 2026-08):
    TIPO A — bordes vectoriales en ≥1 página → pdfplumber con estrategia lines
    TIPO B — sin bordes, capa de texto nativa → pdfplumber estrategia text, incierto
    TIPO C — escaneado sin capa de texto → reparar_con_modelo (Plan B)

    NOTA TIPO C: "16. PLIEGO DE CONDICIONES DEFINITIVO.pdf" es el pliego sobre el
    que se realizó el diagnóstico inicial del proyecto (Paicol). Cuando se procese
    con marker, reparar_con_modelo() pasará de función teórica a necesaria. El stub
    debe dejar eso explícito.

REGLA DE METODOLOGÍA [I8-ext]:
    Ningún diagnóstico sobre estructura de documento se basa en una muestra de las
    primeras páginas. Las portadas e índices carecen de tablas y no son
    representativos. En la FASE 0 (2026-08), muestrear solo las primeras 5 páginas
    clasificó incorrectamente 3 PDFs como TIPO B cuando en realidad eran TIPO A
    (bordes presentes desde la página 5 en adelante). Todos los escáneres de
    estructura deben recorrer el documento COMPLETO.

INVARIANTES:
    [I1] Ningún paso trunca el contenido de una celda. Las celdas se transcriben
         completas por largas que sean. La longitud de contenido no-tabla del
         markdown final no puede ser menor que la del original.
    [I2] La reparación usa el PDF original como fuente de verdad, NUNCA el markdown
         de marker. El markdown solo sirve para DETECTAR qué tabla está rota.
    [I3] Las erratas del PDF se preservan textualmente. Si el PDF dice
         "Unidad Operacional" donde debería decir "Utilidad", se transcribe
         "Unidad". La errata puede tener efecto legal.
    [I4] La verificación usa str.find normalizado — nunca un modelo de IA para
         auditar. Un modelo auditor tiende a sesgo de confirmación y no es
         reproducible.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore

# ─── Normalización (espeja verifier.py._norm) ────────────────────────────────
# Duplicada aquí para evitar import circular con verifier → extractor.

_SYMBOL_MAP = str.maketrans({
    "≥": ">=", "≤": "<=", "≠": "!=",
    "−": "-",  "–": "-",  "—": "-",
    "×": "*",  "÷": "/",  "·": "*",
    "'": "'",  "'": "'",
    "“": '"', "”": '"',
    "«": '"',  "»": '"',
})


def _norm(texto: str) -> str:
    texto = texto.translate(_SYMBOL_MAP)
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    sin_acc = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acc).strip()


# ─── Configuración pdfplumber ─────────────────────────────────────────────────

_STRAT_LINEAS: dict[str, Any] = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "edge_min_length": 3,
    "min_words_vertical": 1,
    "min_words_horizontal": 1,
    "intersection_tolerance": 3,
    "text_tolerance": 3,
}

_UMBRAL_ACEPTAR = 0.90    # tasa mínima de verificación para sustituir
_UMBRAL_DEGRADADO = 0.75  # tasa mínima si no hay texto nativo (PDF escaneado)
_MAX_PAGINAS_BUSQUEDA = 4  # páginas hacia adelante desde la sección


# ─── Tipos de datos ───────────────────────────────────────────────────────────

@dataclass
class TablaSospechosa:
    """Una tabla del markdown de marker identificada como fragmentada."""
    indice_bloque: int
    motivo: str              # "celdas_1p" | "primera_col_vacia" | ambos
    n_filas: int
    n_columnas: int
    texto_crudo: str         # líneas originales del bloque
    seccion_cercana: str     # encabezado de sección más próximo hacia arriba
    linea_inicio: int        # índice (0-based) de la primera línea del bloque en el markdown
    linea_fin: int           # índice (0-based) de la última línea (inclusive)


@dataclass
class ResultadoTabla:
    """Estado de reparación de una tabla sospechosa."""
    tabla: TablaSospechosa
    pagina: int | None = None
    estado: str = "pendiente"
    # estados: reparada | rechazada | pagina_no_localizada |
    #          reparacion_no_disponible | sin_tabla_plumber | calidad_insuficiente
    via: str = "pdfplumber"   # "pdfplumber" | "modelo"
    tabla_reparada_md: str | None = None
    tasa_verificacion: float = 0.0
    celdas_fallidas: list[str] = field(default_factory=list)
    verificacion_degradada: bool = False  # True si no hubo texto nativo


# ─── helpers internos ─────────────────────────────────────────────────────────

def _es_separador_md(linea: str) -> bool:
    return bool(re.match(r"^\|[\s\-\|:]+\|$", linea.strip()))


def _limpiar_header_md(texto: str) -> str:
    """Elimina markup de markdown para obtener texto plano del encabezado."""
    texto = re.sub(r"^#+\s*", "", texto.strip())
    texto = re.sub(r"\*\*([^*]+)\*\*", r"\1", texto)
    texto = re.sub(r"\*([^*]+)\*", r"\1", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _analizar_bloque(lineas: list[str]) -> dict:
    """
    Evalúa si un bloque de tabla de marker está fragmentado.

    Criterio a — >50% de las celdas no-vacías tienen 1 sola palabra.
    Criterio b — >30% de las celdas de la primera columna están vacías.
    """
    filas = [l for l in lineas if not _es_separador_md(l)]
    if not filas:
        return {"es_rota": False, "motivo": "vacia", "n_filas": 0, "n_cols": 0}

    todas_ne: list[str] = []
    primera_col: list[str] = []

    for linea in filas:
        partes = linea.split("|")
        celdas = [c.strip() for c in partes[1:-1]]
        for i, celda in enumerate(celdas):
            if i == 0:
                primera_col.append(celda)
            if celda:
                todas_ne.append(celda)

    if not todas_ne:
        return {"es_rota": False, "motivo": "sin_contenido", "n_filas": len(filas), "n_cols": 0}

    celdas_1p = sum(1 for c in todas_ne if len(c.split()) == 1)
    pct_1p = celdas_1p / len(todas_ne)

    pct_primera_vacia = 0.0
    if primera_col:
        pct_primera_vacia = sum(1 for c in primera_col if not c) / len(primera_col)

    n_cols = max(len(l.split("|")) - 2 for l in filas) if filas else 0

    motivos = []
    if pct_1p > 0.50:
        motivos.append(f"celdas_1p={pct_1p:.0%}")
    if pct_primera_vacia > 0.30:
        motivos.append(f"primera_col_vacia={pct_primera_vacia:.0%}")

    return {
        "es_rota": bool(motivos),
        "motivo": "; ".join(motivos) if motivos else "ok",
        "n_filas": len(filas),
        "n_cols": n_cols,
        "celdas_1p_pct": pct_1p,
        "primera_col_vacia_pct": pct_primera_vacia,
    }


def _indices_cols_reales(tabla: list[list]) -> list[int]:
    """Índices de columnas con al menos una celda no-vacía en alguna fila."""
    if not tabla:
        return []
    n_cols = max(len(f) for f in tabla)
    reales = []
    for c in range(n_cols):
        for fila in tabla:
            if c < len(fila) and fila[c] and str(fila[c]).strip():
                reales.append(c)
                break
    return reales


def _tabla_a_markdown(tabla: list[list]) -> str:
    """
    Convierte tabla de pdfplumber a markdown limpio.

    - Elimina columnas completamente vacías (artefactos de celdas combinadas)
    - Colapsa saltos de línea dentro de cada celda a un espacio
    - [I1] Nunca trunca el contenido de ninguna celda
    - [I3] No corrige erratas; transcribe el PDF literalmente
    """
    cols = _indices_cols_reales(tabla)
    if not cols:
        return ""

    lineas: list[str] = []
    for f_idx, fila in enumerate(tabla):
        celdas = []
        for c in cols:
            val = fila[c] if c < len(fila) else None
            celda = str(val).replace("\n", " ").strip() if val else ""
            celdas.append(celda)
        lineas.append("| " + " | ".join(celdas) + " |")
        if f_idx == 0:
            lineas.append("| " + " | ".join("---" for _ in cols) + " |")

    return "\n".join(lineas)


def _score_overlap(tabla_texto: str, hint: str) -> float:
    """
    Fracción de tokens del hint (tabla rota de marker) que aparecen en
    tabla_texto (tabla de pdfplumber normalizada).

    Sin hint → 1.0 (toda candidata es válida).
    Usado para elegir cuál tabla de pdfplumber corresponde a la de marker
    cuando hay múltiples en la misma página.
    """
    if not hint:
        return 1.0
    hint_tokens = {t for t in _norm(hint).split() if len(t) > 2}
    if not hint_tokens:
        return 1.0
    tabla_norm = _norm(tabla_texto)
    encontrados = sum(1 for t in hint_tokens if t in tabla_norm)
    return encontrados / len(hint_tokens)


def _verificar_similitud(
    tabla_md: str,
    surya_texto: str,
    ratio_celda: float = 0.80,
    ratio_global: float = 0.75,
) -> tuple[float, list[str]]:
    """
    Verifica celdas de tabla_md contra el texto OCR de Surya (marker fragmentado).

    Para PDFs escaneados donde fitz.page.get_text() está vacío, no hay
    fuente exacta. La referencia es el texto fragmentado que marker produjo
    (Surya OCR). Se compara por solapamiento de tokens, no por str.find exacto.

    Acepta una celda si ≥ ratio_celda de sus tokens aparecen en surya_texto.
    Retorna (tasa_global, celdas_fallidas).
    """
    surya_tokens = set(_norm(surya_texto).split())

    celdas: list[str] = []
    for linea in tabla_md.splitlines():
        if _es_separador_md(linea):
            continue
        for c in linea.split("|")[1:-1]:
            val = c.strip()
            if val:
                celdas.append(val)

    if not celdas:
        return 1.0, []

    fallidas: list[str] = []
    for celda in celdas:
        tokens = [t for t in _norm(celda).split() if len(t) >= 2]
        if not tokens:
            continue
        solapamiento = sum(1 for t in tokens if t in surya_tokens) / len(tokens)
        if solapamiento < ratio_celda:
            fallidas.append(celda)

    tasa = (len(celdas) - len(fallidas)) / len(celdas)
    return tasa, fallidas


def _clasificar_tipo_pdf(pdf_path: Path) -> str:
    """
    Clasifica el PDF en TIPO A/B/C.

    [I8-ext] Escanea TODAS las páginas, no solo las primeras.
    Ver FASE 0 (2026-08): muestrear páginas 0-4 clasificó incorrectamente
    3 PDFs como TIPO B (portadas sin bordes ≠ documento sin bordes).
    """
    doc = fitz.open(str(pdf_path))
    n_pags = doc.page_count
    total_chars = sum(len(doc[i].get_text()) for i in range(n_pags))
    doc.close()
    tiene_texto = total_chars >= n_pags * 50

    if not tiene_texto:
        return "C"

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:  # todas las páginas — [I8-ext]
            if page.edges or page.rects:
                return "A"

    return "B"


# ─── FASE 1 — Detector ────────────────────────────────────────────────────────

def detectar_tablas_rotas(markdown: str) -> list[TablaSospechosa]:
    """
    Sobre el markdown de marker, identifica bloques de tabla y marca como
    rotos los que cumplen CUALQUIERA de:
      a) >50% de las celdas no-vacías tienen una sola palabra
      b) >30% de las celdas de la primera columna están vacías

    Es aritmética pura sobre conteo de celdas; sin modelo ni heurística difusa.
    """
    lineas = markdown.splitlines()
    resultado: list[TablaSospechosa] = []
    bloque_idx = 0
    i = 0

    while i < len(lineas):
        if not lineas[i].strip().startswith("|"):
            i += 1
            continue

        # Inicio de bloque de tabla
        j = i
        while j < len(lineas) and lineas[j].strip().startswith("|"):
            j += 1
        bloque_lineas = lineas[i:j]

        # Encabezado de sección más cercano hacia arriba
        seccion = ""
        for k in range(i - 1, -1, -1):
            if lineas[k].strip().startswith("#"):
                seccion = lineas[k].strip()
                break

        analisis = _analizar_bloque(bloque_lineas)
        if analisis["es_rota"]:
            resultado.append(TablaSospechosa(
                indice_bloque=bloque_idx,
                motivo=analisis["motivo"],
                n_filas=analisis["n_filas"],
                n_columnas=analisis["n_cols"],
                texto_crudo="\n".join(bloque_lineas),
                seccion_cercana=seccion,
                linea_inicio=i,
                linea_fin=j - 1,
            ))

        bloque_idx += 1
        i = j

    return resultado


# ─── FASE 2 — Localizador de página ──────────────────────────────────────────

def localizar_pagina(tabla: TablaSospechosa, pdf_path: Path) -> int | None:
    """
    Determina en qué página del PDF está la sección de la tabla rota.

    Busca el texto del encabezado de sección (limpiado de markdown) en el
    texto plano de CADA página vía fitz. Devuelve la ÚLTIMA ocurrencia para
    evitar falsos positivos del índice/TOC (que siempre precede al contenido).

    [I8-ext] Busca en TODAS las páginas, sin muestrear.

    Si no se encuentra con certeza: devuelve None.
    Fallo ruidoso; nunca adivina la página.
    """
    if not tabla.seccion_cercana:
        return None

    header_limpio = _limpiar_header_md(tabla.seccion_cercana)
    if not header_limpio:
        return None

    header_norm = _norm(header_limpio)

    # Fallback: primeros 2 tokens del header para búsqueda más tolerante
    tokens_cortos = " ".join(header_norm.split()[:3])

    try:
        doc = fitz.open(str(pdf_path))
        candidatos: list[int] = []
        candidatos_cortos: list[int] = []

        for pg_idx in range(doc.page_count):
            texto_norm = _norm(doc[pg_idx].get_text())
            if header_norm and header_norm in texto_norm:
                candidatos.append(pg_idx)
            elif tokens_cortos and len(tokens_cortos) >= 6 and tokens_cortos in texto_norm:
                candidatos_cortos.append(pg_idx)

        doc.close()

        if candidatos:
            return candidatos[-1]  # última ocurrencia = sección real (no TOC)
        if candidatos_cortos:
            return candidatos_cortos[-1]

    except Exception:
        pass

    return None


# ─── FASE 3 — Extractor pdfplumber ───────────────────────────────────────────

def extraer_tabla_pdfplumber(
    pdf_path: Path,
    pagina: int,
    hint_texto: str = "",
) -> str | None:
    """
    Extrae la mejor tabla de la página indicada y hasta _MAX_PAGINAS_BUSQUEDA
    páginas siguientes, usando estrategia de LÍNEAS (validada en Tarea 1.5).

    Filtro mínimo: ≥2 filas, ≥2 columnas reales (elimina marcos decorativos
    de 1 columna: notas legales, cajas de anotación, encabezados).

    La "mejor" tabla es la que maximiza solapamiento de tokens con hint_texto
    (texto de la tabla rota en marker), lo que resuelve el caso de múltiples
    tablas en la misma página.

    Returns: tabla como markdown limpio, o None si no hay tabla utilizable.
    [I1] Celdas devueltas completas — sin truncar.
    [I3] Erratas del PDF preservadas.
    """
    candidatos: list[tuple[float, str]] = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            n_pags = len(pdf.pages)
            for pg_idx in range(pagina, min(pagina + _MAX_PAGINAS_BUSQUEDA, n_pags)):
                tablas = pdf.pages[pg_idx].extract_tables(table_settings=_STRAT_LINEAS)
                for tabla in tablas:
                    if not tabla:
                        continue
                    cols_reales = _indices_cols_reales(tabla)
                    if len(tabla) < 2 or len(cols_reales) < 2:
                        continue
                    md = _tabla_a_markdown(tabla)
                    score = _score_overlap(md, hint_texto)
                    candidatos.append((score, md))
    except Exception:
        return None

    if not candidatos:
        return None

    candidatos.sort(key=lambda x: -x[0])
    mejor_score, mejor_md = candidatos[0]

    # Si hay hint, exigir solapamiento mínimo para no confundir tablas
    if hint_texto and mejor_score < 0.10:
        return None

    return mejor_md


# ─── FASE 4 — Auditor de fidelidad ───────────────────────────────────────────

def verificar_tabla(
    tabla_md: str,
    pdf_path: Path,
    pagina: int,
) -> tuple[float, list[str], bool]:
    """
    Verifica que cada valor de celda de tabla_md exista en el texto plano de la
    página (fitz page.get_text()), usando la misma normalización que verifier.py.

    [I4] Sin modelo para auditar — str.find normalizado es determinista y
         no tiene sesgo de confirmación.

    Returns:
        (tasa, celdas_fallidas, verificacion_degradada)
        tasa: fracción de celdas verificadas (0.0–1.0)
        celdas_fallidas: valores que no se encontraron en el texto de la página
        verificacion_degradada: True si no había texto nativo (PDF escaneado)

    Caso sin texto nativo (PDF escaneado):
        Devuelve (0.0, [...], True) — no hay fuente contra la que verificar.
        El llamador debe marcar el resultado como "verificacion_degradada" y
        bajar el umbral a _UMBRAL_DEGRADADO.
    """
    # Texto de la página y ventana ampliada (página ± 1 para tablas que paginan)
    texto_combinado = ""
    try:
        doc = fitz.open(str(pdf_path))
        n = doc.page_count
        for pg in range(max(0, pagina - 1), min(n, pagina + 2)):
            texto_combinado += doc[pg].get_text() + " "
        doc.close()
    except Exception:
        return 0.0, [], True

    if not texto_combinado.strip():
        return 0.0, [], True  # PDF escaneado

    texto_norm = _norm(texto_combinado)
    degradada = False

    # Extraer valores de celda del markdown
    celdas: list[str] = []
    for linea in tabla_md.splitlines():
        if _es_separador_md(linea):
            continue
        partes = linea.split("|")
        for celda in partes[1:-1]:
            val = celda.strip()
            if val:
                celdas.append(val)

    if not celdas:
        return 1.0, [], degradada

    fallidas: list[str] = []
    for celda in celdas:
        celda_norm = _norm(celda)
        # Solo verificar celdas con ≥3 caracteres tras normalizar
        if len(celda_norm) >= 3 and celda_norm not in texto_norm:
            fallidas.append(celda)

    verificadas = len(celdas) - len(fallidas)
    tasa = verificadas / len(celdas)
    return tasa, fallidas, degradada


# ─── FASE 5 — Plan B (visión con modelo) ─────────────────────────────────────

_MODELOS_VISION = [
    "claude-haiku-4-5-20251001",   # más barato; escalar si trunca
    "claude-sonnet-4-6",
]


def _matrix_ratio_entero(doc: Any, pagina: int, multiplicador: int = 2) -> fitz.Matrix:
    """
    Calcula la Matrix de fitz que produce un múltiplo ENTERO de la imagen nativa.

    Para fuentes bilevel (bpc=1, típico en documentos escaneados), un ratio
    entero elimina el anti-aliasing de sub-píxel: cada píxel fuente se mapea
    a exactamente multiplicador×multiplicador píxeles de salida, sin mezcla.

    Con ratio no-entero (ej. 1.44×) los bordes de caracteres se convierten en
    grises intermedios; "1,21" y "1.21" pueden ser indistinguibles.

    Proceso:
      1. Lee el ancho en píxeles de la imagen embebida en la página
      2. Calcula scale = (multiplicador × img_w) / mediabox_w_pts
      3. Fallback a Matrix(2, 2) si no hay imagen embebida detectable

    Ejemplo con este documento (1278×1650 px, mediabox 612×792 pts):
      scale = (2 × 1278) / 612 = 4.176  →  salida: 2556×3303 px

    NOTA — Esta función NO se invoca desde reparar_con_modelo(). La API de
    Anthropic normaliza las imágenes internamente: test empírico (2026-08) sobre
    16. PLIEGO DEFINITIVO mostró 4406 tokens de imagen idénticos para los cuatro
    niveles probados (2x / 3x / 4.17x / nativo). El ratio entero es irrelevante
    en la práctica. Se conserva por si la política de normalización de Anthropic
    cambia en el futuro.
    """
    try:
        page = doc[pagina]
        imgs = page.get_images(full=True)
        if imgs and isinstance(imgs[0], (tuple, list)) and len(imgs[0]) > 2:
            img_w = int(imgs[0][2])
            box_w = float(page.mediabox.width)
            if img_w > 0 and box_w > 0:
                scale = (multiplicador * img_w) / box_w
                return fitz.Matrix(scale, scale)
    except Exception:
        pass
    return fitz.Matrix(2.0, 2.0)  # fallback seguro


def reparar_con_modelo(
    pdf_path: Path,
    pagina: int,
    skill_path: Path | None = None,   # mantenido por compat, ignorado
    n_tablas: int = 1,
    surya_refs: list[str] | None = None,
    tipo_pdf: str = "C",
) -> list[str | None]:
    """
    Plan B: transcribir tablas de una página con un modelo de visión.

    PUNTO DE EXTENSIÓN — TIPO A/B únicamente.
    En TIPO C esta función es inalcanzable: localizar_pagina() no puede
    ubicar tablas en PDFs escaneados (pdfplumber devuelve 0 chars) y todas
    las tablas fallan con pagina_no_localizada antes de llegar aquí.
    Si en el futuro el OCR propaga el número de página directamente (punto 3
    de la instrucción de estabilización 2026-08), esta restricción desaparece.

    Carga skills desde disco. Para TIPO C (escaneado) concatena base +
    anexo_escaneados; para TIPO A/B usa solo el base. Ambos se leen
    de disco; no hay prompt embebido en el código.

    El modelo devuelve JSON según el formato del skill. El parseo extrae
    tablas[].markdown y devuelve una lista de n_tablas strings (None = sin tabla).

    [I3] No se pide al modelo que corrija erratas — transcripción literal.
    [I4] La verificación es por similitud de tokens, no por modelo auditor.

    Returns: lista de n_tablas strings markdown (None donde no hay tabla/calidad).
    Raises: EnvironmentError si ANTHROPIC_API_KEY no está configurada.
    Raises: FileNotFoundError si falta el skill obligatorio.
    """
    import base64
    import os

    # Comprobar API key ANTES de cualquier operación costosa
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY no configurada. "
            "reparar_con_modelo requiere acceso a la API de Anthropic."
        )

    # Cargar skill base — obligatorio, sin fallback silencioso
    skills_dir = Path(__file__).parent.parent / "skills"
    base_skill = skills_dir / "transcripcion_tablas.md"
    if not base_skill.exists():
        raise FileNotFoundError(
            f"Skill de transcripción no encontrada: {base_skill}. "
            "El archivo es obligatorio — no hay prompt de respaldo embebido."
        )
    system_text = base_skill.read_text("utf-8")

    # Anexo de escaneados — solo para TIPO C (sin texto nativo)
    if tipo_pdf == "C":
        anexo = skills_dir / "anexo_escaneados.md"
        if not anexo.exists():
            raise FileNotFoundError(
                f"Skill de escaneados no encontrada: {anexo}. "
                "El PDF es TIPO C (escaneado) y requiere este skill."
            )
        system_text += "\n\n" + anexo.read_text("utf-8")

    # 2x (144 dpi) — la API de Anthropic normaliza internamente hasta ~1224×1584 px.
    # Resoluciones mayores producen idénticos tokens de imagen (verificado empíricamente
    # con 2x / 3x / 4.17x / nativo sobre 16. PLIEGO DEFINITIVO, 2026-08).
    doc = fitz.open(str(pdf_path))
    if pagina >= doc.page_count:
        doc.close()
        return [None] * n_tablas
    pix = doc[pagina].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
    imagen_b64 = base64.b64encode(pix.tobytes("png")).decode()
    doc.close()

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    for modelo in _MODELOS_VISION:
        try:
            resp = client.messages.create(
                model=modelo,
                max_tokens=8_000,
                extra_body={"temperature": 0.0},
                system=[{
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Página {pagina} del PDF.",
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": imagen_b64,
                            },
                        },
                    ],
                }],
            )
        except Exception as exc:
            print(f"  [VISION] Error con {modelo}: {exc}", flush=True)
            continue

        if resp.stop_reason == "max_tokens":
            print(f"  [VISION] {modelo} truncó (max_tokens); escalando...", flush=True)
            continue

        texto: str | None = None
        for bloque in resp.content:
            if getattr(bloque, "type", None) == "text":
                texto = bloque.text.strip()
                break

        if not texto:
            continue

        # Limpiar posible envoltorio markdown (modelo añade ``` pese a la instrucción)
        texto_clean = re.sub(r"^```(?:json)?\s*", "", texto, flags=re.MULTILINE).strip()
        texto_clean = re.sub(r"```\s*$", "", texto_clean, flags=re.MULTILINE).strip()

        # Parsear JSON — el skill especifica salida JSON exclusivamente
        try:
            data = json.loads(texto_clean)
        except json.JSONDecodeError:
            print(f"  [VISION] {modelo} devolvió JSON inválido; escalando...", flush=True)
            continue

        # Página ilegible completa (E5)
        if data.get("calidad_insuficiente", False):
            return [None] * n_tablas

        tablas_data = data.get("tablas", [])
        resultado: list[str | None] = []
        for t in tablas_data[:n_tablas]:
            if isinstance(t, dict):
                md = t.get("markdown", "").strip()
                resultado.append(md if md else None)
            else:
                resultado.append(None)

        while len(resultado) < n_tablas:
            resultado.append(None)

        return resultado

    return [None] * n_tablas


# ─── FASE 6 — Sustitución y auditoría ────────────────────────────────────────

def reparar_markdown(
    markdown: str,
    pdf_path: Path,
) -> tuple[str, dict]:
    """
    Orquesta las FASES 1–5 sobre un markdown completo.

    TIPO C (escaneado con Claude OCR): Claude produce tablas Markdown
    correctamente formateadas con valores cortos legítimos (SI/NO, fechas,
    códigos). El detector dispara falsos positivos sobre este output. La
    reparación es inútil: localizar_pagina() requiere texto nativo vía
    pdfplumber, que devuelve 0 chars en TIPO C. Resultado observado (2026-08,
    16. PLIEGO DEFINITIVO, 31 tablas detectadas): 100% pagina_no_localizada,
    0 reparadas. El módulo corre sin efecto pero no produce errores.

    TIPO A/B (vectorial): flujo completo disponible.
      FASE B — priorización: tablas con celdas largas (>40 chars en el PDF) primero.
      FASE C — per-page: una sola llamada al modelo por página (no por tabla).

    Flujo por tabla (TIPO A/B):
      1. Pre-scan: localizar página + extraer con pdfplumber (único pasada)
      2. Ordenar: tablas con celda > 40 chars van primero
      3. Si pdfplumber verifica (tasa >= umbral): sustituir
      4. Si pdfplumber falla o no verifica: acolar para el modelo
      5. Por cada página con tablas pendientes: UNA llamada a reparar_con_modelo
      6. Aplicar sustituciones de abajo hacia arriba

    [I1] El número de líneas no-tabla del markdown final no puede ser menor
         que el del original.

    Returns:
        (markdown_reparado, metadata)
    """
    tipo_pdf = _clasificar_tipo_pdf(pdf_path)
    sospechosas = detectar_tablas_rotas(markdown)

    # ── Pre-scan: página + pdfplumber en un solo pasada ─────────────────────
    pre: list[tuple[TablaSospechosa, int | None, str | None, bool]] = []
    for ts in sospechosas:
        pagina = localizar_pagina(ts, pdf_path)
        tabla_md = None
        tiene_celda_larga = False
        if pagina is not None:
            tabla_md = extraer_tabla_pdfplumber(pdf_path, pagina, hint_texto=ts.texto_crudo)
            if tabla_md:
                tiene_celda_larga = any(
                    len(c.strip()) > 40
                    for linea in tabla_md.splitlines()
                    if not _es_separador_md(linea)
                    for c in linea.split("|")[1:-1]
                )
        pre.append((ts, pagina, tabla_md, tiene_celda_larga))

    # Tablas con texto largo primero (son las que fragmentan citas legales)
    pre.sort(key=lambda x: -int(x[3]))

    # ── Procesar en orden de prioridad ───────────────────────────────────────
    resultados: dict[int, ResultadoTabla] = {}
    reemplazos: list[tuple[int, int, str]] = []
    # pagina → [(ts, surya_texto)]  — tablas que necesitan el modelo
    pendientes_modelo: dict[int, list[tuple[TablaSospechosa, str]]] = {}

    for ts, pagina, tabla_md, _ in pre:
        res = ResultadoTabla(tabla=ts)
        resultados[ts.indice_bloque] = res

        if pagina is None:
            res.estado = "pagina_no_localizada"
            continue
        res.pagina = pagina

        if tabla_md is None:
            pendientes_modelo.setdefault(pagina, []).append((ts, ts.texto_crudo))
            continue

        tasa, fallidas, degradada = verificar_tabla(tabla_md, pdf_path, pagina)
        res.tasa_verificacion = tasa
        res.celdas_fallidas = fallidas
        res.verificacion_degradada = degradada
        umbral = _UMBRAL_DEGRADADO if degradada else _UMBRAL_ACEPTAR

        if tasa >= umbral:
            res.estado = "reparada"
            res.tabla_reparada_md = tabla_md
            reemplazos.append((ts.linea_inicio, ts.linea_fin, tabla_md))
        else:
            # pdfplumber halló tabla pero no verificó → cola para el modelo
            pendientes_modelo.setdefault(pagina, []).append((ts, ts.texto_crudo))

    # ── UNA llamada por PÁGINA (FASE C) ─────────────────────────────────────
    for pagina, items in pendientes_modelo.items():
        n_tablas = len(items)
        surya_refs = [surya for _, surya in items]
        try:
            tablas_modelo = reparar_con_modelo(pdf_path, pagina, n_tablas=n_tablas, tipo_pdf=tipo_pdf)
        except Exception as exc:
            print(f"  [WARN tablas] página {pagina}: {type(exc).__name__}: {exc}", flush=True)
            for ts, _ in items:
                resultados[ts.indice_bloque].estado = "reparacion_no_disponible"
            continue

        for i, (ts, surya) in enumerate(items):
            res = resultados[ts.indice_bloque]
            tabla_md = tablas_modelo[i] if i < len(tablas_modelo) else None

            if tabla_md is None:
                res.estado = "calidad_insuficiente"
                continue

            # Verificar por similitud de tokens (no hay texto nativo en escaneados)
            tasa, fallidas = _verificar_similitud(tabla_md, surya)
            res.tasa_verificacion = tasa
            res.celdas_fallidas = fallidas
            res.verificacion_degradada = True

            if tasa >= _UMBRAL_DEGRADADO:
                res.estado = "reparada"
                res.via = "modelo"
                res.tabla_reparada_md = tabla_md
                reemplazos.append((ts.linea_inicio, ts.linea_fin, tabla_md))
            else:
                res.estado = "rechazada"

    # ── FASE 6 — aplicar sustituciones de abajo hacia arriba ────────────────
    lineas = markdown.splitlines()
    n_lineas_no_tabla_orig = sum(1 for l in lineas if not l.strip().startswith("|"))

    for inicio, fin, nuevo_md in sorted(reemplazos, key=lambda x: -x[0]):
        lineas[inicio:fin + 1] = nuevo_md.splitlines()

    md_final = "\n".join(lineas)

    n_lineas_no_tabla_final = sum(
        1 for l in md_final.splitlines() if not l.strip().startswith("|")
    )
    assert n_lineas_no_tabla_final >= n_lineas_no_tabla_orig, (
        f"[I1] Sustitución eliminó contenido no-tabla: "
        f"{n_lineas_no_tabla_final} líneas vs {n_lineas_no_tabla_orig} originales."
    )

    # ── Metadata ─────────────────────────────────────────────────────────────
    todos = list(resultados.values())
    reparadas_plumber = sum(1 for r in todos if r.estado == "reparada" and r.via == "pdfplumber")
    reparadas_modelo  = sum(1 for r in todos if r.estado == "reparada" and r.via == "modelo")
    rechazadas        = sum(1 for r in todos if r.estado == "rechazada")
    no_localizada     = sum(1 for r in todos if r.estado == "pagina_no_localizada")
    no_disponible     = sum(1 for r in todos if r.estado == "reparacion_no_disponible")
    sin_tabla         = sum(1 for r in todos if r.estado == "sin_tabla_plumber")
    calidad_insuf     = sum(1 for r in todos if r.estado == "calidad_insuficiente")

    tasas = [r.tasa_verificacion for r in todos if r.estado == "reparada"]
    tasa_media = sum(tasas) / len(tasas) if tasas else 0.0

    metadata: dict = {
        "tablas_totales": _contar_bloques_tabla(markdown),
        "tablas_rotas_detectadas": len(sospechosas),
        "tablas_reparadas_pdfplumber": reparadas_plumber,
        "tablas_reparadas_modelo": reparadas_modelo,
        "tablas_rechazadas": rechazadas,
        "tablas_pagina_no_localizada": no_localizada,
        "tablas_reparacion_no_disponible": no_disponible,
        "tablas_sin_tabla_plumber": sin_tabla,
        "tablas_calidad_insuficiente": calidad_insuf,
        "tasa_verificacion_media": round(tasa_media, 4),
        "tipo_pdf": tipo_pdf,
    }

    return md_final, metadata


def _contar_bloques_tabla(markdown: str) -> int:
    """Cuenta bloques de tabla (secuencias contiguas de líneas con '|')."""
    en_tabla = False
    count = 0
    for linea in markdown.splitlines():
        es_tabla = linea.strip().startswith("|")
        if es_tabla and not en_tabla:
            count += 1
        en_tabla = es_tabla
    return count
