/**
 * MAREA's water — a metaball WebGL fragment shader, ported from
 * design/design_handoff_marea/reference/IA Liquida - Propuestas.dc.html
 * (search `const fs =` there for the original inline copy). The GLSL and
 * the per-state parameter table are portable near-verbatim per the design
 * handoff's README; two things the prototype doesn't have, added here:
 *
 * - Resize handling: the prototype hardcodes a fixed 1280x800 canvas.
 *   This engine reads the canvas's actual CSS size every frame (a
 *   ResizeObserver in WaterCanvas.svelte keeps canvas.width/height in
 *   sync with it) and derives uRes/screen-space conversions from that.
 * - Real audio instead of a synthetic sine wave: the prototype's `audio`
 *   parameter is a fixed per-state weight that scales a sin(9t)/sin(13.7t)
 *   pulse to *simulate* speech. Here, `audio` in MAREA_TARGETS is instead
 *   a *gate* (0..1) — how much the state should let sound drive the
 *   visual at all — multiplied every frame by setLiveLevel()'s real
 *   value from the mic (listening) or TTS (responding). The gate itself
 *   still lerps smoothly on state change like every other parameter; the
 *   live level does not (it needs to track actual sound in real time).
 */

export type MareaVisualState = 'idle' | 'listen' | 'think' | 'respond' | 'panel';

interface WaterParams {
  split: number;
  noise: number;
  ripple: number;
  glow: number;
  scale: number;
  cx: number;
  cy: number;
  squash: number;
  audio: number; // gate, see module docstring
}

// See design/design_handoff_marea/README.md's "Motor del agua" table —
// values copied verbatim. "respond" has two sub-targets (a <0.6s burst,
// then a settled state) so the water visibly surges before easing into
// the modal's open posture.
const IDLE: WaterParams = { split: 0, noise: 0.45, ripple: 0, glow: 0.55, scale: 0.85, cx: 0, cy: 0.05, squash: 1, audio: 0 };
const LISTEN: WaterParams = { split: 0.05, noise: 1, ripple: 1, glow: 0.9, scale: 0.9, cx: 0, cy: 0.05, squash: 1, audio: 1 };
const THINK: WaterParams = { split: 1, noise: 0.5, ripple: 0, glow: 0.7, scale: 0.8, cx: 0.14, cy: 0.05, squash: 1, audio: 0 };
const RESPOND_BURST: WaterParams = { split: 0.3, noise: 1, ripple: 0, glow: 1.1, scale: 1.6, cx: 0, cy: -0.08, squash: 0.75, audio: 0 };
const RESPOND_SETTLED: WaterParams = { split: 0.1, noise: 0.8, ripple: 0, glow: 0.8, scale: 1.25, cx: 0, cy: -0.55, squash: 3.2, audio: 0.5 };
const PANEL: WaterParams = { split: 0, noise: 0.5, ripple: 0, glow: 0.95, scale: 0.32, cx: 0.56, cy: -0.42, squash: 1, audio: 0.2 };

function targetFor(state: MareaVisualState, dtSinceEntered: number): WaterParams {
  switch (state) {
    case 'listen':
      return LISTEN;
    case 'think':
      return THINK;
    case 'respond':
      return dtSinceEntered < 0.6 ? RESPOND_BURST : RESPOND_SETTLED;
    case 'panel':
      return PANEL;
    default:
      return IDLE;
  }
}

const VERTEX_SRC = 'attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}';

// Verbatim from the design handoff (see module docstring for the source
// location) — 27 lines of GLSL, WebGL1-safe, no textures/extensions.
const FRAGMENT_SRC = `precision highp float;
uniform vec2 uRes;uniform float uT;uniform vec3 uB[8];
uniform float uNoise,uRipple,uGlow,uScale,uSquash;uniform vec2 uC;
void main(){
 vec2 uv=(gl_FragCoord.xy-.5*uRes)/min(uRes.x,uRes.y);
 vec2 p=(uv-uC)/uScale; p.y*=uSquash;
 p+=uNoise*.05*vec2(sin(p.y*7.+uT*1.3)+.5*sin(p.y*17.-uT*2.1), cos(p.x*6.-uT*1.1)+.5*cos(p.x*15.+uT*1.7));
 float f=0.;
 for(int i=0;i<8;i++){vec2 d=p-uB[i].xy;f+=uB[i].z*uB[i].z/(dot(d,d)+1e-5);}
 float m=smoothstep(.92,1.08,f);
 float inner=clamp((f-1.)/4.,0.,1.);
 vec3 deep=vec3(.01,.14,.38),mid=vec3(.07,.48,.9),hi=vec3(.6,.96,1.);
 vec3 col=mix(mid,deep,inner);
 col+=hi*.18*smoothstep(-.2,.5,p.y);
 float rim=smoothstep(.92,1.04,f)*(1.-smoothstep(1.04,1.5,f));
 col+=hi*rim*(.55+.6*uGlow);
 vec2 sp=p-uB[0].xy-vec2(-.09,.11);
 col+=hi*exp(-dot(sp,sp)*90.)*.5*m;
 float halo=uGlow*.5*clamp(f*.55,0.,1.)*(1.-m);
 float dc=length(uv-uC);
 float rings=0.;
 for(int k=0;k<3;k++){float ph=fract(uT*.34+float(k)*.333);float rr=.1+ph*.5;
  rings+=(1.-smoothstep(0.,.012,abs(dc-rr)))*(1.-ph);}
 vec3 oc=col*m+hi*halo+hi*rings*uRipple*.8;
 float a=max(max(m,halo*.9),rings*uRipple*.55);
 gl_FragColor=vec4(oc,a);
}`;

interface Uniforms {
  uRes: WebGLUniformLocation | null;
  uT: WebGLUniformLocation | null;
  uNoise: WebGLUniformLocation | null;
  uRipple: WebGLUniformLocation | null;
  uGlow: WebGLUniformLocation | null;
  uScale: WebGLUniformLocation | null;
  uSquash: WebGLUniformLocation | null;
  uC: WebGLUniformLocation | null;
  uB: WebGLUniformLocation | null;
}

function compileShader(gl: WebGLRenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error('WaterEngine: gl.createShader failed');
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`WaterEngine: shader compile failed: ${log}`);
  }
  return shader;
}

/** One ball's position, for the caller to anchor orbiting labels/UI to. */
export interface BallScreenPosition {
  index: number;
  screenX: number;
  screenY: number;
}

const LERP_K = 0.055; // per design: always interpolate, never set params in seco.

// Attack/release envelope for the live audio level (see setLiveLevel).
// Real mic/TTS amplitude is far noisier frame-to-frame than the design
// prototype's synthetic sine wave — feeding it into the shader raw reads
// as a visible tremor. Standard audio-visualizer envelope: rise fast
// (attack) so the pulse still feels responsive to a new sound, fall
// slower (release) so it doesn't flicker back down between syllables.
const AUDIO_ATTACK_TAU = 0.05; // seconds
const AUDIO_RELEASE_TAU = 0.4; // seconds

export class WaterEngine {
  private gl: WebGLRenderingContext | null = null;
  private uniforms: Uniforms | null = null;
  private params: WaterParams = { ...IDLE };
  private state: MareaVisualState = 'idle';
  private enteredAt = performance.now();
  private liveLevel = 0;
  private smoothedLevel = 0;
  private lastDrawAt: number | null = null;
  private lastBalls: Float32Array = new Float32Array(24);
  private energy = 1;
  private disposed = false;

  constructor(private canvas: HTMLCanvasElement) {
    const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: false, antialias: true });
    if (!gl) {
      // No WebGL — the canvas stays blank; MAREA's chat still works fully
      // without the water visualization (e.g. very old browsers, or a
      // software-rendering-disabled headless environment).
      return;
    }
    this.gl = gl;

    const program = gl.createProgram();
    if (!program) throw new Error('WaterEngine: gl.createProgram failed');
    gl.attachShader(program, compileShader(gl, gl.VERTEX_SHADER, VERTEX_SRC));
    gl.attachShader(program, compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SRC));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(`WaterEngine: program link failed: ${gl.getProgramInfoLog(program)}`);
    }
    gl.useProgram(program);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const aLoc = gl.getAttribLocation(program, 'a');
    gl.enableVertexAttribArray(aLoc);
    gl.vertexAttribPointer(aLoc, 2, gl.FLOAT, false, 0, 0);

    this.uniforms = {
      uRes: gl.getUniformLocation(program, 'uRes'),
      uT: gl.getUniformLocation(program, 'uT'),
      uNoise: gl.getUniformLocation(program, 'uNoise'),
      uRipple: gl.getUniformLocation(program, 'uRipple'),
      uGlow: gl.getUniformLocation(program, 'uGlow'),
      uScale: gl.getUniformLocation(program, 'uScale'),
      uSquash: gl.getUniformLocation(program, 'uSquash'),
      uC: gl.getUniformLocation(program, 'uC'),
      uB: gl.getUniformLocation(program, 'uB[0]'),
    };
  }

  setState(state: MareaVisualState): void {
    if (this.state === state) return;
    this.state = state;
    this.enteredAt = performance.now();
  }

  /** Real-time amplitude (0..1) from the mic (listening) or TTS
   * (responding) — see module docstring for how this combines with the
   * per-state `audio` gate. Anything else (idle/think/panel) should pass 0. */
  setLiveLevel(level: number): void {
    this.liveLevel = Math.max(0, Math.min(1, level));
  }

  /** Overall glow multiplier — mirrors the prototype's `energia` tweak. */
  setEnergy(energy: number): void {
    this.energy = energy;
  }

  /** Sync the drawing buffer to the canvas's current CSS size. Call this
   * from a ResizeObserver — the prototype never needed to, since its
   * canvas was a fixed 1280x800. */
  resize(cssWidth: number, cssHeight: number): void {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(cssWidth * dpr));
    const height = Math.max(1, Math.round(cssHeight * dpr));
    if (this.canvas.width !== width) this.canvas.width = width;
    if (this.canvas.height !== height) this.canvas.height = height;
  }

  /** Advance and render one frame. `tSeconds` should be a monotonically
   * increasing clock (e.g. (performance.now() - t0) / 1000) — NOT a
   * per-frame delta, since the shader itself is time-driven (waves,
   * orbits), not frame-count-driven. */
  draw(tSeconds: number): void {
    const gl = this.gl;
    const U = this.uniforms;
    if (!gl || !U || this.disposed) return;

    const now = performance.now();
    const dtSinceEntered = (now - this.enteredAt) / 1000;
    const target = targetFor(this.state, dtSinceEntered);
    for (const key of Object.keys(target) as (keyof WaterParams)[]) {
      this.params[key] += (target[key] - this.params[key]) * LERP_K;
    }
    const P = this.params;

    // Attack/release envelope on the raw live level — see AUDIO_ATTACK_TAU.
    const frameDt = this.lastDrawAt === null ? 1 / 60 : Math.min(0.25, (now - this.lastDrawAt) / 1000);
    this.lastDrawAt = now;
    const tau = this.liveLevel > this.smoothedLevel ? AUDIO_ATTACK_TAU : AUDIO_RELEASE_TAU;
    const envelopeAlpha = 1 - Math.exp(-frameDt / tau);
    this.smoothedLevel += (this.liveLevel - this.smoothedLevel) * envelopeAlpha;

    const audio = P.audio * this.smoothedLevel;

    const b = new Float32Array(24);
    const pulse = 1 + audio * (0.07 * Math.sin(tSeconds * 9) + 0.05 * Math.sin(tSeconds * 13.7));
    b[0] = 0.03 * Math.sin(tSeconds * 0.7) * (1 - P.split);
    b[1] = 0.04 * Math.sin(tSeconds * 0.9 + 2) * (1 - P.split);
    b[2] = 0.3 * (1 - 0.62 * P.split) * pulse;
    for (let i = 1; i < 8; i++) {
      const ang = tSeconds * (0.6 + 1.9 * P.split) + (i * Math.PI * 2) / 7;
      const rad = (0.1 + 0.36 * P.split) * (0.8 + 0.3 * ((i * 0.37) % 1));
      b[i * 3] = Math.cos(ang) * rad;
      b[i * 3 + 1] = Math.sin(ang) * rad * 0.92;
      b[i * 3 + 2] = 0.085 + 0.02 * Math.sin(tSeconds * 2 + i);
    }
    this.lastBalls = b;

    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform2f(U.uRes, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.uniform1f(U.uT, tSeconds);
    gl.uniform3fv(U.uB, b);
    gl.uniform1f(U.uNoise, P.noise);
    gl.uniform1f(U.uRipple, P.ripple);
    gl.uniform1f(U.uGlow, P.glow * this.energy);
    gl.uniform1f(U.uScale, Math.max(P.scale, 0.05));
    gl.uniform1f(U.uSquash, P.squash);
    gl.uniform2f(U.uC, P.cx, P.cy);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  /** Screen-space (CSS px, canvas-relative) position of each satellite
   * ball from the last draw() call — for anchoring orbiting agent labels
   * (Fase 6). Ball 0 is the core; 1-7 are satellites. */
  getBallScreenPositions(cssWidth: number, cssHeight: number): BallScreenPosition[] {
    const P = this.params;
    const unit = Math.min(cssWidth, cssHeight);
    const positions: BallScreenPosition[] = [];
    for (let i = 0; i < 8; i++) {
      const bx = this.lastBalls[i * 3];
      const by = this.lastBalls[i * 3 + 1];
      const uvx = P.cx + bx * P.scale;
      const uvy = P.cy + (by / P.squash) * P.scale;
      positions.push({
        index: i,
        screenX: cssWidth / 2 + uvx * unit,
        screenY: cssHeight / 2 - uvy * unit,
      });
    }
    return positions;
  }

  /** Opacity for the orbiting agent-label overlay (Fase 6's design item
   * 7) — 0 outside "think", and inside it ramped in only once the split
   * has progressed enough that the satellites have visibly separated
   * from the core (mirrors the design prototype's own `showL` formula:
   * `Math.min(1, Math.max(0, (split-.35)*2))`), so labels don't appear
   * hovering over an still-mostly-merged sphere. */
  getLabelOpacity(): number {
    if (this.state !== 'think') return 0;
    return Math.min(1, Math.max(0, (this.params.split - 0.35) * 2));
  }

  dispose(): void {
    this.disposed = true;
  }
}
