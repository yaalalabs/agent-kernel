import React, { useState, useEffect, useRef } from 'react';
import styles from './styles.module.css';
import {
  MdSwapHoriz,
  MdMemory,
  MdSettings,
  MdVisibility,
  MdSecurity,
  MdMessage,
} from 'react-icons/md';
import { FaAws, FaDocker } from 'react-icons/fa';
import { FaMicrosoft } from 'react-icons/fa';

/* ─── Data ───────────────────────────────────────────────────────────────── */

const capabilityModules = [
  { id: 'adapters',   label: 'Framework Adapters', icon: <MdSwapHoriz /> },
  { id: 'memory',     label: 'Session & Memory',   icon: <MdMemory /> },
  { id: 'hooks',      label: 'Execution Hooks',    icon: <MdSettings /> },
  { id: 'messaging',  label: 'Messaging',          icon: <MdMessage /> },
  { id: 'observ',     label: 'Observability',      icon: <MdVisibility /> },
  { id: 'guardrails', label: 'Guardrails',         icon: <MdSecurity /> },
];

const deployTargets = [
  { id: 'lambda',    label: 'AWS Lambda',       icon: <FaAws /> },
  { id: 'ecs',       label: 'AWS ECS',          icon: <FaAws /> },
  { id: 'azfunc',    label: 'Azure Functions',  icon: <FaMicrosoft /> },
  { id: 'azapp',     label: 'Container Apps',   icon: <FaMicrosoft /> },
  { id: 'docker',    label: 'Docker',           icon: <FaDocker /> },
];

/*
 * SVG overlay only handles two simple connectors:
 *   1. Top connector:  Your Code box bottom → hub card top  (~36px gap)
 *   2. Fan connector:  hub card bottom → each deploy box top (~44px gap)
 *
 * The SVG is placed between rows as narrow strips so coordinate alignment is exact.
 * No coordinate ambiguity — each SVG strip is only as tall as the gap it fills.
 */

// 5 deploy targets; their x-center positions spread across 900px
const DEPLOY_X = [90, 225, 450, 675, 810];

/* ─── Component ─────────────────────────────────────────────────────────── */

export default function AgentKernelArchDiagram() {
  const sectionRef = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setVisible(true);
      return;
    }
    const el = sectionRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.1 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const reducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  return (
    <section ref={sectionRef} className={styles.archSection} aria-label="Agent Kernel architecture overview">
      <div className="container">
        <div className={styles.header}>
          <h2 className={styles.title}>How Agent Kernel Fits In</h2>
          <p className={styles.subtitle}>
            A thin, production-ready runtime between your agent logic and the cloud —
            handling everything except what makes your agents unique.
          </p>
        </div>

        <div className={styles.diagram}>

          {/* ── Layer 1: Your Agent Logic ── */}
          <div
            className={`${styles.topBox} ${visible ? styles.layerIn : ''}`}
            style={{ '--layer-delay': '0ms' } as React.CSSProperties}
          >
            <div className={styles.topBoxContent}>
              <span className={styles.topBoxLabel}>Your Agent Logic</span>
              <span className={styles.topBoxSub}>OpenAI · LangGraph · CrewAI · Google ADK</span>
            </div>
          </div>

          {/*
            ── Connector 1: topBox → hubCard ──
            A narrow SVG strip (36px tall) sits between the two rows.
            viewBox 900×36 maps exactly to the CSS gap height.
          */}
          <svg
            className={styles.connectorSvg}
            viewBox="0 0 900 36"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <defs>
              <marker id="akArrow1" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto">
                <path d="M0,0 L7,3.5 L0,7 Z" fill="var(--ak-blue)" opacity="0.6" />
              </marker>
              <filter id="akGlowTop" x="-200%" y="-200%" width="500%" height="500%">
                <feGaussianBlur stdDeviation="2" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              <path id="akDown1" d="M 450 0 L 450 36" />
            </defs>
            <line
              x1="450" y1="0" x2="450" y2="30"
              stroke="var(--ak-blue)" strokeWidth="1.5" strokeOpacity="0.5"
              strokeDasharray="30"
              strokeDashoffset={visible ? 0 : 30}
              style={{ transition: 'stroke-dashoffset 0.4s cubic-bezier(0.22,1,0.36,1) 0.1s' }}
              markerEnd="url(#akArrow1)"
            />
            {visible && !reducedMotion && (
              <circle r="3.5" fill="var(--ak-blue)" filter="url(#akGlowTop)" opacity="0.9">
                <animateMotion dur="1.8s" repeatCount="indefinite" begin="0.9s">
                  <mpath href="#akDown1" />
                </animateMotion>
              </circle>
            )}
          </svg>

          {/* ── Layer 2: Agent Kernel Runtime hub card ── */}
          <div
            className={`${styles.hubCard} ${visible ? styles.layerIn : ''}`}
            style={{ '--layer-delay': '180ms' } as React.CSSProperties}
          >
            <div className={styles.hubHeader}>
              <img
                src="/img/branding/agent-kernel-icon-color.svg"
                alt="Agent Kernel"
                className={styles.hubLogo}
              />
              <span className={styles.hubLabel}>Agent Kernel Runtime</span>
            </div>
            <div className={styles.modulesGrid}>
              {capabilityModules.map((mod, i) => (
                <div
                  key={mod.id}
                  className={`${styles.moduleChip} ${visible ? styles.moduleIn : ''}`}
                  style={{ '--mod-delay': `${280 + i * 65}ms` } as React.CSSProperties}
                >
                  <span className={styles.moduleIcon}>{mod.icon}</span>
                  <span className={styles.moduleLabel}>{mod.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/*
            ── Connector 2: hubCard → deployRow ──
            A 44px SVG strip — fan of 5 lines from hub center (x=450) to each deploy box.
            viewBox 900×44 maps exactly to this gap.
            Lines go from y=0 (hub card bottom) to y=44 (deploy box top).
          */}
          <svg
            className={styles.connectorSvg}
            viewBox="0 0 900 44"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <defs>
              <marker id="akArrow2" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill="var(--ak-blue)" opacity="0.4" />
              </marker>
              <filter id="akGlowFan" x="-100%" y="-100%" width="300%" height="300%">
                <feGaussianBlur stdDeviation="2.5" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              {/* Particle paths — one per deploy target */}
              {DEPLOY_X.map((x, i) => (
                <path
                  key={i}
                  id={`akFan${i}`}
                  d={`M 450 0 C 450 22, ${x} 22, ${x} 44`}
                />
              ))}
            </defs>

            {/* Fan lines: hub center → each deploy box top */}
            {DEPLOY_X.map((x, i) => {
              const dx = x - 450;
              const len = Math.round(Math.sqrt(dx * dx + 44 * 44) + 20);
              return (
                <path
                  key={i}
                  d={`M 450 0 C 450 22, ${x} 22, ${x} 44`}
                  fill="none"
                  stroke="var(--ak-blue)"
                  strokeWidth="1"
                  strokeOpacity="0.22"
                  strokeDasharray={len}
                  strokeDashoffset={visible ? 0 : len}
                  style={{
                    transition: `stroke-dashoffset 0.45s cubic-bezier(0.22,1,0.36,1) ${0.35 + i * 0.06}s`,
                  }}
                  markerEnd="url(#akArrow2)"
                />
              );
            })}

            {/* Particles — staggered to different deploy targets */}
            {visible && !reducedMotion && [0, 2, 4, 1, 3].map((targetIdx, j) => (
              <circle key={j} r="3.5"
                fill={j % 2 === 0 ? 'var(--ak-blue)' : 'var(--ak-purple)'}
                filter="url(#akGlowFan)"
                opacity="0.85"
              >
                <animateMotion
                  dur={`${1.6 + j * 0.2}s`}
                  repeatCount="indefinite"
                  begin={`${1.5 + j * 0.45}s`}
                >
                  <mpath href={`#akFan${targetIdx}`} />
                </animateMotion>
              </circle>
            ))}
          </svg>

          {/* ── Layer 3: Deployment targets ── */}
          <div className={styles.deployRow}>
            {deployTargets.map((t, i) => (
              <div
                key={t.id}
                className={`${styles.deployBox} ${visible ? styles.deployIn : ''}`}
                style={{ '--deploy-delay': `${500 + i * 55}ms` } as React.CSSProperties}
              >
                <span className={styles.deployIcon}>{t.icon}</span>
                <span className={styles.deployLabel}>{t.label}</span>
              </div>
            ))}
          </div>

        </div>
      </div>
    </section>
  );
}
