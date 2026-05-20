import React, { useState, useEffect, useRef } from 'react';
import styles from './styles.module.css';
import { FaRegClock, FaRocket } from 'react-icons/fa';

/* ─── Data ───────────────────────────────────────────────────────────────── */

interface Step {
  label: string;
  sub: string;
}

interface Track {
  id: 'traditional' | 'with-ak';
  title: string;
  timeLabel: string;
  steps: Step[];
  doneLabel: string;
  doneIcon: React.ReactNode;
}

const tracks: Track[] = [
  {
    id: 'traditional',
    title: 'Traditional',
    timeLabel: '3–6 months',
    doneLabel: 'Months later…',
    doneIcon: <FaRegClock />,
    steps: [
      { label: 'Platform engineering', sub: 'Set up base infrastructure' },
      { label: 'Framework setup',      sub: 'Choose, configure, scaffold' },
      { label: 'Cloud config',         sub: 'Regions, roles, networking' },
      { label: 'Session management',   sub: 'Auth, state, tokens' },
      { label: 'Integrations',         sub: 'APIs, queues, data sources' },
      { label: 'Testing setup',        sub: 'Harnesses, CI, coverage' },
      { label: 'Deploy pipeline',      sub: 'Build, push, release gates' },
    ],
  },
  {
    id: 'with-ak',
    title: 'Agent Kernel',
    timeLabel: 'Days',
    doneLabel: 'Shipped',
    doneIcon: <FaRocket />,
    steps: [
      { label: 'Write your logic', sub: 'Focus on what your agent does — not how it runs' },
      { label: 'Deploy',           sub: 'Agent Kernel handles the rest' },
    ],
  },
];

/* ─── Component ─────────────────────────────────────────────────────────── */

export default function UseCaseJourneyMap() {
  const sectionRef = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  const [animationNonce, setAnimationNonce] = useState(0);
  const isInViewRef = useRef(false);

  useEffect(() => {
    if (
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      setVisible(true);
      return;
    }
    const el = sectionRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !isInViewRef.current) {
          isInViewRef.current = true;
          setVisible(true);
          setAnimationNonce((nonce) => nonce + 1);
        } else if (!entry.isIntersecting) {
          isInViewRef.current = false;
        }
      },
      { threshold: 0.1 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <section
      ref={sectionRef}
      className={styles.journeySection}
      aria-label="Time to production comparison"
    >
      <div className="container" key={animationNonce}>

        {/* Header */}
        <div className={styles.header}>
          <p className={styles.eyebrow}>Time to production</p>
          <h2 className={styles.title}>
            Traditional vs.{' '}
            <span className={styles.gradientText}>Agent Kernel</span>
          </h2>
        </div>

        {/* Two-column timeline grid */}
        <div className={styles.grid}>
          {tracks.map((track, trackIdx) => (
            <div
              key={track.id}
              className={`${styles.column} ${styles[`col_${track.id}`]}`}
            >
              {/* Column header */}
              <div className={styles.colHeader}>
                <p className={styles.colTitle}>{track.title}</p>
                <p className={`${styles.colTime} ${styles[`colTime_${track.id}`]}`}>
                  {track.timeLabel}
                </p>
              </div>

              {/* Steps */}
              <div className={styles.timeline}>
                {track.steps.map((step, stepIdx) => {
                  const isLast = stepIdx === track.steps.length - 1;
                  // stagger: each track starts offset so AK finishes way before Traditional
                  const baseDelay = trackIdx === 0 ? 0 : 200;
                  const stepDelay = baseDelay + stepIdx * (trackIdx === 0 ? 120 : 220);
                  const lineDelay = stepDelay + 60;

                  return (
                    <div key={stepIdx} className={styles.stepRow}>
                      {/* Node + connector */}
                      <div className={styles.nodeCol}>
                        <div
                          className={`${styles.node} ${styles[`node_${track.id}`]} ${visible ? styles.nodeVisible : ''}`}
                          style={{ '--node-delay': `${stepDelay}ms` } as React.CSSProperties}
                        />
                        {!isLast && (
                          <div
                            className={`${styles.connector} ${styles[`connector_${track.id}`]} ${visible ? styles.connectorVisible : ''}`}
                            style={{ '--line-delay': `${lineDelay}ms` } as React.CSSProperties}
                          />
                        )}
                      </div>

                      {/* Text */}
                      <div
                        className={`${styles.stepText} ${visible ? styles.stepTextVisible : ''}`}
                        style={{ '--text-delay': `${stepDelay}ms` } as React.CSSProperties}
                      >
                        <span className={styles.stepLabel}>{step.label}</span>
                        <span className={styles.stepSub}>{step.sub}</span>
                      </div>
                    </div>
                  );
                })}

                {/* Done badge */}
                <div
                  className={`${styles.doneBadge} ${styles[`done_${track.id}`]} ${visible ? styles.doneBadgeVisible : ''}`}
                  style={{
                    '--done-delay': `${
                      trackIdx === 0
                        ? track.steps.length * 120 + 100
                        : 200 + track.steps.length * 220
                    }ms`,
                  } as React.CSSProperties}
                >
                  <span>{track.doneIcon}</span>
                  <span>{track.doneLabel}</span>
                </div>
              </div>

              {/* Savings callout — only on AK column */}
              {track.id === 'with-ak' && (
                <div
                  className={`${styles.savingsCard} ${visible ? styles.savingsCardVisible : ''}`}
                >
                  <p className={styles.savingsLabel}>Time saved</p>
                  <p className={styles.savingsValue}>~90% less</p>
                </div>
              )}
            </div>
          ))}
        </div>

      </div>
    </section>
  );
}