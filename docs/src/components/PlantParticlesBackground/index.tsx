'use client';

import { useEffect, useMemo, useRef } from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const PLANT_MAX_EXTENT = 3.2;
const MAX_PARTICLES = 8_000;

const vertexShader = `
  uniform float uSize;
  uniform float uResolutionY;
  varying vec3 vPos;

  void main() {
    vPos = position;
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = uSize * uResolutionY * 0.0013 * (1.0 / -mvPosition.z);
    gl_Position = projectionMatrix * mvPosition;
  }
`;

// Sharp bright core of each particle
const coreFragmentShader = `
  varying vec3 vPos;

  void main() {
    float d = distance(gl_PointCoord, vec2(0.5));
    float strength = 0.05 / d - 0.1;
    vec3 color = vec3(0.0, 0.867, 1.0);
    gl_FragColor = vec4(color, strength * length(vPos));
  }
`;

// Large soft halo drawn on top of the core — simulates bloom without post-processing
const glowFragmentShader = `
  varying vec3 vPos;

  void main() {
    float d = distance(gl_PointCoord, vec2(0.5));
    if (d > 0.5) discard;
    float strength = pow(max(0.0, 1.0 - d * 2.0), 3.0) * 0.25;
    vec3 color = vec3(0.0, 0.867, 1.0);
    gl_FragColor = vec4(color, strength * clamp(length(vPos) * 0.6, 0.0, 1.0));
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
        uSize: { value: 12.0 },
        uResolutionY: { value: window.innerHeight },
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
        uSize: { value: 60.0 },
        uResolutionY: { value: window.innerHeight },
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
      coreParticles.rotation.y += 0.001;
      glowParticles.rotation.y = coreParticles.rotation.y;
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
