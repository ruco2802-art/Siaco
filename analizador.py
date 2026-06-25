# -*- coding: utf-8 -*-
import json
import os
import re

from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


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
    import pandas as pd
    from docx import Document
    from pypdf import PdfReader

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
                    reader = PdfReader(ruta_completa)
                    paginas_texto = []
                    for i, pagina in enumerate(reader.pages):
                        if i >= LIMITE_PAGINAS_PDF:
                            break
                        paginas_texto.append(pagina.extract_text() or "")
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
    import fitz  # PyMuPDF
    try:
        import pytesseract
        from PIL import Image
        TESSERACT_DISPONIBLE = True
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    except ImportError:
        TESSERACT_DISPONIBLE = False

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
    for i, pagina in enumerate(doc):
        texto = pagina.get_text()
        if len(texto.strip()) < 100 and TESSERACT_DISPONIBLE:
            try:
                pix = pagina.get_pixmap(matrix=fitz.Matrix(2, 2))
                imagen = Image.open(_io.BytesIO(pix.tobytes("png")))
                texto = pytesseract.image_to_string(imagen, lang='spa')
            except Exception:
                pass  # conserva el texto nativo residual

        texto_min = texto.lower()
        if any(kw in texto_min for kw in keywords_habilitantes):
            paginas_criticas.append({"pagina": i + 1, "texto": texto})

    paginas_criticas.sort(key=lambda x: len(x["texto"]), reverse=True)
    return paginas_criticas[:7]


def extraer_texto_pliego(ruta_pdf_o_bytes):
    """
    Función de conveniencia: llama a escanear_paginas_pdf() y concatena
    el texto de las páginas relevantes en un único string listo para
    inyectar en el prompt de los agentes.
    """
    paginas = escanear_paginas_pdf(ruta_pdf_o_bytes)
    if not paginas:
        return ""
    bloques = []
    for p in paginas:
        bloques.append(f"--- EXTRACTO PÁGINA {p['pagina']} ---\n{p['texto']}")
    return "\n".join(bloques)


def extraer_texto_completo_pdf(raw_bytes: bytes) -> str:
    """
    Extrae TODO el texto del PDF sin filtrar por keywords.
    OCR automático (Tesseract spa) si la página tiene < 50 chars de texto nativo.
    Retorna string vacío si el PDF no se puede leer.
    """
    import io as _io
    import fitz

    TESSERACT = False
    try:
        import pytesseract
        from PIL import Image
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
    for i, pagina in enumerate(doc):
        texto = pagina.get_text().strip()
        if len(texto) < 50 and TESSERACT:
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
    return resultado


_RAG_QUERIES = [
    "requisitos financieros indice liquidez endeudamiento capital trabajo patrimonio",
    "experiencia tecnica contratos anteriores similares UNSPSC CIIU objeto similar",
    "requisitos habilitantes juridicos RUP camara comercio capacidad juridica",
    "objeto contrato valor presupuesto oficial precio base estimado",
    "plazo ejecucion anticipo forma pago modalidad seleccion cronograma",
]


def chunking_rag_pliego(texto: str, query: str = "", top_k_por_query: int = 5) -> str:
    """
    RAG semántico multi-query para pliegos de cualquier tamaño.

    - Chunking: 800 chars con overlap 150
    - 5 queries especializadas en habilitantes SECOP II
    - top_k_por_query chunks por query → deduplicados (máx 25 únicos)
    - Resultado ordenado por posición original para coherencia
    - Fallback sin modelo: primeros + últimos chunks
    """
    CHUNK_SIZE = 800
    OVERLAP    = 150
    MAX_CHARS  = 5000   # límite de contexto enviado a Claude

    # ── Chunking ──────────────────────────────────
    chunks = []    # list of (original_pos, text)
    pos = 0
    while pos < len(texto):
        chunk = texto[pos: pos + CHUNK_SIZE].strip()
        if len(chunk) > 60:
            chunks.append((pos, chunk))
        pos += CHUNK_SIZE - OVERLAP

    if not chunks:
        return texto[:MAX_CHARS]
    if len(chunks) <= top_k_por_query:
        resultado = "\n\n".join(c[1] for c in chunks)
        return resultado[:MAX_CHARS]

    print(f"[RAG] {len(chunks)} chunks generados de {len(texto)} chars")

    # ── Embedding + recuperación ───────────────────
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np

        print("[RAG] Generando embeddings...")
        model  = SentenceTransformer("all-MiniLM-L6-v2")
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
        seleccion  = "\n\n[...]\n\n".join(texts[i] for i in sorted_idx)

        print(f"[RAG] {len(selected)} chunks únicos seleccionados de {len(queries)} queries → {len(seleccion)} chars")
        return seleccion[:MAX_CHARS]

    except Exception as e:
        print(f"[RAG] Fallback sin modelo semántico: {e}")
        mid      = top_k_por_query // 2
        textos   = [c[1] for c in chunks]
        fallback = textos[:mid] + textos[-(top_k_por_query - mid):]
        return "\n\n[...]\n\n".join(fallback)[:MAX_CHARS]


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

    # Códigos UNSPSC del cliente (primeros 4 dígitos de cada código)
    codigos_cliente = [
        c.strip()[:4]
        for c in str(perfil_cliente.get("codigos_unspsc", "")).split(",")
        if c.strip()
    ]

    # Keywords: del perfil + de KEYWORDS_HVAC de config
    try:
        from config_legacy import KEYWORDS_HVAC as _kw_hvac
        kw_extra = [k.lower() for k in _kw_hvac]
    except Exception:
        kw_extra = []
    keywords_perfil = list(_extraer_keywords(str(perfil_cliente.get("objeto_similar", ""))))
    # Combinar sin duplicados (keywords del perfil tienen prioridad)
    todas_keywords = keywords_perfil + [k for k in kw_extra if k not in keywords_perfil]

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
        score_unspsc = 1.0 if any(cod in unspsc_c for cod in codigos_cliente if cod) else 0.0

        # Nivel 2: Keywords — buscar en título + descripción
        score_keywords = 0.0
        if todas_keywords:
            matches = sum(1 for kw in todas_keywords if kw in texto_contrato)
            score_keywords = min(1.0, matches / max(len(todas_keywords), 1))

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

        if modelo is not None:
            score_final = 0.25 * score_unspsc + 0.35 * score_keywords + 0.40 * score_semantico
            pasa = score_final > 0.40 or score_unspsc == 1.0 or score_keywords > 0.60
        else:
            # Sin modelo semántico: solo UNSPSC + keywords con umbral más bajo
            score_final = 0.40 * score_unspsc + 0.60 * score_keywords
            pasa = score_final > 0.25 or score_unspsc == 1.0 or score_keywords > 0.40

        print(
            f"[HÍBRIDO] {titulo[:50]:<50} | "
            f"UNSPSC={score_unspsc:.2f} KW={score_keywords:.2f} "
            f"Sem={score_semantico:.2f} Total={score_final:.2f} | "
            f"{'✓ PASA' if pasa else '✗ descarta'}"
        )

        if pasa:
            resultados.append({
                **contrato,
                "score_hibrido": round(score_final, 4),
                "score_unspsc": score_unspsc,
                "score_keywords": round(score_keywords, 4),
                "score_semantico": round(score_semantico, 4),
            })

    resultados.sort(key=lambda x: x["score_hibrido"], reverse=True)
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


def agente_financiero(licitacion, cliente, texto_pliego=None, cliente_id=None):
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
        bloque_pliego = (
            f"\nPLIEGO ESPECÍFICO (prioridad sobre criterios genéricos):\n{texto_pliego[:8000]}\n"
        )
    else:
        bloque_pliego = "\nPLIEGO ESPECÍFICO: No suministrado. Usa criterios financieros genéricos de contratación estatal colombiana.\n"

    prompt = f"""
{_SKILL_FIN}

Actúa como un Auditor Financiero experto en contratación estatal colombiana.
IMPORTANTE: Cita siempre el artículo o norma específica (Ley 80/1993, Decreto 1082/2015,
Resolución 196/2016 CCE) que respalda cada punto de tu evaluación.

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

REGLA DE ORO: Responde ÚNICAMENTE con JSON válido. Estructura exacta:
{{
    "score_financiero": numero_0_a_100,
    "concepto": "VIABLE" o "NO VIABLE" o "CONDICIONAL",
    "razones": ["razón 1 con decreto o artículo si aplica"],
    "articulos_aplicables": ["Decreto 1082/2015 art. X"],
    "recomendaciones": ["acción concreta 1"],
    "indices_evaluados": {{"liquidez": valor_numerico, "endeudamiento": valor_numerico, "capital_trabajo": "calculado o N/A"}},
    "cumple_financiero": true o false,
    "analisis_numerico": "resumen corto max 2 líneas",
    "checklist_detallado": [
        {{"requisito": "Índice de Liquidez", "valor_pliego": "exigido", "valor_empresa": "del cliente", "cumple": true}},
        {{"requisito": "Índice de Endeudamiento", "valor_pliego": "exigido", "valor_empresa": "del cliente", "cumple": true}},
        {{"requisito": "Capacidad de Contratación (RUP)", "valor_pliego": "valor contrato", "valor_empresa": "cap. máx. cliente", "cumple": true}}
    ]
}}
"""

    t0 = _time.time()
    respuesta = api_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = _time.time() - t0
    if elapsed > 10:
        try:
            from logger import setup_logger
            setup_logger().warning(f"agente_financiero tardó {elapsed:.1f}s — módulo_origen=analizador")
        except Exception:
            pass

    resultado = _extraer_json(respuesta.content[0].text)

    # Garantizar retrocompatibilidad: derivar campos si faltan
    if "cumple_financiero" not in resultado:
        resultado["cumple_financiero"] = resultado.get("concepto") == "VIABLE"
    if "analisis_numerico" not in resultado:
        resultado["analisis_numerico"] = resultado.get("razones", [""])[0]
    if "checklist_detallado" not in resultado:
        idx = resultado.get("indices_evaluados", {})
        resultado["checklist_detallado"] = [
            {"requisito": "Índice de Liquidez", "valor_pliego": "≥ 1.0", "valor_empresa": str(idx.get("liquidez", "N/A")), "cumple": resultado.get("cumple_financiero", False)},
            {"requisito": "Índice de Endeudamiento", "valor_pliego": "≤ 0.80", "valor_empresa": str(idx.get("endeudamiento", "N/A")), "cumple": resultado.get("cumple_financiero", False)},
        ]

    return resultado


def agente_legal_rag(licitacion, contexto_biblioteca, experiencia_cliente=None, texto_pliego=None, cliente_id=None):
    """
    AGENTE 2: Abogado Consultor RAG con cruce documental del cliente.
    cliente_id: si se proporciona, cruza requisitos del pliego con documentos del cliente.
    """
    import anthropic
    import time as _time

    try:
        from prompts import SKILL_JURIDICO as _SKILL_JUR, SKILL_ESTRATEGIA as _SKILL_EST
    except ImportError:
        _SKILL_JUR = ""
        _SKILL_EST = ""

    api_client = anthropic.Anthropic(api_key=API_KEY, timeout=120.0, max_retries=2)
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

    bloque_experiencia = f"""
EXPERIENCIA REGISTRADA DEL OFERENTE:
- Valor acumulado contratos similares (3 años): COP {experiencia_cliente.get('valor_acumulado', 'No registrado')}
- Valor contrato individual más alto: COP {experiencia_cliente.get('valor_individual_max', 'No registrado')}
- Objetos de contratos similares: {experiencia_cliente.get('objeto_similar', 'No registrado')}
- Códigos UNSPSC: {experiencia_cliente.get('codigos_unspsc', 'No registrado')}
- Participación mínima en consorcios previos: {experiencia_cliente.get('participacion_minima', 'No registrado')}%
"""

    if texto_pliego:
        bloque_pliego = f"\nPLIEGO ESPECÍFICO (prioridad sobre biblioteca normativa):\n{texto_pliego[:15000]}\n"
    else:
        bloque_pliego = "\nPLIEGO ESPECÍFICO: No suministrado. Análisis basado en biblioteca normativa general.\n"

    prompt = f"""
{_SKILL_JUR}
{_SKILL_EST}

Actúa como Abogado Consultor experto en contratación pública colombiana.
IMPORTANTE: Cita siempre el artículo y norma específica (Ley 80/1993, Ley 1150/2007,
Decreto 1082/2015, Resolución CCE) que respalda cada evaluación. Indica si el documento
faltante es SUBSANABLE o NO SUBSANABLE con base en Ley 1150/2007 art. 5.

OBJETO PROCESO: {licitacion.get('nombre_del_procedimiento')}
VALOR: COP {licitacion.get('precio_base')}

BIBLIOTECA NORMATIVA (fragmentos más relevantes):
{contexto_biblioteca[:10000]}
{bloque_pliego}
{bloque_experiencia}
{bloque_docs_cliente}

Evalúa la experiencia habilitante cruzando los datos del cliente con los requisitos.
Prioriza el pliego sobre la biblioteca. Si no hay info suficiente, usa "Sin información disponible".

REGLA DE ORO: Responde ÚNICAMENTE con JSON válido. Estructura exacta:
{{
    "viable_juridico": true o false,
    "score_juridico": numero_0_a_100,
    "concepto": "VIABLE" o "NO VIABLE" o "CONDICIONAL",
    "riesgos_legales": "resumen max 2 líneas",
    "argumentos_viabilidad": "por qué es viable (max 5 líneas)",
    "documentos_a_gestionar": ["Doc 1", "Doc 2"],
    "documentos_faltantes": ["doc que el cliente no tiene según análisis"],
    "riesgos": ["riesgo con norma aplicable"],
    "requisitos_habilitantes": [
        {{"requisito": "nombre", "exigido": "lo que pide el pliego", "cliente_tiene": "lo que tiene el cliente", "cumple": true, "documento_soporte": "nombre doc", "norma": "art. X"}}
    ],
    "matriz_experiencia": [
        {{"requisito": "Valor acumulado de contratos", "valor_pliego": "exigido", "valor_empresa": "COP {experiencia_cliente.get('valor_acumulado', '—')}", "cumple": true o false}},
        {{"requisito": "Valor contrato individual más alto", "valor_pliego": "exigido", "valor_empresa": "COP {experiencia_cliente.get('valor_individual_max', '—')}", "cumple": true o false}},
        {{"requisito": "Objeto similar", "valor_pliego": "clasificación exigida", "valor_empresa": "{experiencia_cliente.get('objeto_similar', '—')}", "cumple": true o false}},
        {{"requisito": "Códigos UNSPSC", "valor_pliego": "códigos exigidos", "valor_empresa": "{experiencia_cliente.get('codigos_unspsc', '—')}", "cumple": true o false}},
        {{"requisito": "Participación mínima", "valor_pliego": "porcentaje exigido", "valor_empresa": "{experiencia_cliente.get('participacion_minima', '—')}%", "cumple": true o false}}
    ]
}}
"""

    t0 = _time.time()
    respuesta = api_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = _time.time() - t0
    if elapsed > 10:
        try:
            from logger import setup_logger
            setup_logger().warning(f"agente_legal_rag tardó {elapsed:.1f}s — módulo_origen=analizador")
        except Exception:
            pass

    resultado = _extraer_json(respuesta.content[0].text)

    # Retrocompatibilidad
    if "viable_juridico" not in resultado:
        resultado["viable_juridico"] = resultado.get("concepto") == "VIABLE"
    if "riesgos_legales" not in resultado:
        resultado["riesgos_legales"] = "; ".join(resultado.get("riesgos", ["Sin riesgos identificados"])[:2])
    if "argumentos_viabilidad" not in resultado:
        resultado["argumentos_viabilidad"] = resultado.get("concepto", "Sin análisis disponible")
    if "documentos_a_gestionar" not in resultado:
        resultado["documentos_a_gestionar"] = resultado.get("documentos_faltantes", [])

    return resultado


def analizar_cliente_vs_licitacion_paralelo(licitacion, cliente, modalidad, sector, texto_pliego=None, cliente_id=None):
    """
    ORQUESTADOR CENTRAL v3.0.
    cliente_id: si se proporciona, enriquece análisis con documentos e historial del cliente.
    """
    res_financiero = agente_financiero(licitacion, cliente, texto_pliego=texto_pliego, cliente_id=cliente_id)

    consulta_rag = " ".join(filter(None, [
        licitacion.get('nombre_del_procedimiento', ''),
        f"Sector {sector}",
        f"Modalidad {modalidad}",
        " ".join(cliente.get("codigos_unspsc_permitidos", []) or []),
    ]))

    contexto_legal = obtener_contexto_legal(modalidad, sector, consulta=consulta_rag, top_k=8)
    res_legal = agente_legal_rag(
        licitacion, contexto_legal, cliente.get("experiencia"),
        texto_pliego, cliente_id=cliente_id
    )

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
            temperature=0.0,
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