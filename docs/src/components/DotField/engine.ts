/**
 * A small WebGL runner for fields of dots. A scene supplies its vertex shader, its
 * attributes and a function that sets its uniforms each frame; the runner does the rest:
 * it starts only when the canvas first comes on screen, sizes the canvas to its box,
 * stops drawing while the canvas is off screen or the tab is hidden, and cleans up.
 *
 * Every scene shares one fragment shader: a round dot whose colour and opacity come from
 * the vertex shader in `vColor` and `vAlpha`. The runner sets `uView` (the box in CSS
 * pixels), `uDpr` and `uTime` for every scene.
 */

export type Uniforms = (name: string) => WebGLUniformLocation | null;

export type DotScene = {
  vertex: string;
  attributes: Record<string, { data: Float32Array; size: number }>;
  count: number;
  /** Sets the scene's own uniforms before a frame. `step` is the seconds since the last one. */
  frame: (gl: WebGLRenderingContext, uniform: Uniforms, time: number, step: number) => void;
};

const FRAGMENT = `
precision mediump float;
varying vec3 vColor;
varying float vAlpha;

void main() {
  float radius = length(gl_PointCoord - 0.5);
  float alpha = smoothstep(0.5, 0.3, radius) * vAlpha;
  gl_FragColor = vec4(vColor * alpha, alpha);
}
`;

function compile(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  return gl.getShaderParameter(shader, gl.COMPILE_STATUS) ? shader : null;
}

/** Reads a theme token such as `--ak-blue-rgb` ("177, 205, 255") as three numbers from 0 to 1. */
export function tokenColour(element: Element, token: string): [number, number, number] {
  const parts = getComputedStyle(element).getPropertyValue(token).split(',').map((part) => parseFloat(part) / 255);
  return parts.length === 3 && parts.every((part) => Number.isFinite(part)) ? (parts as [number, number, number]) : [0.7, 0.8, 1];
}

/**
 * Runs a scene on a canvas. With `still`, one frame is drawn and nothing moves (for visitors
 * who asked for reduced motion). Returns a function that stops the scene.
 */
export function runDots(canvas: HTMLCanvasElement, scene: DotScene, still = false): () => void {
  let stop: (() => void) | null = null;

  const begin = (): (() => void) | null => {
    const gl = canvas.getContext('webgl', { alpha: true, antialias: false, premultipliedAlpha: true });
    if (!gl) return null;
    const vertex = compile(gl, gl.VERTEX_SHADER, scene.vertex);
    const fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT);
    const program = gl.createProgram();
    if (!vertex || !fragment || !program) return null;
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
    gl.useProgram(program);

    for (const [name, { data, size }] of Object.entries(scene.attributes)) {
      const at = gl.getAttribLocation(program, name);
      if (at < 0) continue;
      gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(at);
      gl.vertexAttribPointer(at, size, gl.FLOAT, false, 0, 0);
    }
    const found = new Map<string, WebGLUniformLocation | null>();
    const uniform: Uniforms = (name) => {
      if (!found.has(name)) found.set(name, gl.getUniformLocation(program, name));
      return found.get(name) ?? null;
    };
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.disable(gl.DEPTH_TEST);
    gl.clearColor(0, 0, 0, 0);

    const measure = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const bounds = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(bounds.width * dpr));
      canvas.height = Math.max(1, Math.round(bounds.height * dpr));
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(uniform('uView'), bounds.width, bounds.height);
      gl.uniform1f(uniform('uDpr'), dpr);
    };
    measure();

    let clock = 0;
    let last: number | null = null;
    let frame = 0;
    let running = false;
    let onScreen = true;
    const draw = (now: number) => {
      const step = last === null ? 0 : Math.min((now - last) / 1000, 0.05);
      last = now;
      clock += step;
      gl.uniform1f(uniform('uTime'), clock);
      scene.frame(gl, uniform, clock, step);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.POINTS, 0, scene.count);
      if (!still) frame = requestAnimationFrame(draw);
    };
    const sync = () => {
      const should = onScreen && !document.hidden;
      if (still) {
        if (should) requestAnimationFrame(draw);
        return;
      }
      if (should === running) return;
      running = should;
      // Visible in the inspector, like the stage drawings: the canvas says when it is paused
      canvas.toggleAttribute('data-paused', !running);
      if (running) {
        last = null;
        frame = requestAnimationFrame(draw);
      } else {
        cancelAnimationFrame(frame);
      }
    };
    const resized = new ResizeObserver(() => {
      measure();
      if (still) requestAnimationFrame(draw);
    });
    resized.observe(canvas);
    const seen = new IntersectionObserver(([entry]) => {
      onScreen = entry.isIntersecting;
      sync();
    });
    seen.observe(canvas);
    document.addEventListener('visibilitychange', sync);
    // A change of colour mode repaints a still scene; a moving one picks it up on its next frame.
    const themed = new MutationObserver(() => {
      if (still) requestAnimationFrame(draw);
    });
    themed.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    sync();

    return () => {
      cancelAnimationFrame(frame);
      resized.disconnect();
      seen.disconnect();
      themed.disconnect();
      document.removeEventListener('visibilitychange', sync);
      // The context is left to the browser to collect: losing it here would leave the canvas dead
      // if this effect runs again on the same element, as it does on a hot reload.
    };
  };

  // Nothing is set up until the canvas is first near the screen.
  const waiting = new IntersectionObserver(
    ([entry]) => {
      if (!entry.isIntersecting) return;
      waiting.disconnect();
      stop = begin();
    },
    { rootMargin: '200px' },
  );
  waiting.observe(canvas);

  // A browser can take the WebGL context away (a phone after switching apps, a GPU reset).
  // The scene stops, and is set up again if the context comes back.
  const onLost = (event: Event) => {
    event.preventDefault();
    stop?.();
    stop = null;
  };
  const onRestored = () => {
    stop?.();
    stop = begin();
  };
  canvas.addEventListener('webglcontextlost', onLost);
  canvas.addEventListener('webglcontextrestored', onRestored);

  return () => {
    waiting.disconnect();
    canvas.removeEventListener('webglcontextlost', onLost);
    canvas.removeEventListener('webglcontextrestored', onRestored);
    stop?.();
  };
}

/** A small seeded generator, so a field is the same on every visit. */
export function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
