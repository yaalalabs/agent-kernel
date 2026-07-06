'use client';

import { useEffect, useMemo, useRef, forwardRef, useImperativeHandle } from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const PLANT_MAX_EXTENT = 2.8;
const MAX_PARTICLES = 2_000;
const PARTICLE_CORE_ALPHA = 0.15;
const PARTICLE_GLOW_ALPHA = 0.10;
const PARTICLE_OVERLAY_OPACITY = 0.12;
const INTRO_ANIMATION_DURATION = 2.0; // seconds
const INTRO_ANIMATION_SCATTER_RADIUS = 6.0; // how far particles scatter initially
const SCATTER_OUT_DELAY = 3.5; // delay before scattering out (after intro completes)
const SCATTER_OUT_DURATION = 3.5; // duration of scatter out animation
const SCATTER_OUT_FADE_DURATION = 1.0; // duration of fade out after scatter completes
const SCATTER_OUT_RADIUS = 8.0; // how far particles scatter outward

// ── Scatter-float animation constants ────────────────────────────────────────
const SCATTER_FLOAT_DURATION = 2.5;   // seconds to scatter outward before floating
const SCATTER_FLOAT_RADIUS   = 5.0;   // how far particles scatter before floating
const FLOAT_DRIFT_AMPLITUDE  = 0.06;  // max drift distance per axis while floating (firefly-gentle)
const FLOAT_REFORM_DURATION  = 2.2;   // seconds to ease back into model shape
const INTRO_DRIFT_FADE_IN_DURATION = 0.8; // seconds to fade drift in after intro completes

// Color palette
const PALETTE: [number, number, number][] = [
  [0.0, 221 / 255, 1.0],          // #00DDFF (brand color)
  [0.0, 170 / 255, 222 / 255],    // #00AADE (blue shade)
  [242 / 255, 0.0, 1.0],          // #F200FF (accent)
];

const vertexShader = `
  attribute vec3 aColor;
  uniform float uSize;
  uniform float uResolutionY;
  uniform float uTime;
  uniform float uDisableDrift;
  uniform float uDriftMix;
  varying vec3 vPos;
  varying vec3 vColor;

  void main() {
    vec3 pos = position;
    
    if (uDisableDrift > 0.5) {
      float hash = sin(pos.x * 12.9898 + pos.y * 78.233 + pos.z * 45.164) * 43758.5453;
      float frac_hash = fract(hash);
      
      float drift_x = sin(uTime * 0.5 + frac_hash * 6.28) * 0.045;
      float drift_y = cos(uTime * 0.4 + frac_hash * 6.28) * 0.045;
      float drift_z = sin(uTime * 0.35 + frac_hash * 6.28) * 0.035;
      
      pos += vec3(drift_x, drift_y, drift_z) * uDriftMix;
    }
    
    vPos = pos;
    vColor = aColor;
    vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
    gl_PointSize = uSize * uResolutionY * 0.0013 * (1.0 / -mvPosition.z);
    gl_Position = projectionMatrix * mvPosition;
  }
`;

const coreFragmentShader = `
  varying vec3 vPos;
  varying vec3 vColor;
  uniform float uAlpha;

  void main() {
    float d = distance(gl_PointCoord, vec2(0.5));
    float strength = 0.05 / d - 0.1;
    vec3 color = vColor;
    gl_FragColor = vec4(color, strength * length(vPos) * ${PARTICLE_CORE_ALPHA.toFixed(2)} * uAlpha);
  }
`;

const glowFragmentShader = `
  varying vec3 vPos;
  varying vec3 vColor;
  uniform float uAlpha;

  void main() {
    float d = distance(gl_PointCoord, vec2(0.5));
    if (d > 0.5) discard;
    float strength = pow(max(0.0, 1.0 - d * 2.0), 3.0) * 0.22;
    vec3 color = vColor;
    gl_FragColor = vec4(color, strength * clamp(length(vPos) * 0.5, 0.0, 1.0) * ${PARTICLE_GLOW_ALPHA.toFixed(2)} * uAlpha);
  }
`;

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
  geo.scale(PLANT_MAX_EXTENT / maxDim, PLANT_MAX_EXTENT / maxDim, PLANT_MAX_EXTENT / maxDim);
  geo.translate(0, -1.5, 0);
}

function assignColorsToGeometry(geo: THREE.BufferGeometry, count: number) {
  const colors = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const r = Math.random();
    let idx = 0;
    if (r < 0.6) idx = 0;
    else if (r < 0.9) idx = 1;
    else idx = 2;
    const c = PALETTE[idx];
    colors[i * 3] = c[0];
    colors[i * 3 + 1] = c[1];
    colors[i * 3 + 2] = c[2];
  }
  geo.setAttribute('aColor', new THREE.BufferAttribute(colors, 3));
}

function generateScatteredPositions(count: number): Float32Array {
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const r = INTRO_ANIMATION_SCATTER_RADIUS * (0.6 + Math.random() * 0.4);
    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta) - 1.5;
    positions[i * 3 + 2] = r * Math.cos(phi);
  }
  return positions;
}

/**
 * Generate per-particle float seeds.
 * Layout per particle (stride = 6):
 *   [0] freqX   – oscillation frequency on X  (0.3 – 0.9 Hz)
 *   [1] freqY   – oscillation frequency on Y
 *   [2] freqZ   – oscillation frequency on Z
 *   [3] phaseX  – phase offset X  (0 – 2π)
 *   [4] phaseY  – phase offset Y
 *   [5] phaseZ  – phase offset Z
 */
function generateFloatSeeds(count: number): Float32Array {
  const seeds = new Float32Array(count * 6);
  for (let i = 0; i < count; i++) {
    const base = i * 6;
    // Very slow independent frequencies per axis — firefly drift feel
    seeds[base + 0] = 0.08 + Math.random() * 0.14;  // 0.08–0.22 Hz X
    seeds[base + 1] = 0.07 + Math.random() * 0.13;  // 0.07–0.20 Hz Y
    seeds[base + 2] = 0.06 + Math.random() * 0.12;  // 0.06–0.18 Hz Z
    seeds[base + 3] = Math.random() * Math.PI * 2;   // phase X
    seeds[base + 4] = Math.random() * Math.PI * 2;   // phase Y
    seeds[base + 5] = Math.random() * Math.PI * 2;   // phase Z
  }
  return seeds;
}

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

interface PlantParticlesBackgroundProps {
  modelUrl?: string;
}

interface PlantParticlesBackgroundHandle {
  triggerScatterOut: () => void;
  triggerScatterIn: () => void;
  triggerReverseScatterIn: () => void;
  /** New: scatter particles outward then let them float. Particles stay visible. */
  triggerScatterFloat: () => void;
  /** New: reform floating particles back into the model shape. */
  triggerFloatReform: () => void;
}

const PlantParticlesBackground = forwardRef<PlantParticlesBackgroundHandle, PlantParticlesBackgroundProps>(
  ({ modelUrl }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const { siteConfig } = useDocusaurusContext();
    const triggerScatterOutRef         = useRef<() => void>(() => {});
    const triggerScatterInRef          = useRef<() => void>(() => {});
    const triggerReverseScatterInRef   = useRef<() => void>(() => {});
    const triggerScatterFloatRef       = useRef<() => void>(() => {});
    const triggerFloatReformRef        = useRef<() => void>(() => {});

    useImperativeHandle(ref, () => ({
      triggerScatterOut:       () => triggerScatterOutRef.current(),
      triggerScatterIn:        () => triggerScatterInRef.current(),
      triggerReverseScatterIn: () => triggerReverseScatterInRef.current(),
      triggerScatterFloat:     () => triggerScatterFloatRef.current(),
      triggerFloatReform:      () => triggerFloatReformRef.current(),
    }));

    const indexModelUrl = useMemo(() => {
      if (modelUrl) return modelUrl;
      const base = siteConfig.baseUrl.endsWith('/')
        ? siteConfig.baseUrl
        : `${siteConfig.baseUrl}/`;
      return `${base}models/index.glb`;
    }, [modelUrl, siteConfig.baseUrl]);

    useEffect(() => {
      if (!containerRef.current) return;
      const container = containerRef.current;
      let cancelled = false;
      let animationId: number | null = null;

      // ── Shared time ──────────────────────────────────────────────────────────
      let elapsedTime = 0;

      // ── Intro animation ──────────────────────────────────────────────────────
      let isAnimatingIntro    = false;
      let introAnimationTime  = 0;
      let introDriftFadeInTime = 0;
      let isSettlingAfterIntro = false;
      let startPositions: Float32Array | null = null;
      let endPositions:   Float32Array | null = null;
      let introScatterPositions: Float32Array | null = null;

      // ── Scatter-out (original, with fade) ────────────────────────────────────
      let isAnimatingScatterOut   = false;
      let scatterOutAnimationTime = 0;
      let isAnimatingFadeOut      = false;
      let fadeOutAnimationTime    = 0;
      let scatteredPositions: Float32Array | null = null;
      let hasScatteredOut = false;

      // ── Scatter-in (original) ────────────────────────────────────────────────
      let hasScatteredIn         = true;

      // ── Reverse scatter-in ───────────────────────────────────────────────────
      let isAnimatingReverseScatterIn   = false;
      let reverseScatterInAnimationTime = 0;

      // ── Model reference ──────────────────────────────────────────────────────
      let canonicalModelPositions: Float32Array | null = null;
      let modelPositions: Float32Array | null = null;

      // ── NEW: Scatter-float state ─────────────────────────────────────────────
      let isAnimatingScatterFloat   = false;
      let scatterFloatTime          = 0;
      let scatterFloatStart: Float32Array | null  = null;  // positions at trigger time
      let scatterFloatTarget: Float32Array | null = null;  // outward resting positions
      let isFloating                = false;               // steady-state floating
      let floatBasePositions: Float32Array | null = null;  // resting centres for drift
      let floatSeeds: Float32Array | null         = null;  // per-particle freq/phase

      // ── NEW: Float-reform state ──────────────────────────────────────────────
      let isAnimatingFloatReform    = false;
      let floatReformTime           = 0;
      let floatReformStart: Float32Array | null = null;   // snapshot at trigger time

      // ── Scene setup ──────────────────────────────────────────────────────────
      const scene  = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 100);
      camera.position.z = 5;

      const pixelRatio = Math.min(window.devicePixelRatio, 1.5);
      const renderer  = new THREE.WebGLRenderer({ antialias: false, alpha: false, powerPreference: 'high-performance' });
      renderer.setSize(window.innerWidth, window.innerHeight);
      renderer.setPixelRatio(pixelRatio);
      renderer.setClearColor(0x0D001A, 1);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      container.appendChild(renderer.domElement);

      // ── Geometry & materials ─────────────────────────────────────────────────
      const geometry = new THREE.BufferGeometry();

      const makeUniforms = () => ({
        uSize:        { value: 110.0 },
        uResolutionY: { value: window.innerHeight },
        uTime:        { value: 0 },
        uAlpha:       { value: 1.0 },
        uDisableDrift:{ value: 0.0 },
        uDriftMix:    { value: 0.0 },
      });

      const coreMaterial = new THREE.ShaderMaterial({
        uniforms: makeUniforms(),
        vertexShader,
        fragmentShader: coreFragmentShader,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      coreMaterial.uniforms.uSize.value = 110.0;

      const glowMaterial = new THREE.ShaderMaterial({
        uniforms: makeUniforms(),
        vertexShader,
        fragmentShader: glowFragmentShader,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      glowMaterial.uniforms.uSize.value = 160.0;

      const coreParticles = new THREE.Points(geometry, coreMaterial);
      const glowParticles = new THREE.Points(geometry, glowMaterial);
      scene.add(glowParticles);
      scene.add(coreParticles);

      // ── Overlay ───────────────────────────────────────────────────────────────
      const overlay = document.createElement('div');
      overlay.style.cssText = `position:absolute;inset:0;pointer-events:none;
        background:linear-gradient(180deg,rgba(13,0,26,0.08) 0%,rgba(13,0,26,${PARTICLE_OVERLAY_OPACITY}) 100%);
        mix-blend-mode:multiply;`;
      container.appendChild(overlay);

      // ── Resize / visibility ───────────────────────────────────────────────────
      const handleResize = () => {
        const pr = Math.min(window.devicePixelRatio, 1.5);
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(pr);
        coreMaterial.uniforms.uResolutionY.value = window.innerHeight;
        glowMaterial.uniforms.uResolutionY.value = window.innerHeight;
      };
      window.addEventListener('resize', handleResize);

      const handleVisibility = () => {
        if (document.hidden) {
          if (animationId !== null) { cancelAnimationFrame(animationId); animationId = null; }
        } else if (!cancelled) {
          animationId = requestAnimationFrame(animate);
        }
      };
      document.addEventListener('visibilitychange', handleVisibility);

      // ── Helper: set alpha on both materials ───────────────────────────────────
      const setAlpha = (v: number) => {
        coreMaterial.uniforms.uAlpha.value = v;
        glowMaterial.uniforms.uAlpha.value = v;
      };

      const readCurrentPositions = () => {
        const posAttr = geometry.attributes.position as THREE.BufferAttribute;
        return new Float32Array(posAttr.array as Float32Array);
      };

      const writePositions = (positions: Float32Array) => {
        const posAttr = geometry.attributes.position as THREE.BufferAttribute;
        (posAttr.array as Float32Array).set(positions);
        posAttr.needsUpdate = true;
      };

      const resetMotionState = () => {
        isAnimatingIntro = false;
        introAnimationTime = 0;
        introDriftFadeInTime = 0;
        isSettlingAfterIntro = false;
        startPositions = null;

        isAnimatingScatterOut = false;
        scatterOutAnimationTime = 0;
        isAnimatingFadeOut = false;
        fadeOutAnimationTime = 0;
        scatteredPositions = null;

        isAnimatingReverseScatterIn = false;
        reverseScatterInAnimationTime = 0;

        isAnimatingScatterFloat = false;
        scatterFloatTime = 0;
        scatterFloatStart = null;
        scatterFloatTarget = null;

        isAnimatingFloatReform = false;
        floatReformTime = 0;
        floatReformStart = null;

        isFloating = false;
        floatBasePositions = null;
        floatSeeds = null;

        if (canonicalModelPositions) {
          endPositions = canonicalModelPositions.slice();
          modelPositions = canonicalModelPositions.slice();
        }
      };

      const startScatterOut = () => {
        if (!canonicalModelPositions || !endPositions) return;
        const startFromModel = hasScatteredOut && modelPositions !== null;
        resetMotionState();
        hasScatteredIn = false;
        hasScatteredOut = false;
        startPositions = startFromModel ? modelPositions.slice() : readCurrentPositions();
        isAnimatingScatterOut = true;
        scatterOutAnimationTime = 0;
        setAlpha(1.0);
      };

      const startScatterIn = () => {
        if (!canonicalModelPositions) return;
        resetMotionState();
        hasScatteredIn = true;
        hasScatteredOut = false;
        endPositions = canonicalModelPositions.slice();
        startPositions = generateScatteredPositions(endPositions.length / 3);
        writePositions(startPositions);
        setAlpha(0.0);
        isAnimatingIntro = true;
        introAnimationTime = 0;
      };

      const startReverseScatterIn = () => {
        if (!canonicalModelPositions || !introScatterPositions) return;
        resetMotionState();
        hasScatteredOut = false;
        hasScatteredIn = false;
        startPositions = readCurrentPositions();
        endPositions = introScatterPositions.slice();
        writePositions(startPositions);
        setAlpha(1.0);
        isAnimatingReverseScatterIn = true;
        reverseScatterInAnimationTime = 0;
      };

      const startScatterFloat = () => {
        if (!modelPositions) return;
        resetMotionState();
        scatterFloatStart = readCurrentPositions();

        const n = scatterFloatStart.length / 3;
        scatterFloatTarget = new Float32Array(scatterFloatStart.length);
        for (let i = 0; i < n; i++) {
          const idx = i * 3;
          const x = scatterFloatStart[idx];
          const y = scatterFloatStart[idx + 1];
          const z = scatterFloatStart[idx + 2];
          const dist = Math.sqrt(x * x + y * y + z * z);
          const nx = dist > 0.001 ? x / dist : (Math.random() - 0.5) * 2;
          const ny = dist > 0.001 ? y / dist : (Math.random() - 0.5) * 2;
          const nz = dist > 0.001 ? z / dist : (Math.random() - 0.5) * 2;
          const r = SCATTER_FLOAT_RADIUS + dist * 0.5;
          scatterFloatTarget[idx] = nx * r;
          scatterFloatTarget[idx + 1] = ny * r;
          scatterFloatTarget[idx + 2] = nz * r;
        }

        floatSeeds = generateFloatSeeds(n);
        isAnimatingScatterFloat = true;
        scatterFloatTime = 0;
        setAlpha(1.0);
      };

      const startFloatReform = () => {
        if (!modelPositions) return;
        resetMotionState();
        floatReformStart = readCurrentPositions();
        endPositions = modelPositions.slice();
        isAnimatingFloatReform = true;
        floatReformTime = 0;
        setAlpha(1.0);
      };

      // ── Expose triggers ───────────────────────────────────────────────────────
      triggerScatterOutRef.current = startScatterOut;
      triggerScatterInRef.current = startScatterIn;
      triggerReverseScatterInRef.current = startReverseScatterIn;

      triggerScatterFloatRef.current = startScatterFloat;
      triggerFloatReformRef.current = startFloatReform;

      // ── Animate ────────────────────────────────────────────────────────────────
      const animate = () => {
        if (cancelled) return;
        animationId = requestAnimationFrame(animate);
        elapsedTime += 0.016;

        // Rotation when idle
        if (!isAnimatingIntro && !isAnimatingScatterOut && !isAnimatingFadeOut
            && !isAnimatingScatterFloat && !isAnimatingFloatReform && !isFloating) {
          coreParticles.rotation.y += 0.001;
          glowParticles.rotation.y = coreParticles.rotation.y;
        }

        // ── Intro ───────────────────────────────────────────────────────────────
        if (isAnimatingIntro && startPositions && endPositions) {
          introAnimationTime += 0.016;
          const progress = Math.min(introAnimationTime / INTRO_ANIMATION_DURATION, 1.0);
          const ep = easeInOutCubic(progress);
          const posAttr = geometry.attributes.position as THREE.BufferAttribute;
          const positions = posAttr.array as Float32Array;
          const n = positions.length / 3;
          for (let i = 0; i < n; i++) {
            const idx = i * 3;
            positions[idx]     = startPositions[idx]     + (endPositions[idx]     - startPositions[idx])     * ep;
            positions[idx + 1] = startPositions[idx + 1] + (endPositions[idx + 1] - startPositions[idx + 1]) * ep;
            positions[idx + 2] = startPositions[idx + 2] + (endPositions[idx + 2] - startPositions[idx + 2]) * ep;
          }
          posAttr.needsUpdate = true;
          setAlpha(ep);

          if (progress >= 1.0) {
            isAnimatingIntro = false;
            setAlpha(1.0);
            const posAttr2 = geometry.attributes.position as THREE.BufferAttribute;
            posAttr2.array.set(endPositions);
            posAttr2.needsUpdate = true;
            canonicalModelPositions = endPositions.slice();
            modelPositions = endPositions.slice();
            introScatterPositions = startPositions.slice();
            startPositions = null;
            isSettlingAfterIntro = true;
            introDriftFadeInTime = 0;
          }
        }

        // ── Reverse scatter-in animation ────────────────────────────────────────
        if (isAnimatingReverseScatterIn && startPositions && endPositions) {
          reverseScatterInAnimationTime += 0.016;
          const progress = Math.min(reverseScatterInAnimationTime / INTRO_ANIMATION_DURATION, 1.0);
          const ep = easeInOutCubic(progress);
          const posAttr = geometry.attributes.position as THREE.BufferAttribute;
          const positions = posAttr.array as Float32Array;
          const n = positions.length / 3;
          for (let i = 0; i < n; i++) {
            const idx = i * 3;
            positions[idx]     = startPositions[idx]     + (endPositions[idx]     - startPositions[idx])     * ep;
            positions[idx + 1] = startPositions[idx + 1] + (endPositions[idx + 1] - startPositions[idx + 1]) * ep;
            positions[idx + 2] = startPositions[idx + 2] + (endPositions[idx + 2] - startPositions[idx + 2]) * ep;
          }
          posAttr.needsUpdate = true;
          setAlpha(1.0 - ep);
          if (progress >= 1.0) {
            isAnimatingReverseScatterIn = false;
            startPositions = null;
            endPositions   = modelPositions ? modelPositions.slice() : null;
          }
        }

        // ── Original scatter-out animation ──────────────────────────────────────
        if (isAnimatingScatterOut && startPositions && endPositions) {
          scatterOutAnimationTime += 0.016;
          const progress = Math.min(scatterOutAnimationTime / SCATTER_OUT_DURATION, 1.0);
          const ep = easeInOutCubic(progress);
          const posAttr = geometry.attributes.position as THREE.BufferAttribute;
          const positions = posAttr.array as Float32Array;
          const n = positions.length / 3;
          for (let i = 0; i < n; i++) {
            const idx = i * 3;
            const x = startPositions[idx], y = startPositions[idx + 1], z = startPositions[idx + 2];
            const dist = Math.sqrt(x * x + y * y + z * z);
            const dx = dist > 0.001 ? x / dist : 0;
            const dy = dist > 0.001 ? y / dist : 0;
            const dz = dist > 0.001 ? z / dist : 0;
            const sd = SCATTER_OUT_RADIUS + dist * 0.5;
            positions[idx]     = startPositions[idx]     + (dx * sd - startPositions[idx])     * ep;
            positions[idx + 1] = startPositions[idx + 1] + (dy * sd - startPositions[idx + 1]) * ep;
            positions[idx + 2] = startPositions[idx + 2] + (dz * sd - startPositions[idx + 2]) * ep;
          }
          posAttr.needsUpdate = true;
          if (progress >= 1.0) {
            isAnimatingScatterOut = false;
            startPositions = null;
            const pa = geometry.attributes.position as THREE.BufferAttribute;
            scatteredPositions = new Float32Array(pa.array as Float32Array);
            isAnimatingFadeOut = true;
            fadeOutAnimationTime = 0;
          }
        }

        // ── Original fade-out ────────────────────────────────────────────────────
        if (isAnimatingFadeOut && scatteredPositions) {
          fadeOutAnimationTime += 0.016;
          const fp = Math.min(fadeOutAnimationTime / SCATTER_OUT_FADE_DURATION, 1.0);
          setAlpha(1.0 - fp);
          const posAttr = geometry.attributes.position as THREE.BufferAttribute;
          const positions = posAttr.array as Float32Array;
          const n = positions.length / 3;
          for (let i = 0; i < n; i++) {
            const idx = i * 3;
            const x = scatteredPositions[idx], y = scatteredPositions[idx + 1], z = scatteredPositions[idx + 2];
            const dist = Math.sqrt(x * x + y * y + z * z);
            const dx = dist > 0.001 ? x / dist : 0;
            const dy = dist > 0.001 ? y / dist : 0;
            const dz = dist > 0.001 ? z / dist : 0;
            const add = dist * fp * 0.3;
            positions[idx]     = scatteredPositions[idx]     + (dx * (dist + add) - scatteredPositions[idx])     * fp;
            positions[idx + 1] = scatteredPositions[idx + 1] + (dy * (dist + add) - scatteredPositions[idx + 1]) * fp;
            positions[idx + 2] = scatteredPositions[idx + 2] + (dz * (dist + add) - scatteredPositions[idx + 2]) * fp;
          }
          posAttr.needsUpdate = true;
          if (fp >= 1.0) {
            isAnimatingFadeOut = false;
            hasScatteredOut    = true;
            scatteredPositions = null;
            const pa = geometry.attributes.position as THREE.BufferAttribute;
            const pos = pa.array as Float32Array;
            for (let i = 0; i < pos.length / 3; i++) {
              pos[i * 3] = pos[i * 3 + 1] = pos[i * 3 + 2] = 10000;
            }
            pa.needsUpdate = true;
          }
        }

        // ── Scatter-float animation ──────────────────────────────────────────────
        if (isAnimatingScatterFloat && scatterFloatStart && scatterFloatTarget) {
          scatterFloatTime += 0.016;
          const progress = Math.min(scatterFloatTime / SCATTER_FLOAT_DURATION, 1.0);
          const ep       = easeInOutCubic(progress);

          const posAttr  = geometry.attributes.position as THREE.BufferAttribute;
          const positions = posAttr.array as Float32Array;
          const n = positions.length / 3;

          for (let i = 0; i < n; i++) {
            const idx = i * 3;
            positions[idx]     = scatterFloatStart[idx]     + (scatterFloatTarget[idx]     - scatterFloatStart[idx])     * ep;
            positions[idx + 1] = scatterFloatStart[idx + 1] + (scatterFloatTarget[idx + 1] - scatterFloatStart[idx + 1]) * ep;
            positions[idx + 2] = scatterFloatStart[idx + 2] + (scatterFloatTarget[idx + 2] - scatterFloatStart[idx + 2]) * ep;
          }
          posAttr.needsUpdate = true;
          setAlpha(1.0);

          if (progress >= 1.0) {
            isAnimatingScatterFloat = false;
            scatterFloatStart = null;
            // Save resting positions for the float loop
            floatBasePositions = scatterFloatTarget!.slice();
            scatterFloatTarget = null;
            isFloating = true;
          }
        }

        // ── Floating (steady-state) ──────────────────────────────────────────────
        if (isFloating && floatBasePositions && floatSeeds) {
          const posAttr  = geometry.attributes.position as THREE.BufferAttribute;
          const positions = posAttr.array as Float32Array;
          const n = positions.length / 3;

          for (let i = 0; i < n; i++) {
            const idx  = i * 3;
            const seed = i * 6;
            positions[idx]     = floatBasePositions[idx]     + Math.sin(elapsedTime * floatSeeds[seed]     + floatSeeds[seed + 3]) * FLOAT_DRIFT_AMPLITUDE;
            positions[idx + 1] = floatBasePositions[idx + 1] + Math.sin(elapsedTime * floatSeeds[seed + 1] + floatSeeds[seed + 4]) * FLOAT_DRIFT_AMPLITUDE;
            positions[idx + 2] = floatBasePositions[idx + 2] + Math.sin(elapsedTime * floatSeeds[seed + 2] + floatSeeds[seed + 5]) * FLOAT_DRIFT_AMPLITUDE;
          }
          posAttr.needsUpdate = true;
          setAlpha(1.0);
        }

        // ── Float-reform animation ───────────────────────────────────────────────
        if (isAnimatingFloatReform && floatReformStart && endPositions) {
          floatReformTime += 0.016;
          const progress = Math.min(floatReformTime / FLOAT_REFORM_DURATION, 1.0);
          const ep       = easeInOutCubic(progress);

          const posAttr  = geometry.attributes.position as THREE.BufferAttribute;
          const positions = posAttr.array as Float32Array;
          const n = positions.length / 3;

          for (let i = 0; i < n; i++) {
            const idx = i * 3;
            positions[idx]     = floatReformStart[idx]     + (endPositions[idx]     - floatReformStart[idx])     * ep;
            positions[idx + 1] = floatReformStart[idx + 1] + (endPositions[idx + 1] - floatReformStart[idx + 1]) * ep;
            positions[idx + 2] = floatReformStart[idx + 2] + (endPositions[idx + 2] - floatReformStart[idx + 2]) * ep;
          }
          posAttr.needsUpdate = true;
          setAlpha(1.0);

          if (progress >= 1.0) {
            isAnimatingFloatReform = false;
            floatReformStart       = null;
            floatBasePositions     = null;
            floatSeeds             = null;
            // Snap exactly to model positions
            const pa = geometry.attributes.position as THREE.BufferAttribute;
            pa.array.set(endPositions);
            pa.needsUpdate = true;
            setAlpha(1.0);
          }
        }

        // ── Shader uniform updates ───────────────────────────────────────────────
        coreMaterial.uniforms.uTime.value = elapsedTime;
        glowMaterial.uniforms.uTime.value = elapsedTime;

        // Fade GPU-side drift back in after intro so idle motion resumes smoothly.
        let driftMix = 1.0;
        if (isSettlingAfterIntro) {
          introDriftFadeInTime += 0.016;
          const fadeProgress = Math.min(introDriftFadeInTime / INTRO_DRIFT_FADE_IN_DURATION, 1.0);
          driftMix = easeInOutCubic(fadeProgress);
          if (fadeProgress >= 1.0) {
            isSettlingAfterIntro = false;
          }
        }
        const driftDisabled = (isAnimatingIntro || isAnimatingScatterOut || isAnimatingFadeOut
                || isAnimatingReverseScatterIn || isAnimatingScatterFloat || isAnimatingFloatReform
                      || isFloating) ? 0.0 : 1.0;
        coreMaterial.uniforms.uDisableDrift.value = driftDisabled;
        glowMaterial.uniforms.uDisableDrift.value = driftDisabled;
        coreMaterial.uniforms.uDriftMix.value = driftDisabled > 0.5 ? driftMix : 0.0;
        glowMaterial.uniforms.uDriftMix.value = driftDisabled > 0.5 ? driftMix : 0.0;

        renderer.render(scene, camera);
      };

      // ── Fallback sphere ──────────────────────────────────────────────────────
      const buildFallbackSphere = () => {
        const COUNT  = 5_000;
        const RADIUS = 2.0;
        const finalPositions = new Float32Array(COUNT * 3);
        for (let i = 0; i < COUNT; i++) {
          const theta = Math.random() * Math.PI * 2;
          const phi   = Math.acos(2 * Math.random() - 1);
          const r     = RADIUS * (0.95 + Math.random() * 0.1);
          finalPositions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
          finalPositions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
          finalPositions[i * 3 + 2] = r * Math.cos(phi);
        }
        endPositions   = finalPositions;
        startPositions = generateScatteredPositions(COUNT);
        canonicalModelPositions = finalPositions.slice();
        modelPositions = finalPositions.slice();
        geometry.setAttribute('position', new THREE.BufferAttribute(startPositions.slice(), 3));
        assignColorsToGeometry(geometry, COUNT);
        isAnimatingIntro  = true;
        introAnimationTime = 0;
      };

      // ── Load model ────────────────────────────────────────────────────────────
      (async () => {
        try {
          const loader = new GLTFLoader();
          const gltf   = await loader.loadAsync(indexModelUrl);
          if (cancelled) return;

          const merged = mergePlantFromGltf(gltf.scene);
          normalizePlantGeometry(merged);

          const attr       = merged.attributes.position as THREE.BufferAttribute;
          const totalVerts = attr.count;

          if (totalVerts === 0) {
            merged.dispose();
            buildFallbackSphere();
          } else {
            const step          = Math.max(1, Math.floor(totalVerts / MAX_PARTICLES));
            const particleCount = Math.ceil(totalVerts / step);
            const finalPositions = new Float32Array(particleCount * 3);
            const src = attr.array as Float32Array;
            for (let i = 0, j = 0; j < particleCount; i += step, j++) {
              const si = Math.min(i, totalVerts - 1) * 3;
              finalPositions[j * 3]     = src[si];
              finalPositions[j * 3 + 1] = src[si + 1];
              finalPositions[j * 3 + 2] = src[si + 2];
            }
            merged.dispose();

            endPositions   = finalPositions;
            startPositions = generateScatteredPositions(particleCount);
            geometry.setAttribute('position', new THREE.BufferAttribute(startPositions.slice(), 3));
            assignColorsToGeometry(geometry, particleCount);
            isAnimatingIntro  = true;
            introAnimationTime = 0;
          }
        } catch {
          if (cancelled) return;
          buildFallbackSphere();
        }

        if (cancelled) return;
        animate();
      })();

      // ── Cleanup ───────────────────────────────────────────────────────────────
      return () => {
        cancelled = true;
        window.removeEventListener('resize', handleResize);
        document.removeEventListener('visibilitychange', handleVisibility);
        if (animationId !== null) cancelAnimationFrame(animationId);
        renderer.dispose();
        geometry.dispose();
        coreMaterial.dispose();
        glowMaterial.dispose();
        if (container.contains(renderer.domElement)) container.removeChild(renderer.domElement);
        if (container.contains(overlay))              container.removeChild(overlay);
      };
    }, [indexModelUrl]);

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
          background: '#0D001A',
        }}
      />
    );
  }
);

PlantParticlesBackground.displayName = 'PlantParticlesBackground';

export default PlantParticlesBackground;