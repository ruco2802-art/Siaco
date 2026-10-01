# -*- coding: utf-8 -*-
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=False)  # Railway env vars tienen prioridad sobre .env local

API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Sentinel retornado por las funciones de extracción cuando el PDF es una
# imagen escaneada y Tesseract no está disponible en el servidor.
SCANNED_PDF_MARKER = "__SCANNED_PDF_NO_OCR__"


def _limpiar_markdown(texto):
    """
    Quita bloques ```json ... ``` o ``` ... ``` que Claude agrega al responder.
    Devuelve el contenido interno limpio, o el texto original si no hay bloque.
    """
    texto = texto.strip()
    if "```" not in texto:
        return texto
    partes = texto.split("```")
    # Los índices impares son el contenido dentro de los bloques de código
    for frag in partes[1::2]:
        limpio = frag.strip()
        if limpio.lower().startswith("json"):
            limpio = limpio[4:].strip()
        if limpio:
            return limpio
    return texto


def _extraer_json(texto):
    """
    Extrae un objeto JSON de la respuesta de Claude, incluso si viene
    envuelto en ```json ... ``` o con texto adicional alrededor.
    Lanza json.JSONDecodeError con el texto crudo incluido si no logra parsear.
    """
    texto = texto.strip()

    # 1. Limpiar bloque markdown y parsear directamente
    texto_limpio = _limpiar_markdown(texto)
    try:
        return json.loads(texto_limpio)
    except json.JSONDecodeError:
        pass

    # 2. Intento directo sobre el texto original (sin bloque)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass

    # 3. Buscar el primer '{' y el último '}' del texto limpio
    for candidato in (texto_limpio, texto):
        inicio = candidato.find("{")
        fin = candidato.rfind("}")
        if inicio != -1 and fin != -1 and fin > inicio:
            try:
                return json.loads(candidato[inicio:fin + 1])
            except json.JSONDecodeError:
                pass

    # 4. Si nada funcionó, lanzar error con el texto crudo para depuración
    raise json.JSONDecodeError(
        f"No se pudo extraer JSON. Respuesta cruda de Claude:\n{texto[:1000]}",
        texto, 0
    )


def _listar_documentos_relevantes(modalidad, sector):
    """
    Recorre la biblioteca normativa y extrae el texto COMPLETO de cada
    documento relevante para la modalidad/sector (sin recortar), junto
    con sus metadatos (nombre de archivo, carpeta).

    Reglas de inclusión:
    - Archivos en la raíz de la modalidad (resoluciones transversales): siempre se incluyen.
    - Archivos dentro de cualquier carpeta cuyo nombre contenga el sector (con o sin
      tildes/variantes) o la palabra "transversal": se incluyen.
    - Carpetas de otros sectores se omiten.

    Devuelve: lista de dicts {"archivo": str, "carpeta": str, "texto": str}
    """
    import os
    import fitz  # PyMuPDF
    import pandas as pd
    from docx import Document

    variantes_sector = {
        "educacion": ["educacion", "educación", "educativo", "educativa"],
        "salud": ["salud"],
        "deporte": ["deporte", "cultura", "recreacion", "recreación"],
        "vivienda": ["vivienda"],
        "institucional": ["institucional"],
    }
    claves_sector = variantes_sector.get(sector.lower(), [sector.lower()])

    ruta_carpeta = f"./biblioteca_normativa/{modalidad}"
    documentos = []
    LIMITE_PAGINAS_PDF = 60  # tope de seguridad por documento PDF

    if not os.path.exists(ruta_carpeta):
        return documentos

    def _ruta_relevante(raiz):
        rel = os.path.relpath(raiz, ruta_carpeta).lower()
        if rel == ".":
            return True
        if "transversal" in rel:
            return True
        return any(clave in rel for clave in claves_sector)

    def _limpiar_texto(texto):
        """Colapsa espacios múltiples, elimina tokens 'NaN' sueltos."""
        import re as _re
        texto = _re.sub(r"\bNaN\b", "", texto)
        texto = _re.sub(r"[ \t]+", " ", texto)
        texto = _re.sub(r"\n\s*\n+", "\n", texto)
        return texto.strip()

    for raiz, carpetas, archivos in os.walk(ruta_carpeta):
        if not _ruta_relevante(raiz):
            continue

        archivos_lower = {a.lower() for a in archivos}

        for archivo in archivos:
            ruta_completa = os.path.join(raiz, archivo)
            nombre_lower = archivo.lower()
            base, ext = os.path.splitext(nombre_lower)
            extraido = ""

            # Si existe un .txt con el mismo nombre base, omitir .xlsx/.docx
            # equivalentes (el .txt es la versión ya convertida/limpia).
            if ext in (".xlsx", ".xls", ".docx") and f"{base}.txt" in archivos_lower:
                continue

            if nombre_lower.endswith(".txt"):
                try:
                    with open(ruta_completa, "r", encoding="utf-8", errors="ignore") as f:
                        extraido = f.read()
                except Exception as e:
                    extraido = f"[Error leyendo TXT {archivo}: {str(e)}]"

            elif nombre_lower.endswith(".docx"):
                try:
                    doc = Document(ruta_completa)
                    extraido = "\n".join(p.text for p in doc.paragraphs)
                except Exception as e:
                    extraido = f"[Error leyendo Word {archivo}: {str(e)}]"

            elif nombre_lower.endswith((".xlsx", ".xls")):
                try:
                    df = pd.read_excel(ruta_completa)
                    extraido = df.to_string()
                except Exception as e:
                    extraido = f"[Error leyendo Excel {archivo}: {str(e)}]"

            elif nombre_lower.endswith(".pdf"):
                try:
                    doc_pdf = fitz.open(str(ruta_completa))
                    paginas_texto = []
                    for i, pagina in enumerate(doc_pdf):
                        if i >= LIMITE_PAGINAS_PDF:
                            break
                        paginas_texto.append(pagina.get_text() or "")
                    extraido = "\n".join(paginas_texto)
                except Exception as e:
                    extraido = f"[Error leyendo PDF {archivo}: {str(e)}]"

            else:
                continue

            extraido = _limpiar_texto(extraido)
            if extraido:
                documentos.append({
                    "archivo": archivo,
                    "carpeta": os.path.relpath(raiz, ruta_carpeta),
                    "texto": extraido,
                })

    return documentos


def _chunkear_texto(texto, tamano=900, solapamiento=150):
    """
    Divide un texto largo en fragmentos (chunks) de tamaño aproximado
    `tamano` caracteres, con solapamiento entre fragmentos consecutivos
    para no perder contexto en los bordes.
    """
    texto = texto.strip()
    if len(texto) <= tamano:
        return [texto]

    chunks = []
    inicio = 0
    while inicio < len(texto):
        fin = inicio + tamano
        chunk = texto[inicio:fin]
        if chunk.strip():
            chunks.append(chunk)
        inicio += tamano - solapamiento

    return chunks


_modelo_embeddings = None


def _obtener_modelo_embeddings():
    """Carga el modelo de sentence-transformers (una sola vez, perezosamente)."""
    global _modelo_embeddings
    if _modelo_embeddings is None:
        from sentence_transformers import SentenceTransformer
        _modelo_embeddings = SentenceTransformer("all-MiniLM-L6-v2")
    return _modelo_embeddings


def verificar_embeddings() -> dict:
    """
    Verifica si el servicio de embeddings responde correctamente.
    Retorna {"disponible": bool, "error": str | None}.
    Llamar antes de corridas por lote para abortar temprano si el modelo no está listo.
    """
    try:
        modelo = _obtener_modelo_embeddings()
        modelo.encode(["verificacion_salud"], show_progress_bar=False)
        return {"disponible": True, "error": None}
    except Exception as exc:
        return {"disponible": False, "error": str(exc)}


def _extraer_keywords(texto):
    """Extrae palabras clave simples (>3 caracteres) de un texto en español."""
    import re as _re
    palabras_vacias = {
        "para", "como", "este", "esta", "estos", "estas", "el", "la", "los", "las",
        "de", "del", "en", "con", "por", "que", "una", "uno", "y", "o", "se", "su",
        "sus", "al", "lo", "le", "les", "es", "son", "ser", "más", "menos", "sin",
        "sobre", "entre", "según", "cada", "todo", "toda", "todos", "todas",
    }
    palabras = _re.findall(r"[a-záéíóúñ0-9]{4,}", texto.lower())
    return set(p for p in palabras if p not in palabras_vacias)


def buscar_chunks_relevantes(modalidad, sector, consulta, top_k=8,
                              peso_keywords=0.4, peso_semantico=0.6):
    """
    RAG híbrido: extrae documentos de la biblioteca normativa, los divide
    en chunks, y devuelve los `top_k` fragmentos más relevantes para la
    `consulta` (texto que describe la licitación: objeto + sector + valor),
    combinando:
      - coincidencia de palabras clave (score_keywords)
      - similitud semántica por embeddings (score_semantico)

    Devuelve: lista de dicts {"archivo", "carpeta", "texto", "score"}
    ordenada de mayor a menor relevancia.
    """
    import numpy as np

    documentos = _listar_documentos_relevantes(modalidad, sector)
    if not documentos:
        return []

    # 1. Chunking de todos los documentos, descartando fragmentos de bajo contenido
    import re as _re
    MIN_CARACTERES_ALFA = 40  # un chunk debe tener al menos esta cantidad de letras reales

    chunks = []
    for doc in documentos:
        for fragmento in _chunkear_texto(doc["texto"]):
            num_letras = len(_re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]", fragmento))
            if num_letras < MIN_CARACTERES_ALFA:
                continue
            chunks.append({
                "archivo": doc["archivo"],
                "carpeta": doc["carpeta"],
                "texto": fragmento,
            })

    if not chunks:
        return []

    # 2. Score por palabras clave (Jaccard simple entre consulta y chunk)
    kw_consulta = _extraer_keywords(consulta)
    scores_kw = []
    for c in chunks:
        kw_chunk = _extraer_keywords(c["texto"])
        if not kw_consulta or not kw_chunk:
            scores_kw.append(0.0)
            continue
        interseccion = len(kw_consulta & kw_chunk)
        scores_kw.append(interseccion / len(kw_consulta))

    scores_kw = np.array(scores_kw)
    if scores_kw.max() > 0:
        scores_kw = scores_kw / scores_kw.max()  # normalizar a [0,1]

    # 3. Score semántico (similitud coseno de embeddings)
    try:
        modelo = _obtener_modelo_embeddings()
        textos_chunks = [c["texto"] for c in chunks]
        emb_chunks = modelo.encode(textos_chunks, convert_to_numpy=True, show_progress_bar=False)
        emb_consulta = modelo.encode([consulta], convert_to_numpy=True, show_progress_bar=False)[0]

        # similitud coseno
        emb_chunks_norm = emb_chunks / np.linalg.norm(emb_chunks, axis=1, keepdims=True)
        emb_consulta_norm = emb_consulta / np.linalg.norm(emb_consulta)
        scores_sem = emb_chunks_norm @ emb_consulta_norm

        # normalizar a [0,1]
        rango = scores_sem.max() - scores_sem.min()
        if rango > 0:
            scores_sem = (scores_sem - scores_sem.min()) / rango
    except Exception:
        # Si sentence-transformers no está disponible, usar solo keywords
        scores_sem = np.zeros(len(chunks))
        peso_keywords, peso_semantico = 1.0, 0.0

    # 4. Score combinado
    scores_finales = peso_keywords * scores_kw + peso_semantico * scores_sem

    # 5. Ordenar y devolver top_k
    indices_ordenados = np.argsort(scores_finales)[::-1][:top_k]
    resultado = []
    for i in indices_ordenados:
        resultado.append({
            "archivo": chunks[i]["archivo"],
            "carpeta": chunks[i]["carpeta"],
            "texto": chunks[i]["texto"],
            "score": float(scores_finales[i]),
        })

    return resultado


def obtener_contexto_legal(modalidad, sector, consulta=None, top_k=8):
    """
    Punto de entrada principal del RAG legal.

    Si se proporciona `consulta` (texto describiendo la licitación), se
    realiza una búsqueda híbrida (keywords + semántica) y se devuelve solo
    el texto de los `top_k` chunks más relevantes, formateado para inyectar
    en el prompt del agente legal.

    Si `consulta` es None, se mantiene compatibilidad hacia atrás devolviendo
    el contexto completo sin chunking (uso no recomendado para bibliotecas grandes).
    """
    if consulta is None:
        documentos = _listar_documentos_relevantes(modalidad, sector)
        if not documentos:
            return f"Advertencia: No se encontraron documentos relevantes para modalidad='{modalidad}' y sector='{sector}'."
        contexto = ""
        for doc in documentos:
            contexto += f"\n--- Documento: {doc['archivo']} (carpeta: {doc['carpeta']}) ---\n"
            contexto += doc["texto"][:8000] + "\n"
        return contexto

    chunks = buscar_chunks_relevantes(modalidad, sector, consulta, top_k=top_k)
    if not chunks:
        return f"Advertencia: No se encontraron documentos relevantes para modalidad='{modalidad}' y sector='{sector}'."

    contexto = ""
    for c in chunks:
        contexto += f"\n--- Fragmento de: {c['archivo']} (carpeta: {c['carpeta']}, relevancia: {c['score']:.2f}) ---\n"
        contexto += c["texto"] + "\n"

    return contexto


def escanear_paginas_pdf(ruta_pdf_o_bytes):
    """
    Extractor híbrido reutilizado de escrapeador_pliegos.py.
    Acepta una ruta de archivo (str) o bytes en memoria (bytes).

    - Si la página tiene texto nativo suficiente (>=100 chars): lo usa directamente.
    - Si la página está escaneada: aplica Tesseract OCR (spa) como respaldo.
    - Filtra solo las páginas con keywords financieros/habilitantes.
    - Devuelve las 7 páginas más densas como lista de dicts {"pagina", "texto"}.
    """
    import io as _io
    import sys
    import fitz  # PyMuPDF
    TESSERACT_DISPONIBLE = False
    try:
        import pytesseract
        from PIL import Image
        if sys.platform == "win32":
            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        TESSERACT_DISPONIBLE = True
    except ImportError:
        pass

    keywords_habilitantes = [
        'liquidez', 'endeudamiento', 'capital de trabajo', 'cobertura',
        'requisitos financieros', 'capacidad organizacional', 'rentabilidad',
        'rup', 'experiencia', 'unspsc', 'objeto similar', 'valor acumulado',
        'habilitante', 'requisito', 'capacidad residual', 'patrimonio',
        'margen', 'indicador', 'criterio',
    ]

    try:
        if isinstance(ruta_pdf_o_bytes, (bytes, bytearray)):
            doc = fitz.open(stream=ruta_pdf_o_bytes, filetype="pdf")
        else:
            doc = fitz.open(str(ruta_pdf_o_bytes))
    except Exception as e:
        return [{"pagina": 0, "texto": f"[Error abriendo PDF: {str(e)}]"}]

    paginas_criticas = []
    paginas_escaneadas = 0
    for i, pagina in enumerate(doc):
        texto = pagina.get_text()
        if len(texto.strip()) < 100:
            paginas_escaneadas += 1
            if TESSERACT_DISPONIBLE:
                try:
                    pix = pagina.get_pixmap(matrix=fitz.Matrix(2, 2))
                    imagen = Image.open(_io.BytesIO(pix.tobytes("png")))
                    texto = pytesseract.image_to_string(imagen, lang='spa')
                except Exception:
                    pass  # conserva el texto nativo residual

        texto_min = texto.lower()
        if any(kw in texto_min for kw in keywords_habilitantes):
            paginas_criticas.append({"pagina": i + 1, "texto": texto})

    # PDF de imagen sin OCR disponible: señal explícita para el router
    if not paginas_criticas and paginas_escaneadas > 0 and not TESSERACT_DISPONIBLE:
        return [{"pagina": 0, "texto": SCANNED_PDF_MARKER}]

    paginas_criticas.sort(key=lambda x: len(x["texto"]), reverse=True)
    return paginas_criticas[:7]


def extraer_texto_pliego(ruta_pdf_o_bytes):
    """
    Función de conveniencia: llama a escanear_paginas_pdf() y concatena
    el texto de las páginas relevantes en un único string listo para
    inyectar en el prompt de los agentes.
    Retorna SCANNED_PDF_MARKER si el PDF es imagen sin OCR disponible.
    """
    paginas = escanear_paginas_pdf(ruta_pdf_o_bytes)
    if not paginas:
        return ""
    # Propaga el sentinel sin modificarlo
    if len(paginas) == 1 and paginas[0].get("texto") == SCANNED_PDF_MARKER:
        return SCANNED_PDF_MARKER
    bloques = []
    for p in paginas:
        bloques.append(f"--- EXTRACTO PÁGINA {p['pagina']} ---\n{p['texto']}")
    return "\n".join(bloques)


def extraer_texto_completo_pdf(raw_bytes: bytes) -> str:
    """
    Extrae TODO el texto del PDF sin filtrar por keywords.
    OCR automático (Tesseract spa) si la página tiene < 50 chars de texto nativo.
    Retorna SCANNED_PDF_MARKER si el PDF es imagen sin OCR disponible.
    Retorna string vacío si el PDF no se puede leer.
    """
    import io as _io
    import sys
    import fitz

    TESSERACT = False
    try:
        import pytesseract
        from PIL import Image
        if sys.platform == "win32":
            pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        TESSERACT = True
    except ImportError:
        pass

    try:
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
    except Exception as e:
        print(f"[PDF] Error abriendo PDF: {e}")
        return ""

    bloques = []
    paginas_escaneadas = 0
    for i, pagina in enumerate(doc):
        texto = pagina.get_text().strip()
        if len(texto) < 50:
            paginas_escaneadas += 1
            if TESSERACT:
                try:
                    pix = pagina.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img = Image.open(_io.BytesIO(pix.tobytes("png")))
                    texto = pytesseract.image_to_string(img, lang="spa").strip()
                except Exception:
                    pass
        if texto:
            bloques.append(f"--- PÁGINA {i + 1} ---\n{texto}")

    resultado = "\n".join(bloques)
    print(f"[PDF] Extraídas {len(bloques)} páginas — {len(resultado)} chars totales")

    # PDF es imagen escaneada y OCR no está disponible
    if not resultado.strip() and paginas_escaneadas > 0:
        return SCANNED_PDF_MARKER

    return resultado


# Sentinel para archivos .doc (Word 97-2003) que python-docx no puede abrir
DOC_NOT_SUPPORTED_MARKER = "__DOC_LEGACY_NOT_SUPPORTED__"

# Sentinel para requisitos que no pudieron evaluarse por retrieval insuficiente.
# Distinto de NO_ENCONTRADO_EN_PLIEGO (que significa "se buscó y no está").
NO_ANALIZADO_SENTINEL = "NO_ANALIZADO_CONTEXTO_INSUFICIENTE"

# Umbral configurable: % mínimo de chars_totales_documento que deben llegar
# a Claude para considerar el retrieval "completo". Basado en corridas exitosas
# de la Tarea 3 (~21 %) — se usa 12 % para dar margen a pliegos cortos.
COBERTURA_NORMAL_MIN_PCT = 12.0


def extraer_texto_word(archivo_bytes: bytes) -> str:
    """Extrae texto y tablas de un documento Word (.docx)."""
    import io as _io
    try:
        from docx import Document
    except ImportError:
        return ""
    try:
        doc = Document(_io.BytesIO(archivo_bytes))
        partes = [p.text for p in doc.paragraphs if p.text.strip()]
        for tabla in doc.tables:
            for fila in tabla.rows:
                celda_textos = " | ".join(
                    c.text.strip() for c in fila.cells if c.text.strip()
                )
                if celda_textos:
                    partes.append(celda_textos)
        resultado = "\n".join(partes)
        print(f"[WORD] {len(partes)} bloques — {len(resultado)} chars")
        return resultado
    except Exception as e:
        print(f"[WORD] Error: {e}")
        return ""


def extraer_texto_imagen(archivo_bytes: bytes) -> str:
    """Extrae texto de una imagen con Tesseract OCR (retorna SCANNED_PDF_MARKER si OCR falla)."""
    import io as _io
    import sys
    try:
        import pytesseract
        from PIL import Image
        if sys.platform == "win32":
            pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        imagen = Image.open(_io.BytesIO(archivo_bytes))
        texto = pytesseract.image_to_string(imagen, lang="spa").strip()
        print(f"[IMG] OCR — {len(texto)} chars")
        return texto
    except Exception as e:
        print(f"[IMG] OCR error: {e}")
        return SCANNED_PDF_MARKER


def extraer_texto_xlsx(archivo_bytes: bytes) -> str:
    """Extrae texto de celdas de un archivo Excel (.xlsx/.xls)."""
    import io as _io
    try:
        import openpyxl
        wb = openpyxl.load_workbook(_io.BytesIO(archivo_bytes), data_only=True)
        partes: list[str] = []
        for nombre_hoja in wb.sheetnames:
            hoja = wb[nombre_hoja]
            partes.append(f"=== Hoja: {nombre_hoja} ===")
            for fila in hoja.iter_rows(values_only=True):
                celda_textos = " | ".join(
                    str(c) for c in fila if c is not None and str(c).strip()
                )
                if celda_textos:
                    partes.append(celda_textos)
        resultado = "\n".join(partes)
        print(f"[XLSX] {len(wb.sheetnames)} hojas — {len(resultado)} chars")
        return resultado
    except Exception as e:
        print(f"[XLSX] Error: {e}")
        return ""


def extraer_texto_documento(archivo_bytes: bytes, filename: str) -> tuple[str, str]:
    """
    Extractor unificado multimodal. Retorna (texto, formato_detectado).
    formato_detectado: 'pdf' | 'word' | 'imagen' | 'excel' | 'doc_legacy' | 'desconocido'
    """
    ext = filename.rsplit(".", 1)[-1].lower() if filename and "." in filename else ""

    if ext == "pdf":
        return extraer_texto_completo_pdf(archivo_bytes), "pdf"
    elif ext == "docx":
        return extraer_texto_word(archivo_bytes), "word"
    elif ext == "doc":
        return DOC_NOT_SUPPORTED_MARKER, "doc_legacy"
    elif ext in ("png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif"):
        return extraer_texto_imagen(archivo_bytes), "imagen"
    elif ext in ("xlsx", "xls"):
        return extraer_texto_xlsx(archivo_bytes), "excel"
    else:
        return "", "desconocido"


_RAG_QUERIES = [
    "requisitos financieros indice liquidez endeudamiento capital trabajo patrimonio",
    "experiencia tecnica contratos anteriores similares UNSPSC CIIU objeto similar",
    "requisitos habilitantes juridicos RUP camara comercio capacidad juridica",
    "objeto contrato valor presupuesto oficial precio base estimado",
    "plazo ejecucion anticipo forma pago modalidad seleccion cronograma",
]


def _es_tabla_contenido(chunk: str) -> bool:
    """
    Detecta si un chunk es predominantemente tabla de contenido (índice de secciones).
    Si es ToC: se excluye del indexado semántico pero se conserva como mapa de secciones.
    """
    import re as _re

    lineas = [l for l in chunk.split('\n') if l.strip()]
    if len(lineas) < 4:
        return False

    patron_toc_clasico = _re.compile(r'^\s*\d+(\.\d+)*\s+.{3,}\.{3,}')  # "1.2. Texto....."
    patron_num_inicio  = _re.compile(r'^\s*\d+(\.\d+)+\s')               # "1.2 " o "3.9.1 "
    patron_puntos      = _re.compile(r'\.{3,}')

    n_toc    = sum(1 for l in lineas if patron_toc_clasico.match(l))
    n_num    = sum(1 for l in lineas if patron_num_inicio.match(l))
    n_puntos = sum(1 for l in lineas if patron_puntos.search(l))
    total    = len(lineas)

    if n_toc / total > 0.25:       # ToC clásico con puntos
        return True
    if n_num / total > 0.45 and n_puntos / total > 0.20:  # índice denso sin puntos largos
        return True
    return False


def chunking_rag_pliego(
    texto: str, query: str = "", top_k_por_query: int = 5, max_chars: int = 50_000
) -> "tuple[str, dict]":
    """
    RAG semántico multi-query para pliegos de cualquier tamaño.

    - Chunking: 2.000 chars con overlap 250
    - La tabla de contenido se excluye del indexado semántico y se conserva como
      mapa de secciones al inicio del resultado (primer elemento del split).
    - 5 queries especializadas + query de usuario → top_k_por_query chunks únicos por query
    - Resultado ordenado por posición original para coherencia narrativa
    - Fallback sin modelo: primeros + últimos chunks de contenido

    Retorna: (contexto_str, meta_dict) donde meta_dict contiene:
      - embeddings_disponibles (bool)
      - n_chunks_content (int)
      - n_chunks_seleccionados (int)
      - chars_enviados (int)
      - motivo_degradacion (str | None)
    """
    CHUNK_SIZE = 2000
    OVERLAP    = 250
    MAX_CHARS  = max_chars  # configurable por corrida; default 50_000

    def _meta(emb_ok, n_content, n_sel, resultado_str, motivo=None):
        return {
            "embeddings_disponibles": emb_ok,
            "n_chunks_content":       n_content,
            "n_chunks_seleccionados": n_sel,
            "chars_enviados":         len(resultado_str),
            "motivo_degradacion":     motivo,
        }

    # ── Chunking ──────────────────────────────────
    chunks_all = []    # list of (original_pos, text)
    pos = 0
    while pos < len(texto):
        chunk = texto[pos: pos + CHUNK_SIZE].strip()
        if len(chunk) > 100:
            chunks_all.append((pos, chunk))
        pos += CHUNK_SIZE - OVERLAP

    if not chunks_all:
        r = texto[:MAX_CHARS]
        return r, _meta(False, 0, 0, r, "Sin chunks extraíbles del documento")

    # ── Separar tabla de contenido de contenido real ──────────────────────────
    chunks_toc     = [(p, t) for p, t in chunks_all if _es_tabla_contenido(t)]
    chunks_content = [(p, t) for p, t in chunks_all if not _es_tabla_contenido(t)]

    toc_text = ""
    if chunks_toc:
        toc_joined = "\n\n".join(t for _, t in chunks_toc[:3])  # máx 3 chunks de índice
        toc_text = f"[ÍNDICE DE SECCIONES DEL PLIEGO]\n{toc_joined}"
        print(f"[RAG] {len(chunks_toc)} chunk(s) de tabla de contenido separados del indexado semántico")

    # Si todo el texto era ToC (poco probable), indexar todo
    chunks = chunks_content if chunks_content else chunks_all

    if len(chunks) <= top_k_por_query:
        contenido = "\n\n[...]\n\n".join(c[1] for c in chunks)
        resultado = toc_text + "\n\n[...]\n\n" + contenido if toc_text else contenido
        r = resultado[:MAX_CHARS]
        return r, _meta(True, len(chunks), len(chunks), r)

    print(f"[RAG] {len(chunks)} chunks de contenido de {len(texto)} chars (excl. {len(chunks_toc)} ToC)")

    # ── Embedding + recuperación ───────────────────
    try:
        import numpy as np

        print("[RAG] Generando embeddings...")
        model  = _obtener_modelo_embeddings()
        texts  = [c[1] for c in chunks]
        c_embs = model.encode(texts, show_progress_bar=False)

        queries = ([query] if query else []) + _RAG_QUERIES
        selected: set[int] = set()

        for q in queries:
            q_emb  = model.encode([q])
            scores = np.dot(c_embs, q_emb.T).flatten()
            top_n  = min(top_k_por_query, len(chunks))
            top_ix = np.argsort(scores)[::-1][:top_n].tolist()
            selected.update(top_ix)

        # Ordenar por posición original para coherencia narrativa
        sorted_idx = sorted(selected, key=lambda i: chunks[i][0])
        contenido  = "\n\n[...]\n\n".join(texts[i] for i in sorted_idx)

        print(f"[RAG] {len(selected)} chunks únicos de {len(queries)} queries → {len(contenido)} chars")

        resultado = toc_text + "\n\n[...]\n\n" + contenido if toc_text else contenido
        r = resultado[:MAX_CHARS]
        return r, _meta(True, len(chunks), len(selected), r)

    except Exception as e:
        print(f"[RAG] Fallback sin modelo semántico: {e}")
        mid      = top_k_por_query // 2
        textos   = [c[1] for c in chunks]
        fallback = textos[:mid] + textos[-(top_k_por_query - mid):]
        contenido = "\n\n[...]\n\n".join(fallback)
        resultado = toc_text + "\n\n[...]\n\n" + contenido if toc_text else contenido
        r = resultado[:MAX_CHARS]
        return r, _meta(False, len(chunks), len(fallback), r, str(e))


def _procesar_y_cachear_pliego(cliente_id: str, texto: str) -> tuple:
    """
    Chunking + embedding del texto completo del pliego y persistencia en sesión.
    Retorna (chunks: list[str], embeddings: np.ndarray).
    Llamar una sola vez por pliego; las búsquedas posteriores reutilizan el caché.
    """
    import hashlib
    import numpy as np
    from contexto_sesion import guardar_pliego_procesado

    CHUNK_SIZE = 800
    OVERLAP    = 150
    chunks: list[str] = []
    pos = 0
    while pos < len(texto):
        chunk = texto[pos: pos + CHUNK_SIZE].strip()
        if len(chunk) > 60:
            chunks.append(chunk)
        pos += CHUNK_SIZE - OVERLAP

    if not chunks:
        return [], np.array([])

    print(f"[RAG-CACHE] Procesando {len(chunks)} chunks — cliente {cliente_id}")
    modelo     = _obtener_modelo_embeddings()
    embeddings = modelo.encode(chunks, show_progress_bar=False)

    hash_cont = hashlib.md5(texto.encode("utf-8")).hexdigest()
    guardar_pliego_procesado(cliente_id, chunks, embeddings.tolist(), hash_cont)
    print(f"[RAG-CACHE] {len(chunks)} chunks cacheados — hash {hash_cont[:8]}")
    return chunks, embeddings


def buscar_chunks_pliego_cacheados(cliente_id: str, query: str, top_k: int = 5) -> list:
    """
    Busca los top_k chunks más relevantes del pliego usando embeddings cacheados.
    Si el caché no existe o el texto cambió (hash distinto), lo reprocesa.
    Solo codifica la query — no vuelve a codificar el documento.
    """
    import hashlib
    import numpy as np
    from contexto_sesion import obtener_contexto_sesion

    ctx         = obtener_contexto_sesion(cliente_id)
    texto       = ctx.get("texto_pliego", "")
    if not texto:
        return []

    chunks      = ctx.get("chunks_pliego", [])
    emb_list    = ctx.get("embeddings_pliego", [])
    hash_guard  = ctx.get("hash_contenido", "")
    hash_actual = hashlib.md5(texto.encode("utf-8")).hexdigest()

    if chunks and emb_list and hash_guard == hash_actual:
        embeddings = np.array(emb_list)
    else:
        chunks, embeddings = _procesar_y_cachear_pliego(cliente_id, texto)
        if not chunks:
            return [texto[:2000]]

    modelo = _obtener_modelo_embeddings()
    q_emb  = modelo.encode([query], show_progress_bar=False)[0]

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    q_norm = q_emb / (np.linalg.norm(q_emb) or 1)
    sims   = (embeddings / norms) @ q_norm

    top_idx = np.argsort(sims)[::-1][:top_k].tolist()
    return [chunks[i] for i in top_idx]


def rag_pliego_con_cache(cliente_id: str, texto: str, query: str = "", top_k_por_query: int = 5) -> str:
    """
    RAG multi-query con caché de embeddings.
    Reemplaza chunking_rag_pliego() cuando se tiene cliente_id disponible.
    Primera llamada: procesa y cachea chunks+embeddings en sesión.
    Llamadas siguientes: reutiliza el caché, solo codifica las queries.
    Invalida el caché si el texto del pliego cambió (hash MD5 distinto).
    """
    import hashlib
    import numpy as np
    from contexto_sesion import obtener_contexto_sesion

    MAX_CHARS = 5000

    ctx          = obtener_contexto_sesion(cliente_id)
    hash_nuevo   = hashlib.md5(texto.encode("utf-8")).hexdigest()
    hash_guard   = ctx.get("hash_contenido", "")
    chunks_cache = ctx.get("chunks_pliego", [])
    emb_cache    = ctx.get("embeddings_pliego", [])

    if chunks_cache and emb_cache and hash_guard == hash_nuevo:
        chunks     = chunks_cache
        embeddings = np.array(emb_cache)
        print(f"[RAG-CACHE] Reutilizando {len(chunks)} chunks cacheados")
    else:
        chunks, embeddings = _procesar_y_cachear_pliego(cliente_id, texto)
        if not chunks:
            return texto[:MAX_CHARS]

    queries  = ([query] if query else []) + _RAG_QUERIES
    selected: set[int] = set()
    modelo   = _obtener_modelo_embeddings()

    for q in queries:
        q_emb  = modelo.encode([q], show_progress_bar=False)[0]
        norms  = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        q_norm = q_emb / (np.linalg.norm(q_emb) or 1)
        sims   = (embeddings / norms) @ q_norm
        top_ix = np.argsort(sims)[::-1][:top_k_por_query].tolist()
        selected.update(top_ix)

    sorted_idx = sorted(selected, key=lambda i: i)
    seleccion  = "\n\n[...]\n\n".join(chunks[i] for i in sorted_idx)
    print(f"[RAG-CACHE] {len(selected)} chunks de {len(chunks)} → {len(seleccion)} chars")
    return seleccion[:MAX_CHARS]


# [D40] DOS EJES, no uno. La jerarquía UNSPSC es:
#   2 segmento · 4 FAMILIA · 6 CLASE · 8 producto
#
# Se usaban 4 dígitos para todo y mezclaba sectores; se pasó a 6 y entonces un
# proceso de la misma familia pero de otra clase se descartaba. **Las dos cosas
# estaban mal porque son DOS PREGUNTAS DISTINTAS**:
#
#   ¿pertenece a mi sector?  -> FAMILIA (4) -> decide si SE MUESTRA
#   ¿encaja con mi perfil?   -> CLASE  (6) -> decide el ORDEN
#
# Una constructora tiene que ver TODA la obra de su zona y decidir ella qué
# sirve —para eso está la evaluación— y además ver el sector completo dice
# cómo se mueve el mercado, no sólo qué encaja hoy. Lo que NO tiene que ver es
# refrigeración, y eso lo sigue cortando la familia.
DIGITOS_FAMILIA = 4
DIGITOS_CLASE = 6
DIGITOS_UNSPSC = DIGITOS_CLASE   # compatibilidad con quien lo importe


def normalizar_codigos_unspsc(valor, digitos: int = DIGITOS_CLASE) -> list[str]:
    """
    Prefijos de los códigos UNSPSC del perfil, venga como lista o como cadena
    separada por comas [D39]. `digitos` elige el nivel: 4 familia, 6 clase.

    Devuelve lista vacía si no hay nada utilizable — nunca un prefijo basura,
    que es lo que producía el `str(lista).split(",")` anterior.
    """
    if valor is None:
        return []
    if isinstance(valor, (list, tuple, set)):
        crudos = [str(v) for v in valor]
    else:
        crudos = str(valor).replace(";", ",").split(",")
    salida: list[str] = []
    for c in crudos:
        # Sólo dígitos: descarta comillas, corchetes y separadores que dejaba
        # la conversión de una lista a texto.
        solo = "".join(ch for ch in str(c) if ch.isdigit())
        if len(solo) >= digitos:
            pref = solo[:digitos]
            if pref not in salida:
                salida.append(pref)
    return salida


# [D41] Coincidencias necesarias para el puntaje máximo de keywords.
#
# Se normaliza por TOPE y no dividiendo entre el tamaño de la lista, que era
# lo que hacía antes: con `matches / len(lista)`, una lista de 24 términos que
# describe bien el sector daba 0,04 por acierto y una de 5 daba 0,20. **El
# perfil que mejor se describía salía peor puntuado.**
KEYWORDS_PARA_TOPE = 3

_RUTA_KEYWORDS = (Path(__file__).parent / "pipeline" / "data"
                  / "keywords_sector.json")
_CACHE_KEYWORDS: dict | None = None


def puntaje_keywords(matches: int) -> float:
    """3 coincidencias o más → 1,0 · 2 → 2/3 · 1 → 1/3 · 0 → 0."""
    if matches <= 0:
        return 0.0
    return min(1.0, matches / KEYWORDS_PARA_TOPE)


def keywords_de_sector(sector: str | None) -> list[str]:
    """
    Palabras clave del sector declarado en el perfil, o **lista vacía**.

    Vacía en dos casos, y los dos son correctos: el perfil no declara sector,
    o lo declara y no hay lista revisada para él. En ninguno se inventa un
    conjunto: las palabras deciden qué procesos ve un cliente y ponerlas a
    ojo es lo que produjo [D41].
    """
    global _CACHE_KEYWORDS
    if not sector:
        return []
    if _CACHE_KEYWORDS is None:
        try:
            _CACHE_KEYWORDS = json.loads(_RUTA_KEYWORDS.read_text("utf-8"))
        except Exception:
            _CACHE_KEYWORDS = {}
    clave = str(sector).strip().lower()
    # Los perfiles anteriores al desplegable traen el sector en texto libre
    # («OBRA PUBLICA»). Sin resolver el alias se quedarían sin keywords y
    # nadie lo notaría: el filtrado seguiría funcionando, peor.
    clave = (_CACHE_KEYWORDS.get("_alias") or {}).get(clave, clave)
    valor = _CACHE_KEYWORDS.get(clave)
    return [k.lower() for k in valor] if isinstance(valor, list) else []


def estado_keywords_sector(sector: str | None) -> dict:
    """
    Si el sector de un perfil tiene palabras clave, y si no, **por qué**.

    Existe porque quedarse en cero era invisible: la búsqueda seguía
    funcionando, peor, y nadie lo notaba. Es el mismo patrón que [I10] —ante
    la ausencia de un dato, declararla en vez de seguir como si nada— llevado
    al sitio donde el usuario puede corregirlo.

    `estado` es uno de tres:
      `sin_sector`   el perfil no declara sector
      `sin_lista`    lo declara y no hay lista revisada para él
      `ok`           tiene lista
    """
    crudo = (sector or "").strip()
    if not crudo:
        return {"estado": "sin_sector", "sector": "", "clave": None,
                "n_terminos": 0,
                "aviso": ("El perfil no declara sector, así que el filtrado "
                          "por palabras no se aplica.")}
    terminos = keywords_de_sector(crudo)
    if terminos:
        _cache = _CACHE_KEYWORDS or {}
        clave = (_cache.get("_alias") or {}).get(crudo.lower(), crudo.lower())
        return {"estado": "ok", "sector": crudo, "clave": clave,
                "n_terminos": len(terminos), "aviso": None}
    return {
        "estado": "sin_lista", "sector": crudo, "clave": None, "n_terminos": 0,
        "aviso": (f"El sector «{crudo}» no tiene palabras clave asociadas; "
                  "el filtrado por contenido no se aplicará."),
    }


def busqueda_hibrida_triple(query: str, perfil_cliente: dict, contratos: list) -> list:
    """
    Triple scoring para filtrar contratos relevantes para un cliente:
      score_unspsc   (0 o 1)   — match exacto código UNSPSC (4 primeros dígitos)
      score_keywords (0–1)     — keywords del perfil en título + descripción
      score_semantico (0–1)    — similitud coseno de embeddings all-MiniLM-L6-v2
    score_final = 0.25*score_unspsc + 0.35*score_keywords + 0.40*score_semantico
    Pasa si:  score_final > 0.40
           OR score_unspsc == 1.0 (match UNSPSC exacto → siempre incluir)
           OR score_keywords > 0.60 (muchas keywords coinciden)
    Si no hay modelo semántico, el fallback usa solo UNSPSC+keywords (umbral 0.25).
    """
    import numpy as np

    # [D39] El campo llega en DOS formas y las dos son legítimas: el esquema
    # canónico (`PerfilExperiencia.codigos_unspsc`) lo declara `list[str]` y el
    # formulario web manda una cadena separada por comas.
    #
    # Antes se hacía `str(...).split(",")` sin distinguir, así que una lista se
    # convertía en `"['72151500', '72141100']"` y los códigos salían como
    # `"['7"` y `" '72"`. Medido: con la lista pasaban **0 de 10** procesos,
    # porque sin coincidencia de UNSPSC el total no llega al umbral. Un perfil
    # que descarta todo en silencio es peor que no filtrar.
    #
    # [D40] Se comparan **6 dígitos, no 4**. En UNSPSC 4 dígitos son la
    # FAMILIA y 6 la CLASE: `7215` cubre a la vez `72151500` (albañilería) y
    # `72154000` (climatización), así que una constructora traía procesos de
    # refrigeración con puntaje 1,00.
    _codigos = perfil_cliente.get("codigos_unspsc")
    clases_cliente = normalizar_codigos_unspsc(_codigos, DIGITOS_CLASE)
    familias_cliente = normalizar_codigos_unspsc(_codigos, DIGITOS_FAMILIA)

    # [D41] Las keywords salen del SECTOR que declara el perfil, no de una
    # constante. Antes se inyectaban las 54 de `KEYWORDS_HVAC` a todos los
    # clientes, fueran de climatización o no: herencia de cuando el producto
    # era para un solo cliente.
    #
    # Sin sector declarado NO se pone ninguna. Un conjunto por defecto
    # repetiría exactamente el error que esto corrige.
    keywords_perfil = list(_extraer_keywords(str(perfil_cliente.get("objeto_similar", ""))))
    kw_sector = keywords_de_sector(perfil_cliente.get("sector"))
    todas_keywords = keywords_perfil + [k for k in kw_sector if k not in keywords_perfil]

    modelo = None
    emb_query = None
    try:
        modelo = _obtener_modelo_embeddings()
        emb_query = modelo.encode([query], convert_to_numpy=True, show_progress_bar=False)[0]
    except Exception:
        pass  # fallback: solo UNSPSC + keywords

    resultados = []
    for contrato in contratos:
        if not isinstance(contrato, dict):
            continue
        titulo = str(contrato.get("nombre_del_procedimiento", ""))
        # SECOP II puede usar descripci_n_del_procedimiento o descripcion_del_procedimiento
        objeto = str(
            contrato.get("descripci_n_del_procedimiento", "")
            or contrato.get("descripcion_del_procedimiento", "")
        )
        texto_contrato = (titulo + " " + objeto).lower()

        # Nivel 1: UNSPSC — comparar primeros 4 dígitos contra campo SECOP II
        unspsc_c = str(
            contrato.get("codigo_principal_de_categoria", "")
            or contrato.get("unspsc_bienes_y_servicios", "")
            or contrato.get("unspsc", "")
        ).lower().replace("-", "").replace(" ", "")
        # Clase (6): encaje fino, sube el orden. Familia (4): mismo sector.
        score_clase = 1.0 if any(c in unspsc_c for c in clases_cliente if c) else 0.0
        score_familia = 1.0 if any(f in unspsc_c for f in familias_cliente if f) else 0.0
        # Nombre heredado, que el resto del sistema ya muestra.
        score_unspsc = score_clase

        # Nivel 2: Keywords — [D41] normalizado por TOPE, no por tamaño de lista.
        matches = sum(1 for kw in todas_keywords if kw in texto_contrato)
        score_keywords = puntaje_keywords(matches)

        # Nivel 3: Semántico — similitud coseno normalizada a [0,1]
        score_semantico = 0.0
        if modelo is not None and emb_query is not None:
            try:
                texto_emb = (titulo + " " + objeto)[:500]
                emb_c = modelo.encode([texto_emb], convert_to_numpy=True, show_progress_bar=False)[0]
                nq = np.linalg.norm(emb_query)
                nc = np.linalg.norm(emb_c)
                if nq > 0 and nc > 0:
                    cos = float(np.dot(emb_query, emb_c) / (nq * nc))
                    score_semantico = (cos + 1) / 2  # [-1,1] → [0,1]
            except Exception:
                pass

        # [D40] La FAMILIA decide si se muestra; la CLASE, el orden.
        #
        # Coincidir de familia NO se descarta nunca por relevancia: es del
        # sector del cliente y él decide si le sirve. Coincidir de clase suma
        # mucho más, así que lo específico aparece primero.
        #
        # Sin coincidencia de familia hay que ganárselo con keywords y
        # semántica, y ahí sí se descarta: es el cruce entre sectores, que es
        # justo lo que no debe pasar.
        # [D40] La familia ABRE la puerta; el contenido la confirma.
        #
        # Coincidir de familia no basta por sí solo, y el motivo es concreto:
        # la familia `7215` incluye a la vez `721515` (albañilería) y `721540`
        # (climatización), así que abrir sólo por familia devolvía
        # refrigeración a una constructora. Medido.
        #
        # Y NO se puede arbitrar con la semántica: el modelo es débil en
        # español técnico. Medido sobre estos mismos procesos, contra la
        # consulta de la constructora, «papelería» da coseno 0,32 y «obra
        # civil para adecuación de aulas» da 0,25. La semántica ordena, no
        # decide.
        #
        # Lo que sí separa son las KEYWORDS DEL SECTOR [D41]: «obra civil para
        # adecuación de aulas y baterías sanitarias» encuentra cuatro términos
        # de obra; «mantenimiento preventivo de sistemas de refrigeración»
        # encuentra uno, y «climatización HVAC para centro de datos», ninguno.
        #
        # De ahí la regla: misma familia Y alguna palabra del sector.
        # DOS palabras del sector, no una. Medido: «Mantenimiento preventivo de
        # sistemas de refrigeración y cuartos fríos» encuentra UNA palabra de
        # obra —«mantenimiento», que está en la lista con razón: «mantenimiento
        # de vías» es obra— y con una sola bastaba para colarse. «Obra civil
        # para adecuación de aulas y baterías sanitarias» encuentra CUATRO.
        #
        # El coste es real y conviene saberlo: un proceso del sector con
        # título muy corto puede quedarse en una sola palabra y caer fuera.
        # Se prefiere ese fallo al contrario —enseñar refrigeración a una
        # constructora— porque el primero se ve al revisar los descartados,
        # que salen con su razón, y el segundo ensucia la lista buena.
        mismo_sector = (score_familia == 1.0
                        and score_keywords >= 2 / KEYWORDS_PARA_TOPE)

        if modelo is not None:
            score_final = (0.40 * score_clase + 0.10 * score_familia
                           + 0.15 * score_keywords + 0.35 * score_semantico)
            pasa = (score_clase == 1.0 or mismo_sector
                    or score_final > 0.50 or score_keywords >= 1.0)
        else:
            # Sin modelo semántico no hay tercera señal: los códigos deciden.
            score_final = (0.50 * score_clase + 0.20 * score_familia
                           + 0.30 * score_keywords)
            pasa = (score_clase == 1.0 or mismo_sector
                    or score_final > 0.50 or score_keywords >= 1.0)

        # Marca visible del porqué, para que el orden se pueda explicar.
        if score_clase == 1.0:
            nivel, etiqueta_nivel = "clase", ""
        elif mismo_sector:
            nivel, etiqueta_nivel = "familia", "mismo sector, otra especialidad"
        else:
            nivel, etiqueta_nivel = "afinidad", "afinidad por contenido"

        print(
            f"[HÍBRIDO] {titulo[:50]:<50} | "
            f"CLASE={score_clase:.2f} FAM={score_familia:.2f} KW={score_keywords:.2f} "
            f"Sem={score_semantico:.2f} Total={score_final:.2f} | "
            f"{'✓ PASA' if pasa else '✗ descarta'}"
        )

        if pasa:
            resultados.append({
                **contrato,
                "score_hibrido": round(score_final, 4),
                "score_unspsc": score_unspsc,
                "score_clase": score_clase,
                "score_familia": score_familia,
                "nivel_coincidencia": nivel,
                "etiqueta_coincidencia": etiqueta_nivel,
                "score_keywords": round(score_keywords, 4),
                "score_semantico": round(score_semantico, 4),
            })

    # Orden VISIBLE: clase exacta arriba, familia después, afinidad al final;
    # dentro de cada grupo, por puntaje. Sin esto, un proceso de la misma
    # especialidad podía quedar por debajo de uno de otra sólo por semántica.
    _RANGO = {"clase": 0, "familia": 1, "afinidad": 2}
    resultados.sort(key=lambda x: (_RANGO.get(x.get("nivel_coincidencia", "afinidad"), 3),
                                   -x["score_hibrido"]))
    print(f"[HÍBRIDO] {len(resultados)}/{len(contratos)} contratos pasaron el filtro")
    return resultados


def guardar_analisis_historial(cliente_id: str, resultado_analisis: dict, proceso_id: str):
    """Agrega entrada al historial de licitaciones analizadas del cliente."""
    from pathlib import Path
    from datetime import datetime as _dt

    ruta = Path(f"./clientes/{cliente_id}/historial/licitaciones.json")
    ruta.parent.mkdir(parents=True, exist_ok=True)

    historial = []
    if ruta.exists():
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                historial = json.load(f)
        except Exception:
            historial = []

    historial = [h for h in historial if h.get("proceso_id") != proceso_id]
    historial.append({
        "proceso_id": proceso_id,
        "fecha_analisis": _dt.now().isoformat(),
        "score_financiero": resultado_analisis.get("score", resultado_analisis.get("score_financiero", 0)),
        "score_juridico": resultado_analisis.get("score_juridico", 0),
        "concepto_final": resultado_analisis.get("accion", resultado_analisis.get("concepto", "")),
        "decision_usuario": None,
        "resultado_final": None,
        "lecciones": [],
    })

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)


def actualizar_resultado(cliente_id: str, proceso_id: str, resultado: str, lecciones: list) -> bool:
    """Registra si el cliente ganó o perdió una licitación y las lecciones aprendidas."""
    from pathlib import Path

    ruta = Path(f"./clientes/{cliente_id}/historial/licitaciones.json")
    if not ruta.exists():
        return False
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            historial = json.load(f)
        for h in historial:
            if h.get("proceso_id") == proceso_id:
                h["resultado_final"] = resultado
                h["decision_usuario"] = resultado
                h["lecciones"] = lecciones
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(historial, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def analizar_patrones(cliente_id: str) -> dict:
    """Resumen estadístico de éxito por sector/modalidad para enriquecer prompts."""
    from pathlib import Path

    ruta = Path(f"./clientes/{cliente_id}/historial/licitaciones.json")
    if not ruta.exists():
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            historial = json.load(f)
    except Exception:
        return {}

    ganados = [h for h in historial if h.get("resultado_final") == "GANADO"]
    perdidos = [h for h in historial if h.get("resultado_final") == "PERDIDO"]
    tasa = len(ganados) / len(historial) if historial else 0
    scores_g = [h.get("score_financiero", 0) for h in ganados]
    score_prom = sum(scores_g) / len(scores_g) if scores_g else 0

    return {
        "total_analizados": len(historial),
        "ganados": len(ganados),
        "perdidos": len(perdidos),
        "tasa_exito": round(tasa, 2),
        "score_promedio_exito": round(score_prom, 1),
        "lecciones": [l for h in ganados for l in h.get("lecciones", [])],
    }


def agente_financiero(licitacion, cliente, texto_pliego=None, cliente_id=None, sin_rag=False):
    """
    AGENTE 1: Auditor Financiero con memoria documental e historial.
    cliente_id: si se proporciona, enriquece el análisis con documentos del cliente
    y el historial de licitaciones previas.
    """
    import anthropic
    import time as _time

    try:
        from prompts import SKILL_FINANCIERO as _SKILL_FIN
    except ImportError:
        _SKILL_FIN = ""

    api_client = anthropic.Anthropic(api_key=API_KEY, timeout=120.0, max_retries=2)

    # Contexto documental del cliente
    bloque_docs = ""
    if cliente_id:
        try:
            from gestor_documentos import buscar_en_documentos_cliente
            from pathlib import Path as _Path
            query_fin = f"estados financieros liquidez endeudamiento capital {licitacion.get('nombre_del_procedimiento','')}"
            chunks = buscar_en_documentos_cliente(query_fin, cliente_id, top_k=4)
            if chunks:
                bloque_docs = "\nDOCUMENTOS FINANCIEROS DEL CLIENTE (fragmentos relevantes):\n"
                for ch in chunks:
                    bloque_docs += f"[{ch.get('doc_type','')} — {ch.get('filename','')}]: {ch.get('texto','')[:300]}\n"
        except Exception:
            pass

    # Contexto de historial
    bloque_historial = ""
    if cliente_id:
        try:
            from pathlib import Path as _Path
            import json as _json
            ruta_h = _Path(f"./clientes/{cliente_id}/historial/licitaciones.json")
            if ruta_h.exists():
                with open(ruta_h, "r", encoding="utf-8") as f:
                    hist = _json.load(f)
                ultimas = hist[-5:]
                if ultimas:
                    bloque_historial = "\nHISTORIAL RECIENTE (últimas 5 licitaciones):\n"
                    for h in ultimas:
                        bloque_historial += (
                            f"- [{h.get('fecha_analisis','')[:10]}] "
                            f"Score: {h.get('score_financiero','N/A')} | "
                            f"Concepto: {h.get('concepto_final','N/A')} | "
                            f"Resultado: {h.get('resultado_final','Pendiente')}\n"
                        )
        except Exception:
            pass

    if texto_pliego:
        _ctx_fin = texto_pliego if sin_rag else texto_pliego[:70_000]
        bloque_pliego = (
            f"\nPLIEGO ESPECÍFICO (prioridad sobre cualquier criterio genérico):\n{_ctx_fin}\n"
        )
    else:
        bloque_pliego = "\nPLIEGO ESPECÍFICO: No suministrado. Todos los campos valor_pliego del checklist_detallado deben decir NO_ENCONTRADO_EN_PLIEGO.\n"

    prompt = f"""
{_SKILL_FIN}

Actúa como un Auditor Financiero experto en contratación estatal colombiana.
REGLA DE EXTRACCIÓN: Los valores exigidos en cada indicador financiero (liquidez, endeudamiento,
etc.) deben venir EXCLUSIVAMENTE del pliego suministrado. Si el pliego no menciona un umbral,
el campo "valor_pliego" debe decir NO_ENCONTRADO_EN_PLIEGO. Prohibido usar umbrales genéricos
(ej: "≥ 1.0", "≤ 0.80") que no aparezcan textualmente en el pliego.

Evalúa la viabilidad financiera del cliente para esta licitación.

LICITACIÓN:
- Objeto: {licitacion.get('nombre_del_procedimiento')}
- Presupuesto Base: COP {licitacion.get('precio_base')}

INDICADORES DEL CLIENTE:
- RUP: {cliente['rup'].get('estado_rup')}
- Liquidez: {cliente['financiero'].get('indice_liquidez')}
- Endeudamiento: {cliente['financiero'].get('indice_endeudamiento')}
- Capacidad Máx. Oferta: COP {cliente['financiero'].get('presupuesto_maximo_contrato')}
{bloque_docs}{bloque_historial}{bloque_pliego}

Regla de concepto: score < 40 → NO VIABLE | 40–70 → CONDICIONAL | > 70 → VIABLE
LÍMITE: Máximo 100 chars por razón/recomendación. Máximo 3 razones y 3 recomendaciones.
El array "checklist_detallado" va PRIMERO en el JSON.

REGLA DE ORO: Responde ÚNICAMENTE con JSON válido. Estructura exacta:
{{
    "checklist_detallado": [
        {{
            "requisito": "Índice de Liquidez",
            "valor_pliego": "valor del pliego o NO_ENCONTRADO_EN_PLIEGO",
            "exigido_literal": "igual a valor_pliego",
            "valor_normativo_referencia": "IDL ≥ 1.0 según Res.196/2016 CCE (referencia orientativa)",
            "fuente": "pliego | no_encontrado",
            "valor_empresa": "del cliente",
            "cumple": true/false/null
        }},
        {{
            "requisito": "Índice de Endeudamiento",
            "valor_pliego": "valor del pliego o NO_ENCONTRADO_EN_PLIEGO",
            "exigido_literal": "igual a valor_pliego",
            "valor_normativo_referencia": "NDE ≤ 0.80 según Res.196/2016 CCE (referencia orientativa)",
            "fuente": "pliego | no_encontrado",
            "valor_empresa": "del cliente",
            "cumple": true/false/null
        }},
        {{
            "requisito": "Capacidad de Contratación (RUP)",
            "valor_pliego": "valor contrato o NO_ENCONTRADO_EN_PLIEGO",
            "exigido_literal": "igual a valor_pliego",
            "valor_normativo_referencia": null,
            "fuente": "pliego | no_encontrado",
            "valor_empresa": "cap. máx. cliente",
            "cumple": true/false/null
        }}
    ],
    "score_financiero": numero_0_a_100,
    "concepto": "VIABLE" o "NO VIABLE" o "CONDICIONAL",
    "razones": ["máx 100 chars por razón"],
    "articulos_aplicables": ["Decreto 1082/2015 art. X"],
    "recomendaciones": ["máx 100 chars por recomendación"],
    "indices_evaluados": {{"liquidez": valor_numerico, "endeudamiento": valor_numerico, "capital_trabajo": "calculado o N/A"}},
    "cumple_financiero": true o false,
    "analisis_numerico": "max 120 chars"
}}
"""

    t0 = _time.time()
    respuesta = api_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6144,
        extra_body={"temperature": 0.0},
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = _time.time() - t0
    if elapsed > 10:
        try:
            from logger import setup_logger
            setup_logger().warning(f"agente_financiero tardó {elapsed:.1f}s — módulo_origen=analizador")
        except Exception:
            pass

    if respuesta.stop_reason == "max_tokens":
        print(f"[FIN-DIAG] FINANCIERO TRUNCADO (stop=max_tokens) — JSON puede ser incompleto")

    resultado = _extraer_json(respuesta.content[0].text)
    resultado["_uso"] = {
        "input_tokens":  respuesta.usage.input_tokens,
        "output_tokens": respuesta.usage.output_tokens,
    }

    # Garantizar retrocompatibilidad: derivar campos si faltan
    if "cumple_financiero" not in resultado:
        resultado["cumple_financiero"] = resultado.get("concepto") == "VIABLE"
    if "analisis_numerico" not in resultado:
        resultado["analisis_numerico"] = resultado.get("razones", [""])[0]
    if "checklist_detallado" not in resultado:
        idx = resultado.get("indices_evaluados", {})
        resultado["checklist_detallado"] = [
            {"requisito": "Índice de Liquidez", "valor_pliego": "NO_ENCONTRADO_EN_PLIEGO", "valor_empresa": str(idx.get("liquidez", "N/A")), "cumple": None},
            {"requisito": "Índice de Endeudamiento", "valor_pliego": "NO_ENCONTRADO_EN_PLIEGO", "valor_empresa": str(idx.get("endeudamiento", "N/A")), "cumple": None},
        ]

    return resultado


def _agente_legal_paso_a(api_client, licitacion, texto_pliego, call_id, max_chars=70_000):
    """Paso A — Extracción pura: solo el pliego, sin normativa ni skills.

    max_chars: límite de caracteres del pliego enviados al modelo.
    None = sin límite (para experimentos sin RAG). Default=70_000 (comportamiento de producción).
    """
    import time as _time

    bloque_pliego = (texto_pliego or "")[:max_chars] if max_chars is not None else (texto_pliego or "")

    prompt_a = f"""Actúa como un extractor de datos de documentos contractuales.
Tu única tarea es leer el pliego adjunto y extraer los REQUISITOS HABILITANTES — las condiciones que un proponente debe cumplir para que su oferta sea evaluada.

REGLAS ABSOLUTAS — sin excepción:
1. El pliego es tu ÚNICA fuente. No tienes acceso a ninguna normativa externa.
2. Si un valor, umbral, porcentaje o plazo NO aparece textualmente en el fragmento recibido, escribe exactamente: NO_ENCONTRADO_EN_PLIEGO
3. PROHIBIDO completar campos con: valores que suelen exigirse en procesos similares, conocimiento general, ni lo que dicen el Decreto 1082, la Resolución 196/2016 [no-citable], la Resolución CCE, ni ninguna otra norma. Un campo NO_ENCONTRADO_EN_PLIEGO es correcto. Un campo inventado es un error grave.
4. En "ubicacion_pliego": anota la sección o numeral exacto (ej: "Numeral 3.9", "Sección 2.6.3"). Si no puedes ubicarlo, escribe "texto del pliego" o null.
5. No cites artículos de ley ni resoluciones. Solo cita el pliego.
6. EXCLUIR únicamente: (a) causales de rechazo de la oferta económica, (b) plazos del cronograma del proceso (fechas de apertura, cierre, adjudicación), (c) instrucciones de formato de la oferta (foliado, sellos, carátulas, formularios de presentación, AIU). NO excluyas documentos que el proponente debe acreditar aunque no tengan umbral numérico — esos sí son habilitantes.
7. Sé conciso: máximo 200 caracteres por campo. Si el valor es largo, resume la esencia sin perder el número o umbral.
8. Extrae TODOS los requisitos habilitantes que encuentres, sin límite de cantidad. No omitas ninguno por considerarlo menos importante. Un requisito habilitante omitido puede descalificar al proponente, sin importar cuán menor parezca. Si un requisito no tiene umbral numérico (por ejemplo, presentar una declaración, un certificado o un paz y salvo), es igualmente habilitante y debe reportarse.

PROCESO: {licitacion.get('nombre_del_procedimiento')}
VALOR: COP {licitacion.get('precio_base')}

TEXTO DEL PLIEGO:
{bloque_pliego}

Categorías de requisitos habilitantes a extraer (ejemplos no exhaustivos — extrae cualquier requisito que encuentres, aunque no encaje en ninguna categoría):
- EXPERIENCIA (ejemplos): valor acumulado contratos similares, valor contrato individual mayor, objeto similar (descripción, CIIU, UNSPSC), participación mínima en consorcio, plazo de la experiencia, número máximo de contratos para acreditar
- FINANCIEROS (ejemplos): índice de liquidez (IDL), índice de endeudamiento (NDE), razón de cobertura de intereses (RCI), capital de trabajo, patrimonio neto líquido, renta o ingresos operacionales, capacidad residual
- JURÍDICOS / CAPACIDAD LEGAL (ejemplos): RUP en firme, cámara de comercio, pólizas habilitantes, garantía de seriedad, inhabilidades e incompatibilidades, paz y salvos (municipal, parafiscales, seguridad social), boletín de responsables fiscales, antecedentes disciplinarios, declaraciones juramentadas, certificaciones de aportes parafiscales, certificado de industria nacional
- TÉCNICOS Y OPERATIVOS (ejemplos): personal mínimo requerido, equipos mínimos, certificaciones técnicas
- OTROS: cualquier condición que el pliego exija cumplir para que la oferta sea evaluada, aunque no encaje en las categorías anteriores

REGLA DE ORO: Responde ÚNICAMENTE con JSON válido, sin texto antes ni después.
{{
    "requisitos_habilitantes": [
        {{
            "requisito": "nombre corto del requisito",
            "exigido_literal": "cita textual del pliego (máx 200 chars) — o NO_ENCONTRADO_EN_PLIEGO",
            "ubicacion_pliego": "Numeral X.X / null",
            "documento_soporte": "documento que pide el pliego (máx 80 chars) — o NO_ENCONTRADO_EN_PLIEGO"
        }}
    ],
    "observaciones_extraccion": "Notas breves: secciones que parecen faltar, si el fragmento está incompleto, etc. (máx 200 chars)"
}}"""

    t0 = _time.time()
    respuesta = api_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        extra_body={"temperature": 0.0},
        messages=[{"role": "user", "content": prompt_a}],
    )
    elapsed = _time.time() - t0
    stop_reason = respuesta.stop_reason
    print(
        f"[LEGAL-DIAG #{call_id}] PASO-A | {elapsed:.1f}s | stop={stop_reason} | "
        f"tokens={respuesta.usage.input_tokens}in/{respuesta.usage.output_tokens}out"
    )
    if stop_reason == "max_tokens":
        print(f"[LEGAL-DIAG #{call_id}] PASO-A TRUNCADO — JSON puede estar incompleto")
    resultado = _extraer_json(respuesta.content[0].text)
    resultado["_uso"] = {
        "input_tokens":  respuesta.usage.input_tokens,
        "output_tokens": respuesta.usage.output_tokens,
    }
    return resultado


def _agente_legal_paso_b(api_client, licitacion, contexto_biblioteca, resultado_a,
                          experiencia_cliente, bloque_docs_cliente, call_id):
    """Paso B — Contraste: requisitos extraídos en Paso A + normativa CCE + datos del cliente."""
    import json as _json
    import time as _time

    try:
        from prompts import SKILL_JURIDICO as _SKILL_JUR, SKILL_ESTRATEGIA as _SKILL_EST
    except ImportError:
        _SKILL_JUR = ""
        _SKILL_EST = ""

    # Truncar campos de texto largo antes de serializar: reduce input tokens de Paso B
    # y previene que el modelo los expanda aún más en el output.
    reqs_a_compactos = []
    for req in resultado_a.get("requisitos_habilitantes", []):
        reqs_a_compactos.append({
            "requisito":         req.get("requisito", "")[:80],
            "exigido_literal":   (req.get("exigido_literal") or "")[:120],
            "ubicacion_pliego":  req.get("ubicacion_pliego"),
            "documento_soporte": (req.get("documento_soporte") or "")[:60],
        })
    requisitos_a = _json.dumps(reqs_a_compactos, ensure_ascii=False, indent=2)
    obs = resultado_a.get("observaciones_extraccion", "")

    exp_acumulado     = experiencia_cliente.get('valor_acumulado', '—')
    exp_individual    = experiencia_cliente.get('valor_individual_max', '—')
    exp_objeto        = experiencia_cliente.get('objeto_similar', '—')
    exp_unspsc        = experiencia_cliente.get('codigos_unspsc', '—')
    exp_participacion = experiencia_cliente.get('participacion_minima', '—')

    bloque_experiencia = f"""
EXPERIENCIA REGISTRADA DEL OFERENTE:
- Valor acumulado contratos similares (3 años): COP {experiencia_cliente.get('valor_acumulado', 'No registrado')}
- Valor contrato individual más alto: COP {experiencia_cliente.get('valor_individual_max', 'No registrado')}
- Objetos de contratos similares: {experiencia_cliente.get('objeto_similar', 'No registrado')}
- Códigos UNSPSC: {experiencia_cliente.get('codigos_unspsc', 'No registrado')}
- Participación mínima en consorcios previos: {experiencia_cliente.get('participacion_minima', 'No registrado')}%
"""

    prompt_b = f"""
{_SKILL_JUR}
{_SKILL_EST}

Actúa como Abogado Consultor experto en contratación pública colombiana.
LÍMITE DE RESPUESTA: Incluye TODOS los requisitos recibidos de Paso A sin omitir ninguno. Sé estrictamente conciso en campos de texto libre (máx 150 chars por campo). Máximo 4 documentos en documentos_a_gestionar. Máximo 3 ítems en riesgos.
Cita el artículo y norma específica (Ley 80/1993, Ley 1150/2007, Decreto 1082/2015, Resolución CCE)
que respalda cada evaluación. Indica si el documento faltante es SUBSANABLE o NO SUBSANABLE
con base en Ley 1150/2007 art. 5.

OBJETO PROCESO: {licitacion.get('nombre_del_procedimiento')}
VALOR: COP {licitacion.get('precio_base')}

REQUISITOS EXTRAÍDOS DEL PLIEGO (fuente primaria — Paso A):
{requisitos_a}
{f"NOTA DEL EXTRACTOR: {obs}" if obs else ""}

BIBLIOTECA NORMATIVA CCE (solo para contraste y detección de riesgos — NO para completar campos vacíos):
{contexto_biblioteca[:10000]}
{bloque_experiencia}
{bloque_docs_cliente}

Instrucciones de evaluación:
- Para cada requisito recibido de Paso A: copia "exigido_literal" y "ubicacion_pliego" tal como llegaron.
- "exigido" = mismo valor que "exigido_literal" (campo de compatibilidad).
- "valor_normativo_referencia": lo que dice la biblioteca CCE sobre ese tipo de requisito (referencia orientativa, NUNCA como exigencia del proceso). null si la norma no aplica o no hay referencia relevante.
- "fuente": "pliego" si exigido_literal tiene un valor real (no NO_ENCONTRADO_EN_PLIEGO); "no_encontrado" si exigido_literal = NO_ENCONTRADO_EN_PLIEGO y no hay norma de referencia; "normativa" solo si exigido_literal = NO_ENCONTRADO_EN_PLIEGO pero hay un valor_normativo_referencia.
- Para requisitos con exigido_literal="NO_ENCONTRADO_EN_PLIEGO": en "cliente_tiene" escribe "El pliego no especifica — no se puede evaluar". En "cumple" usa null.
- Los requisitos que la norma exige pero el pliego no menciona explícitamente van en "riesgos", no en "requisitos_habilitantes".

REGLA DE ORO: Responde ÚNICAMENTE con JSON válido. MÁXIMO 150 chars por campo de texto libre.
El array "requisitos_habilitantes" va PRIMERO para garantizar que no quede truncado.
{{
    "requisitos_habilitantes": [
        {{
            "requisito": "nombre corto",
            "exigido": "igual a exigido_literal",
            "exigido_literal": "cita textual del pliego o NO_ENCONTRADO_EN_PLIEGO (de Paso A)",
            "ubicacion_pliego": "sección o null (de Paso A)",
            "valor_normativo_referencia": "referencia CCE o null (máx 80 chars)",
            "fuente": "pliego | normativa | no_encontrado",
            "cliente_tiene": "dato corto o El pliego no especifica (máx 60 chars)",
            "cumple": true/false/null,
            "documento_soporte": "doc o null",
            "norma": "Ley/Decreto art. X (máx 60 chars)"
        }}
    ],
    "matriz_experiencia": [
        {{"requisito": "Valor acumulado de contratos", "valor_pliego": "exigido o NO_ENCONTRADO_EN_PLIEGO", "valor_empresa": "COP {exp_acumulado}", "cumple": true/false/null}},
        {{"requisito": "Valor contrato individual más alto", "valor_pliego": "exigido o NO_ENCONTRADO_EN_PLIEGO", "valor_empresa": "COP {exp_individual}", "cumple": true/false/null}},
        {{"requisito": "Objeto similar", "valor_pliego": "clasificación exigida o NO_ENCONTRADO_EN_PLIEGO", "valor_empresa": "{exp_objeto}", "cumple": true/false/null}},
        {{"requisito": "Códigos UNSPSC", "valor_pliego": "códigos exigidos o NO_ENCONTRADO_EN_PLIEGO", "valor_empresa": "{exp_unspsc}", "cumple": true/false/null}},
        {{"requisito": "Participación mínima", "valor_pliego": "porcentaje exigido o NO_ENCONTRADO_EN_PLIEGO", "valor_empresa": "{exp_participacion}%", "cumple": true/false/null}}
    ],
    "viable_juridico": true o false,
    "score_juridico": numero_0_a_100,
    "concepto": "VIABLE" o "NO VIABLE" o "CONDICIONAL",
    "riesgos_legales": "max 150 chars — cita norma y numeral del pliego",
    "argumentos_viabilidad": "max 150 chars",
    "documentos_a_gestionar": ["Doc 1", "Doc 2", "Doc 3", "Doc 4"],
    "documentos_faltantes": ["doc que el cliente no tiene"],
    "riesgos": ["max 80 chars por riesgo"]
}}"""

    t0 = _time.time()
    respuesta = api_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        extra_body={"temperature": 0.0},
        messages=[{"role": "user", "content": prompt_b}],
    )
    elapsed = _time.time() - t0
    stop_reason = respuesta.stop_reason
    uso = respuesta.usage
    print(
        f"[LEGAL-DIAG #{call_id}] PASO-B | {elapsed:.1f}s | stop={stop_reason} | "
        f"tokens={uso.input_tokens}in/{uso.output_tokens}out"
    )
    if stop_reason == "max_tokens":
        print(f"[LEGAL-DIAG #{call_id}] PASO-B TRUNCADO — JSON probablemente incompleto")
    resultado = _extraer_json(respuesta.content[0].text)
    resultado["_uso"] = {
        "input_tokens":  uso.input_tokens,
        "output_tokens": uso.output_tokens,
    }
    return resultado


def _con_reintento(fn, call_id: str, paso: str, max_intentos: int = 3):
    """
    Ejecuta fn() con hasta max_intentos intentos ante errores de red o tasa.
    Backoff fijo: 5 s → 15 s → 45 s.
    Re-lanza en el último intento o ante errores no retriables.
    """
    import time as _t
    import anthropic as _anth

    _RETRIABLES = (_anth.APIConnectionError, _anth.RateLimitError, _anth.InternalServerError)
    esperas = [5, 15, 45]

    for intento in range(1, max_intentos + 1):
        try:
            return fn()
        except _RETRIABLES as exc:
            if intento == max_intentos:
                raise
            espera = esperas[intento - 1]
            print(
                f"[LEGAL-DIAG #{call_id}] {paso} intento {intento}/{max_intentos} "
                f"falló ({type(exc).__name__}) — reintentando en {espera}s"
            )
            _t.sleep(espera)


def agente_legal_rag(licitacion, contexto_biblioteca, experiencia_cliente=None, texto_pliego=None, cliente_id=None, sin_rag=False):
    """
    AGENTE 2: Abogado Consultor RAG — pipeline de dos pasos.
    Paso A: extracción pura del pliego (sin normativa).
    Paso B: contraste con biblioteca CCE y evaluación del cliente.

    Parámetros:
      sin_rag: si True, envía texto_pliego completo a Paso A sin truncar los 70 000 chars.
               Solo para experimentos — el comportamiento de producción usa sin_rag=False.

    Garantías de integridad (Task 8):
    - Si Paso A falla tras 3 reintentos, Paso B NO corre.
    - Errores de red/tasa se reintenten automáticamente (backoff 5/15/45 s).
    - _estado_analisis y _tokens_uso siempre presentes en el retorno.
    """
    import anthropic
    import time as _time
    import uuid as _uuid

    call_id = _uuid.uuid4().hex[:8]
    t_inicio = _time.time()
    # max_retries=0 — el reintento lo manejamos nosotros en _con_reintento
    api_client = anthropic.Anthropic(api_key=API_KEY, timeout=240.0, max_retries=0)
    experiencia_cliente = experiencia_cliente or {}

    # Contexto documental del cliente para cruce legal
    bloque_docs_cliente = ""
    if cliente_id:
        try:
            from gestor_documentos import buscar_en_documentos_cliente
            query_jur = f"experiencia contratos habilitante requisitos {licitacion.get('nombre_del_procedimiento','')}"
            chunks = buscar_en_documentos_cliente(query_jur, cliente_id, top_k=5)
            if chunks:
                bloque_docs_cliente = "\nDOCUMENTOS DEL CLIENTE (fragmentos para cruce con requisitos habilitantes):\n"
                for ch in chunks:
                    bloque_docs_cliente += f"[{ch.get('doc_type','')} — {ch.get('filename','')}]: {ch.get('texto','')[:300]}\n"
        except Exception:
            pass

    print(
        f"[LEGAL-DIAG #{call_id}] INICIO | "
        f"pliego={len(texto_pliego or '')} chars | "
        f"biblioteca={len(contexto_biblioteca)} chars"
    )

    errores_capturados = []
    paso_a_ok = False
    paso_b_ok = False
    _max_chars_a = None if sin_rag else 70_000  # sin_rag=True → texto completo a Paso A

    # ── Paso A: extracción pura (con reintento) ───────────────────────────────
    try:
        resultado_a = _con_reintento(
            lambda: _agente_legal_paso_a(api_client, licitacion, texto_pliego, call_id, max_chars=_max_chars_a),
            call_id, "PASO-A",
        )
        paso_a_ok = True
    except Exception as exc:
        msg = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(f"[LEGAL-DIAG #{call_id}] PASO-A ABORTADO tras reintentos: {msg}")
        errores_capturados.append({"paso": "A", "error": msg})

    # Extraer token counts de Paso A antes de pasarlo a Paso B
    uso_a = resultado_a.pop("_uso", {}) if paso_a_ok else {}

    # ── Abortar si Paso A falló: no correr Paso B con datos vacíos ────────────
    if not paso_a_ok:
        t_total = round(_time.time() - t_inicio, 1)
        print(f"[LEGAL-DIAG #{call_id}] ABORTADO | {t_total}s — Paso B NO ejecutado")
        return {
            "viable_juridico": False,
            "score_juridico":  0,
            "concepto":        "ERROR",
            "riesgos_legales": "Análisis no completado — ver _estado_analisis",
            "argumentos_viabilidad": "",
            "documentos_a_gestionar": [],
            "documentos_faltantes":   [],
            "riesgos":                [],
            "requisitos_habilitantes": [],
            "matriz_experiencia":      [],
            "_estado_analisis": {
                "estado":          "fallido",
                "paso_a_exitoso":  False,
                "paso_b_exitoso":  False,
                "errores":         errores_capturados,
            },
        }

    # ── Paso B: contraste con normativa (con reintento) ───────────────────────
    try:
        resultado = _con_reintento(
            lambda: _agente_legal_paso_b(
                api_client, licitacion, contexto_biblioteca,
                resultado_a, experiencia_cliente, bloque_docs_cliente, call_id,
            ),
            call_id, "PASO-B",
        )
        paso_b_ok = True
        uso_b = resultado.pop("_uso", {})
    except json.JSONDecodeError as exc:
        msg = f"JSONDecodeError: {str(exc)[:200]}"
        print(f"[LEGAL-DIAG #{call_id}] PASO-B PARSE FALLÓ: {msg}")
        errores_capturados.append({"paso": "B", "error": msg})
        uso_b = {}
        resultado = {
            "viable_juridico":   None,
            "score_juridico":    None,
            "concepto":          "PARCIAL",
            "riesgos_legales":   "Paso B no completó el análisis",
            "argumentos_viabilidad": "",
            "documentos_a_gestionar": [],
            "requisitos_habilitantes": resultado_a.get("requisitos_habilitantes", []),
            "matriz_experiencia": [],
        }
    except Exception as exc:
        msg = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(f"[LEGAL-DIAG #{call_id}] PASO-B ABORTADO: {msg}")
        errores_capturados.append({"paso": "B", "error": msg})
        uso_b = {}
        resultado = {
            "viable_juridico":   None,
            "score_juridico":    None,
            "concepto":          "PARCIAL",
            "riesgos_legales":   "Paso B falló — ver _estado_analisis",
            "argumentos_viabilidad": "",
            "documentos_a_gestionar": [],
            "requisitos_habilitantes": resultado_a.get("requisitos_habilitantes", []),
            "matriz_experiencia": [],
        }

    t_total = round(_time.time() - t_inicio, 1)
    print(f"[LEGAL-DIAG #{call_id}] TOTAL | {t_total}s (Paso A + Paso B)")

    score_j = resultado.get("score_juridico")
    if score_j is not None and score_j == 0:
        print(f"[LEGAL-DIAG #{call_id}] score_juridico=0 — posible resultado degradado")

    # Retrocompatibilidad
    if "viable_juridico" not in resultado:
        resultado["viable_juridico"] = resultado.get("concepto") == "VIABLE"
    if "riesgos_legales" not in resultado:
        resultado["riesgos_legales"] = "; ".join(resultado.get("riesgos", ["Sin riesgos identificados"])[:2])
    if "argumentos_viabilidad" not in resultado:
        resultado["argumentos_viabilidad"] = resultado.get("concepto", "Sin análisis disponible")
    if "documentos_a_gestionar" not in resultado:
        resultado["documentos_a_gestionar"] = resultado.get("documentos_faltantes", [])

    # Estado de análisis para consumidores del JSON
    if errores_capturados:
        estado_an = "parcial" if paso_a_ok else "fallido"
    else:
        estado_an = "completo"

    resultado["_estado_analisis"] = {
        "estado":         estado_an,
        "paso_a_exitoso": paso_a_ok,
        "paso_b_exitoso": paso_b_ok,
        "errores":        errores_capturados,
    }
    resultado["_tokens_uso"] = {
        "paso_a_input":  uso_a.get("input_tokens"),
        "paso_a_output": uso_a.get("output_tokens"),
        "paso_b_input":  uso_b.get("input_tokens"),
        "paso_b_output": uso_b.get("output_tokens"),
    }

    return resultado


def analizar_cliente_vs_licitacion_paralelo(licitacion, cliente, modalidad, sector, texto_pliego=None, cliente_id=None):
    """
    ORQUESTADOR CENTRAL v3.1 — agentes financiero y legal en paralelo (ThreadPoolExecutor).
    El contexto RAG se computa en el hilo principal antes de lanzar los hilos para evitar
    condiciones de carrera en la carga del modelo de embeddings.
    cliente_id: si se proporciona, enriquece análisis con documentos e historial del cliente.
    """
    from concurrent.futures import ThreadPoolExecutor

    _ERR_FIN = {
        "score_financiero": 0, "cumple_financiero": False, "concepto": "ERROR",
        "razones": [], "articulos_aplicables": [], "recomendaciones": [],
        "indices_evaluados": {}, "analisis_numerico": "", "checklist_detallado": [],
    }
    _ERR_LEG = {
        "viable_juridico": False, "score_juridico": 0, "concepto": "ERROR",
        "riesgos_legales": "", "argumentos_viabilidad": "", "documentos_a_gestionar": [],
        "documentos_faltantes": [], "riesgos": [], "requisitos_habilitantes": [],
        "matriz_experiencia": [],
    }

    # Contexto RAG en hilo principal — garantiza modelo cargado antes de paralelizar
    consulta_rag = " ".join(filter(None, [
        licitacion.get('nombre_del_procedimiento', ''),
        f"Sector {sector}",
        f"Modalidad {modalidad}",
        " ".join(cliente.get("codigos_unspsc_permitidos", []) or []),
    ]))
    contexto_legal = obtener_contexto_legal(modalidad, sector, consulta=consulta_rag, top_k=8)

    def _run_financiero():
        try:
            return agente_financiero(licitacion, cliente, texto_pliego=texto_pliego, cliente_id=cliente_id)
        except Exception as e:
            return {**_ERR_FIN, "analisis_numerico": f"Error agente financiero: {e}"}

    def _run_legal():
        try:
            return agente_legal_rag(
                licitacion, contexto_legal, cliente.get("experiencia"),
                texto_pliego, cliente_id=cliente_id,
            )
        except Exception as e:
            # El detalle (texto crudo, stop_reason, tokens) ya quedó impreso
            # dentro de agente_legal_rag bajo el mismo call_id — aquí solo
            # confirmamos que _run_legal capturó la excepción y devolvió el fallback.
            print(f"[LEGAL-DIAG] _run_legal capturó {type(e).__name__} — devolviendo score=0")
            return {**_ERR_LEG, "riesgos_legales": f"Error agente legal: {type(e).__name__}"}

    with ThreadPoolExecutor(max_workers=2) as executor:
        fut_fin = executor.submit(_run_financiero)
        fut_leg = executor.submit(_run_legal)
        res_financiero = fut_fin.result()
        res_legal      = fut_leg.result()

    viable_final = res_financiero["cumple_financiero"] and res_legal["viable_juridico"]
    score_fin = res_financiero.get("score_financiero", 0)
    score_jur = res_legal.get("score_juridico", 0)

    return {
        "viable": viable_final,
        "score": score_fin,
        "score_juridico": score_jur,
        "accion": "PRESENTAR" if viable_final else "REVISAR",
        "motivo": f"FINANZAS: {res_financiero.get('analisis_numerico', '')} | JURÍDICO: {res_legal.get('riesgos_legales', '')}",
        # Datos enriquecidos v3.0
        "concepto_financiero": res_financiero.get("concepto", ""),
        "razones_financiero": res_financiero.get("razones", []),
        "articulos_aplicables": res_financiero.get("articulos_aplicables", []),
        "recomendaciones": res_financiero.get("recomendaciones", []),
        "indices_evaluados": res_financiero.get("indices_evaluados", {}),
        "concepto_juridico": res_legal.get("concepto", ""),
        "requisitos_habilitantes": res_legal.get("requisitos_habilitantes", []),
        "riesgos_juridicos": res_legal.get("riesgos", []),
        "documentos_faltantes": res_legal.get("documentos_faltantes", []),
        # Matrices estructuradas (compatibilidad v2.0)
        "checklist_financiero": res_financiero.get("checklist_detallado", []),
        "matriz_experiencia": res_legal.get("matriz_experiencia", []),
        # Data para PDF
        "pdf_checklist": res_financiero.get("checklist_detallado", []),
        "pdf_argumentos": res_legal.get("argumentos_viabilidad", ""),
        "pdf_documentos": res_legal.get("documentos_a_gestionar", []),
        "detalles_licitacion": {
            "objeto": licitacion.get("nombre_del_procedimiento"),
            "entidad": licitacion.get("entidad", "Entidad Estatal"),
            "valor": licitacion.get("precio_base"),
            "cliente": cliente.get("nombre", "Cliente"),
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# PIPELINE 1 — FUNCIONES PARA EL FLUJO AUTOMÁTICO (agente_secop.py)
# Versión ligera sin RAG: carga clientes JSON y hace filtros duros + IA
# simple de viabilidad. Coexisten con el motor RAG premium sin conflicto.
# ═══════════════════════════════════════════════════════════════════════

def cargar_clientes():
    """
    Carga los perfiles de los clientes desde la carpeta ./clientes/*.json
    Usado por agente_secop.py y por la nueva pantalla de búsqueda en app.py.
    """
    import os as _os
    ruta_clientes = "./clientes"
    clientes = []
    if not _os.path.exists(ruta_clientes):
        _os.makedirs(ruta_clientes, exist_ok=True)
        return clientes
    for archivo in _os.listdir(ruta_clientes):
        if archivo.endswith(".json"):
            try:
                with open(_os.path.join(ruta_clientes, archivo), "r", encoding="utf-8") as f:
                    clientes.append(json.load(f))
            except Exception as e:
                print(f"Error cargando cliente {archivo}: {e}")
    return clientes


def _analisis_viabilidad_ligero(licitacion, cliente):
    """
    Análisis rápido de viabilidad cliente vs licitación para el Pipeline 1.
    Usa Claude con un prompt corto (sin RAG) — optimizado para velocidad y costo.
    Devuelve dict con: viable, score, accion, riesgo, motivo
    """
    import anthropic as _anthropic

    _client = _anthropic.Anthropic(api_key=API_KEY, timeout=120.0, max_retries=2)

    fin = cliente.get("financiero", {})
    prompt = f"""
    Analiza si este cliente puede presentarse a esta licitación.

    LICITACIÓN:
    - Objeto: {licitacion.get('nombre_del_procedimiento', 'N/A')}
    - Valor: COP {licitacion.get('precio_base', 0)}
    - Fase: {licitacion.get('fase', 'N/A')}
    - Departamento: {licitacion.get('departamento_entidad', 'N/A')}

    CLIENTE:
    - Nombre: {cliente.get('nombre', 'N/A')}
    - Sector: {cliente.get('sector', 'N/A')}
    - Presupuesto máximo: COP {fin.get('presupuesto_maximo_contrato', 0)}
    - Liquidez: {fin.get('indice_liquidez', 0)}
    - Endeudamiento: {fin.get('indice_endeudamiento', 0)}
    - RUP: {cliente.get('rup', {}).get('estado_rup', 'Desconocido')}

    Responde SOLO con JSON sin texto adicional:
    {{"viable": true o false, "score": 0-100, "accion": "PRESENTAR" o "REVISAR" o "DESCARTAR", "riesgo": "BAJO" o "MEDIO" o "ALTO", "motivo": "explicación en máximo 2 líneas"}}
    """

    try:
        respuesta = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=250,
            extra_body={"temperature": 0.0},
            messages=[{"role": "user", "content": prompt}]
        )
        return _extraer_json(respuesta.content[0].text)
    except Exception as e:
        return {"viable": False, "score": 0, "accion": "ERROR", "riesgo": "ALTO", "motivo": str(e)}


def cruzar_licitacion_con_clientes(licitacion, clientes):
    """
    Cruza una licitación detectada con todos los clientes cargados.
    Aplica filtros duros primero (sector, presupuesto, RUP, fase) para
    evitar gastar tokens de API en clientes claramente no aptos.

    Devuelve lista de dicts:
    {
        "cliente": nombre_cliente,
        "pasa_filtro": bool,
        "motivo_filtro": str,      # razón si no pasó el filtro duro
        "analisis_ia": dict|None   # resultado de _analisis_viabilidad_ligero
    }
    """
    fases_validas = [
        "presentación de oferta", "convocatoria abierta", "publicado",
        "manifestación de interés", "selección abreviada",
    ]

    keywords_sector = {
        "hvac":         ["hvac", "aire acondicionado", "climatizacion", "refrigeracion", "ventilacion"],
        "obras civiles":["obra", "civil", "construc", "adecuac", "mantenimiento", "locativo", "infraestructura"],
        "transporte":   ["transporte", "logistica", "carga", "vehiculo", "flete", "movilizacion"],
    }

    objeto_lic = (
        str(licitacion.get("nombre_del_procedimiento", "")) + " " +
        str(licitacion.get("descripci_n_del_procedimiento", ""))
    ).lower()

    try:
        valor_lic = float(licitacion.get("precio_base", 0))
    except (ValueError, TypeError):
        valor_lic = 0

    fase_lic = str(licitacion.get("fase", "")).lower()

    resultados = []
    for cliente in clientes:
        nombre = cliente.get("nombre", "Cliente desconocido")
        fin = cliente.get("financiero", {})
        sector_cliente = cliente.get("sector", "").lower()
        rup_estado = cliente.get("rup", {}).get("estado_rup", "").lower()

        # ── Filtro 1: RUP activo ──────────────────────────────────────
        if "activo" not in rup_estado:
            resultados.append({
                "cliente": nombre, "pasa_filtro": False,
                "motivo_filtro": f"RUP no activo ({rup_estado})", "analisis_ia": None
            })
            continue

        # ── Filtro 2: fase válida ─────────────────────────────────────
        if fase_lic and not any(f in fase_lic for f in fases_validas):
            resultados.append({
                "cliente": nombre, "pasa_filtro": False,
                "motivo_filtro": f"Fase no válida: {licitacion.get('fase', 'N/A')}", "analisis_ia": None
            })
            continue

        # ── Filtro 3: rango presupuestal ──────────────────────────────
        pres_min = fin.get("presupuesto_minimo_contrato", 0)
        pres_max = fin.get("presupuesto_maximo_contrato", float("inf"))
        if valor_lic > 0 and not (pres_min <= valor_lic <= pres_max):
            resultados.append({
                "cliente": nombre, "pasa_filtro": False,
                "motivo_filtro": f"Valor COP {valor_lic:,.0f} fuera del rango del cliente", "analisis_ia": None
            })
            continue

        # ── Filtro 4: sector compatible ───────────────────────────────
        kws = []
        for sec, palabras in keywords_sector.items():
            if sec in sector_cliente:
                kws = palabras
                break
        if kws and not any(kw in objeto_lic for kw in kws):
            resultados.append({
                "cliente": nombre, "pasa_filtro": False,
                "motivo_filtro": f"Sector cliente '{sector_cliente}' no aplica al objeto", "analisis_ia": None
            })
            continue

        # ── Pasa filtros duros → análisis IA ligero ───────────────────
        analisis = _analisis_viabilidad_ligero(licitacion, cliente)
        resultados.append({
            "cliente": nombre, "pasa_filtro": True,
            "motivo_filtro": "Pasó todos los filtros duros", "analisis_ia": analisis
        })

    return resultados