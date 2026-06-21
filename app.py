# -*- coding: utf-8 -*-
import streamlit as st
import json
import os
from pathlib import Path
from datetime import datetime

from analizador import (
    obtener_contexto_legal,
    analizar_cliente_vs_licitacion_paralelo,
    extraer_texto_pliego,
    cargar_clientes,
    cruzar_licitacion_con_clientes,
    guardar_analisis_historial,
    actualizar_resultado,
    analizar_patrones,
    _extraer_json,
)

# ─────────────────────────────────────────────
# CONFIG GENERAL
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="SIACO v3.0 — Inteligencia de Contratación",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# ESTILOS
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap');
* { font-family: 'Inter', sans-serif; }
html, body, [class*="css"],
[data-testid="stAppViewContainer"], [data-testid="stApp"],
.main, .main > div, [data-testid="stMain"], section.main {
    background-color: #0A0A0A !important; color: #F5F5F0;
}
[data-testid="stSidebar"] { background-color: #0F0F0F; border-right: 1px solid #1F1F1F; }
[data-testid="stSidebar"] .stRadio label { color: #9A9A9A; font-size: 0.85rem; }
.block-container { padding: 2rem 2.5rem; max-width: 1400px; }
.siaco-logo { font-family: 'JetBrains Mono', monospace; font-size: 1.4rem; font-weight: 600; color: #C6F24E; letter-spacing: 0.15em; }
.siaco-sub { font-size: 0.72rem; color: #9A9A9A; letter-spacing: 0.08em; }
h1, h2, h3, h4, h5, h6,
[data-testid="stHeading"], [data-testid="stHeading"] h1, [data-testid="stHeading"] h1 *,
[data-testid="stMarkdownContainer"] h1, .main [data-testid="stVerticalBlock"] h1 {
    color: #FFFFFF !important; -webkit-text-fill-color: #FFFFFF !important;
    background: transparent !important; background-color: transparent !important;
    background-image: none !important; -webkit-background-clip: unset !important;
    background-clip: unset !important; opacity: 1 !important;
}
h1 { font-weight: 800 !important; letter-spacing: -0.01em; }
[data-testid="stCaptionContainer"], .stCaption, small { color: #9A9A9A !important; }
.metric-card { background: #141414; border: 1px solid #262626; border-radius: 16px; padding: 18px 22px; text-align: center; }
.metric-value { font-family: 'JetBrains Mono', monospace; font-size: 2.1rem; font-weight: 700; color: #C6F24E; line-height: 1.1; }
.metric-label { font-size: 0.75rem; color: #9A9A9A; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 4px; }
.veredicto-box { border-radius: 16px; padding: 18px 22px; font-size: 0.95rem; line-height: 1.5; }
.veredicto-viable { background: #16210A; border: 1px solid #C6F24E; color: #F5F5F0; box-shadow: 0 0 24px -8px rgba(198,242,78,0.35); }
.veredicto-riesgo { background: #2B1F08; border: 1px solid #F0A500; color: #F5F5F0; }
.status-bar { background: #141414; border: 1px solid #262626; border-radius: 12px; padding: 10px 16px; font-size: 0.8rem; color: #9A9A9A; margin-bottom: 1.5rem; }
.stButton > button { background: #C6F24E !important; color: #0A0A0A !important; border: none !important; border-radius: 999px !important; font-weight: 700 !important; padding: 10px 24px !important; box-shadow: 0 0 24px -6px rgba(198,242,78,0.5) !important; transition: box-shadow 0.2s, opacity 0.2s !important; }
.stButton > button:hover { opacity: 0.9 !important; box-shadow: 0 0 32px -4px rgba(198,242,78,0.7) !important; }
.stTextInput input, .stSelectbox > div, .stNumberInput input,
.stSelectbox div[data-baseweb="select"] > div, .stSelectbox div[data-baseweb="select"] *,
.stFileUploader section { background: #F0F0EC !important; border: 1px solid #D5D5D0 !important; color: #1A1A1A !important; border-radius: 12px !important; }
.stTextInput input::placeholder, .stNumberInput input::placeholder { color: #8A8A85 !important; }
.stSelectbox svg { fill: #1A1A1A !important; }
label { color: #9A9A9A !important; font-size: 0.8rem !important; text-transform: uppercase !important; letter-spacing: 0.05em !important; }
hr { border-color: #1F1F1F !important; }
.stProgress > div > div { background: #C6F24E !important; }
[data-testid="stMetricValue"] { color: #C6F24E !important; font-family: 'JetBrains Mono', monospace; }
[data-testid="stMetricLabel"] { color: #9A9A9A !important; }
.urgencia-rojo { background: #3B0D0D; border: 1px solid #FF4444; border-radius: 8px; padding: 6px 10px; }
.urgencia-amarillo { background: #2B1F08; border: 1px solid #FFB800; border-radius: 8px; padding: 6px 10px; }
.urgencia-verde { background: #16210A; border: 1px solid #C6F24E; border-radius: 8px; padding: 6px 10px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# VERIFICAR API KEY
# ─────────────────────────────────────────────
import config as _cfg
if not _cfg.API_KEY:
    st.error("⚠️ Configura la variable de entorno ANTHROPIC_API_KEY antes de iniciar SIACO.")
    st.code("set ANTHROPIC_API_KEY=sk-ant-api03-...", language="bash")
    st.stop()

# ─────────────────────────────────────────────
# ESTADO DE SESIÓN
# ─────────────────────────────────────────────
defaults = {
    "cliente_activo": None,
    "analisis_resultado": None,
    "caracteres_leidos": 0,
    "perfil_financiero": {"liquidez": 1.4, "endeudamiento": 0.55, "presupuesto_max": 500_000_000},
    "licitacion_actual": None,
    "licitaciones_encontradas": [],
    "texto_pliego": None,
    "nombre_pliego": None,
    "datos_pliego_extraidos": {},
    "auditoria_estado": "idle",
    "auditoria_error": None,
    "audit_params": None,
    "estrategia_competitiva": None,
    "excel_expedientes": None,
    "experiencia_oferente": {
        "valor_acumulado": 1_200_000_000,
        "valor_individual_max": 450_000_000,
        "objeto_similar": "Adecuación y mantenimiento de infraestructura institucional, obras civiles sector salud y educación",
        "codigos_unspsc": "7210, 7211, 7212",
        "participacion_minima": 50,
    },
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ═══════════════════════════════════════════════════════
# PANTALLA DE LOGIN
# ═══════════════════════════════════════════════════════
def _mostrar_login():
    st.markdown("""
    <div style="max-width:420px; margin:80px auto 0;">
        <div class="siaco-logo" style="font-size:2rem; text-align:center; margin-bottom:4px;">◈ SIACO v3.0</div>
        <div class="siaco-sub" style="text-align:center; margin-bottom:32px;">Sistema Inteligente de Análisis de Contratación Pública</div>
    </div>
    """, unsafe_allow_html=True)

    col_c, col_form, col_d = st.columns([1, 2, 1])
    with col_form:
        # Slot persistente — React siempre lo ve, solo cambia el contenido
        _login_slot = st.empty()
        if st.session_state.get("login_error"):
            _login_slot.error(st.session_state.login_error)

        with st.form("form_login"):
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            submit = st.form_submit_button("Ingresar", use_container_width=True)

        if submit:
            from auth import verificar_credenciales
            resultado = verificar_credenciales(username.strip(), password.strip())
            if resultado:
                st.session_state["cliente_activo"] = resultado
                st.session_state["login_error"] = ""
                st.toast(f"Bienvenido, {resultado['nombre']}", icon="✅")
            else:
                st.session_state["login_error"] = "Credenciales incorrectas o cuenta inactiva."


if not st.session_state.get("cliente_activo"):
    _mostrar_login()
    st.stop()

# ─────────────────────────────────────────────
# USUARIO AUTENTICADO
# ─────────────────────────────────────────────
cliente_activo = st.session_state["cliente_activo"]
cliente_id = cliente_activo["id"]
perfil_cliente = cliente_activo.get("perfil_json", {})


# ═══════════════════════════════════════════════════════
# PANEL ADMINISTRADOR
# ═══════════════════════════════════════════════════════
if cliente_activo.get("plan") == "admin":
    from auth import listar_clientes_activos, crear_cliente, desactivar_cliente, generar_nueva_password

    st.title("Panel de Administración SIACO")
    st.caption("Gestión de clientes y accesos del sistema")

    tab_lista, tab_crear = st.tabs(["📋 Clientes activos", "➕ Crear cliente"])

    with tab_lista:
        clientes_lista = listar_clientes_activos()
        if clientes_lista:
            for c in clientes_lista:
                with st.expander(f"{'🟢' if c['activo'] else '🔴'} {c['nombre']} — {c['plan']}"):
                    col1, col2, col3 = st.columns(3)
                    col1.write(f"**ID:** {c['cliente_id']}")
                    col2.write(f"**Creado:** {c['fecha_creacion'][:10]}")
                    col3.write(f"**Vence:** {c['fecha_vencimiento'][:10]}")

                    col_a, col_b, col_c_btn = st.columns(3)
                    with col_a:
                        if st.button("🔑 Nueva password", key=f"npw_{c['cliente_id']}"):
                            nueva = generar_nueva_password(c["cliente_id"])
                            if nueva:
                                st.toast(f"Nueva password: `{nueva}`", icon="🔑")
                    with col_b:
                        if c["activo"] and st.button("🚫 Desactivar", key=f"des_{c['cliente_id']}"):
                            desactivar_cliente(c["cliente_id"])
                            st.toast("Cliente desactivado", icon="🚫")
        else:
            st.info("No hay clientes registrados.")

    with tab_crear:
        with st.form("form_crear_cliente"):
            nc_id = st.text_input("ID del cliente (sin espacios)")
            nc_nombre = st.text_input("Nombre de la empresa")
            nc_pass = st.text_input("Contraseña inicial", type="password")
            nc_plan = st.selectbox("Plan", ["básico", "profesional", "enterprise"])
            nc_dias = st.number_input("Días de vigencia", value=30, min_value=1)
            crear_btn = st.form_submit_button("Crear cliente")

        if crear_btn:
            if nc_id and nc_pass:
                res = crear_cliente(nc_id.strip(), nc_pass, nc_plan, int(nc_dias))
                if res["ok"]:
                    from auth import guardar_perfil
                    perfil_n = {"cliente_id": nc_id.strip(), "nombre": nc_nombre or nc_id.strip(),
                                "plan": nc_plan, "fecha_creacion": datetime.now().isoformat(),
                                "notificacion": "whatsapp", "contacto_whatsapp": "", "contacto_email": ""}
                    guardar_perfil(nc_id.strip(), perfil_n)
                    st.toast(f"✅ Cliente '{nc_id}' creado exitosamente", icon="✅")
                else:
                    st.toast(f"Error al crear cliente: {res}", icon="❌")
            else:
                st.toast("ID y contraseña son obligatorios", icon="⚠️")

    with st.sidebar:
        st.markdown('<div class="siaco-logo">◈ SIACO v3.0</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="color:#C6F24E; font-size:0.82rem;">Admin: {cliente_activo["nombre"]}</div>', unsafe_allow_html=True)
        st.markdown("---")
        with st.form("form_logout_admin"):
            if st.form_submit_button("🚪 Cerrar sesión"):
                st.session_state["cliente_activo"] = None
    st.stop()


# ═══════════════════════════════════════════════════════
# SIDEBAR — USUARIO NORMAL
# ═══════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<div class="siaco-logo">◈ SIACO v3.0</div>', unsafe_allow_html=True)
    st.markdown('<div class="siaco-sub">Sistema Inteligente de Análisis de Contratación</div>', unsafe_allow_html=True)
    st.markdown("---")
    st.markdown(f'<div style="color:#C6F24E; font-size:0.82rem; margin-bottom:8px;">👤 {cliente_activo["nombre"]}</div>', unsafe_allow_html=True)

    pantalla = st.radio(
        "MÓDULOS DEL SISTEMA",
        [
            "👤  Perfil Comercial",
            "🔍  Búsqueda SECOP II",
            "📂  Auditoría de Pliego",
            "📊  Cuadro de Control",
            "🤝  Inteligencia Competitiva",
            "📋  Gestión de Expedientes",
        ],
    )

    st.markdown("---")

    if st.session_state.get("licitacion_actual"):
        lic = st.session_state.licitacion_actual
        st.markdown(f"""
        <div style="font-size:0.75rem; color:#9A9A9A; background:#141414; border:1px solid #262626; border-radius:10px; padding:10px 12px;">
            <span style="color:#C6F24E; font-weight:700;">● Licitación activa</span><br>
            <span style="color:#F5F5F0;">{str(lic.get('nombre_del_procedimiento',''))[:50]}…</span><br>
            <span style="color:#9A9A9A;">COP {float(lic.get('precio_base',0)):,.0f}</span>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    if st.session_state.get("texto_pliego"):
        st.markdown(f"""
        <div style="font-size:0.75rem; color:#9A9A9A; background:#141414; border:1px solid #262626; border-radius:10px; padding:10px 12px;">
            <span style="color:#C6F24E; font-weight:700;">● Pliego cargado</span><br>
            <span style="color:#F5F5F0;">{st.session_state.get('nombre_pliego','')}</span><br>
            <span style="color:#9A9A9A;">{len(st.session_state.texto_pliego):,} caracteres</span>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    st.markdown(f"""
    <div style="font-size:0.78rem; color:#9A9A9A;">
        <span style="color:#C6F24E;">●</span> Motor RAG activo<br>
        <span style="color:#C6F24E;">●</span> Biblioteca legal local cargada<br><br>
        Volumen indexado:<br>
        <span style="color:#C6F24E; font-family:'JetBrains Mono',monospace; font-size:1.1rem;">{st.session_state.caracteres_leidos:,}</span> caracteres
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    with st.form("form_logout_user"):
        if st.form_submit_button("🚪 Cerrar sesión"):
            st.session_state["cliente_activo"] = None


# ═══════════════════════════════════════════════════════
# PANTALLA 1: PERFIL COMERCIAL + BIBLIOTECA DE DOCUMENTOS
# ═══════════════════════════════════════════════════════
if "Perfil Comercial" in pantalla:
    st.title("Configuración del Perfil Empresarial")
    st.caption("Capacidades financieras, experiencia y biblioteca de documentos del cliente")

    tab_perfil, tab_docs = st.tabs(["📝 Perfil y Financiero", "📁 Biblioteca de Documentos"])

    with tab_perfil:
        SECTOR_DEFAULTS = {
            "Obras Civiles": {"objeto": "Construcción, adecuación, mantenimiento y remodelación de infraestructura civil, vías, edificaciones, redes hidrosanitarias y obras de urbanismo.", "unspsc": "72141100, 72141500, 72102900, 72151500"},
            "Salud": {"objeto": "Adecuación, mantenimiento y construcción de centros de salud, hospitales, puestos de salud y edificaciones del sector sanitario.", "unspsc": "72141200, 72141300, 72151500"},
            "Educación": {"objeto": "Construcción, ampliación, adecuación y mantenimiento de instituciones educativas, aulas, baterías sanitarias y espacios recreodeportivos.", "unspsc": "72141100, 72141500, 72102900"},
            "Deporte": {"objeto": "Construcción, adecuación y mantenimiento de escenarios deportivos, coliseos, polideportivos, canchas y espacios recreativos.", "unspsc": "72141100, 72141500, 72151500"},
            "HVAC": {"objeto": "Suministro, instalación y mantenimiento de sistemas de climatización, aires acondicionados, ventilación, ductos y equipos de refrigeración.", "unspsc": "72103200, 40101700, 40101800, 40161500"},
        }

        # sector_comercial fuera del form para actualizar defaults dinámicamente
        sector_comercial = st.selectbox("Sector de Operación Principal",
            ["Obras Civiles", "Salud", "Educación", "Deporte", "HVAC"])
        obj_default = SECTOR_DEFAULTS.get(sector_comercial, {}).get("objeto", "")
        unspsc_default = SECTOR_DEFAULTS.get(sector_comercial, {}).get("unspsc", "")

        _pf = st.session_state.perfil_financiero
        _exp = st.session_state.experiencia_oferente

        with st.form("form_perfil_completo"):
            col1, col2 = st.columns(2)
            with col1:
                nombre_empresa = st.text_input("Razón Social", perfil_cliente.get("nombre", "Construcciones del Huila S.A.S"))
                nit = st.text_input("NIT de la Empresa", perfil_cliente.get("nit", "901.345.892-1"))
            with col2:
                pref_notif = st.selectbox("Preferencia de notificación", ["whatsapp", "gmail", "ambos"],
                    index=["whatsapp","gmail","ambos"].index(perfil_cliente.get("notificacion","whatsapp")))
                contacto_wa = st.text_input("Número WhatsApp (con código país, ej: 573138…)", value=perfil_cliente.get("contacto_whatsapp",""))

            col_r1, col_r2 = st.columns(2)
            with col_r1:
                rup_venc = st.text_input("Fecha vencimiento RUP (YYYY-MM-DD)", value=perfil_cliente.get("fecha_vencimiento_rup",""))
            with col_r2:
                contacto_email = st.text_input("Email para notificaciones", value=perfil_cliente.get("contacto_email",""))

            st.markdown("##### Indicadores Financieros")
            col3, col4, col5 = st.columns(3)
            with col3:
                liq_input = st.number_input("Índice de Liquidez", value=_pf["liquidez"], step=0.1, format="%.2f")
            with col4:
                end_input = st.number_input("Índice de Endeudamiento", value=_pf["endeudamiento"], step=0.05, format="%.2f")
            with col5:
                cap_input = st.number_input("Presupuesto Máximo Ofertante (COP)", value=_pf["presupuesto_max"], step=10_000_000)

            st.markdown("##### Experiencia del Oferente")
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                valor_acumulado_input = st.number_input("Valor acumulado en contratos similares (3 años, COP)", value=_exp["valor_acumulado"], step=10_000_000)
                valor_individual_input = st.number_input("Valor del contrato individual más alto (COP)", value=_exp["valor_individual_max"], step=10_000_000)
            with col_e2:
                objeto_similar_input = st.text_area("Objetos de contratos similares ejecutados", value=obj_default, height=80)
                codigos_unspsc_input = st.text_input("Códigos UNSPSC (separados por coma)", value=unspsc_default)

            participacion_input = st.slider("Participación mínima en consorcios (%)", 0, 100, _exp["participacion_minima"])

            guardar_perfil_btn = st.form_submit_button("💾 Guardar Perfil Completo", use_container_width=True)

        # Mostrar métricas actuales (solo HTML, sin widgets)
        _pf_actual = st.session_state.perfil_financiero
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{_pf_actual["liquidez"]:.2f}</div><div class="metric-label">Liquidez actual</div></div>', unsafe_allow_html=True)
        with col_m2:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{_pf_actual["endeudamiento"]:.0%}</div><div class="metric-label">Endeudamiento actual</div></div>', unsafe_allow_html=True)
        with col_m3:
            st.markdown(f'<div class="metric-card"><div class="metric-value">${_pf_actual["presupuesto_max"]/1_000_000:.0f}M</div><div class="metric-label">Presupuesto Máx.</div></div>', unsafe_allow_html=True)

        if guardar_perfil_btn:
            st.session_state.perfil_financiero = {"liquidez": liq_input, "endeudamiento": end_input, "presupuesto_max": cap_input}
            st.session_state.experiencia_oferente = {
                "valor_acumulado": valor_acumulado_input,
                "valor_individual_max": valor_individual_input,
                "objeto_similar": objeto_similar_input,
                "codigos_unspsc": codigos_unspsc_input,
                "participacion_minima": participacion_input,
            }
            perfil_actualizado = dict(perfil_cliente)
            perfil_actualizado.update({
                "nombre": nombre_empresa,
                "nit": nit,
                "notificacion": pref_notif,
                "contacto_whatsapp": contacto_wa,
                "contacto_email": contacto_email,
                "fecha_vencimiento_rup": rup_venc,
            })
            from auth import guardar_perfil
            guardar_perfil(cliente_id, perfil_actualizado)
            st.session_state["cliente_activo"]["perfil_json"] = perfil_actualizado
            perfil_cliente.update(perfil_actualizado)
            st.toast("✅ Perfil completo guardado", icon="✅")

    with tab_docs:
        st.markdown("##### Biblioteca de Documentos del Cliente")
        st.caption("Sube los documentos habilitantes. SIACO los indexa para usarlos en análisis de viabilidad.")

        from gestor_documentos import listar_documentos, verificar_vigencia_rup, procesar_documento, TIPOS_DOCUMENTO

        # Indicador RUP
        rup_info = verificar_vigencia_rup(cliente_id)
        if rup_info["tiene_rup"] and rup_info["dias_restantes"] is not None:
            dias_rup = rup_info["dias_restantes"]
            pct = max(0, min(100, int(dias_rup / 365 * 100)))
            color_rup = "#FF4444" if dias_rup < 60 else "#C6F24E"
            st.markdown(f"""
            <div style="background:#141414; border:1px solid #262626; border-radius:10px; padding:12px 16px; margin-bottom:16px;">
                <b style="color:{color_rup};">{'⚠️ RUP próximo a vencer' if dias_rup < 60 else '✅ RUP vigente'}</b>
                — {dias_rup} días restantes (vence: {rup_info.get('fecha_vencimiento','')[:10]})
            </div>
            """, unsafe_allow_html=True)
            st.progress(pct / 100)
        elif not rup_info["tiene_rup"]:
            st.markdown(
                '<div style="background:#F0A50020; border:1px solid #F0A500; border-radius:10px; padding:10px 14px; color:#F0C040;">'
                '⚠️ Sin fecha de vencimiento de RUP registrada. Actualízala en la pestaña de Perfil.</div>',
                unsafe_allow_html=True,
            )

        # Formulario de carga
        with st.form("form_subir_documento"):
            tipo_doc = st.selectbox("Tipo de documento", TIPOS_DOCUMENTO)
            archivo_doc = st.file_uploader("Selecciona PDF o DOCX", type=["pdf", "docx"])
            procesar_btn = st.form_submit_button("📤 Subir y procesar documento")

        _slot_doc = st.empty()

        if procesar_btn and archivo_doc:
            _slot_doc.info(f"Procesando {archivo_doc.name}…")
            resultado = procesar_documento(archivo_doc.read(), archivo_doc.name, cliente_id, tipo_doc)
            if resultado["ok"]:
                st.session_state["doc_resultado"] = ("ok", f"✅ {resultado['chunks']} chunks indexados — {resultado['caracteres']:,} caracteres extraídos")
            else:
                st.session_state["doc_resultado"] = ("error", f"❌ {resultado['error']}")
            _slot_doc.empty()

        _res_doc = st.session_state.get("doc_resultado")
        if _res_doc:
            if _res_doc[0] == "ok":
                _slot_doc.success(_res_doc[1])
            else:
                _slot_doc.error(_res_doc[1])

        # Tabla de documentos
        docs = listar_documentos(cliente_id)
        if docs:
            st.markdown("##### Documentos indexados")
            filas_html = ""
            for d in docs:
                filas_html += f"""
                <tr>
                    <td style="padding:8px 12px; border-bottom:1px solid #262626; color:#C6F24E;">{d['tipo']}</td>
                    <td style="padding:8px 12px; border-bottom:1px solid #262626; color:#F5F5F0;">{d['filename']}</td>
                    <td style="padding:8px 12px; border-bottom:1px solid #262626; color:#9A9A9A;">{d['fecha_subida']}</td>
                    <td style="padding:8px 12px; border-bottom:1px solid #262626; color:#9A9A9A; text-align:center;">{d['chunks']}</td>
                </tr>"""
            st.markdown(f"""
            <div style="background:#141414; border:1px solid #262626; border-radius:10px; overflow:hidden; margin-top:12px;">
            <table style="width:100%; border-collapse:collapse; font-size:0.85rem;">
                <thead><tr style="background:#262626;">
                    <th style="padding:8px 12px; text-align:left; color:#9A9A9A; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em;">Tipo</th>
                    <th style="padding:8px 12px; text-align:left; color:#9A9A9A; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em;">Archivo</th>
                    <th style="padding:8px 12px; text-align:left; color:#9A9A9A; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em;">Fecha</th>
                    <th style="padding:8px 12px; text-align:center; color:#9A9A9A; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em;">Chunks</th>
                </tr></thead>
                <tbody>{filas_html}</tbody>
            </table></div>
            """, unsafe_allow_html=True)
        else:
            st.info("Aún no hay documentos indexados. Sube el primero arriba.")


# ═══════════════════════════════════════════════════════
# PANTALLA 2: BÚSQUEDA SECOP II
# ═══════════════════════════════════════════════════════
elif "Búsqueda" in pantalla:
    st.title("Radar de Oportunidades SECOP II")
    st.caption("Detección inteligente de licitaciones con filtro temporal, búsqueda híbrida y alertas")

    from datetime import timedelta as _td

    FASES_VALIDAS = ["presentación de oferta", "convocatoria abierta", "publicado", "selección abreviada", "convocado", "concurso de méritos"]
    FASES_EXCLUIDAS_UI = ["manifestación de interés", "adjudicado", "desierto", "liquidado", "terminado", "celebrado"]

    with st.form("form_busqueda"):
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        with col_f1:
            fecha_desde = st.text_input("Publicadas desde", "2026-01-01")
        with col_f2:
            valor_minimo_busq = st.number_input("Valor mínimo (COP)", value=5_000_000, step=1_000_000)
        with col_f3:
            max_resultados = st.selectbox("Máx. licitaciones", [20, 50, 100], index=1)
        with col_f4:
            score_umbral = st.slider("Score mínimo alerta", 0, 100, 65, 5)
        buscar = st.form_submit_button("🔍 Buscar Licitaciones", use_container_width=True)

    # Slots persistentes — siempre en DOM, contenido cambia según estado
    _slot_busq1 = st.empty()
    _slot_busq2 = st.empty()
    _slot_progreso = st.empty()
    _slot_barra = st.empty()

    if buscar:
        import requests as _req
        import time as _time
        _slot_busq1.info("📡 Conectando con SECOP II...")
        lics_raw = []
        for _intento in range(3):
            try:
                url = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
                params = {
                    "$where": f"fecha_de_publicacion > '{fecha_desde}T00:00:00' AND estado_del_procedimiento = 'Publicado'",
                    "$limit": str(max_resultados),
                    "$order": "fecha_de_publicacion DESC",
                }
                resp = _req.get(url, params=params, timeout=30)
                _parsed = resp.json()
                # La API a veces devuelve dict de error en lugar de lista
                if isinstance(_parsed, list):
                    lics_raw = [x for x in _parsed if isinstance(x, dict)]
                else:
                    raise ValueError(f"Respuesta inesperada: {str(_parsed)[:80]}")
                _slot_busq1.empty()
                st.toast(f"{len(lics_raw)} licitaciones obtenidas de SECOP II", icon="📡")
                break
            except Exception:
                if _intento < 2:
                    _slot_busq1.info(f"📡 Reintentando conexión ({_intento + 2}/3)…")
                    _time.sleep(3)
                else:
                    _slot_busq1.error("No se pudo conectar con SECOP II. Intente de nuevo en unos segundos.")

        if lics_raw:
            _slot_busq2.info("🔎 Filtrando y clasificando licitaciones...")

            now = datetime.now()
            vistos = set()
            lics_unicas = []
            for lic in lics_raw:
                if not isinstance(lic, dict):
                    continue
                cod = lic.get("id_del_proceso") or lic.get("referencia_del_proceso", "")
                if cod and cod not in vistos:
                    vistos.add(cod)
                    lics_unicas.append(lic)

            relevantes = []
            desc_contratos = []  # contratos descartados con su razón
            desc_fase = 0
            desc_temporal = 0

            for lic in lics_unicas:
                if not isinstance(lic, dict):
                    continue
                fase_lic = str(lic.get("fase", "")).lower().strip()

                if any(exc in fase_lic for exc in FASES_EXCLUIDAS_UI):
                    desc_contratos.append({"lic": lic, "razon": f"Fase: {fase_lic or 'sin fase'}"})
                    desc_fase += 1
                    continue

                def _dt(campo):
                    s = lic.get(campo, "")
                    if not s:
                        return None
                    try:
                        return datetime.fromisoformat(str(s).replace("Z", "").split("+")[0])
                    except Exception:
                        return None

                dt_manif = _dt("fecha_limite_manifestacion_interes")
                if dt_manif and dt_manif < now + _td(hours=24):
                    horas = max(0, int((dt_manif - now).total_seconds() / 3600))
                    desc_contratos.append({"lic": lic, "razon": f"Manifestación cierra en {horas}h"})
                    desc_temporal += 1
                    continue
                dt_oferta = _dt("fecha_limite_recepcion_ofertas") or _dt("fecha_de_recepcion_de")
                if dt_oferta and dt_oferta < now + _td(hours=48):
                    horas = max(0, int((dt_oferta - now).total_seconds() / 3600))
                    desc_contratos.append({"lic": lic, "razon": f"Oferta cierra en {horas}h"})
                    desc_temporal += 1
                    continue

                try:
                    valor = float(lic.get("precio_base", 0))
                except Exception:
                    valor = 0

                if valor >= valor_minimo_busq:
                    relevantes.append(lic)
                else:
                    desc_contratos.append({"lic": lic, "razon": f"Valor COP {valor:,.0f} < mínimo"})

            # Guardar descartados para mostrar al usuario
            st.session_state["desc_contratos"] = desc_contratos

            _slot_busq2.markdown(f"✅ {len(relevantes)} contratos pasan filtros · {desc_fase} por fase · {desc_temporal} por fecha")
            st.toast(f"{len(relevantes)} relevantes de {len(lics_unicas)} únicos", icon="🔎")

            if relevantes:
                import anthropic as _ant
                _cli = _ant.Anthropic(api_key=_cfg.API_KEY)
                resultados_busqueda = []

                for i, lic in enumerate(relevantes):
                    if not isinstance(lic, dict):
                        continue
                    _slot_progreso.markdown(f"🧠 Analizando con Claude... **{i+1}/{len(relevantes)}** — {lic.get('nombre_del_procedimiento','')[:60]}…")
                    _slot_barra.progress((i + 1) / len(relevantes))

                    codigo = lic.get("id_del_proceso", lic.get("referencia_del_proceso", f"SIN-CODIGO-{i}"))
                    objeto_lic = lic.get("nombre_del_procedimiento", "N/A")
                    valor_lic = lic.get("precio_base", "N/A")
                    entidad_lic = lic.get("entidad", "N/A")
                    desc_lic = lic.get("descripci_n_del_procedimiento", "")[:300]
                    fase_lic_r = lic.get("fase", "N/A")

                    # Calcular días restantes
                    dt_manif2 = None
                    dt_oferta2 = None
                    try:
                        s_m = lic.get("fecha_limite_manifestacion_interes", "")
                        if s_m:
                            dt_manif2 = datetime.fromisoformat(str(s_m).replace("Z","").split("+")[0])
                    except Exception:
                        pass
                    try:
                        s_o = lic.get("fecha_limite_recepcion_ofertas", "") or lic.get("fecha_de_recepcion_de", "")
                        if s_o:
                            dt_oferta2 = datetime.fromisoformat(str(s_o).replace("Z","").split("+")[0])
                    except Exception:
                        pass

                    dias_manif = int((dt_manif2 - now).total_seconds() / 86400) if dt_manif2 else None
                    dias_cierre = int((dt_oferta2 - now).total_seconds() / 86400) if dt_oferta2 else None

                    try:
                        resp_ia = _cli.messages.create(
                            model="claude-sonnet-4-6",
                            max_tokens=250,
                            temperature=0.1,
                            system=(
                                "Eres SIACO, experto en licitaciones SECOP II Colombia. "
                                "Evalúa relevancia para empresas de obras civiles, HVAC y transporte. "
                                "Responde SOLO con JSON sin texto adicional ni bloques markdown. "
                                "Tu respuesta debe empezar con { y terminar con }."
                            ),
                            messages=[{"role": "user", "content": (
                                f"Objeto: {objeto_lic}\nDescripción: {desc_lic}\nValor: COP {valor_lic}\n"
                                f"Entidad: {entidad_lic}\nFase: {fase_lic_r}\n"
                                f'Responde: {{"score": numero_0_a_100, "relevante": true_o_false, '
                                f'"motivo": "explicacion_max_1_linea", "urgente": true_o_false}}'
                            )}],
                        )
                        import re as _re
                        texto_ia = resp_ia.content[0].text.strip()
                        if not texto_ia.startswith("{"):
                            m = _re.search(r"\{.*\}", texto_ia, _re.DOTALL)
                            texto_ia = m.group(0) if m else texto_ia
                        analisis = json.loads(texto_ia)
                    except Exception as e:
                        analisis = {"score": 0, "relevante": False, "motivo": f"Error IA: {str(e)[:80]}", "urgente": False}

                    resultados_busqueda.append({
                        "licitacion": lic,
                        "codigo": codigo,
                        "analisis": analisis,
                        "dias_manif": dias_manif,
                        "dias_cierre": dias_cierre,
                    })

                # NO vaciar slots — dejarlos en estado "éxito" evita insertBefore
                # NO filtrar por score>0 — cuando Claude falla da score=0 y se perdían todos
                resultados_busqueda.sort(key=lambda x: x["analisis"].get("score", 0), reverse=True)
                st.session_state.licitaciones_encontradas = resultados_busqueda
                n_ok = len(resultados_busqueda)
                _slot_progreso.markdown(f"✅ **{n_ok} contratos analizados** — ordenados por relevancia")
                _slot_barra.progress(1.0)
                st.toast(f"✅ {n_ok} contratos listos", icon="✅")

    if st.session_state.licitaciones_encontradas:
        resultados = st.session_state.licitaciones_encontradas
        st.markdown("---")
        st.markdown(f"##### {len(resultados)} Oportunidades Detectadas")

        pref_notif = perfil_cliente.get("notificacion", "whatsapp")
        contacto_wa = perfil_cliente.get("contacto_whatsapp", "")
        contacto_email = perfil_cliente.get("contacto_email", "")

        for idx, r in enumerate(resultados):
            lic = r["licitacion"]
            ans = r["analisis"]
            score = ans.get("score", 0)
            color = "#C6F24E" if score >= 75 else "#F0A500" if score >= 55 else "#F85149"
            urgente = "⚡ URGENTE" if ans.get("urgente") else ""
            dias_m = r.get("dias_manif")
            dias_c = r.get("dias_cierre")

            with st.expander(f"{score}/100  ·  {lic.get('nombre_del_procedimiento','')[:70]}…  {urgente}"):
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    st.markdown(f"**Entidad:** {lic.get('entidad','N/A')}")
                    st.markdown(f"**ID:** `{r['codigo']}`")
                    st.markdown(f"**Fase:** {lic.get('fase','N/A')}")
                    st.markdown(f"**Motivo SIACO:** {ans.get('motivo','N/A')}")
                    if dias_m is not None:
                        st.markdown(f"⏰ **{dias_m}d** para manifestación")
                    if dias_c is not None:
                        st.markdown(f"📅 **{dias_c}d** para cierre de oferta")
                    url_data = lic.get("urlproceso", {})
                    url_final = url_data.get("url") if isinstance(url_data, dict) else url_data
                    if url_final:
                        st.markdown(f"[🔗 Ver en SECOP II]({url_final})")
                with c2:
                    try:
                        valor_fmt = f"$ {float(lic.get('precio_base',0)):,.0f}"
                    except Exception:
                        valor_fmt = str(lic.get('precio_base','N/A'))
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-value" style="font-size:1.5rem; color:{color};">{score}/100</div>
                        <div class="metric-label">Score IA</div>
                    </div>
                    <div class="metric-card" style="margin-top:10px;">
                        <div class="metric-value" style="font-size:1rem;">{valor_fmt}</div>
                        <div class="metric-label">Valor COP</div>
                    </div>
                    """, unsafe_allow_html=True)
                with c3:
                    with st.form(f"form_acc_{idx}_{r['codigo'][:8]}"):
                        _alerta_btn = st.form_submit_button(
                            "📱 Alerta", use_container_width=True,
                            disabled=(score < score_umbral),
                        )
                        _audit_btn  = st.form_submit_button("📂 Auditoría",   use_container_width=True)
                        _exp_btn    = st.form_submit_button("➕ Expediente",   use_container_width=True)

                    if _alerta_btn:
                        from notificador import Notificador
                        notif = Notificador(pref_notif)
                        dias_ref = dias_c if dias_c is not None else 99
                        try:
                            notif.enviar_alerta(lic, score, dias_ref, contacto_wa, contacto_email)
                            st.toast("✅ Alerta enviada", icon="✅")
                        except Exception as e:
                            st.toast(f"Error alerta: {e}", icon="❌")
                    if _audit_btn:
                        st.session_state.licitacion_actual = lic
                        st.session_state.analisis_resultado = None
                        st.toast("Licitación cargada — ve a 📂 Auditoría de Pliego", icon="✅")
                    if _exp_btn:
                        from gestor_expedientes import agregar_expediente
                        res_exp = agregar_expediente(cliente_id, lic, score)
                        st.toast(
                            "✅ Agregado a expedientes" if res_exp.get("ok")
                            else f"⚠️ {res_exp.get('error','No se pudo agregar')}",
                            icon="✅" if res_exp.get("ok") else "⚠️",
                        )

    # ── Sección de descartados — siempre presente, contenido desde session_state ──
    _desc_list = st.session_state.get("desc_contratos", [])
    if _desc_list:
        st.markdown("---")
        with st.expander(f"📋 {len(_desc_list)} contratos descartados — ver los más cercanos al perfil"):
            st.caption("Descartados por fase, fecha o valor. Revisa si alguno aplica para gestionar manualmente.")
            for _d in _desc_list[:5]:
                _dl = _d["lic"]
                try:
                    _dv = f"COP {float(_dl.get('precio_base', 0)):,.0f}"
                except Exception:
                    _dv = str(_dl.get('precio_base', '—'))
                st.markdown(
                    f'<div style="background:#141414; border:1px solid #262626; border-radius:8px; padding:10px 14px; margin-bottom:8px;">'
                    f'<span style="color:#F0A500; font-size:0.8rem; font-weight:600;">⚠ {_d["razon"]}</span><br>'
                    f'<span style="color:#F5F5F0; font-size:0.85rem;">{_dl.get("nombre_del_procedimiento","Sin nombre")[:90]}</span><br>'
                    f'<span style="color:#9A9A9A; font-size:0.78rem;">{_dl.get("entidad","")[:50]} · {_dv} · Fase: {_dl.get("fase","—")}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


# ═══════════════════════════════════════════════════════
# PANTALLA 3: AUDITORÍA DE PLIEGO
# ═══════════════════════════════════════════════════════
elif "Auditoría" in pantalla:
    st.title("Auditoría Jurídica y Financiera del Pliego")
    st.caption("Evaluación normativa con memoria documental del cliente y biblioteca legal local")

    # ── Banner licitación pre-cargada (solo HTML, sin widgets) ──
    lic_precargada = st.session_state.get("licitacion_actual")
    if lic_precargada:
        try:
            _val_lic = f"COP {float(lic_precargada.get('precio_base', 0)):,.0f}"
        except Exception:
            _val_lic = str(lic_precargada.get("precio_base", ""))
        st.markdown(f"""
        <div class="status-bar">
            <span style="color:#C6F24E; font-weight:700;">● Licitación pre-cargada desde búsqueda SECOP II</span><br>
            <b style="color:#F5F5F0;">{lic_precargada.get('nombre_del_procedimiento','')}</b><br>
            {lic_precargada.get('entidad','')} · {_val_lic}
        </div>
        """, unsafe_allow_html=True)

    # ── Inicializar audit_params (solo primera vez por sesión) ──
    if st.session_state.audit_params is None:
        _lic0 = st.session_state.get("licitacion_actual") or {}
        try:
            _val0 = int(float(_lic0.get("precio_base", 450_000_000)))
        except Exception:
            _val0 = 450_000_000
        st.session_state.audit_params = {
            "modalidad": "infraestructura_obra_publica",
            "sector": "salud",
            "entidad": _lic0.get("entidad") or "Alcaldía de Neiva",
            "objeto": _lic0.get("nombre_del_procedimiento") or "Contratación de obras",
            "valor": _val0,
        }

    # ══════════════════════════════════════════════════════════════
    # CARGA DE PLIEGO — FUERA de cualquier form y ANTES de los tabs.
    # El file_uploader devuelve el archivo en cuanto el usuario lo
    # selecciona (sin necesitar submit), por eso podemos procesar
    # el PDF aquí y actualizar audit_params / meta_* ANTES de que
    # cualquier tab o form renderice sus widgets.
    # ══════════════════════════════════════════════════════════════
    st.markdown("##### Pliego de Condiciones (opcional)")
    st.caption("Sube el PDF y presiona **Procesar** — los campos se autocompletarán.")

    # file_uploader DENTRO de form: se procesa solo al hacer submit (evita re-renders mid-Claude)
    with st.form("form_pliego_pdf"):
        archivo_pdf = st.file_uploader(
            "Arrastra el pliego descargado de SECOP II",
            type=["pdf"],
            key="uploader_pliego_p3",
        )
        _procesar_pdf_btn = st.form_submit_button("📋 Procesar pliego", use_container_width=True)

    # Slot persistente — siempre en DOM
    _slot_pdf = st.empty()

    # Mostrar estado del pliego activo
    if st.session_state.get("nombre_pliego"):
        _slot_pdf.success(f"✅ Pliego activo: {st.session_state['nombre_pliego']}")

    if _procesar_pdf_btn and archivo_pdf:
        _bytes_pdf = archivo_pdf.read()
        _slot_pdf.info("Extrayendo texto del PDF…")
        _texto_ext = extraer_texto_pliego(_bytes_pdf)
        st.session_state.texto_pliego = _texto_ext
        st.session_state.nombre_pliego = archivo_pdf.name

        if _texto_ext:
            _slot_pdf.info(f"Analizando pliego con IA… ({len(_texto_ext):,} chars extraídos)")
            _extraidos = {}
            try:
                import anthropic as _ant2
                # timeout=20 en el cliente para no quedarse bloqueado
                _c2 = _ant2.Anthropic(api_key=_cfg.API_KEY, timeout=20.0)
                _r2 = _c2.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=300,
                    temperature=0.0,
                    messages=[{"role": "user", "content": (
                        "Extrae del siguiente texto de pliego de licitación pública colombiana:\n"
                        "1) entidad contratante\n"
                        "2) objeto del contrato (máx. 200 caracteres)\n"
                        "3) valor o presupuesto base en pesos colombianos (número entero)\n\n"
                        f"Texto:\n{_texto_ext[:5000]}\n\n"
                        'Responde SOLO con JSON:\n'
                        '{"entidad": "nombre entidad", "objeto": "descripcion objeto", "valor": numero_entero_o_null}'
                    )}],
                )
                _extraidos = _extraer_json(_r2.content[0].text)
            except Exception:
                # Si Claude falla, el usuario completa los campos manualmente
                pass

            st.session_state["meta_entidad"] = _extraidos.get("entidad") or ""
            st.session_state["meta_objeto"] = _extraidos.get("objeto") or ""
            try:
                st.session_state["meta_valor"] = int(_extraidos["valor"]) if _extraidos.get("valor") else None
            except Exception:
                st.session_state["meta_valor"] = None

            _ap_upd = dict(st.session_state.audit_params)
            if st.session_state["meta_entidad"]:
                _ap_upd["entidad"] = st.session_state["meta_entidad"]
            if st.session_state["meta_objeto"]:
                _ap_upd["objeto"] = st.session_state["meta_objeto"]
            if st.session_state["meta_valor"] is not None:
                _ap_upd["valor"] = st.session_state["meta_valor"]
            st.session_state.audit_params = _ap_upd
            st.session_state.datos_pliego_extraidos = _extraidos

            if _extraidos:
                _slot_pdf.success(f"✅ Pliego procesado — {len(_texto_ext):,} chars · campos autocompletados ↓")
            else:
                _slot_pdf.info(f"✅ Pliego cargado ({len(_texto_ext):,} chars) — completa los campos manualmente.")
        else:
            _slot_pdf.error("No se pudo extraer texto del PDF. Intenta con otro archivo.")

    # Banner de pliego activo (solo HTML)
    _nombre_p = st.session_state.get("nombre_pliego") or ""
    _texto_p  = st.session_state.get("texto_pliego") or ""
    if _nombre_p:
        _dp2 = st.session_state.get("datos_pliego_extraidos") or {}
        _vdp = _dp2.get("valor")
        _vdp_str = f"COP {int(_vdp):,}" if isinstance(_vdp, (int, float)) else "—"
        st.markdown(f"""
        <div style="background:#141414; border:1px solid #262626; border-radius:10px;
                    padding:10px 16px; font-size:0.82rem; color:#9A9A9A; margin:8px 0 4px;">
            <b style="color:#C6F24E;">✅ Pliego activo:</b> {_nombre_p}
            &nbsp;·&nbsp; <b style="color:#F5F5F0;">{len(_texto_p):,} chars</b>
            &nbsp;·&nbsp; <span style="color:#C6F24E;">Entidad:</span> {_dp2.get('entidad','—')}
            &nbsp;·&nbsp; <span style="color:#C6F24E;">Valor:</span> {_vdp_str}
        </div>
        """, unsafe_allow_html=True)

    # Re-leer _ap — puede haber sido actualizado por el procesamiento del pliego
    _ap = st.session_state.audit_params
    _MODALIDADES = ["infraestructura_obra_publica", "infraestructura_menor_cuantia", "infraestructura_minima_cuantia"]
    _SECTORES    = ["salud", "deporte", "educacion", "vivienda", "institucional"]

    st.markdown("---")
    st.markdown("##### Parámetros y lanzamiento de auditoría")

    _mod_idx = _MODALIDADES.index(_ap["modalidad"]) if _ap["modalidad"] in _MODALIDADES else 0
    _sec_idx = _SECTORES.index(_ap["sector"]) if _ap["sector"] in _SECTORES else 0
    _ent_val = st.session_state.get("meta_entidad") or _ap["entidad"]
    _obj_val = st.session_state.get("meta_objeto") or _ap["objeto"]
    _val_val = (
        st.session_state["meta_valor"]
        if st.session_state.get("meta_valor") is not None
        else int(_ap["valor"])
    )

    with st.form("form_auditoria_p3"):
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            modalidad_sel = st.selectbox("Modalidad Contractual", _MODALIDADES, index=_mod_idx)
        with col_m2:
            sector_sel = st.selectbox("Sector Técnico", _SECTORES, index=_sec_idx)
        entidad_f = st.text_input("Entidad Contratante", value=_ent_val)
        objeto_f  = st.text_input("Objeto del Proceso",  value=_obj_val)
        valor_f   = st.number_input(
            "Presupuesto Base (COP)", value=_val_val, step=10_000_000, min_value=0
        )
        st.caption(
            f"Pliego: {'✅ ' + _nombre_p if _nombre_p else '⚠️ Sin pliego — solo biblioteca normativa'}"
        )
        activar_auditoria = st.form_submit_button(
            "🚀 Iniciar Auditoría Jurídica e IA", use_container_width=True
        )

    # ══════════════════════════════════════════════════
    # PROCESAMIENTO — fuera de tabs y forms.
    # Corre solo cuando activar_auditoria == True.
    # ══════════════════════════════════════════════════
    _zona_estado = st.empty()

    if activar_auditoria:
        # Guardar valores del form antes de leer — elimina desincronía entre forms
        st.session_state.audit_params = {
            "modalidad": modalidad_sel,
            "sector":    sector_sel,
            "entidad":   entidad_f,
            "objeto":    objeto_f,
            "valor":     int(valor_f),
        }
        for _mk in ("meta_entidad", "meta_objeto", "meta_valor"):
            st.session_state.pop(_mk, None)

        _p = st.session_state.audit_params
        licitacion_actual = {
            "nombre_del_procedimiento": _p["objeto"],
            "entidad":    _p["entidad"],
            "precio_base": _p["valor"],
            "modalidad":  _p["modalidad"],
        }
        st.session_state.licitacion_actual = licitacion_actual
        st.session_state.auditoria_error   = None

        perfil = st.session_state.perfil_financiero
        exp    = st.session_state.experiencia_oferente
        cliente_analisis = {
            "nombre":     perfil_cliente.get("nombre", "Cliente SIACO"),
            "id_cliente": cliente_id,
            "sector":     "Obras Civiles",
            "rup":        {"estado_rup": "Activo"},
            "sectores_clave":           ["obras", "construccion", _p["sector"]],
            "codigos_unspsc_permitidos": ["7210"],
            "financiero": {
                "presupuesto_maximo_contrato": perfil["presupuesto_max"],
                "indice_liquidez":             perfil["liquidez"],
                "indice_endeudamiento":        perfil["endeudamiento"],
            },
            "experiencia": {
                "valor_acumulado":      exp["valor_acumulado"],
                "valor_individual_max": exp["valor_individual_max"],
                "objeto_similar":       exp["objeto_similar"],
                "codigos_unspsc":       exp["codigos_unspsc"],
                "participacion_minima": exp["participacion_minima"],
            },
        }

        try:
            resultado = analizar_cliente_vs_licitacion_paralelo(
                licitacion_actual, cliente_analisis, _p["modalidad"], _p["sector"],
                texto_pliego=st.session_state.texto_pliego,
                cliente_id=cliente_id,
            )
            st.session_state.analisis_resultado  = resultado
            st.session_state.caracteres_leidos   = 987_218
            st.session_state.auditoria_estado    = "ok"
            _pid = f"AUDITORIA-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            guardar_analisis_historial(cliente_id, resultado, _pid)
        except json.JSONDecodeError as e:
            st.session_state.auditoria_estado = "error_json"
            st.session_state.auditoria_error  = str(e)
        except Exception as e:
            st.session_state.auditoria_estado = "error"
            st.session_state.auditoria_error  = str(e)

    _estado = st.session_state.get("auditoria_estado", "idle")
    if _estado == "ok":
        _zona_estado.markdown("""<div style="background:#16210A; border:1px solid #C6F24E; border-radius:10px; padding:14px 18px; font-size:0.9rem; color:#F5F5F0; margin-top:12px;">✅ <b>Análisis consolidado</b> — Ve a <b>📊 Cuadro de Control</b> para ver el dictamen.</div>""", unsafe_allow_html=True)
    elif _estado == "error_json":
        _zona_estado.markdown(f"""<div style="background:#3B0D0D; border:1px solid #F85149; border-radius:10px; padding:14px 18px; font-size:0.9rem; color:#F5F5F0; margin-top:12px;">❌ <b>Claude devolvió una respuesta no válida.</b> Intenta de nuevo.<br><span style="color:#9A9A9A; font-size:0.78rem;">{st.session_state.get('auditoria_error','')[:200]}</span></div>""", unsafe_allow_html=True)
    elif _estado == "error":
        _zona_estado.markdown(f"""<div style="background:#3B0D0D; border:1px solid #F85149; border-radius:10px; padding:14px 18px; font-size:0.9rem; color:#F5F5F0; margin-top:12px;">❌ <b>Error:</b> {st.session_state.get('auditoria_error','')[:200]}</div>""", unsafe_allow_html=True)
    else:
        _zona_estado.markdown("""<div style="background:#141414; border:1px solid #262626; border-radius:10px; padding:14px 18px; font-size:0.82rem; color:#9A9A9A; margin-top:12px;">💡 Completa o ajusta los campos y presiona <b>🚀 Iniciar Auditoría Jurídica e IA</b> para comenzar el análisis.</div>""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════
# PANTALLA 4: CUADRO DE CONTROL + PDF MEJORADO
# ═══════════════════════════════════════════════════════
elif "Cuadro de Control" in pantalla:
    st.title("Dictamen de Viabilidad Contractual")
    st.caption("Resultado del análisis multi-agente con scores financiero y jurídico")

    if st.session_state.analisis_resultado is None:
        st.warning("⚠️ No hay análisis en memoria. Ve a **📂 Auditoría de Pliego** y presiona 'Iniciar Auditoría'.")
    else:
        res = st.session_state.analisis_resultado
        score_fin = res.get("score", 0)
        score_jur = res.get("score_juridico", 0)
        viable = res.get("viable", False)
        accion = res.get("accion", "REVISAR")
        motivo = res.get("motivo", "No disponible")
        concepto_fin = res.get("concepto_financiero", "")
        concepto_jur = res.get("concepto_juridico", "")

        color_fin = "#C6F24E" if score_fin >= 70 else "#F0A500" if score_fin >= 40 else "#F85149"
        color_jur = "#C6F24E" if score_jur >= 70 else "#F0A500" if score_jur >= 40 else "#F85149"
        icon_accion = "🟢" if accion == "PRESENTAR" else "🟡" if accion == "REVISAR" else "🔴"

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f'<div class="metric-card"><div class="metric-value" style="color:{color_fin};">{score_fin}/100</div><div class="metric-label">Score Financiero</div></div>', unsafe_allow_html=True)
            st.progress(min(score_fin, 100) / 100)
        with c2:
            st.markdown(f'<div class="metric-card"><div class="metric-value" style="color:{color_jur};">{score_jur}/100</div><div class="metric-label">Score Jurídico</div></div>', unsafe_allow_html=True)
            st.progress(min(score_jur, 100) / 100)
        with c3:
            st.markdown(f'<div class="metric-card"><div class="metric-value" style="font-size:1.4rem; color:{color_fin};">{icon_accion} {accion}</div><div class="metric-label">Decisión Estratégica</div></div>', unsafe_allow_html=True)
        with c4:
            st.markdown(f'<div class="metric-card"><div class="metric-value" style="font-size:1.2rem;">{st.session_state.caracteres_leidos:,}</div><div class="metric-label">Caracteres Legales</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("##### Dictamen Integral")
        css_class = "veredicto-viable" if viable else "veredicto-riesgo"
        titulo_dictamen = "✅ PROCESO CON ALTA FACTIBILIDAD HABILITANTE" if viable else "⚠️ COMPATIBILIDAD BAJA / RIESGO DETECTADO"
        st.markdown(f'<div class="veredicto-box {css_class}"><b>{titulo_dictamen}</b><br><br>{motivo}</div>', unsafe_allow_html=True)

        # Detalle financiero y jurídico
        if concepto_fin or concepto_jur:
            col_df, col_dj = st.columns(2)
            with col_df:
                if concepto_fin:
                    st.markdown(f"**Concepto Financiero:** {concepto_fin}")
                for razon in res.get("razones_financiero", [])[:3]:
                    st.markdown(f"• {razon}")
            with col_dj:
                if concepto_jur:
                    st.markdown(f"**Concepto Jurídico:** {concepto_jur}")
                for riesgo in res.get("riesgos_juridicos", [])[:3]:
                    st.markdown(f"• {riesgo}")

        st.markdown("---")
        st.markdown("##### Simulador de Consorcio / Unión Temporal")

        _slot_consorcio = st.empty()

        with st.form("form_consorcio"):
            consorcio_check = st.checkbox("🤝 Simular con aliado (Consorcio / Unión Temporal)")
            col_a, col_b = st.columns(2)
            with col_a:
                liq_aliado = st.number_input("Liquidez del aliado", value=1.6, step=0.1, min_value=0.0)
            with col_b:
                cap_aliado = st.number_input("Capital adicional del aliado (COP)", value=200_000_000, step=10_000_000)
            calcular_consorcio = st.form_submit_button("Calcular impacto consorcio")

        if calcular_consorcio and consorcio_check:
            perfil = st.session_state.perfil_financiero
            liq_combinada = (perfil["liquidez"] + liq_aliado) / 2
            cap_combinado = perfil["presupuesto_max"] + cap_aliado
            score_ajustado = min(100, score_fin + 12)
            st.session_state["consorcio_resultado"] = f"""
            <div class="metric-card" style="text-align:left; padding:16px 20px; margin-top:10px;">
                <div class="metric-value" style="font-size:1.8rem;">{score_ajustado}/100</div>
                <div style="font-size:0.82rem; color:#9A9A9A; margin-top:8px;">
                    Liquidez combinada: <b style="color:#F5F5F0;">{liq_combinada:.2f}</b><br>
                    Capacidad combinada: <b style="color:#F5F5F0;">${cap_combinado/1_000_000:.0f}M COP</b><br>
                    <span style="color:#C6F24E;">▲ Mejora de {score_ajustado - score_fin} puntos</span>
                </div>
            </div>"""

        if st.session_state.get("consorcio_resultado"):
            _slot_consorcio.markdown(st.session_state["consorcio_resultado"], unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("##### Matriz de Cumplimiento Financiero")

        def render_matriz(items):
            if not items:
                st.info("Sin datos estructurados disponibles.")
                return
            filas_html = ""
            for item in items:
                cumple = item.get("cumple", False)
                icono = "🟢" if cumple else "🔴"
                obs = item.get("observacion", item.get("norma", ""))
                filas_html += f"""
                <tr>
                    <td style="padding:10px 14px; border-bottom:1px solid #262626; color:#FFFFFF;">{item.get('requisito','—')}</td>
                    <td style="padding:10px 14px; border-bottom:1px solid #262626; color:#9A9A9A;">{item.get('valor_pliego', item.get('exigido','—'))}</td>
                    <td style="padding:10px 14px; border-bottom:1px solid #262626; color:#F5F5F0;">{item.get('valor_empresa', item.get('cliente_tiene','—'))}</td>
                    <td style="padding:10px 14px; border-bottom:1px solid #262626; text-align:center;">{icono}</td>
                    <td style="padding:10px 14px; border-bottom:1px solid #262626; color:#9A9A9A; font-size:0.8rem;">{obs}</td>
                </tr>"""
            st.markdown(f"""
            <div style="background:#141414; border:1px solid #262626; border-radius:10px; overflow:hidden;">
            <table style="width:100%; border-collapse:collapse; font-size:0.85rem;">
                <thead><tr style="background:#262626;">
                    <th style="padding:10px 14px; text-align:left; color:#9A9A9A; text-transform:uppercase; font-size:0.72rem; letter-spacing:0.05em;">Requisito</th>
                    <th style="padding:10px 14px; text-align:left; color:#9A9A9A; text-transform:uppercase; font-size:0.72rem; letter-spacing:0.05em;">Exigido (Pliego)</th>
                    <th style="padding:10px 14px; text-align:left; color:#9A9A9A; text-transform:uppercase; font-size:0.72rem; letter-spacing:0.05em;">Cliente Tiene</th>
                    <th style="padding:10px 14px; text-align:center; color:#9A9A9A; text-transform:uppercase; font-size:0.72rem; letter-spacing:0.05em;">Cumple</th>
                    <th style="padding:10px 14px; text-align:left; color:#9A9A9A; text-transform:uppercase; font-size:0.72rem; letter-spacing:0.05em;">Observación</th>
                </tr></thead>
                <tbody>{filas_html}</tbody>
            </table></div>
            """, unsafe_allow_html=True)

        render_matriz(res.get("checklist_financiero", []))
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("##### Matriz de Experiencia Habilitante")
        render_matriz(res.get("matriz_experiencia", []))

        # Documentos faltantes y recomendaciones
        docs_falt = res.get("documentos_faltantes", res.get("pdf_documentos", []))
        recomend = res.get("recomendaciones", [])
        if docs_falt or recomend:
            col_df2, col_rec = st.columns(2)
            with col_df2:
                if docs_falt:
                    st.markdown("##### Documentos Faltantes")
                    for d in docs_falt:
                        st.markdown(f"❌ {d}")
            with col_rec:
                if recomend:
                    st.markdown("##### Recomendaciones Estratégicas")
                    for i, r_item in enumerate(recomend, 1):
                        st.markdown(f"**{i}.** {r_item}")

        st.markdown("---")
        st.markdown("##### Registro de Resultado")
        with st.form("form_resultado_lic"):
            proceso_id_reg = st.text_input("ID del proceso", value=st.session_state.licitacion_actual.get("id_del_proceso", "") if st.session_state.licitacion_actual else "")
            resultado_reg = st.selectbox("Resultado real", ["Pendiente", "GANADO", "PERDIDO", "DESISTIDO"])
            lecciones_reg = st.text_area("Lecciones aprendidas (una por línea)")
            guardar_btn = st.form_submit_button("💾 Registrar resultado")
        if guardar_btn and proceso_id_reg and resultado_reg != "Pendiente":
            lec_lista = [l.strip() for l in lecciones_reg.strip().split("\n") if l.strip()]
            actualizar_resultado(cliente_id, proceso_id_reg, resultado_reg, lec_lista)
            st.toast("✅ Resultado registrado en historial", icon="✅")

        st.markdown("---")
        st.markdown("##### Documentación Ejecutiva")

        def generar_pdf_bytes(datos_reporte):
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib import colors
            from reportlab.graphics.shapes import Drawing, Rect, String as RLString
            from reportlab.graphics.charts.barcharts import HorizontalBarChart
            from reportlab.graphics import renderPDF
            import io

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter,
                                    rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
            story = []
            styles = getSampleStyleSheet()
            def S(name, **kw):
                return ParagraphStyle(name, parent=styles["Normal"], **kw)

            title_s = S("T", fontSize=20, textColor=colors.HexColor("#003366"), spaceAfter=6, fontName="Helvetica-Bold")
            h2_s = S("H2", fontSize=13, textColor=colors.HexColor("#00A37A"), spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold")
            h3_s = S("H3", fontSize=11, textColor=colors.HexColor("#333333"), spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold")
            body_s = S("B", fontSize=10, leading=14, spaceAfter=6)
            cell_s = S("C", fontSize=8, leading=10)
            cell_h_s = S("CH", fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold")
            small_s = S("SM", fontSize=8, textColor=colors.HexColor("#555555"), leading=10)

            det = datos_reporte.get("detalles_licitacion", {})
            nombre_cli = det.get("cliente", "Cliente")
            score_f = datos_reporte.get("score", 0)
            score_j = datos_reporte.get("score_juridico", 0)

            # 1. PORTADA
            story.append(Paragraph("◈  SIACO v3.0", S("logo", fontSize=18, textColor=colors.HexColor("#003366"), fontName="Helvetica-Bold")))
            story.append(Paragraph("Sistema Inteligente de Análisis de Contratación Pública", small_s))
            story.append(Spacer(1, 20))
            story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#00A37A")))
            story.append(Spacer(1, 10))
            story.append(Paragraph(f"Reporte de Viabilidad Contractual", title_s))
            story.append(Paragraph(f"<b>Empresa:</b> {nombre_cli}", body_s))
            story.append(Paragraph(f"<b>Entidad:</b> {det.get('entidad','—')}", body_s))
            story.append(Paragraph(f"<b>Proceso:</b> {det.get('objeto','—')}", body_s))
            story.append(Paragraph(f"<b>Fecha:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}", body_s))
            story.append(Spacer(1, 20))

            # 2. RESUMEN EJECUTIVO
            story.append(Paragraph("1. Resumen Ejecutivo", h2_s))
            story.append(Paragraph(f"<b>Decisión estratégica:</b> {datos_reporte.get('accion','—')} | Concepto Financiero: {datos_reporte.get('concepto_financiero','—')} | Concepto Jurídico: {datos_reporte.get('concepto_juridico','—')}", body_s))

            # Gráfico de barras scores
            try:
                drawing = Drawing(400, 80)
                bc = HorizontalBarChart()
                bc.x = 80; bc.y = 5; bc.height = 60; bc.width = 300
                bc.data = [[score_f, score_j]]
                bc.categoryAxis.categoryNames = ["Score Jurídico", "Score Financiero"]
                bc.bars[0].fillColor = colors.HexColor("#00A37A")
                bc.valueAxis.valueMin = 0; bc.valueAxis.valueMax = 100
                drawing.add(bc)
                story.append(drawing)
            except Exception:
                story.append(Paragraph(f"Score Financiero: {score_f}/100 | Score Jurídico: {score_j}/100", body_s))

            story.append(Spacer(1, 10))

            # 3. TABLA COMPARATIVA
            story.append(Paragraph("2. Tabla Comparativa de Requisitos", h2_s))
            req_items = datos_reporte.get("requisitos_habilitantes", datos_reporte.get("checklist_financiero", []))
            if req_items:
                t_data = [[
                    Paragraph("Requisito", cell_h_s),
                    Paragraph("Exigido", cell_h_s),
                    Paragraph("Cliente tiene", cell_h_s),
                    Paragraph("Cumple", cell_h_s),
                    Paragraph("Observación", cell_h_s),
                ]]
                for item in req_items:
                    cumple_str = "✅ Sí" if item.get("cumple") else "❌ No"
                    t_data.append([
                        Paragraph(str(item.get("requisito", "—")), cell_s),
                        Paragraph(str(item.get("exigido", item.get("valor_pliego","—"))), cell_s),
                        Paragraph(str(item.get("cliente_tiene", item.get("valor_empresa","—"))), cell_s),
                        Paragraph(cumple_str, cell_s),
                        Paragraph(str(item.get("norma", item.get("observacion",""))), cell_s),
                    ])
                t = Table(t_data, colWidths=[100, 90, 90, 50, 90], repeatRows=1)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00A37A")),
                    ("ALIGN", (0,0), (-1,-1), "LEFT"),
                    ("VALIGN", (0,0), (-1,-1), "TOP"),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
                    ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#dee2e6")),
                    ("TOPPADDING", (0,0), (-1,-1), 4),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                    ("LEFTPADDING", (0,0), (-1,-1), 5),
                    ("RIGHTPADDING", (0,0), (-1,-1), 5),
                ]))
                story.append(t)
            story.append(Spacer(1, 12))

            # 4. ANÁLISIS FINANCIERO
            story.append(Paragraph("3. Análisis Financiero Detallado", h2_s))
            story.append(Paragraph(f"<b>Score:</b> {score_f}/100 — <b>Concepto:</b> {datos_reporte.get('concepto_financiero','—')}", body_s))
            for art in datos_reporte.get("articulos_aplicables", [])[:5]:
                story.append(Paragraph(f"• {art}", body_s))
            idx_eval = datos_reporte.get("indices_evaluados", {})
            if idx_eval:
                story.append(Paragraph(f"<b>Índices evaluados:</b> Liquidez={idx_eval.get('liquidez','N/A')} | Endeudamiento={idx_eval.get('endeudamiento','N/A')} | Capital de trabajo={idx_eval.get('capital_trabajo','N/A')}", small_s))
            story.append(Spacer(1, 8))

            # 5. ANÁLISIS JURÍDICO
            story.append(Paragraph("4. Análisis Jurídico Detallado", h2_s))
            story.append(Paragraph(f"<b>Score:</b> {score_j}/100 — <b>Concepto:</b> {datos_reporte.get('concepto_juridico','—')}", body_s))
            argumentos = datos_reporte.get("pdf_argumentos", "")
            if argumentos:
                story.append(Paragraph(argumentos[:800], body_s))
            for riesgo in datos_reporte.get("riesgos_juridicos", [])[:5]:
                story.append(Paragraph(f"⚠️ {riesgo}", small_s))
            story.append(Spacer(1, 8))

            # 6. MATRIZ EXPERIENCIA
            story.append(Paragraph("5. Matriz de Experiencia Habilitante", h2_s))
            exp_items = datos_reporte.get("matriz_experiencia", [])
            if exp_items:
                t2_data = [[
                    Paragraph("Requisito", cell_h_s),
                    Paragraph("Exigido (Pliego)", cell_h_s),
                    Paragraph("Empresa", cell_h_s),
                    Paragraph("Cumple", cell_h_s),
                ]]
                for item in exp_items:
                    t2_data.append([
                        Paragraph(str(item.get("requisito","—")), cell_s),
                        Paragraph(str(item.get("valor_pliego","—")), cell_s),
                        Paragraph(str(item.get("valor_empresa","—")), cell_s),
                        Paragraph("Sí" if item.get("cumple") else "No", cell_s),
                    ])
                t2 = Table(t2_data, colWidths=[140, 130, 150, 50], repeatRows=1)
                t2.setStyle(TableStyle([
                    ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#00A37A")),
                    ("ALIGN", (0,0), (-1,-1), "LEFT"),
                    ("VALIGN", (0,0), (-1,-1), "TOP"),
                    ("BACKGROUND", (0,1), (-1,-1), colors.HexColor("#f8f9fa")),
                    ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#dee2e6")),
                    ("TOPPADDING", (0,0), (-1,-1), 4),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                    ("LEFTPADDING", (0,0), (-1,-1), 5),
                    ("RIGHTPADDING", (0,0), (-1,-1), 5),
                ]))
                story.append(t2)
            story.append(Spacer(1, 12))

            # 7. CHECKLIST DOCUMENTOS FALTANTES
            docs_f = datos_reporte.get("documentos_faltantes", datos_reporte.get("pdf_documentos", []))
            if docs_f:
                story.append(Paragraph("6. Checklist de Documentos Faltantes", h2_s))
                for d in docs_f:
                    story.append(Paragraph(f"❌ {d}", body_s))
                story.append(Spacer(1, 8))

            # 8. RECOMENDACIONES ESTRATÉGICAS
            recomend_list = datos_reporte.get("recomendaciones", [])
            if recomend_list:
                story.append(Paragraph("7. Recomendaciones Estratégicas Priorizadas", h2_s))
                for i, r_item in enumerate(recomend_list, 1):
                    story.append(Paragraph(f"<b>{i}.</b> {r_item}", body_s))

            doc.build(story)
            buffer.seek(0)
            return buffer.getvalue()

        _slot_pdf_dl = st.empty()

        try:
            pdf_data = generar_pdf_bytes(res)
            Path("./reportes").mkdir(exist_ok=True)
            det_pdf = res.get("detalles_licitacion", {})
            nombre_emp = det_pdf.get("cliente", "SIACO").replace(" ", "_")[:20]
            proceso_pdf = st.session_state.licitacion_actual.get("id_del_proceso", "PROCESO") if st.session_state.licitacion_actual else "PROCESO"
            fecha_hoy = datetime.now().strftime("%Y-%m-%d")
            nombre_pdf = f"{nombre_emp}_{proceso_pdf}_{fecha_hoy}.pdf"
            ruta_pdf = Path(f"./reportes/{nombre_pdf}")
            ruta_pdf.write_bytes(pdf_data)
            st.session_state["pdf_resultado"] = {"data": pdf_data, "nombre": nombre_pdf}
        except Exception as e:
            st.toast(f"No se pudo generar el PDF: {str(e)}", icon="❌")

        if st.session_state.get("pdf_resultado"):
            _pr = st.session_state["pdf_resultado"]
            _slot_pdf_dl.download_button(
                label="📥 Descargar Reporte Ejecutivo (PDF)",
                data=_pr["data"],
                file_name=_pr["nombre"],
                mime="application/pdf",
                use_container_width=True,
            )


# ═══════════════════════════════════════════════════════
# PANTALLA 5: INTELIGENCIA COMPETITIVA
# ═══════════════════════════════════════════════════════
elif "Inteligencia Competitiva" in pantalla:
    st.title("Inteligencia Competitiva")
    st.caption("Análisis de ofertas de competidores y generación de estrategia de oferta")

    from competidor import extraer_datos_oferta, actualizar_inteligencia_competitiva, cargar_inteligencia_competidor, listar_competidores_proceso, generar_estrategia_oferta

    lic_actual = st.session_state.get("licitacion_actual")
    proceso_id_comp = lic_actual.get("id_del_proceso", "PROCESO-ACTUAL") if lic_actual else "PROCESO-SIN-SELECCION"

    if not lic_actual:
        st.info("ℹ️ Selecciona una licitación en **🔍 Búsqueda SECOP II** para analizar sus competidores.")

    st.markdown(f"**Proceso activo:** `{proceso_id_comp}`")
    st.markdown("---")

    with st.form("form_competidores"):
        st.markdown("##### Cargar ofertas de competidores")
        archivos_comp = st.file_uploader("Subir PDFs de ofertas (múltiples)", type=["pdf"], accept_multiple_files=True)
        nits_text = st.text_area("NITs de competidores (uno por línea, en el mismo orden que los PDFs)")
        subir_comp_btn = st.form_submit_button("🔍 Analizar Ofertas")

    if subir_comp_btn and archivos_comp:
        nits_lista = [n.strip() for n in nits_text.strip().split("\n") if n.strip()]
        _slot_comp = st.empty()
        _resumen_comp = []
        for i, archivo_c in enumerate(archivos_comp):
            nit_c = nits_lista[i] if i < len(nits_lista) else f"NIT-{i+1}"
            _slot_comp.info(f"Analizando oferta NIT {nit_c} ({i+1}/{len(archivos_comp)})…")
            resultado_c = extraer_datos_oferta(archivo_c.read(), proceso_id_comp, nit_c)
            if resultado_c.get("ok"):
                actualizar_inteligencia_competitiva(nit_c, resultado_c["datos"])
                _resumen_comp.append(f"✅ {nit_c}")
            else:
                _resumen_comp.append(f"❌ {nit_c}: {resultado_c.get('error','Error')}")
        _slot_comp.success("Procesamiento completo: " + " | ".join(_resumen_comp))

    competidores_proceso = listar_competidores_proceso(proceso_id_comp)
    if competidores_proceso:
        st.markdown("---")
        st.markdown(f"##### {len(competidores_proceso)} Competidores analizados en este proceso")
        for comp in competidores_proceso:
            nit_c = comp.get("nit", "N/A")
            with st.expander(f"NIT: {nit_c}"):
                col_c1, col_c2 = st.columns(2)
                with col_c1:
                    precio_ofert = comp.get("precio_ofertado")
                    if precio_ofert:
                        try:
                            st.markdown(f"**Precio ofertado:** ${float(precio_ofert):,.0f} COP")
                        except Exception:
                            st.markdown(f"**Precio ofertado:** {precio_ofert}")
                    st.markdown(f"**Experiencia declarada:** {comp.get('experiencia_declarada','N/A')}")
                with col_c2:
                    st.markdown(f"**Metodología:** {comp.get('metodologia','N/A')}")
                    certs = comp.get("certificaciones", [])
                    if certs:
                        st.markdown(f"**Certificaciones:** {', '.join(certs[:3])}")

                # Perfil histórico si existe
                perfil_hist = cargar_inteligencia_competidor(nit_c)
                if perfil_hist and perfil_hist.get("historial_precios"):
                    rango = perfil_hist.get("rango_precios", {})
                    st.markdown(f"📊 **Historial:** Min={rango.get('min','?')} | Prom={rango.get('promedio','?')} | Max={rango.get('max','?')}")
                    st.markdown(f"🏆 Ganados: {perfil_hist.get('procesos_ganados',0)} | Perdidos: {perfil_hist.get('procesos_perdidos',0)}")

        st.markdown("---")
        with st.form("form_estrategia_comp"):
            estrategia_btn = st.form_submit_button("⚡ Generar Estrategia de Oferta", use_container_width=True)

        if estrategia_btn:
            comp_input = [{"nit": c.get("nit","")} for c in competidores_proceso]
            _slot_est = st.empty()
            _slot_est.info("Generando estrategia con Claude…")
            estrategia = generar_estrategia_oferta(cliente_id, proceso_id_comp, comp_input)
            _slot_est.empty()
            st.session_state["estrategia_competitiva"] = estrategia

        estrategia = st.session_state.get("estrategia_competitiva")
        if estrategia:
            if "error" in estrategia:
                st.markdown(
                    f'<div style="background:#F0A50020; border:1px solid #F0A500; border-radius:10px; padding:10px 14px; color:#F0C040;">'
                    f'⚠️ Error al generar estrategia: {estrategia["error"]}</div>',
                    unsafe_allow_html=True,
                )
            else:
                precio_sug = estrategia.get("precio_sugerido")
                if precio_sug:
                    try:
                        st.markdown(f"💰 **Precio sugerido:** ${float(precio_sug):,.0f} COP")
                    except Exception:
                        st.markdown(f"💰 **Precio sugerido:** {precio_sug}")
                fortalezas = estrategia.get("fortalezas_a_destacar", [])
                advertencias = estrategia.get("advertencias", [])
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    st.markdown("**Fortalezas a destacar:**")
                    for f_item in fortalezas:
                        st.markdown(f"✅ {f_item}")
                with col_e2:
                    st.markdown("**Advertencias:**")
                    for adv in advertencias:
                        st.markdown(f"⚠️ {adv}")
                template = estrategia.get("template_oferta_estructura", "")
                if template:
                    st.markdown("**Estructura de oferta sugerida:**")
                    st.info(template)
    else:
        st.info("Aún no hay ofertas analizadas para este proceso. Sube los PDFs arriba.")


# ═══════════════════════════════════════════════════════
# PANTALLA 6: GESTIÓN DE EXPEDIENTES
# ═══════════════════════════════════════════════════════
elif "Expedientes" in pantalla:
    st.title("Gestión de Expedientes")
    st.caption("Seguimiento de procesos con alertas de urgencia y control de estados")

    from gestor_expedientes import listar_expedientes, actualizar_estado, ESTADOS_INTERNOS

    expedientes_all = listar_expedientes(cliente_id)

    # Alertas rojas al tope
    rojos = [e for e in expedientes_all if e["urgencia"]["nivel"] == "rojo"]
    if rojos:
        _items_html = "".join(f"<li>{r_item['nombre'][:60]} — {r_item['entidad']}</li>" for r_item in rojos)
        st.markdown(
            f'<div style="background:#FF000018; border:1px solid #FF4444; border-radius:10px; padding:12px 16px; margin-bottom:12px; color:#FF7777;">'
            f'🚨 <b>{len(rojos)} proceso(s) con cierre en menos de 24 horas</b> — prepara documentación de inmediato!<ul style="margin:6px 0 0 16px; color:#FF9999;">{_items_html}</ul></div>',
            unsafe_allow_html=True,
        )

    # Filtros
    with st.form("form_filtros_expedientes"):
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            estados_disponibles = ["Todos"] + ESTADOS_INTERNOS
            filtro_estado_exp = st.selectbox("Filtrar por estado interno", estados_disponibles)
        with col_f2:
            filtro_urgencia = st.selectbox("Filtrar por urgencia", ["Todos", "🔴 Rojo", "🟡 Amarillo", "🟢 Verde"])
        aplicar_filtro = st.form_submit_button("Aplicar Filtros")

    expedientes_filtrados = expedientes_all
    if aplicar_filtro or True:
        if filtro_estado_exp != "Todos":
            expedientes_filtrados = [e for e in expedientes_filtrados if e.get("estado_interno") == filtro_estado_exp]
        if filtro_urgencia != "Todos":
            nivel_map = {"🔴 Rojo": "rojo", "🟡 Amarillo": "amarillo", "🟢 Verde": "verde"}
            nivel_f = nivel_map.get(filtro_urgencia, "")
            if nivel_f:
                expedientes_filtrados = [e for e in expedientes_filtrados if e["urgencia"]["nivel"] == nivel_f]

    if not expedientes_filtrados:
        st.info("No hay expedientes que coincidan con los filtros. Agrega licitaciones desde **🔍 Búsqueda SECOP II**.")
    else:
        st.markdown(f"##### {len(expedientes_filtrados)} Expedientes")
        st.markdown('<p style="font-size:0.78rem; color:#9A9A9A;">📋 Prepare documentación con 24h de anticipación al cierre de oferta</p>', unsafe_allow_html=True)

        for exp_item in expedientes_filtrados:
            urg = exp_item["urgencia"]
            nivel = urg["nivel"]
            color_borde = "#FF4444" if nivel == "rojo" else "#FFB800" if nivel == "amarillo" else "#C6F24E"
            icono_urg = "🔴" if nivel == "rojo" else "🟡" if nivel == "amarillo" else "🟢"

            dias_m = urg.get("dias_manif")
            dias_c = urg.get("dias_cierre")
            str_manif = f"⏰ {dias_m}d manifestación" if dias_m is not None else ""
            str_cierre = f"📅 {dias_c}d cierre oferta" if dias_c is not None else ""

            with st.expander(f"{icono_urg} {exp_item['nombre'][:70]} — {exp_item['entidad'][:30]}"):
                col_i1, col_i2, col_i3 = st.columns([3, 1, 1])
                with col_i1:
                    try:
                        valor_exp = f"${float(exp_item.get('valor',0)):,.0f} COP"
                    except Exception:
                        valor_exp = str(exp_item.get('valor','N/A'))
                    st.markdown(f"**Valor:** {valor_exp}")
                    st.markdown(f"**Fase SECOP:** {exp_item.get('fase_secop','—')}")
                    if str_manif:
                        st.markdown(str_manif)
                    if str_cierre:
                        st.markdown(str_cierre)
                    if exp_item.get("url"):
                        st.markdown(f"[🔗 Ver proceso]({exp_item['url']})")
                with col_i2:
                    score_exp = exp_item.get("score_viabilidad", 0)
                    st.markdown(f'<div class="metric-card"><div class="metric-value" style="font-size:1.3rem; color:{color_borde};">{score_exp}/100</div><div class="metric-label">Score</div></div>', unsafe_allow_html=True)
                with col_i3:
                    with st.form(f"form_est_{exp_item['proceso_id'][:12]}"):
                        nuevo_estado = st.selectbox(
                            "Estado",
                            ESTADOS_INTERNOS,
                            index=ESTADOS_INTERNOS.index(exp_item.get("estado_interno", "En seguimiento"))
                                if exp_item.get("estado_interno") in ESTADOS_INTERNOS else 0,
                        )
                        guardar_est_btn = st.form_submit_button("Guardar", use_container_width=True)
                    if guardar_est_btn:
                        actualizar_estado(cliente_id, exp_item["proceso_id"], nuevo_estado)
                        st.toast("Estado actualizado", icon="✅")

        # Exportar Excel
        st.markdown("---")
        with st.form("form_exportar_excel"):
            exportar_btn = st.form_submit_button("📊 Exportar expedientes a Excel", use_container_width=True)

        _slot_excel_dl = st.empty()

        if exportar_btn:
            try:
                import openpyxl
                from openpyxl.styles import Font, PatternFill
                import io as _io2

                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Expedientes SIACO"
                headers = ["Proceso ID", "Nombre", "Entidad", "Valor COP", "Fase SECOP", "Estado", "Manifestación (días)", "Cierre (días)", "Score", "Urgencia"]
                for col_n, h in enumerate(headers, 1):
                    cell = ws.cell(row=1, column=col_n, value=h)
                    cell.font = Font(bold=True, color="FFFFFF")
                    cell.fill = PatternFill(fill_type="solid", fgColor="00A37A")

                for row_n, e_item in enumerate(expedientes_filtrados, 2):
                    urg_e = e_item.get("urgencia", {})
                    ws.append([
                        e_item.get("proceso_id",""),
                        e_item.get("nombre",""),
                        e_item.get("entidad",""),
                        e_item.get("valor",""),
                        e_item.get("fase_secop",""),
                        e_item.get("estado_interno",""),
                        urg_e.get("dias_manif",""),
                        urg_e.get("dias_cierre",""),
                        e_item.get("score_viabilidad",""),
                        urg_e.get("nivel",""),
                    ])

                buf_xl = _io2.BytesIO()
                wb.save(buf_xl)
                buf_xl.seek(0)
                st.session_state["excel_expedientes"] = buf_xl.getvalue()
            except ImportError:
                st.toast("Instala openpyxl: py -3.13 -m pip install openpyxl", icon="❌")
            except Exception as e:
                st.toast(f"Error generando Excel: {e}", icon="❌")

        if st.session_state.get("excel_expedientes"):
            _slot_excel_dl.download_button(
                label="📥 Descargar Excel",
                data=st.session_state["excel_expedientes"],
                file_name=f"expedientes_siaco_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
