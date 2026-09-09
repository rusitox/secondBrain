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
const runningAgentKeys = new Set(); // agent_keys with a manual run in flight — survives re-render/navigation
let selectedRunId = null;
let selectedConversationId = null;
let cy = null;                 // cytoscape instance
let claimsChart = null;
let confidenceChart = null;

// Graph view state (Fase 1 — explorador enfocado)
let graphEntitiesCache = [];   // last GET /graph/entities response
let graphLinksCache = [];      // last GET /graph/links response
let graphEntityById = new Map();  // id -> entity (from graphEntitiesCache)
let graphAdjacency = new Map();   // id -> Set(neighbor ids)
let graphEdgesByPair = new Map(); // "idA|idB" -> link, both orderings
let graphMode = 'focus';       // 'focus' | 'map'
let graphFocusEntityId = null;
let graphZoom = 1;

const AGENT_KEYS_META = {
  slack: { label: 'Slack', icon: '💬' },
  outlook: { label: 'Outlook', icon: '📧' },
  teams: { label: 'Teams', icon: '👥' },
  fathom: { label: 'Fathom', icon: '🎙' },
  notion: { label: 'Notion', icon: '📝' },
  rd: { label: 'I+D Platform', icon: '🔬' },
  orchestrator: { label: 'Orchestrator (chat)', icon: '🧠' },
  reconciliation: { label: 'Reconciliación', icon: '🧬' },
  negotiation: { label: 'Negociación', icon: '🤝' },
};

const RUN_TYPE_LABELS = {
  domain_agent: 'Agente de dominio',
  rd_agent: 'I+D',
  reconciliation: 'Reconciliación',
  negotiation: 'Negociación',
  chat: 'Chat',
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
  document.getElementById('runs-type-filter').addEventListener('change', loadRuns);
  document.getElementById('runs-status-filter').addEventListener('change', loadRuns);

  document.getElementById('conv-refresh').addEventListener('click', loadConversations);
  document.getElementById('conv-outcome-filter').addEventListener('change', loadConversations);
  document.getElementById('conv-participant-filter').addEventListener('input', debounce(loadConversations, 250));

  document.getElementById('graph-refresh').addEventListener('click', () => loadGraph({ resetFocus: true }));
  document.getElementById('graph-search').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadGraph({ resetFocus: true });
  });
  document.getElementById('graph-mode-focus').addEventListener('click', () => setGraphMode('focus'));
  document.getElementById('graph-mode-map').addEventListener('click', () => setGraphMode('map'));
  document.getElementById('graph-hops').addEventListener('change', renderCurrentGraphMode);

  document.getElementById('questions-refresh').addEventListener('click', loadQuestions);
  document.getElementById('questions-status-filter').addEventListener('change', () => {
    questionsPage = 1;
    loadQuestions();
  });

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

/** Like apiGet, but also reads X-Total-Count — for paginated list endpoints
 * that set it (GET /graph/entities, GET /graph/questions) so the UI can show
 * "página X de Y" instead of silently truncating at whatever `limit` the
 * page fetch used. Falls back to data.length if the header is absent. */
async function apiGetWithTotal(path) {
  const resp = await authedFetch(path);
  if (!resp.ok) throw new Error(`GET ${path} -> ${resp.status}`);
  const data = await resp.json();
  const totalHeader = resp.headers.get('X-Total-Count');
  return { data, total: totalHeader !== null ? parseInt(totalHeader, 10) : data.length };
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
  if (view === 'conversations') loadConversations();
  if (view === 'graph') loadGraph();
  if (view === 'questions') { questionsPage = 1; loadQuestions(); }
  if (view === 'mcps') { loadMcpServers(); loadToolsCatalog(); }
  if (view === 'architecture') renderArchitectureView();
}

function debounce(fn, ms) {
  let t = null;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
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
    return `<div class="agent-card ${a.agent_key === selectedAgentKey ? 'selected' : ''}" data-key="${escapeHtml(a.agent_key)}">
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
    agentsCache.map((a) => `<option value="${escapeHtml(a.agent_key)}">${escapeHtml((AGENT_KEYS_META[a.agent_key] || {}).label || a.agent_key)}</option>`).join('');
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
        <button class="btn-primary btn-small" id="agent-run-btn"></button>
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
  setAgentRunButtonState(config.agent_key);
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
  if (runningAgentKeys.has(agentKey)) return; // already in flight (e.g. navigated away and back)
  runningAgentKeys.add(agentKey);
  // Re-render the button if this agent is still the one on screen — the
  // handler that fired this may be on a stale, already-detached button
  // (user navigated to another agent while a previous run was in flight).
  if (selectedAgentKey === agentKey) setAgentRunButtonState(agentKey);
  try {
    const run = await apiSend('POST', `/backoffice/agents/${agentKey}/run`);
    showToast(`Corrida completa: ${run.status}`);
    if (currentView === 'runs') loadRuns();
  } catch (e) {
    showToast('Error al correr el agente: ' + e.message, true);
  } finally {
    runningAgentKeys.delete(agentKey);
    if (selectedAgentKey === agentKey) setAgentRunButtonState(agentKey);
  }
}

function setAgentRunButtonState(agentKey) {
  const btn = document.getElementById('agent-run-btn');
  if (!btn) return;
  const running = runningAgentKeys.has(agentKey);
  btn.disabled = running;
  btn.textContent = running ? 'Corriendo… (puede tardar)' : '▶ Correr ahora';
}

// ── Runs ──────────────────────────────────────────────────────────────────────
// Only top-level runs (parent_run_id is null) — negotiation sub-runs live in
// the Conversations view, or nested under the run that triggered them.

function agentLabel(key) {
  const meta = AGENT_KEYS_META[key] || { label: key, icon: '🤖' };
  return `${meta.icon} ${escapeHtml(meta.label)}`;
}

function truncate(s, n) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

async function loadRuns() {
  const agentKey = document.getElementById('runs-agent-filter').value;
  const runType = document.getElementById('runs-type-filter').value;
  const status = document.getElementById('runs-status-filter').value;
  const params = new URLSearchParams();
  if (agentKey) params.set('agent_key', agentKey);
  if (runType) params.set('run_type', runType);
  if (status) params.set('status', status);
  params.set('top_level', 'true');
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
  el.innerHTML = `<table><thead><tr><th>Agente</th><th>Tipo</th><th>Estado</th><th>Trigger</th><th>Inicio</th></tr></thead><tbody>
    ${runs.map((r) => `<tr class="clickable ${r.id === selectedRunId ? 'selected' : ''}" data-id="${r.id}">
      <td>${agentLabel(r.agent_key)}</td>
      <td class="mono">${escapeHtml(RUN_TYPE_LABELS[r.run_type] || r.run_type)}</td>
      <td><span class="badge badge-${escapeHtml(r.status)}">${escapeHtml(r.status)}</span></td>
      <td class="mono">${escapeHtml(r.trigger)}</td>
      <td class="mono">${fmtDate(r.started_at)}</td>
    </tr>`).join('')}
  </tbody></table>`;
  el.querySelectorAll('tr.clickable').forEach((row) => {
    row.addEventListener('click', () => selectRun(row.dataset.id, 'run-detail'));
  });
}

/** Shared by the Runs detail pane and the Conversations detail pane —
 * containerId picks which one gets re-rendered on drill-down/back nav. */
async function selectRun(runId, containerId = 'run-detail') {
  if (!runId) return;
  if (containerId === 'run-detail') {
    selectedRunId = runId;
    document.querySelectorAll('#runs-table tr').forEach((r) => r.classList.toggle('selected', r.dataset.id === runId));
  } else {
    selectedConversationId = runId;
    document.querySelectorAll('#conversations-list tr').forEach((r) => r.classList.toggle('selected', r.dataset.id === runId));
  }
  const detail = document.getElementById(containerId);
  detail.innerHTML = '<div class="empty-hint">Cargando…</div>';
  try {
    const run = await apiGet(`/backoffice/runs/${runId}`);
    detail.innerHTML = buildRunDetailHtml(run, containerId);
    wireRunDetailEvents(detail, run, containerId);
  } catch (e) {
    detail.innerHTML = `<div class="empty-hint">Error: ${escapeHtml(e.message)}</div>`;
  }
}

function wireRunDetailEvents(detail, run, containerId) {
  const backBtn = detail.querySelector('[data-action="back-to-parent"]');
  if (backBtn) backBtn.addEventListener('click', () => selectRun(run.parent_run_id, containerId));
  const jumpBtn = detail.querySelector('[data-action="jump-to-runs"]');
  if (jumpBtn) {
    jumpBtn.addEventListener('click', async () => {
      switchView('runs');
      await loadRuns();
      selectRun(run.parent_run_id, 'run-detail');
    });
  }
  detail.querySelectorAll('[data-action="open-sub-run"]').forEach((card) => {
    card.addEventListener('click', () => selectRun(card.dataset.id, containerId));
  });
}

function buildRunDetailHtml(run, containerId) {
  const isConversation = run.run_type === 'negotiation';
  const backAction = containerId === 'conversation-detail' && run.parent_run_id ? 'jump-to-runs' : 'back-to-parent';
  const header = `
    <div class="detail-header">
      <div class="detail-title">${agentLabel(run.agent_key)} <span class="badge badge-${escapeHtml(run.status)}">${escapeHtml(run.status)}</span></div>
    </div>
    <div class="mono" style="margin-bottom:10px">
      ${fmtDate(run.started_at)} → ${fmtDate(run.finished_at)} (${fmtDuration(run.duration_ms)})
      ${run.total_tokens ? ` · ${run.total_tokens} tokens` : ''} · disparado por ${escapeHtml(run.trigger)}
    </div>
    ${run.parent_run_id ? `<button type="button" class="btn-secondary btn-small" data-action="${backAction}" style="margin-bottom:12px">
      ← ${backAction === 'jump-to-runs' ? 'Ver la corrida que la disparó' : 'Volver a la corrida padre'}
    </button>` : ''}
    ${run.error ? `<div class="form-error visible" style="margin-bottom:10px">${escapeHtml(run.error)}</div>` : ''}
  `;

  if (isConversation) return header + buildConversationBodyHtml(run);

  return header + `
    ${run.summary ? `<div style="margin-bottom:10px">${escapeHtml(run.summary)}</div>` : ''}
    <h2>Traza</h2>
    <div class="timeline">
      ${run.events.length ? run.events.map(renderTimelineEvent).join('') : '<div class="empty-hint">Sin eventos registrados.</div>'}
    </div>
    ${run.sub_runs.length ? `<div class="sub-runs">
      <h2>Conversaciones disparadas (${run.sub_runs.length})</h2>
      ${run.sub_runs.map((s) => `<div class="timeline-event clickable" data-action="open-sub-run" data-id="${s.id}">
        <div class="timeline-actor">🤝 ${escapeHtml(s.stats && s.stats.participants ? s.stats.participants.join(' + ') : 'negociación')} · <span class="badge badge-${escapeHtml(s.status)}">${escapeHtml(s.status)}</span></div>
        <div class="timeline-body">${escapeHtml(s.summary || 'Sin conclusión.')} <span class="link-hint">Ver conversación →</span></div>
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

// ── Conversations (negotiation runs — interaction + conclusion) ────────────────

async function loadConversations() {
  const outcome = document.getElementById('conv-outcome-filter').value;
  const participant = document.getElementById('conv-participant-filter').value.trim().toLowerCase();
  const params = new URLSearchParams({ run_type: 'negotiation', limit: '100' });
  if (outcome) params.set('status', outcome);

  const el = document.getElementById('conversations-list');
  el.innerHTML = '<div class="empty-hint">Cargando…</div>';
  try {
    let runs = await apiGet(`/backoffice/runs?${params}`);
    if (participant) {
      // negotiate_same_as' node names are the fixed "entity_a/b_negotiator" —
      // the real source names live in stats.sources, not stats.participants.
      runs = runs.filter((r) => {
        const stats = r.stats || {};
        const haystack = [...(stats.participants || []), ...(stats.sources || [])];
        return haystack.some((p) => p.toLowerCase().includes(participant));
      });
    }
    renderConversationsTable(runs);
  } catch (e) {
    el.innerHTML = `<div class="empty-hint">Error: ${escapeHtml(e.message)}</div>`;
  }
}

function renderConversationsTable(runs) {
  const el = document.getElementById('conversations-list');
  if (!runs.length) { el.innerHTML = '<div class="empty-hint">Sin conversaciones todavía.</div>'; return; }
  el.innerHTML = `<table><thead><tr><th>Sobre qué</th><th>Participantes</th><th>Resultado</th><th>Inicio</th></tr></thead><tbody>
    ${runs.map((r) => {
      const stats = r.stats || {};
      const participants = (stats.participants || []).map((p) => `<span class="chip">${escapeHtml(p)}</span>`).join(' ');
      return `<tr class="clickable ${r.id === selectedConversationId ? 'selected' : ''}" data-id="${r.id}">
        <td>${escapeHtml(truncate(stats.question || r.summary || '—', 80))}</td>
        <td>${participants || '—'}</td>
        <td><span class="badge badge-${escapeHtml(r.status)}">${escapeHtml(r.status)}</span></td>
        <td class="mono">${fmtDate(r.started_at)}</td>
      </tr>`;
    }).join('')}
  </tbody></table>`;
  el.querySelectorAll('tr.clickable').forEach((row) => {
    row.addEventListener('click', () => selectRun(row.dataset.id, 'conversation-detail'));
  });
}

function buildConversationBodyHtml(run) {
  const stats = run.stats || {};
  const participants = stats.participants || [];
  const contextLines = [];
  if (stats.question) contextLines.push(`<div><strong>Pregunta:</strong> ${escapeHtml(stats.question)}</div>`);
  const entityLabel = stats.entity_name
    || (stats.entity_a_name && stats.entity_b_name ? `${stats.entity_a_name} ↔ ${stats.entity_b_name}` : null);
  if (entityLabel) contextLines.push(`<div><strong>Entidad:</strong> ${escapeHtml(entityLabel)}</div>`);

  const handoffEvents = run.events.filter((e) => e.event_type === 'handoff');
  const handoffChips = handoffEvents.length
    ? [handoffEvents[0].actor, ...handoffEvents.map((e) => e.payload.to)]
    : participants;

  const verdictEvent = run.events.find((e) => e.event_type === 'verdict') || null;
  const turns = groupEventsIntoTurns(run.events.filter((e) => e.event_type !== 'handoff' && e.event_type !== 'verdict'));

  return `
    ${contextLines.length ? `<div class="conv-context">${contextLines.join('')}</div>` : ''}
    ${participants.length ? `<div style="margin-bottom:10px"><strong>Participantes:</strong> ${participants.map((p) => `<span class="chip">${escapeHtml(p)}</span>`).join(' ')}</div>` : ''}
    ${handoffChips.length ? `<div class="handoff-map">${handoffChips.map((c) => `<span class="chip chip-handoff">${escapeHtml(c)}</span>`).join('<span class="handoff-arrow">→</span>')}</div>` : ''}
    <h2>Conversación</h2>
    <div class="chat-thread">
      ${turns.length ? turns.map(renderChatTurn).join('') : '<div class="empty-hint">Sin turnos registrados.</div>'}
    </div>
    ${renderVerdictCard(verdictEvent, run)}
  `;
}

function groupEventsIntoTurns(events) {
  const turns = [];
  for (const ev of events) {
    const last = turns[turns.length - 1];
    if (last && last.actor === (ev.actor || null)) last.events.push(ev);
    else turns.push({ actor: ev.actor || null, events: [ev] });
  }
  return turns;
}

function renderChatTurn(turn) {
  return `<div class="chat-turn">
    <div class="chat-turn-actor">${escapeHtml(turn.actor || 'sistema')}</div>
    <div class="chat-turn-body">${turn.events.map(renderChatEvent).join('') || '<span class="empty-hint">—</span>'}</div>
  </div>`;
}

function renderChatEvent(ev) {
  if (ev.event_type === 'assistant_text') return ev.payload.text ? `<p>${escapeHtml(ev.payload.text)}</p>` : '';
  if (ev.event_type === 'tool_call') return `<details><summary>🔧 ${escapeHtml(ev.tool_name || 'tool')}</summary><pre>${escapeHtml(JSON.stringify(ev.payload.input, null, 2))}</pre></details>`;
  if (ev.event_type === 'tool_result') return `<details><summary>↩ resultado</summary><pre>${escapeHtml(JSON.stringify(ev.payload.content, null, 2))}</pre></details>`;
  if (ev.event_type === 'error') return `<p class="chat-event-error">${escapeHtml(ev.payload.error || '')}</p>`;
  return `<pre>${escapeHtml(JSON.stringify(ev.payload))}</pre>`;
}

function renderVerdictCard(verdictEvent, run) {
  // Both negotiation tools init their verdict dict with default values *before*
  // the swarm runs and always record it, even when the swarm itself crashed
  // (run.status !== 'completed') — that default is not a real conclusion, so
  // a crashed run must never reach the payload branches below.
  const payload = run.status === 'completed' && verdictEvent ? verdictEvent.payload : null;
  if (!payload) {
    return `<div class="verdict-card ${run.status === 'failed' ? 'verdict-escalated' : ''}">
      <div class="verdict-title">${run.status === 'failed' ? '⚠️ La negociación falló' : (run.status === 'completed' ? '✅ Conclusión' : '⏳ En curso')}</div>
      ${run.summary ? `<div>${escapeHtml(run.summary)}</div>` : '<div class="empty-hint">Sin veredicto registrado.</div>'}
    </div>`;
  }
  let title;
  let body;
  let resolved;
  if ('resolved' in payload) {
    resolved = !!payload.resolved;
    title = resolved ? '✅ Conclusión entre pares' : '⚠️ Sin acuerdo — escalada al humano';
    body = payload.answer;
  } else {
    resolved = true;
    title = '🧬 Veredicto de duplicado';
    body = `${payload.same_entity ? 'Son la misma entidad — se fusionan.' : 'Son entidades distintas.'} ${payload.reasoning || ''}`.trim();
  }
  const confidence = payload.confidence != null ? `${Math.round(payload.confidence * 100)}%` : null;
  return `<div class="verdict-card ${resolved ? 'verdict-resolved' : 'verdict-escalated'}">
    <div class="verdict-title">${title}</div>
    ${body ? `<div>${escapeHtml(body)}</div>` : ''}
    ${confidence ? `<div class="mono">confianza: ${confidence}</div>` : ''}
  </div>`;
}

// ── Graph ─────────────────────────────────────────────────────────────────────
// Fase 1 — explorador enfocado. Default: sólo el vecindario (1-2 saltos) de
// una entidad, layout concentric — legible por construcción, sin nodos
// sueltos compitiendo por espacio. "Mapa completo" es un modo aparte que
// excluye nodos sin relaciones (van a una bandeja aparte) y atenúa
// etiquetas para no superponerse.

const TYPE_COLORS = {
  person: '#6366f1', project: '#22c55e', initiative: '#f59e0b',
  topic: '#38bdf8', organization: '#a78bfa',
};
const LABEL_ZOOM_THRESHOLD = 1.1;
const LABEL_DEGREE_THRESHOLD = 6;

async function loadGraph(opts = {}) {
  const search = document.getElementById('graph-search').value.trim();
  const entityType = document.getElementById('graph-type-filter').value;
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (entityType) params.set('entity_type', entityType);
  params.set('limit', '150');

  try {
    const [entities, links] = await Promise.all([
      apiGet(`/backoffice/graph/entities?${params}`),
      apiGet('/backoffice/graph/links'),
    ]);
    indexGraphData(entities, links);

    if (opts.resetFocus || !graphFocusEntityId || !graphEntityById.has(graphFocusEntityId)) {
      graphFocusEntityId = !entities.length ? null : (search ? entities[0].id : pickDefaultFocusEntity());
    }
    renderCurrentGraphMode();
  } catch (e) {
    showToast('Error cargando el grafo: ' + e.message, true);
  }
}

function indexGraphData(entities, links) {
  graphEntitiesCache = entities;
  graphLinksCache = links;
  graphEntityById = new Map(entities.map((e) => [e.id, e]));
  graphAdjacency = new Map(entities.map((e) => [e.id, new Set()]));
  graphEdgesByPair = new Map();
  for (const link of links) {
    if (!graphEntityById.has(link.entity_id_a) || !graphEntityById.has(link.entity_id_b)) continue;
    graphAdjacency.get(link.entity_id_a).add(link.entity_id_b);
    graphAdjacency.get(link.entity_id_b).add(link.entity_id_a);
    graphEdgesByPair.set(`${link.entity_id_a}|${link.entity_id_b}`, link);
    graphEdgesByPair.set(`${link.entity_id_b}|${link.entity_id_a}`, link);
  }
}

function graphDegree(id) {
  const neighbors = graphAdjacency.get(id);
  return neighbors ? neighbors.size : 0;
}

/** No search typed → land on the best-connected entity instead of an empty
 * canvas, so the view is useful the moment you open it. */
function pickDefaultFocusEntity() {
  let best = null;
  for (const e of graphEntitiesCache) {
    if (!best || graphDegree(e.id) > graphDegree(best.id)) best = e;
  }
  return best ? best.id : null;
}

function setGraphMode(mode) {
  graphMode = mode;
  document.getElementById('graph-mode-focus').classList.toggle('active', mode === 'focus');
  document.getElementById('graph-mode-map').classList.toggle('active', mode === 'map');
  document.getElementById('graph-hops').style.visibility = mode === 'focus' ? 'visible' : 'hidden';
  renderCurrentGraphMode();
}

function renderCurrentGraphMode() {
  if (!graphEntitiesCache.length) {
    if (cy) { cy.destroy(); cy = null; }
    document.getElementById('cy').innerHTML = '';
    document.getElementById('graph-stats').textContent = '';
    document.getElementById('graph-isolated').innerHTML = '';
    document.getElementById('graph-legend').innerHTML = '';
    document.getElementById('graph-detail').innerHTML = '<div class="empty-hint">Sin resultados.</div>';
    return;
  }
  renderGraphChrome();
  if (graphMode === 'focus') renderFocusGraph();
  else renderMapGraph();
}

function renderGraphChrome() {
  const linkCount = graphLinksCache.filter((l) => graphEntityById.has(l.entity_id_a) && graphEntityById.has(l.entity_id_b)).length;
  const isolated = graphEntitiesCache.filter((e) => graphDegree(e.id) === 0);
  document.getElementById('graph-stats').textContent =
    `${graphEntitiesCache.length} entidades · ${linkCount} relaciones · ${isolated.length} sin relaciones`;

  document.getElementById('graph-legend').innerHTML = Object.entries(TYPE_COLORS)
    .map(([type, color]) => `<span class="legend-item"><span class="legend-dot" style="background:${color}"></span>${escapeHtml(type)}</span>`)
    .join('');

  renderIsolatedTray(isolated);
}

/** Entities with no relations don't earn canvas space (that's what made the
 * old graph unreadable) — they live here instead, still one click from their
 * claims. */
function renderIsolatedTray(isolated) {
  const el = document.getElementById('graph-isolated');
  if (!isolated.length) { el.innerHTML = ''; return; }
  el.innerHTML = `<details>
    <summary>Sin relaciones (${isolated.length})</summary>
    <div class="graph-isolated-list">
      ${isolated.map((e) => `<button type="button" class="chip chip-clickable" data-id="${e.id}">${escapeHtml(e.canonical_name)}</button>`).join('')}
    </div>
  </details>`;
  el.querySelectorAll('[data-id]').forEach((btn) => {
    btn.addEventListener('click', () => { selectGraphEntity(btn.dataset.id); });
  });
}

function focusGraphEntity(entityId) {
  graphFocusEntityId = entityId;
  if (graphMode !== 'focus') setGraphMode('focus');
  else renderCurrentGraphMode();
}

/** BFS from centerId → Map(id -> hop distance), bounded to `hops`. */
function graphNeighborhood(centerId, hops) {
  const visited = new Map([[centerId, 0]]);
  let frontier = [centerId];
  for (let hop = 1; hop <= hops; hop++) {
    const next = [];
    for (const id of frontier) {
      for (const neighbor of graphAdjacency.get(id) || []) {
        if (!visited.has(neighbor)) { visited.set(neighbor, hop); next.push(neighbor); }
      }
    }
    frontier = next;
  }
  return visited;
}

function renderFocusGraph() {
  const centerId = graphFocusEntityId;
  const container = document.getElementById('cy');
  if (!centerId || !graphEntityById.has(centerId)) {
    if (cy) { cy.destroy(); cy = null; }
    container.innerHTML = '';
    document.getElementById('graph-detail').innerHTML = '<div class="empty-hint">Buscá o elegí una entidad para ver su vecindario.</div>';
    return;
  }
  const hops = parseInt(document.getElementById('graph-hops').value, 10) || 1;
  const visited = graphNeighborhood(centerId, hops);

  const nodeElements = [...visited.entries()].map(([id, dist]) => {
    const e = graphEntityById.get(id);
    return { data: { id, label: e.canonical_name, type: e.entity_type, confidence: e.confidence, degree: graphDegree(id), dist } };
  });
  const edgeElements = [];
  const seenEdges = new Set();
  for (const id of visited.keys()) {
    for (const neighbor of graphAdjacency.get(id) || []) {
      if (!visited.has(neighbor)) continue;
      const link = graphEdgesByPair.get(`${id}|${neighbor}`);
      if (!link || seenEdges.has(link.id)) continue;
      seenEdges.add(link.id);
      edgeElements.push({ data: { id: link.id, source: link.entity_id_a, target: link.entity_id_b, relation: link.relation_type, confidence: link.confidence } });
    }
  }

  buildCy(container, nodeElements, edgeElements, {
    alwaysShowLabels: true,
    layout: {
      name: 'concentric', animate: true, fit: true, padding: 40,
      concentric: (n) => -n.data('dist'), equidistant: true, minNodeSpacing: 45,
    },
  });
  cy.getElementById(centerId).select();
  selectGraphEntity(centerId);
}

function renderMapGraph() {
  const container = document.getElementById('cy');
  const connected = graphEntitiesCache.filter((e) => graphDegree(e.id) > 0);
  if (!connected.length) {
    if (cy) { cy.destroy(); cy = null; }
    container.innerHTML = '';
    document.getElementById('graph-detail').innerHTML = '<div class="empty-hint">Ninguna entidad tiene relaciones todavía — mirá la bandeja de abajo.</div>';
    return;
  }

  const nodeElements = connected.map((e) => ({
    data: { id: e.id, label: e.canonical_name, type: e.entity_type, confidence: e.confidence, degree: graphDegree(e.id) },
  }));
  const edgeElements = [];
  const seenEdges = new Set();
  for (const e of connected) {
    for (const neighbor of graphAdjacency.get(e.id) || []) {
      const link = graphEdgesByPair.get(`${e.id}|${neighbor}`);
      if (!link || seenEdges.has(link.id)) continue;
      seenEdges.add(link.id);
      edgeElements.push({ data: { id: link.id, source: link.entity_id_a, target: link.entity_id_b, relation: link.relation_type, confidence: link.confidence } });
    }
  }

  buildCy(container, nodeElements, edgeElements, {
    alwaysShowLabels: false,
    layout: {
      name: 'cose', animate: true, randomize: true, fit: true, padding: 30,
      nodeRepulsion: 9000, idealEdgeLength: 70, gravity: 40, numIter: 1500,
      componentSpacing: 150, // keeps disconnected clusters from overlapping
    },
  });
}

function buildCy(container, nodeElements, edgeElements, { layout, alwaysShowLabels }) {
  if (cy) cy.destroy();
  graphZoom = 1;

  cy = cytoscape({
    container,
    elements: [...nodeElements, ...edgeElements],
    style: [
      {
        selector: 'node',
        style: {
          'background-color': (n) => TYPE_COLORS[n.data('type')] || '#94a3b8',
          // Map mode only shows a label once zoomed in, or for a well-connected
          // node — otherwise 80+ labels stack on top of each other.
          'label': (n) => (alwaysShowLabels || graphZoom >= LABEL_ZOOM_THRESHOLD || n.data('degree') >= LABEL_DEGREE_THRESHOLD) ? n.data('label') : '',
          'color': '#c9d1e0',
          'font-size': 10,
          'text-valign': 'bottom',
          'text-margin-y': 4,
          'width': (n) => 9 + Math.min(n.data('degree'), 10) * 3.5,
          'height': (n) => 9 + Math.min(n.data('degree'), 10) * 3.5,
          'opacity': (n) => 0.5 + n.data('confidence') * 0.5,
          'border-width': 1,
          'border-color': 'rgba(255,255,255,0.2)',
          'transition-property': 'opacity',
          'transition-duration': 150,
        },
      },
      { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#f1f5f9', 'label': 'data(label)' } },
      { selector: 'node.faded', style: { 'opacity': 0.08 } },
      {
        selector: 'edge',
        style: {
          'width': 1,
          'line-color': 'rgba(255,255,255,0.15)',
          'curve-style': 'haystack',
          'haystack-radius': 0,
          'opacity': 1,
          'transition-property': 'opacity',
          'transition-duration': 150,
        },
      },
      { selector: 'edge.faded', style: { 'opacity': 0.03 } },
      { selector: 'edge.highlighted', style: { 'line-color': 'rgba(255,255,255,0.5)' } },
    ],
    layout,
    wheelSensitivity: 0.3,
    minZoom: 0.2,
    maxZoom: 3,
  });

  // Focus mode: clicking a node re-centers the neighborhood on it (Obsidian's
  // "local graph" navigation). Map mode: clicking just opens its detail panel.
  cy.on('tap', 'node', (evt) => {
    const id = evt.target.id();
    if (graphMode === 'focus') focusGraphEntity(id);
    else selectGraphEntity(id);
  });

  cy.on('mouseover', 'node', (evt) => {
    const node = evt.target;
    const neighborhood = node.closedNeighborhood();
    cy.elements().difference(neighborhood).addClass('faded');
    neighborhood.edges().addClass('highlighted');
  });
  cy.on('mouseout', 'node', () => {
    cy.elements().removeClass('faded').removeClass('highlighted');
  });

  if (!alwaysShowLabels) {
    cy.on('zoom', () => { graphZoom = cy.zoom(); cy.style().update(); });
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

function otherEntityLabel(link, entityId) {
  const otherId = link.entity_id_a === entityId ? link.entity_id_b : link.entity_id_a;
  const other = graphEntityById.get(otherId);
  return other ? other.canonical_name : `#${otherId.slice(0, 8)}`;
}

function renderGraphDetail(entity) {
  const detail = document.getElementById('graph-detail');
  const showFocusBtn = graphMode === 'map' || graphFocusEntityId !== entity.id;
  detail.innerHTML = `
    <div class="detail-title">${escapeHtml(entity.canonical_name)}</div>
    <div class="mono" style="margin:6px 0 14px">${escapeHtml(entity.entity_type)} · confianza ${(entity.confidence * 100).toFixed(0)}%</div>
    ${entity.aliases.length ? `<div style="margin-bottom:12px" class="mono">alias: ${entity.aliases.map(escapeHtml).join(', ')}</div>` : ''}
    ${showFocusBtn ? '<button type="button" class="btn-secondary btn-small" id="graph-focus-here-btn" style="margin-bottom:14px">🔎 Ver vecindario</button>' : ''}
    <h2>Relaciones (${entity.links.length})</h2>
    ${entity.links.length ? `<table class="relations-table"><tbody>
      ${entity.links.map((l) => `<tr>
        <td>${escapeHtml(otherEntityLabel(l, entity.id))}</td>
        <td class="mono">${escapeHtml(l.relation_type)}</td>
        <td class="mono">${(l.confidence * 100).toFixed(0)}%</td>
      </tr>`).join('')}
    </tbody></table>` : '<div class="empty-hint">Sin relaciones.</div>'}
    <h2 style="margin-top:16px">Claims (${entity.claims.length})</h2>
    ${entity.claims.map((c) => `<div class="claim-item">
      <span class="claim-source">${escapeHtml(c.source)}</span>
      <span class="claim-confidence">${(c.confidence * 100).toFixed(0)}%</span>
      <div>${escapeHtml(c.claim_text)}</div>
    </div>`).join('') || '<div class="empty-hint">Sin claims.</div>'}
  `;
  if (showFocusBtn) {
    document.getElementById('graph-focus-here-btn').addEventListener('click', () => focusGraphEntity(entity.id));
  }
}

// ── Questions ─────────────────────────────────────────────────────────────────

let questionsPage = 1;
const QUESTIONS_PAGE_SIZE = 100;

async function loadQuestions() {
  const status = document.getElementById('questions-status-filter').value;
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  params.set('limit', String(QUESTIONS_PAGE_SIZE));
  params.set('offset', String((questionsPage - 1) * QUESTIONS_PAGE_SIZE));

  const el = document.getElementById('questions-list');
  el.innerHTML = '<div class="empty-hint">Cargando…</div>';
  document.getElementById('questions-pagination').innerHTML = '';
  try {
    const { data: questions, total } = await apiGetWithTotal(`/backoffice/graph/questions?${params}`);
    if (!questions.length && questionsPage > 1) {
      // Landed past the last page (e.g. just dismissed the last item on it) — step back.
      questionsPage = Math.max(1, Math.ceil(total / QUESTIONS_PAGE_SIZE));
      return loadQuestions();
    }
    renderQuestions(questions);
    renderQuestionsPagination(total);
  } catch (e) {
    el.innerHTML = `<div class="empty-hint">Error: ${escapeHtml(e.message)}</div>`;
  }
  refreshQuestionsBadge();
}

function renderQuestionsPagination(total) {
  const el = document.getElementById('questions-pagination');
  const pageCount = Math.max(1, Math.ceil(total / QUESTIONS_PAGE_SIZE));
  if (pageCount <= 1) {
    el.innerHTML = total ? `<span class="pagination-summary mono">${total} pregunta${total === 1 ? '' : 's'}</span>` : '';
    return;
  }
  el.innerHTML = `
    <button type="button" class="btn-secondary btn-small" id="questions-prev" ${questionsPage <= 1 ? 'disabled' : ''}>« Anterior</button>
    <span class="pagination-summary mono">Página ${questionsPage} de ${pageCount} · ${total} preguntas</span>
    <button type="button" class="btn-secondary btn-small" id="questions-next" ${questionsPage >= pageCount ? 'disabled' : ''}>Siguiente »</button>
  `;
  const prevBtn = document.getElementById('questions-prev');
  const nextBtn = document.getElementById('questions-next');
  if (prevBtn) prevBtn.addEventListener('click', () => { questionsPage -= 1; loadQuestions(); });
  if (nextBtn) nextBtn.addEventListener('click', () => { questionsPage += 1; loadQuestions(); });
}

async function refreshQuestionsBadge() {
  try {
    // limit=1 — the body is discarded, only X-Total-Count matters here, so
    // there's no reason to pull a full page just to read .length off it
    // (that undercounted whenever open questions outnumbered the limit).
    const { total } = await apiGetWithTotal('/backoffice/graph/questions?status=open&limit=1');
    const badge = document.getElementById('questions-badge');
    if (total > 0) {
      badge.textContent = total > 99 ? '99+' : String(total);
      badge.title = `${total} preguntas abiertas`;
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
  } catch { /* non-fatal */ }
}

/** Two entity names (entity_name + candidate_entity_name) means this is a
 * reconciliation question ("¿son la misma entidad?"); one name means the
 * question is about that single entity; neither means it isn't scoped to
 * an entity at all (context carried no entity_id). */
function questionEntityLabel(q) {
  if (q.entity_name && q.candidate_entity_name) {
    return `${escapeHtml(q.entity_name)} ↔ ${escapeHtml(q.candidate_entity_name)} <span class="mono">(¿son la misma entidad?)</span>`;
  }
  if (q.entity_name) return escapeHtml(q.entity_name);
  return null;
}

function renderQuestions(questions) {
  const el = document.getElementById('questions-list');
  if (!questions.length) { el.innerHTML = '<div class="empty-hint">No hay preguntas.</div>'; return; }
  el.innerHTML = questions.map((q) => {
    const entityLabel = questionEntityLabel(q);
    return `
    <div class="question-card" data-id="${q.id}">
      <div class="question-meta">
        <span class="badge badge-${escapeHtml(q.status)}">${escapeHtml(q.status)}</span>
        <span class="mono">${escapeHtml(q.raised_by_agent)} · ${fmtDate(q.created_at)}</span>
      </div>
      ${entityLabel ? `<div class="question-entity">🏷 ${entityLabel}</div>` : ''}
      <div class="question-text">${escapeHtml(q.question_text)}</div>
      ${q.candidate_answer ? `<div class="question-candidate">Candidata: ${escapeHtml(q.candidate_answer)} ${q.candidate_confidence != null ? `(${(q.candidate_confidence * 100).toFixed(0)}%)` : ''}</div>` : ''}
      ${q.status === 'open' ? `
        <div class="question-actions">
          ${q.entity_name && q.candidate_entity_name ? `
            <input class="form-input" type="text" placeholder="Motivo (opcional)…" value="${escapeHtml(q.candidate_answer || '')}" />
            <button class="btn-primary btn-small" data-action="answer-same">✅ Son la misma</button>
            <button class="btn-secondary btn-small" data-action="answer-different">❌ Son distintas</button>
          ` : `
            <input class="form-input" type="text" placeholder="Escribí una respuesta…" value="${escapeHtml(q.candidate_answer || '')}" />
            <button class="btn-primary btn-small" data-action="answer">Responder</button>
          `}
          <button class="btn-secondary btn-small" data-action="dismiss">Descartar</button>
        </div>
      ` : q.answer_text ? `<div class="mono">Respuesta: ${escapeHtml(q.answer_text)}</div>` : ''}
    </div>
  `;
  }).join('');

  el.querySelectorAll('.question-card').forEach((card) => {
    const id = card.dataset.id;
    const input = card.querySelector('input');
    const answerBtn = card.querySelector('[data-action="answer"]');
    const answerSameBtn = card.querySelector('[data-action="answer-same"]');
    const answerDifferentBtn = card.querySelector('[data-action="answer-different"]');
    const dismissBtn = card.querySelector('[data-action="dismiss"]');
    if (answerBtn) answerBtn.addEventListener('click', () => answerQuestion(id, input.value.trim(), true));
    if (answerSameBtn) {
      answerSameBtn.addEventListener('click', () => (
        answerQuestion(id, input.value.trim() || 'Confirmado: son la misma entidad.', true)
      ));
    }
    if (answerDifferentBtn) {
      // confirmed=false closes the question (dismissed) without linking —
      // same_as never gets created, but the reasoning is kept as answer_text
      // instead of being discarded like a plain "Descartar" would.
      answerDifferentBtn.addEventListener('click', () => (
        answerQuestion(id, input.value.trim() || 'Confirmado: son entidades distintas.', false)
      ));
    }
    if (dismissBtn) dismissBtn.addEventListener('click', () => dismissQuestion(id));
  });
}

/** confirmed=true (default) actually writes to the graph — a same_as link
 * for an identity question, a CONFIRMED_BY_USER claim otherwise — matching
 * what confirming the same question in chat would do. confirmed=false closes
 * the question without touching the graph, keeping the answer_text as a note
 * (e.g. "these are distinct" for an identity question, so a "Son distintas"
 * click doesn't get misread as agreeing they're the same). */
async function answerQuestion(id, answerText, confirmed = true) {
  if (!answerText) { showToast('Escribí una respuesta primero.', true); return; }
  try {
    await apiSend('POST', `/backoffice/graph/questions/${id}/answer`, { answer_text: answerText, confirmed });
    showToast(confirmed ? 'Pregunta respondida.' : 'Marcado y cerrado.');
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
  const submitBtn = e.target.querySelector('button[type=submit]');
  const body = {
    name: document.getElementById('mcp-form-name').value.trim(),
    url: document.getElementById('mcp-form-url').value.trim(),
    auth_header: document.getElementById('mcp-form-auth-header').value.trim() || 'Authorization',
    enabled: document.getElementById('mcp-form-enabled').checked,
  };
  const apiKeyInput = document.getElementById('mcp-form-api-key').value.trim();
  if (apiKeyInput) body.api_key = apiKeyInput;

  submitBtn.disabled = true;
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
  } finally {
    submitBtn.disabled = false;
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

// ── Architecture ──────────────────────────────────────────────────────────────
// Fase 3: documents the resolution ladder (specs/plan-multi-agent-knowledge.md)
// and gives every synthetic agent_key that shows up in Runs/Conversations
// (reconciliation, negotiation) a place to be explained — they're processes,
// not configurable agents, so they have no card in the Agents view.

const ARCH_DIAGRAM = `graph TD
  subgraph Fuentes
    SRC_SLACK[Slack]
    SRC_OUTLOOK[Outlook]
    SRC_TEAMS[Teams]
    SRC_FATHOM[Fathom]
    SRC_NOTION[Notion]
    SRC_ID["Plataforma I+D (MCP)"]
  end
  subgraph "Agentes de dominio (configurables)"
    A_SLACK(slack)
    A_OUTLOOK(outlook)
    A_TEAMS(teams)
    A_FATHOM(fathom)
    A_NOTION(notion)
    A_RD(rd)
  end
  SRC_SLACK --> A_SLACK
  SRC_OUTLOOK --> A_OUTLOOK
  SRC_TEAMS --> A_TEAMS
  SRC_FATHOM --> A_FATHOM
  SRC_NOTION --> A_NOTION
  SRC_ID --> A_RD

  A_SLACK & A_OUTLOOK & A_TEAMS & A_FATHOM & A_NOTION & A_RD --> KB[("Grafo de conocimiento
compartido")]

  KB --> CONSULT{"¿Duda sobre
una entidad?"}
  CONSULT -->|"consult_knowledge_base
responde"| KB
  CONSULT -->|"sigue sin resolverse"| NEGO["🤝 negociación entre pares
(ask_peer_agents, Swarm)"]
  NEGO -->|"acuerdo"| KB
  NEGO -->|"sin acuerdo"| HUMAN["❓ escalate_or_validate
→ Preguntas pendientes"]
  HUMAN -->|"humano responde"| KB

  SCHED["⏱ Scheduler
(por usuario, cada ciclo)"] --> A_SLACK & A_OUTLOOK & A_TEAMS & A_FATHOM & A_NOTION & A_RD
  SCHED --> RECON["🧬 Reconciliación
(duplicados por similitud)"]
  RECON -->|"candidato dudoso"| NEGO2["🤝 negociación entre pares
(negotiate_same_as, Swarm)"]
  NEGO2 -->|"misma entidad"| MERGE["same_as → fusión"]
  MERGE --> KB
  RECON --> KB

  CHAT["🧠 Orchestrator
(chat CLI / voz)"] --> KB
  CHAT -->|"duda puntual, antes
de responder (ask_domain_agents)"| NEGO
`;

const ARCH_ACTORS = [
  {
    icon: '💬📧👥🎙📝', title: 'Agentes de dominio', runType: 'domain_agent', configurable: true,
    body: 'Uno por fuente (Slack, Outlook, Teams, Fathom, Notion). En cada ciclo leen documentos nuevos de su fuente y proponen entidades/claims al grafo compartido.',
  },
  {
    icon: '🔬', title: 'I+D Platform (rd)', runType: 'rd_agent', configurable: true,
    body: 'De sólo lectura, sobre la plataforma de I+D vía servidor MCP. Mismo patrón que los agentes de dominio, pero su fuente es un MCP externo en vez de la tabla Document.',
  },
  {
    icon: '🧬', title: 'Reconciliación', runType: 'reconciliation', configurable: false,
    body: 'Corre sola al final de cada ciclo del scheduler. Busca entidades candidatas a duplicado cross-fuente por similitud de embeddings, y dispara una negociación por cada candidato dudoso.',
  },
  {
    icon: '🤝', title: 'Negociación', runType: 'negotiation', configurable: false,
    body: 'Swarm acotado de 2+ agentes pares, disparado por un agente que duda (ask_peer_agents), por reconciliación sospechando un duplicado (negotiate_same_as), o por el orchestrator validando una duda antes de responder (ask_domain_agents). Su conversación completa vive en Conversaciones.',
  },
  {
    icon: '🧠', title: 'Orchestrator (chat)', runType: 'chat', configurable: true,
    body: 'El agente que responde en el CLI y por voz. Antes de responder puede validar una duda con los agentes de dominio relevantes (ask_domain_agents) en vez de conformarse con lo ya consolidado. Su system prompt se compone dinámicamente por request (identidad, estilo, fecha) — por eso no es editable desde acá.',
  },
];

let archDiagramRendered = false;

async function renderArchitectureView() {
  renderArchActorCards();
  await renderArchDiagram();
}

function renderArchActorCards() {
  const el = document.getElementById('arch-actor-cards');
  el.innerHTML = ARCH_ACTORS.map((a) => `
    <div class="arch-actor-card">
      <div class="arch-actor-title">${a.icon} ${escapeHtml(a.title)}</div>
      <div class="arch-actor-body">${escapeHtml(a.body)}</div>
      <div class="arch-actor-meta">
        <span class="badge ${a.configurable ? 'badge-completed' : 'badge-neutral'}">${a.configurable ? 'configurable' : 'proceso del sistema'}</span>
        <button type="button" class="btn-secondary btn-small" data-run-type="${a.runType}">Ver corridas →</button>
      </div>
    </div>
  `).join('');
  el.querySelectorAll('[data-run-type]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const runType = btn.dataset.runType;
      if (runType === 'negotiation') { switchView('conversations'); return; }
      // Set the filter before switching — switchView('runs') already calls
      // loadRuns() once; setting it after would mean a second, redundant fetch.
      document.getElementById('runs-type-filter').value = runType;
      switchView('runs');
    });
  });
}

/** Rendered once — mermaid.render() replaces the <pre> with a static SVG, so
 * re-running it against the same content on every view switch is wasted work. */
async function renderArchDiagram() {
  const el = document.getElementById('arch-diagram');
  if (archDiagramRendered) return;
  if (typeof mermaid === 'undefined') {
    el.textContent = ARCH_DIAGRAM;
    return;
  }
  try {
    mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict' });
    const { svg } = await mermaid.render('arch-diagram-svg', ARCH_DIAGRAM);
    el.innerHTML = svg;
    archDiagramRendered = true;
  } catch {
    el.textContent = ARCH_DIAGRAM;
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

init();
