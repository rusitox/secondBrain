/**
 * secondBrain Backoffice — observability + config UI for the multi-agent
 * knowledge system. Vanilla JS, no build step (same pattern as static/voice).
 */

// ── Config / state ───────────────────────────────────────────────────────────

const API_BASE = '';
const STORAGE_KEY = 'sb_api_key'; // shared with the voice UI — one login for both

let apiKey = localStorage.getItem(STORAGE_KEY) || '';
let currentView = 'dashboard';
let agentsCache = [];          // [{agent_key, enabled, model_id, ...}]
let selectedAgentKey = null;
let selectedRunId = null;
let cy = null;                 // cytoscape instance
let claimsChart = null;
let confidenceChart = null;

const AGENT_KEYS_META = {
  slack: { label: 'Slack', icon: '💬' },
  outlook: { label: 'Outlook', icon: '📧' },
  teams: { label: 'Teams', icon: '👥' },
  fathom: { label: 'Fathom', icon: '🎙' },
  notion: { label: 'Notion', icon: '📝' },
  rd: { label: 'I+D Platform', icon: '🔬' },
  orchestrator: { label: 'Orchestrator (chat)', icon: '🧠' },
};

// ── DOM refs ──────────────────────────────────────────────────────────────────

const authOverlay = document.getElementById('auth-overlay');
const authForm = document.getElementById('auth-form');
const emailInput = document.getElementById('email-input');
const passwordInput = document.getElementById('password-input');
const authSubmitBtn = document.getElementById('auth-submit-btn');
const authError = document.getElementById('auth-error');
const logoutBtn = document.getElementById('logout-btn');
const toast = document.getElementById('toast');

// ── Init ──────────────────────────────────────────────────────────────────────

function init() {
  if (!apiKey) {
    authOverlay.style.display = 'flex';
  } else {
    authOverlay.style.display = 'none';
    boot();
  }

  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
  });

  document.getElementById('runs-refresh').addEventListener('click', loadRuns);
  document.getElementById('runs-agent-filter').addEventListener('change', loadRuns);
  document.getElementById('runs-status-filter').addEventListener('change', loadRuns);

  document.getElementById('graph-refresh').addEventListener('click', loadGraph);
  document.getElementById('graph-search').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadGraph();
  });

  document.getElementById('questions-refresh').addEventListener('click', loadQuestions);
  document.getElementById('questions-status-filter').addEventListener('change', loadQuestions);

  document.getElementById('mcp-new-btn').addEventListener('click', () => openMcpModal(null));
  document.getElementById('mcp-modal-cancel').addEventListener('click', closeMcpModal);
  document.getElementById('mcp-form').addEventListener('submit', submitMcpForm);
}

function boot() {
  loadDashboard();
  loadAgentsList(); // also populates the runs-agent-filter dropdown
  refreshQuestionsBadge();
}

// ── Auth ──────────────────────────────────────────────────────────────────────

authForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = emailInput.value.trim();
  const password = passwordInput.value;
  if (!email || !password) return;

  authSubmitBtn.disabled = true;
  authSubmitBtn.textContent = 'Entrando…';
  authError.classList.remove('visible');

  try {
    const resp = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!resp.ok) throw new Error('bad credentials');
    const data = await resp.json();
    apiKey = data.api_key;
    localStorage.setItem(STORAGE_KEY, apiKey);
    authOverlay.style.display = 'none';
    passwordInput.value = '';
    boot();
  } catch {
    authError.textContent = 'Credenciales incorrectas.';
    authError.classList.add('visible');
    passwordInput.value = '';
    passwordInput.focus();
  } finally {
    authSubmitBtn.disabled = false;
    authSubmitBtn.textContent = 'Entrar';
  }
});

logoutBtn.addEventListener('click', () => {
  localStorage.removeItem(STORAGE_KEY);
  apiKey = '';
  authOverlay.style.display = 'flex';
});

/** Shared fetch wrapper: attaches the bearer key, and on 401 bounces back to
 * the login overlay instead of leaving the UI silently broken (the gap
 * static/voice/app.js has today). */
async function authedFetch(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  if (resp.status === 401) {
    localStorage.removeItem(STORAGE_KEY);
    apiKey = '';
    authOverlay.style.display = 'flex';
    throw new Error('unauthorized');
  }
  return resp;
}

async function apiGet(path) {
  const resp = await authedFetch(path);
  if (!resp.ok) throw new Error(`GET ${path} -> ${resp.status}`);
  return resp.json();
}

async function apiSend(method, path, body) {
  const resp = await authedFetch(path, { method, body: body !== undefined ? JSON.stringify(body) : undefined });
  if (!resp.ok) {
    let detail = `${method} ${path} -> ${resp.status}`;
    try {
      const err = await resp.json();
      detail = formatApiError(err) || detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

function formatApiError(err) {
  if (!err || !err.detail) return null;
  if (typeof err.detail === 'string') return err.detail;
  if (Array.isArray(err.detail)) {
    return err.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
  }
  return JSON.stringify(err.detail);
}

// ── Toast ─────────────────────────────────────────────────────────────────────

let toastTimer = null;
function showToast(message, isError = false) {
  toast.textContent = message;
  toast.classList.toggle('error', isError);
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 3200);
}

// ── Nav / view switching ─────────────────────────────────────────────────────

function switchView(view) {
  currentView = view;
  document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${view}`));
  if (view === 'dashboard') loadDashboard();
  if (view === 'agents' && agentsCache.length === 0) loadAgentsList();
  if (view === 'runs') loadRuns();
  if (view === 'graph') loadGraph();
  if (view === 'questions') loadQuestions();
  if (view === 'mcps') { loadMcpServers(); loadToolsCatalog(); }
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('es-AR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function fmtDuration(ms) {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

async function loadDashboard() {
  try {
    const stats = await apiGet('/knowledge/status');
    renderStatGrid(stats);
    renderClaimsChart(stats.claims_by_source || {});
    renderConfidenceChart(stats.entities_by_confidence || {});
  } catch (e) {
    showToast('No se pudo cargar el dashboard: ' + e.message, true);
  }
  try {
    const runs = await apiGet('/backoffice/runs?limit=8');
    renderRecentRuns(runs);
  } catch { /* non-fatal */ }
}

function renderStatGrid(stats) {
  const cards = [
    { label: 'Entidades', value: stats.total_entities },
    { label: 'Claims', value: stats.total_claims },
    { label: 'Preguntas abiertas', value: stats.pending_questions_open },
    { label: 'Fusionadas (24h)', value: stats.entities_merged_recent },
    { label: 'Scheduler', value: stats.scheduler_active ? 'activo' : 'inactivo' },
  ];
  document.getElementById('stat-grid').innerHTML = cards.map((c) => `
    <div class="stat-card">
      <div class="stat-value">${escapeHtml(c.value)}</div>
      <div class="stat-label">${escapeHtml(c.label)}</div>
    </div>
  `).join('');
}

function renderClaimsChart(bySource) {
  const ctx = document.getElementById('claims-chart');
  const labels = Object.keys(bySource);
  const data = Object.values(bySource);
  if (claimsChart) claimsChart.destroy();
  claimsChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: '#6366f1', borderRadius: 4 }] },
    options: chartOptions(),
  });
}

function renderConfidenceChart(byConfidence) {
  const ctx = document.getElementById('confidence-chart');
  const order = ['low', 'medium', 'high'];
  const labels = order.filter((k) => k in byConfidence);
  const data = labels.map((k) => byConfidence[k]);
  const colors = { low: '#ef4444', medium: '#f59e0b', high: '#22c55e' };
  if (confidenceChart) confidenceChart.destroy();
  confidenceChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: labels.map((l) => colors[l]), borderRadius: 4 }] },
    options: chartOptions(),
  });
}

function chartOptions() {
  return {
    responsive: true,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.06)' } },
      y: { ticks: { color: '#94a3b8', precision: 0 }, grid: { color: 'rgba(255,255,255,0.06)' }, beginAtZero: true },
    },
  };
}

function renderRecentRuns(runs) {
  const el = document.getElementById('recent-runs');
  if (!runs.length) { el.innerHTML = '<div class="empty-hint">Sin corridas todavía.</div>'; return; }
  el.innerHTML = `<table><thead><tr><th>Agente</th><th>Tipo</th><th>Estado</th><th>Inicio</th><th>Duración</th></tr></thead><tbody>
    ${runs.map((r) => `<tr>
      <td>${escapeHtml(r.agent_key)}</td>
      <td class="mono">${escapeHtml(r.run_type)}</td>
      <td><span class="badge badge-${escapeHtml(r.status)}">${escapeHtml(r.status)}</span></td>
      <td class="mono">${fmtDate(r.started_at)}</td>
      <td class="mono">${fmtDuration(r.duration_ms)}</td>
    </tr>`).join('')}
  </tbody></table>`;
}

// ── Agents ────────────────────────────────────────────────────────────────────

async function loadAgentsList() {
  try {
    agentsCache = await apiGet('/backoffice/agents');
  } catch (e) {
    showToast('No se pudieron cargar los agentes: ' + e.message, true);
    return;
  }
  renderAgentList();
  populateRunsAgentFilter();
}

function renderAgentList() {
  const el = document.getElementById('agent-list');
  el.innerHTML = agentsCache.map((a) => {
    const meta = AGENT_KEYS_META[a.agent_key] || { label: a.agent_key, icon: '🤖' };
    return `<div class="agent-card ${a.agent_key === selectedAgentKey ? 'selected' : ''}" data-key="${a.agent_key}">
      <div class="agent-card-name">${meta.icon} ${escapeHtml(meta.label)}</div>
      <div class="agent-card-meta">
        <span class="badge ${a.enabled ? 'badge-completed' : 'badge-failed'}">${a.enabled ? 'enabled' : 'disabled'}</span>
        ${a.has_override ? '<span class="badge badge-neutral">override</span>' : ''}
      </div>
    </div>`;
  }).join('');
  el.querySelectorAll('.agent-card').forEach((card) => {
    card.addEventListener('click', () => selectAgent(card.dataset.key));
  });
}

function populateRunsAgentFilter() {
  const sel = document.getElementById('runs-agent-filter');
  const current = sel.value;
  sel.innerHTML = '<option value="">Todos los agentes</option>' +
    agentsCache.map((a) => `<option value="${a.agent_key}">${escapeHtml((AGENT_KEYS_META[a.agent_key] || {}).label || a.agent_key)}</option>`).join('');
  sel.value = current;
}

async function selectAgent(key) {
  selectedAgentKey = key;
  renderAgentList();
  const detail = document.getElementById('agent-detail');
  detail.innerHTML = '<div class="empty-hint">Cargando…</div>';
  try {
    const [config, tools, mcpServers] = await Promise.all([
      apiGet(`/backoffice/agents/${key}`),
      apiGet(`/backoffice/tools?agent_key=${key}`),
      apiGet('/backoffice/mcp-servers'),
    ]);
    renderAgentDetail(config, tools, mcpServers);
  } catch (e) {
    detail.innerHTML = `<div class="empty-hint">Error: ${escapeHtml(e.message)}</div>`;
  }
}

function renderAgentDetail(config, tools, mcpServers) {
  const meta = AGENT_KEYS_META[config.agent_key] || { label: config.agent_key, icon: '🤖' };
  const detail = document.getElementById('agent-detail');
  const showMcp = config.agent_key === 'rd';

  detail.innerHTML = `
    <div class="detail-header">
      <div class="detail-title">${meta.icon} ${escapeHtml(meta.label)}</div>
      <div class="detail-actions">
        <button class="btn-secondary btn-small" id="agent-reset-btn">Reset a defaults</button>
        <button class="btn-primary btn-small" id="agent-run-btn">▶ Correr ahora</button>
      </div>
    </div>
    <form id="agent-form">
      <div class="form-group form-row">
        <label class="form-checkbox"><input type="checkbox" id="agent-enabled" ${config.enabled ? 'checked' : ''} /> Habilitado</label>
      </div>
      <div class="form-group">
        <label class="form-label">Modelo <span class="form-hint">(vacío = default de settings)</span></label>
        <input class="form-input" id="agent-model" placeholder="openai/gpt-4o-mini" value="${escapeHtml(config.model_id || '')}" />
      </div>
      <div class="form-group">
        <label class="form-label">System prompt ${config.agent_key === 'orchestrator' ? '<span class="form-hint">(solo lectura — se compone dinámicamente por request)</span>' : ''}</label>
        <textarea class="form-textarea" id="agent-prompt" rows="8" ${config.agent_key === 'orchestrator' ? 'readonly' : ''}>${escapeHtml(config.system_prompt)}</textarea>
      </div>
      <div class="form-group">
        <label class="form-label">Tools</label>
        <div class="tool-grid">
          ${tools.map((t) => `
            <label class="tool-check ${t.configurable ? '' : 'locked'}">
              <input type="checkbox" data-tool="${escapeHtml(t.name)}"
                ${!t.configurable ? 'checked disabled' : (config.enabled_tools === null || config.enabled_tools.includes(t.name)) ? 'checked' : ''} />
              <div>
                <div class="tool-check-name">${escapeHtml(t.name)}</div>
                <div class="tool-check-desc">${escapeHtml(t.description)}</div>
              </div>
            </label>
          `).join('')}
        </div>
      </div>
      ${showMcp ? `
      <div class="form-group">
        <label class="form-label">Servidor MCP</label>
        <select class="form-select" id="agent-mcp-server">
          <option value="">— usar variables de entorno (id_brain_mcp_url) —</option>
          ${mcpServers.map((s) => `<option value="${s.id}" ${config.mcp_server_ids[0] === s.id ? 'selected' : ''}>${escapeHtml(s.name)}</option>`).join('')}
        </select>
      </div>` : ''}
      <div id="agent-form-error" class="form-error"></div>
      <button type="submit" class="btn-primary">Guardar</button>
    </form>
  `;

  document.getElementById('agent-form').addEventListener('submit', (e) => saveAgentConfig(e, config, tools));
  document.getElementById('agent-reset-btn').addEventListener('click', () => resetAgentConfig(config.agent_key));
  document.getElementById('agent-run-btn').addEventListener('click', () => runAgentNow(config.agent_key));
}

async function saveAgentConfig(e, config, tools) {
  e.preventDefault();
  const errorEl = document.getElementById('agent-form-error');
  errorEl.classList.remove('visible');

  const enabled = document.getElementById('agent-enabled').checked;
  const modelInput = document.getElementById('agent-model').value.trim();
  const promptEl = document.getElementById('agent-prompt');
  const checkedConfigurable = Array.from(document.querySelectorAll('#agent-form .tool-check input[type=checkbox]:not(:disabled)'))
    .map((cb) => ({ name: cb.dataset.tool, checked: cb.checked }));
  const allConfigurableChecked = checkedConfigurable.every((t) => t.checked);
  const enabledTools = allConfigurableChecked ? null : checkedConfigurable.filter((t) => t.checked).map((t) => t.name);

  const body = {
    enabled,
    model_id: modelInput || null,
  };
  if (config.agent_key !== 'orchestrator') {
    body.system_prompt = promptEl.value;
  }
  body.enabled_tools = enabledTools;
  const mcpSelect = document.getElementById('agent-mcp-server');
  if (mcpSelect) {
    body.mcp_server_ids = mcpSelect.value ? [mcpSelect.value] : [];
  }

  try {
    await apiSend('PUT', `/backoffice/agents/${config.agent_key}`, body);
    showToast('Configuración guardada.');
    await loadAgentsList();
    selectAgent(config.agent_key);
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.add('visible');
  }
}

async function resetAgentConfig(agentKey) {
  if (!confirm(`¿Volver "${agentKey}" a la configuración por defecto?`)) return;
  try {
    await apiSend('DELETE', `/backoffice/agents/${agentKey}/overrides`);
    showToast('Configuración reseteada.');
    await loadAgentsList();
    selectAgent(agentKey);
  } catch (e) {
    showToast('Error: ' + e.message, true);
  }
}

async function runAgentNow(agentKey) {
  const btn = document.getElementById('agent-run-btn');
  btn.disabled = true;
  btn.textContent = 'Corriendo… (puede tardar)';
  try {
    const run = await apiSend('POST', `/backoffice/agents/${agentKey}/run`);
    showToast(`Corrida completa: ${run.status}`);
    if (currentView === 'runs') loadRuns();
  } catch (e) {
    showToast('Error al correr el agente: ' + e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Correr ahora';
  }
}

// ── Runs ──────────────────────────────────────────────────────────────────────

async function loadRuns() {
  const agentKey = document.getElementById('runs-agent-filter').value;
  const status = document.getElementById('runs-status-filter').value;
  const params = new URLSearchParams();
  if (agentKey) params.set('agent_key', agentKey);
  if (status) params.set('status', status);
  params.set('limit', '50');

  const tableEl = document.getElementById('runs-table');
  tableEl.innerHTML = '<div class="empty-hint">Cargando…</div>';
  try {
    const runs = await apiGet(`/backoffice/runs?${params}`);
    renderRunsTable(runs);
  } catch (e) {
    tableEl.innerHTML = `<div class="empty-hint">Error: ${escapeHtml(e.message)}</div>`;
  }
}

function renderRunsTable(runs) {
  const el = document.getElementById('runs-table');
  if (!runs.length) { el.innerHTML = '<div class="empty-hint">Sin corridas.</div>'; return; }
  el.innerHTML = `<table><thead><tr><th>Agente</th><th>Estado</th><th>Trigger</th><th>Inicio</th></tr></thead><tbody>
    ${runs.map((r) => `<tr class="clickable ${r.id === selectedRunId ? 'selected' : ''}" data-id="${r.id}">
      <td>${escapeHtml(r.agent_key)}</td>
      <td><span class="badge badge-${escapeHtml(r.status)}">${escapeHtml(r.status)}</span></td>
      <td class="mono">${escapeHtml(r.trigger)}</td>
      <td class="mono">${fmtDate(r.started_at)}</td>
    </tr>`).join('')}
  </tbody></table>`;
  el.querySelectorAll('tr.clickable').forEach((row) => {
    row.addEventListener('click', () => selectRun(row.dataset.id));
  });
}

async function selectRun(runId) {
  selectedRunId = runId;
  document.querySelectorAll('#runs-table tr').forEach((r) => r.classList.toggle('selected', r.dataset.id === runId));
  const detail = document.getElementById('run-detail');
  detail.innerHTML = '<div class="empty-hint">Cargando…</div>';
  try {
    const run = await apiGet(`/backoffice/runs/${runId}`);
    renderRunDetail(run);
  } catch (e) {
    detail.innerHTML = `<div class="empty-hint">Error: ${escapeHtml(e.message)}</div>`;
  }
}

function renderRunDetail(run) {
  const detail = document.getElementById('run-detail');
  detail.innerHTML = `
    <div class="detail-header">
      <div class="detail-title">${escapeHtml(run.agent_key)} <span class="badge badge-${escapeHtml(run.status)}">${escapeHtml(run.status)}</span></div>
    </div>
    <div class="mono" style="margin-bottom:10px">
      ${fmtDate(run.started_at)} → ${fmtDate(run.finished_at)} (${fmtDuration(run.duration_ms)})
      ${run.total_tokens ? ` · ${run.total_tokens} tokens` : ''}
    </div>
    ${run.summary ? `<div style="margin-bottom:10px">${escapeHtml(run.summary)}</div>` : ''}
    ${run.error ? `<div class="form-error visible" style="margin-bottom:10px">${escapeHtml(run.error)}</div>` : ''}
    <h2>Traza</h2>
    <div class="timeline">
      ${run.events.length ? run.events.map(renderTimelineEvent).join('') : '<div class="empty-hint">Sin eventos registrados.</div>'}
    </div>
    ${run.sub_runs.length ? `<div class="sub-runs">
      <h2>Sub-corridas (negociaciones)</h2>
      ${run.sub_runs.map((s) => `<div class="timeline-event">
        <div class="timeline-actor">${escapeHtml(s.agent_key)} · <span class="badge badge-${escapeHtml(s.status)}">${escapeHtml(s.status)}</span></div>
        <div class="timeline-body">${escapeHtml(s.summary || '')}</div>
      </div>`).join('')}
    </div>` : ''}
  `;
}

function renderTimelineEvent(ev) {
  let body = '';
  if (ev.event_type === 'assistant_text') body = escapeHtml(ev.payload.text || '');
  else if (ev.event_type === 'tool_call') body = `<strong>${escapeHtml(ev.tool_name)}</strong><pre>${escapeHtml(JSON.stringify(ev.payload.input, null, 2))}</pre>`;
  else if (ev.event_type === 'tool_result') body = `<pre>${escapeHtml(JSON.stringify(ev.payload.content, null, 2))}</pre>`;
  else if (ev.event_type === 'handoff') body = `→ ${escapeHtml(ev.payload.to || '')}`;
  else if (ev.event_type === 'verdict') body = `<pre>${escapeHtml(JSON.stringify(ev.payload, null, 2))}</pre>`;
  else if (ev.event_type === 'error') body = escapeHtml(ev.payload.error || '');
  else body = escapeHtml(JSON.stringify(ev.payload));
  return `<div class="timeline-event type-${escapeHtml(ev.event_type)}">
    <div class="timeline-actor">${escapeHtml(ev.actor || '')} · ${escapeHtml(ev.event_type)}</div>
    <div class="timeline-body">${body}</div>
  </div>`;
}

// ── Graph ─────────────────────────────────────────────────────────────────────

async function loadGraph() {
  const search = document.getElementById('graph-search').value.trim();
  const entityType = document.getElementById('graph-type-filter').value;
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (entityType) params.set('entity_type', entityType);
  params.set('limit', '150');

  let entities = [];
  try {
    entities = await apiGet(`/backoffice/graph/entities?${params}`);
  } catch (e) {
    showToast('Error cargando el grafo: ' + e.message, true);
    return;
  }
  renderGraph(entities);
}

const TYPE_COLORS = {
  person: '#6366f1', project: '#22c55e', initiative: '#f59e0b',
  topic: '#38bdf8', organization: '#a78bfa',
};

function renderGraph(entities) {
  const container = document.getElementById('cy');
  const elements = entities.map((e) => ({
    data: { id: e.id, label: e.canonical_name, type: e.entity_type, confidence: e.confidence },
  }));

  if (cy) cy.destroy();
  cy = cytoscape({
    container,
    elements,
    style: [
      {
        selector: 'node',
        style: {
          'background-color': (n) => TYPE_COLORS[n.data('type')] || '#94a3b8',
          'label': 'data(label)',
          'color': '#f1f5f9',
          'font-size': 10,
          'text-valign': 'bottom',
          'text-margin-y': 4,
          'width': (n) => 18 + n.data('confidence') * 28,
          'height': (n) => 18 + n.data('confidence') * 28,
          'opacity': (n) => 0.4 + n.data('confidence') * 0.6,
          'border-width': 1,
          'border-color': 'rgba(255,255,255,0.2)',
        },
      },
      { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#f1f5f9' } },
      { selector: 'edge', style: { 'width': 1.5, 'line-color': 'rgba(255,255,255,0.2)', 'curve-style': 'bezier' } },
    ],
    layout: { name: 'cose', animate: false, padding: 30 },
    wheelSensitivity: 0.3,
  });

  cy.on('tap', 'node', (evt) => selectGraphEntity(evt.target.id()));

  if (!entities.length) {
    document.getElementById('graph-detail').innerHTML = '<div class="empty-hint">Sin resultados.</div>';
  }
}

async function selectGraphEntity(entityId) {
  const detail = document.getElementById('graph-detail');
  detail.innerHTML = '<div class="empty-hint">Cargando…</div>';
  try {
    const entity = await apiGet(`/backoffice/graph/entities/${entityId}`);
    renderGraphDetail(entity);
  } catch (e) {
    detail.innerHTML = `<div class="empty-hint">Error: ${escapeHtml(e.message)}</div>`;
  }
}

function renderGraphDetail(entity) {
  const detail = document.getElementById('graph-detail');
  detail.innerHTML = `
    <div class="detail-title">${escapeHtml(entity.canonical_name)}</div>
    <div class="mono" style="margin:6px 0 14px">${escapeHtml(entity.entity_type)} · confianza ${(entity.confidence * 100).toFixed(0)}%</div>
    ${entity.aliases.length ? `<div style="margin-bottom:12px" class="mono">alias: ${entity.aliases.map(escapeHtml).join(', ')}</div>` : ''}
    <h2>Claims (${entity.claims.length})</h2>
    ${entity.claims.map((c) => `<div class="claim-item">
      <span class="claim-source">${escapeHtml(c.source)}</span>
      <span class="claim-confidence">${(c.confidence * 100).toFixed(0)}%</span>
      <div>${escapeHtml(c.claim_text)}</div>
    </div>`).join('') || '<div class="empty-hint">Sin claims.</div>'}
    ${entity.links.length ? `<h2 style="margin-top:16px">Vínculos</h2>${entity.links.map((l) => `<div class="claim-item">${escapeHtml(l.relation_type)} (${(l.confidence * 100).toFixed(0)}%)</div>`).join('')}` : ''}
  `;
}

// ── Questions ─────────────────────────────────────────────────────────────────

async function loadQuestions() {
  const status = document.getElementById('questions-status-filter').value;
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  params.set('limit', '100');

  const el = document.getElementById('questions-list');
  el.innerHTML = '<div class="empty-hint">Cargando…</div>';
  try {
    const questions = await apiGet(`/backoffice/graph/questions?${params}`);
    renderQuestions(questions);
  } catch (e) {
    el.innerHTML = `<div class="empty-hint">Error: ${escapeHtml(e.message)}</div>`;
  }
  refreshQuestionsBadge();
}

async function refreshQuestionsBadge() {
  try {
    const open = await apiGet('/backoffice/graph/questions?status=open&limit=200');
    const badge = document.getElementById('questions-badge');
    if (open.length > 0) {
      badge.textContent = open.length;
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
  } catch { /* non-fatal */ }
}

function renderQuestions(questions) {
  const el = document.getElementById('questions-list');
  if (!questions.length) { el.innerHTML = '<div class="empty-hint">No hay preguntas.</div>'; return; }
  el.innerHTML = questions.map((q) => `
    <div class="question-card" data-id="${q.id}">
      <div class="question-meta">
        <span class="badge badge-${escapeHtml(q.status)}">${escapeHtml(q.status)}</span>
        <span class="mono">${escapeHtml(q.raised_by_agent)} · ${fmtDate(q.created_at)}</span>
      </div>
      <div class="question-text">${escapeHtml(q.question_text)}</div>
      ${q.candidate_answer ? `<div class="question-candidate">Candidata: ${escapeHtml(q.candidate_answer)} ${q.candidate_confidence != null ? `(${(q.candidate_confidence * 100).toFixed(0)}%)` : ''}</div>` : ''}
      ${q.status === 'open' ? `
        <div class="question-actions">
          <input class="form-input" type="text" placeholder="Escribí una respuesta…" value="${escapeHtml(q.candidate_answer || '')}" />
          <button class="btn-primary btn-small" data-action="answer">Responder</button>
          <button class="btn-secondary btn-small" data-action="dismiss">Descartar</button>
        </div>
      ` : q.answer_text ? `<div class="mono">Respuesta: ${escapeHtml(q.answer_text)}</div>` : ''}
    </div>
  `).join('');

  el.querySelectorAll('.question-card').forEach((card) => {
    const id = card.dataset.id;
    const answerBtn = card.querySelector('[data-action="answer"]');
    const dismissBtn = card.querySelector('[data-action="dismiss"]');
    const input = card.querySelector('input');
    if (answerBtn) answerBtn.addEventListener('click', () => answerQuestion(id, input.value.trim()));
    if (dismissBtn) dismissBtn.addEventListener('click', () => dismissQuestion(id));
  });
}

async function answerQuestion(id, answerText) {
  if (!answerText) { showToast('Escribí una respuesta primero.', true); return; }
  try {
    await apiSend('POST', `/backoffice/graph/questions/${id}/answer`, { answer_text: answerText });
    showToast('Pregunta respondida.');
    loadQuestions();
  } catch (e) {
    showToast('Error: ' + e.message, true);
  }
}

async function dismissQuestion(id) {
  try {
    await apiSend('POST', `/backoffice/graph/questions/${id}/dismiss`);
    showToast('Pregunta descartada.');
    loadQuestions();
  } catch (e) {
    showToast('Error: ' + e.message, true);
  }
}

// ── MCP servers ───────────────────────────────────────────────────────────────

let mcpServersCache = [];

async function loadMcpServers() {
  const el = document.getElementById('mcp-list');
  el.innerHTML = '<div class="empty-hint">Cargando…</div>';
  try {
    mcpServersCache = await apiGet('/backoffice/mcp-servers');
    renderMcpList();
  } catch (e) {
    el.innerHTML = `<div class="empty-hint">Error: ${escapeHtml(e.message)}</div>`;
  }
}

function renderMcpList() {
  const el = document.getElementById('mcp-list');
  if (!mcpServersCache.length) { el.innerHTML = '<div class="empty-hint">Sin servidores registrados.</div>'; return; }
  el.innerHTML = mcpServersCache.map((s) => `
    <div class="mcp-card" data-id="${s.id}">
      <div class="mcp-card-main">
        <div class="mcp-card-name">${escapeHtml(s.name)} ${s.enabled ? '' : '<span class="badge badge-neutral">deshabilitado</span>'}</div>
        <div class="mcp-card-url mono">${escapeHtml(s.url)}</div>
        <div class="mcp-card-status">${s.last_status ? `${s.last_status === 'ok' ? '✓' : '✗'} ${escapeHtml(s.last_status)} · ${fmtDate(s.last_checked_at)}` : 'sin probar todavía'}</div>
      </div>
      <div class="mcp-card-actions">
        <button class="btn-secondary btn-small" data-action="test">Probar</button>
        <button class="btn-secondary btn-small" data-action="edit">Editar</button>
        <button class="btn-danger btn-small" data-action="delete">Borrar</button>
      </div>
    </div>
  `).join('');

  el.querySelectorAll('.mcp-card').forEach((card) => {
    const id = card.dataset.id;
    const server = mcpServersCache.find((s) => s.id === id);
    card.querySelector('[data-action="test"]').addEventListener('click', () => testMcpServer(id, card));
    card.querySelector('[data-action="edit"]').addEventListener('click', () => openMcpModal(server));
    card.querySelector('[data-action="delete"]').addEventListener('click', () => deleteMcpServer(id));
  });
}

async function testMcpServer(id, card) {
  const btn = card.querySelector('[data-action="test"]');
  btn.disabled = true;
  btn.textContent = 'Probando…';
  try {
    const result = await apiSend('POST', `/backoffice/mcp-servers/${id}/test`);
    showToast(result.status === 'ok' ? `Conectado — ${result.tools.length} tools encontradas.` : result.status, result.status !== 'ok');
    loadMcpServers();
  } catch (e) {
    showToast('Error: ' + e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Probar';
  }
}

async function deleteMcpServer(id) {
  if (!confirm('¿Borrar este servidor MCP?')) return;
  try {
    await apiSend('DELETE', `/backoffice/mcp-servers/${id}`);
    showToast('Servidor eliminado.');
    loadMcpServers();
  } catch (e) {
    showToast('Error: ' + e.message, true);
  }
}

function openMcpModal(server) {
  document.getElementById('mcp-modal-title').textContent = server ? 'Editar servidor MCP' : 'Nuevo servidor MCP';
  document.getElementById('mcp-form-id').value = server ? server.id : '';
  document.getElementById('mcp-form-name').value = server ? server.name : '';
  document.getElementById('mcp-form-url').value = server ? server.url : '';
  document.getElementById('mcp-form-auth-header').value = server ? server.auth_header : 'Authorization';
  document.getElementById('mcp-form-api-key').value = '';
  document.getElementById('mcp-form-api-key').placeholder = server && server.has_api_key ? '•••••••• (sin cambios)' : '';
  document.getElementById('mcp-form-enabled').checked = server ? server.enabled : true;
  document.getElementById('mcp-form-error').classList.remove('visible');
  document.getElementById('mcp-modal-overlay').hidden = false;
}

function closeMcpModal() {
  document.getElementById('mcp-modal-overlay').hidden = true;
}

async function submitMcpForm(e) {
  e.preventDefault();
  const id = document.getElementById('mcp-form-id').value;
  const errorEl = document.getElementById('mcp-form-error');
  const body = {
    name: document.getElementById('mcp-form-name').value.trim(),
    url: document.getElementById('mcp-form-url').value.trim(),
    auth_header: document.getElementById('mcp-form-auth-header').value.trim() || 'Authorization',
    enabled: document.getElementById('mcp-form-enabled').checked,
  };
  const apiKeyInput = document.getElementById('mcp-form-api-key').value;
  if (apiKeyInput) body.api_key = apiKeyInput;

  try {
    if (id) {
      await apiSend('PUT', `/backoffice/mcp-servers/${id}`, body);
    } else {
      await apiSend('POST', '/backoffice/mcp-servers', body);
    }
    showToast('Servidor guardado.');
    closeMcpModal();
    loadMcpServers();
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.add('visible');
  }
}

// ── Tools catalog ─────────────────────────────────────────────────────────────

async function loadToolsCatalog() {
  const el = document.getElementById('tools-table');
  el.innerHTML = '<div class="empty-hint">Cargando…</div>';
  try {
    const tools = await apiGet('/backoffice/tools');
    el.innerHTML = `<table><thead><tr><th>Nombre</th><th>Categoría</th><th>Descripción</th><th>Configurable</th></tr></thead><tbody>
      ${tools.map((t) => `<tr>
        <td class="mono">${escapeHtml(t.name)}</td>
        <td><span class="badge badge-neutral">${escapeHtml(t.category)}</span></td>
        <td>${escapeHtml(t.description)}</td>
        <td>${t.configurable ? '✓' : '—'}</td>
      </tr>`).join('')}
    </tbody></table>`;
  } catch (e) {
    el.innerHTML = `<div class="empty-hint">Error: ${escapeHtml(e.message)}</div>`;
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

init();
