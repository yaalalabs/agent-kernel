import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "@docusaurus/Link";
import clsx from "clsx";
import styles from "./styles.module.css";
import {
  CORE_LABEL,
  CORE_PILLS,
  DESTINATIONS,
  DESTINATIONS_LABEL,
  FLOW_WORDS,
  SOURCES,
  SOURCES_LABEL,
  type ArchCard,
  type Chip,
} from "./data";

/** Below this width the three columns stack and the connector overlay is not drawn. Keep in sync with styles.module.css. */
const STACKED_BREAKPOINT = 1100;

/** Gap between a connector's end and the core box, so the arrowhead sits just outside the border. */
const CORE_INSET = 6;

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Connector {
  d: string;
  kind: "source" | "destination" | "pill";
}

function rectWithin(el: Element, container: Element): Rect {
  const c = container.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  return { x: r.left - c.left, y: r.top - c.top, w: r.width, h: r.height };
}

/** A horizontal-vertical-horizontal path from (x1, y1) to (x2, y2) that turns at xm, with rounded corners. */
function elbowPath(x1: number, y1: number, xm: number, y2: number, x2: number, radius = 12): string {
  if (Math.abs(y2 - y1) < 1) {
    return `M ${x1} ${y1} H ${x2}`;
  }
  const dirX1 = Math.sign(xm - x1);
  const dirY = Math.sign(y2 - y1);
  const dirX2 = Math.sign(x2 - xm);
  const r = Math.min(radius, Math.abs(y2 - y1) / 2, Math.abs(xm - x1), Math.abs(x2 - xm));
  return [
    `M ${x1} ${y1}`,
    `H ${xm - dirX1 * r}`,
    `Q ${xm} ${y1} ${xm} ${y1 + dirY * r}`,
    `V ${y2 - dirY * r}`,
    `Q ${xm} ${y2} ${xm + dirX2 * r} ${y2}`,
    `H ${x2}`,
  ].join(" ");
}

function ChipLink({ chip }: { chip: Chip }) {
  return (
    <Link to={chip.href} className={styles.chip} title={chip.name} aria-label={chip.name}>
      {chip.icon ?? (
        <img
          src={chip.logo}
          alt=""
          loading="lazy"
          className={clsx(styles.chipImg, chip.mono && styles.mono)}
        />
      )}
    </Link>
  );
}

const Card = React.forwardRef<HTMLDivElement, { card: ArchCard }>(function Card({ card }, ref) {
  return (
    <div ref={ref} className={styles.card}>
      <div className={styles.cardTitle}>{card.title}</div>
      <div className={styles.chipRow}>
        {card.chips.map((chip) => (
          <ChipLink key={chip.name} chip={chip} />
        ))}
      </div>
    </div>
  );
});

function ColumnLabel({ children, align }: { children: React.ReactNode; align: "start" | "center" | "end" }) {
  return (
    <div className={clsx(styles.columnLabel, styles[`align-${align}`])}>
      <span className={styles.columnRule} aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}

export default function ArchitectureOverview() {
  const diagramRef = useRef<HTMLDivElement>(null);
  const coreRef = useRef<HTMLDivElement>(null);
  const sourceRefs = useRef<(HTMLDivElement | null)[]>([]);
  const destinationRefs = useRef<(HTMLDivElement | null)[]>([]);
  const pillRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);

  const measure = useCallback(() => {
    const diagram = diagramRef.current;
    const core = coreRef.current;
    if (!diagram || !core) return;
    if (window.innerWidth <= STACKED_BREAKPOINT) {
      setConnectors([]);
      return;
    }

    const box = rectWithin(core, diagram);
    const attachY = (index: number, count: number) => box.y + (box.h * (index + 1)) / (count + 1);
    const next: Connector[] = [];

    const sources = sourceRefs.current.filter((el): el is HTMLDivElement => el !== null);
    sources.forEach((el, index) => {
      const r = rectWithin(el, diagram);
      const x1 = r.x + r.w;
      const y1 = r.y + r.h / 2;
      const x2 = box.x - CORE_INSET;
      const xm = x1 + (x2 - x1) * 0.5;
      next.push({ d: elbowPath(x1, y1, xm, attachY(index, sources.length), x2), kind: "source" });
    });

    const destinations = destinationRefs.current.filter((el): el is HTMLDivElement => el !== null);
    destinations.forEach((el, index) => {
      const r = rectWithin(el, diagram);
      // Same gap as the core end of a source path, so the arrowhead sits just outside the card border.
      const x1 = r.x - CORE_INSET;
      const y1 = r.y + r.h / 2;
      const x2 = box.x + box.w + CORE_INSET;
      const xm = x1 - (x1 - x2) * 0.5;
      next.push({ d: elbowPath(x1, y1, xm, attachY(index, destinations.length), x2), kind: "destination" });
    });

    // Each pill ties to the nearest corner of the core with a short dotted lead.
    const coreCenterX = box.x + box.w / 2;
    const coreCenterY = box.y + box.h / 2;
    pillRefs.current.forEach((el) => {
      if (!el) return;
      const r = rectWithin(el, diagram);
      const pillCenterX = r.x + r.w / 2;
      const pillCenterY = r.y + r.h / 2;
      const left = pillCenterX < coreCenterX;
      const above = pillCenterY < coreCenterY;
      const startX = left ? r.x + r.w : r.x;
      const startY = above ? r.y + r.h : r.y;
      const endX = left ? box.x : box.x + box.w;
      const endY = above ? box.y : box.y + box.h;
      next.push({ d: `M ${startX} ${startY} L ${endX} ${endY}`, kind: "pill" });
    });

    setConnectors(next);
  }, []);

  useEffect(() => {
    measure();
    const observer = new ResizeObserver(() => measure());
    if (diagramRef.current) observer.observe(diagramRef.current);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [measure]);

  return (
    <section id="architecture" className={styles.section}>
      <div className={styles.topGlow} />

      <div className={styles.header}>
        <div className={styles.badge}>
          <span className={styles.badgeStar}>✦</span>
          Architecture
        </div>
        <h2 className={styles.title}>One runtime between your channels and your agents</h2>
        <p className={styles.subtitle}>
          Requests arrive from any channel or protocol. Agent Kernel runs your framework-native
          agents with sessions, guardrails, queues and sandboxes, on whichever cloud you choose.
        </p>
      </div>

      <div ref={diagramRef} className={styles.diagram}>
        <svg className={styles.connectors} aria-hidden="true">
          <defs>
            <marker id="ak-arch-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 1 1 L 9 5 L 1 9" className={styles.arrowHead} />
            </marker>
          </defs>
          {connectors.map((connector, index) => {
            // Requests flow into the core and responses back out, so a source path carries its arrowhead
            // at the core end and a destination path at the card end (the marker's auto-start-reverse
            // orientation flips it to point into the card).
            const arrow = "url(#ak-arch-arrow)";
            return (
              <path
                key={index}
                d={connector.d}
                className={clsx(styles.connector, styles[`connector-${connector.kind}`])}
                markerEnd={connector.kind === "source" ? arrow : undefined}
                markerStart={connector.kind === "destination" ? arrow : undefined}
              />
            );
          })}
        </svg>

        <div className={styles.columns}>
          <div className={styles.column}>
            <ColumnLabel align="start">{SOURCES_LABEL}</ColumnLabel>
            {SOURCES.map((card, index) => (
              <Card
                key={card.title}
                card={card}
                ref={(el) => {
                  sourceRefs.current[index] = el;
                }}
              />
            ))}
          </div>

          <div className={styles.stackArrow} aria-hidden="true">↓</div>

          <div className={clsx(styles.column, styles.centerColumn)}>
            <ColumnLabel align="center">{CORE_LABEL}</ColumnLabel>
            <div className={styles.core}>
              <div className={styles.coreGlow} aria-hidden="true" />
              <div className={styles.coreRing} aria-hidden="true" />
              <div ref={coreRef} className={styles.coreBox}>
                <img
                  src="/img/branding/agent-kernel-icon-color.svg"
                  alt=""
                  className={styles.coreLogo}
                />
              </div>
              <div className={styles.coreName}>Agent Kernel</div>
              <div className={styles.coreSub}>Runtime</div>
              <div className={styles.pills}>
                {CORE_PILLS.map((pill, index) => (
                  <Link
                    key={pill.label}
                    to={pill.href}
                    className={clsx(styles.pill, styles[`pill-${index}`])}
                    ref={(el) => {
                      pillRefs.current[index] = el;
                    }}
                  >
                    <span className={styles.pillDot} aria-hidden="true" />
                    {pill.label}
                  </Link>
                ))}
              </div>
            </div>
          </div>

          <div className={styles.stackArrow} aria-hidden="true">↓</div>

          <div className={styles.column}>
            <ColumnLabel align="end">{DESTINATIONS_LABEL}</ColumnLabel>
            {DESTINATIONS.map((card, index) => (
              <Card
                key={card.title}
                card={card}
                ref={(el) => {
                  destinationRefs.current[index] = el;
                }}
              />
            ))}
          </div>
        </div>

        <div className={styles.footer}>
          <div className={styles.flowLabel}>
            <span>Request · Inbound</span>
            <span className={styles.flowLine} aria-hidden="true" />
          </div>
          <div className={styles.flowWords}>
            {FLOW_WORDS.map((entry, index) => (
              <React.Fragment key={entry.word}>
                {index > 0 && <span className={styles.flowSeparator} aria-hidden="true">·</span>}
                <span className={clsx(entry.accent && styles.flowAccent)}>{entry.word}</span>
              </React.Fragment>
            ))}
          </div>
          <div className={styles.flowLabel}>
            <span>Response · Outbound</span>
            <span className={styles.flowLine} aria-hidden="true" />
          </div>
        </div>
      </div>
    </section>
  );
}
