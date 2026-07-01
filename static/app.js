/* SIACO v3.0 — Frontend SPA */
'use strict';

// ════════════ ESTADO GLOBAL ════════════
let TOKEN          = localStorage.getItem('siaco_token') || '';
let CLIENTE_ID     = localStorage.getItem('siaco_cid')   || '';
let PLAN           = localStorage.getItem('siaco_plan')   || 'basico';
let NOMBRE         = localStorage.getItem('siaco_nombre') || '';
let TIPO           = localStorage.getItem('siaco_tipo')   || 'cliente';
let USOS_PREMIUM   = JSON.parse(localStorage.getItem('siaco_usos') || '{}');
let DIAS_RESTANTES = parseInt(localStorage.getItem('siaco_dias')  || '0');
let _contratos   = [];
let _descartados = [];
let _pliegoRaw   = null;
let _selIdx      = -1;   // índice del contrato seleccionado en el panel

// ════════════ UTILIDADES BASE ════════════
async function api(path, opts = {}) {
  const headers = { Authorization: `Bearer ${TOKEN}`, ...(opts.headers || {}) };
  if (!(opts.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) { doLogout(); throw new Error('Sesión expirada'); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res;
}
async function apiJson(path, opts = {}) { return (await api(path, opts)).json(); }

function fmtCOP(v) {
  const n = parseFloat(v) || 0;
  if (n >= 1e9) return `$${(n/1e9).toFixed(2)} Mil M`;
  if (n >= 1e6) return `$${(n/1e6).toFixed(1)} M`;
  return `$${n.toLocaleString('es-CO')}`;
}
function fmtDate(s) {
  if (!s) return '—';
  try { return new Date(s).toLocaleDateString('es-CO'); } catch { return s; }
}
function toast(msg, tipo = 'info') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast toast-${tipo} show`;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 4500);
}
function alertHtml(tipo, msg) { return `<div class="alert-${tipo}">${msg}</div>`; }
function val(id) { const el = document.getElementById(id); return el ? el.value.trim() : ''; }
function setVal(id, v) { const el = document.getElementById(id); if (el) el.value = (v != null) ? v : ''; }
function txt(id, v) { const el = document.getElementById(id); if (el) el.textContent = v ?? '—'; }

function urlSecop(c) {
  const u = c.urlproceso;
  if (!u) return '';
  return typeof u === 'object' ? (u.url || '') : String(u);
}

// ════════════ AUTENTICACIÓN ════════════
document.getElementById('login-form').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = document.getElementById('btn-login');
  const errEl = document.getElementById('login-error');
  btn.disabled = true; btn.textContent = 'Ingresando...';
  errEl.innerHTML = '';
  try {
    const data = await apiJson('/api/login', {
      method: 'POST',
      body: JSON.stringify({
        username: document.getElementById('inp-user').value.trim(),
        password: document.getElementById('inp-pass').value,
      }),
    });
    TOKEN      = data.token;
    const cli  = data.cliente || {};
    CLIENTE_ID     = cli.cliente_id || cli.id || '';
    PLAN           = cli.plan || 'basico';
    NOMBRE         = cli.nombre || CLIENTE_ID;
    TIPO           = cli.tipo || 'cliente';
    USOS_PREMIUM   = cli.usos_premium || {};
    DIAS_RESTANTES = cli.dias_restantes || 0;
    localStorage.setItem('siaco_token',  TOKEN);
    localStorage.setItem('siaco_cid',    CLIENTE_ID);
    localStorage.setItem('siaco_plan',   PLAN);
    localStorage.setItem('siaco_nombre', NOMBRE);
    localStorage.setItem('siaco_tipo',   TIPO);
    localStorage.setItem('siaco_usos',   JSON.stringify(USOS_PREMIUM));
    localStorage.setItem('siaco_dias',   String(DIAS_RESTANTES));
    initMainScreen();
  } catch (err) {
    errEl.innerHTML = alertHtml('error', err.message);
    btn.disabled = false; btn.textContent = 'Ingresar';
  }
});

function doLogout() {
  api('/api/logout', { method: 'POST' }).catch(() => {});
  ['siaco_token','siaco_cid','siaco_plan','siaco_nombre','siaco_tipo','siaco_usos','siaco_dias']
    .forEach(k => localStorage.removeItem(k));
  sessionStorage.clear();
  TOKEN = CLIENTE_ID = PLAN = NOMBRE = '';
  TIPO = 'cliente'; USOS_PREMIUM = {}; DIAS_RESTANTES = 0;
  document.getElementById('main-screen').style.display = 'none';
  document.getElementById('login-screen').style.display = '';
}
document.getElementById('btn-logout').addEventListener('click', doLogout);

// ════════════ INICIALIZACIÓN ════════════
function initMainScreen() {
  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('main-screen').style.display  = '';

  const chip = document.getElementById('plan-chip');
  if      (PLAN === 'admin')   { chip.textContent = 'Admin';   chip.className = 'plan-chip admin'; }
  else if (PLAN === 'premium') { chip.textContent = 'Premium'; chip.className = 'plan-chip premium'; }
  else if (TIPO === 'tester')  { chip.textContent = 'Prueba';  chip.className = 'plan-chip tester'; }
  else                         { chip.textContent = 'Básico';  chip.className = 'plan-chip basico'; }
  document.getElementById('sidebar-user').textContent = NOMBRE || CLIENTE_ID;

  // Mostrar nav de admin solo para plan admin
  const navAdmin = document.getElementById('nav-admin');
  if (navAdmin) navAdmin.style.display = PLAN === 'admin' ? '' : 'none';

  // Banner tester
  const banner = document.getElementById('tester-banner');
  if (banner) {
    if (TIPO === 'tester') {
      banner.style.display = '';
      const diasEl = document.getElementById('tester-dias');
      if (diasEl) diasEl.textContent = DIAS_RESTANTES;
      if (DIAS_RESTANTES <= 2) banner.classList.add('dias-critico');
      else banner.classList.remove('dias-critico');
      document.body.style.paddingTop = (banner.offsetHeight || 42) + 'px';
    } else {
      banner.style.display = 'none';
      document.body.style.paddingTop = '';
    }
  }

  if (PLAN !== 'premium' && PLAN !== 'admin') {
    const gate = document.getElementById('comp-premium-gate');
    if (gate && !gate.querySelector('.gate-overlay')) {
      const ov = document.createElement('div');
      ov.className = 'gate-overlay';
      ov.innerHTML = `<div class="gate-msg">🔒 Plan Premium<br><small>Upgrade para acceder a Inteligencia Competitiva</small></div>`;
      gate.appendChild(ov);
    }
  }

  navigateTo('perfil');
  loadPerfil();
}

// ════════════ NAVEGACIÓN ════════════
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => navigateTo(btn.dataset.page));
});

function navigateTo(page) {
  if (page === 'competidores' && TIPO === 'tester') {
    checkTesterPremium('analisis_competencia', () => _doNavigate('competidores'));
    return;
  }
  _doNavigate(page);
}

function _doNavigate(page) {
  cerrarDetalle();
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const navBtn = document.querySelector(`.nav-item[data-page="${page}"]`);
  const pg     = document.getElementById(`page-${page}`);
  if (navBtn) navBtn.classList.add('active');
  if (pg) pg.classList.add('active');

  if (page === 'expedientes')  loadExpedientes();
  if (page === 'auditoria')    checkPrecargadoBusqueda();
  if (page === 'competidores') checkPrecargadoCompetidores();
  if (page === 'oferta')       oferta_prefill();
}

// ════════════ GATE TESTER ════════════
function checkTesterPremium(feature, onProceed) {
  if (TIPO !== 'tester') { onProceed(); return; }
  if (USOS_PREMIUM[feature] === true) { showTesterBlockModal(); return; }
  showTesterConfirmModal(feature, onProceed);
}

function showTesterConfirmModal(feature, onProceed) {
  const overlay = document.getElementById('tester-gate-modal');
  overlay.style.display = 'flex';
  const btnConfirm = document.getElementById('tgm-confirm');
  const btnCancel  = document.getElementById('tgm-cancel');
  const doConfirm = async () => {
    overlay.style.display = 'none';
    btnConfirm.removeEventListener('click', doConfirm);
    btnCancel.removeEventListener('click', doCancel);
    try {
      await apiJson('/api/tester/consumir', { method: 'POST', body: JSON.stringify({ feature }) });
      USOS_PREMIUM[feature] = true;
      localStorage.setItem('siaco_usos', JSON.stringify(USOS_PREMIUM));
      onProceed();
    } catch (err) {
      if (err.message && err.message.includes('Ya utilizaste')) {
        USOS_PREMIUM[feature] = true;
        localStorage.setItem('siaco_usos', JSON.stringify(USOS_PREMIUM));
        showTesterBlockModal();
      } else { toast(err.message || 'Error', 'error'); }
    }
  };
  const doCancel = () => {
    overlay.style.display = 'none';
    btnConfirm.removeEventListener('click', doConfirm);
    btnCancel.removeEventListener('click', doCancel);
  };
  btnConfirm.addEventListener('click', doConfirm);
  btnCancel.addEventListener('click', doCancel);
}

function showTesterBlockModal() {
  const overlay = document.getElementById('tester-block-modal');
  overlay.style.display = 'flex';
  const btnClose = document.getElementById('tbm-close');
  const doClose = () => {
    overlay.style.display = 'none';
    btnClose.removeEventListener('click', doClose);
  };
  btnClose.addEventListener('click', doClose);
}

// ════════════ TABS (PERFIL) ════════════
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const panel = document.getElementById(`tab-${btn.dataset.tab}`);
    if (panel) panel.classList.add('active');
  });
});

// ════════════ PERFIL ════════════
async function loadPerfil() {
  try {
    const data = await apiJson('/api/perfil');
    const p = data.perfil || {};
    const fin = p.financiero  || {};
    const exp = p.experiencia || {};
    const rup = p.rup         || {};

    setVal('p-nombre', p.nombre);   setVal('p-nit', p.nit);
    setVal('p-sector', p.sector);   setVal('p-notificacion', p.notificacion || 'whatsapp');
    setVal('p-whatsapp', p.contacto_whatsapp); setVal('p-email', p.contacto_email);
    setVal('p-rup-tiene',  String(rup.tiene_rup || false));
    setVal('p-rup-estado', rup.estado_rup || 'Inactivo');
    setVal('p-rup-numero', rup.numero_rup);
    setVal('p-rup-vence',  rup.fecha_vencimiento_rup);

    setVal('p-idl', fin.indice_liquidez);     setVal('p-nde', fin.indice_endeudamiento);
    setVal('p-rci', fin.razon_cobertura_interes);
    setVal('p-patrimonio', fin.patrimonio_liquido);
    setVal('p-capital',    fin.capital_trabajo);
    setVal('p-pres-min',   fin.presupuesto_minimo_contrato);
    setVal('p-pres-max',   fin.presupuesto_maximo_contrato);

    setVal('p-exp-acum',   exp.valor_acumulado);
    setVal('p-exp-max',    exp.valor_individual_max);
    setVal('p-exp-part',   exp.participacion_minima);
    setVal('p-exp-objeto', exp.objeto_similar);
    setVal('p-unspsc',     exp.codigos_unspsc);

    const rupAlert = document.getElementById('rup-alert-box');
    if (rupAlert) {
      const rv = data.rup_vigencia || {};
      if (!rup.tiene_rup || rup.estado_rup === 'Inactivo') {
        rupAlert.innerHTML = `<div class="rup-alert">⚠ RUP inactivo o no configurado. Requerido para Licitación Pública y Selección Abreviada (Decreto 1082/2015 art. 2.2.1.2.1.5.6).</div>`;
      } else if (rv.vence_pronto) {
        rupAlert.innerHTML = `<div class="rup-alert">⚠ RUP vence el ${rv.fecha_vencimiento || 'pronto'}. Renuévalo antes de presentar propuestas.</div>`;
      } else { rupAlert.innerHTML = ''; }
    }
    loadDocumentos(data.documentos);
  } catch (err) { toast(err.message, 'error'); }
}

function buildPerfilBody() {
  return {
    nombre: val('p-nombre'), nit: val('p-nit'), sector: val('p-sector'),
    notificacion: val('p-notificacion'),
    contacto_whatsapp: val('p-whatsapp'), contacto_email: val('p-email'),
    rup: {
      tiene_rup:             val('p-rup-tiene') === 'true',
      estado_rup:            val('p-rup-estado'),
      numero_rup:            val('p-rup-numero'),
      fecha_vencimiento_rup: val('p-rup-vence'),
    },
    financiero: {
      indice_liquidez:             parseFloat(val('p-idl'))        || 0,
      indice_endeudamiento:        parseFloat(val('p-nde'))        || 0,
      razon_cobertura_interes:     parseFloat(val('p-rci'))        || 0,
      patrimonio_liquido:          parseFloat(val('p-patrimonio')) || 0,
      capital_trabajo:             parseFloat(val('p-capital'))    || 0,
      presupuesto_minimo_contrato: parseFloat(val('p-pres-min'))   || 0,
      presupuesto_maximo_contrato: parseFloat(val('p-pres-max'))   || 0,
    },
    experiencia: {
      valor_acumulado:      parseFloat(val('p-exp-acum'))  || 0,
      valor_individual_max: parseFloat(val('p-exp-max'))   || 0,
      objeto_similar:       val('p-exp-objeto'),
      codigos_unspsc:       val('p-unspsc'),
      participacion_minima: parseFloat(val('p-exp-part'))  || 30,
    },
  };
}

async function savePerfil() {
  const tieneContacto = val('p-whatsapp') || val('p-email');
  if (TIPO === 'tester' && tieneContacto) {
    checkTesterPremium('notificaciones', () => _savePerfilImpl());
    return;
  }
  _savePerfilImpl();
}
async function _savePerfilImpl() {
  try {
    await apiJson('/api/perfil', { method: 'PUT', body: JSON.stringify(buildPerfilBody()) });
    toast('Perfil guardado correctamente', 'success');
    const st = document.getElementById('perfil-save-status');
    if (st) st.textContent = '✓ Guardado ' + new Date().toLocaleTimeString('es-CO');
    loadPerfil();
  } catch (err) { toast(err.message, 'error'); }
}

document.getElementById('btn-save-perfil').addEventListener('click', savePerfil);
document.getElementById('btn-save-financiero').addEventListener('click', savePerfil);
document.getElementById('btn-save-experiencia').addEventListener('click', savePerfil);

// ─── Documentos ─────────────────────────────────────
function loadDocumentos(docs) {
  const cont = document.getElementById('doc-list-container');
  if (!cont) return;
  if (!docs) {
    apiJson('/api/perfil/documentos').then(d => loadDocumentos(d.documentos)).catch(() => {});
    return;
  }
  if (!docs.length) {
    cont.innerHTML = '<div class="empty-state">No hay documentos indexados todavía.</div>';
    return;
  }
  cont.innerHTML = docs.map(d => `
    <div class="doc-card">
      <div class="doc-info">
        <span class="doc-tipo">${d.tipo || 'Documento'}</span>
        <span class="doc-nombre">${d.nombre || d.filename || '—'}</span>
        <span class="doc-chunks">${d.chunks || '?'} fragmentos indexados</span>
      </div>
      <button class="btn btn-ghost btn-sm btn-danger"
        onclick="deleteDoc('${encodeURIComponent(d.filename || d.nombre || '')}')">🗑</button>
    </div>
  `).join('');
}

async function deleteDoc(enc) {
  if (!confirm(`¿Eliminar "${decodeURIComponent(enc)}" del índice?`)) return;
  try {
    await apiJson(`/api/perfil/documento/${enc}`, { method: 'DELETE' });
    toast('Documento eliminado', 'success');
    loadDocumentos();
  } catch (err) { toast(err.message, 'error'); }
}

setupUpload('doc-upload-area', 'doc-file', 'doc-filename', 'btn-upload-doc');
document.getElementById('btn-upload-doc').addEventListener('click', () => {
  checkTesterPremium('subir_documentos', () => _uploadDocImpl());
});
async function _uploadDocImpl() {
  const file = document.getElementById('doc-file').files[0];
  if (!file) { toast('Selecciona un archivo', 'warn'); return; }
  const fd = new FormData();
  fd.append('tipo_doc', document.getElementById('doc-tipo').value);
  fd.append('archivo', file);
  const stEl = document.getElementById('doc-upload-status');
  const btn  = document.getElementById('btn-upload-doc');
  stEl.innerHTML = alertHtml('info', 'Indexando documento con IA...');
  btn.disabled = true;
  try {
    const data = await apiJson('/api/perfil/documento', { method: 'POST', body: fd });
    stEl.innerHTML = alertHtml('success', `✓ ${data.chunks || '?'} fragmentos indexados — ${data.filename || file.name}`);
    toast('Documento indexado', 'success');
    loadDocumentos();
  } catch (err) {
    stEl.innerHTML = alertHtml('error', err.message);
  } finally { btn.disabled = false; }
}

// ════════════ BÚSQUEDA SECOP II ════════════
document.getElementById('btn-buscar').addEventListener('click', buscarContratos);
document.getElementById('btn-analizar-ia').addEventListener('click', analizarConIA);

async function buscarContratos() {
  const btn  = document.getElementById('btn-buscar');
  const stEl = document.getElementById('busq-status');
  btn.disabled = true; btn.textContent = 'Buscando...';
  stEl.innerHTML = alertHtml('info', 'Consultando SECOP II... (puede tardar hasta 30 seg)');
  document.getElementById('busq-results').style.display = 'none';
  const bannerEl = document.getElementById('busq-banner');
  if (bannerEl) bannerEl.style.display = 'none';

  try {
    const qs = new URLSearchParams({
      fecha_desde:    val('b-fecha') || '2026-01-01',
      valor_minimo:   val('b-valor') || '5000000',
      max_resultados: val('b-max')   || '50',
      departamento:   val('b-depto') || '',
    });
    const data = await apiJson(`/api/contratos?${qs}`);

    // Support both new and legacy response shapes
    _contratos   = data.contratos_relevantes || data.contratos   || [];
    _descartados = data.contratos_descartados || data.descartados || [];

    stEl.innerHTML = '';
    renderBusquedaResult(data);
    renderTabla(_contratos);
    renderDescartados(_descartados);
    document.getElementById('busq-results').style.display = '';
    document.getElementById('btn-analizar-ia').disabled = !_contratos.length;

    if (!_contratos.length && _descartados.length) {
      // Zero relevant: auto-expand discarded and show guidance
      const discSec = document.getElementById('disc-section');
      if (discSec) discSec.setAttribute('open', '');
      stEl.innerHTML = alertHtml('warn',
        `Sin contratos relevantes para tu perfil. Se encontraron ${_descartados.length} contratos — puedes analizarlos individualmente.`
      );
    } else if (!_contratos.length) {
      stEl.innerHTML = alertHtml('warn', 'Sin resultados. Prueba ampliar fechas o reducir valor mínimo.');
    }
  } catch (err) {
    stEl.innerHTML = alertHtml('error', err.message);
  } finally { btn.disabled = false; btn.textContent = 'Buscar contratos'; }
}

function renderBusquedaResult(data) {
  const bannerEl  = document.getElementById('busq-banner');
  const badgeEl   = document.getElementById('badge-modo');
  if (!bannerEl) return;

  const rel   = data.total_relevantes  ?? (data.contratos_relevantes  || data.contratos  || []).length;
  const disc  = data.total_descartados ?? (data.contratos_descartados || data.descartados || []).length;
  const total = data.total_analizados  ?? data.total_raw ?? (rel + disc);
  const modo  = data.modo_busqueda || 'keywords_only';

  // Mode badge
  if (badgeEl) {
    const isHibrido = modo === 'hibrido';
    badgeEl.textContent = isHibrido ? '🧬 HÍBRIDO' : 'KEYWORDS';
    badgeEl.className   = `badge-avanzada ${isHibrido ? 'badge-verde' : 'badge-amber'}`;
    badgeEl.style.display = '';
  }

  // Summary banner
  bannerEl.innerHTML = `<div class="busq-banner-card">
    <div class="busq-banner-row">
      <span class="banner-rel">✅ <strong>${rel}</strong> relevantes</span>
      <span class="banner-disc">🗑 <strong>${disc}</strong> descartados de <strong>${total}</strong> analizados</span>
    </div>
  </div>`;
  bannerEl.style.display = (rel + disc) > 0 ? '' : 'none';
}

async function analizarConIA() {
  const btn  = document.getElementById('btn-analizar-ia');
  const stEl = document.getElementById('busq-status');
  btn.disabled = true; btn.textContent = '⏳ Analizando...';
  stEl.innerHTML = alertHtml('info', `Claude IA analizando ${Math.min(_contratos.length, 50)} contratos (20-40 seg)...`);
  try {
    const data = await apiJson('/api/contratos/analizar', {
      method: 'POST',
      body: JSON.stringify({ contratos: _contratos }),
    });
    // Merge by contract ID — preserves hybrid score, adds _score_ia
    const byId = {};
    for (const r of (data.resultados || [])) {
      const id = r.id_del_proceso || r.referencia_del_proceso || '';
      if (id) byId[id] = r;
    }
    _contratos = _contratos.map(c => {
      const id = c.id_del_proceso || c.referencia_del_proceso || '';
      const r = byId[id];
      if (!r) return c;
      return { ...c, _score_ia: r._score ?? 0, _motivo_ia: r._motivo || '', _urgente: r._urgente ?? c._urgente };
    });
    // Sort: IA score desc, hybrid score as tiebreaker
    _contratos.sort((a, b) =>
      (b._score_ia ?? -1) - (a._score_ia ?? -1) || (b._score || 0) - (a._score || 0)
    );
    renderTabla(_contratos);
    stEl.innerHTML = '';
    toast('Análisis completado — ordenado por Score IA', 'success');
  } catch (err) {
    stEl.innerHTML = alertHtml('error', err.message);
  } finally { btn.disabled = false; btn.textContent = '🤖 Analizar con IA'; }
}

// ─── Render tabla principal de contratos ────────────────────────────────────
function renderTabla(lista) {
  txt('busq-count', `${lista.length} contrato${lista.length !== 1 ? 's' : ''} relevantes`);
  const tbody = document.getElementById('tabla-body');
  tbody.innerHTML = lista.map((c, i) => {
    // Columna "Perfil": score del filtro híbrido (siempre visible)
    const scorePerfil = c._score || 0;
    const clsP        = scorePerfil >= 70 ? 'score-high' : scorePerfil >= 40 ? 'score-mid' : 'score-low';
    const scoreBar    = `<div class="score-cell">
      <div class="score-bar"><div class="score-bar-fill ${clsP}" style="width:${scorePerfil}%"></div></div>
      <span class="score-num-sm ${clsP}">${scorePerfil || '—'}</span>
    </div>`;
    // Columna "IA": score de Claude (solo después de "Analizar con IA")
    const scoreIa = c._score_ia != null ? c._score_ia : null;
    const clsIA   = scoreIa >= 70 ? 'score-high' : scoreIa >= 40 ? 'score-mid' : 'score-low';
    const cellIa  = scoreIa != null
      ? `<span class="score-num-sm ${clsIA}" title="${c._motivo_ia || ''}">${scoreIa}</span>`
      : `<span class="score-num-sm" style="color:var(--muted)">—</span>`;
    const nombre  = (c.nombre_del_procedimiento || 'Sin nombre').substring(0, 65);
    const entidad = (c.entidad || '—').substring(0, 32);
    const dias    = c._dias_cierre != null ? `${c._dias_cierre}d` : '—';
    const title   = [c._motivo, c._motivo_ia].filter(Boolean).join(' | ') || 'Ver detalle';
    return `<tr class="${c._urgente ? 'urgente' : ''}" data-idx="${i}">
      <td>${scoreBar}</td>
      <td class="td-num">${cellIa}</td>
      <td class="td-nombre">
        <span class="td-nombre-link" onclick="abrirDetalle(${i})" title="${title}">${nombre}${c._urgente ? ' <span class="urg-tag">URG</span>' : ''}</span>
      </td>
      <td class="td-sm">${entidad}</td>
      <td class="td-num">${fmtCOP(c.precio_base || 0)}</td>
      <td class="td-sm">${c.fase || '—'}</td>
      <td class="td-num">${dias}</td>
      <td class="td-actions">
        <button class="btn btn-ghost btn-xs" onclick="abrirDetalle(${i})" title="Ver detalle">👁</button>
        <button class="btn btn-ghost btn-xs" onclick="precargaAuditoria(${i})" title="Auditar">📂</button>
        <button class="btn btn-ghost btn-xs" onclick="agregarExpediente(${i})" title="Expediente">📋</button>
      </td>
    </tr>`;
  }).join('');
}

// ─── Render tabla de descartados ─────────────────────────────────────────────
function renderDescartados(descartados) {
  const discSec  = document.getElementById('disc-section');
  const discHdr  = document.getElementById('disc-header');
  const discBody = document.getElementById('disc-tbody');
  if (!discSec) return;

  if (!descartados.length) {
    discSec.style.display = 'none';
    return;
  }

  discSec.style.display = '';
  if (discHdr) discHdr.textContent = `▼ ${descartados.length} contratos descartados automáticamente`;

  if (discBody) {
    discBody.innerHTML = descartados.map((d, i) => {
      const score = d._score_hibrido ? Math.round(d._score_hibrido * 100) : null;
      return `<tr>
        <td class="td-nombre"><span class="td-nombre-link" style="cursor:default">${(d.nombre_del_procedimiento||'Sin nombre').substring(0,55)}</span></td>
        <td class="td-sm">${(d.entidad||'—').substring(0,28)}</td>
        <td class="td-num">${fmtCOP(d.precio_base||0)}</td>
        <td><span class="disc-razon-tag">${d.razon_descarte||d._razon||'—'}</span></td>
        <td class="td-num">${score != null ? score : '—'}</td>
        <td class="td-actions">
          <button class="btn btn-ghost btn-xs" onclick="analizarDeTodasFormas(${i})" title="Incluir en resultados">▶ Analizar</button>
        </td>
      </tr>`;
    }).join('');
  }
}

// ─── Mover contrato descartado a resultados principales ──────────────────────
function analizarDeTodasFormas(idx) {
  const c = _descartados[idx];
  if (!c) return;
  _contratos.push({
    ...c,
    _score:  0,
    _motivo: `Incluido manualmente (${c.razon_descarte || c._razon || 'descartado'})`,
  });
  _descartados.splice(idx, 1);
  renderTabla(_contratos);
  renderDescartados(_descartados);
  document.getElementById('btn-analizar-ia').disabled = false;
  toast('Contrato incluido en resultados principales', 'success');
}

// ════════════ PANEL DE DETALLE ════════════
function abrirDetalle(i) {
  const c = _contratos[i]; if (!c) return;
  _selIdx = i;

  txt('det-nombre', c.nombre_del_procedimiento || 'Sin nombre');
  txt('det-entidad', c.entidad || '—');
  document.getElementById('det-valor').textContent = fmtCOP(c.precio_base || 0);
  txt('det-fase', c.fase || '—');
  const dias = c._dias_cierre != null ? `${c._dias_cierre} días` : '—';
  document.getElementById('det-dias').textContent = dias;

  const url = urlSecop(c);
  const urlRow = document.getElementById('det-url-row');
  if (url) {
    urlRow.style.display = '';
    const link = document.getElementById('det-url-link');
    link.href = url;
    document.getElementById('det-url-text').textContent = url;
  } else {
    urlRow.style.display = 'none';
  }

  // Mostrar si es Premium el botón de competidores
  const btnComp = document.getElementById('det-btn-competidores');
  if (btnComp) {
    btnComp.textContent = (PLAN === 'premium' || PLAN === 'admin')
      ? '🏆 Analizar Competencia'
      : '🏆 Analizar Competencia (Plan Premium)';
  }

  document.getElementById('detalle-overlay').classList.add('open');
  document.getElementById('detalle-panel').classList.add('open');
}

function cerrarDetalle() {
  document.getElementById('detalle-overlay').classList.remove('open');
  document.getElementById('detalle-panel').classList.remove('open');
}

// Botones del panel de detalle
function irAuditoria() {
  precargaAuditoria(_selIdx);
  cerrarDetalle();
}

async function irAgregarExpediente() {
  const btn = document.getElementById('det-btn-expediente');
  btn.disabled = true; btn.textContent = 'Guardando...';
  await agregarExpediente(_selIdx);
  btn.disabled = false; btn.textContent = '📋 Agregar a Expedientes';
}

function irCompetidores() {
  const c = _contratos[_selIdx]; if (!c) return;
  const pid = c.id_del_proceso || c.referencia_del_proceso || '';
  const url = urlSecop(c);
  sessionStorage.setItem('siaco_comp_proceso', pid);
  sessionStorage.setItem('siaco_comp_nombre',  c.nombre_del_procedimiento || '');
  sessionStorage.setItem('siaco_comp_url',     url);
  cerrarDetalle();
  navigateTo('competidores');
}

// ════════════ PRECARGA ENTRE PANTALLAS ════════════
function precargaAuditoria(i) {
  const c = _contratos[i]; if (!c) return;
  // Guardar en sessionStorage para que auditoría muestre el banner
  sessionStorage.setItem('siaco_precarg_entidad', c.entidad || '');
  sessionStorage.setItem('siaco_precarg_objeto',  c.nombre_del_procedimiento || '');
  sessionStorage.setItem('siaco_precarg_valor',   c.precio_base || '');
  sessionStorage.setItem('siaco_precarg_url',     urlSecop(c));
  sessionStorage.setItem('siaco_precarg_pid',     c.id_del_proceso || c.referencia_del_proceso || '');
  navigateTo('auditoria');
}

function checkPrecargadoBusqueda() {
  const banner = document.getElementById('audit-precargado-banner');
  if (!banner) return;
  const entidad = sessionStorage.getItem('siaco_precarg_entidad');
  if (!entidad) { banner.style.display = 'none'; return; }

  setVal('a-entidad', entidad);
  setVal('a-objeto',  sessionStorage.getItem('siaco_precarg_objeto') || '');
  setVal('a-valor',   sessionStorage.getItem('siaco_precarg_valor')  || '');

  const url = sessionStorage.getItem('siaco_precarg_url') || '';
  const urlHtml = url
    ? `<span class="precargado-secop-url">URL del proceso: <a href="${url}" target="_blank" rel="noopener">Abrir en SECOP II ↗</a></span>`
    : '<span class="precargado-secop-url">Sin URL directa disponible — busca el proceso en <a href="https://www.colombiacompra.gov.co" target="_blank">SECOP II</a> y descarga el pliego manualmente.</span>';

  banner.style.display = '';
  banner.innerHTML = `<div class="precargado-banner">
    <div>
      <strong>✓ Datos precargados desde Búsqueda SECOP II</strong><br>
      Descarga el <strong>Pliego de Condiciones</strong> del proceso en SECOP II y súbelo aquí para el análisis IA.
      ${urlHtml}
    </div>
    <button onclick="limpiarPrecargado()" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:.8rem;white-space:nowrap">✕ Limpiar</button>
  </div>`;
}

function limpiarPrecargado() {
  ['siaco_precarg_entidad','siaco_precarg_objeto','siaco_precarg_valor','siaco_precarg_url','siaco_precarg_pid']
    .forEach(k => sessionStorage.removeItem(k));
  const banner = document.getElementById('audit-precargado-banner');
  if (banner) banner.style.display = 'none';
}

function checkPrecargadoCompetidores() {
  const pid = sessionStorage.getItem('siaco_comp_proceso');
  if (!pid) return;
  setVal('comp-proceso', pid);
  const url = sessionStorage.getItem('siaco_comp_url') || '';
  const nombre = sessionStorage.getItem('siaco_comp_nombre') || '';

  const stEl = document.getElementById('comp-status');
  if (stEl && url) {
    stEl.innerHTML = alertHtml('info',
      `<strong>Proceso precargado: ${pid}</strong><br>
       Descarga las ofertas desde: <a href="${url}" target="_blank" rel="noopener" style="color:var(--accent)">${url}</a><br>
       → Sección <em>Lista de Proveedores</em> → descarga los PDFs de cada oferta → sube aquí uno por uno.`
    );
  }
  document.getElementById('comp-proceso-label').textContent = pid ? `Competidores: ${pid}` : 'Competidores analizados';
  document.getElementById('btn-estrategia').disabled = !pid;
  listarCompetidores(pid);

  sessionStorage.removeItem('siaco_comp_proceso');
  sessionStorage.removeItem('siaco_comp_nombre');
  sessionStorage.removeItem('siaco_comp_url');
}

// ════════════ AGREGAR A EXPEDIENTES ════════════
async function agregarExpediente(i) {
  const c = _contratos[i]; if (!c) return;
  try {
    await apiJson('/api/contratos/expediente', {
      method: 'POST',
      body: JSON.stringify({ contrato: c, score: c._score || 0 }),
    });
    toast(`✓ "${(c.nombre_del_procedimiento||'Contrato').substring(0,45)}" guardado en Expedientes`, 'success');
  } catch (err) {
    // Si ya existe no es error crítico
    if (err.message.includes('ya está')) toast('Este proceso ya está en tus expedientes', 'warn');
    else toast(err.message, 'error');
  }
}

// ════════════ AUDITORÍA ════════════
setupUpload('pliego-upload-area', 'pliego-file', 'pliego-filename', 'btn-extraer');
setupUploadMini('estudios-upload-area', 'estudios-file', 'estudios-filename');
setupUploadMini('anexo-upload-area',    'anexo-file',    'anexo-filename');
setupUploadMini('adenda-upload-area',   'adenda-file',   'adenda-filename');
document.getElementById('btn-extraer').addEventListener('click', extraerPliego);
document.getElementById('btn-analizar-pliego').addEventListener('click', analizarPliego);
// Auto-extraer cuando el usuario selecciona el archivo del pliego
document.getElementById('pliego-file').addEventListener('change', function() {
  if (this.files[0]) setTimeout(extraerPliego, 120);
});

async function extraerPliego() {
  const file = document.getElementById('pliego-file').files[0];
  if (!file) { toast('Selecciona un archivo', 'warn'); return; }
  _pliegoRaw = file;
  const btn  = document.getElementById('btn-extraer');
  const stEl = document.getElementById('pliego-extract-status');
  btn.disabled = true; btn.textContent = 'Analizando...';
  stEl.innerHTML = alertHtml('info', 'Analizando documento con Claude...');
  const fd = new FormData(); fd.append('pdf', file);
  try {
    const d = await apiJson('/api/auditoria/extraer', { method: 'POST', body: fd });
    if (d.entidad)   setVal('a-entidad',   d.entidad);
    if (d.objeto)    setVal('a-objeto',    d.objeto);
    if (d.valor)     setVal('a-valor',     d.valor);
    if (d.modalidad) setVal('a-modalidad', d.modalidad);
    if (d.sector)    setVal('a-sector',    d.sector);
    const fmt = d.formato_detectado ? ` desde ${d.formato_detectado}` : '';
    if (d.extraccion_ok) {
      stEl.innerHTML = alertHtml('success', `✓ ${(d.texto_chars||0).toLocaleString()} caracteres extraídos${fmt}. Campos prellenados automáticamente.`);
    } else {
      stEl.innerHTML = alertHtml('warn', `✓ ${(d.texto_chars||0).toLocaleString()} caracteres extraídos${fmt}. No se pudieron extraer campos automáticamente — completa los parámetros manualmente.`);
    }
  } catch (err) {
    stEl.innerHTML = alertHtml('error', err.message);
  } finally { btn.disabled = false; btn.textContent = '⚡ Extraer datos automáticamente'; }
}

async function analizarPliego() {
  const btn  = document.getElementById('btn-analizar-pliego');
  const stEl = document.getElementById('audit-status');
  const resEl= document.getElementById('audit-results');

  // Validar que hay pliego subido
  const pliegoFile = document.getElementById('pliego-file').files[0];
  if (!pliegoFile) {
    stEl.innerHTML = alertHtml('error', '⚠ Debes subir el Pliego de Condiciones antes de analizar.');
    return;
  }

  btn.disabled = true; btn.textContent = '⏳ Analizando...';
  resEl.style.display = 'none';

  // ── Animated progress steps ──────────────────────
  const STEPS = [
    'Extrayendo texto del pliego...',
    'Indexando documentos...',
    'Buscando secciones relevantes...',
    'Analizando con IA (puede tardar 40-90 seg)...',
  ];
  const DELAYS = [0, 3000, 8000, 16000]; // ms after start
  const timers = [];

  function showStep(active) {
    const rows = STEPS.map((s, i) => {
      if (i < active)  return `<span class="prog-step prog-done">✓ ${s}</span>`;
      if (i === active) return `<span class="prog-step prog-active"><span class="prog-spinner"></span>${s}</span>`;
      return `<span class="prog-step prog-pending">○ ${s}</span>`;
    }).join('');
    stEl.innerHTML = `<div class="progress-steps">${rows}</div>`;
  }

  DELAYS.forEach((d, i) => {
    timers.push(setTimeout(() => showStep(i), d));
  });

  const clearTimers = () => timers.forEach(t => clearTimeout(t));

  const fd = new FormData();
  fd.append('cliente_id', CLIENTE_ID);
  fd.append('modalidad',  val('a-modalidad'));
  fd.append('sector',     val('a-sector'));
  fd.append('entidad',    val('a-entidad'));
  fd.append('objeto',     val('a-objeto'));
  fd.append('valor',      val('a-valor') || '450000000');
  fd.append('pliego', pliegoFile);

  const estudiosFile = document.getElementById('estudios-file')?.files[0];
  const anexoFile    = document.getElementById('anexo-file')?.files[0];
  const adendaFile   = document.getElementById('adenda-file')?.files[0];
  if (estudiosFile) fd.append('estudio_previo', estudiosFile);
  if (anexoFile)    fd.append('anexo_tecnico',  anexoFile);
  if (adendaFile)   fd.append('adenda',         adendaFile);

  try {
    const data = await apiJson('/api/auditoria/analizar', { method: 'POST', body: fd });
    clearTimers();
    const ragBadge = data.rag_activado
      ? `<span class="prog-rag-badge">RAG activado — ${data.pliego_chars?.toLocaleString()} chars indexados → ${data.contexto_chars?.toLocaleString()} chars enviados</span>`
      : '';
    const allDone = STEPS.map(s => `<span class="prog-step prog-done">✓ ${s}</span>`).join('');
    stEl.innerHTML = `<div class="progress-steps">${allDone}${ragBadge}</div>`;
    resEl.style.display = '';
    resEl.innerHTML = renderAuditResult(data);
    resEl.scrollIntoView({ behavior: 'smooth' });
    window._lastAnalisis = data;
    // Registra que el análisis completó y qué cliente_id fue usado,
    // para que observaciones y otras pestañas usen exactamente el mismo key de sesión.
    sessionStorage.setItem('siaco_pliego_sesion_cid', CLIENTE_ID);
  } catch (err) {
    clearTimers();
    stEl.innerHTML = alertHtml('error', err.message);
  } finally { btn.disabled = false; btn.textContent = '🔍 Analizar con IA'; }
}

function renderAuditResult(r) {
  const concepto = r.concepto_global || 'CONDICIONAL';
  const color    = r.concepto_color  || 'amber';
  const scoreG   = r.score_global    || 0;
  const scoreF   = r.score || r.score_financiero || 0;
  const scoreJ   = r.score_juridico  || 0;
  const badgeCls = color === 'green' ? 'viable' : color === 'red' ? 'no-viable' : 'condicional';

  const tablaRows = (r.tabla_comparativa || []).map(row => {
    const icon = row.cumple ? '✅' : '❌';
    const sub  = row.subsanable ? '<span class="sub-tag">Subsanable</span>' : '';
    const tipo = row.tipo === 'financiero' ? '💰' : '⚖️';
    return `<tr class="${row.cumple ? 'row-ok' : 'row-fail'}">
      <td>${tipo}</td><td>${row.requisito||'—'}</td><td>${row.exigido||'—'}</td>
      <td>${row.cliente_tiene||'—'}</td><td class="td-center">${icon} ${sub}</td>
      <td class="norma-cell">${row.norma||'—'}</td>
    </tr>`;
  }).join('');

  const citas = (r.citas_normativas||[]).map(c => `<div class="norma-cite">📖 ${c}</div>`).join('')
    || '<div class="empty-state">—</div>';
  const docsFalt = (r.checklist_documentos||[]).filter(d => d.estado === 'falta');
  const docsHtml = docsFalt.length
    ? docsFalt.map(d => `<div class="doc-faltante">📄 ${d.documento}${d.subsanable ? ' <span class="sub-tag">Subsanable</span>':''}</div>`).join('')
    : '<div class="empty-state">Sin documentos faltantes</div>';
  const recs = [...(r.recomendaciones||[]), ...(r.acciones_inmediatas||[])];
  const riesgos = r.riesgos_juridicos || r.riesgos || [];

  return `<div class="audit-result">
    <div class="concepto-header">
      <span class="concepto-badge ${badgeCls}">${concepto}</span>
      <div class="scores-row">
        <div class="score-card"><div class="score-big">${scoreG}</div><div class="score-label">Global</div></div>
        <div class="score-card"><div class="score-big">${scoreF}</div><div class="score-label">Financiero</div></div>
        <div class="score-card"><div class="score-big">${scoreJ}</div><div class="score-label">Jurídico</div></div>
      </div>
    </div>
    ${r.analisis_financiero ? `<div class="card"><div class="card-title">💰 Análisis Financiero</div><div class="analisis-texto">${r.analisis_financiero}</div></div>` : ''}
    ${tablaRows ? `<div class="card"><div class="card-title">📋 Habilitantes — Tabla Comparativa</div>
      <div class="table-wrap"><table class="req-table">
        <thead><tr><th></th><th>Requisito</th><th>Exigido</th><th>Empresa</th><th>¿Cumple?</th><th>Norma</th></tr></thead>
        <tbody>${tablaRows}</tbody>
      </table></div></div>` : ''}
    ${r.analisis_juridico ? `<div class="card"><div class="card-title">⚖️ Análisis Jurídico (RAG)</div><div class="analisis-texto">${r.analisis_juridico}</div></div>` : ''}
    <div class="card"><div class="card-title">📖 Citas Normativas</div>${citas}</div>
    ${docsFalt.length ? `<div class="card"><div class="card-title">📎 Documentos a Gestionar</div>${docsHtml}</div>` : ''}
    ${riesgos.length ? `<div class="card"><div class="card-title">⚠ Riesgos</div><ul class="riesgos-list">${riesgos.map(x=>`<li>⚠ ${x}</li>`).join('')}</ul></div>` : ''}
    ${recs.length ? `<div class="card"><div class="card-title">✅ Plan de Acción</div><ul>${recs.map(x=>`<li>${x}</li>`).join('')}</ul></div>` : ''}
    <div style="margin-top:20px;display:flex;gap:10px;flex-wrap:wrap">
      <button class="btn btn-secondary" onclick="descargarPDF(event)">⬇ Descargar PDF Ejecutivo</button>
      <button id="btn-obs-pliego" class="btn btn-primary" onclick="generarObservaciones(event)">📋 Generar Observaciones al Pliego</button>
      <button class="btn btn-secondary" onclick="navigateTo('oferta')">📄 Generar documentos de oferta</button>
    </div>
    <div id="obs-result" style="margin-top:16px"></div>
  </div>`;
}

async function descargarPDF(event) {
  const btn = event.target;
  checkTesterPremium('descargar_pdf_analisis', () => _descargarPDFImpl(btn));
}
async function _descargarPDFImpl(btn) {
  if (!window._lastAnalisis) { toast('Realiza un análisis primero', 'warn'); return; }
  btn.disabled = true; btn.textContent = '⏳ Generando PDF...';
  try {
    const res = await api('/api/reportes/pdf', {
      method: 'POST',
      body: JSON.stringify({
        analisis:       window._lastAnalisis,
        licitacion:     { nombre_del_procedimiento: val('a-objeto'), entidad: val('a-entidad'), precio_base: val('a-valor') },
        cliente_nombre: NOMBRE || CLIENTE_ID,
      }),
    });
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `SIACO_${Date.now()}.pdf`; a.click();
    URL.revokeObjectURL(url);
    toast('PDF descargado', 'success');
  } catch (err) { toast(`Error PDF: ${err.message}`, 'error'); }
  finally { btn.disabled = false; btn.textContent = '⬇ Descargar PDF Ejecutivo'; }
}

function _renderObsResult(data, resDiv) {
  if (!data.tiene_discrepancias || !data.discrepancias?.length) {
    resDiv.innerHTML = `<div class="card" style="border-left:4px solid #4caf50">
      <div class="card-title">Pliego conforme a Documentos Tipo CCE</div>
      <p>No se encontraron discrepancias que justifiquen observaciones formales.</p>
    </div>`;
    return;
  }
  const filas = data.discrepancias.map(d => `
    <tr>
      <td style="font-weight:700;white-space:nowrap">Obs. ${d.numero}</td>
      <td>${d.titulo||'—'}</td>
      <td style="font-size:0.82em;color:#aaa">${d.seccion_pliego||'—'}</td>
      <td style="font-size:0.82em;color:#e57373">${d.norma_vulnerada||'—'}</td>
    </tr>`).join('');
  const descPdfBtn = data.pdf_disponible && data.pdf_filename
    ? `<button class="btn btn-secondary" style="margin-top:12px"
         onclick="descargarObservaciones('${data.pdf_filename}')">
         📄 Descargar PDF de Observaciones
       </button>`
    : '';
  const descDocxBtn = data.docx_filename
    ? `<button class="btn btn-secondary" style="margin-top:12px;margin-left:8px"
         onclick="descargarObservaciones('${data.docx_filename}')">
         📝 Descargar Word (.docx)
       </button>`
    : '';
  resDiv.innerHTML = `<div class="card" style="border-left:4px solid #C6F24E">
    <div class="card-title">${data.total_discrepancias} discrepancia(s) identificada(s) — ${data.entidad||'Entidad'}</div>
    <div class="table-wrap"><table class="req-table">
      <thead><tr><th>#</th><th>Título</th><th>Sección</th><th>Norma vulnerada</th></tr></thead>
      <tbody>${filas}</tbody>
    </table></div>
    <div style="display:flex;flex-wrap:wrap;gap:4px">${descPdfBtn}${descDocxBtn}</div>
  </div>`;
  toast(`${data.total_discrepancias} observacion(es) generadas`, 'success');
}

async function generarObservaciones(event) {
  const btn = event.target;
  const resDiv = document.getElementById('obs-result');
  if (!CLIENTE_ID) { toast('Inicia sesión primero', 'warn'); return; }

  const _pliegoCid = sessionStorage.getItem('siaco_pliego_sesion_cid');
  if (!_pliegoCid) {
    if (resDiv) resDiv.innerHTML = alertHtml('warn',
      'No hay pliego en sesión. Ve a la pestaña <b>Auditoría</b>, ' +
      'sube el PDF del pliego y haz clic en <b>Analizar con IA</b> primero.');
    toast('Primero analiza el pliego en Auditoría', 'warn');
    return;
  }

  btn.disabled = true; btn.textContent = '⏳ Procesando...';
  if (resDiv) resDiv.innerHTML = `<div class="loading">
    Analizando pliego con IA — esto puede tardar hasta 90 segundos...
  </div>`;

  let jobId = null;
  try {
    const procesoId = val('a-codigo-proceso') || val('a-objeto') || `obs_${Date.now()}`;
    const launch = await apiJson('/api/observaciones/generar', {
      method: 'POST',
      body: JSON.stringify({ cliente_id: _pliegoCid, proceso_id: procesoId }),
    });
    jobId = launch.job_id;
  } catch (err) {
    resDiv.innerHTML = `<div class="alert alert-error">${err.message||'Error al iniciar análisis'}</div>`;
    toast(`Error: ${err.message}`, 'error');
    btn.disabled = false; btn.textContent = '📋 Generar Observaciones al Pliego';
    return;
  }

  // Polling: consultar estado cada 3s durante max 3 minutos
  const MAX_MS = 3 * 60 * 1000;
  const POLL_MS = 3000;
  const started = Date.now();
  let elapsed = 0;

  const poll = async () => {
    elapsed = Date.now() - started;
    if (elapsed > MAX_MS) {
      resDiv.innerHTML = alertHtml('warn',
        'El análisis tardó más de 3 minutos. Intenta de nuevo o con un pliego más corto.');
      toast('Tiempo de análisis agotado', 'warn');
      btn.disabled = false; btn.textContent = '📋 Generar Observaciones al Pliego';
      return;
    }

    const seg = Math.round(elapsed / 1000);
    resDiv.innerHTML = `<div class="loading">
      Analizando con IA... ${seg}s — puede tardar hasta 90s
    </div>`;

    try {
      const estado = await apiJson(`/api/observaciones/estado/${jobId}`, { method: 'GET' });
      if (estado.estado === 'completo') {
        _renderObsResult(estado.datos, resDiv);
        btn.disabled = false; btn.textContent = '📋 Generar Observaciones al Pliego';
        return;
      }
      if (estado.estado === 'error') {
        resDiv.innerHTML = `<div class="alert alert-error">${estado.mensaje||'Error en el análisis'}</div>`;
        toast(`Error: ${estado.mensaje}`, 'error');
        btn.disabled = false; btn.textContent = '📋 Generar Observaciones al Pliego';
        return;
      }
      // estado === 'procesando' → seguir haciendo polling
      setTimeout(poll, POLL_MS);
    } catch (err) {
      // error de red al consultar estado → reintentar
      setTimeout(poll, POLL_MS);
    }
  };

  setTimeout(poll, POLL_MS);
}

function descargarObservaciones(filename) {
  checkTesterPremium('descargar_pdf_observaciones', () => _descargarObsImpl(filename));
}
async function _descargarObsImpl(filename) {
  if (!CLIENTE_ID || !filename) { toast('PDF no disponible', 'warn'); return; }
  try {
    const res = await api(`/api/observaciones/pdf/${CLIENTE_ID}/${encodeURIComponent(filename)}`);
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
    toast('PDF descargado', 'success');
  } catch (err) { toast(`Error descargando PDF: ${err.message}`, 'error'); }
}

// ════════════ EXPEDIENTES ════════════
async function loadExpedientes() {
  const el = document.getElementById('exp-list');
  el.innerHTML = '<div class="loading">Cargando expedientes...</div>';
  try {
    const data = await apiJson(`/api/expedientes/${CLIENTE_ID}`);
    const exps  = data.expedientes || [];
    if (!exps.length) {
      el.innerHTML = '<div class="empty-state">Sin expedientes. Agrega procesos desde la Búsqueda (📋).</div>';
      return;
    }
    el.innerHTML = exps.map(e => {
      // gestor_expedientes devuelve e.urgencia = { nivel, dias_manif, dias_cierre }
      const urgObj  = e.urgencia || {};
      const urg     = (typeof urgObj === 'string' ? urgObj : urgObj.nivel || 'verde').toLowerCase();
      const urgLbl  = { rojo: '🔴 Urgente', amarillo: '🟡 Atención', verde: '🟢 Normal' }[urg] || '🟢 Normal';
      const diasStr = urgObj.dias_cierre != null ? `${urgObj.dias_cierre} días para cierre` : '';
      const estados = ['En seguimiento','Documentación en preparación','Oferta enviada','Adjudicado','No adjudicado','Descartado'];
      const opts    = estados.map(s =>
        `<option value="${s}" ${(e.estado_interno || 'En seguimiento') === s ? 'selected':''}>${s}</option>`
      ).join('');
      const pid = e.proceso_id || '';
      return `<div class="exp-card ${urg}">
        <div class="exp-header">
          <span class="urg-dot ${urg}"></span>
          <div class="exp-nombre">${(e.nombre || 'Sin nombre').substring(0,75)}</div>
          <span class="urg-label">${urgLbl}</span>
        </div>
        <div class="exp-meta">
          <span>${e.entidad || '—'}</span>
          <span>${fmtCOP(e.valor || 0)}</span>
          ${diasStr ? `<span>${diasStr}</span>` : `<span>Cierre: ${fmtDate(e.fecha_cierre_oferta)}</span>`}
          ${e.score_viabilidad ? `<span class="score-badge score-mid">Score ${e.score_viabilidad}</span>` : ''}
        </div>
        <div class="exp-footer">
          <select class="select-sm" onchange="cambiarEstado('${pid}', this.value)">${opts}</select>
          <button class="btn btn-ghost btn-xs" onclick="precargaAuditoriaFromExp('${encodeURIComponent(JSON.stringify(e))}')">📂 Auditar</button>
          ${e.url ? `<a class="btn btn-ghost btn-xs" href="${e.url}" target="_blank" rel="noopener">🔗 SECOP</a>` : ''}
        </div>
      </div>`;
    }).join('');
  } catch (err) {
    el.innerHTML = alertHtml('error', err.message);
  }
}

async function cambiarEstado(pid, estado) {
  try {
    await apiJson('/api/expedientes/estado', {
      method: 'PUT',
      body: JSON.stringify({ cliente_id: CLIENTE_ID, proceso_id: pid, nuevo_estado: estado }),
    });
    toast(`Estado → ${estado}`, 'success');
  } catch (err) { toast(err.message, 'error'); }
}

function precargaAuditoriaFromExp(enc) {
  const e = JSON.parse(decodeURIComponent(enc));
  sessionStorage.setItem('siaco_precarg_entidad', e.entidad || '');
  sessionStorage.setItem('siaco_precarg_objeto',  e.nombre  || '');
  sessionStorage.setItem('siaco_precarg_valor',   e.valor   || '');
  sessionStorage.setItem('siaco_precarg_url',     e.url     || '');
  sessionStorage.setItem('siaco_precarg_pid',     e.proceso_id || '');
  navigateTo('auditoria');
}

// ════════════ COMPETIDORES (PREMIUM) ════════════
setupUpload('comp-upload-area', 'comp-file', 'comp-filename', 'btn-extraer-comp');
document.getElementById('btn-extraer-comp').addEventListener('click', extraerOfertaComp);
document.getElementById('btn-estrategia').addEventListener('click', generarEstrategia);

document.getElementById('comp-proceso').addEventListener('input', function () {
  const pid = this.value.trim();
  document.getElementById('comp-proceso-label').textContent = pid ? `Competidores: ${pid}` : 'Competidores analizados';
  document.getElementById('btn-estrategia').disabled = !pid;
  if (pid) listarCompetidores(pid);
});

async function extraerOfertaComp() {
  if (PLAN !== 'premium' && PLAN !== 'admin') { toast('Plan Premium requerido', 'warn'); return; }
  const file    = document.getElementById('comp-file').files[0];
  const proceso = val('comp-proceso');
  const nit     = val('comp-nit');
  if (!file || !proceso || !nit) { toast('Completa proceso, NIT y PDF', 'warn'); return; }

  const btn  = document.getElementById('btn-extraer-comp');
  const stEl = document.getElementById('comp-status');
  btn.disabled = true; btn.textContent = 'Extrayendo...';
  stEl.innerHTML = alertHtml('info', 'Analizando oferta PDF del competidor...');

  const fd = new FormData();
  fd.append('proceso_id', proceso);
  fd.append('nit_competidor', nit);
  fd.append('nombre_competidor', val('comp-nombre'));
  fd.append('pdf', file);
  try {
    await apiJson('/api/competidores/extraer', { method: 'POST', body: fd });
    stEl.innerHTML = alertHtml('success', `✓ Oferta del competidor ${nit} analizada y guardada.`);
    toast('Oferta analizada', 'success');
    listarCompetidores(proceso);
  } catch (err) {
    stEl.innerHTML = alertHtml('error', err.message);
  } finally { btn.disabled = false; btn.textContent = 'Analizar oferta PDF'; }
}

async function listarCompetidores(pid) {
  if (!pid) return;
  const el = document.getElementById('comp-list');
  try {
    const data = await apiJson(`/api/competidores/${encodeURIComponent(pid)}`);
    const lista = data.competidores || [];
    if (!lista.length) {
      el.innerHTML = '<div class="empty-state">Sin competidores analizados para este proceso.</div>';
      return;
    }
    el.innerHTML = `<div class="table-wrap"><table class="data-table">
      <thead><tr><th>NIT</th><th>Nombre</th><th>Valor oferta</th><th>Técnico</th><th>Financiero</th><th>Fortalezas</th></tr></thead>
      <tbody>${lista.map(c => { const d = c.datos || c; return `<tr>
        <td>${c.nit||'—'}</td><td>${d.nombre||'—'}</td>
        <td>${fmtCOP(d.valor_oferta||0)}</td>
        <td>${d.puntaje_tecnico||'—'}</td><td>${d.capacidad_financiera||'—'}</td>
        <td>${(d.fortalezas||[]).join(', ')||'—'}</td>
      </tr>`; }).join('')}</tbody>
    </table></div>`;
  } catch (err) { el.innerHTML = alertHtml('error', err.message); }
}

async function generarEstrategia() {
  const pid = val('comp-proceso');
  if (!pid) { toast('Ingresa el ID del proceso', 'warn'); return; }
  const btn = document.getElementById('btn-estrategia');
  const el  = document.getElementById('comp-estrategia');
  btn.disabled = true; btn.textContent = '⏳ Generando...';
  el.style.display = '';
  el.innerHTML = alertHtml('info', 'Claude generando estrategia de oferta...');
  try {
    const data = await apiJson(`/api/competidores/estrategia/${encodeURIComponent(pid)}`, { method: 'POST' });
    const est  = data.estrategia || {};
    el.innerHTML = `<div class="card">
      <div class="card-title">🎯 Estrategia — ${data.num_competidores||0} competidor(es)</div>
      ${est.resumen ? `<div class="analisis-texto">${est.resumen}</div>` : ''}
      ${est.precio_recomendado ? `<p>Precio objetivo: <strong>${fmtCOP(est.precio_recomendado)}</strong></p>` : ''}
      ${est.ventajas_competitivas?.length ? `<p><strong>Ventajas:</strong></p><ul>${est.ventajas_competitivas.map(v=>`<li>${v}</li>`).join('')}</ul>` : ''}
      ${est.recomendaciones?.length ? `<p><strong>Recomendaciones:</strong></p><ul>${est.recomendaciones.map(v=>`<li>${v}</li>`).join('')}</ul>` : ''}
      ${est.contenido_completo ? `<div class="analisis-texto" style="white-space:pre-wrap">${est.contenido_completo}</div>` : ''}
    </div>`;
    toast('Estrategia generada', 'success');
  } catch (err) {
    el.innerHTML = alertHtml('error', err.message);
  } finally { btn.disabled = false; btn.textContent = '🎯 Generar estrategia'; }
}

// ════════════ HELPER: UPLOAD AREAS ════════════
function setupUpload(areaId, inputId, nameId, btnId) {
  const area   = document.getElementById(areaId);
  const input  = document.getElementById(inputId);
  const nameEl = document.getElementById(nameId);
  const btn    = document.getElementById(btnId);
  if (!area || !input) return;

  area.addEventListener('click', e => { if (e.target !== input) input.click(); });
  area.addEventListener('dragover',  e => { e.preventDefault(); area.classList.add('drag-over'); });
  area.addEventListener('dragleave', () => area.classList.remove('drag-over'));
  area.addEventListener('drop', e => {
    e.preventDefault(); area.classList.remove('drag-over');
    if (e.dataTransfer.files[0]) {
      const dt = new DataTransfer();
      dt.items.add(e.dataTransfer.files[0]);
      input.files = dt.files;
      setNombreUpload(input.files[0].name);
    }
  });
  input.addEventListener('change', () => { if (input.files[0]) setNombreUpload(input.files[0].name); });

  function setNombreUpload(name) {
    if (nameEl) nameEl.textContent = name;
    if (btn) btn.disabled = false;
  }
}

// ─── Mini upload (documentos adicionales auditoría) ──
function setupUploadMini(areaId, inputId, nameId) {
  const area   = document.getElementById(areaId);
  const input  = document.getElementById(inputId);
  const nameEl = document.getElementById(nameId);
  if (!area || !input) return;

  area.addEventListener('click', e => { if (e.target !== input) input.click(); });
  area.addEventListener('dragover',  e => { e.preventDefault(); area.classList.add('drag-over'); });
  area.addEventListener('dragleave', () => area.classList.remove('drag-over'));
  area.addEventListener('drop', e => {
    e.preventDefault(); area.classList.remove('drag-over');
    if (e.dataTransfer.files[0]) {
      const dt = new DataTransfer();
      dt.items.add(e.dataTransfer.files[0]);
      input.files = dt.files;
      if (nameEl) nameEl.textContent = e.dataTransfer.files[0].name;
    }
  });
  input.addEventListener('change', () => {
    if (input.files[0] && nameEl) nameEl.textContent = input.files[0].name;
  });
}

// ════════════ CHAT ASISTENTE ════════════
let _chatAbierto = false;
let _chatIniciado = false;

function toggleChat() {
  _chatAbierto = !_chatAbierto;
  const panel = document.getElementById('chat-panel');
  panel.style.display = _chatAbierto ? 'flex' : 'none';
  if (_chatAbierto && !_chatIniciado) {
    _chatIniciado = true;
    _appendChatMsg('assistant', '¡Hola! Soy tu asesor de contratación pública. Puedo guiarte paso a paso para aplicar a esta licitación. ¿Por dónde quieres empezar?');
  }
  if (_chatAbierto) {
    const inp = document.getElementById('chat-input');
    if (inp) inp.focus();
  }
}

function limpiarChat() {
  _chatIniciado = false;
  const msgs = document.getElementById('chat-msgs');
  if (msgs) msgs.innerHTML = '';
  api('/api/chat/historial', { method: 'DELETE' }).catch(() => {});
  _appendChatMsg('assistant', '¡Hola! Soy tu asesor de contratación pública. Puedo guiarte paso a paso para aplicar a esta licitación. ¿Por dónde quieres empezar?');
  _chatIniciado = true;
}

function _appendChatMsg(role, text) {
  const msgs = document.getElementById('chat-msgs');
  if (!msgs) return;
  const div = document.createElement('div');
  div.className = `chat-bubble chat-${role}`;
  div.textContent = text;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

async function sendChat() {
  const input  = document.getElementById('chat-input');
  const sendBtn= document.getElementById('btn-chat-send');
  const msg    = (input?.value || '').trim();
  if (!msg) return;

  input.value = '';
  input.style.height = '';
  sendBtn.disabled = true;
  _appendChatMsg('user', msg);

  // Indicador "escribiendo..."
  const msgs = document.getElementById('chat-msgs');
  const typing = document.createElement('div');
  typing.className = 'chat-bubble chat-assistant chat-typing';
  typing.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
  msgs.appendChild(typing);
  msgs.scrollTop = msgs.scrollHeight;

  // Contexto de la pantalla actual y contrato seleccionado
  const activePage = document.querySelector('.page.active')?.id?.replace('page-', '') || '';
  const ctx = {};
  if (_selIdx >= 0 && _contratos[_selIdx]) {
    const c = _contratos[_selIdx];
    ctx.nombre  = c.nombre_del_procedimiento || '';
    ctx.entidad = c.entidad || '';
    ctx.valor   = c.precio_base ? fmtCOP(c.precio_base) : '';
  }

  try {
    const data = await apiJson('/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        mensaje:           msg,
        pantalla_actual:   activePage,
        cliente_id:        CLIENTE_ID,
        contexto_contrato: ctx,
      }),
    });
    typing.remove();
    _appendChatMsg('assistant', data.respuesta);
  } catch (err) {
    typing.remove();
    _appendChatMsg('assistant', `Lo siento, ocurrió un error: ${err.message}`);
  } finally {
    sendBtn.disabled = false;
    if (input) input.focus();
  }
}

// Enter = enviar, Shift+Enter = nueva línea
document.getElementById('chat-input')?.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
});

// ════════════ BÚSQUEDA AVANZADA ════════════
document.getElementById('btn-busq-avanzada')?.addEventListener('click', ejecutarBusquedaAvanzada);
document.getElementById('btn-busq-avanzada-limpiar')?.addEventListener('click', () => {
  ['adv-codigo-proceso','adv-nit','adv-municipio','adv-keywords','adv-unspsc',
   'adv-valor-min','adv-valor-max','adv-fecha-desde','adv-fecha-hasta'].forEach(id => setVal(id, ''));
  setVal('adv-departamento', '');
  setVal('adv-modalidad', '');
});

async function ejecutarBusquedaAvanzada() {
  const campos = [
    ['adv-codigo-proceso', 'codigo_proceso'],
    ['adv-nit',            'nit_entidad'],
    ['adv-municipio',      'municipio'],
    ['adv-departamento',   'departamento'],
    ['adv-modalidad',      'modalidad'],
    ['adv-valor-min',      'valor_min'],
    ['adv-valor-max',      'valor_max'],
    ['adv-fecha-desde',    'fecha_desde'],
    ['adv-fecha-hasta',    'fecha_hasta'],
    ['adv-keywords',       'keywords'],
    ['adv-unspsc',         'unspsc'],
  ];

  const params = new URLSearchParams();
  let hayFiltro = false;
  for (const [id, param] of campos) {
    const v = val(id);
    if (v) { params.append(param, v); hayFiltro = true; }
  }

  if (!hayFiltro) {
    toast('Ingresa al menos un criterio de búsqueda avanzada', 'warn');
    return;
  }

  const stEl  = document.getElementById('busq-status');
  const resEl = document.getElementById('busq-results');
  stEl.innerHTML = alertHtml('info', 'Buscando en SECOP II...');
  resEl.style.display = 'none';

  // Cerrar el panel desplegable para ver resultados
  const details = document.getElementById('busq-avanzada-details');
  if (details) details.open = false;

  try {
    const data = await apiJson(`/api/contratos/busqueda-avanzada?${params.toString()}`);
    _contratos   = data.contratos || [];
    _descartados = [];

    const aviso = data.advertencia
      ? alertHtml('warn', `⚠ ${data.advertencia}`)
      : '';
    stEl.innerHTML = aviso;

    renderTablaAvanzada(_contratos, data.busqueda_exacta);
    resEl.style.display = '';

    document.getElementById('btn-analizar-ia').disabled = !_contratos.length;
  } catch (err) {
    stEl.innerHTML = alertHtml('error', err.message);
  }
}

function renderTablaAvanzada(lista, exacta) {
  txt('busq-count', `${lista.length} resultado${lista.length !== 1 ? 's' : ''} — búsqueda avanzada`);
  const tbody = document.getElementById('tabla-body');
  tbody.innerHTML = lista.map((c, i) => {
    const nombre  = (c.nombre_del_procedimiento || 'Sin nombre').substring(0, 65);
    const entidad = (c.entidad || '—').substring(0, 32);
    const dias    = c._dias_cierre != null ? `${c._dias_cierre}d` : '—';
    const badge   = `<span class="badge-avanzada">ADV</span>`;
    const scoreIa = c._score_ia != null ? c._score_ia : null;
    const clsIA   = scoreIa >= 70 ? 'score-high' : scoreIa >= 40 ? 'score-mid' : 'score-low';
    const cellIa  = scoreIa != null
      ? `<span class="score-num-sm ${clsIA}">${scoreIa}</span>`
      : `<span class="score-num-sm" style="color:var(--muted)">—</span>`;
    return `<tr class="${c._urgente ? 'urgente' : ''}" data-idx="${i}">
      <td>${badge}</td>
      <td class="td-num">${cellIa}</td>
      <td class="td-nombre">
        <span class="td-nombre-link" onclick="abrirDetalle(${i})" title="Ver detalle">${nombre}${c._urgente ? ' <span class="urg-tag">URG</span>' : ''}</span>
      </td>
      <td class="td-sm">${entidad}</td>
      <td class="td-num">${fmtCOP(c.precio_base || 0)}</td>
      <td class="td-sm">${c.fase || c.estado_del_procedimiento || '—'}</td>
      <td class="td-num">${dias}</td>
      <td class="td-actions">
        <button class="btn btn-ghost btn-xs" onclick="abrirDetalle(${i})" title="Ver detalle">👁</button>
        <button class="btn btn-ghost btn-xs" onclick="precargaAuditoria(${i})" title="Auditar">📂</button>
        <button class="btn btn-ghost btn-xs" onclick="agregarExpediente(${i})" title="Expediente">📋</button>
      </td>
    </tr>`;
  }).join('');

  const discSec = document.getElementById('disc-section');
  if (discSec) discSec.style.display = 'none';
}

// ════════════ ADMIN ════════════
let _admCredenciales = {};

function toggleDiasAcceso() {
  const tipo = document.getElementById('adm-tipo')?.value;
  const diasGroup = document.getElementById('adm-dias-group');
  if (diasGroup) diasGroup.style.display = tipo === 'tester' ? '' : 'none';
}

async function cargarListaClientes() {
  const el = document.getElementById('admin-clientes-lista');
  if (!el) return;
  el.innerHTML = '<div style="color:var(--muted);font-size:.85rem">Cargando...</div>';
  try {
    const data = await apiJson('/api/admin/clientes');
    const lista = data.clientes || [];
    if (!lista.length) {
      el.innerHTML = '<div style="color:var(--muted);font-size:.85rem">No hay clientes registrados.</div>';
      return;
    }
    el.innerHTML = `<div class="table-wrap"><table class="data-table" style="font-size:.82rem">
      <thead><tr>
        <th>Usuario</th><th>Empresa</th><th>Plan</th><th>Tipo</th>
        <th>Estado</th><th>Funciones usadas</th><th>Acciones</th>
      </tr></thead>
      <tbody>${lista.map(c => {
        const tipo = c.tipo || 'cliente';
        const badge = tipo === 'tester'
          ? '<span class="admin-client-badge badge-tester">🧪 Tester</span>'
          : tipo === 'admin'
          ? '<span class="admin-client-badge badge-admin-b">👑 Admin</span>'
          : '<span class="admin-client-badge badge-cliente">✅ Cliente</span>';
        const dias = tipo === 'tester' && c.dias_restantes !== undefined
          ? `<span class="${c.dias_restantes <= 2 ? 'dias-critico' : 'dias-restantes'}">${c.dias_restantes}d restantes</span>`
          : c.activo
          ? '<span style="color:var(--ok)">Activo</span>'
          : '<span style="color:var(--danger)">Inactivo</span>';
        const usos = tipo === 'tester' && c.usos_premium
          ? Object.entries(c.usos_premium).map(([k, v]) =>
              `<span style="font-size:.72rem;display:block">${v ? '✅' : '⏳'} ${k.replace(/_/g,' ')}</span>`
            ).join('')
          : '—';
        const acciones = tipo === 'tester'
          ? `<button class="btn" style="font-size:.72rem;padding:3px 8px;margin-bottom:4px;display:block"
               onclick="extenderAcceso('${c.cliente_id}')">+7 días</button>
             <button class="btn btn-primary" style="font-size:.72rem;padding:3px 8px;display:block"
               onclick="convertirACliente('${c.cliente_id}')">→ Cliente</button>`
          : '—';
        return `<tr>
          <td style="font-family:var(--mono);font-size:.78rem">${c.cliente_id}</td>
          <td>${c.nombre || '—'}</td>
          <td>${c.plan || '—'}</td>
          <td>${badge}</td>
          <td>${dias}</td>
          <td style="line-height:1.8">${usos}</td>
          <td>${acciones}</td>
        </tr>`;
      }).join('')}
      </tbody></table></div>`;
  } catch (err) {
    el.innerHTML = `<div style="color:var(--danger);font-size:.85rem">${err.message}</div>`;
  }
}

async function extenderAcceso(username) {
  try {
    await apiJson(`/api/admin/clientes/${encodeURIComponent(username)}/extender`, { method: 'POST' });
    toast(`Acceso de ${username} extendido 7 días`, 'ok');
    cargarListaClientes();
  } catch (err) { toast(err.message, 'error'); }
}

async function convertirACliente(username) {
  if (!confirm(`¿Convertir a ${username} de Tester a Cliente?`)) return;
  try {
    await apiJson(`/api/admin/clientes/${encodeURIComponent(username)}/convertir`, { method: 'POST' });
    toast(`${username} convertido a Cliente`, 'ok');
    cargarListaClientes();
  } catch (err) { toast(err.message, 'error'); }
}

function toggleFormNuevoCliente() {
  const form = document.getElementById('card-nuevo-cliente');
  const cred = document.getElementById('card-credenciales');
  if (form.style.display === 'none') {
    form.style.display = '';
    cred.style.display = 'none';
    setTimeout(() => document.getElementById('adm-nombre').focus(), 50);
  } else {
    form.style.display = 'none';
  }
}

function sugerirUsuario() {
  const nit = document.getElementById('adm-nit').value;
  document.getElementById('adm-user').value = 'nit' + nit.replace(/[^0-9]/g, '');
}

async function crearCliente(e) {
  e.preventDefault();
  const btn = document.getElementById('btn-crear-cliente');
  btn.disabled = true;
  btn.textContent = 'Creando…';
  try {
    const body = {
      nombre_empresa: document.getElementById('adm-nombre').value.trim(),
      nit:            document.getElementById('adm-nit').value.trim(),
      username:       document.getElementById('adm-user').value.trim(),
      password:       document.getElementById('adm-pass').value.trim(),
      sector:         document.getElementById('adm-sector').value,
      plan:           document.getElementById('adm-plan').value,
      tipo:           document.getElementById('adm-tipo')?.value || 'cliente',
      dias_acceso:    parseInt(document.getElementById('adm-dias')?.value || '7'),
      email:          document.getElementById('adm-email').value.trim(),
      whatsapp:       document.getElementById('adm-wa').value.trim(),
    };
    await apiJson('/api/admin/clientes', { method: 'POST', body: JSON.stringify(body) });
    _admCredenciales = body;
    mostrarCredenciales(body);
    toast('Cliente creado exitosamente', 'ok');
  } catch (err) {
    toast(err.message, 'error');
    btn.disabled = false;
    btn.textContent = 'Crear cliente';
  }
}

function mostrarCredenciales(c) {
  document.getElementById('card-nuevo-cliente').style.display = 'none';
  const cred = document.getElementById('card-credenciales');
  cred.style.display = '';
  document.getElementById('cred-resumen').innerHTML = `
    <div style="display:grid;grid-template-columns:auto 1fr;gap:8px 24px;font-size:.9rem;margin-top:10px;line-height:1.6">
      <span style="color:var(--muted)">Empresa</span>   <span>${c.nombre_empresa}</span>
      <span style="color:var(--muted)">NIT</span>        <span>${c.nit}</span>
      <span style="color:var(--muted)">Usuario</span>    <strong style="font-family:var(--mono)">${c.username}</strong>
      <span style="color:var(--muted)">Contraseña</span> <strong style="font-family:var(--mono);color:var(--accent)">${c.password}</strong>
      <span style="color:var(--muted)">Plan</span>       <span>${c.plan}</span>
    </div>`;
  cred.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function copiarCredenciales() {
  const c = _admCredenciales;
  const msg = `Bienvenido a SIACO, ${c.nombre_empresa}.\nSu usuario: ${c.username}\nSu contraseña temporal: ${c.password}\nIngrese en: https://siaco-production.up.railway.app`;
  navigator.clipboard.writeText(msg)
    .then(() => toast('Credenciales copiadas al portapapeles', 'ok'))
    .catch(() => toast('No se pudo copiar automáticamente', 'warn'));
}

function nuevoClienteForm() {
  document.getElementById('card-credenciales').style.display = 'none';
  const form = document.getElementById('card-nuevo-cliente');
  form.style.display = '';
  document.getElementById('form-nuevo-cliente').reset();
  document.getElementById('btn-crear-cliente').disabled = false;
  document.getElementById('btn-crear-cliente').textContent = 'Crear cliente';
  setTimeout(() => document.getElementById('adm-nombre').focus(), 50);
}

function descargarContrato() {
  const a = document.createElement('a');
  a.href     = '/api/contrato/descargar';
  a.download = 'Contrato_Servicios_SIACO.docx';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ════════════ CALCULADORA APU ════════════
let _apuLastResult = null;
let _apuMatIdx = 0, _apuMoIdx = 0, _apuEqIdx = 0;
let _apuLastFlujo = null;

// Factor prestacional 2026 — FACTOR_PRESTACIONAL_CON_AUXILIO=0.5238 → multiplicador total
const APU_FACTOR_PREST = 1.5238;

// ── Agregar filas ─────────────────────────────────────────────────────────
function apu_agregarMaterial() {
  const idx = _apuMatIdx++;
  const tr  = document.createElement('tr');
  tr.id = `apu-mat-row-${idx}`;
  tr.innerHTML = `
    <td><input class="apu-td-input" data-apu="nombre" placeholder="Descripción" oninput="apu_calcularLocal()" /></td>
    <td><input class="apu-td-input" data-apu="unidad" placeholder="und" style="width:60px" /></td>
    <td><input class="apu-td-input" data-apu="cantidad" type="number" value="1" min="0" step="0.01" oninput="apu_calcularLocal()" /></td>
    <td><input class="apu-td-input" data-apu="precio" type="number" value="0" min="0" step="1000" oninput="apu_calcularLocal()" /></td>
    <td class="apu-td-total" id="apu-mat-rt-${idx}">$0</td>
    <td><button class="apu-btn-del" onclick="apu_delFila('mat',${idx})">✕</button></td>`;
  document.getElementById('apu-mat-body').appendChild(tr);
  apu_calcularLocal();
}

function apu_agregarPersonal() {
  const idx = _apuMoIdx++;
  const tr  = document.createElement('tr');
  tr.id = `apu-mo-row-${idx}`;
  tr.innerHTML = `
    <td><input class="apu-td-input" data-apu="cargo" placeholder="Cargo" oninput="apu_calcularLocal()" /></td>
    <td><input class="apu-td-input" data-apu="salario" type="number" value="1423500" min="0" step="50000" oninput="apu_calcularLocal()" /></td>
    <td><input class="apu-td-input" data-apu="cant" type="number" value="1" min="1" style="width:52px" oninput="apu_calcularLocal()" /></td>
    <td><input class="apu-td-input" data-apu="dias" type="number" value="30" min="1" style="width:58px" oninput="apu_calcularLocal()" /></td>
    <td class="apu-td-total" id="apu-mo-fp-${idx}" style="color:var(--text2)">52.17%</td>
    <td class="apu-td-total" id="apu-mo-rt-${idx}">$0</td>
    <td><button class="apu-btn-del" onclick="apu_delFila('mo',${idx})">✕</button></td>`;
  document.getElementById('apu-mo-body').appendChild(tr);
  apu_calcularLocal();
}

function apu_agregarEquipo() {
  const idx = _apuEqIdx++;
  const tr  = document.createElement('tr');
  tr.id = `apu-eq-row-${idx}`;
  tr.innerHTML = `
    <td><input class="apu-td-input" data-apu="nombre" placeholder="Equipo o herramienta" oninput="apu_calcularLocal()" /></td>
    <td><input class="apu-td-input" data-apu="costo_dia" type="number" value="0" min="0" step="5000" oninput="apu_calcularLocal()" /></td>
    <td><input class="apu-td-input" data-apu="dias" type="number" value="1" min="1" oninput="apu_calcularLocal()" /></td>
    <td class="apu-td-total" id="apu-eq-rt-${idx}">$0</td>
    <td><button class="apu-btn-del" onclick="apu_delFila('eq',${idx})">✕</button></td>`;
  document.getElementById('apu-eq-body').appendChild(tr);
  apu_calcularLocal();
}

function apu_delFila(tipo, idx) {
  const row = document.getElementById(`apu-${tipo}-row-${idx}`);
  if (row) row.remove();
  apu_calcularLocal();
}

// ── Cálculo local en tiempo real (sin API) ────────────────────────────────
function apu_calcularLocal() {
  // Materiales
  let totMat = 0;
  document.querySelectorAll('#apu-mat-body tr').forEach(tr => {
    const cant  = parseFloat(tr.querySelector('[data-apu="cantidad"]')?.value) || 0;
    const precio = parseFloat(tr.querySelector('[data-apu="precio"]')?.value) || 0;
    const sub = cant * precio;
    totMat += sub;
    const idx = tr.id.replace('apu-mat-row-', '');
    const cell = document.getElementById(`apu-mat-rt-${idx}`);
    if (cell) cell.textContent = fmtCOP(sub);
  });

  // Mano de obra
  let totMO = 0;
  document.querySelectorAll('#apu-mo-body tr').forEach(tr => {
    const salario = parseFloat(tr.querySelector('[data-apu="salario"]')?.value) || 0;
    const cant    = parseFloat(tr.querySelector('[data-apu="cant"]')?.value) || 1;
    const dias    = parseFloat(tr.querySelector('[data-apu="dias"]')?.value) || 30;
    const costoMes = salario * APU_FACTOR_PREST;
    const costo   = costoMes * cant * (dias / 30);
    totMO += costo;
    const idx = tr.id.replace('apu-mo-row-', '');
    const fp  = document.getElementById(`apu-mo-fp-${idx}`);
    const rt  = document.getElementById(`apu-mo-rt-${idx}`);
    if (fp) fp.textContent = `${((APU_FACTOR_PREST - 1) * 100).toFixed(2)}%`;
    if (rt) rt.textContent = fmtCOP(costo);
  });

  // Equipos
  let totEQ = 0;
  document.querySelectorAll('#apu-eq-body tr').forEach(tr => {
    const costoDia = parseFloat(tr.querySelector('[data-apu="costo_dia"]')?.value) || 0;
    const dias     = parseFloat(tr.querySelector('[data-apu="dias"]')?.value) || 1;
    const sub = costoDia * dias;
    totEQ += sub;
    const idx = tr.id.replace('apu-eq-row-', '');
    const cell = document.getElementById(`apu-eq-rt-${idx}`);
    if (cell) cell.textContent = fmtCOP(sub);
  });

  // Totales de sección
  const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = fmtCOP(v); };
  setTxt('apu-mat-total', totMat);
  setTxt('apu-mo-total',  totMO);
  setTxt('apu-eq-total',  totEQ);

  // AIU
  const adminPct  = (parseFloat(document.getElementById('apu-admin')?.value)  || 12) / 100;
  const imprevPct = (parseFloat(document.getElementById('apu-imprev')?.value) || 3)  / 100;
  const utilPct   = (parseFloat(document.getElementById('apu-util')?.value)   || 8)  / 100;
  const directos  = totMat + totMO + totEQ;
  const admin     = directos * adminPct;
  const imprev    = directos * imprevPct;
  const utilidad  = directos * utilPct;

  setTxt('apu-admin-val',  admin);
  setTxt('apu-imprev-val', imprev);
  setTxt('apu-util-val',   utilidad);

  const precioMin = directos + admin + imprev + utilidad;
  const precioSug = precioMin * 1.05;
  const margenPct = precioMin > 0 ? ((utilidad / precioMin) * 100).toFixed(1) : '0.0';

  // Resultados
  if (directos > 0 || admin > 0) {
    const resDiv = document.getElementById('apu-resultados');
    if (resDiv) resDiv.style.display = '';

    setTxt('apu-res-minimo',   precioMin);
    setTxt('apu-res-sugerido', precioSug);
    setTxt('apu-res-utilidad', utilidad);
    const m = document.getElementById('apu-res-margen'); if (m) m.textContent = `${margenPct}%`;

    const desglose = document.getElementById('apu-res-desglose');
    if (desglose) desglose.innerHTML = `
      <div>Materiales:</div>   <div style="font-family:var(--mono);text-align:right">${fmtCOP(totMat)}</div>
      <div>Mano de obra:</div> <div style="font-family:var(--mono);text-align:right">${fmtCOP(totMO)}</div>
      <div>Equipos:</div>      <div style="font-family:var(--mono);text-align:right">${fmtCOP(totEQ)}</div>
      <div>AIU (${((adminPct+imprevPct+utilPct)*100).toFixed(1)}%):</div>
      <div style="font-family:var(--mono);text-align:right">${fmtCOP(admin+imprev+utilidad)}</div>`;
  }

  // Viabilidad rápida (sin pólizas — el servidor las añade)
  const presupuesto = parseFloat(document.getElementById('apu-presupuesto')?.value) || 0;
  const viabCard    = document.getElementById('apu-viabilidad-card');
  if (viabCard && presupuesto > 0 && precioMin > 0) {
    viabCard.style.display = '';
    const diff      = presupuesto - precioMin;
    const mViab     = ((diff / presupuesto) * 100).toFixed(1);
    let concepto, css, icon, recom;
    if (diff < 0) {
      concepto='INVIABLE'; css='danger'; icon='❌';
      recom=`Presupuesto ${fmtCOP(presupuesto)} menor que precio mínimo ${fmtCOP(precioMin)}. Reduzca costos.`;
    } else if (parseFloat(mViab) < 8) {
      concepto='AJUSTADO'; css='warn'; icon='⚠️';
      recom=`Margen disponible ${mViab}% — estrecho. Revise las partidas de mayor peso.`;
    } else {
      concepto='VIABLE'; css='ok'; icon='✅';
      recom=`Margen de ${mViab}% sobre precio mínimo. Puede presentar una oferta competitiva.`;
    }
    viabCard.className = `card viab-${concepto.toLowerCase()}`;
    const vc = document.getElementById('apu-viabilidad-content');
    if (vc) vc.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:12px">
        <div><div style="font-size:.72rem;color:var(--muted)">Presupuesto oficial</div>
          <div style="font-family:var(--mono);font-weight:600">${fmtCOP(presupuesto)}</div></div>
        <div><div style="font-size:.72rem;color:var(--muted)">Su precio mínimo</div>
          <div style="font-family:var(--mono);font-weight:600">${fmtCOP(precioMin)}</div></div>
        <div><div style="font-size:.72rem;color:var(--muted)">Margen disponible</div>
          <div style="font-family:var(--mono);font-weight:600;color:var(--${css})">${mViab}%</div></div>
      </div>
      <div class="viab-concepto ${css}">${icon} ${concepto}</div>
      <div style="font-size:.85rem;color:var(--text2)">${recom}</div>`;
  } else if (viabCard && presupuesto === 0) {
    viabCard.style.display = 'none';
  }
}

// ── Cálculo completo con servidor ─────────────────────────────────────────
async function apu_calcularServidor() {
  const btn  = document.getElementById('btn-apu-calcular');
  const stEl = document.getElementById('apu-calc-status');
  btn.disabled = true; btn.textContent = '⏳ Calculando...';
  stEl.textContent = '';
  try {
    const body = {
      materiales:      apu_leerMateriales(),
      personal:        apu_leerPersonal(),
      equipos:         apu_leerEquipos(),
      aiu: {
        admin_pct:       (parseFloat(document.getElementById('apu-admin').value)  || 12) / 100,
        imprevistos_pct: (parseFloat(document.getElementById('apu-imprev').value) || 3)  / 100,
        utilidad_pct:    (parseFloat(document.getElementById('apu-util').value)   || 8)  / 100,
      },
      plazo_meses:     parseInt(document.getElementById('apu-plazo').value)        || 6,
      incluir_polizas: document.getElementById('apu-polizas').checked,
    };
    const presupuesto = parseFloat(document.getElementById('apu-presupuesto').value) || 0;
    if (presupuesto > 0) body.presupuesto_oficial = presupuesto;

    const data = await apiJson('/api/calculadora/oferta', { method:'POST', body:JSON.stringify(body) });
    _apuLastResult = data;
    apu_renderResultados(data);
    document.getElementById('apu-flujo-card').style.display    = '';
    document.getElementById('apu-export-btns').style.display   = '';
    document.getElementById('apu-docs-section').style.display  = '';
    stEl.textContent = '✓ Cálculo completo con pólizas estimadas';
    toast('Oferta calculada', 'ok');
  } catch (err) {
    stEl.textContent = err.message;
    toast(err.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = '🧮 Calcular oferta completa';
  }
}

function apu_renderResultados(data) {
  const resDiv = document.getElementById('apu-resultados');
  if (resDiv) resDiv.style.display = '';

  const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = fmtCOP(v); };
  setTxt('apu-res-minimo',   data.precio_minimo);
  setTxt('apu-res-sugerido', data.precio_sugerido);
  setTxt('apu-res-utilidad', data.resumen?.utilidad_proyectada || 0);
  const m = document.getElementById('apu-res-margen');
  if (m) m.textContent = `${data.resumen?.margen_utilidad_pct || 0}%`;

  const cd  = data.costos_directos || {};
  const aiu = data.aiu || {};
  const des = document.getElementById('apu-res-desglose');
  if (des) des.innerHTML = `
    <div>Materiales:</div>   <div style="font-family:var(--mono);text-align:right">${fmtCOP(cd.materiales)}</div>
    <div>Mano de obra:</div> <div style="font-family:var(--mono);text-align:right">${fmtCOP(cd.mano_obra)}</div>
    <div>Equipos:</div>      <div style="font-family:var(--mono);text-align:right">${fmtCOP(cd.equipos)}</div>
    <div>AIU (${aiu.porcentaje_total || 0}%):</div>
    <div style="font-family:var(--mono);text-align:right">${fmtCOP(aiu.total_aiu)}</div>
    ${data.polizas_estimadas ? `<div>Pólizas est.:</div><div style="font-family:var(--mono);text-align:right">${fmtCOP(data.polizas_estimadas)}</div>` : ''}`;

  const viabCard = document.getElementById('apu-viabilidad-card');
  if (data.viabilidad && viabCard) {
    const v   = data.viabilidad;
    const csm = { VIABLE:'ok', AJUSTADO:'warn', INVIABLE:'danger' };
    const ico = { VIABLE:'✅', AJUSTADO:'⚠️', INVIABLE:'❌' };
    const css = csm[v.concepto] || 'ok';
    viabCard.style.display  = '';
    viabCard.className      = `card viab-${v.concepto.toLowerCase()}`;
    const vc = document.getElementById('apu-viabilidad-content');
    if (vc) vc.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:12px">
        <div><div style="font-size:.72rem;color:var(--muted)">Presupuesto oficial</div>
          <div style="font-family:var(--mono);font-weight:600">${fmtCOP(v.presupuesto_oficial)}</div></div>
        <div><div style="font-size:.72rem;color:var(--muted)">Su precio mínimo</div>
          <div style="font-family:var(--mono);font-weight:600">${fmtCOP(v.precio_minimo)}</div></div>
        <div><div style="font-size:.72rem;color:var(--muted)">Margen disponible</div>
          <div style="font-family:var(--mono);font-weight:600;color:var(--${css})">${v.margen_disponible_pct}%</div></div>
      </div>
      <div class="viab-concepto ${css}">${ico[v.concepto]} ${v.concepto}</div>
      <div style="font-size:.85rem;color:var(--text2)">${v.recomendacion}</div>`;
  }
}

// ── Leer filas de tablas ──────────────────────────────────────────────────
function apu_leerMateriales() {
  return Array.from(document.querySelectorAll('#apu-mat-body tr')).map(tr => ({
    nombre:          tr.querySelector('[data-apu="nombre"]')?.value.trim()  || '',
    unidad:          tr.querySelector('[data-apu="unidad"]')?.value.trim()  || 'und',
    cantidad:        parseFloat(tr.querySelector('[data-apu="cantidad"]')?.value)       || 0,
    precio_unitario: parseFloat(tr.querySelector('[data-apu="precio"]')?.value)          || 0,
  })).filter(i => i.cantidad > 0 || i.precio_unitario > 0);
}

function apu_leerPersonal() {
  return Array.from(document.querySelectorAll('#apu-mo-body tr')).map(tr => ({
    cargo:    tr.querySelector('[data-apu="cargo"]')?.value.trim() || 'Personal',
    salario:  parseFloat(tr.querySelector('[data-apu="salario"]')?.value) || 0,
    cantidad: parseInt(tr.querySelector('[data-apu="cant"]')?.value)      || 1,
    dias:     parseFloat(tr.querySelector('[data-apu="dias"]')?.value)    || 30,
  })).filter(i => i.salario > 0);
}

function apu_leerEquipos() {
  return Array.from(document.querySelectorAll('#apu-eq-body tr')).map(tr => ({
    nombre:    tr.querySelector('[data-apu="nombre"]')?.value.trim()      || 'Equipo',
    costo_dia: parseFloat(tr.querySelector('[data-apu="costo_dia"]')?.value) || 0,
    dias:      parseFloat(tr.querySelector('[data-apu="dias"]')?.value)   || 1,
  })).filter(i => i.costo_dia > 0);
}

// ── Flujo de caja ─────────────────────────────────────────────────────────
async function apu_calcularFlujo() {
  if (!_apuLastResult) { toast('Calcule la oferta primero', 'warn'); return; }
  try {
    const adminPct  = (parseFloat(document.getElementById('apu-admin')?.value)  || 12) / 100;
    const imprevPct = (parseFloat(document.getElementById('apu-imprev')?.value) || 3)  / 100;
    const utilPct   = (parseFloat(document.getElementById('apu-util')?.value)   || 8)  / 100;
    const body = {
      valor_contrato:  _apuLastResult.precio_minimo,
      anticipo_pct:    (parseFloat(document.getElementById('apu-anticipo').value) || 30) / 100,
      plazo_meses:     parseInt(document.getElementById('apu-plazo').value) || 6,
      costos_directos: _apuLastResult.costos_directos?.subtotal || 0,
      aiu_pct:         adminPct + imprevPct + utilPct,
    };
    const data = await apiJson('/api/calculadora/flujo-caja', { method:'POST', body:JSON.stringify(body) });
    _apuLastFlujo = data;

    const alertDiv = document.getElementById('apu-flujo-alertas');
    if (alertDiv) {
      const msgs = [];
      if (data.alerta_deficit) msgs.push('Déficit de flujo detectado — revise anticipo o plazo.');
      if (data.capital_trabajo_adicional > 0)
        msgs.push(`Capital de trabajo adicional requerido: ${fmtCOP(data.capital_trabajo_adicional)}`);
      alertDiv.innerHTML = msgs.map(a => `<div class="flujo-alerta">⚠️ ${a}</div>`).join('');
    }

    const resumenDiv = document.getElementById('apu-flujo-resumen');
    if (resumenDiv && data.resumen) resumenDiv.textContent = data.resumen;

    const meses = data.flujo_mensual || data.proyeccion || [];
    const tbody = document.getElementById('apu-flujo-body');
    if (tbody) tbody.innerHTML = meses.map(m => {
      const actaBruta = m.ingresos?.acta_cobrada ?? (typeof m.ingresos === 'number' ? m.ingresos : 0);
      const amort     = m.amortizacion_anticipo ?? 0;
      const egresos   = m.egresos?.total_egresos ?? (typeof m.egresos === 'number' ? m.egresos : 0);
      const flujoN    = m.flujo_neto_mes ?? m.saldo_mes ?? 0;
      const saldoAc   = m.saldo_acumulado ?? 0;
      const neg       = saldoAc < 0 ? 'class="flujo-negativo"' : '';
      const colorSaldo = saldoAc < 0 ? 'var(--danger)' : 'var(--ok)';
      return `<tr ${neg}>
        <td style="text-align:center">Mes ${m.mes}</td>
        <td style="font-family:var(--mono);text-align:right">${fmtCOP(actaBruta)}</td>
        <td style="font-family:var(--mono);text-align:right;color:var(--warn)">${fmtCOP(amort)}</td>
        <td style="font-family:var(--mono);text-align:right">${fmtCOP(egresos)}</td>
        <td style="font-family:var(--mono);text-align:right">${fmtCOP(flujoN)}</td>
        <td style="font-family:var(--mono);text-align:right;font-weight:600;color:${colorSaldo}">${fmtCOP(saldoAc)}</td>
      </tr>`;
    }).join('');

    const tabla = document.getElementById('apu-flujo-tabla');
    if (tabla) tabla.style.display = '';
    toast('Flujo de caja generado', 'ok');
  } catch (err) { toast(err.message, 'error'); }
}

// ── Exportaciones ─────────────────────────────────────────────────────────
async function apu_exportarExcel() {
  if (!_apuLastResult) { toast('Calcule la oferta primero', 'warn'); return; }
  try {
    const body = {
      materiales: apu_leerMateriales(),
      personal:   apu_leerPersonal(),
      equipos:    apu_leerEquipos(),
      resultado:  _apuLastResult,
      flujo:      _apuLastFlujo || {},
    };
    const res  = await api('/api/calculadora/exportar-excel', { method:'POST', body:JSON.stringify(body) });
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `SIACO_Analisis_Oferta_${new Date().toISOString().slice(0,10)}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
    toast('Excel generado', 'ok');
  } catch (err) { toast(err.message, 'error'); }
}

function apu_exportarPDF() {
  if (!_apuLastResult) { toast('Calcule la oferta primero', 'warn'); return; }
  toast('Abriendo diálogo de impresión...', 'info');
  setTimeout(() => window.print(), 300);
}

// ════════════ GENERADOR DE OFERTA (página independiente) ════════════

function oferta_prefill() {
  const auditEntidad = val('a-entidad');
  const auditObjeto  = val('a-objeto');
  const auditPid     = val('a-codigo-proceso') || sessionStorage.getItem('siaco_precarg_pid') || '';
  const banner       = document.getElementById('oferta-precargado-banner');

  if (auditEntidad || auditObjeto || auditPid) {
    if (auditEntidad && !val('oferta-entidad'))    setVal('oferta-entidad', auditEntidad);
    if (auditObjeto  && !val('oferta-objeto'))     setVal('oferta-objeto',  auditObjeto);
    if (auditPid     && !val('oferta-proceso-id')) setVal('oferta-proceso-id', auditPid);
    if (banner && (auditEntidad || auditObjeto)) {
      banner.innerHTML    = alertHtml('info', '↖ Datos precargados automáticamente desde la última auditoría.');
      banner.style.display = '';
    }
  }
}

async function oferta_generarDoc(tipo) {
  const pid   = val('oferta-proceso-id').trim();
  if (!pid) { toast('Ingresa el ID del proceso SECOP II', 'warn'); return; }
  const stEl  = document.getElementById('oferta-docs-status');
  if (stEl) stEl.textContent = `⏳ Generando ${tipo}...`;
  const clienteId = CLIENTE_ID || '';

  try {
    let endpoint, body, filename, mime;

    if (tipo === 'carta-presentacion') {
      endpoint = '/api/oferta/carta-presentacion';
      body     = { cliente_id: clienteId, proceso_id: pid };
      filename = `Carta_Presentacion_${pid}.docx`;
      mime     = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    } else if (tipo === 'formulario-economico') {
      endpoint = '/api/oferta/formulario-economico';
      body     = { cliente_id: clienteId, proceso_id: pid, datos_apu: _apuLastResult || {} };
      filename = `Formulario_Economico_${pid}.docx`;
      mime     = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    } else if (tipo === 'formato-experiencia') {
      endpoint = '/api/oferta/formato-experiencia';
      body     = { cliente_id: clienteId, proceso_id: pid };
      filename = `Formulario_Experiencia_${pid}.docx`;
      mime     = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    } else if (tipo === 'capacidad-residual') {
      endpoint = '/api/oferta/capacidad-residual';
      body     = { cliente_id: clienteId, proceso_id: pid, k_requerido: 0, contratos_vigentes: [] };
      filename = `Capacidad_Residual_${pid}.docx`;
      mime     = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    } else if (tipo === 'paz-y-salvos') {
      endpoint = '/api/oferta/paz-y-salvos';
      body     = { cliente_id: clienteId, proceso_id: pid };
      filename = `05_Paz_Y_Salvos_${pid}.docx`;
      mime     = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    } else if (tipo === 'checklist') {
      endpoint = '/api/oferta/checklist';
      body     = { cliente_id: clienteId, proceso_id: pid };
      filename = `00_Checklist_Anti_Rechazo_${pid}.docx`;
      mime     = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    } else if (tipo === 'paquete-completo') {
      endpoint = '/api/oferta/paquete-completo';
      body     = { cliente_id: clienteId, proceso_id: pid, datos_apu: _apuLastResult || {}, k_requerido: 0, contratos_vigentes: [] };
      filename = `SIACO_Oferta_${pid}_${new Date().toISOString().slice(0,10)}.zip`;
      mime     = 'application/zip';
    } else {
      toast('Tipo de documento no reconocido', 'error'); return;
    }

    const res = await api(endpoint, { method: 'POST', body: JSON.stringify(body) });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Error desconocido' }));
      throw new Error(err.detail || `Error ${res.status}`);
    }
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
    if (stEl) stEl.textContent = `✓ ${filename} descargado`;
    toast('Documento generado', 'ok');
  } catch (err) {
    if (stEl) stEl.textContent = `Error: ${err.message}`;
    toast(err.message, 'error');
  }
}

// ════════════ GENERADOR DE DOCUMENTOS DE OFERTA ════════════

function apu_docs_prefill() {
  // Intenta precargar el proceso desde sessionStorage o el campo de competidores
  const pid = sessionStorage.getItem('siaco_comp_proceso') || val('comp-proceso') || '';
  if (pid) setVal('apu-docs-proceso', pid);
}

async function apu_generarDoc(tipo) {
  if (!_apuLastResult && tipo !== 'carta-presentacion' && tipo !== 'formato-experiencia' && tipo !== 'capacidad-residual') {
    toast('Calcule la oferta primero para incluir los valores económicos', 'warn');
  }
  const pid    = val('apu-docs-proceso').trim();
  if (!pid) { toast('Ingresa el ID del proceso SECOP II', 'warn'); return; }
  const stEl   = document.getElementById('apu-docs-status');
  if (stEl) stEl.textContent = `⏳ Generando ${tipo}...`;

  const clienteId = CLIENTE_ID || '';

  try {
    let endpoint, body, filename, mime;

    if (tipo === 'carta-presentacion') {
      endpoint = '/api/oferta/carta-presentacion';
      body     = { cliente_id: clienteId, proceso_id: pid };
      filename = `Carta_Presentacion_${pid}.docx`;
      mime     = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

    } else if (tipo === 'formulario-economico') {
      endpoint = '/api/oferta/formulario-economico';
      body     = { cliente_id: clienteId, proceso_id: pid, datos_apu: _apuLastResult || {} };
      filename = `Formulario_Economico_${pid}.docx`;
      mime     = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

    } else if (tipo === 'formato-experiencia') {
      endpoint = '/api/oferta/formato-experiencia';
      body     = { cliente_id: clienteId, proceso_id: pid };
      filename = `Formulario_Experiencia_${pid}.docx`;
      mime     = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

    } else if (tipo === 'capacidad-residual') {
      endpoint = '/api/oferta/capacidad-residual';
      body     = { cliente_id: clienteId, proceso_id: pid, k_requerido: 0, contratos_vigentes: [] };
      filename = `Capacidad_Residual_${pid}.docx`;
      mime     = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

    } else if (tipo === 'paquete-completo') {
      endpoint = '/api/oferta/paquete-completo';
      body     = { cliente_id: clienteId, proceso_id: pid, datos_apu: _apuLastResult || {}, k_requerido: 0, contratos_vigentes: [] };
      filename = `SIACO_Oferta_${pid}_${new Date().toISOString().slice(0,10)}.zip`;
      mime     = 'application/zip';
    } else {
      toast('Tipo de documento no reconocido', 'error'); return;
    }

    const res  = await api(endpoint, { method: 'POST', body: JSON.stringify(body) });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Error desconocido' }));
      throw new Error(err.detail || `Error ${res.status}`);
    }
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
    if (stEl) stEl.textContent = `✓ ${filename} descargado`;
    toast('Documento generado', 'ok');
  } catch (err) {
    if (stEl) stEl.textContent = `Error: ${err.message}`;
    toast(err.message, 'error');
  }
}

// Mostrar sección de docs cuando la oferta está calculada
const _origRenderResultados = typeof apu_renderResultados === 'function' ? apu_renderResultados : null;

// ════════════ ESTRATEGIA DE PRECIO (Módulo 2) ════════════

async function calcularEstrategiaPrecio() {
  const btn   = document.getElementById('btn-estrategia-precio');
  const stEl  = document.getElementById('ep-status');
  const resEl = document.getElementById('ep-resultado');
  const pid   = val('comp-proceso').trim();

  const precioMin  = parseFloat(val('ep-precio-minimo'))  || 0;
  const presupuesto= parseFloat(val('ep-presupuesto'))    || 0;
  const metodo     = val('ep-metodo')     || 'media_aritmetica';
  const nProp      = parseInt(val('ep-proponentes')) || 3;

  if (!precioMin)   { toast('Ingresa el precio mínimo', 'warn'); return; }
  if (!presupuesto) { toast('Ingresa el presupuesto oficial', 'warn'); return; }

  btn.disabled = true;
  stEl.textContent = '⏳ Calculando...';
  resEl.style.display = 'none';

  try {
    const clienteId = CLIENTE_ID || '';
    const data = await apiJson('/api/competidores/estrategia-precio', {
      method: 'POST',
      body: JSON.stringify({
        cliente_id:            clienteId,
        proceso_id:            pid || 'sin-proceso',
        precio_minimo_cliente: precioMin,
        presupuesto_oficial:   presupuesto,
        metodo_calificacion:   metodo,
        n_proponentes:         nProp,
      }),
    });

    const p = data.probabilidades || {};
    const u = data.utilidades_proyectadas || {};
    const up = data.utilidades_pct || {};

    const barWidth = (prob) => `${Math.round(prob * 100)}%`;
    const barCol   = (prob) => prob >= 0.65 ? 'var(--ok)' : prob >= 0.45 ? 'var(--warn)' : 'var(--danger)';

    const escenarioHTML = (label, precio, prob, utilidad, pct, icon) => `
      <div style="display:grid;grid-template-columns:140px 1fr auto;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #222">
        <div>
          <div style="font-size:.78rem;color:var(--muted)">${label}</div>
          <div style="font-family:var(--mono);font-weight:600;font-size:1.05rem">${fmtCOP(precio)}</div>
        </div>
        <div>
          <div style="background:#222;border-radius:4px;height:8px;overflow:hidden">
            <div style="width:${barWidth(prob)};height:100%;background:${barCol(prob)};border-radius:4px;transition:width .4s"></div>
          </div>
          <div style="font-size:.75rem;color:var(--muted);margin-top:3px">${icon} Prob. adjudicación: <strong style="color:${barCol(prob)}">${Math.round(prob*100)}%</strong></div>
        </div>
        <div style="text-align:right">
          <div style="font-size:.72rem;color:var(--muted)">Utilidad</div>
          <div style="font-family:var(--mono);color:var(--ok)">${fmtCOP(utilidad)}</div>
          <div style="font-size:.72rem;color:var(--muted)">(${pct}%)</div>
        </div>
      </div>`;

    resEl.innerHTML = `
      <div style="margin-bottom:12px">
        <span style="font-size:.8rem;color:var(--muted)">Método: </span>
        <strong>${data.metodo_label || metodo}</strong>
        <span style="margin-left:16px;font-size:.8rem;color:var(--muted)">Históricos: </span>
        <strong>${data.n_historicos_analizados}</strong>
        <span style="margin-left:16px;font-size:.8rem;color:var(--muted)">Proponentes esperados: </span>
        <strong>${data.n_proponentes_esperados}</strong>
        <span style="margin-left:16px;font-size:.8rem;color:var(--muted)">Confianza: </span>
        <strong style="color:${data.confianza_modelo==='alta'?'var(--ok)':data.confianza_modelo==='media'?'var(--warn)':'var(--danger)'}">${data.confianza_modelo || '—'}</strong>
      </div>

      <div style="background:var(--bg2);border:1px solid #333;border-radius:8px;padding:16px;margin-bottom:14px">
        <div style="font-size:.78rem;color:var(--muted);margin-bottom:4px">PRECIO MÍNIMO (no perder dinero)</div>
        <div style="font-family:var(--mono);font-size:1.1rem;color:var(--muted)">━━━  ${fmtCOP(data.precio_minimo)}</div>

        ${escenarioHTML('PRECIO AGRESIVO', data.precio_agresivo, p.agresivo, u.agresivo, up.agresivo, '')}
        ${escenarioHTML('PRECIO ÓPTIMO ⭐', data.precio_optimo, p.optimo, u.optimo, up.optimo, '⭐')}
        ${escenarioHTML('PRECIO CONSERVADOR', data.precio_conservador, p.conservador, u.conservador, up.conservador, '')}
      </div>

      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px">
        <div style="background:var(--bg2);border-radius:6px;padding:10px;border:1px solid #333">
          <div style="font-size:.72rem;color:var(--muted)">Precio ideal estimado</div>
          <div style="font-family:var(--mono);font-weight:600">${fmtCOP(data.precio_ideal_estimado||0)}</div>
        </div>
        <div style="background:var(--bg2);border-radius:6px;padding:10px;border:1px solid #333">
          <div style="font-size:.72rem;color:var(--muted)">Rango competitivo</div>
          <div style="font-family:var(--mono);font-size:.85rem">${fmtCOP(data.rango_competitivo?.minimo||0)} – ${fmtCOP(data.rango_competitivo?.maximo||0)}</div>
        </div>
        <div style="background:var(--bg2);border-radius:6px;padding:10px;border:1px solid #333">
          <div style="font-size:.72rem;color:var(--muted)">Presupuesto oficial</div>
          <div style="font-family:var(--mono);font-weight:600">${fmtCOP(presupuesto)}</div>
        </div>
      </div>

      ${data.estrategia_recomendada ? `
      <div style="background:#0a1a0a;border:1px solid #1a4a1a;border-radius:6px;padding:12px 14px;margin-bottom:12px">
        <div style="font-size:.78rem;color:var(--ok);font-weight:600;margin-bottom:6px">⭐ Recomendación SIACO</div>
        <div style="font-size:.85rem;color:var(--text2);line-height:1.6">${data.estrategia_recomendada}</div>
      </div>` : ''}

      ${data.advertencias?.length ? `
      <div style="font-size:.78rem;color:var(--warn)">
        ${data.advertencias.map(a => `<div style="margin-bottom:3px">⚠ ${a}</div>`).join('')}
      </div>` : ''}
    `;
    resEl.style.display = '';
    stEl.textContent = `✓ Calculado con ${data.n_historicos_analizados} precio(s) histórico(s)`;
    toast('Estrategia de precio calculada', 'ok');
  } catch (err) {
    stEl.textContent = err.message;
    toast(err.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

// Prefill precio mínimo desde calculadora APU → competidores
function ep_prefillarDesdeAPU() {
  if (_apuLastResult?.precio_minimo) {
    setVal('ep-precio-minimo', _apuLastResult.precio_minimo);
  }
}

// ════════════ BOOT ════════════
(function boot() {
  if (TOKEN) {
    apiJson('/api/perfil')
      .then(() => initMainScreen())
      .catch(() => { localStorage.removeItem('siaco_token'); TOKEN = ''; });
  }
})();
