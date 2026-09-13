# Handoff: MAREA — Interfaz conversacional de IA líquida (propuesta 1a)

## Overview
MAREA es una interfaz de conversación voz-primero con una IA representada como una esfera de agua (metaballs WebGL). La esfera transforma su forma según el estado de la conversación: reposo → escucha → pensamiento (se divide en gotas-agente que orbitan) → respuesta (se abre en ola y pide un dato al usuario) → panel (se repliega a la esquina y cede el centro a un dashboard multi-sistema). Incluye un panel de "proceso de pensamiento" que muestra en vivo qué agentes, herramientas y sistemas usa la IA.

## Sobre los archivos de diseño
Los archivos en `reference/` son **referencias de diseño creadas en HTML** — un prototipo que muestra el look y el comportamiento buscados, **no código de producción para copiar directo**. La tarea es **recrear este diseño en el entorno del codebase destino** (React, Vue, SwiftUI, nativo, etc.) usando sus patrones y librerías; si todavía no existe un entorno, elegir el framework más apropiado e implementarlo ahí. El shader GLSL y la lógica de parámetros del agua sí son portables casi tal cual a cualquier stack con WebGL/Metal/Skia.

Nota: el archivo de referencia contiene 3 propuestas; **este handoff cubre solo la tarjeta `1a MAREA`** (elemento `[data-screen-label="1a MAREA"]`). Ignorar 1b y 1c.

## Fidelidad
**Alta (hifi).** Colores, tipografía, espaciados, copys y animaciones son finales. Recrear pixel-perfect con las librerías existentes del codebase.

## Pantalla única: MAREA (lienzo 1280×800, escalable)
Contenedor: `overflow:hidden`, fondo `radial-gradient(1100px 760px at 50% 44%, #0B1C36 0%, #060D1C 55%, #030710 100%)`, borde `1px solid rgba(120,190,255,.14)`.

Capas (de atrás hacia adelante):
1. **Canvas WebGL** (toda la superficie): la esfera de agua. Ver "Motor del agua".
2. **Capa de clic** (toda la superficie, `cursor:pointer`): un tap sobre el agua avanza al siguiente estado.
3. **Header izquierdo** (top 28, left 32): wordmark `MAREA ·01` (Michroma 13px, letter-spacing .3em, #9FD8FF) + fila de estado: punto 7px #54E0FF con glow y pulso 2s + etiqueta de estado (11px, tracking .22em, rgba(210,240,255,.78)). Etiquetas por estado: EN REPOSO / ESCUCHANDO / PROCESANDO / RESPONDIENDO / SISTEMAS ACTIVOS.
4. **Header derecho** (top 28, right 32, alineado a la derecha): "NÚCLEO CONECTADO A" (10px, tracking .2em, rgba(160,210,255,.6)) + "Gmail · Slack · Calendar · Asana" (12px, rgba(224,245,255,.85)).
5. **Barras de voz** (solo en escucha; centro, bottom 120): 5 barras 4px de ancho, alto 34px, gradiente vertical #54E0FF→#1A6FD4, radio 2px, `transform-origin:bottom`, animación `scaleY(.22→1)` con duraciones .58–.92s desfasadas. Fade in/out con `opacity` + transición .5s.
6. **Panel "Proceso de pensamiento"** (estados pensando y respuesta; left 32, top 118, ancho 300): vidrio `rgba(9,26,50,.58)` + `backdrop-filter:blur(14px)`, borde `rgba(120,200,255,.2)`, radio 16, padding 18/20. Título "PROCESO DE PENSAMIENTO" (10px, tracking .25em, #6FC9FF) + subtítulo "agentes · herramientas · sistemas". Filas que aparecen secuencialmente (una cada ~500 ms) con fadeUp .4s; separador `rgba(120,200,255,.08)`. Cada fila: badge + texto (11.5px #DCEEFF) + estado (● pulsante #54E0FF si activa, ✓ #6EF2C5 si completa). Badges (8.5px, tracking .12em, padding 3/6, radio 5):
   - AGENTE — fondo rgba(84,224,255,.16), texto #54E0FF
   - HERRAMIENTA — rgba(140,160,255,.16), #9FB0FF
   - SISTEMA — rgba(110,242,197,.14), #6EF2C5
   - RAZONAMIENTO — rgba(255,255,255,.09), rgba(220,240,255,.8)
   Pasos (en orden): Intención detectada: «resumen del día» (RAZONAMIENTO) · Correo → leyendo Gmail (3 hilos nuevos) (AGENTE) · Mensajería → Slack: 2 canales sin leer (AGENTE) · calendar.buscar_eventos(hoy) (HERRAMIENTA) · Asana: 4 tareas abiertas (SISTEMA) · Priorizando 12 ítems → síntesis (RAZONAMIENTO). En "respuesta" el panel queda como checklist completo.
7. **Etiquetas orbitales de agentes** (solo pensando): 5 etiquetas flotantes (10px, tracking .16em, #BFE9FF, punto de color por tipo) ancladas a las gotas que orbitan: `● AG · CORREO`, `● AG · SLACK`, `● AG · CALENDAR`, `● HERR · RANKING` (punto #9FB0FF), `● SYS · ASANA` (punto #6EF2C5). Posición actualizada por frame desde la simulación (offset +16px x, −7px y del centro de cada gota); opacidad ligada al progreso de la división de la esfera.
8. **Modal de respuesta** (estado respuesta; centrado en left 56%, top 118, ancho 600): vidrio `rgba(9,26,50,.6)` blur 16, borde `rgba(120,200,255,.22)`, radio 18, padding 26/32. Dos fases:
   - **Fase "dato"**: kicker "LA IA NECESITA UN DATO TUYO" (10px #6FC9FF) · pregunta 19px/1.5 #EAF6FF con resaltes #7FE3FF ("**Valentina** espera tu respuesta sobre el **presupuesto Q4**. ¿Qué decidís?") · chips de decisión Aprobar / Con cambios / Rechazar (mismo estilo que chips de estado; activo relleno #54E0FF texto #052540) · input de comentario opcional (fondo rgba(4,16,34,.6), borde rgba(120,200,255,.3), radio 10, 14px #EAF6FF; placeholder «Agregá un comentario, ej: "ajustar la partida de viajes"») · nota "La demo se pausa mientras escribís" (10.5px) · botón primario "GENERAR RESPUESTA →" (relleno #54E0FF, texto #052540, 600, radio 10, glow `0 0 18px rgba(84,224,255,.4)`).
   - **Fase "borrador"**: kicker "RESPUESTA GENERADA · LISTA PARA ENVIAR" (#6EF2C5) · tarjeta de correo (fondo rgba(4,16,34,.55)): cabecera "Para: Valentina Ruiz · Asunto: Re: Presupuesto Q4" (11px) + cuerpo 14.5px/1.6 generado con plantilla según decisión + comentario (ver Estado) + pie "Redactado por MAREA con tu decisión — editable antes de enviar." · botones "← Editar dato" (ghost) y "ENVIAR ✓" (relleno #6EF2C5, texto #04301F, glow verde). Enviar transiciona al estado panel.
9. **Dashboard multi-sistema** (estado panel; padding 98/44 arriba): grilla 3 columnas, gap 20, tarjetas de vidrio (rgba(9,26,50,.52), blur 14, borde rgba(120,200,255,.18), radio 16, padding 20/22) que entran con `condense` escalonado (.05/.2/.35s):
   - CORREO · 3 importantes: Valentina Ruiz — Presupuesto Q4 · 09:12 / Martín Oliva — Contrato v3 · 08:47 / RRHH — Firma pendiente · ayer
   - SLACK · 5 pendientes: #producto (2) Review del sprint / @sofi (1) «¿Viste el deck?» / #incidentes (2) Confirmar cierre
   - TAREAS · 4 hoy: Enviar presupuesto Q4 / Demo cliente · 15:00 / Revisar PR #482 / Llamar al contador
   Filas: título 13px 500 #EAF6FF, secundario 12px rgba(190,225,255,.8), separadores rgba(120,200,255,.1). Hint bottom-right sobre la esfera replegada: "LA ESFERA CEDIÓ EL CENTRO — DECÍ «VOLVÉ» PARA RETOMAR" (11px, tracking .14em).
10. **Chips de estado** (centro, bottom 28): Reposo · Escucha · Pensando · Respuesta · Panel + toggle ▶ AUTO. Base: padding 7/14, radio 999, 11px 500, borde rgba(120,200,255,.28), fondo rgba(8,28,56,.5), texto rgba(205,238,255,.85). Activo: fondo #54E0FF, texto #052540, glow `0 0 18px rgba(84,224,255,.45)`. Hover: `translateY(-1px)`.

## Motor del agua (WebGL, fragment shader de metaballs)
Quad fullscreen; 8 bolas `vec3(x, y, radio)` en espacio normalizado (centro 0,0; unidad = min(ancho,alto)). Campo `f = Σ r²/d²`, superficie en `smoothstep(.92, 1.08, f)`.

- **Composición**: 1 núcleo (radio `0.30·(1−0.62·split)·pulso`) + 7 satélites en órbita (`ang = t·(0.6+1.9·split) + i·2π/7`, radio orbital `(0.10+0.36·split)` con variación por índice, radio de gota `0.085 + 0.02·sin`).
- **Borde orgánico**: domain-warp `p += noise·0.05·(sin/cos multiescala en t)`.
- **Color**: profundo `rgb(.01,.14,.38)` → medio `rgb(.07,.48,.9)` según densidad; luz vertical y highlight especular; **rim** (banda en el umbral) en `rgb(.6,.96,1)` ≈ #99F5FF con intensidad ligada a `glow`; halo exterior suave.
- **Ondas de escucha**: 3 anillos concéntricos expandiéndose desde el centro (`fract(t·.34 + k/3)`), alpha decreciente, mezclados con `ripple`.
- **Parámetros continuos** (interpolar SIEMPRE hacia el target con lerp k≈0.055 por frame — así cualquier cambio de estado se ve como morfosis, nunca como corte):

| Estado | split | noise | ripple | glow | scale | cx | cy | squash | audio |
|---|---|---|---|---|---|---|---|---|---|
| Reposo | 0 | .45 | 0 | .55 | .85 | 0 | .05 | 1 | 0 |
| Escucha | .05 | 1 | 1 | .9 | .9 | 0 | .05 | 1 | 1 |
| Pensando | 1 | .5 | 0 | .7 | .8 | .14 | .05 | 1 | 0 |
| Respuesta (burst <0.6s) | .3 | 1 | 0 | 1.1 | 1.6 | 0 | −.08 | .75 | 0 |
| Respuesta (asentada) | .1 | .8 | 0 | .8 | 1.25 | 0 | −.55 | 3.2 | .5 |
| Panel | 0 | .5 | 0 | .95 | .32 | .56 | −.42 | 1 | .2 |

`squash` multiplica p.y (aplasta la masa en una marea horizontal al responder); `audio` modula el pulso del radio del núcleo (`1 + audio·(.07·sin 9t + .05·sin 13.7t)`) simulando la voz. Coordenada y positiva hacia arriba. Conversión a píxeles de pantalla (para anclar las etiquetas de agentes): `pxX = 640 + (cx + bx·scale)·800`, `pxY = 400 − (cy + by/squash·scale)·800`.

El shader GLSL completo está en `reference/IA Liquida - Propuestas.dc.html` (buscar `const fs =`).

## Interacciones y comportamiento
- **Ciclo demo automático** (activable): reposo 3000 ms → escucha 3400 → pensando 3400 → respuesta 5800 → panel 8000 → reposo. Duraciones divididas por el tweak de velocidad.
- **Tap sobre el agua**: avanza al siguiente estado y desactiva el auto.
- **Chips**: saltan a un estado directo y desactivan el auto. Toggle ▶ AUTO lo reactiva.
- **Cualquier interacción con el modal de respuesta** (foco en input, chips de decisión, escribir) pausa el auto.
- **Pasos del pensamiento**: se revelan 1 cada ~500 ms durante "pensando"; en "respuesta" quedan todos en ✓.
- **Transiciones DOM**: paneles entran con `condense` (opacity 0 + blur 14px → nítido, .6–.9s, `both`). ⚠️ El keyframe NO debe tocar `transform` (los paneles se centran con translate; un `transform:none` final los desplaza). Filas con `fadeUp` (opacity + translateY 14→0, .4s).
- **Envío del borrador**: transiciona a "panel" (el agua se repliega a la esquina inferior derecha mientras entra el dashboard).

## Gestión de estado
- `estado: 'idle'|'listen'|'think'|'respond'|'panel'` + timestamp de entrada al estado.
- `auto: boolean` (demo), `pasoPensamiento: 0–6`.
- Fase del modal: `'ask'|'draft'`; `decision: 'Aprobar'|'Con cambios'|'Rechazar'` (default Aprobar); `comentario: string`.
- Borrador generado (plantilla): cuerpo según decisión — Aprobar: "Hola Valentina: revisé el presupuesto Q4 y queda aprobado." / Con cambios: "…va bien, pero antes de aprobarlo necesito un ajuste." / Rechazar: "…por ahora no puedo aprobar el presupuesto Q4 tal como está." + si hay comentario: " Un detalle: {comentario}." + " ¿Lo repasamos cinco minutos antes de la demo de las 15:00?". En producción, reemplazar la plantilla por la generación real del modelo.
- Parámetros del agua: objeto continuo interpolado por frame (nunca setear en seco).
- Tweaks expuestos en el prototipo: `velocidad` (0.3–2), `energia` (0.4–1.8, escala glow), `autoDemo` (bool).

## Design tokens
- **Fondos**: base #030710 / #060D1C / #0B1C36 (radial). Vidrio: rgba(9,26,50,.52–.6) + blur 14–16px, borde rgba(120,200,255,.18–.22).
- **Acentos**: cian primario #54E0FF · cian claro #7FE3FF · rim #99F5FF · azul profundo #1A6FD4 · verde éxito #6EF2C5 · lavanda herramienta #9FB0FF.
- **Texto**: principal #EAF6FF · secundario rgba(190,225,255,.8) · terciario rgba(160,210,255,.6) · sobre acento #052540 / #04301F.
- **Tipografía**: Space Grotesk (400/500/600/700) para todo el cuerpo y UI; Michroma solo para el wordmark. Kickers 10px tracking .2–.25em; cuerpo modal 19–21px/1.5; listas 12–13px.
- **Radios**: chips 999 · inputs/botones 10 · tarjetas internas 12 · paneles 16–18.
- **Glow**: `0 0 18px` del color del acento al 35–45%.
- **Escala de tiempos**: micro .3–.5s · paneles .6–.9s · morfosis del agua ≈1–1.5s (resultado del lerp).

## Assets
- Google Fonts: [Space Grotesk](https://fonts.google.com/specimen/Space+Grotesk) y [Michroma](https://fonts.google.com/specimen/Michroma). Sin imágenes ni íconos externos: todo el visual del agua es generado por shader.

## Files
- `reference/IA Liquida - Propuestas.dc.html` — prototipo completo (abrir en navegador junto a `support.js`). La propuesta entregada es la tarjeta `1a MAREA`; el shader, la lógica de estados y los estilos están inline. Las tarjetas 1b/1c son exploraciones descartadas.
- `reference/support.js` — runtime del prototipo (requerido solo para abrir la referencia, no para la implementación).
