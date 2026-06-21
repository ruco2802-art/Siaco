# -*- coding: utf-8 -*-
import hashlib
import pickle
from pathlib import Path


class CacheManager:
    """Gestión de caché de embeddings con invalidación por hash MD5."""

    @staticmethod
    def _md5_directorio(ruta: str) -> str:
        """MD5 agregado de todos los archivos de un directorio."""
        h = hashlib.md5()
        p = Path(ruta)
        if not p.exists():
            return ""
        for f in sorted(p.rglob("*")):
            if f.is_file():
                try:
                    h.update(f.read_bytes())
                except Exception:
                    pass
        return h.hexdigest()

    def cargar_embeddings_biblioteca(self, modalidad: str):
        """Embeddings de biblioteca normativa; invalida si cambió algún archivo."""
        import streamlit as st
        ruta = f"./biblioteca_normativa/{modalidad}"
        hash_actual = self._md5_directorio(ruta)
        cache_key = f"emb_bib_{modalidad}"
        hash_key = f"emb_bib_hash_{modalidad}"

        if st.session_state.get(hash_key) == hash_actual and cache_key in st.session_state:
            return st.session_state[cache_key]

        from analizador import _listar_documentos_relevantes, _chunkear_texto, _obtener_modelo_embeddings
        import numpy as np

        docs = _listar_documentos_relevantes(modalidad, "")
        chunks_texto = [ch for doc in docs for ch in _chunkear_texto(doc["texto"])]
        if not chunks_texto:
            return None

        modelo = _obtener_modelo_embeddings()
        embeddings = modelo.encode(chunks_texto, convert_to_numpy=True, show_progress_bar=False)
        resultado = {"chunks": chunks_texto, "embeddings": embeddings}
        st.session_state[cache_key] = resultado
        st.session_state[hash_key] = hash_actual
        return resultado

    def cargar_embeddings_cliente(self, cliente_id: str):
        """Embeddings de documentos del cliente; invalida si cambió el pkl."""
        import streamlit as st
        ruta_pkl = Path(f"./clientes/{cliente_id}/embeddings/documentos_index.pkl")
        if not ruta_pkl.exists():
            return None

        hash_actual = hashlib.md5(ruta_pkl.read_bytes()).hexdigest()
        cache_key = f"emb_cli_{cliente_id}"
        hash_key = f"emb_cli_hash_{cliente_id}"

        if st.session_state.get(hash_key) == hash_actual and cache_key in st.session_state:
            return st.session_state[cache_key]

        with open(ruta_pkl, "rb") as f:
            datos = pickle.load(f)
        st.session_state[cache_key] = datos
        st.session_state[hash_key] = hash_actual
        return datos

    def limpiar_cache_cliente(self, cliente_id: str):
        """Fuerza recarga de embeddings del cliente en la próxima consulta."""
        import streamlit as st
        for key in [f"emb_cli_{cliente_id}", f"emb_cli_hash_{cliente_id}"]:
            st.session_state.pop(key, None)
