import React, { useEffect, useRef, useState } from 'react';
import clsx from 'clsx';
import { onThemeChange, themeChannels } from '@site/src/lib/brand';
import styles from './styles.module.css';

/**
 * The home page hero: the Open Agent Kernel mark as a field of fine dots, drawn on the GPU.
 *
 * - On load the mark comes into focus over two seconds: the dots start as a loose haze close
 *   to their places, then fade in and tighten. Nothing flies across the hero.
 * - At rest the surface breathes: a slow wave lifts rows of dots, and the mark turns a little.
 * - Under the pointer, rings travel out across the surface, the dots swirl, and the mark
 *   leans towards the pointer. The ripple trails the cursor by a moment and lingers after it.
 * - As the page scrolls, the dots let go and drift up and out. Scrolling back gathers them.
 *
 * Every dot is moved in the vertex shader from a handful of numbers, so the page thread only
 * updates a few uniforms per frame. The canvas fills the hero; the `anchor` box, sized in the
 * stylesheet, says where the mark sits. Without WebGL, or with reduced motion, the plain mark
 * is shown instead.
 */

// The two halves of the mark (branding/logo-mark, viewBox 0 0 86.86 86.85).
const MARK_LEFT =
  'M19.74,39.48v15.79l12.48,5.06c4.39,1.76,7.26,6.01,7.26,10.73v15.79l-27.78-11.11c-7.07-2.83-11.7-9.67-11.7-17.27V0l27.79,11.11c7.06,2.83,11.69,9.67,11.69,17.27v19.07L19.74,39.48Z';
const MARK_RIGHT =
  'M86.86,0v58.47c0,7.6-4.64,14.44-11.7,17.27l-27.78,11.11v-23.69c0-4.72,2.87-8.97,7.26-10.73l12.48-5.06v-15.79l-19.74,7.97v-11.17c0-7.6,4.63-14.44,11.69-17.27L86.86,0Z';
const UNITS = 86.86;

const BUILD_SECONDS = 2;

/* ---- The dots ------------------------------------------------------------- */

/** A small seeded generator, so the field is the same on every visit. */
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type Field = { count: number; target: Float32Array; seed: Float32Array; kind: Float32Array };

/**
 * Places the dots: a hexagonal lattice inside the mark (so the wave reads as woven rows) with
 * a sparser layer behind it, a denser line along its outline, and a little dust around it.
 * The kinds are 0 body, 1 outline, 2 dust, 3 back layer. Positions are in mark space,
 * with the mark spanning -0.5 to 0.5 and y pointing down.
 */
function buildField(): Field | null {
  const context = document.createElement('canvas').getContext('2d');
  if (!context || typeof Path2D === 'undefined') return null;
  const halves = [new Path2D(MARK_LEFT), new Path2D(MARK_RIGHT)];
  const inside = (x: number, y: number) => halves.some((half) => context.isPointInPath(half, x, y));
  const random = seeded(20261119);
  const target: number[] = [];
  const kind: number[] = [];
  const place = (x: number, y: number, z: number, as: number) => {
    target.push(x / UNITS - 0.5, y / UNITS - 0.5, z);
    kind.push(as);
  };

  // Body: a lattice, lightly jittered so it does not moire against the screen.
  const step = UNITS / 64;
  // Every third dot is repeated on a layer behind, which gives the mark thickness as it turns.
  for (let row = 0, y = 0; y <= UNITS; y += step * 0.866, row++) {
    for (let column = 0, x = (row % 2) * step * 0.5; x <= UNITS; x += step, column++) {
      const jx = x + (random() - 0.5) * step * 0.3;
      const jy = y + (random() - 0.5) * step * 0.3;
      if (!inside(jx, jy)) continue;
      place(jx, jy, 0, 0);
      if ((column + row) % 3 === 0) place(jx, jy, -0.1, 3);
    }
  }

  // Outline: dots along each half's edge, so the shape stays crisp while the body moves.
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '0');
  svg.setAttribute('height', '0');
  svg.style.position = 'absolute';
  document.body.appendChild(svg);
  for (const d of [MARK_LEFT, MARK_RIGHT]) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    svg.appendChild(path);
    const length = path.getTotalLength();
    for (let at = 0; at < length; at += 0.55) {
      const point = path.getPointAtLength(at);
      place(point.x + (random() - 0.5) * 0.25, point.y + (random() - 0.5) * 0.25, 0, 1);
    }
  }
  svg.remove();

  // Dust: a sparse cloud around the mark, for depth.
  for (let i = 0; i < 300; i++) {
    const angle = random() * Math.PI * 2;
    const radius = 0.35 + random() * 1.1;
    target.push(Math.cos(angle) * radius, Math.sin(angle) * radius * 0.8, (random() - 0.5) * 0.9);
    kind.push(2);
  }

  const count = kind.length;
  const seed = new Float32Array(count * 4);
  for (let i = 0; i < seed.length; i++) seed[i] = random();
  return { count, target: new Float32Array(target), seed, kind: new Float32Array(kind) };
}

/* ---- The shaders ------------------------------------------------------------ */

const VERTEX = `
precision highp float;
attribute vec3 aTarget;
attribute vec4 aSeed;
attribute float aKind;
uniform float uTime;
uniform float uBuild;
uniform float uScatter;
uniform float uHover;
uniform float uDpr;
uniform float uSize;
uniform float uInk;
uniform vec2 uCentre;
uniform vec2 uView;
uniform vec2 uPointer;
uniform vec2 uTilt;
varying float vAlpha;
varying float vTone;
varying float vSpeck;

void main() {
  vec3 p = aTarget;
  float t = uTime;
  float back = step(2.5, aKind);
  float dust = step(1.5, aKind) * (1.0 - back);

  // At rest the surface breathes: a slow travelling wave lifts rows of dots.
  float wave = sin(p.x * 9.0 + p.y * 3.0 + t * 0.9 + back * 1.9) * cos(p.y * 7.0 - t * 0.7);
  p.z += wave * (0.02 + 0.035 * uHover) * (1.0 - dust);
  p.xy += dust * vec2(sin(t * 0.21 + aSeed.x * 6.283), cos(t * 0.17 + aSeed.y * 6.283)) * 0.06;

  // Under the pointer: rings travel outwards, and the dots swirl around it.
  vec2 away = p.xy - uPointer;
  float reach = length(away);
  vec2 outward = away / max(reach, 0.0001);
  float ring = sin(reach * 30.0 - t * 7.0) * exp(-reach * 3.6) * uHover;
  float near = exp(-reach * 5.0) * uHover;
  p.xy += outward * ring * 0.016 + vec2(-outward.y, outward.x) * near * 0.04 * sin(t * 2.2 + aSeed.x * 6.283);
  p.z += ring * 0.07 + near * 0.05;

  // Build: the mark comes into focus. Each dot starts as part of a loose haze close to its
  // place, then fades in and tightens, at its own moment. Nothing travels across the hero.
  float delay = aSeed.x * 0.35;
  float built = clamp(uBuild * 1.35 - delay, 0.0, 1.0);
  float settle = 1.0 - pow(1.0 - built, 3.0);
  p += vec3(aSeed.yz - 0.5, aSeed.w - 0.5) * vec3(0.22, 0.22, 0.5) * (1.0 - settle);

  // Scroll: the dots let go, and drift up and out.
  float gone = smoothstep(aSeed.z * 0.55, 1.0, uScatter);
  vec2 drift = normalize(aTarget.xy + (aSeed.xy - 0.5) * 0.7 + 0.0001) * (0.45 + aSeed.w * 1.3);
  p.xy += (drift + vec2(0.0, -0.7 * aSeed.x)) * gone;
  p.xy += vec2(sin(t * 1.3 + aSeed.x * 20.0), cos(t * 1.1 + aSeed.y * 20.0)) * 0.04 * gone;
  p.z += (aSeed.y - 0.5) * 1.3 * gone;

  // The mark turns a little, and leans towards the pointer.
  float cy = cos(uTilt.x);
  float sy = sin(uTilt.x);
  p.xz = vec2(p.x * cy + p.z * sy, p.z * cy - p.x * sy);
  float cx = cos(uTilt.y);
  float sx = sin(uTilt.y);
  p.yz = vec2(p.y * cx - p.z * sx, p.y * sx + p.z * cx);

  float depth = 1.0 / (1.0 - p.z * 0.55);
  vec2 pixel = uCentre + p.xy * depth * uSize;
  vec2 clip = pixel / uView * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);

  // A band of light crosses the mark every few seconds.
  float band = abs(fract((aTarget.x + aTarget.y) * 0.5 - t * 0.11) - 0.5);
  float sweep = smoothstep(0.07, 0.0, band) * (1.0 - dust);

  float edge = step(0.5, aKind) * (1.0 - step(1.5, aKind));
  float size = mix(mix(2.8, 3.2, edge), mix(2.4, 1.7, dust), max(dust, back));
  size *= (0.8 + aSeed.w * 0.5) * depth * (1.0 + max(ring, 0.0) * 1.4 + max(wave, 0.0) * 0.3 + sweep * 0.5);
  gl_PointSize = max(size * uInk * uDpr * clamp(uSize / 440.0, 0.65, 1.25), 1.0);

  float alpha = mix(mix(0.95, 1.0, edge), mix(0.5, 0.42, dust), max(dust, back));
  vAlpha = alpha * smoothstep(0.0, 0.6, built) * (1.0 - gone * 0.9);
  vTone = clamp(max(wave, 0.0) * 0.55 + max(ring, 0.0) * 1.6 + sweep * 0.8 + near * 0.5, 0.0, 1.0);
  vSpeck = max(dust, step(0.96, aSeed.y) * (1.0 - edge) * (1.0 - back));
}
`;

const FRAGMENT = `
precision mediump float;
uniform vec3 uColor;
uniform vec3 uHot;
uniform vec3 uSpeck;
varying float vAlpha;
varying float vTone;
varying float vSpeck;

void main() {
  float radius = length(gl_PointCoord - 0.5);
  float alpha = smoothstep(0.5, 0.3, radius) * vAlpha;
  vec3 colour = mix(mix(uColor, uHot, vTone), uSpeck, vSpeck);
  gl_FragColor = vec4(colour * alpha, alpha);
}
`;

function compile(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  return gl.getShaderParameter(shader, gl.COMPILE_STATUS) ? shader : null;
}

/* ---- The scene ---------------------------------------------------------------- */

const unit = (token: Parameters<typeof themeChannels>[0]): [number, number, number] => {
  const [r, g, b] = themeChannels(token).split(',').map((part) => parseInt(part, 10) / 255);
  return [r, g, b];
};

/** Starts the drawing. Returns a function that stops it, or null where WebGL is not available. */
function start(stage: HTMLElement, canvas: HTMLCanvasElement, anchor: HTMLElement): (() => void) | null {
  const gl = canvas.getContext('webgl', { alpha: true, antialias: false, premultipliedAlpha: true });
  const field = gl && buildField();
  if (!gl || !field) return null;
  const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX);
  const fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT);
  const program = gl.createProgram();
  if (!vertex || !fragment || !program) return null;
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  gl.useProgram(program);

  const attribute = (name: string, data: Float32Array, size: number) => {
    const at = gl.getAttribLocation(program, name);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(at);
    gl.vertexAttribPointer(at, size, gl.FLOAT, false, 0, 0);
  };
  attribute('aTarget', field.target, 3);
  attribute('aSeed', field.seed, 4);
  attribute('aKind', field.kind, 1);
  const uniform = (name: string) => gl.getUniformLocation(program, name);
  const at = {
    time: uniform('uTime'),
    build: uniform('uBuild'),
    scatter: uniform('uScatter'),
    hover: uniform('uHover'),
    dpr: uniform('uDpr'),
    size: uniform('uSize'),
    ink: uniform('uInk'),
    centre: uniform('uCentre'),
    view: uniform('uView'),
    pointer: uniform('uPointer'),
    tilt: uniform('uTilt'),
    color: uniform('uColor'),
    hot: uniform('uHot'),
    speck: uniform('uSpeck'),
  };
  gl.enable(gl.BLEND);
  gl.disable(gl.DEPTH_TEST);
  gl.clearColor(0, 0, 0, 0);

  // Colours follow the colour mode. On the dark page the dots add up like light; on the
  // light page they sit like ink.
  const paint = () => {
    const light = document.documentElement.getAttribute('data-theme') === 'light';
    gl.uniform3fv(at.color, unit('primary'));
    gl.uniform3fv(at.hot, light ? [0.76, 0.2, 0.05] : [1.0, 0.8, 0.62]);
    gl.uniform3fv(at.speck, unit(light ? 'dusk' : 'blue'));
    // Ink on a light page needs a slightly larger dot than light on a dark one.
    gl.uniform1f(at.ink, light ? 1.25 : 1.1);
    gl.blendFunc(gl.ONE, light ? gl.ONE_MINUS_SRC_ALPHA : gl.ONE);
  };
  paint();
  const unwatch = onThemeChange(paint);

  // Where the mark sits, in canvas pixels. The anchor box is laid out by the stylesheet.
  let dpr = 1;
  let centreX = 0;
  let centreY = 0;
  let size = 1;
  const measure = () => {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const bounds = stage.getBoundingClientRect();
    const box = anchor.getBoundingClientRect();
    canvas.width = Math.max(1, Math.round(bounds.width * dpr));
    canvas.height = Math.max(1, Math.round(bounds.height * dpr));
    centreX = box.left - bounds.left + box.width / 2;
    centreY = box.top - bounds.top + box.height / 2;
    size = Math.min(box.width, box.height);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(at.view, bounds.width, bounds.height);
    gl.uniform2f(at.centre, centreX, centreY);
    gl.uniform1f(at.size, size);
    gl.uniform1f(at.dpr, dpr);
  };
  measure();
  const resized = new ResizeObserver(measure);
  resized.observe(stage);

  // The pointer, in mark space. It only counts while it is over the mark.
  const pointer = { x: 0, y: 0, over: false, tiltX: 0, tiltY: 0 };
  const onMove = (event: PointerEvent) => {
    const bounds = stage.getBoundingClientRect();
    pointer.x = (event.clientX - bounds.left - centreX) / size;
    pointer.y = (event.clientY - bounds.top - centreY) / size;
    pointer.over = Math.hypot(pointer.x, pointer.y) < 0.66;
    pointer.tiltX = Math.max(-1, Math.min(1, pointer.x));
    pointer.tiltY = Math.max(-1, Math.min(1, pointer.y));
  };
  const onLeave = () => {
    pointer.over = false;
  };
  window.addEventListener('pointermove', onMove, { passive: true });
  document.documentElement.addEventListener('pointerleave', onLeave);

  let clock = 0;
  let last: number | null = null;
  let frame = 0;
  let running = false;
  let onScreen = true;
  let hover = 0;
  let tiltX = 0;
  let tiltY = 0;
  let scatter = 0;
  // Where the ripple is. It trails the pointer, so the rings arrive a moment after the cursor.
  let rippleX = 0;
  let rippleY = 0;

  const draw = (now: number) => {
    const step = last === null ? 0 : Math.min((now - last) / 1000, 0.05);
    last = now;
    clock += step;
    // Everything eases towards its goal, so nothing snaps.
    const ease = 1 - Math.exp(-step * 6);
    // A ripple that has died away starts again under the cursor, and does not glide in from afar.
    if (pointer.over && hover < 0.02) {
      rippleX = pointer.x;
      rippleY = pointer.y;
    }
    // The ripple comes up quickly and fades slowly, so it lingers after the pointer has left.
    hover += ((pointer.over ? 1 : 0) - hover) * (pointer.over ? ease : 1 - Math.exp(-step * 2.2));
    // It follows only while the pointer is over the mark: once the pointer leaves, the ripple
    // stays where it was and fades there.
    if (pointer.over) {
      const follow = 1 - Math.exp(-step * 3.2);
      rippleX += (pointer.x - rippleX) * follow;
      rippleY += (pointer.y - rippleY) * follow;
    }
    tiltX += ((pointer.over ? pointer.tiltX * 0.5 : 0) - tiltX) * ease * 0.6;
    tiltY += ((pointer.over ? pointer.tiltY * 0.4 : 0) - tiltY) * ease * 0.6;
    const bounds = stage.getBoundingClientRect();
    const scrolled = Math.max(0, Math.min(-bounds.top / (bounds.height * 0.6), 1));
    scatter += (scrolled - scatter) * (1 - Math.exp(-step * 9));

    gl.uniform1f(at.time, clock);
    gl.uniform1f(at.build, Math.min(clock / BUILD_SECONDS, 1));
    gl.uniform1f(at.scatter, scatter);
    gl.uniform1f(at.hover, hover);
    gl.uniform2f(at.pointer, rippleX, rippleY);
    gl.uniform2f(at.tilt, Math.sin(clock * 0.35) * 0.16 + tiltX, Math.cos(clock * 0.27) * 0.07 - tiltY);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.POINTS, 0, field.count);
    frame = requestAnimationFrame(draw);
  };

  const sync = () => {
    const should = onScreen && !document.hidden;
    if (should === running) return;
    running = should;
    if (running) {
      last = null;
      frame = requestAnimationFrame(draw);
    } else {
      cancelAnimationFrame(frame);
    }
  };
  const seen = new IntersectionObserver(([entry]) => {
    onScreen = entry.isIntersecting;
    sync();
  });
  seen.observe(stage);
  document.addEventListener('visibilitychange', sync);
  sync();

  return () => {
    cancelAnimationFrame(frame);
    seen.disconnect();
    resized.disconnect();
    unwatch();
    window.removeEventListener('pointermove', onMove);
    document.documentElement.removeEventListener('pointerleave', onLeave);
    document.removeEventListener('visibilitychange', sync);
    // The context is left to the browser to collect: losing it here would leave the canvas dead
    // if this effect runs again on the same element, as it does on a hot reload.
  };
}

/* ---- The component -------------------------------------------------------------- */

function PlainMark(): JSX.Element {
  return (
    <svg className={styles.plain} viewBox={`0 0 ${UNITS} ${UNITS}`} aria-hidden="true" focusable="false">
      <path d={MARK_LEFT} />
      <path d={MARK_RIGHT} />
    </svg>
  );
}

export default function ParticleLogo({ className }: { className?: string }): JSX.Element {
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const anchor = useRef<HTMLDivElement>(null);
  // True where the dots cannot run: no WebGL, or the visitor asked for reduced motion.
  const [plain, setPlain] = useState(false);

  useEffect(() => {
    if (!stage.current || !canvas.current || !anchor.current) return undefined;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setPlain(true);
      return undefined;
    }
    const stop = start(stage.current, canvas.current, anchor.current);
    if (!stop) setPlain(true);
    return stop ?? undefined;
  }, []);

  return (
    <div ref={stage} className={clsx(styles.stage, className)} aria-hidden="true">
      <canvas ref={canvas} className={styles.canvas} />
      <div ref={anchor} className={styles.anchor}>
        {plain && <PlainMark />}
        <noscript>
          <PlainMark />
        </noscript>
      </div>
    </div>
  );
}
