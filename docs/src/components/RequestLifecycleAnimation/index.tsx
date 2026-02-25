import React, { useState, useEffect, useRef } from 'react';
import styles from './styles.module.css';
import {
  MdMessage,
  MdSettings,
  MdSwapHoriz,
  MdCode,
  MdSecurity,
  MdRocketLaunch,
} from 'react-icons/md';
import { SiOpenai } from 'react-icons/si';

/* ─── Data ───────────────────────────────────────────────────────────────── */

interface Stage {
  id: string;
  label: string;
  sublabel?: string;
  icon: React.ReactNode;
  color: 'blue' | 'violet' | 'green';
}

const stages: Stage[] = [
  { id: 'input',     label: 'User Message',    icon: <MdMessage />,      color: 'blue'   },
  { id: 'prehooks',  label: 'Pre-Hooks',        sublabel: 'guardrails · RAG', icon: <MdSettings />,  color: 'violet' },
  { id: 'adapter',   label: 'Framework',        sublabel: 'adapter',      icon: <MdSwapHoriz />, color: 'blue'   },
  { id: 'llm',       label: 'Agent Invocation', icon: <SiOpenai />,       color: 'violet' },
  { id: 'tools',     label: 'Tool Execution',   icon: <MdCode />,         color: 'blue'   },
  { id: 'posthooks', label: 'Post-Hooks',       sublabel: 'moderation',   icon: <MdSecurity />,  color: 'violet' },
  { id: 'response',  label: 'Response',         icon: <MdRocketLaunch />, color: 'green'  },
];

const SVG_WIDTH = 900;
const STAGE_COUNT = stages.length;

// Stage X positions: evenly spaced from 60 to SVG_WIDTH-60
const stageXPositions = stages.map((_, i) =>
  Math.round(60 + (i * (SVG_WIDTH - 120)) / (STAGE_COUNT - 1))
);
const TRACK_LENGTH = SVG_WIDTH - 120;

// Per-stage dwell time in ms
const STAGE_DWELL = 460;

/* ─── Component ─────────────────────────────────────────────────────────── */

export default function RequestLifecycleAnimation() {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [activeStage, setActiveStage] = useState(-1);

  // Scroll-trigger
  useEffect(() => {
    if (typeof window !== 'undefined' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setVisible(true);
      return;
    }
    const el = wrapperRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.2 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  /*
   * Stage highlight + packet position loop.
   * The packet is a CSS-transitioned SVG <g> driven by activeStage,
   * so packet and card highlight are ALWAYS in sync — no drift.
   *
   * Sequence:  wait 900ms → show stage 0 → advance every STAGE_DWELL ms
   *            → at last stage, pause 700ms → reset to -1 (hide) → restart
   */
  useEffect(() => {
    if (!visible) return;

    let idx = 0;
    let intervalId: ReturnType<typeof setInterval>;

    const startCycle = () => {
      idx = 0;
      setActiveStage(0);
      intervalId = setInterval(() => {
        idx++;
        if (idx >= STAGE_COUNT) {
          // End of cycle — hide packet briefly then restart
          clearInterval(intervalId);
          setActiveStage(-1);
          setTimeout(startCycle, 700);
        } else {
          setActiveStage(idx);
        }
      }, STAGE_DWELL);
    };

    const initTimer = setTimeout(startCycle, 900);

    return () => {
      clearTimeout(initTimer);
      clearInterval(intervalId);
    };
  }, [visible]);

  const reducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Packet x-position: falls back to first stage when hidden (opacity handles visibility)
  const packetX = activeStage >= 0 ? stageXPositions[activeStage] : stageXPositions[0];
  const packetVisible = visible && !reducedMotion && activeStage >= 0;

  return (
    <div ref={wrapperRef} className={styles.wrapper}>
      <div className="container">
        <div className={styles.header}>
          <span className={styles.badge}>Request Lifecycle</span>
          <h2 className={styles.title}>Every Request, Fully Orchestrated</h2>
          <p className={styles.subtitle}>
            Agent Kernel wraps your agent logic in a structured, inspectable execution pipeline —
            from user message to validated response.
          </p>
        </div>

        <div className={styles.pipelineOuter}>
          {/* Stage node row */}
          <div className={styles.stageRow}>
            {stages.map((stage, i) => (
              <div
                key={stage.id}
                className={`
                  ${styles.stageNode}
                  ${styles[`color_${stage.color}`]}
                  ${visible ? styles.stageVisible : ''}
                  ${activeStage === i ? styles.stageActive : ''}
                  ${activeStage > i ? styles.stageDimmed : ''}
                `}
                style={{ '--stage-delay': `${i * 120}ms` } as React.CSSProperties}
              >
                <div className={styles.stageIcon}>{stage.icon}</div>
                <div className={styles.stageLabel}>{stage.label}</div>
                {stage.sublabel && (
                  <div className={styles.stageSublabel}>{stage.sublabel}</div>
                )}
              </div>
            ))}
          </div>

          {/* SVG track */}
          <svg
            className={styles.trackSvg}
            viewBox={`0 0 ${SVG_WIDTH} 48`}
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <defs>
              <linearGradient id="rlTrackGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="var(--ak-blue)" />
                <stop offset="100%" stopColor="var(--ak-purple)" />
              </linearGradient>
              <filter id="rlGlow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            {/* Background track */}
            <line
              x1="60" y1="24" x2={SVG_WIDTH - 60} y2="24"
              stroke="var(--ak-border)" strokeWidth="2"
            />

            {/* Animated fill track — draws on scroll-into-view */}
            <line
              x1="60" y1="24" x2={SVG_WIDTH - 60} y2="24"
              stroke="url(#rlTrackGrad)" strokeWidth="2"
              strokeDasharray={TRACK_LENGTH}
              strokeDashoffset={visible ? 0 : TRACK_LENGTH}
              className={styles.trackLine}
            />

            {/* Stage tick circles — fill as packet passes */}
            {stageXPositions.map((x, i) => (
              <circle
                key={i}
                cx={x} cy="24" r="5"
                fill={activeStage >= i && activeStage >= 0 ? 'var(--ak-blue)' : 'var(--ak-surface-overlay)'}
                stroke={activeStage >= i && activeStage >= 0 ? 'var(--ak-blue)' : 'var(--ak-border)'}
                strokeWidth="1.5"
                style={{ transition: 'fill 0.2s ease, stroke 0.2s ease' }}
              />
            ))}

            {/*
              Packet dot — a <g> whose translateX is driven by activeStage.
              CSS transition on transform keeps it perfectly in sync with the
              card highlights (both driven from the same React state), eliminating drift.
            */}
            {visible && (
              <g
                style={{
                  transform: `translateX(${packetX}px)`,
                  transition: activeStage >= 0
                    ? `transform ${STAGE_DWELL * 0.65}ms cubic-bezier(0.4, 0, 0.2, 1)`
                    : 'none',
                  opacity: packetVisible ? 1 : 0,
                }}
              >
                <circle cx="0" cy="24" r="9" fill="var(--ak-blue)" filter="url(#rlGlow)" opacity="0.85" />
                <circle cx="0" cy="24" r="5" fill="white" opacity="0.35" />
              </g>
            )}
          </svg>
        </div>
      </div>
    </div>
  );
}
