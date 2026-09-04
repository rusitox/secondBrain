# Plan: Voice Interface

**Rama**: `feat/voice-interface`  
**Estado**: En planificación — 2026-09-03

---

## Objetivo

Interfaz de voz profesional como canal principal de interacción con el agente multiagente. El usuario habla, el agente escucha, piensa (con visibilidad de herramientas), y responde en voz + texto. Streaming real de tokens para que el audio empiece antes de que termine de generar. Wake word para activación hands-free. Whisper local para privacidad y uso offline.

---

## Decisiones de diseño

### Stack tecnológico

| Capa | Tecnología | Justificación |
|------|-----------|---------------|
| STT local | `openai-whisper` (Python lib) | Privacidad total, sin costo, funciona offline. Modelo configurable (tiny/base/small). |
| STT fallback | OpenAI Whisper API | Cuando el modelo local no está disponible o para mayor precisión. |
| TTS | OpenAI TTS API (`tts-1` / `tts-1-hd`) | Voz natural en español. Sin nuevas libs (openai ya instalado). |
| Streaming | Server-Sent Events (SSE) | Endpoint `/agent/stream` transmite tokens + eventos de tool call en tiempo real. |
| Wake word | Web Speech API (`continuous=true`) | Nativo en browser, sin WASM ni libs externas para MVP. |
| Frontend | Vanilla JS + Tailwind CSS CDN + Marked.js CDN | Sin build step. Servido por FastAPI StaticFiles. |
| Audio recording | MediaRecorder API (WebM/Opus) | Nativo en browsers modernos. |
| Waveform viz | Web Audio API AnalyserNode | Visualización en tiempo real del audio capturado. |

### Por qué web UI y no CLI

El CLI requiere librerías de audio nativas con deps del sistema complicadas cross-platform (portaudio, sounddevice, pyaudio). El browser tiene acceso nativo al micrófono, altavoces y APIs de visualización de audio sin instalación alguna. Además permite una UI con diseño profesional que el terminal no puede ofrecer.

### Modo STT: local vs API

Configurable via variable de entorno `STT_MODE`:
- `local` → carga modelo Whisper en memoria al iniciar el servidor (default en producción para privacidad)
- `api` → llama a OpenAI Whisper API por cada transcripción (default en dev si no hay GPU)
- El modelo local (`tiny`/`base`/`small`) configurable via `WHISPER_MODEL`

### Auth en el web UI

Mismo mecanismo que el CLI: API key `Bearer`. En el primer acceso el UI muestra un modal de login, guarda la key en `localStorage` y la envía en cada request. Sin cambios en el backend de auth.

---

## Diseño de UI — especificación visual detallada

### Concepto general

Dark mode exclusivo. Diseño minimalista centrado en la voz, inspirado en interfaces de asistentes de voz premium (no un chat genérico). La jerarquía visual prioriza el estado de la conversación sobre el texto.

### Paleta de colores

```css
--bg-base:       #080d1a   /* fondo base — deep navy casi negro */
--bg-surface:    #0f1829   /* paneles y burbujas */
--bg-glass:      rgba(255,255,255,0.04)  /* glassmorphism */
--border-subtle: rgba(255,255,255,0.07)
--accent:        #6366f1   /* indigo — acción primaria */
--accent-glow:   rgba(99,102,241,0.3)
--recording:     #ef4444   /* rojo — grabando */
--recording-glow:rgba(239,68,68,0.35)
--success:       #22c55e
--text-primary:  #f1f5f9
--text-secondary:#94a3b8
--text-muted:    #475569
```

### Tipografía

- Font: **Inter** (Google Fonts CDN, weights 300/400/500/600)
- Respuestas del agente: 15px/1.7 line-height
- Input: 16px (evita zoom en iOS)
- Metadata (tools, session): 11px, monospace para valores técnicos

### Layout (viewport completo, sin scroll de página)

```
┌────────────────────────────────────────────────────┐
│  Header: logo + session info + controles (80px)    │
├────────────────────────────────────────────────────┤
│                                                    │
│  Chat history — scroll interno (flex-1)            │
│                                                    │
│   ┌─ Burbuja usuario ─────────────────────────┐   │
│   │  ¿Cuáles son mis compromisos pendientes?  │   │
│   └────────────────────────────────────────────┘  │
│                                                    │
│   ┌─ Burbuja agente ──────────────────────────┐   │
│   │  [tool badge: search_memory] [list_tasks] │   │
│   │                                           │   │
│   │  Tenés 3 compromisos pendientes:          │   │
│   │  • Enviar propuesta a Cliente X — hoy     │   │
│   │  • Revisar contrato Proyecto Y — viernes  │   │
│   │  • Responder a Juan — sin fecha           │   │
│   │                                     [▶]  │   │
│   └────────────────────────────────────────────┘  │
│                                                    │
│   [agente pensando — tool call en curso...]        │
│                                                    │
├────────────────────────────────────────────────────┤
│  Input area (140px fijo en bottom)                 │
│  ┌──────────────────────────────────┐  [🎤]       │
│  │  Escribí o hablá...              │  [enviar]   │
│  └──────────────────────────────────┘             │
└────────────────────────────────────────────────────┘
```

### Botón de micrófono — estados y animaciones

El micrófono es el elemento central del UI. Tiene 4 estados:

**Idle** (en reposo)
- Círculo 56px, fondo `--bg-glass`, borde `--border-subtle`
- Ícono de micrófono en `--text-secondary`
- Hover: escala 1.05, `--accent-glow` como box-shadow

**Recording** (grabando)
- Fondo `--recording`, borde transparente
- Pulse animation: `@keyframes pulse-ring` — ring exterior que crece y se desvanece cada 1.5s
- Waveform canvas de 200px de ancho sobre el input que muestra el audio en tiempo real (AnalyserNode)
- Timer de segundos en la esquina superior del canvas

**Processing** (transcribiendo)
- Spinner CSS sobre el ícono
- Label debajo: "transcribiendo..."
- Estado bloqueado (no se puede hacer clic)

**Agent thinking** (agente procesando)
- No cambia el botón pero se muestra un indicador de "herramienta en uso" en el chat
- Tool badges aparecen con fade-in a medida que el streaming trae los eventos

### Burbujas del chat

**Burbuja usuario**
```css
background: rgba(99,102,241,0.12);
border: 1px solid rgba(99,102,241,0.2);
border-radius: 18px 18px 4px 18px;
padding: 12px 16px;
max-width: 80%;
margin-left: auto;  /* alineado a la derecha */
```

**Burbuja agente**
```css
background: var(--bg-glass);
border: 1px solid var(--border-subtle);
backdrop-filter: blur(12px);
border-radius: 4px 18px 18px 18px;
padding: 16px;
max-width: 90%;
```

**Tool badges** (dentro de la burbuja agente, antes del texto)
```css
display: inline-flex;
background: rgba(99,102,241,0.15);
border: 1px solid rgba(99,102,241,0.25);
border-radius: 4px;
padding: 2px 8px;
font-size: 11px;
font-family: monospace;
color: var(--accent);
gap: 4px;  /* íconos por herramienta */
```

Íconos por herramienta:
- `search_memory` → 🔍
- `list_tasks` → ✅
- `get_calendar` → 📅
- `get_user_style` → 🎨
- `search_learnings` → 🧠
- `save_learning` → 💾

**Estado streaming** (mientras el agente escribe)
- Cursor parpadeante al final del texto parcial
- Texto aparece token a token con transición suave

**Botón de audio** (▶ reproducir respuesta)
- Ícono pequeño bottom-right de la burbuja
- Al hacer clic: llama a `/agent/speak`, reproduce mp3
- Durante reproducción: ícono cambia a ⏹, subtle border-left animado en la burbuja

### Header

```
[⬡ secondBrain]    [session: 8f3a2b...]  [🔊 auto] [☽ wake] [⚙]
```

- Logo text con monospace y color `--accent`
- Session ID abreviado (primeros 8 chars)
- Toggle auto-play (🔊/🔇) — si activo, cada respuesta se lee automáticamente
- Toggle wake word (☽ = inactivo, 🟢 = escuchando)
- Engranaje → panel lateral de configuración (API key, voz TTS, modelo Whisper)

### Input area

- Textarea con auto-resize (máximo 4 líneas antes de hacer scroll interno)
- Placeholder que rota: "¿Qué tengo hoy?", "¿Quién me escribió esta semana?", "Hablá o escribí..."
- `Enter` envía, `Shift+Enter` nueva línea
- Diseño unificado: el waveform de grabación reemplaza visualmente el textarea durante la captura

### Markdown rendering

Las respuestas del agente se renderizan con **Marked.js** (CDN):
- Listas (`•` con color accent)
- Negrita y cursiva
- Código inline y bloques (con Highlight.js, tema `github-dark`)
- Headers H1-H3 (para briefings)
- Links (se abren en nueva tab)

### Responsive — mobile

En pantallas < 640px:
- Header colapsa a solo logo + botones esenciales
- El botón de micrófono sube a 64px (más fácil de tocar)
- Las burbujas son full-width
- El waveform se muestra encima del botón en lugar del input

---

## Fase 1 — Whisper local + endpoints de audio

### Nuevas dependencias

**requirements.txt:**
```
openai-whisper>=20231117      # STT local (diferente del paquete openai)
python-multipart>=0.0.6       # ya requerido por FastAPI para file uploads
```

**Dockerfile** (runtime stage):
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
```

**Nota**: `openai-whisper` descarga el modelo al primer uso. En producción, pre-descargar y montar como volumen para no redescargar en cada restart. Se documenta en el README.

### Nuevas variables de entorno

```env
STT_MODE=local           # local | api
WHISPER_MODEL=base       # tiny | base | small | medium | large
TTS_VOICE=nova           # alloy | echo | fable | onyx | nova | shimmer
TTS_MODEL=tts-1          # tts-1 | tts-1-hd (hd = mayor calidad, más lento)
VOICE_MAX_AUDIO_MB=25    # límite de upload de audio en MB
```

### `app/api/schemas/voice.py` (nuevo)

```python
class TranscribeResponse(BaseModel):
    transcript: str
    language: str
    duration_seconds: Optional[float]

class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)
    voice: str = Field(default="nova")
```

### `app/services/voice/transcriber.py` (nuevo)

Servicio singleton que:
- En startup carga el modelo Whisper si `STT_MODE=local`
- `async def transcribe(audio_bytes: bytes, filename: str) -> TranscribeResponse`
  - Si local: escribe a tempfile → `whisper.load_model().transcribe()` → limpia tempfile
  - Si api: `openai.audio.transcriptions.create(model="whisper-1", file=...)`
- Expuesto como singleton para evitar recargar el modelo en cada request

### `app/services/voice/tts.py` (nuevo)

```python
async def synthesize(text: str, voice: str, model: str) -> AsyncIterator[bytes]:
    """Stream MP3 chunks from OpenAI TTS."""
    async with openai_client.audio.speech.with_streaming_response.create(
        model=model, voice=voice, input=text
    ) as response:
        async for chunk in response.iter_bytes():
            yield chunk
```

### `app/api/routers/voice.py` (nuevo)

```
POST /voice/transcribe
  Auth: Bearer
  Body: multipart/form-data { file: UploadFile }
  Response: TranscribeResponse

POST /voice/speak
  Auth: Bearer
  Body: SpeakRequest
  Response: StreamingResponse (audio/mpeg)
```

### `app/core/config.py` — nuevos campos

```python
stt_mode: str = "api"          # local | api
whisper_model: str = "base"
tts_voice: str = "nova"
tts_model: str = "tts-1"
voice_max_audio_mb: int = 25
```

---

## Fase 2 — Streaming SSE del agente

El streaming permite que el audio empiece a reproducirse mientras el agente aún está generando texto. Arquitectura: tokens llegan via SSE → el frontend acumula oraciones → llama a `/voice/speak` por oración → reproduce audio mientras sigue recibiendo texto.

### Nuevo endpoint `POST /agent/stream`

```
POST /agent/stream
Auth: Bearer
Body: AgentQueryRequest (mismo que /agent/query)
Response: text/event-stream

Eventos SSE:
  event: tool_call
  data: {"tool": "search_memory", "status": "calling"}

  event: tool_result
  data: {"tool": "search_memory", "status": "done", "count": 3}

  event: token
  data: {"text": "Tenés "}

  event: token
  data: {"text": "3 compromisos"}

  event: done
  data: {"session_id": "...", "iterations": 3, "tools_used": [...]}

  event: error
  data: {"detail": "LLM unavailable"}
```

### Modificación a `LLMClient.generate_with_tools()`

Agregar parámetro opcional `stream_callback: Optional[Callable[[str], Awaitable[None]]] = None`.

Cuando está presente:
- En Anthropic: usar `stream=True` en la llamada final (después de los tool calls)
- Llamar a `stream_callback(token_text)` por cada chunk de texto
- El resultado final sigue siendo `ToolUseResult` (compatibilidad total con `/agent/query` existente)

Los tool calls intermedios NO se streamean vía el callback — se envían como eventos SSE separados (`tool_call` / `tool_result`) desde el router.

### `app/api/routers/agent_stream.py` (nuevo) o ampliar `agent.py`

```python
@router.post("/stream")
async def agent_stream(
    data: AgentQueryRequest,
    current_user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    async def event_generator() -> AsyncIterator[dict]:
        # Envía tool_call events + tokens via callbacks
        ...
    return EventSourceResponse(event_generator())
```

**Nueva dependencia:**
```
sse-starlette>=1.6,<2.0    # SSE support para FastAPI
```

### Frontend: TTS pipeline de baja latencia

```javascript
// Acumula tokens hasta completar una oración (. ? ! o 80+ chars)
// Cuando tiene una oración: POST /voice/speak → AudioContext → reproduce
// Encola el audio: mientras reproduce oración 1, ya está solicitando oración 2
```

El efecto para el usuario: el agente empieza a hablar ~1-2 segundos después de que el LLM genera la primera oración, en lugar de esperar toda la respuesta.

---

## Fase 3 — Wake word

### Implementación: Web Speech API (continuous)

El browser puede escuchar continuamente usando `SpeechRecognition` con `continuous=true` y `interimResults=true`. Detectamos la frase de activación en el transcript interim.

```javascript
const wakeWords = ["hey brain", "secondbrain", "oye brain", "second brain"];

recognition.onresult = (event) => {
  const transcript = event.results[event.results.length - 1][0].transcript.toLowerCase();
  if (wakeWords.some(w => transcript.includes(w))) {
    activateVoiceInput();  // cambia al estado de grabación completa
  }
};
```

**Limitaciones conocidas y cómo las manejamos:**
- Chrome solo: Firefox tiene soporte limitado → mostrar badge "Chrome recomendado" al activar wake word
- Requiere HTTPS en producción → documentado en deployment guide
- Consume CPU en background → el toggle de wake word en el header es claramente visible, default OFF

**Toggle wake word** (☽ en el header):
- OFF por default
- Al activar: muestra indicador visual pulsante, browser pide permiso de micrófono si no lo tiene
- Cuando detecta wake word: el botón de mic hace "pop" visual y empieza a grabar automáticamente

---

## Fase 4 — Polish y accesibilidad

- **Keyboard-first**: `Space` = push to talk, `Escape` = cancelar, `Enter` = enviar, `Ctrl+K` = focus en input
- **Indicador de estado de conexión**: dot verde/rojo en el header (ping a `/health`)
- **Historial persistente**: `localStorage` guarda las últimas 20 conversaciones (no el audio, solo el texto)
- **Configuración inline**: panel ⚙ con selector de voz TTS (preview de cada voz), toggle auto-play, toggle markdown
- **Exportar conversación**: botón en header para descargar el historial como `.txt` o `.md`
- **Accesibilidad**: `aria-label` en todos los controles, soporte de screen reader, `prefers-reduced-motion`

---

## Archivos a crear / modificar

### Nuevos
```
app/api/routers/voice.py
app/api/schemas/voice.py
app/services/voice/__init__.py
app/services/voice/transcriber.py
app/services/voice/tts.py
static/voice/index.html
static/voice/app.js
static/voice/style.css
tests/unit/test_voice_transcriber.py
tests/unit/test_voice_tts.py
tests/integration/test_voice_endpoints.py
```

### Modificados
```
app/main.py                     # mount StaticFiles + include voice router + include agent stream
app/core/config.py              # 5 nuevos settings (stt_mode, whisper_model, tts_voice, tts_model, voice_max_audio_mb)
app/services/llm/claude_client.py  # stream_callback en generate_with_tools()
app/api/routers/agent.py        # agregar /agent/stream endpoint (o nuevo router)
requirements.txt                # openai-whisper, sse-starlette
Dockerfile                      # ffmpeg + libsndfile1 en runtime stage
```

---

## Tests

### Unit
- `test_voice_transcriber.py`
  - `test_local_mode_transcribes_audio`
  - `test_api_mode_calls_openai`
  - `test_large_file_raises_error`
  - `test_empty_audio_returns_empty_transcript`
- `test_voice_tts.py`
  - `test_synthesize_streams_bytes`
  - `test_invalid_voice_raises_error`

### Integration
- `test_voice_endpoints.py`
  - `test_transcribe_requires_auth` → 401
  - `test_transcribe_missing_file` → 422
  - `test_transcribe_oversized_file` → 413
  - `test_speak_requires_auth` → 401
  - `test_speak_empty_text` → 422
  - `test_speak_returns_audio_stream`
  - `test_agent_stream_sends_sse_events`
  - `test_agent_stream_requires_auth`

---

## Orden de implementación

```
1. git checkout -b feat/voice-interface
2. Fase 1A: config.py + schemas/voice.py + services/voice/
3. Fase 1B: routers/voice.py + tests + montar en main.py
4. Fase 1C: static/voice/ — estructura HTML + CSS (sin JS todavía)
5. Fase 2A: streaming en LLMClient (stream_callback)
6. Fase 2B: /agent/stream endpoint + sse-starlette
7. Fase 2C: JS del frontend — grabación + transcripción + query + TTS pipeline
8. Fase 3: Wake word en JS
9. Fase 4: Polish, keyboard shortcuts, historial localStorage
10. Code review + QA visual en browser
11. PR a main
```

---

## Fuera de alcance

- App móvil nativa (iOS/Android)
- Whisper large/medium en producción sin GPU (demasiado lento para respuesta en tiempo real)
- Múltiples voces simultáneas / transcripción de reuniones en tiempo real
- Video input
