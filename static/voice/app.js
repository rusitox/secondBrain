/**
 * secondBrain Voice Interface
 * Handles: auth, recording, STT, SSE streaming, TTS pipeline, wake word
 */

// ── Config ────────────────────────────────────────────────────────────────────

const API_BASE = '';           // same origin
const STORAGE_KEY = 'sb_api_key';
const SESSION_KEY = 'sb_session_id';
const AUTOPLAY_KEY = 'sb_autoplay';
const WAKE_KEY    = 'sb_wake';
const VOICE_KEY   = 'sb_tts_voice';

const TOOL_ICONS = {
  search_memory:    '🔍',
  list_tasks:       '✅',
  get_calendar:     '📅',
  get_user_style:   '🎨',
  search_learnings: '🧠',
  save_learning:    '💾',
};

const HINTS = [
  '¿Qué tengo pendiente hoy?',
  '¿Con quién me reúno mañana?',
  '¿Qué hablamos sobre [proyecto]?',
  'Dame un briefing rápido',
];

// ── State ─────────────────────────────────────────────────────────────────────

let apiKey       = localStorage.getItem(STORAGE_KEY) || '';
let sessionId    = localStorage.getItem(SESSION_KEY)  || crypto.randomUUID();
let autoPlay     = localStorage.getItem(AUTOPLAY_KEY) !== 'false';
let wakeEnabled  = localStorage.getItem(WAKE_KEY) === 'true';
let selectedVoice = localStorage.getItem(VOICE_KEY) || 'nova';

let mediaRecorder   = null;
let audioChunks     = [];
let recordingTimer  = null;
let recordingSeconds = 0;

let waveformAnimId  = null;
let analyser        = null;
let waveformCtx     = null;

let currentAudio    = null;   // currently playing HTMLAudioElement
let currentSpeakBtn = null;   // button that triggered current audio
let audioBlobQueue  = [];     // array of Promise<string|null> (pre-fetched object URLs)
let ttsPlaying      = false;
let ttsGeneration   = 0;      // incremented on stopTTS() to cancel in-flight ops

let wakeRecognition = null;   // SpeechRecognition instance for wake word
let isStreaming     = false;

// ── DOM refs ──────────────────────────────────────────────────────────────────

const authOverlay    = document.getElementById('auth-overlay');
const authForm       = document.getElementById('auth-form');
const emailInput     = document.getElementById('email-input');
const passwordInput  = document.getElementById('password-input');
const authSubmitBtn  = document.getElementById('auth-submit-btn');
const authError      = document.getElementById('auth-error');

const chat           = document.getElementById('chat');
const emptyState     = document.getElementById('empty-state');
const questionInput  = document.getElementById('question-input');
const micBtn         = document.getElementById('mic-btn');
const sendBtn        = document.getElementById('send-btn');
const waveformCvs    = document.getElementById('waveform');
const waveformWrap   = document.getElementById('waveform-container');
const recTimer       = document.getElementById('rec-timer');

const autoBtn        = document.getElementById('auto-btn');
const wakeBtn        = document.getElementById('wake-btn');
const settingsBtn    = document.getElementById('settings-btn');
const settingsPanel  = document.getElementById('settings-panel');
const sessionDisplay = document.getElementById('session-display');
const logoutBtn      = document.getElementById('logout-btn');
const voiceSelect    = document.getElementById('voice-select');
const toast          = document.getElementById('toast');

// ── Init ──────────────────────────────────────────────────────────────────────

function init() {
  localStorage.setItem(SESSION_KEY, sessionId);
  sessionDisplay.textContent = sessionId.slice(0, 8) + '…';
  voiceSelect.value = selectedVoice;

  updateAutoBtn();
  updateWakeBtn();
  renderHints();

  if (!apiKey) {
    authOverlay.style.display = 'flex';
  } else {
    authOverlay.style.display = 'none';
    if (wakeEnabled) startWakeWord();
  }

  // Auto-resize textarea
  questionInput.addEventListener('input', () => {
    questionInput.style.height = 'auto';
    questionInput.style.height = Math.min(questionInput.scrollHeight, 120) + 'px';
  });

  questionInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if (authOverlay.style.display !== 'none') return;
    if (e.target === questionInput) return;
    if (e.code === 'Space' && !isStreaming) {
      e.preventDefault();
      if (mediaRecorder && mediaRecorder.state === 'recording') stopRecording();
      else startRecording();
    }
    if (e.key === 'Escape') {
      if (mediaRecorder && mediaRecorder.state === 'recording') cancelRecording();
      settingsPanel.classList.remove('open');
    }
  });

  // Outside click closes settings
  document.addEventListener('click', (e) => {
    if (!settingsPanel.contains(e.target) && e.target !== settingsBtn) {
      settingsPanel.classList.remove('open');
    }
  });

  waveformCtx = waveformCvs.getContext('2d');
}

// ── Auth ──────────────────────────────────────────────────────────────────────

authForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email    = emailInput.value.trim();
  const password = passwordInput.value;
  if (!email || !password) return;

  authSubmitBtn.disabled = true;
  authSubmitBtn.textContent = 'Entrando…';
  authError.classList.remove('visible');

  const result = await login(email, password);
  authSubmitBtn.disabled = false;
  authSubmitBtn.textContent = 'Entrar';

  if (result) {
    apiKey = result.api_key;
    localStorage.setItem(STORAGE_KEY, apiKey);
    authOverlay.style.display = 'none';
    passwordInput.value = '';
    if (wakeEnabled) startWakeWord();
  } else {
    authError.textContent = 'Credenciales incorrectas.';
    authError.classList.add('visible');
    passwordInput.value = '';
    passwordInput.focus();
  }
});

async function login(email, password) {
  try {
    const resp = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!resp.ok) return null;
    return await resp.json(); // { api_key, user_name }
  } catch {
    return null;
  }
}

logoutBtn.addEventListener('click', () => {
  localStorage.removeItem(STORAGE_KEY);
  apiKey = '';
  authOverlay.style.display = 'flex';
  settingsPanel.classList.remove('open');
  stopWakeWord();
});

// ── Settings ──────────────────────────────────────────────────────────────────

settingsBtn.addEventListener('click', () => settingsPanel.classList.toggle('open'));

voiceSelect.addEventListener('change', () => {
  selectedVoice = voiceSelect.value;
  localStorage.setItem(VOICE_KEY, selectedVoice);
  showToast(`Voz: ${selectedVoice}`);
});

autoBtn.addEventListener('click', () => {
  autoPlay = !autoPlay;
  localStorage.setItem(AUTOPLAY_KEY, autoPlay);
  updateAutoBtn();
  showToast(autoPlay ? 'Auto-play activado' : 'Auto-play desactivado');
});

wakeBtn.addEventListener('click', () => {
  wakeEnabled = !wakeEnabled;
  localStorage.setItem(WAKE_KEY, wakeEnabled);
  updateWakeBtn();
  if (wakeEnabled) startWakeWord();
  else stopWakeWord();
  showToast(wakeEnabled ? 'Wake word activado' : 'Wake word desactivado');
});

function updateAutoBtn() {
  autoBtn.classList.toggle('active', autoPlay);
  autoBtn.title = autoPlay ? 'Auto-play ON' : 'Auto-play OFF';
}

function updateWakeBtn() {
  wakeBtn.classList.toggle('active', wakeEnabled);
}

// ── Hints ─────────────────────────────────────────────────────────────────────

function renderHints() {
  const container = document.getElementById('hint-chips');
  if (!container) return;
  HINTS.forEach(h => {
    const chip = document.createElement('button');
    chip.className = 'hint-chip';
    chip.textContent = h;
    chip.addEventListener('click', () => {
      questionInput.value = h;
      questionInput.dispatchEvent(new Event('input'));
      questionInput.focus();
    });
    container.appendChild(chip);
  });
}

// ── Recording ─────────────────────────────────────────────────────────────────

micBtn.addEventListener('click', () => {
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    stopRecording();
  } else if (micBtn.classList.contains('processing')) {
    // ignore during processing
  } else {
    startRecording();
  }
});

async function startRecording() {
  if (isStreaming) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    setupWaveform(stream);

    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream, { mimeType: getAudioMimeType() });

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      stopWaveformViz();
      processAudio();
    };

    mediaRecorder.start(100);
    micBtn.classList.add('recording');
    micBtn.innerHTML = '<span>⏹</span>';
    waveformWrap.classList.add('visible');

    recordingSeconds = 0;
    recTimer.textContent = '0s';
    recordingTimer = setInterval(() => {
      recordingSeconds++;
      recTimer.textContent = recordingSeconds + 's';
    }, 1000);

  } catch (err) {
    showToast('No se pudo acceder al micrófono');
    console.error(err);
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    clearInterval(recordingTimer);
    mediaRecorder.stop();
    micBtn.classList.remove('recording');
    micBtn.classList.add('processing');
    micBtn.innerHTML = '<span>🎤</span>';
    waveformWrap.classList.remove('visible');
  }
}

function cancelRecording() {
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    clearInterval(recordingTimer);
    mediaRecorder.stop();
    audioChunks = []; // discard
    micBtn.classList.remove('recording');
    micBtn.innerHTML = '<span>🎤</span>';
    waveformWrap.classList.remove('visible');
    stopWaveformViz();
  }
}

async function processAudio() {
  if (audioChunks.length === 0) {
    resetMicBtn();
    return;
  }

  const mimeType = getAudioMimeType();
  const blob = new Blob(audioChunks, { type: mimeType });
  const ext  = mimeType.includes('ogg') ? 'ogg' : 'webm';

  try {
    const formData = new FormData();
    formData.append('file', blob, `recording.${ext}`);

    const resp = await fetch(`${API_BASE}/voice/transcribe`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${apiKey}` },
      body: formData,
    });

    if (!resp.ok) throw new Error(`Transcription error ${resp.status}`);
    const data = await resp.json();

    resetMicBtn();

    if (data.transcript && data.transcript.trim()) {
      questionInput.value = data.transcript.trim();
      questionInput.dispatchEvent(new Event('input'));
      // Auto-send after STT
      await handleSend();
    } else {
      showToast('No se detectó audio. Intentá de nuevo.');
    }
  } catch (err) {
    resetMicBtn();
    showToast('Error al transcribir el audio');
    console.error(err);
  }
}

function resetMicBtn() {
  micBtn.classList.remove('recording', 'processing');
  micBtn.innerHTML = '<span>🎤</span>';
}

function getAudioMimeType() {
  const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg'];
  return types.find(t => MediaRecorder.isTypeSupported(t)) || 'audio/webm';
}

// ── Waveform ──────────────────────────────────────────────────────────────────

function setupWaveform(stream) {
  const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;
  const source = audioCtx.createMediaStreamSource(stream);
  source.connect(analyser);
  drawWaveform();
}

function drawWaveform() {
  if (!analyser) return;
  const bufLen = analyser.frequencyBinCount;
  const dataArr = new Uint8Array(bufLen);
  const W = waveformCvs.clientWidth;
  const H = waveformCvs.clientHeight;
  waveformCvs.width  = W;
  waveformCvs.height = H;

  function draw() {
    waveformAnimId = requestAnimationFrame(draw);
    analyser.getByteTimeDomainData(dataArr);

    waveformCtx.clearRect(0, 0, W, H);
    waveformCtx.lineWidth = 2;
    waveformCtx.strokeStyle = '#ef4444';
    waveformCtx.beginPath();

    const sliceW = W / bufLen;
    let x = 0;

    for (let i = 0; i < bufLen; i++) {
      const v = dataArr[i] / 128.0;
      const y = (v * H) / 2;
      if (i === 0) waveformCtx.moveTo(x, y);
      else waveformCtx.lineTo(x, y);
      x += sliceW;
    }
    waveformCtx.lineTo(W, H / 2);
    waveformCtx.stroke();
  }
  draw();
}

function stopWaveformViz() {
  if (waveformAnimId) cancelAnimationFrame(waveformAnimId);
  analyser = null;
}

// ── Send / Stream ─────────────────────────────────────────────────────────────

sendBtn.addEventListener('click', handleSend);

async function handleSend() {
  const question = questionInput.value.trim();
  if (!question || isStreaming) return;

  questionInput.value = '';
  questionInput.style.height = 'auto';

  hideEmptyState();
  appendUserMessage(question);
  const agentMsg = appendAgentMessage();

  isStreaming = true;
  setInputDisabled(true);
  stopTTS(); // stop any playing audio

  try {
    await streamAgentQuery(question, agentMsg);
  } catch (err) {
    agentMsg.bubble.innerHTML = `<span style="color:var(--recording)">Error al procesar la consulta. Intentá de nuevo.</span>`;
    console.error(err);
  } finally {
    isStreaming = false;
    setInputDisabled(false);
    questionInput.focus();
  }
}

async function streamAgentQuery(question, agentMsg) {
  const resp = await fetch(`${API_BASE}/agent/stream`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ question, session_id: sessionId }),
  });

  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail || `HTTP ${resp.status}`);
  }

  const reader  = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  let fullAnswer = '';
  let sentenceBuf = '';   // accumulates text until sentence boundary for TTS
  let ttsWasStreamed = false;  // true once any sentence was enqueued during streaming
  let toolsUsed = [];

  // Sentence-level TTS: flush when we hit . ? ! or buffer grows past ~80 chars
  function flushTTS(force = false) {
    if (!sentenceBuf.trim()) return;
    const ready = force || /[.?!]\s*$/.test(sentenceBuf) || sentenceBuf.length > 90;
    if (!ready) return;
    const text = sentenceBuf.trim();
    sentenceBuf = '';
    ttsWasStreamed = true;
    enqueueTTS(text);
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buf += decoder.decode(value, { stream: true });

    // Parse SSE frames
    const lines = buf.split('\n');
    buf = lines.pop() || '';

    let evtName = '';
    for (const line of lines) {
      if (line.startsWith('event:')) {
        evtName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        const raw = line.slice(5).trim();
        let payload;
        try { payload = JSON.parse(raw); } catch { continue; }

        if (evtName === 'tool_call') {
          addToolBadge(agentMsg.badges, payload.tool, 'calling');
        } else if (evtName === 'tool_result') {
          updateToolBadge(agentMsg.badges, payload.tool, 'done');
          if (!toolsUsed.includes(payload.tool)) toolsUsed.push(payload.tool);
        } else if (evtName === 'token') {
          fullAnswer += payload.text;
          sentenceBuf += payload.text;
          flushTTS();
          renderStreamingText(agentMsg.bubble, fullAnswer);
        } else if (evtName === 'done') {
          sessionId = payload.session_id || sessionId;
          localStorage.setItem(SESSION_KEY, sessionId);
          sessionDisplay.textContent = sessionId.slice(0, 8) + '…';
          flushTTS(true);  // flush remaining TTS buffer
        } else if (evtName === 'error') {
          throw new Error(payload.detail || 'Agent error');
        }
        evtName = '';
      }
    }
  }

  // Finalize message
  finalizeAgentMessage(agentMsg, fullAnswer, ttsWasStreamed);
}

// ── Chat rendering ────────────────────────────────────────────────────────────

function hideEmptyState() {
  if (emptyState) emptyState.style.display = 'none';
}

function appendUserMessage(text) {
  const msg = document.createElement('div');
  msg.className = 'msg user';
  msg.innerHTML = `
    <div class="msg-role">Vos</div>
    <div class="msg-bubble">${escapeHtml(text)}</div>
    <div class="msg-footer"><span class="msg-time">${formatTime()}</span></div>
  `;
  chat.appendChild(msg);
  scrollChat();
  return msg;
}

function appendAgentMessage() {
  const msg = document.createElement('div');
  msg.className = 'msg agent';

  const role = document.createElement('div');
  role.className = 'msg-role';
  role.textContent = 'secondBrain';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';

  const badges = document.createElement('div');
  badges.className = 'tool-badges';

  // Show thinking dots initially
  const thinking = document.createElement('div');
  thinking.className = 'thinking-dots';
  thinking.innerHTML = '<span></span><span></span><span></span>';

  bubble.appendChild(badges);
  bubble.appendChild(thinking);
  msg.appendChild(role);
  msg.appendChild(bubble);
  chat.appendChild(msg);
  scrollChat();

  return { el: msg, bubble, badges, thinking };
}

function addToolBadge(container, toolName, status) {
  // Check if badge already exists
  const existing = container.querySelector(`[data-tool="${toolName}"]`);
  if (existing) return;

  const badge = document.createElement('span');
  badge.className = `tool-badge ${status}`;
  badge.dataset.tool = toolName;
  const icon = TOOL_ICONS[toolName] || '🔧';
  badge.textContent = `${icon} ${toolName}`;
  container.appendChild(badge);
}

function updateToolBadge(container, toolName, status) {
  const badge = container.querySelector(`[data-tool="${toolName}"]`);
  if (badge) badge.className = `tool-badge ${status}`;
}

function renderStreamingText(bubble, text) {
  // Remove thinking dots if present
  const thinking = bubble.querySelector('.thinking-dots');
  if (thinking) thinking.remove();

  // Keep badges, update text
  const textNode = bubble.querySelector('.stream-text') || (() => {
    const el = document.createElement('div');
    el.className = 'stream-text';
    bubble.appendChild(el);
    return el;
  })();

  textNode.innerHTML = renderMarkdown(text) + '<span class="stream-cursor"></span>';
  scrollChat();
}

function finalizeAgentMessage(agentMsg, fullAnswer, ttsWasStreamed = false) {
  const { bubble } = agentMsg;

  // Remove thinking dots
  const thinking = bubble.querySelector('.thinking-dots');
  if (thinking) thinking.remove();

  // Set final content
  const textNode = bubble.querySelector('.stream-text') || bubble;
  if (bubble.querySelector('.stream-text')) {
    textNode.innerHTML = renderMarkdown(fullAnswer);
  } else {
    // No streaming happened (tool-only response)
    bubble.innerHTML = '';
    const badges = agentMsg.badges;
    bubble.appendChild(badges);
    const content = document.createElement('div');
    content.innerHTML = renderMarkdown(fullAnswer || '(sin respuesta)');
    bubble.appendChild(content);
  }

  // Add footer with time + speak button
  const footer = document.createElement('div');
  footer.className = 'msg-footer';
  footer.innerHTML = `<span class="msg-time">${formatTime()}</span>`;

  if (fullAnswer) {
    const speakBtn = document.createElement('button');
    speakBtn.className = 'speak-btn';
    speakBtn.innerHTML = '▶ reproducir';
    speakBtn.addEventListener('click', () => onSpeakBtnClick(speakBtn, fullAnswer));
    footer.appendChild(speakBtn);
  }

  agentMsg.el.appendChild(footer);
  scrollChat();

  if (autoPlay && fullAnswer && !ttsWasStreamed) {
    // Only enqueue the full answer if no sentences were streamed during generation
    enqueueTTS(fullAnswer);
  }
}

// ── TTS pipeline ──────────────────────────────────────────────────────────────
// Pipelined: fetch next audio while current is playing to eliminate gaps.

function enqueueTTS(text) {
  if (!autoPlay) return;
  const gen = ttsGeneration;
  // Start fetching immediately — don't wait for current audio to finish
  audioBlobQueue.push(_fetchTTSUrl(text, gen));
  _drainAudioQueue();
}

async function _fetchTTSUrl(text, gen) {
  const cleanText = stripMarkdown(text);
  if (!cleanText.trim()) return null;
  try {
    const resp = await fetch(`${API_BASE}/voice/speak`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: cleanText, voice: selectedVoice }),
    });
    if (!resp.ok || gen !== ttsGeneration) return null;
    const blob = await resp.blob();
    if (gen !== ttsGeneration) return null;
    return URL.createObjectURL(blob);
  } catch {
    return null;
  }
}

async function _drainAudioQueue() {
  if (ttsPlaying) return;
  ttsPlaying = true;

  while (audioBlobQueue.length > 0) {
    const urlPromise = audioBlobQueue.shift();
    const gen = ttsGeneration;
    const url = await urlPromise;   // may already be resolved (no extra wait)
    if (!url || gen !== ttsGeneration) continue;
    await _playUrl(url, gen);
    URL.revokeObjectURL(url);
  }

  ttsPlaying = false;
}

async function _playUrl(url, gen) {
  return new Promise((resolve) => {
    const audio = new Audio(url);
    currentAudio = audio;
    const done = () => { currentAudio = null; resolve(); };
    audio.onended = done;
    audio.onerror = done;
    audio.play().catch(done);

    // Bail out immediately if stopTTS() was called mid-play
    const iv = setInterval(() => {
      if (gen !== ttsGeneration) { audio.pause(); clearInterval(iv); done(); }
    }, 100);
    audio.onended = () => { clearInterval(iv); done(); };
    audio.onerror = () => { clearInterval(iv); done(); };
  });
}

// Legacy wrapper used by the "▶ reproducir" button
async function playTTS(text) {
  const url = await _fetchTTSUrl(text, ttsGeneration);
  if (!url) return;
  await _playUrl(url, ttsGeneration);
  URL.revokeObjectURL(url);
}

function stopTTS() {
  ttsGeneration++;          // invalidates all in-flight fetches and queued items
  audioBlobQueue = [];
  ttsPlaying = false;
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  if (currentSpeakBtn) {
    currentSpeakBtn.classList.remove('playing');
    currentSpeakBtn.innerHTML = '▶ reproducir';
    currentSpeakBtn = null;
  }
}

async function onSpeakBtnClick(btn, text) {
  if (btn.classList.contains('playing')) {
    stopTTS();
    return;
  }

  stopTTS();
  currentSpeakBtn = btn;
  btn.classList.add('playing');
  btn.innerHTML = '⏹ detener';

  try {
    await playTTS(text);
  } finally {
    if (currentSpeakBtn === btn) {
      btn.classList.remove('playing');
      btn.innerHTML = '▶ reproducir';
      currentSpeakBtn = null;
    }
  }
}

// ── Wake word ─────────────────────────────────────────────────────────────────

const WAKE_PHRASES = ['hey brain', 'secondbrain', 'second brain', 'oye brain', 'hey secondbrain'];

function startWakeWord() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    showToast('Wake word requiere Chrome o Edge');
    wakeEnabled = false;
    updateWakeBtn();
    return;
  }

  wakeRecognition = new SR();
  wakeRecognition.continuous = true;
  wakeRecognition.interimResults = true;
  wakeRecognition.lang = 'es-AR';

  wakeRecognition.onresult = (event) => {
    const last = event.results[event.results.length - 1];
    const transcript = last[0].transcript.toLowerCase().trim();

    if (WAKE_PHRASES.some(p => transcript.includes(p))) {
      if (!isStreaming && !(mediaRecorder && mediaRecorder.state === 'recording')) {
        showToast('Wake word detectado!');
        startRecording();
      }
    }
  };

  wakeRecognition.onend = () => {
    if (wakeEnabled) {
      // Auto-restart
      setTimeout(() => {
        try { wakeRecognition.start(); } catch {}
      }, 500);
    }
  };

  try {
    wakeRecognition.start();
  } catch (e) {
    console.warn('Wake word start error:', e);
  }
}

function stopWakeWord() {
  if (wakeRecognition) {
    try { wakeRecognition.stop(); } catch {}
    wakeRecognition = null;
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function scrollChat() {
  requestAnimationFrame(() => {
    chat.scrollTop = chat.scrollHeight;
  });
}

function setInputDisabled(disabled) {
  questionInput.disabled = disabled;
  sendBtn.disabled = disabled;
  micBtn.style.pointerEvents = disabled ? 'none' : '';
}

function formatTime() {
  return new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function renderMarkdown(text) {
  if (window.marked) {
    try {
      const raw = window.marked.parse(text, { breaks: true, gfm: true });
      return window.DOMPurify ? window.DOMPurify.sanitize(raw) : raw;
    } catch {}
  }
  return escapeHtml(text).replace(/\n/g, '<br>');
}

function stripMarkdown(text) {
  return text
    .replace(/#{1,6}\s+/g, '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\*(.*?)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1')
    .replace(/^[-*+]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .trim();
}

function showToast(msg, duration = 2800) {
  toast.textContent = msg;
  toast.classList.add('visible');
  setTimeout(() => toast.classList.remove('visible'), duration);
}

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
