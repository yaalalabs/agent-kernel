import React, { useState, useEffect, useRef } from 'react';
import styles from './styles.module.css';

/* ─── Data ───────────────────────────────────────────────────────────────── */

interface Track {
  id: 'traditional' | 'with-ak';
  title: string;
  timeLabel: string;
  fillPercent: number;
  barDuration: string;
  steps: string[];
}

const tracks: Track[] = [
  {
    id: 'traditional',
    title: 'Traditional Approach',
    timeLabel: '3–6 Months',
    fillPercent: 90,
    barDuration: '1.4s',
    // 7 chips — fits within a ~90% wide bar without overflow
    steps: ['Platform Eng.', 'Framework Setup', 'Cloud Config', 'Session Mgmt', 'Integrations', 'Testing Setup', 'Deploy Pipeline'],
  },
  {
    id: 'with-ak',
    title: 'With Agent Kernel',
    timeLabel: 'Days',
    fillPercent: 28,
    barDuration: '0.5s',
    // 2 chips — bar intentionally short; whitespace to the right reinforces simplicity
    steps: ['Write Logic', 'Deploy'],
  },
];

/* ─── Component ─────────────────────────────────────────────────────────── */

export default function UseCaseJourneyMap() {
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

  return (
    <section ref={sectionRef} className={styles.journeySection} aria-label="Time to production comparison">
      <div className="container">
        <div className={styles.header}>
          <h2 className={styles.title}>
            Traditional vs.{' '}
            <span className={styles.gradientText}>With Agent Kernel</span>
          </h2>
          <p className={styles.subtitle}>
            The same production-ready deployment, in a fraction of the time.
          </p>
        </div>

        <div className={styles.tracksWrapper}>
          {/* SVG bracket — positioned absolutely over trackMeta column */}
          <svg
            className={styles.bracketSvg}
            viewBox="0 0 40 100"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <line
              x1="32" y1="12" x2="32" y2="88"
              stroke="var(--ak-border-accent)" strokeWidth="1.5"
              strokeDasharray="76"
              strokeDashoffset={visible ? 0 : 76}
              style={{ transition: 'stroke-dashoffset 0.6s cubic-bezier(0.22,1,0.36,1) 0.3s' }}
            />
            <line x1="22" y1="12" x2="32" y2="12" stroke="var(--ak-border-accent)" strokeWidth="1.5" />
            <line x1="22" y1="88" x2="32" y2="88" stroke="var(--ak-border-accent)" strokeWidth="1.5" />
            <text
              x="12" y="54"
              fill="var(--ak-text-muted)"
              fontSize="10"
              fontFamily="var(--ifm-font-family-base)"
              textAnchor="middle"
            >vs</text>
          </svg>

          {tracks.map((track, i) => (
            <div key={track.id} className={`${styles.trackRow} ${styles[`trackRow_${track.id}`]}`}>
              <div className={styles.trackMeta}>
                <span className={styles.trackTitle}>{track.title}</span>
                <span className={`${styles.trackTime} ${styles[`trackTime_${track.id}`]}`}>
                  {track.timeLabel}
                </span>
              </div>

              <div className={styles.trackBarOuter}>
                <div
                  className={`${styles.trackBar} ${styles[`bar_${track.id}`]} ${visible ? styles.trackBarVisible : ''}`}
                  style={{
                    '--bar-target': `${track.fillPercent}%`,
                    '--bar-duration': track.barDuration,
                    '--bar-delay': `${i * 150}ms`,
                  } as React.CSSProperties}
                >
                  {track.steps.map((step, j) => (
                    <span
                      key={j}
                      className={`${styles.stepChip} ${visible ? styles.chipVisible : ''}`}
                      style={{ '--chip-delay': `${i * 150 + 650 + j * 65}ms` } as React.CSSProperties}
                    >
                      {step}
                    </span>
                  ))}
                </div>

                {track.id === 'with-ak' && (
                  <span className={`${styles.timeSavedBadge} ${visible ? styles.badgeVisible : ''}`}>
                    ~90% less time
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
