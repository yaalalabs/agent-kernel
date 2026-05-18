import React, { useState, useEffect, useRef } from 'react';
import styles from './styles.module.css';
import {
  MdSwapHoriz,
  MdMemory,
  MdSettings,
  MdVisibility,
  MdSecurity,
  MdMessage,
  MdMenuBook,
} from 'react-icons/md';
import { FaAws, FaDocker } from 'react-icons/fa';
import { FaMicrosoft } from 'react-icons/fa';

/* ─── Data ───────────────────────────────────────────────────────────────── */

const capabilityModulesRow1 = [
  { id: 'adapters',   label: 'Framework Adapters', icon: <MdSwapHoriz /> },
  { id: 'memory',     label: 'Session & Memory',   icon: <MdMemory /> },
  { id: 'hooks',      label: 'Execution Hooks',    icon: <MdSettings /> },
  { id: 'knowledge',  label: 'Knowledge Bases',    icon: <MdMenuBook /> },
];

const capabilityModulesRow2 = [
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

// 5 deploy targets; their x-center positions spread across 900px
const DEPLOY_X = [90, 225, 450, 675, 810];

/* ─── Cyan accent tokens (match differentiators palette) ───────────────── */
const TEAL      = 'rgba(0,221,255,1)';
const TEAL_LINE = 'rgba(0,221,255,0.28)';
const TEAL_HALO = 'rgba(0,221,255,0.1)';

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
        <div className={styles.diagram}>

          {/* ── Layer 1: Your Agent Logic ── */}
          <div
            className={`${styles.topBox} ${visible ? styles.layerIn : ''}`}
            style={{ '--layer-delay': '0ms' } as React.CSSProperties}
          >
            <div className={styles.topBoxContent}>
              <span className={styles.topBoxLabel}>Your Agent Logic</span>
              <span className={styles.topBoxSub}>
                {['OpenAI', 'LangGraph', 'CrewAI', 'Google ADK', 'Smolagents', 'LiveKit'].map((item, idx) => (
                  <React.Fragment key={item}>
                    {idx > 0 && (
                      <span className={styles.topBoxSubSep} aria-hidden="true">
                        ●
                      </span>
                    )}
                    {item}
                  </React.Fragment>
                ))}
              </span>
            </div>
          </div>

          {/*
            ── Connector 1: topBox → hubCard ──
            Narrow 36px strip between the two rows.
          */}
          <svg
            className={styles.connectorSvg}
            viewBox="0 0 900 36"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <defs>
              <marker id="akArrow1" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto">
                <path d="M0,0 L7,3.5 L0,7 Z" fill={TEAL} opacity="0.6" />
              </marker>
              <filter id="akGlowTop" x="-200%" y="-200%" width="500%" height="500%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              {/* Halo filter — matches differentiators lineGlow */}
              <filter id="akHaloTop" x="-80%" y="-80%" width="260%" height="260%">
                <feGaussianBlur stdDeviation="5" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <path id="akDown1" d="M 450 0 L 450 36" />
            </defs>
            {/* Halo line */}
            <line
              x1="450" y1="0" x2="450" y2="30"
              stroke={TEAL_HALO}
              strokeWidth="8"
              filter="url(#akHaloTop)"
            />
            {/* Main line */}
            <line
              x1="450" y1="0" x2="450" y2="30"
              stroke={TEAL_LINE}
              strokeWidth="1.5"
              strokeDasharray="30"
              strokeDashoffset={visible ? 0 : 30}
              style={{ transition: 'stroke-dashoffset 0.4s cubic-bezier(0.22,1,0.36,1) 0.1s' }}
              markerEnd="url(#akArrow1)"
            />
            {visible && !reducedMotion && (
              <circle r="3.5" fill={TEAL} filter="url(#akGlowTop)" opacity="0.9">
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
              {/* Logo with pulsing glow — mirrors orbitHub */}
              <div className={styles.hubLogoWrap}>
                <div className={styles.hubLogoGlow} />
                <img
                  src="/img/branding/agent-kernel-icon-color.svg"
                  alt="Agent Kernel"
                  className={styles.hubLogo}
                />
              </div>
              <span className={styles.hubLabel}>Agent Kernel Runtime</span>
            </div>
            <div className={styles.modulesGrid}>
              <div className={styles.modulesRow}>
                {capabilityModulesRow1.map((mod, i) => (
                  <div
                    key={mod.id}
                    className={`${styles.moduleChip} ${visible ? styles.moduleIn : ''}`}
                    style={{ '--mod-delay': `${280 + i * 65}ms` } as React.CSSProperties}
                  >
                    <div className={styles.moduleIconCell}>
                      <div className={styles.moduleIconBg} />
                      <span className={styles.moduleIcon}>{mod.icon}</span>
                    </div>
                    <span className={styles.moduleLabel}>{mod.label}</span>
                  </div>
                ))}
              </div>
              <div className={`${styles.modulesRow} ${styles.modulesRowSecond}`}>
                {capabilityModulesRow2.map((mod, i) => (
                  <div
                    key={mod.id}
                    className={`${styles.moduleChip} ${visible ? styles.moduleIn : ''}`}
                    style={{ '--mod-delay': `${540 + i * 65}ms` } as React.CSSProperties}
                  >
                    <div className={styles.moduleIconCell}>
                      <div className={styles.moduleIconBg} />
                      <span className={styles.moduleIcon}>{mod.icon}</span>
                    </div>
                    <span className={styles.moduleLabel}>{mod.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/*
            ── Connector 2: hubCard → deployRow ──
            44px SVG fan — 5 curved paths from hub centre to each deploy box.
          */}
          <svg
            className={styles.connectorSvg}
            viewBox="0 0 900 44"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <defs>
              <marker id="akArrow2" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill={TEAL} opacity="0.4" />
              </marker>
              <filter id="akGlowFan" x="-100%" y="-100%" width="300%" height="300%">
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              <filter id="akHaloFan" x="-80%" y="-80%" width="260%" height="260%">
                <feGaussianBlur stdDeviation="5" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              {/* Particle paths */}
              {DEPLOY_X.map((x, i) => (
                <path key={i} id={`akFan${i}`} d={`M 450 0 C 450 22, ${x} 22, ${x} 44`} />
              ))}
            </defs>

            {/* Halo fan lines */}
            {DEPLOY_X.map((x, i) => (
              <path
                key={`halo${i}`}
                d={`M 450 0 C 450 22, ${x} 22, ${x} 44`}
                fill="none"
                stroke={TEAL_HALO}
                strokeWidth="8"
                filter="url(#akHaloFan)"
              />
            ))}

            {/* Main fan lines */}
            {DEPLOY_X.map((x, i) => {
              const dx = x - 450;
              const len = Math.round(Math.sqrt(dx * dx + 44 * 44) + 20);
              return (
                <path
                  key={i}
                  d={`M 450 0 C 450 22, ${x} 22, ${x} 44`}
                  fill="none"
                  stroke={TEAL_LINE}
                  strokeWidth="1.5"
                  strokeDasharray={len}
                  strokeDashoffset={visible ? 0 : len}
                  style={{
                    transition: `stroke-dashoffset 0.45s cubic-bezier(0.22,1,0.36,1) ${0.35 + i * 0.06}s`,
                  }}
                  markerEnd="url(#akArrow2)"
                />
              );
            })}

            {/* Traveling dots — teal, staggered */}
            {visible && !reducedMotion && [0, 2, 4, 1, 3].map((targetIdx, j) => (
              <circle key={j} r="3.5"
                fill={TEAL}
                filter="url(#akGlowFan)"
                opacity="0.9"
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
