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
 * Layout constants — these match the CSS below.
 * The SVG viewBox is 900 × 420. All Y values are in those units.
 *
 *   topBox  :  y=0   → h=74   → bottom at 74
 *   gap     :  74   → 110
 *   hub     :  110  → h=130  → bottom at 240   center=175
 *   gap     :  240  → 280
 *   deployRow: 280  → h=72   → center=316
 */
const SVG_W = 900;
const SVG_H = 420;

const TOP_BOTTOM  = 74;
const HUB_TOP     = 110;
const HUB_BOTTOM  = 240;
const HUB_CX      = 450;

const DEPLOY_TOP  = 280;
const DEPLOY_BOTTOM = 352;
const DEPLOY_CX   = DEPLOY_TOP + (DEPLOY_BOTTOM - DEPLOY_TOP) / 2; // y midpoint

// 5 deploy targets, evenly spread across 900px with padding
const DEPLOY_POSITIONS = [100, 230, 450, 670, 800];

const TRACK_LEN = SVG_W - 120;

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

        {/*
          The diagram is a single relative container. One SVG overlay covers
          the full container for lines and particles. HTML layers are stacked on top.
          All SVG Y values correspond directly to CSS row positions (SVG viewBox = actual px layout).
        */}
        <div className={styles.diagram}>

          {/* SVG overlay — absolute, covers full .diagram height */}
          <svg
            className={styles.svgOverlay}
            viewBox={`0 0 ${SVG_W} ${SVG_H}`}
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
          >
            <defs>
              <linearGradient id="akGradV" x1="0" y1={`${TOP_BOTTOM}`} x2="0" y2={`${HUB_TOP}`} gradientUnits="userSpaceOnUse">
                <stop offset="0%" stopColor="var(--ak-blue)" stopOpacity="0.7" />
                <stop offset="100%" stopColor="var(--ak-blue)" stopOpacity="0.35" />
              </linearGradient>
              <filter id="akGlowF" x="-100%" y="-100%" width="300%" height="300%">
                <feGaussianBlur stdDeviation="2.5" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              <marker id="akArrowBlue" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto">
                <path d="M0,0 L7,3.5 L0,7 Z" fill="var(--ak-blue)" opacity="0.5" />
              </marker>

              {/* Particle paths */}
              <path id="akPathTopHub" d={`M ${HUB_CX} ${TOP_BOTTOM} L ${HUB_CX} ${HUB_TOP}`} />
              {DEPLOY_POSITIONS.map((x, i) => (
                <path key={i}
                  id={`akPathDeploy${i}`}
                  d={`M ${HUB_CX} ${HUB_BOTTOM} C ${HUB_CX} ${HUB_BOTTOM + 40}, ${x} ${DEPLOY_TOP - 20}, ${x} ${DEPLOY_TOP}`}
                />
              ))}
            </defs>

            {/* Top connector line: Your Code → Hub */}
            <line
              x1={HUB_CX} y1={TOP_BOTTOM}
              x2={HUB_CX} y2={HUB_TOP}
              stroke="url(#akGradV)" strokeWidth="1.5"
              strokeDasharray="36"
              strokeDashoffset={visible ? 0 : 36}
              style={{ transition: 'stroke-dashoffset 0.45s cubic-bezier(0.22,1,0.36,1) 0.1s' }}
              markerEnd="url(#akArrowBlue)"
            />

            {/* Fan lines: Hub → Deploy targets */}
            {DEPLOY_POSITIONS.map((x, i) => {
              const dy = DEPLOY_TOP - HUB_BOTTOM;
              const dx = x - HUB_CX;
              const len = Math.round(Math.sqrt(dx * dx + dy * dy) + 40); // approx bezier len
              return (
                <path
                  key={i}
                  d={`M ${HUB_CX} ${HUB_BOTTOM} C ${HUB_CX} ${HUB_BOTTOM + 40}, ${x} ${DEPLOY_TOP - 20}, ${x} ${DEPLOY_TOP}`}
                  fill="none"
                  stroke="var(--ak-blue)" strokeWidth="1" strokeOpacity="0.2"
                  strokeDasharray={len}
                  strokeDashoffset={visible ? 0 : len}
                  style={{
                    transition: `stroke-dashoffset 0.5s cubic-bezier(0.22,1,0.36,1) ${0.38 + i * 0.07}s`,
                  }}
                  markerEnd="url(#akArrowBlue)"
                />
              );
            })}

            {/* Animated particles */}
            {visible && !reducedMotion && (
              <>
                {/* Top → Hub */}
                <circle r="4" fill="var(--ak-blue)" filter="url(#akGlowF)">
                  <animateMotion dur="1.8s" repeatCount="indefinite" begin="0.9s">
                    <mpath href="#akPathTopHub" />
                  </animateMotion>
                </circle>
                {/* Hub → deploys (staggered) */}
                {[0, 2, 4].map(i => (
                  <circle key={i} r="3.5" fill="var(--ak-purple)" filter="url(#akGlowF)" opacity="0.85">
                    <animateMotion
                      dur={`${1.8 + i * 0.2}s`}
                      repeatCount="indefinite"
                      begin={`${1.6 + i * 0.5}s`}
                    >
                      <mpath href={`#akPathDeploy${i}`} />
                    </animateMotion>
                  </circle>
                ))}
                {[1, 3].map(i => (
                  <circle key={i} r="3" fill="var(--ak-blue)" filter="url(#akGlowF)" opacity="0.8">
                    <animateMotion
                      dur={`${2.0 + i * 0.15}s`}
                      repeatCount="indefinite"
                      begin={`${2.2 + i * 0.4}s`}
                    >
                      <mpath href={`#akPathDeploy${i}`} />
                    </animateMotion>
                  </circle>
                ))}
              </>
            )}
          </svg>

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
