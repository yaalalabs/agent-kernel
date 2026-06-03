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
  MdExtension,
} from 'react-icons/md';
import { FaAws, FaDocker } from 'react-icons/fa';
import { FaMicrosoft, FaGoogle } from 'react-icons/fa';

/* ─── Data ───────────────────────────────────────────────────────────────── */

const capabilityModulesRow1 = [
  { id: 'adapters',   label: 'Framework Adapters', icon: <MdSwapHoriz /> },
  { id: 'memory',     label: 'Session & Memory',   icon: <MdMemory /> },
  { id: 'hooks',      label: 'Execution Nodes',    icon: <MdSettings /> },
  { id: 'knowledge',  label: 'Knowledge Bases',    icon: <MdMenuBook /> },
];

const capabilityModulesRow2 = [
  { id: 'messaging',  label: 'Messaging',          icon: <MdMessage /> },
  { id: 'observ',     label: 'Observability',      icon: <MdVisibility /> },
  { id: 'guardrails', label: 'Guardrails',         icon: <MdSecurity /> },
  { id: 'integrations', label: 'Integrations',     icon: <MdExtension /> },
];

const deployTargets = [
  { id: 'lambda',   label: 'AWS Lambda',      icon: <FaAws /> },
  { id: 'ecs',      label: 'AWS ECS',         icon: <FaAws /> },
  { id: 'azfunc',   label: 'Azure Functions', icon: <FaMicrosoft /> },
  { id: 'gapps',    label: 'Google Apps',     icon: <FaGoogle /> },
  { id: 'docker',   label: 'Docker',          icon: <FaDocker /> },
];

// 5 deploy targets; their x-center positions spread across 900px
const DEPLOY_X = [90, 225, 450, 675, 810];

/* ─── Component ─────────────────────────────────────────────────────────── */

export interface AgentKernelArchDiagramProps {
  /**
   * CSS color value for the accent (default: var(--ak-accent, #26A64D)).
   * Pass any valid CSS color — hex, rgb, hsl, or a var().
   * Example: accentColor="#CC7D21" or accentColor="var(--brand-color)"
   */
  accentColor?: string;
}

export default function AgentKernelArchDiagram({ accentColor }: AgentKernelArchDiagramProps) {
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

  // Accent color CSS variable override. Falls back to the module-level --ak-accent.
  const accentStyle = accentColor
    ? ({ '--ak-accent': accentColor } as React.CSSProperties)
    : undefined;

  const TEAL      = 'var(--ak-accent)';
  const TEAL_LINE = 'color-mix(in srgb, var(--ak-accent) 28%, transparent)';
  const TEAL_HALO = 'color-mix(in srgb, var(--ak-accent) 10%, transparent)';

  return (
    <section
      ref={sectionRef}
      className={styles.archSection}
      aria-label="Agent Kernel architecture overview"
      style={accentStyle}
    >
      <div className="container">
        <div className={styles.diagram}>

          {/* ── Layer 1: Your Agent Logic ── */}
          <div
            className={`${styles.topBox} ${visible ? styles.layerIn : ''}`}
            style={{ '--layer-delay': '0ms' } as React.CSSProperties}
          >
            <div className={styles.topBoxContent}>
              <span className={styles.topBoxLabel}>Your Agent Logic</span>
              <div className={styles.topBoxChips}>
                {['OpenAI', 'LangGraph', 'CrewAI', 'Google ADK', 'Smolagents', 'LiveKit'].map((item) => (
                  <span key={item} className={styles.topBoxChip}>{item}</span>
                ))}
              </div>
            </div>
          </div>

          {/* ── Connector 1: topBox → hubCard ── */}
          <svg
            className={styles.connectorSvg}
            style={{ height: '80px' }}
            viewBox="0 0 900 80"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <defs>
              <marker id="akArrow1" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto">
                <path d="M0,0 L7,3.5 L0,7 Z" fill={TEAL} opacity="0.6" />
              </marker>
              <filter id="akGlowTop" x="-200%" y="-200%" width="500%" height="500%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <filter id="akHaloTop" x="-80%" y="-80%" width="260%" height="260%">
                <feGaussianBlur stdDeviation="5" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <path id="akDown1" d="M 450 0 L 450 80" />
            </defs>
            {/* Dot at the start of the connector */}
            <circle cx="450" cy="4" r="5.5" fill={TEAL} filter="url(#akGlowTop)" />
            <line x1="450" y1="4" x2="450" y2="74" stroke={TEAL_HALO} strokeWidth="8" filter="url(#akHaloTop)" />
            <line
              x1="450" y1="4" x2="450" y2="74"
              stroke={TEAL_LINE}
              strokeWidth="1.5"
              strokeDasharray="70"
              strokeDashoffset={visible ? 0 : 70}
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

          {/* ── Layer 2: Agent Kernel Runtime hub card (icon + label only) ── */}
          <div
            className={`${styles.hubCard} ${visible ? styles.layerIn : ''}`}
            style={{ '--layer-delay': '180ms' } as React.CSSProperties}
          >
            <div className={styles.hubLogoWrap}>
              <div className={styles.hubLogoGlow} />
              <svg
                className={styles.hubLogo}
                viewBox="0 0 581.263 600"
                xmlns="http://www.w3.org/2000/svg"
                role="img"
                aria-hidden="true"
              >
                <g>
                  <g>
                    <path fill="var(--ak-accent)" d="M238.569,294.85v34.937l1.906,0.938c21.313,10.656,34.532,32.093,34.532,55.905v13.375
                        l-73.186-36.593c-31.75-15.875-51.812-48.343-51.812-83.843v-129.56l73.186,36.593c31.75,15.875,51.812,48.343,51.812,83.843
                        v46.312c-6.125-5.469-13-10.187-20.562-13.968L238.569,294.85z" />
                    <path fill="var(--ak-accent)" d="M431.254,150.008v129.56c0,35.5-20.062,67.968-51.812,83.843l-73.186,36.593v-50.749
                        c0-23.812,13.218-45.249,34.53-55.905l1.907-0.937v-34.937l-15.875,7.937c-7.562,3.781-14.438,8.5-20.562,13.969v-8.937
                        c0-35.5,20.062-67.968,51.812-83.843L431.254,150.008z" />
                    <path fill="var(--ak-accent)" d="M306.26,400.027v44.421l-7.028,3.514c-5.422,2.711-11.805,2.707-17.223-0.011l-6.982-3.503v-44.421
                        l6.969,3.496c5.426,2.722,11.818,2.722,17.244,0.001l6.971-3.496H306.26z" />
                  </g>
                </g>
              </svg>
            </div>
            <span className={styles.hubLabel}>Agent Kernel Runtime</span>
          </div>

          {/* ── Layer 3: Capability modules grid (standalone, outside hub card) ── */}
          <div className={styles.modulesGrid}>
            <div className={styles.modulesRow}>
              {capabilityModulesRow1.map((mod, i) => (
                <div
                  key={mod.id}
                  className={`${styles.moduleChip} ${visible ? styles.moduleIn : ''}`}
                  style={{ '--mod-delay': `${320 + i * 65}ms` } as React.CSSProperties}
                >
                  <div className={styles.moduleIconCell}>
                    <div className={styles.moduleIconBg} />
                    <span className={styles.moduleIcon}>{mod.icon}</span>
                  </div>
                  <span className={styles.moduleLabel}>{mod.label}</span>
                </div>
              ))}
            </div>
            <div className={styles.modulesRow}>
              {capabilityModulesRow2.map((mod, i) => (
                <div
                  key={mod.id}
                  className={`${styles.moduleChip} ${visible ? styles.moduleIn : ''}`}
                  style={{ '--mod-delay': `${580 + i * 65}ms` } as React.CSSProperties}
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

          {/* ── Connector 3: modulesGrid → deployRow (fan) ── */}
          <svg
            className={styles.connectorSvg}
            style={{ height: '80px' }}
            viewBox="0 0 900 80"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <defs>
              <marker id="akArrow3" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill={TEAL} opacity="0.4" />
              </marker>
              <filter id="akGlowFan" x="-100%" y="-100%" width="300%" height="300%">
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <filter id="akHaloFan" x="-80%" y="-80%" width="260%" height="260%">
                <feGaussianBlur stdDeviation="5" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              {DEPLOY_X.map((x, i) => (
                <path key={i} id={`akFan${i}`} d={`M 450 0 C 450 40, ${x} 40, ${x} 80`} />
              ))}
            </defs>
            {DEPLOY_X.map((x, i) => (
              <path
                key={`halo${i}`}
                d={`M 450 0 C 450 40, ${x} 40, ${x} 80`}
                fill="none"
                stroke={TEAL_HALO}
                strokeWidth="8"
                filter="url(#akHaloFan)"
              />
            ))}
            {DEPLOY_X.map((x, i) => {
              const dx = x - 450;
              const len = Math.round(Math.sqrt(dx * dx + 80 * 80) + 30);
              return (
                <path
                  key={i}
                  d={`M 450 0 C 450 40, ${x} 40, ${x} 80`}
                  fill="none"
                  stroke={TEAL_LINE}
                  strokeWidth="1.5"
                  strokeDasharray={len}
                  strokeDashoffset={visible ? 0 : len}
                  style={{
                    transition: `stroke-dashoffset 0.45s cubic-bezier(0.22,1,0.36,1) ${0.55 + i * 0.06}s`,
                  }}
                  markerEnd="url(#akArrow3)"
                />
              );
            })}
            {/* Glowing dot at the top center of the fan connector */}
            <circle cx="450" cy="0" r="5.5" fill={TEAL} filter="url(#akGlowFan)" />
            {visible && !reducedMotion && [0, 2, 4, 1, 3].map((targetIdx, j) => (
              <circle key={j} r="3.5" fill={TEAL} filter="url(#akGlowFan)" opacity="0.9">
                <animateMotion
                  dur={`${1.6 + j * 0.2}s`}
                  repeatCount="indefinite"
                  begin={`${1.8 + j * 0.45}s`}
                >
                  <mpath href={`#akFan${targetIdx}`} />
                </animateMotion>
              </circle>
            ))}
          </svg>

          {/* ── Layer 4: Deployment targets ── */}
          <div className={styles.deployRow}>
            {deployTargets.map((t, i) => (
              <div
                key={t.id}
                className={`${styles.deployBox} ${visible ? styles.deployIn : ''}`}
                style={{ '--deploy-delay': `${700 + i * 55}ms` } as React.CSSProperties}
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