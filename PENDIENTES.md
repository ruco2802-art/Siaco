# SIACO v3.0 — Pendientes

## 🔴 Alta prioridad

### 1. Descarga PDF en SPA web
- `routers/reportes.py` existe y genera el PDF con fpdf2
- El endpoint `POST /api/reportes/pdf` está listo
- **Falta:** botón "Descargar PDF" en `static/app.js` después de terminar la auditoría
- El Streamlit lo tiene con `st.download_button`, la SPA no

### 2. Panel de administración en SPA
- `static/index.html` no tiene pantalla de admin
- El Streamlit tiene panel completo: listar clientes, crear, desactivar, resetear password
- **Falta:** página `page-admin` en HTML + lógica JS + CSS

### 3. WhatsApp real (automático)
- `notificador.py` abre WhatsApp Web en el navegador del servidor — no funciona en producción
- **Opción recomendada:** Twilio WhatsApp API (`pip install twilio`)
- Requiere cuenta Twilio + número sandbox o aprobado
- Variables de entorno: `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_WA_FROM`

---

## 🟡 Media prioridad

### 4. Cuadro de Control / Dictamen en SPA
- La SPA cierra el análisis con un banner de éxito, pero no despliega el dictamen completo
- El Streamlit tiene: scores, matrices, checklist, simulador de consorcio, recomendaciones
- **Falta:** sección de resultados expandida en `page-auditoria` del HTML/JS

### 5. Exportar expedientes a Excel en SPA
- En Streamlit: `openpyxl` genera el Excel y se descarga
- En SPA: el módulo `gestor_expedientes.py` tiene la función pero el endpoint en
  `routers/expedientes.py` no expone `GET /api/expedientes/exportar`
- **Falta:** endpoint Excel + botón de descarga en `page-expedientes`

### 6. Alertas por email desde SPA
- `notificador.py` tiene `enviar_gmail()` funcional con SMTP SSL
- En Streamlit el botón "Alerta" lo llama correctamente
- En SPA: el panel detalle del contrato no tiene botón de enviar alerta
- **Falta:** llamada a `POST /api/contratos/alerta` desde JS (el router no existe aún)

### 7. Router de alertas
- No existe `routers/alertas.py`
- Se puede crear con un endpoint `POST /api/contratos/alerta` que llame a `Notificador`
- Recibe: `{contrato, score, dias_restantes}` + lee preferencias del perfil del cliente

---

## 🟢 Mejoras deseables

### 8. Actualizar requirements.txt
- Verificar que `fpdf2` esté incluido (la SPA usa fpdf2, el Streamlit usa reportlab)
- Agregar `openpyxl` si falta (exportar Excel de expedientes)

### 9. Tests actualizados
- `test_filtro.py`, `test_siaco.py`, `test_contexto_legal.py` pueden estar desactualizados
- Cubrir: agente_financiero, agente_legal_rag, busqueda_hibrida_triple

### 10. Despliegue / producción
- Documentar cómo correr con `gunicorn` o detrás de nginx
- Variables de entorno necesarias en `.env.example` (ya existe parcialmente)
- Considerar `supervisor` o `systemd` para mantener el proceso activo

---

## ✅ Completado (no tocar)

- FastAPI backend completo (auth, busqueda, auditoria, expedientes, perfil, competidores, reportes, chat)
- Motor RAG híbrido (UNSPSC + keywords + semántica all-MiniLM-L6-v2)
- Agente financiero + agente legal con citas normativas Ley 80, Decreto 1082, Ley 1150
- SPA web: login, perfil completo, búsqueda básica + avanzada, auditoría, expedientes, chat
- Streamlit UI: 6 pantallas, PDF ejecutivo con ReportLab, simulador de consorcio
- Biblioteca normativa indexada (infraestructura obra pública, menor cuantía, mínima cuantía)
- Sistema de autenticación multi-cliente con planes (básico, profesional, enterprise, admin)
- Gestor de documentos del cliente con RAG documental
- Inteligencia competitiva (extracción PDF ofertas + estrategia Claude)
- Gestión de expedientes con semáforo de urgencia
- README.md y backup ZIP creados (2026-06-21)
