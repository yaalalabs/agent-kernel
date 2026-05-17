import React, { useEffect, useRef, useState } from 'react';
import styles from './styles.module.css';

/* ─────────────────────────────────────────────────────────────────────────
   StepTimeline
   A fixed top-bar progress indicator that tracks scroll position through
   each level's steps.  Drop it inside <Levels /> and pass:
     • levelId  — '01' | '02' | '03' | null  (null = hidden)
     • contentRef — ref to the scrollable level content wrapper
   ───────────────────────────────────────────────────────────────────────── */

interface StepDef {
  num: string;
  label: string;
  /** CSS selector used to locate the step anchor inside contentRef */
  selector: string;
}

const LEVEL_STEPS: Record<string, StepDef[]> = {
  '01': [
    { num: '01', label: 'Identify the gap',    selector: '[data-step="bl-01"]' },
    { num: '02', label: 'Meet the solution',   selector: '[data-step="bl-02"]' },
    { num: '03', label: 'Agent Kernel',        selector: '[data-step="bl-03"]' },
    { num: '04', label: 'See it in action',    selector: '[data-step="bl-04"]' },
    { num: '05', label: 'How it works',        selector: '[data-step="bl-05"]' },
  ],
  '02': [
    { num: '01', label: 'Analogy',             selector: '[data-step="dev-01"]' },
    { num: '02', label: 'Architecture',        selector: '[data-step="dev-02"]' },
    { num: '03', label: 'Features',            selector: '[data-step="dev-03"]' },
    { num: '04', label: 'Framework',           selector: '[data-step="dev-04"]' },
    { num: '05', label: 'Complete picture',    selector: '[data-step="dev-05"]' },
  ],
  '03': [
    { num: '01', label: 'Analogy',             selector: '[data-step="ai-01"]' },
    { num: '02', label: 'Architecture',        selector: '[data-step="ai-02"]' },
    { num: '03', label: 'Stand out',           selector: '[data-step="ai-03"]' },
    { num: '04', label: 'Features',            selector: '[data-step="ai-04"]' },
    { num: '05', label: 'Framework',           selector: '[data-step="ai-05"]' },
    { num: '06', label: 'Build agents',        selector: '[data-step="ai-06"]' },
    { num: '07', label: 'Complete picture',    selector: '[data-step="ai-07"]' },
    { num: '08', label: 'OS depth',            selector: '[data-step="ai-08"]' },
  ],
};

interface StepTimelineProps {
  levelId: string | null;
  contentRef: React.RefObject<HTMLDivElement>;
}

export function StepTimeline({ levelId, contentRef }: StepTimelineProps) {
  const [activeStep, setActiveStep] = useState(0);
  const [visible, setVisible] = useState(false);
  const contentObserverRef = useRef<IntersectionObserver | null>(null);
  const [progress, setProgress] = useState<number[]>([]);
  const rafRef = useRef<number | null>(null);

  const steps = levelId ? LEVEL_STEPS[levelId] ?? [] : [];

  const getDocumentTop = (element: HTMLElement) => {
    let top = 0;
    let node: HTMLElement | null = element;

    while (node) {
      top += node.offsetTop;
      node = node.offsetParent as HTMLElement | null;
    }

    return top;
  };

  /* ── Visibility: show when the level content is in view; hide when scrolled past ── */
  useEffect(() => {
    // clean previous content observer
    contentObserverRef.current?.disconnect();
    contentObserverRef.current = null;

    if (!levelId || !contentRef.current) {
      setVisible(false);
      setActiveStep(0);
      return;
    }

    const el = contentRef.current;
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setVisible(true);
            setActiveStep(0);
          } else {
            setVisible(false);
            setActiveStep(0);
          }
        });
      },
      { root: null, threshold: 0.05 }
    );

    obs.observe(el);
    contentObserverRef.current = obs;

    return () => {
      obs.disconnect();
      contentObserverRef.current = null;
    };
  }, [levelId, contentRef]);

  /* ── Track scroll progress inside each step ── */
  useEffect(() => {
    if (!visible || !contentRef.current || steps.length === 0) {
      setActiveStep(0);
      setProgress([]);
      return;
    }

    const els = steps.map(s => contentRef.current!.querySelector(s.selector) as HTMLElement | null);

    const update = () => {
      const marker = window.innerHeight * 0.35;
      const scrollPosition = window.scrollY + marker;

      let nextActive = 0;
      const next: number[] = els.map((el, index) => {
        if (!el) return 0;

        const top = getDocumentTop(el);
        const height = el.offsetHeight;
        const bottom = top + height;

        if (scrollPosition >= top) {
          nextActive = index;
        }

        if (height <= 0) return 0;

        const start = top - marker;
        const end = bottom - marker;
        if (end <= start) return scrollPosition >= end ? 1 : 0;

        const frac = (scrollPosition - start) / (end - start);
        return Math.max(0, Math.min(1, frac));
      });

      setActiveStep(nextActive);
      setProgress(next);
      rafRef.current = null;
    };

    const onScroll = () => {
      if (rafRef.current != null) return;
      rafRef.current = window.requestAnimationFrame(update);
    };

    // initial
    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);

    return () => {
      if (rafRef.current) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, [visible, contentRef, steps]);

  /* ── Scroll-to on click ── */
  const scrollToStep = (index: number) => {
    const el = contentRef.current?.querySelector(steps[index]?.selector) as HTMLElement | null;
    if (el && typeof window !== 'undefined') {
      const offset = 80; /* account for the bar height */
      const top = el.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({ top, behavior: 'smooth' });
    }
  };

  if (!visible || steps.length === 0) return null;

  return (
    <div className={styles.bar}>
      <div className={styles.inner}>
        {steps.map((step, index) => {
          const state: 'done' | 'active' | 'upcoming' =
            index < activeStep ? 'done' : index === activeStep ? 'active' : 'upcoming';

          return (
            <React.Fragment key={step.num}>
              {/* connector line before each step (except the first) */}
              {index > 0 && (
                <div className={styles.connectorWrapper} aria-hidden="true">
                  <div
                    className={styles.connectorFill}
                    style={{
                      '--fill-width': `${Math.max(0, Math.min(1, (index - 1) < activeStep ? 1 : (index - 1) === activeStep ? (progress[index - 1] ?? 0) : 0)) * 100}%`,
                    } as React.CSSProperties}
                  />
                </div>
              )}

              <button
                className={`${styles.stepBtn} ${styles[`stepBtn--${state}`]}`}
                onClick={() => scrollToStep(index)}
                aria-label={`Go to step ${step.num}: ${step.label}`}
                title={step.label}
              >
                {/* dot / filled indicator */}
                <span className={`${styles.dot} ${styles[`dot--${state}`]}`} aria-hidden="true">
                  {state === 'done' ? (
                    /* checkmark */
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                      <polyline
                        points="1.5,5 4,7.5 8.5,2.5"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  ) : (
                    step.num
                  )}
                </span>
                <span className={`${styles.label} ${styles[`label--${state}`]}`}>{step.label}</span>
              </button>
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}
