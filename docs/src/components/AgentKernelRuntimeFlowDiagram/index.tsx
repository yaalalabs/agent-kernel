import { brandRgba } from '@site/src/lib/brand';
import React, { useEffect, useId, useRef, useState } from 'react';
import styles from './styles.module.css';

const FRAMEWORKS = [
  'OpenAI',
  'LangGraph',
  'CrewAI',
  'Google ADK',
  'Smolagents',
  'Pydantic AI',
  'Microsoft Agent Framework',
];

const DEPLOY_TARGETS = [
  'AWS Lambda / ECS',
  'Azure Functions / ACA',
  'GCP Cloud Run',
  'On-prem / Docker',
];

const USER_CHANNELS = [
  'Slack · Teams · Gmail',
  'REST · MCP · A2A',
  'Telegram · Messenger',
  'WhatsApp · Instagram',
  'LiveKit',
];

const FOOTER_ITEMS = [
  {
    title: 'Framework-neutral',
    description: 'Bring in LangGraph / CrewAI without rewriting the framework',
    accent: 'framework',
  },
  {
    title: 'Cloud-agnostic',
    description: 'Same code → AWS, Azure, or on-prem (Terraform included)',
    accent: 'cloud',
  },
  {
    title: 'Production-ready',
    description: 'Sessions, hooks, observability and fault tolerance built-in',
    accent: 'production',
  },
  {
    title: 'Lightweight',
    description: 'A thin adapter — not another heavy abstraction to learn',
    accent: 'lightweight',
  },
] as const;

const TEAL = brandRgba('ice', 1);
const TEAL_LINE = brandRgba('ice', 0.45);
const PURPLE = brandRgba('sky', 1);
const PURPLE_LINE = brandRgba('sky', 0.45);

function FlowArrow({
  variant,
  visible,
  animate,
}: {
  variant: 'cyan' | 'purple';
  visible: boolean;
  animate: boolean;
}) {
  const uid = useId().replace(/:/g, '');
  const pathId = `${uid}-${variant}`;
  const isCyan = variant === 'cyan';
  const stroke = isCyan ? TEAL_LINE : PURPLE_LINE;
  const dot = isCyan ? TEAL : PURPLE;

  return (
    <div
      className={`${styles.flowArrow} ${visible ? styles.flowArrowVisible : ''}`}
      aria-hidden="true"
    >
      <svg viewBox="0 0 40 24" fill="none">
        <defs>
          <path id={pathId} d="M 4 12 L 30 12" />
          <filter id={`${pathId}-glow`} x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <path
          className={styles.flowArrowLine}
          d="M2 12h28"
          stroke={stroke}
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeDasharray="6 4"
        />
        <path
          d="M26 6l6 6-6 6"
          stroke={stroke}
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {visible && animate && (
          <circle r="2.5" fill={dot} filter={`url(#${pathId}-glow)`} opacity="0.95">
            <animateMotion
              dur={isCyan ? '1.5s' : '1.7s'}
              repeatCount="indefinite"
              begin={isCyan ? '0.4s' : '0.9s'}
            >
              <mpath href={`#${pathId}`} />
            </animateMotion>
          </circle>
        )}
      </svg>
    </div>
  );
}

function FlowColumn({
  label,
  items,
  visible,
  baseDelay,
}: {
  label: string;
  items: readonly string[];
  visible: boolean;
  baseDelay: number;
}) {
  return (
    <div
      className={`${styles.flowColumn} ${visible ? styles.flowColumnVisible : ''}`}
      style={{ '--col-delay': `${baseDelay}ms` } as React.CSSProperties}
    >
      <p className={styles.flowColumnLabel}>{label}</p>
      <ul className={styles.flowItemList}>
        {items.map((item, i) => (
          <li
            key={item}
            className={styles.flowItem}
            style={{ '--item-delay': `${baseDelay + i * 55}ms` } as React.CSSProperties}
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

const FlowHubIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="-45 -45 176.86 176.85" {...props}>
    <path d="M19.74,39.48v15.79l12.48,5.06c4.39,1.76,7.26,6.01,7.26,10.73v15.79l-27.78-11.11c-7.07-2.83-11.7-9.67-11.7-17.27V0l27.79,11.11c7.06,2.83,11.69,9.67,11.69,17.27v19.07L19.74,39.48Z" />
    <path d="M86.86,0v58.47c0,7.6-4.64,14.44-11.7,17.27l-27.78,11.11v-23.69c0-4.72,2.87-8.97,7.26-10.73l12.48-5.06v-15.79l-19.74,7.97v-11.17c0-7.6,4.63-14.44,11.69-17.27L86.86,0Z" />
  </svg>
);

export default function AgentKernelRuntimeFlowDiagram() {
  const panelRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [animate, setAnimate] = useState(false);

  useEffect(() => {
    if (
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      setVisible(true);
      return;
    }

    const el = panelRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.15 },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return;
    if (
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      return;
    }
    const timer = window.setTimeout(() => setAnimate(true), 500);
    return () => window.clearTimeout(timer);
  }, [visible]);

  return (
    <div
      ref={panelRef}
      className={`${styles.flowPanel} ${visible ? styles.flowPanelVisible : ''}`}
      aria-label="Open Agent Kernel runtime flow"
    >
      <p className={styles.flowScrollHint} aria-hidden="true">
        Scroll horizontally to see the full flow
      </p>

      <div className={styles.flowDiagramWrap}>
        <div className={styles.flowDiagram}>
          <FlowColumn label="BRING YOUR FRAMEWORK" items={FRAMEWORKS} visible={visible} baseDelay={80} />

          <FlowArrow variant="cyan" visible={visible} animate={animate} />

          <div
            className={`${styles.flowHub} ${visible ? styles.flowHubVisible : ''}`}
            style={{ '--col-delay': '420ms' } as React.CSSProperties}
          >
            <FlowHubIcon className={styles.flowHubLogo} />
            <p className={styles.flowHubTitle}>OAK</p>
            <p className={styles.flowHubSubtitle}>Runtime</p>
            <p className={styles.flowHubMeta}>Sessions | Hooks | Observability | Sandbox</p>
          </div>

          <FlowArrow variant="purple" visible={visible} animate={animate} />

          <FlowColumn label="DEPLOY ANYWHERE" items={DEPLOY_TARGETS} visible={visible} baseDelay={520} />

          <FlowColumn label="REACH USERS ON" items={USER_CHANNELS} visible={visible} baseDelay={680} />
        </div>
      </div>

      <div className={styles.flowFooter}>
        {FOOTER_ITEMS.map((item, i) => (
          <article
            key={item.title}
            className={`${styles.flowFooterCard} ${styles[`flowFooterAccent_${item.accent}`]} ${visible ? styles.flowFooterCardVisible : ''
              }`}
            style={{ '--footer-delay': `${760 + i * 70}ms` } as React.CSSProperties}
          >
            <h3 className={styles.flowFooterTitle}>{item.title}</h3>
            <p className={styles.flowFooterDesc}>{item.description}</p>
          </article>
        ))}
      </div>
    </div>
  );
}
