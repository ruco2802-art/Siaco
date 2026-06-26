/* SIACO v3.0 — Frontend SPA */
'use strict';

// ════════════ ESTADO GLOBAL ════════════
let TOKEN        = localStorage.getItem('siaco_token') || '';
let CLIENTE_ID   = localStorage.getItem('siaco_cid')   || '';
let PLAN         = localStorage.getItem('siaco_plan')   || 'basico';
let NOMBRE       = localStorage.getItem('siaco_nombre') || '';
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
    CLIENTE_ID = cli.cliente_id || cli.id || '';
    PLAN       = cli.plan || 'basico';
    NOMBRE     = cli.nombre || CLIENTE_ID;
    localStorage.setItem('siaco_token',  TOKEN);
    localStorage.setItem('siaco_cid',    CLIENTE_ID);
    localStorage.setItem('siaco_plan',   PLAN);
    localStorage.setItem('siaco_nombre', NOMBRE);
    initMainScreen();
  } catch (err) {
    errEl.innerHTML = alertHtml('error', err.message);
    btn.disabled = false; btn.textContent = 'Ingresar';
  }
});

function doLogout() {
  api('/api/logout', { method: 'POST' }).catch(() => {});
  ['siaco_token','siaco_cid','siaco_plan','siaco_nombre'].forEach(k => localStorage.removeItem(k));
  sessionStorage.clear();
  TOKEN = CLIENTE_ID = PLAN = NOMBRE = '';
  document.getElementById('main-screen').style.display = 'none';
  document.getElementById('login-screen').style.display = '';
}
document.getElementById('btn-logout').addEventListener('click', doLogout);

// ════════════ INICIALIZACIÓN ════════════
function initMainScreen() {
  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('main-screen').style.display  = '';

  const chip = document.getElementById('plan-chip');
  chip.textContent = PLAN === 'admin' ? 'Admin' : PLAN === 'premium' ? 'Premium' : 'Básico';
  chip.className   = `plan-chip ${PLAN}`;
  document.getElementById('sidebar-user').textContent = NOMBRE || CLIENTE_ID;

  // Mostrar nav de admin solo para plan admin
  const navAdmin = document.getElementById('nav-admin');
  if (navAdmin) navAdmin.style.display = PLAN === 'admin' ? '' : 'none';

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
document.getElementById('btn-upload-doc').addEventListener('click', async () => {
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
});

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

async function extraerPliego() {
  const file = document.getElementById('pliego-file').files[0];
  if (!file) { toast('Selecciona un PDF', 'warn'); return; }
  _pliegoRaw = file;
  const btn  = document.getElementById('btn-extraer');
  const stEl = document.getElementById('pliego-extract-status');
  btn.disabled = true; btn.textContent = 'Extrayendo...';
  stEl.innerHTML = alertHtml('info', 'Extrayendo datos del PDF con Claude...');
  const fd = new FormData(); fd.append('pdf', file);
  try {
    const d = await apiJson('/api/auditoria/extraer', { method: 'POST', body: fd });
    if (d.entidad)   setVal('a-entidad',   d.entidad);
    if (d.objeto)    setVal('a-objeto',    d.objeto);
    if (d.valor)     setVal('a-valor',     d.valor);
    if (d.modalidad) setVal('a-modalidad', d.modalidad);
    if (d.sector)    setVal('a-sector',    d.sector);
    stEl.innerHTML = alertHtml('success', `✓ ${(d.texto_chars||0).toLocaleString()} caracteres extraídos. Campos prellenados.`);
  } catch (err) {
    stEl.innerHTML = alertHtml('error', err.message);
  } finally { btn.disabled = false; btn.textContent = 'Extraer datos del PDF'; }
}

async function analizarPliego() {
  const btn  = document.getElementById('btn-analizar-pliego');
  const stEl = document.getElementById('audit-status');
  const resEl= document.getElementById('audit-results');

  // Validar que hay pliego subido
  const pliegoFile = document.getElementById('pliego-file').files[0];
  if (!pliegoFile) {
    stEl.innerHTML = alertHtml('error', '⚠ Debes subir el Pliego de Condiciones (PDF) antes de analizar.');
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
    </div>
    <div id="obs-result" style="margin-top:16px"></div>
  </div>`;
}

async function descargarPDF(event) {
  if (!window._lastAnalisis) { toast('Realiza un análisis primero', 'warn'); return; }
  const btn = event.target;
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

async function generarObservaciones(event) {
  const btn = event.target;
  const resDiv = document.getElementById('obs-result');
  if (!CLIENTE_ID) { toast('Inicia sesión primero', 'warn'); return; }
  if (!resDiv) { toast('Realiza un análisis de pliego primero', 'warn'); return; }
  btn.disabled = true; btn.textContent = '⏳ Analizando pliego...';
  resDiv.innerHTML = '<div class="loading">Comparando con Documentos Tipo CCE…</div>';
  try {
    const procesoId = val('a-codigo-proceso') || val('a-objeto') || `obs_${Date.now()}`;
    const data = await apiJson('/api/observaciones/generar', {
      method: 'POST',
      body: JSON.stringify({ cliente_id: CLIENTE_ID, proceso_id: procesoId }),
    });
    if (!data.tiene_discrepancias || !data.discrepancias?.length) {
      resDiv.innerHTML = `<div class="card" style="border-left:4px solid #4caf50">
        <div class="card-title">✅ Pliego conforme a Documentos Tipo CCE</div>
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
    const descBtn = data.pdf_disponible && data.pdf_filename
      ? `<button class="btn btn-secondary" style="margin-top:12px"
           onclick="descargarObservaciones('${data.pdf_filename}')">
           ⬇ Descargar PDF de Observaciones
         </button>`
      : '';
    resDiv.innerHTML = `<div class="card" style="border-left:4px solid #C6F24E">
      <div class="card-title">⚠ ${data.total_discrepancias} discrepancia(s) identificada(s) — ${data.entidad||'Entidad'}</div>
      <div class="table-wrap"><table class="req-table">
        <thead><tr><th>#</th><th>Título</th><th>Sección</th><th>Norma vulnerada</th></tr></thead>
        <tbody>${filas}</tbody>
      </table></div>
      ${descBtn}
    </div>`;
    toast(`${data.total_discrepancias} observacion(es) generadas`, 'success');
  } catch (err) {
    resDiv.innerHTML = `<div class="alert alert-error">${err.message}</div>`;
    toast(`Error: ${err.message}`, 'error');
  } finally {
    btn.disabled = false; btn.textContent = '📋 Generar Observaciones al Pliego';
  }
}

async function descargarObservaciones(filename) {
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

// ════════════ BOOT ════════════
(function boot() {
  if (TOKEN) {
    apiJson('/api/perfil')
      .then(() => initMainScreen())
      .catch(() => { localStorage.removeItem('siaco_token'); TOKEN = ''; });
  }
})();
