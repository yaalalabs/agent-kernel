'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';

const buildPermTable = (): Uint8Array => {
  const p = new Uint8Array(256);
  for (let i = 0; i < 256; i++) p[i] = i;
  for (let i = 255; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const tmp = p[i]; p[i] = p[j]; p[j] = tmp;
  }
  const perm = new Uint8Array(512);
  for (let i = 0; i < 512; i++) perm[i] = p[i & 255];
  return perm;
};

const fade = (t: number) => t * t * t * (t * (t * 6 - 15) + 10);
const lerpN = (a: number, b: number, t: number) => a + t * (b - a);

const grad = (hash: number, x: number, y: number, z: number): number => {
  const h = hash & 15;
  const u = h < 8 ? x : y;
  const v = h < 4 ? y : (h === 12 || h === 14 ? x : z);
  return ((h & 1) ? -u : u) + ((h & 2) ? -v : v);
};

const createNoise = (perm: Uint8Array) => (x: number, y: number, z: number): number => {
  const X = Math.floor(x) & 255, Y = Math.floor(y) & 255, Z = Math.floor(z) & 255;
  x -= Math.floor(x); y -= Math.floor(y); z -= Math.floor(z);
  const u = fade(x), v = fade(y), w = fade(z);
  const A = perm[X] + Y, AA = perm[A] + Z, AB = perm[A + 1] + Z;
  const B = perm[X + 1] + Y, BA = perm[B] + Z, BB = perm[B + 1] + Z;
  return lerpN(
    lerpN(
      lerpN(grad(perm[AA],   x,   y,   z),   grad(perm[BA],   x-1, y,   z),   u),
      lerpN(grad(perm[AB],   x,   y-1, z),   grad(perm[BB],   x-1, y-1, z),   u), v),
    lerpN(
      lerpN(grad(perm[AA+1], x,   y,   z-1), grad(perm[BA+1], x-1, y,   z-1), u),
      lerpN(grad(perm[AB+1], x,   y-1, z-1), grad(perm[BB+1], x-1, y-1, z-1), u), v),
    w
  );
};

const ParticleSphere = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const animationIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Scene
    const scene = new THREE.Scene();

    // Camera
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 30;

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x0F1523, 1);
    containerRef.current.appendChild(renderer.domElement);

    // Noise
    const perm = buildPermTable();
    const noise = createNoise(perm);

    // Particle config
    const COUNT = 7000;
    const RADIUS = 15;
    const NOISE_SCALE = 0.18;
    const DISPLACEMENT = 0.6;

    const positions   = new Float32Array(COUNT * 3);
    const pColors     = new Float32Array(COUNT * 3);
    const basePos     = new Float32Array(COUNT * 3);
    const randValues  = new Float32Array(COUNT);
    const speeds      = new Float32Array(COUNT);

    for (let i = 0; i < COUNT; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi   = Math.acos(2 * Math.random() - 1);
      const r     = RADIUS * (0.97 + Math.random() * 0.06);

      const x = r * Math.sin(phi) * Math.cos(theta);
      const y = r * Math.sin(phi) * Math.sin(theta);
      const z = r * Math.cos(phi);

      basePos[i*3]   = positions[i*3]   = x;
      basePos[i*3+1] = positions[i*3+1] = y;
      basePos[i*3+2] = positions[i*3+2] = z;

      randValues[i] = Math.random() * Math.PI * 2;
      speeds[i]     = 0.3 + Math.random() * 0.7;

      // Maze-style palette: cyan/teal dominant, purple/pink accent
      const rnd = Math.random();
      let pr: number, pg: number, pb: number;
      if (rnd < 0.05) {
        // pink-purple
        pr = 0.75 + Math.random() * 0.25;
        pg = 0.1  + Math.random() * 0.15;
        pb = 0.75 + Math.random() * 0.25;
      } else if (rnd < 0.15) {
        // purple to cyan blend
        const t = Math.random();
        pr = lerpN(0.48, 0.0,  t);
        pg = lerpN(0.25, 0.83, t);
        pb = lerpN(0.89, 1.0,  t);
      } else {
        // cyan to teal
        const t = Math.random();
        pr = 0.0;
        pg = lerpN(0.83, 0.71, t);
        pb = lerpN(1.0,  0.8,  t);
      }
      pColors[i*3]   = pr;
      pColors[i*3+1] = pg;
      pColors[i*3+2] = pb;
    }

    // BufferGeometry — note: color attribute named 'pColor' to avoid
    // conflict with Three.js built-in 'color' when vertexColors is off
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position',    new THREE.BufferAttribute(positions,  3));
    geometry.setAttribute('pColor',      new THREE.BufferAttribute(pColors,    3));
    geometry.setAttribute('randomValue', new THREE.BufferAttribute(randValues, 1));

    // Vertex shader
    const vertexShader = `
      attribute vec3 pColor;
      attribute float randomValue;
      varying vec3 vColor;

      void main() {
        vColor = pColor;

        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = 70.0 * (1.0 / -mvPosition.z);
        gl_Position = projectionMatrix * mvPosition;
      }
    `;

    // Fragment shader
    const fragmentShader = `
      varying vec3 vColor;

      void main() {
        vec2 uv = gl_PointCoord - 0.5;
        float dist = length(uv);
        if (dist > 0.5) discard;
        float alpha = smoothstep(0.5, 0.2, dist) * 0.9;
        gl_FragColor = vec4(vColor, alpha);
      }
    `;

    const material = new THREE.ShaderMaterial({
      uniforms: {},
      vertexShader,
      fragmentShader,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    const particles = new THREE.Points(geometry, material);
    scene.add(particles);

    // Resize handler
    const handleResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener('resize', handleResize);

    // Animation loop
    const posAttr = geometry.attributes.position as THREE.BufferAttribute;
    let time = 0;

    const animate = () => {
      animationIdRef.current = requestAnimationFrame(animate);
      time += 0.005;

      for (let i = 0; i < COUNT; i++) {
        const bx = basePos[i*3], by = basePos[i*3+1], bz = basePos[i*3+2];
        const nt = time * speeds[i] * 0.4 + randValues[i];

        // Three decorrelated noise samples, one per axis
        const nx = noise(bx * NOISE_SCALE + nt,      by * NOISE_SCALE,       bz * NOISE_SCALE);
        const ny = noise(bx * NOISE_SCALE,            by * NOISE_SCALE + nt,  bz * NOISE_SCALE + 1.7);
        const nz = noise(bx * NOISE_SCALE + 3.1,      by * NOISE_SCALE + nt,  bz * NOISE_SCALE);

        posAttr.array[i*3]   = bx + nx * DISPLACEMENT;
        posAttr.array[i*3+1] = by + ny * DISPLACEMENT;
        posAttr.array[i*3+2] = bz + nz * DISPLACEMENT;
      }

      posAttr.needsUpdate = true;

      // Same rotation speeds as original
      particles.rotation.x += 0.0001;
      particles.rotation.y += 0.0005;

      renderer.render(scene, camera);
    };

    animate();

    // Cleanup
    return () => {
      window.removeEventListener('resize', handleResize);
      if (animationIdRef.current) cancelAnimationFrame(animationIdRef.current);
      renderer.dispose();
      geometry.dispose();
      material.dispose();
      if (containerRef.current?.contains(renderer.domElement)) {
        containerRef.current.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        height: '100vh',
        zIndex: -1,
        pointerEvents: 'none',
      }}
    />
  );
};

export default ParticleSphere;
