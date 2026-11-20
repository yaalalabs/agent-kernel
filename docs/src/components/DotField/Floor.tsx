import React, { useEffect, useRef } from 'react';
import clsx from 'clsx';
import { runDots, seeded, tokenColour, type DotScene } from './engine';
import styles from './styles.module.css';

/**
 * A floor of dots along the bottom edge of the integrations section, the full width of the
 * page. It is a relative of the closing panel's wave, and is told apart from it on purpose:
 * it is centred and calm, it is one colour at rest, and the accent only appears as a ripple
 * that crosses the floor when the stage changes, in the direction the visitor moved.
 */

const COLUMNS = 176;
const ROWS = 26;
const RIPPLE_SECONDS = 1.8;

const VERTEX = `
precision highp float;
attribute vec2 aGrid;
attribute float aSeed;
uniform float uTime;
uniform float uDpr;
uniform vec2 uView;
uniform float uRipple;
uniform float uDirection;
uniform float uInk;
uniform vec3 uBase;
uniform vec3 uAccent;
varying vec3 vColor;
varying float vAlpha;

void main() {
  float t = uTime;
  float x = aGrid.x * 2.0 - 1.0;
  float z = aGrid.y;

  // A gentle swell: lower and slower than the closing panel's wave
  float swell = sin(x * 3.1 + t * 0.24) * 0.5 + sin(z * 6.0 - t * 0.3 + x * 2.2) * 0.32 + sin((x - z) * 9.0 + t * 0.4) * 0.12;

  // The ripple: one front that crosses the floor, lifting the dots and lending them the accent
  float front = uDirection * (-1.45 + uRipple * 2.9);
  float lift = exp(-pow((x - front) * 3.6, 2.0)) * sin(min(uRipple, 1.0) * 3.14159);

  // Seen from above the near edge: far rows gather towards a horizon in the middle of the page
  float depth = 1.0 / (1.0 + z * 1.6);
  float px = uView.x * (0.5 + x * 0.84 * (0.45 + 0.55 * depth));
  float py = uView.y * (1.05 - z * 1.95 * depth - (swell * 0.1 + lift * 0.22) * depth);
  vec2 clip = vec2(px, py) / uView * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
  gl_PointSize = max((1.2 + aSeed * 0.6) * (0.55 + depth * 1.05) * (1.0 + lift * 0.9) * uDpr, 1.0);

  vColor = mix(uBase, uAccent, clamp(lift * 1.3, 0.0, 1.0));
  float horizon = 1.0 - smoothstep(0.45, 1.0, z);
  vAlpha = min((0.3 * uInk + lift * 0.65) * horizon, 1.0);
}
`;

function scene(host: Element, stage: { current: number }): DotScene {
  const random = seeded(19);
  const grid = new Float32Array(COLUMNS * ROWS * 2);
  const seed = new Float32Array(COLUMNS * ROWS);
  for (let row = 0, i = 0; row < ROWS; row++) {
    for (let column = 0; column < COLUMNS; column++, i++) {
      grid[i * 2] = column / (COLUMNS - 1);
      grid[i * 2 + 1] = Math.pow(row / (ROWS - 1), 1.25);
      seed[i] = random();
    }
  }
  let shown = stage.current;
  let ripple = 1;
  let direction = 1;
  return {
    vertex: VERTEX,
    attributes: { aGrid: { data: grid, size: 2 }, aSeed: { data: seed, size: 1 } },
    count: COLUMNS * ROWS,
    frame: (gl, uniform, _time, step) => {
      if (stage.current !== shown) {
        direction = stage.current > shown ? 1 : -1;
        shown = stage.current;
        ripple = 0;
      }
      ripple = Math.min(1, ripple + step / RIPPLE_SECONDS);
      gl.uniform1f(uniform('uRipple'), ripple);
      gl.uniform1f(uniform('uDirection'), direction);
      // Ink on the light page needs a little more weight than light on the dark one
      gl.uniform1f(uniform('uInk'), document.documentElement.getAttribute('data-theme') === 'light' ? 1.5 : 1.0);
      gl.uniform3fv(uniform('uBase'), tokenColour(host, '--ak-blue-rgb'));
      gl.uniform3fv(uniform('uAccent'), tokenColour(host, '--ak-primary-rgb'));
    },
  };
}

/** `stage` is the index of the stage in view: each change sends one ripple across the floor. */
export default function Floor({ stage, className }: { stage: number; className?: string }): JSX.Element {
  const canvas = useRef<HTMLCanvasElement>(null);
  const current = useRef(stage);
  current.current = stage;

  useEffect(() => {
    const node = canvas.current;
    if (!node) return undefined;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined;
    return runDots(node, scene(node, current));
  }, []);

  return <canvas ref={canvas} className={clsx(styles.canvas, className)} aria-hidden="true" />;
}
