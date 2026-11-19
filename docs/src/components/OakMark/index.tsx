import React, { useEffect, useId, useRef } from 'react';
import { onThemeChange, themeChannels } from '@site/src/lib/brand';
import clsx from 'clsx';
import styles from './styles.module.css';

type OakMarkProps = {
  /** `hero` is the particle rendition; `hub` and `cta` are the flat mark with a glow. */
  variant?: 'hero' | 'hub' | 'cta';
  /** Set to false for a static mark. Reduced-motion users always get the static mark. */
  animated?: boolean;
  className?: string;
};

// The two halves of the Open Agent Kernel mark (branding/logo-mark, viewBox 0 0 86.86 86.85).
const LEFT =
  'M19.74,39.48v15.79l12.48,5.06c4.39,1.76,7.26,6.01,7.26,10.73v15.79l-27.78-11.11c-7.07-2.83-11.7-9.67-11.7-17.27V0l27.79,11.11c7.06,2.83,11.69,9.67,11.69,17.27v19.07L19.74,39.48Z';
const RIGHT =
  'M86.86,0v58.47c0,7.6-4.64,14.44-11.7,17.27l-27.78,11.11v-23.69c0-4.72,2.87-8.97,7.26-10.73l12.48-5.06v-15.79l-19.74,7.97v-11.17c0-7.6,4.63-14.44,11.69-17.27L86.86,0Z';

function useSafeId(prefix: string): string {
  return `${prefix}-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
}

/* ── Flat mark: diagram hubs and calls to action ─────────────────────────── */

function FlatMark({ variant, animated, className }: Required<Pick<OakMarkProps, 'variant' | 'animated'>> & { className?: string }): JSX.Element {
  const gradientId = useSafeId('oak-mark');
  return (
    <div className={clsx(styles.root, styles[variant], animated && styles.animated, className)} aria-hidden="true">
      <div className={styles.glow} />
      <svg className={styles.svg} viewBox="-4 -4 94.86 94.85" focusable="false">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--ak-primary)" />
            <stop offset="100%" stopColor="var(--ak-primary-soft)" />
          </linearGradient>
        </defs>
        <g className={styles.fill} fill={`url(#${gradientId})`}>
          <path d={LEFT} />
          <path d={RIGHT} />
        </g>
        <g className={styles.outline}>
          <path d={LEFT} pathLength={1} />
          <path d={RIGHT} pathLength={1} />
        </g>
      </svg>
    </div>
  );
}

/* ── Hero: the mark formed from particles ────────────────────────────────── */

const MARK_SIZE = 86.86; // the mark's viewBox edge, in path units

type Particle = {
  hx: number; hy: number; // home, in path units (dust: polar angle and radius factor)
  x: number; y: number; vx: number; vy: number; // position and velocity, in CSS pixels
  r: number; alpha: number; phase: number; speed: number; wobble: number;
  delay: number; // seconds before the particle starts travelling home
  kind: 0 | 1 | 2; // 0 body, 1 outline, 2 ambient dust
  tone: number; // index into the colour table
};

/** Small deterministic generator, so every visit sees the same arrangement. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Orange tones across the mark, light at the top left to soft at the bottom right.
const ORANGE_TONES = ['255, 132, 96', '255, 110, 70', '255, 94, 50', '247, 120, 78', '245, 138, 94'];

function ParticleMark({ animated, className }: { animated: boolean; className?: string }): JSX.Element {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pathRef = useRef<SVGPathElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    const canvas = canvasRef.current;
    const pathEl = pathRef.current;
    const ctx = canvas?.getContext('2d');
    if (!host || !canvas || !pathEl || !ctx) return undefined;

    const still = !animated || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const rnd = mulberry32(20261119);
    const compact = host.clientWidth < 520;
    const counts = compact ? { body: 1300, outline: 620, dust: 36 } : { body: 2700, outline: 1150, dust: 90 };

    // Sample the mark: points inside the two halves, and points along their outlines.
    const scratch = document.createElement('canvas').getContext('2d');
    const halves = [new Path2D(LEFT), new Path2D(RIGHT)];
    const inside = (x: number, y: number) => !!scratch && halves.some((half) => scratch.isPointInPath(half, x, y));
    const particles: Particle[] = [];
    const make = (hx: number, hy: number, kind: 0 | 1 | 2): Particle => ({
      hx, hy, x: 0, y: 0, vx: 0, vy: 0,
      r: kind === 1 ? 0.7 + rnd() * 0.75 : kind === 0 ? 0.45 + rnd() * 0.8 : 0.5 + rnd() * 0.9,
      alpha: kind === 1 ? 0.7 + rnd() * 0.3 : kind === 0 ? 0.28 + rnd() * 0.5 : 0.12 + rnd() * 0.3,
      phase: rnd() * Math.PI * 2, speed: 0.5 + rnd() * 1.1, wobble: kind === 1 ? 0.35 + rnd() * 0.5 : 0.6 + rnd() * 1.3,
      delay: rnd() * 0.9, kind,
      tone: kind === 2 || rnd() < 0.06 ? -1 : Math.min(ORANGE_TONES.length - 1, Math.floor(((hx + hy) / (2 * MARK_SIZE)) * ORANGE_TONES.length + rnd() * 0.9)),
    });
    let guard = 0;
    while (particles.length < counts.body && guard++ < counts.body * 12) {
      const x = rnd() * MARK_SIZE;
      const y = rnd() * MARK_SIZE;
      if (inside(x, y)) particles.push(make(x, y, 0));
    }
    for (const d of [LEFT, RIGHT]) {
      pathEl.setAttribute('d', d);
      const length = pathEl.getTotalLength();
      const n = Math.round(counts.outline / 2);
      for (let i = 0; i < n; i++) {
        const point = pathEl.getPointAtLength(((i + rnd()) / n) * length);
        particles.push(make(point.x + (rnd() - 0.5) * 0.5, point.y + (rnd() - 0.5) * 0.5, 1));
      }
    }
    for (let i = 0; i < counts.dust; i++) particles.push(make(rnd() * Math.PI * 2, 0.66 + rnd() * 0.62, 2));

    // Layout: the canvas fills the host; the mark sits in the middle.
    let width = 0, height = 0, scale = 1, originX = 0, originY = 0, markPx = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let dark = document.documentElement.getAttribute('data-theme') !== 'light';
    let ambient = themeChannels('blue');
    const homeOf = (p: Particle, time: number): [number, number] => {
      if (p.kind === 2) {
        const angle = p.hx + time * 0.035 * p.speed;
        return [width / 2 + Math.cos(angle) * markPx * p.hy, height / 2 + Math.sin(angle) * markPx * p.hy * 0.86];
      }
      return [originX + p.hx * scale, originY + p.hy * scale];
    };
    const layout = (scatter: boolean) => {
      width = host.clientWidth; height = host.clientHeight;
      canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
      markPx = Math.min(Math.min(width, height) * 0.56, 400);
      scale = markPx / MARK_SIZE; originX = (width - markPx) / 2; originY = (height - markPx) / 2;
      for (const p of particles) {
        const [hx, hy] = homeOf(p, 0);
        if (scatter && p.kind !== 2) {
          // start on a wide ring, with a little sideways motion so the particles curve in
          const angle = rnd() * Math.PI * 2;
          const radius = markPx * (0.75 + rnd() * 1.05);
          p.x = width / 2 + Math.cos(angle) * radius; p.y = height / 2 + Math.sin(angle) * radius;
          p.vx = -Math.sin(angle) * (1.5 + rnd() * 2.5); p.vy = Math.cos(angle) * (1.5 + rnd() * 2.5);
        } else { p.x = hx; p.y = hy; p.vx = 0; p.vy = 0; }
      }
    };

    const pointer = { x: 0, y: 0, active: false };
    let shiftX = 0, shiftY = 0;
    const draw = (time: number, step: number) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.globalCompositeOperation = dark ? 'lighter' : 'source-over';
      // the whole mark eases a few pixels toward the pointer
      const wantX = pointer.active ? (pointer.x - width / 2) * 0.018 : 0;
      const wantY = pointer.active ? (pointer.y - height / 2) * 0.018 : 0;
      shiftX += (wantX - shiftX) * 0.05; shiftY += (wantY - shiftY) * 0.05;
      const reach = markPx * 0.3;
      let style = '';
      for (const p of particles) {
        const [hx, hy] = homeOf(p, time);
        if (step > 0) {
          if (time >= p.delay) {
            const tx = hx + shiftX + Math.sin(time * p.speed + p.phase) * p.wobble;
            const ty = hy + shiftY + Math.cos(time * p.speed * 0.8 + p.phase * 1.3) * p.wobble;
            p.vx += (tx - p.x) * 0.042 * step; p.vy += (ty - p.y) * 0.042 * step;
            if (pointer.active && p.kind !== 2) {
              const dx = p.x - pointer.x, dy = p.y - pointer.y;
              const dist = Math.hypot(dx, dy);
              if (dist < reach && dist > 0.01) {
                const push = (1 - dist / reach) ** 2 * 2.4 * step;
                p.vx += (dx / dist) * push; p.vy += (dy / dist) * push;
              }
            }
          }
          const damping = Math.pow(0.86, step);
          p.vx *= damping; p.vy *= damping;
          p.x += p.vx * step; p.y += p.vy * step;
        }
        const fadeIn = still ? 1 : Math.min(1, Math.max(0, (time - p.delay * 0.6) / 0.9));
        const twinkle = still ? 1 : 0.78 + 0.22 * Math.sin(time * (0.9 + p.speed) + p.phase);
        const alpha = p.alpha * fadeIn * twinkle * (dark ? 1 : 1.25);
        if (alpha <= 0.01) continue;
        const next = `rgba(${p.tone < 0 ? ambient : ORANGE_TONES[p.tone]}, ${Math.min(1, alpha).toFixed(3)})`;
        if (next !== style) { ctx.fillStyle = next; style = next; }
        ctx.fillRect(p.x - p.r, p.y - p.r, p.r * 2, p.r * 2);
      }
    };

    let frame = 0, last = 0, start = 0, visible = true;
    const tick = (now: number) => {
      if (!start) { start = now; last = now; }
      const step = Math.min(2.5, (now - last) / 16.67);
      last = now;
      draw((now - start) / 1000, step);
      if (visible) frame = requestAnimationFrame(tick);
    };
    const redrawStill = () => draw(10, 0);

    layout(!still);
    if (still) redrawStill(); else frame = requestAnimationFrame(tick);

    const resize = new ResizeObserver(() => { layout(false); if (still) redrawStill(); });
    resize.observe(host);
    const seen = new IntersectionObserver(([entry]) => {
      const was = visible; visible = entry.isIntersecting;
      if (!still && visible && !was) { last = 0; start = start || 0; frame = requestAnimationFrame((now) => { last = now; tick(now); }); }
    });
    seen.observe(host);
    const stopTheme = onThemeChange(() => {
      dark = document.documentElement.getAttribute('data-theme') !== 'light';
      ambient = themeChannels('blue');
      if (still) redrawStill();
    });

    const section = host.closest('section') ?? host;
    const onMove = (event: PointerEvent) => {
      const box = canvas.getBoundingClientRect();
      pointer.x = event.clientX - box.left; pointer.y = event.clientY - box.top; pointer.active = true;
    };
    const onLeave = () => { pointer.active = false; };
    if (!still) {
      section.addEventListener('pointermove', onMove);
      section.addEventListener('pointerleave', onLeave);
    }
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect(); seen.disconnect(); stopTheme();
      section.removeEventListener('pointermove', onMove);
      section.removeEventListener('pointerleave', onLeave);
    };
  }, [animated]);

  return (
    <div ref={hostRef} className={clsx(styles.particles, className)} aria-hidden="true">
      <div className={styles.particlesGlow} />
      <canvas ref={canvasRef} className={styles.particlesCanvas} />
      <svg width="0" height="0" className={styles.measure} focusable="false">
        <path ref={pathRef} />
      </svg>
    </div>
  );
}

/**
 * The brand mark, drawn in code. The hero variant forms the mark from particles: they drift in
 * and settle into its shape, shimmer, and part around the pointer. It replaces the hero video.
 * The other variants are the flat mark, used in diagram hubs and calls to action.
 */
export default function OakMark({ variant = 'hero', animated = true, className }: OakMarkProps): JSX.Element {
  if (variant === 'hero') {
    return <ParticleMark animated={animated} className={className} />;
  }
  return <FlatMark variant={variant} animated={animated} className={className} />;
}
