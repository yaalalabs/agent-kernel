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
  { id: 'input',     label: 'User Message',      icon: <MdMessage />,    color: 'blue'   },
  { id: 'prehooks',  label: 'Pre-Hooks',          sublabel: 'guardrails · RAG', icon: <MdSettings />, color: 'violet' },
  { id: 'adapter',   label: 'Framework',          sublabel: 'adapter',    icon: <MdSwapHoriz />, color: 'blue' },
  { id: 'llm',       label: 'Agent Invocation',           icon: <SiOpenai />,     color: 'violet' },
  { id: 'tools',     label: 'Tool Execution',     icon: <MdCode />,       color: 'blue'   },
  { id: 'posthooks', label: 'Post-Hooks',         sublabel: 'moderation', icon: <MdSecurity />, color: 'violet' },
  { id: 'response',  label: 'Response',           icon: <MdRocketLaunch />, color: 'green' },
];

const SVG_WIDTH = 900;
const STAGE_COUNT = stages.length;
// Stage tick X positions: evenly spaced from 60 to SVG_WIDTH-60
const stageXPositions = stages.map((_, i) =>
  Math.round(60 + (i * (SVG_WIDTH - 120)) / (STAGE_COUNT - 1))
);
const TRACK_LENGTH = SVG_WIDTH - 120;

// keyPoints and keyTimes for animateMotion — evenly spaced
const keyPointsStr = stageXPositions.map(x => ((x - 60) / TRACK_LENGTH).toFixed(4)).join(';');
const keyTimesStr = stageXPositions.map((_, i) => (i / (STAGE_COUNT - 1)).toFixed(4)).join(';');
// cubic ease for each segment
const keySplines = Array(STAGE_COUNT - 1).fill('0.4 0 0.2 1').join('; ');

// Duration per full loop: 380ms per stage with a 600ms pause at end
const LOOP_DUR_S = (STAGE_COUNT * 380 + 600) / 1000;

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

  // Stage highlight cycle (synced roughly with the SVG animateMotion)
  useEffect(() => {
    if (!visible) return;
    let stageIdx = 0;
    const startTimer = setTimeout(() => {
      const interval = setInterval(() => {
        setActiveStage(stageIdx);
        stageIdx++;
        if (stageIdx >= STAGE_COUNT) {
          stageIdx = 0;
          // Brief gap before restarting (matches SVG loop gap)
          setActiveStage(-1);
          setTimeout(() => { stageIdx = 0; }, 600);
        }
      }, 380);
      return () => clearInterval(interval);
    }, 900); // wait for nodes to appear

    return () => clearTimeout(startTimer);
  }, [visible]);

  const reducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

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
                style={{ '--stage-delay': `${i * 90}ms` } as React.CSSProperties}
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
              {/* Path for animateMotion */}
              <path id="rlTrackPath" d={`M 60 24 L ${SVG_WIDTH - 60} 24`} />
            </defs>

            {/* Background track */}
            <line
              x1="60" y1="24" x2={SVG_WIDTH - 60} y2="24"
              stroke="var(--ak-border)" strokeWidth="2"
            />

            {/* Animated fill track */}
            <line
              x1="60" y1="24" x2={SVG_WIDTH - 60} y2="24"
              stroke="url(#rlTrackGrad)" strokeWidth="2"
              strokeDasharray={TRACK_LENGTH}
              strokeDashoffset={visible ? 0 : TRACK_LENGTH}
              className={styles.trackLine}
            />

            {/* Stage tick circles */}
            {stageXPositions.map((x, i) => (
              <circle
                key={i}
                cx={x} cy="24" r="5"
                fill={
                  activeStage > i
                    ? 'var(--ak-blue)'
                    : activeStage === i
                    ? 'var(--ak-blue)'
                    : 'var(--ak-surface-overlay)'
                }
                stroke={
                  activeStage >= i ? 'var(--ak-blue)' : 'var(--ak-border)'
                }
                strokeWidth="1.5"
                style={{ transition: 'fill 0.2s ease, stroke 0.2s ease' }}
              />
            ))}

            {/* Animated packet dot */}
            {visible && !reducedMotion && (
              <circle r="8" fill="var(--ak-blue)" filter="url(#rlGlow)" opacity="0.9">
                <animateMotion
                  dur={`${LOOP_DUR_S}s`}
                  repeatCount="indefinite"
                  keyPoints={keyPointsStr}
                  keyTimes={keyTimesStr}
                  calcMode="spline"
                  keySplines={keySplines}
                >
                  <mpath href="#rlTrackPath" />
                </animateMotion>
              </circle>
            )}
          </svg>
        </div>
      </div>
    </div>
  );
}
