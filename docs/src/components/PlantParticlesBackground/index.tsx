'use client';

import { useEffect, useMemo, useRef, forwardRef, useImperativeHandle } from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const PLANT_MAX_EXTENT = 2.8;
const MAX_PARTICLES = 2_000;
const PARTICLE_CORE_ALPHA = 0.18;
const PARTICLE_GLOW_ALPHA = 0.12;
const PARTICLE_OVERLAY_OPACITY = 0.12;
const INTRO_ANIMATION_DURATION = 2.0; // seconds
const INTRO_ANIMATION_SCATTER_RADIUS = 6.0; // how far particles scatter initially
const SCATTER_OUT_DELAY = 3.5; // delay before scattering out (after intro completes)
const SCATTER_OUT_DURATION = 3.5; // duration of scatter out animation
const SCATTER_OUT_FADE_DURATION = 1.0; // duration of fade out after scatter completes
const SCATTER_OUT_RADIUS = 8.0; // how far particles scatter outward
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
  uniform float uDisableDrift;
  varying vec3 vPos;
  varying vec3 vColor;

  void main() {
    vec3 pos = position;
    
    // Add individual particle movement based on position hash and time
    // Creates a subtle floating/drifting motion for each particle
    // Only apply when animations are not active (uDisableDrift = 1.0)
    if (uDisableDrift > 0.5) {
      float hash = sin(pos.x * 12.9898 + pos.y * 78.233 + pos.z * 45.164) * 43758.5453;
      float frac_hash = fract(hash);
      
      // Each particle drifts in a subtle pattern (reduced movement)
      float drift_x = sin(uTime * 0.3 + frac_hash * 6.28) * 0.03;
      float drift_y = cos(uTime * 0.25 + frac_hash * 6.28) * 0.03;
      float drift_z = sin(uTime * 0.2 + frac_hash * 6.28) * 0.02;
      
      pos += vec3(drift_x, drift_y, drift_z);
    }
    
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
  uniform float uAlpha;

  void main() {
    float d = distance(gl_PointCoord, vec2(0.5));
    float strength = 0.05 / d - 0.1;
    vec3 color = vColor;
    gl_FragColor = vec4(color, strength * length(vPos) * ${PARTICLE_CORE_ALPHA.toFixed(2)} * uAlpha);
  }
`;

// Large soft halo drawn on top of the core — simulates bloom without post-processing
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

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

const PlantParticlesBackground = forwardRef<{ triggerScatterOut: () => void; triggerScatterIn: () => void }>(
  (_, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const { siteConfig } = useDocusaurusContext();
    const triggerScatterOutRef = useRef<() => void>(() => {});
    const triggerScatterInRef = useRef<() => void>(() => {});

    useImperativeHandle(ref, () => ({
      triggerScatterOut: () => triggerScatterOutRef.current(),
      triggerScatterIn: () => triggerScatterInRef.current(),
    }));

    const indexModelUrl = useMemo(() => {
      const base = siteConfig.baseUrl.endsWith('/')
        ? siteConfig.baseUrl
        : `${siteConfig.baseUrl}/`;
      return `${base}models/index.glb`;
    }, [siteConfig.baseUrl]);

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    let cancelled = false;
    let animationId: number | null = null;

    // Animation state
    let elapsedTime = 0;
    let isAnimatingIntro = false;
    let introAnimationTime = 0;
    let startPositions: Float32Array | null = null;
    let endPositions: Float32Array | null = null;
    let isAnimatingScatterOut = false;
    let scatterOutAnimationTime = 0;
    let scatterOutStartTime = 0;
    let modelPositions: Float32Array | null = null;
    let hasScatteredOut = false; // Track if scatter out has completed
    let shouldTriggerScatterOut = false; // Track external trigger
    let isAnimatingFadeOut = false; // Track fade-out phase
    let fadeOutAnimationTime = 0;
    let scatteredPositions: Float32Array | null = null; // Save positions at end of scatter-out
    let shouldTriggerScatterIn = false; // Track external trigger for scatter-in reset
    let hasScatteredIn = true; // Initialize to true - only allow scatter-in after scatter-out has happened

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

    // Expose scatter out trigger
    triggerScatterOutRef.current = () => {
      shouldTriggerScatterOut = true;
    };

    // Expose scatter in trigger (to reset animation when scrolling back)
    triggerScatterInRef.current = () => {
      shouldTriggerScatterIn = true;
    };

    const geometry = new THREE.BufferGeometry();

    const coreMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uSize: { value: 160.0 },
        uResolutionY: { value: window.innerHeight },
        uTime: { value: 0 },
        uAlpha: { value: 1.0 },
        uDisableDrift: { value: 0.0 },
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
        uSize: { value: 200.0 },
        uResolutionY: { value: window.innerHeight },
        uTime: { value: 0 },
        uAlpha: { value: 1.0 },
        uDisableDrift: { value: 0.0 },
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

      // Constant rotation speed - only apply after intro animation completes
      const rotationSpeed = 0.001;

      // Apply rotation only when not animating intro, scatter-out, or fade-out
      if (!isAnimatingIntro && !isAnimatingScatterOut && !isAnimatingFadeOut) {
        coreParticles.rotation.y += rotationSpeed;
        glowParticles.rotation.y = coreParticles.rotation.y;
      }

      // Handle intro animation - particles collecting into shape
      if (isAnimatingIntro && startPositions && endPositions) {
        introAnimationTime += 0.016;
        const progress = Math.min(introAnimationTime / INTRO_ANIMATION_DURATION, 1.0);
        const easedProgress = easeInOutCubic(progress);

        // Interpolate positions from scattered to model shape
        const posAttr = geometry.attributes.position as THREE.BufferAttribute;
        const positions = posAttr.array as Float32Array;
        const positionCount = positions.length / 3;

        for (let i = 0; i < positionCount; i++) {
          const startIdx = i * 3;
          const endIdx = i * 3;
          positions[startIdx] = startPositions[startIdx] + (endPositions[endIdx] - startPositions[startIdx]) * easedProgress;
          positions[startIdx + 1] = startPositions[startIdx + 1] + (endPositions[endIdx + 1] - startPositions[startIdx + 1]) * easedProgress;
          positions[startIdx + 2] = startPositions[startIdx + 2] + (endPositions[endIdx + 2] - startPositions[startIdx + 2]) * easedProgress;
        }
        posAttr.needsUpdate = true;

        // Fade in particles during intro animation
        const fadeInAlpha = easedProgress;
        (coreMaterial.uniforms.uAlpha as THREE.IUniform<number>).value = fadeInAlpha;
        (glowMaterial.uniforms.uAlpha as THREE.IUniform<number>).value = fadeInAlpha;

        // Stop intro animation when complete
        if (progress >= 1.0) {
          isAnimatingIntro = false;
          startPositions = null;
          // Ensure alpha is at full opacity
          (coreMaterial.uniforms.uAlpha as THREE.IUniform<number>).value = 1.0;
          (glowMaterial.uniforms.uAlpha as THREE.IUniform<number>).value = 1.0;
          // Ensure geometry is exactly at endPositions for clean scatter-out
          const posAttr = geometry.attributes.position as THREE.BufferAttribute;
          posAttr.array.set(endPositions);
          posAttr.needsUpdate = true;
          // Save model positions as a proper copy
          modelPositions = endPositions.slice();
        }
      }

      // Handle external trigger for scatter in (when user scrolls back to hero)
      if (shouldTriggerScatterIn && !hasScatteredIn && modelPositions && endPositions) {
        shouldTriggerScatterIn = false;
        hasScatteredIn = true; // Prevent repeat triggers
        // Reset animation states to allow intro animation to play again
        isAnimatingScatterOut = false;
        isAnimatingFadeOut = false;
        hasScatteredOut = false;
        fadeOutAnimationTime = 0;
        scatterOutAnimationTime = 0;
        // Set positions back to scattered state
        startPositions = generateScatteredPositions(endPositions.length / 3);
        const posAttr = geometry.attributes.position as THREE.BufferAttribute;
        posAttr.array = startPositions.slice();
        posAttr.needsUpdate = true;
        // Reset alpha to full visibility for the scatter-in animation
        (coreMaterial.uniforms.uAlpha as THREE.IUniform<number>).value = 0.0;
        (glowMaterial.uniforms.uAlpha as THREE.IUniform<number>).value = 0.0;
        // Begin intro animation
        isAnimatingIntro = true;
        introAnimationTime = 0;
      }

      // Handle external trigger for scatter out (from scroll to Levels section)
      if (shouldTriggerScatterOut && !isAnimatingScatterOut && !hasScatteredOut && modelPositions && endPositions) {
        isAnimatingScatterOut = true;
        scatterOutAnimationTime = 0;
        startPositions = modelPositions.slice();
        shouldTriggerScatterOut = false;
        hasScatteredIn = false; // Reset so scatter-in can happen again after scatter-out
      }

      if (isAnimatingScatterOut && startPositions && endPositions) {
        scatterOutAnimationTime += 0.016;
        const progress = Math.min(scatterOutAnimationTime / SCATTER_OUT_DURATION, 1.0);
        const easedProgress = easeInOutCubic(progress);

        // Generate scatter-out positions based on model positions
        const posAttr = geometry.attributes.position as THREE.BufferAttribute;
        const positions = posAttr.array as Float32Array;
        const positionCount = positions.length / 3;

        for (let i = 0; i < positionCount; i++) {
          const idx = i * 3;
          const x = startPositions[idx];
          const y = startPositions[idx + 1];
          const z = startPositions[idx + 2];
          
          // Normalize direction from center
          const distance = Math.sqrt(x * x + y * y + z * z);
          const dirX = distance > 0.001 ? x / distance : 0;
          const dirY = distance > 0.001 ? y / distance : 0;
          const dirZ = distance > 0.001 ? z / distance : 0;
          
          // Scatter further out
          const scatterDistance = SCATTER_OUT_RADIUS + (distance * 0.5);
          const endX = dirX * scatterDistance;
          const endY = dirY * scatterDistance;
          const endZ = dirZ * scatterDistance;
          
          positions[idx] = startPositions[idx] + (endX - startPositions[idx]) * easedProgress;
          positions[idx + 1] = startPositions[idx + 1] + (endY - startPositions[idx + 1]) * easedProgress;
          positions[idx + 2] = startPositions[idx + 2] + (endZ - startPositions[idx + 2]) * easedProgress;
        }
        posAttr.needsUpdate = true;

        // Stop scatter-out animation when complete
        if (progress >= 1.0) {
          isAnimatingScatterOut = false;
          startPositions = null;
          // Save scattered positions for fade-out phase
          const posAttr = geometry.attributes.position as THREE.BufferAttribute;
          scatteredPositions = new Float32Array(posAttr.array as Float32Array);
          // Start fade-out phase instead of immediately hiding
          isAnimatingFadeOut = true;
          fadeOutAnimationTime = 0;
        }
      }

      // Handle fade-out animation - particles fade and continue moving out
      if (isAnimatingFadeOut && scatteredPositions) {
        fadeOutAnimationTime += 0.016;
        const fadeProgress = Math.min(fadeOutAnimationTime / SCATTER_OUT_FADE_DURATION, 1.0);
        const fadedAlpha = 1.0 - fadeProgress;

        // Update alpha for smooth disappearance
        (coreMaterial.uniforms.uAlpha as THREE.IUniform<number>).value = fadedAlpha;
        (glowMaterial.uniforms.uAlpha as THREE.IUniform<number>).value = fadedAlpha;

        // Continue moving particles outward during fade from their current scattered positions
        const posAttr = geometry.attributes.position as THREE.BufferAttribute;
        const positions = posAttr.array as Float32Array;
        const positionCount = positions.length / 3;

        for (let i = 0; i < positionCount; i++) {
          const idx = i * 3;
          const x = scatteredPositions[idx];
          const y = scatteredPositions[idx + 1];
          const z = scatteredPositions[idx + 2];
          
          // Normalize direction from center
          const distance = Math.sqrt(x * x + y * y + z * z);
          const dirX = distance > 0.001 ? x / distance : 0;
          const dirY = distance > 0.001 ? y / distance : 0;
          const dirZ = distance > 0.001 ? z / distance : 0;
          
          // Slight acceleration outward during fade
          const additionalDistance = distance * fadeProgress * 0.3;
          const endX = dirX * (distance + additionalDistance);
          const endY = dirY * (distance + additionalDistance);
          const endZ = dirZ * (distance + additionalDistance);
          
          positions[idx] = scatteredPositions[idx] + (endX - scatteredPositions[idx]) * fadeProgress;
          positions[idx + 1] = scatteredPositions[idx + 1] + (endY - scatteredPositions[idx + 1]) * fadeProgress;
          positions[idx + 2] = scatteredPositions[idx + 2] + (endZ - scatteredPositions[idx + 2]) * fadeProgress;
        }
        posAttr.needsUpdate = true;

        // Complete fade-out and move particles out of bounds
        if (fadeProgress >= 1.0) {
          isAnimatingFadeOut = false;
          hasScatteredOut = true;
          scatteredPositions = null;
          
          // Move particles far out of bounds
          const posAttr = geometry.attributes.position as THREE.BufferAttribute;
          const positions = posAttr.array as Float32Array;
          const positionCount = positions.length / 3;
          
          for (let i = 0; i < positionCount; i++) {
            const idx = i * 3;
            positions[idx] = 10000;
            positions[idx + 1] = 10000;
            positions[idx + 2] = 10000;
          }
          posAttr.needsUpdate = true;
        }
      }

      // Update time uniform for particle shader animations
      (coreMaterial.uniforms.uTime as THREE.IUniform<number>).value = elapsedTime;
      (glowMaterial.uniforms.uTime as THREE.IUniform<number>).value = elapsedTime;

      // Control drift: disable during scatter-out and fade-out, enable for intro animation
      const isDriftDisabled = isAnimatingScatterOut || isAnimatingFadeOut ? 0.0 : 1.0;
      (coreMaterial.uniforms.uDisableDrift as THREE.IUniform<number>).value = isDriftDisabled;
      (glowMaterial.uniforms.uDisableDrift as THREE.IUniform<number>).value = isDriftDisabled;

      renderer.render(scene, camera);
    };

    const buildFallbackSphere = () => {
      const COUNT = 5_000;
      const RADIUS = 2.0;
      const finalPositions = new Float32Array(COUNT * 3);
      for (let i = 0; i < COUNT; i++) {
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        const r = RADIUS * (0.95 + Math.random() * 0.1);
        finalPositions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
        finalPositions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
        finalPositions[i * 3 + 2] = r * Math.cos(phi);
      }
      
      // Setup intro animation for fallback
      endPositions = finalPositions;
      startPositions = generateScatteredPositions(COUNT);
      
      geometry.setAttribute('position', new THREE.BufferAttribute(startPositions.slice(), 3));
      assignColorsToGeometry(geometry, COUNT);
      
      // Begin intro animation
      isAnimatingIntro = true;
      introAnimationTime = 0;
    };

    (async () => {
      try {
        const loader = new GLTFLoader();
        const gltf = await loader.loadAsync(indexModelUrl);
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
          const finalPositions = new Float32Array(particleCount * 3);
          const src = attr.array as Float32Array;
          for (let i = 0, j = 0; j < particleCount; i += step, j++) {
            const si = Math.min(i, totalVerts - 1) * 3;
            finalPositions[j * 3] = src[si];
            finalPositions[j * 3 + 1] = src[si + 1];
            finalPositions[j * 3 + 2] = src[si + 2];
          }
          merged.dispose();

          // Setup intro animation
          endPositions = finalPositions;
          startPositions = generateScatteredPositions(particleCount);
          
          // Start with scattered positions
          geometry.setAttribute('position', new THREE.BufferAttribute(startPositions.slice(), 3));
          assignColorsToGeometry(geometry, particleCount);
          
          // Begin intro animation
          isAnimatingIntro = true;
          introAnimationTime = 0;
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
});

PlantParticlesBackground.displayName = 'PlantParticlesBackground';

export default PlantParticlesBackground;
