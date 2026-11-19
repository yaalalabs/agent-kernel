import React, { useEffect, useRef } from 'react';
import clsx from 'clsx';
import { runDots, seeded, tokenColour, type DotScene } from './engine';
import styles from './styles.module.css';

/**
 * A sheet of dots that rolls like slow water, seen from a low angle. It sits behind the text
 * of the closing panel, thins out towards the copy, and carries the accent on its crests.
 * Rows of dots stay rows as they move, so the sheet reads as woven lines, not as noise.
 */

const COLUMNS = 150;
const ROWS = 52;

const VERTEX = `
precision highp float;
attribute vec2 aGrid;
attribute float aSeed;
uniform float uTime;
uniform float uDpr;
uniform vec2 uView;
uniform vec3 uBase;
uniform vec3 uCrest;
varying vec3 vColor;
varying float vAlpha;

void main() {
  float t = uTime;
  float x = aGrid.x * 2.0 - 1.0;
  float z = aGrid.y;

  // Three slow waves of different length and direction make the surface
  float height = sin(x * 2.4 + t * 0.32) * 0.5
    + sin(z * 5.2 - t * 0.26 + x * 1.7) * 0.34
    + sin((x + z) * 7.0 + t * 0.44) * 0.16;

  // A low camera: far rows are higher on the panel, closer together and smaller
  float depth = 1.0 / (1.0 + z * 1.25);
  float px = uView.x * (0.64 + x * 0.74 / (1.0 + z * 0.55));
  float py = uView.y * (1.06 - (z * 1.95 + height * 0.26 + 0.04) * depth);
  vec2 clip = vec2(px, py) / uView * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
  gl_PointSize = max((1.5 + aSeed * 0.9) * (0.5 + depth * 1.35) * uDpr, 1.0);

  float crest = smoothstep(0.35, 0.9, height);
  vColor = mix(uBase, uCrest, crest);
  // Thin towards the copy on the left, towards the horizon, and at the right edge
  float towardsCopy = smoothstep(0.4, 0.78, px / uView.x);
  float horizon = 1.0 - smoothstep(0.5, 1.0, z);
  float edge = 1.0 - smoothstep(0.92, 1.0, abs(x));
  vAlpha = (0.42 + crest * 0.58) * towardsCopy * horizon * edge;
}
`;

function scene(host: Element): DotScene {
  const random = seeded(7);
  const grid = new Float32Array(COLUMNS * ROWS * 2);
  const seed = new Float32Array(COLUMNS * ROWS);
  for (let row = 0, i = 0; row < ROWS; row++) {
    for (let column = 0; column < COLUMNS; column++, i++) {
      grid[i * 2] = column / (COLUMNS - 1);
      // Rows bunch towards the viewer a little less than the camera spreads them
      grid[i * 2 + 1] = Math.pow(row / (ROWS - 1), 1.35);
      seed[i] = random();
    }
  }
  return {
    vertex: VERTEX,
    attributes: { aGrid: { data: grid, size: 2 }, aSeed: { data: seed, size: 1 } },
    count: COLUMNS * ROWS,
    frame: (gl, uniform) => {
      gl.uniform3fv(uniform('uBase'), tokenColour(host, '--ak-blue-rgb'));
      gl.uniform3fv(uniform('uCrest'), tokenColour(host, '--ak-primary-rgb'));
    },
  };
}

export default function Wave({ className }: { className?: string }): JSX.Element {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const node = canvas.current;
    if (!node) return undefined;
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    return runDots(node, scene(node), still);
  }, []);

  return <canvas ref={canvas} className={clsx(styles.canvas, className)} aria-hidden="true" />;
}
