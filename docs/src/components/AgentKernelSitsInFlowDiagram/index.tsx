import React, { useCallback, useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/dist/ScrollTrigger';
import styles from './styles.module.css';

gsap.registerPlugin(ScrollTrigger);

type NodeKind = 'logic' | 'kernel' | 'memory' | 'framework' | 'test';

type FlowNode = {
  id: string;
  label: string;
  kind: NodeKind;
  color?: string;
};

const FLOW_NODES: FlowNode[] = [
  { id: 'logic', label: 'Actual Agent Logic', kind: 'logic', color: '#94a3b8' },
  { id: 'api', label: 'REST API', kind: 'kernel', color: '#60a5fa' },
  { id: 'memory', label: 'Agent Memory', kind: 'memory', color: '#f472b6' },
  {
    id: 'framework',
    label: 'Agentic Framework Implementation',
    kind: 'framework',
    color: '#facc15',
  },
  {
    id: 'testAuto',
    label: 'Agent Test Automation',
    kind: 'test',
    color: '#4ade80',
  },
];

type Point = { x: number; y: number };

type NodeBounds = {
  left: number;
  top: number;
  right: number;
  bottom: number;
  cx: number;
  cy: number;
};

function edgePoint(bounds: NodeBounds, toward: Point, pad = 1): Point {
  const dx = toward.x - bounds.cx;
  const dy = toward.y - bounds.cy;
  if (dx === 0 && dy === 0) return { x: bounds.cx, y: bounds.cy };

  const halfW = (bounds.right - bounds.left) / 2 - pad;
  const halfH = (bounds.bottom - bounds.top) / 2 - pad;
  const scaleX = dx !== 0 ? halfW / Math.abs(dx) : Infinity;
  const scaleY = dy !== 0 ? halfH / Math.abs(dy) : Infinity;
  const scale = Math.min(scaleX, scaleY);
  return {
    x: bounds.cx + dx * scale,
    y: bounds.cy + dy * scale,
  };
}

function pointsToPath(points: Point[]): string {
  return points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
}

function FlowNodeCard({ node }: { node: FlowNode }) {
  const kindClass = styles[`node_${node.kind}`];

  return (
    <div
      data-flow-node={node.id}
      data-kind={node.kind}
      className={`${styles.flowNode} ${kindClass}`}
      style={{ '--node-color': node.color ?? '#00d5be' } as React.CSSProperties}
    >
      <span className={styles.flowNodeLabel}>{node.label}</span>
    </div>
  );
}

export default function AgentKernelSitsInFlowDiagram() {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const nodeRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const setNodeRef = (id: string) => (el: HTMLDivElement | null) => {
    nodeRefs.current[id] = el;
  };

  const drawLines = useCallback(() => {
    const container = containerRef.current;
    const svg = svgRef.current;
    if (!container || !svg) return;

    const cRect = container.getBoundingClientRect();
    svg.setAttribute('viewBox', `0 0 ${cRect.width} ${cRect.height}`);
    svg.innerHTML = `
      <defs>
        <marker id="akSitArrowEnd" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="rgba(255,255,255,0.65)" />
        </marker>
        <marker id="akSitArrowStart" markerWidth="8" markerHeight="8" refX="1" refY="4" orient="auto">
          <path d="M8,0 L0,4 L8,8 Z" fill="rgba(255,255,255,0.65)" />
        </marker>
      </defs>`;

    const boundsOf = (id: string): NodeBounds | null => {
      const slot = nodeRefs.current[id];
      if (!slot) return null;
      const el =
        (slot.querySelector('[data-flow-node]') as HTMLElement | null) ??
        (slot.firstElementChild as HTMLElement | null) ??
        slot;
      const r = el.getBoundingClientRect();
      if (r.width === 0) return null;
      return {
        left: r.left - cRect.left,
        top: r.top - cRect.top,
        right: r.right - cRect.left,
        bottom: r.bottom - cRect.top,
        cx: r.left + r.width / 2 - cRect.left,
        cy: r.top + r.height / 2 - cRect.top,
      };
    };

    const appendBidirectional = (points: Point[]) => {
      const basePath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      basePath.setAttribute('d', pointsToPath(points));
      basePath.setAttribute('fill', 'none');
      basePath.setAttribute('stroke', 'rgba(255, 255, 255, 0.2)');
      basePath.setAttribute('stroke-width', '2');
      basePath.setAttribute('marker-start', 'url(#akSitArrowStart)');
      basePath.setAttribute('marker-end', 'url(#akSitArrowEnd)');
      svg.appendChild(basePath);

      const pulsePath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      pulsePath.setAttribute('d', pointsToPath(points));
      pulsePath.setAttribute('fill', 'none');
      pulsePath.setAttribute('stroke', 'rgba(255, 255, 255, 0.7)');
      pulsePath.setAttribute('stroke-width', '2');
      pulsePath.setAttribute('class', styles.pulseFlow);
      svg.appendChild(pulsePath);
    };

    const connectNodes = (from: NodeBounds, to: NodeBounds) => {
      const towardTo = { x: to.cx, y: to.cy };
      const towardFrom = { x: from.cx, y: from.cy };
      const start = edgePoint(from, towardTo);
      const end = edgePoint(to, towardFrom);

      const dx = Math.abs(end.x - start.x);
      const dy = Math.abs(end.y - start.y);

      if (dx < 2 || dy < 2) {
        appendBidirectional([start, end]);
        return;
      }

      const verticalFirst = dy >= dx;
      if (verticalFirst) {
        appendBidirectional([start, { x: start.x, y: end.y }, end]);
      } else {
        appendBidirectional([start, { x: end.x, y: start.y }, end]);
      }
    };

    const logic = boundsOf('logic');
    const api = boundsOf('api');
    const memory = boundsOf('memory');
    const framework = boundsOf('framework');
    const testAuto = boundsOf('testAuto');

    if (logic && api) connectNodes(api, logic);
    if (logic && memory) connectNodes(memory, logic);
    if (logic && framework) connectNodes(framework, logic);

    if (logic && testAuto) {
      const start = edgePoint(testAuto, { x: logic.cx, y: logic.cy });
      const end = edgePoint(logic, { x: testAuto.cx, y: testAuto.cy });
      appendBidirectional([start, end]);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(drawLines, 100);
    const ro = new ResizeObserver(drawLines);
    if (containerRef.current) ro.observe(containerRef.current);
    window.addEventListener('resize', drawLines);
    return () => {
      clearTimeout(timer);
      ro.disconnect();
      window.removeEventListener('resize', drawLines);
    };
  }, [drawLines]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const nodes = container.querySelectorAll(`.${styles.flowNode}`);
    const tween = gsap.fromTo(
      nodes,
      { opacity: 0, y: 16 },
      {
        opacity: 1,
        y: 0,
        duration: 0.5,
        stagger: 0.05,
        ease: 'power2.out',
        scrollTrigger: {
          trigger: container,
          start: 'top 82%',
          once: true,
        },
        onComplete: drawLines,
        clearProps: 'transform',
      }
    );

    return () => {
      tween.scrollTrigger?.kill();
      tween.kill();
    };
  }, [drawLines]);

  const getNode = (id: string) => FLOW_NODES.find((n) => n.id === id)!;

  return (
    <figure
      className={styles.figure}
      aria-label="How Agent Kernel sits in: kernel-provided components surround user-defined actual agent logic"
    >
      <div ref={containerRef} className={styles.flowScene}>
        <svg ref={svgRef} className={styles.flowSvg} aria-hidden="true" />

        <div ref={setNodeRef('api')} className={styles.slotApi}>
          <FlowNodeCard node={getNode('api')} />
        </div>

        <div ref={setNodeRef('logic')} className={styles.slotLogic}>
          <FlowNodeCard node={getNode('logic')} />
        </div>

        <div ref={setNodeRef('memory')} className={styles.slotMemory}>
          <FlowNodeCard node={getNode('memory')} />
        </div>

        <div ref={setNodeRef('testAuto')} className={styles.slotTestAuto}>
          <FlowNodeCard node={getNode('testAuto')} />
        </div>

        <div className={styles.deploymentZone}>
          <p className={styles.deploymentLabel}>Deployment</p>
          <div ref={setNodeRef('framework')} className={styles.slotFramework}>
            <FlowNodeCard node={getNode('framework')} />
          </div>
        </div>
      </div>
    </figure>
  );
}
