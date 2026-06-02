import React, { useEffect, useId, useRef, useState } from 'react';
import styles from './styles.module.css';

const FRAMEWORKS = [
  'OpenAI',
  'LangGraph',
  'CrewAI',
  'Google ADK',
  'Smolagents',
  'LiveKit',
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

const TEAL = 'rgba(0, 221, 255, 1)';
const TEAL_LINE = 'rgba(0, 221, 255, 0.45)';
const PURPLE = 'rgba(142, 93, 255, 1)';
const PURPLE_LINE = 'rgba(142, 93, 255, 0.45)';

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
  const stroke = TEAL_LINE;
  const dot = TEAL;

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
  <svg viewBox="0 0 581.263 600" {...props}>
    <g>
      <path d="M238.569,294.85v34.937l1.906,0.938c21.313,10.656,34.532,32.093,34.532,55.905v13.375 l-73.186-36.593c-31.75-15.875-51.812-48.343-51.812-83.843v-129.56l73.186,36.593c31.75,15.875,51.812,48.343,51.812,83.843 v46.312c-6.125-5.469-13-10.187-20.562-13.968L238.569,294.85z" />
      <path d="M431.254,150.008v129.56c0,35.5-20.062,67.968-51.812,83.843l-73.186,36.593v-50.749 c0-23.812,13.218-45.249,34.53-55.905l1.907-0.937v-34.937l-15.875,7.937c-7.562,3.781-14.438,8.5-20.562,13.969v-8.937 c0-35.5,20.062-67.968,51.812-83.843L431.254,150.008z" />
      <path d="M306.26,400.027v44.421l-7.028,3.514c-5.422,2.711-11.805,2.707-17.223-0.011l-6.982-3.503v-44.421 l6.969,3.496c5.426,2.722,11.818,2.722,17.244,0.001l6.971-3.496H306.26z" />
    </g>
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
      aria-label="Agent Kernel runtime flow"
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
            <p className={styles.flowHubTitle}>Agent Kernel</p>
            <p className={styles.flowHubSubtitle}>AK Runtime</p>
            <p className={styles.flowHubMeta}>Sessions | Hooks | Observability</p>
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
