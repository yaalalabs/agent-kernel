'use client';

import { useEffect, useMemo, useRef } from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const PLANT_MAX_EXTENT = 3.0;
const MAX_PARTICLES = 7_000;
const PARTICLE_CORE_ALPHA = 0.48;
const PARTICLE_GLOW_ALPHA = 0.10;
const PARTICLE_OVERLAY_OPACITY = 0.10;
// Color palette
const PALETTE: [number, number, number][] = [
  [0.0, 221 / 255, 1.0], // #00DDFF (brand color)
  [0.0, 170 / 255, 222 / 255], // #00AADE (blue shade)
  [242 / 255, 0.0, 1.0], // #F200FF (accent)
];

const vertexShader = `
  attribute vec3 aColor;
  uniform float uSize;
  uniform float uResolutionY;
  uniform float uTime;
  varying vec3 vPos;
  varying vec3 vColor;

  void main() {
    vec3 pos = position;
    
    // Add individual particle movement based on position hash and time
    // Creates a subtle floating/drifting motion for each particle
    float hash = sin(pos.x * 12.9898 + pos.y * 78.233 + pos.z * 45.164) * 43758.5453;
    float frac_hash = fract(hash);
    
    // Each particle drifts in a subtle pattern (reduced movement)
    float drift_x = sin(uTime * 0.3 + frac_hash * 6.28) * 0.03;
    float drift_y = cos(uTime * 0.25 + frac_hash * 6.28) * 0.03;
    float drift_z = sin(uTime * 0.2 + frac_hash * 6.28) * 0.02;
    
    pos += vec3(drift_x, drift_y, drift_z);
    
    vPos = pos;
    vColor = aColor;
    vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
    gl_PointSize = uSize * uResolutionY * 0.0013 * (1.0 / -mvPosition.z);
    gl_Position = projectionMatrix * mvPosition;
  }
`;

// Sharp bright core of each particle
const coreFragmentShader = `
  varying vec3 vPos;
  varying vec3 vColor;

  void main() {
    float d = distance(gl_PointCoord, vec2(0.5));
    float strength = 0.05 / d - 0.1;
    vec3 color = vColor;
    gl_FragColor = vec4(color, strength * length(vPos) * ${PARTICLE_CORE_ALPHA.toFixed(2)});
  }
`;

// Large soft halo drawn on top of the core — simulates bloom without post-processing
const glowFragmentShader = `
  varying vec3 vPos;
  varying vec3 vColor;

  void main() {
    float d = distance(gl_PointCoord, vec2(0.5));
    if (d > 0.5) discard;
    float strength = pow(max(0.0, 1.0 - d * 2.0), 3.0) * 0.22;
    vec3 color = vColor;
    gl_FragColor = vec4(color, strength * clamp(length(vPos) * 0.5, 0.0, 1.0) * ${PARTICLE_GLOW_ALPHA.toFixed(2)});
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
    if (r < 0.6) idx = 0; // primary
    else if (r < 0.9) idx = 1; // blue shade
    else idx = 2; // accent
    const c = PALETTE[idx];
    colors[i * 3] = c[0];
    colors[i * 3 + 1] = c[1];
    colors[i * 3 + 2] = c[2];
  }
  geo.setAttribute('aColor', new THREE.BufferAttribute(colors, 3));
}

const PlantParticlesBackground = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const { siteConfig } = useDocusaurusContext();

  const plantModelUrl = useMemo(() => {
    const base = siteConfig.baseUrl.endsWith('/')
      ? siteConfig.baseUrl
      : `${siteConfig.baseUrl}/`;
    return `${base}models/plant.glb`;
  }, [siteConfig.baseUrl]);

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    let cancelled = false;
    let animationId: number | null = null;

    // Animation state
    let elapsedTime = 0;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 100);
    camera.position.z = 5;

    const pixelRatio = Math.min(window.devicePixelRatio, 1.5);

    const renderer = new THREE.WebGLRenderer({
      antialias: false,
      alpha: false,
      powerPreference: 'high-performance',
    });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(pixelRatio);
    renderer.setClearColor(0x0D001A, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(renderer.domElement);

    const geometry = new THREE.BufferGeometry();

    const coreMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uSize: { value: 22.5 },
        uResolutionY: { value: window.innerHeight },
        uTime: { value: 0 },
      },
      vertexShader,
      fragmentShader: coreFragmentShader,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    // Halo is ~5× larger and uses a smooth cubic falloff to mimic a bloom halo
    const glowMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uSize: { value: 92.0 },
        uResolutionY: { value: window.innerHeight },
        uTime: { value: 0 },
      },
      vertexShader,
      fragmentShader: glowFragmentShader,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    const coreParticles = new THREE.Points(geometry, coreMaterial);
    const glowParticles = new THREE.Points(geometry, glowMaterial);
    scene.add(glowParticles); // draw halo first (behind core)
    scene.add(coreParticles);

    const overlay = document.createElement('div');
    overlay.style.position = 'absolute';
    overlay.style.inset = '0';
    overlay.style.pointerEvents = 'none';
    overlay.style.background = `linear-gradient(180deg, rgba(13, 0, 26, 0.08) 0%, rgba(13, 0, 26, ${PARTICLE_OVERLAY_OPACITY}) 100%)`;
    overlay.style.mixBlendMode = 'multiply';
    container.appendChild(overlay);

    const handleResize = () => {
      const pr = Math.min(window.devicePixelRatio, 1.5);
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
      renderer.setPixelRatio(pr);
      (coreMaterial.uniforms.uResolutionY as THREE.IUniform<number>).value = window.innerHeight;
      (glowMaterial.uniforms.uResolutionY as THREE.IUniform<number>).value = window.innerHeight;
    };
    window.addEventListener('resize', handleResize);

    // Pause the RAF loop when the tab is hidden, resume when visible
    const handleVisibility = () => {
      if (document.hidden) {
        if (animationId !== null) {
          cancelAnimationFrame(animationId);
          animationId = null;
        }
      } else if (!cancelled) {
        animationId = requestAnimationFrame(animate);
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    const animate = () => {
      if (cancelled) return;
      animationId = requestAnimationFrame(animate);
      elapsedTime += 0.016;

      // Constant rotation speed
      const rotationSpeed = 0.001;

      // Apply rotation
      coreParticles.rotation.y += rotationSpeed;
      glowParticles.rotation.y = coreParticles.rotation.y;

      // Update time uniform for particle shader animations
      (coreMaterial.uniforms.uTime as THREE.IUniform<number>).value = elapsedTime;
      (glowMaterial.uniforms.uTime as THREE.IUniform<number>).value = elapsedTime;

      renderer.render(scene, camera);
    };

    const buildFallbackSphere = () => {
      const COUNT = 5_000;
      const RADIUS = 2.0;
      const positions = new Float32Array(COUNT * 3);
      for (let i = 0; i < COUNT; i++) {
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        const r = RADIUS * (0.95 + Math.random() * 0.1);
        positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
        positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
        positions[i * 3 + 2] = r * Math.cos(phi);
      }
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      assignColorsToGeometry(geometry, COUNT);
    };

    (async () => {
      try {
        const loader = new GLTFLoader();
        const gltf = await loader.loadAsync(plantModelUrl);
        if (cancelled) return;

        const merged = mergePlantFromGltf(gltf.scene);
        normalizePlantGeometry(merged);

        const attr = merged.attributes.position as THREE.BufferAttribute;
        const totalVerts = attr.count;

        if (totalVerts === 0) {
          merged.dispose();
          buildFallbackSphere();
        } else {
          const step = Math.max(1, Math.floor(totalVerts / MAX_PARTICLES));
          const particleCount = Math.ceil(totalVerts / step);
          const positions = new Float32Array(particleCount * 3);
          const src = attr.array as Float32Array;
          for (let i = 0, j = 0; j < particleCount; i += step, j++) {
            const si = Math.min(i, totalVerts - 1) * 3;
            positions[j * 3] = src[si];
            positions[j * 3 + 1] = src[si + 1];
            positions[j * 3 + 2] = src[si + 2];
          }
          merged.dispose();
          geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
          assignColorsToGeometry(geometry, particleCount);
        }
      } catch {
        if (cancelled) return;
        buildFallbackSphere();
      }

      if (cancelled) return;
      animate();
    })();

    return () => {
      cancelled = true;
      window.removeEventListener('resize', handleResize);
      document.removeEventListener('visibilitychange', handleVisibility);
      if (animationId !== null) cancelAnimationFrame(animationId);
      renderer.dispose();
      geometry.dispose();
      coreMaterial.dispose();
      glowMaterial.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      if (container.contains(overlay)) {
        container.removeChild(overlay);
      }
    };
  }, [plantModelUrl]);

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
};

export default PlantParticlesBackground;
