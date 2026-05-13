'use client';

import { useEffect, useMemo, useRef } from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const PLANT_MAX_EXTENT = 36;
const PLANT_Y_OFFSET = -15;
const MAX_PARTICLES = 10_000;

const buildPermTable = (): Uint8Array => {
  const p = new Uint8Array(256);
  for (let i = 0; i < 256; i++) p[i] = i;
  for (let i = 255; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const tmp = p[i];
    p[i] = p[j];
    p[j] = tmp;
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
  const v = h < 4 ? y : h === 12 || h === 14 ? x : z;
  return (h & 1 ? -u : u) + (h & 2 ? -v : v);
};

const createNoise = (perm: Uint8Array) => (x: number, y: number, z: number): number => {
  const X = Math.floor(x) & 255,
    Y = Math.floor(y) & 255,
    Z = Math.floor(z) & 255;
  x -= Math.floor(x);
  y -= Math.floor(y);
  z -= Math.floor(z);
  const u = fade(x),
    v = fade(y),
    w = fade(z);
  const A = perm[X] + Y,
    AA = perm[A] + Z,
    AB = perm[A + 1] + Z;
  const B = perm[X + 1] + Y,
    BA = perm[B] + Z,
    BB = perm[B + 1] + Z;
  return lerpN(
    lerpN(
      lerpN(grad(perm[AA], x, y, z), grad(perm[BA], x - 1, y, z), u),
      lerpN(grad(perm[AB], x, y - 1, z), grad(perm[BB], x - 1, y - 1, z), u),
      v
    ),
    lerpN(
      lerpN(grad(perm[AA + 1], x, y, z - 1), grad(perm[BA + 1], x - 1, y, z - 1), u),
      lerpN(grad(perm[AB + 1], x, y - 1, z - 1), grad(perm[BB + 1], x - 1, y - 1, z - 1), u),
      v
    ),
    w
  );
};

function sampleParticlePalette(out: Float32Array, i: number): void {
  const rnd = Math.random();
  let pr: number;
  let pg: number;
  let pb: number;
  if (rnd < 0.05) {
    pr = 0.75 + Math.random() * 0.25;
    pg = 0.1 + Math.random() * 0.15;
    pb = 0.75 + Math.random() * 0.25;
  } else if (rnd < 0.15) {
    const t = Math.random();
    pr = lerpN(0.48, 0.0, t);
    pg = lerpN(0.25, 0.83, t);
    pb = lerpN(0.89, 1.0, t);
  } else {
    const t = Math.random();
    pr = 0.0;
    pg = lerpN(0.83, 0.71, t);
    pb = lerpN(1.0, 0.8, t);
  }
  out[i * 3] = pr;
  out[i * 3 + 1] = pg;
  out[i * 3 + 2] = pb;
}

function mergePlantFromGltf(root: THREE.Object3D): THREE.BufferGeometry {
  root.updateMatrixWorld(true);
  const parts: THREE.BufferGeometry[] = [];
  root.traverse((child) => {
    if (child instanceof THREE.Mesh && child.geometry) {
      let g = child.geometry.clone();
      if (g.index) g = g.toNonIndexed();
      g.applyMatrix4(child.matrixWorld);
      for (const key of Object.keys(g.attributes)) {
        if (key !== 'position') g.deleteAttribute(key);
      }
      parts.push(g);
    }
  });
  if (parts.length === 0) return new THREE.BufferGeometry();
  const merged = mergeGeometries(parts);
  return merged ?? parts[0]!.clone();
}

function normalizePlantGeometry(geo: THREE.BufferGeometry): void {
  geo.computeBoundingBox();
  const bb = geo.boundingBox;
  if (!bb) return;
  geo.translate(-(bb.min.x + bb.max.x) / 2, -bb.min.y, -(bb.min.z + bb.max.z) / 2);
  geo.computeBoundingBox();
  const bb2 = geo.boundingBox;
  if (!bb2) return;
  const size = new THREE.Vector3();
  bb2.getSize(size);
  const maxDim = Math.max(size.x, size.y, size.z, 1e-6);
  const s = PLANT_MAX_EXTENT / maxDim;
  geo.scale(s, s, s);
  geo.translate(0, PLANT_Y_OFFSET, 0);
}

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

const ParticleSphere = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const { siteConfig } = useDocusaurusContext();
  const plantModelUrl = useMemo(() => {
    const base = siteConfig.baseUrl.endsWith('/') ? siteConfig.baseUrl : `${siteConfig.baseUrl}/`;
    return `${base}models/plant.glb`;
  }, [siteConfig.baseUrl]);

  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    const perm = buildPermTable();
    const noise = createNoise(perm);

    const NOISE_SCALE = 0.18;
    const DISPLACEMENT = 0.6;

    let cancelled = false;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 30;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x0f1523, 1);
    container.appendChild(renderer.domElement);

    const particles = new THREE.Points();
    scene.add(particles);

    let animationId: number | null = null;
    let posAttr: THREE.BufferAttribute | null = null;
    let basePos: Float32Array | null = null;
    let randValues: Float32Array | null = null;
    let speeds: Float32Array | null = null;
    let particleCount = 0;

    const geometry = new THREE.BufferGeometry();
    const material = new THREE.ShaderMaterial({
      uniforms: {},
      vertexShader,
      fragmentShader,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    particles.geometry = geometry;
    particles.material = material;

    const handleResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener('resize', handleResize);

    let time = 0;
    const animate = () => {
      if (cancelled) return;
      animationId = requestAnimationFrame(animate);
      if (!posAttr || !basePos || !randValues || !speeds) return;

      time += 0.005;

      for (let i = 0; i < particleCount; i++) {
        const bx = basePos[i * 3],
          by = basePos[i * 3 + 1],
          bz = basePos[i * 3 + 2];
        const nt = time * speeds[i] * 0.4 + randValues[i];

        const nx = noise(bx * NOISE_SCALE + nt, by * NOISE_SCALE, bz * NOISE_SCALE);
        const ny = noise(bx * NOISE_SCALE, by * NOISE_SCALE + nt, bz * NOISE_SCALE + 1.7);
        const nz = noise(bx * NOISE_SCALE + 3.1, by * NOISE_SCALE + nt, bz * NOISE_SCALE);

        posAttr.array[i * 3] = bx + nx * DISPLACEMENT;
        posAttr.array[i * 3 + 1] = by + ny * DISPLACEMENT;
        posAttr.array[i * 3 + 2] = bz + nz * DISPLACEMENT;
      }

      posAttr.needsUpdate = true;

      particles.rotation.x += 0.0001;
      particles.rotation.y += 0.0005;

      renderer.render(scene, camera);
    };

    const startSphereFallback = () => {
      const COUNT = 7000;
      const RADIUS = 15;
      const positions = new Float32Array(COUNT * 3);
      const pColors = new Float32Array(COUNT * 3);
      basePos = new Float32Array(COUNT * 3);
      randValues = new Float32Array(COUNT);
      speeds = new Float32Array(COUNT);
      particleCount = COUNT;

      for (let i = 0; i < COUNT; i++) {
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        const r = RADIUS * (0.97 + Math.random() * 0.06);

        const x = r * Math.sin(phi) * Math.cos(theta);
        const y = r * Math.sin(phi) * Math.sin(theta);
        const z = r * Math.cos(phi);

        basePos[i * 3] = positions[i * 3] = x;
        basePos[i * 3 + 1] = positions[i * 3 + 1] = y;
        basePos[i * 3 + 2] = positions[i * 3 + 2] = z;

        randValues[i] = Math.random() * Math.PI * 2;
        speeds[i] = 0.3 + Math.random() * 0.7;
        sampleParticlePalette(pColors, i);
      }

      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute('pColor', new THREE.BufferAttribute(pColors, 3));
      geometry.setAttribute('randomValue', new THREE.BufferAttribute(randValues, 1));
      posAttr = geometry.attributes.position as THREE.BufferAttribute;
    };

    const startFromPlantGeometry = (plantGeo: THREE.BufferGeometry) => {
      normalizePlantGeometry(plantGeo);
      const attr = plantGeo.attributes.position as THREE.BufferAttribute;
      const totalVerts = attr.count;
      if (totalVerts === 0) {
        plantGeo.dispose();
        startSphereFallback();
        return;
      }

      const step = Math.max(1, Math.floor(totalVerts / MAX_PARTICLES));
      particleCount = Math.ceil(totalVerts / step);

      const positions = new Float32Array(particleCount * 3);
      const pColors = new Float32Array(particleCount * 3);
      basePos = new Float32Array(particleCount * 3);
      randValues = new Float32Array(particleCount);
      speeds = new Float32Array(particleCount);

      const src = attr.array as Float32Array;
      for (let i = 0, j = 0; j < particleCount; i += step, j++) {
        const o = j * 3;
        const si = Math.min(i, totalVerts - 1) * 3;
        positions[o] = basePos[o] = src[si];
        positions[o + 1] = basePos[o + 1] = src[si + 1];
        positions[o + 2] = basePos[o + 2] = src[si + 2];
        randValues[j] = Math.random() * Math.PI * 2;
        speeds[j] = 0.3 + Math.random() * 0.7;
        sampleParticlePalette(pColors, j);
      }

      plantGeo.dispose();

      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute('pColor', new THREE.BufferAttribute(pColors, 3));
      geometry.setAttribute('randomValue', new THREE.BufferAttribute(randValues, 1));
      posAttr = geometry.attributes.position as THREE.BufferAttribute;
    };

    (async () => {
      try {
        const loader = new GLTFLoader();
        const gltf = await loader.loadAsync(plantModelUrl);
        if (cancelled) return;
        const merged = mergePlantFromGltf(gltf.scene);
        startFromPlantGeometry(merged);
      } catch {
        if (cancelled) return;
        startSphereFallback();
      }
      if (cancelled) return;
      animate();
    })();

    return () => {
      cancelled = true;
      window.removeEventListener('resize', handleResize);
      if (animationId !== null) cancelAnimationFrame(animationId);
      renderer.dispose();
      geometry.dispose();
      material.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, [plantModelUrl]);

  return (
    <div
      ref={containerRef}
      style={{
        position: 'fixed',
        top: 30,
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
