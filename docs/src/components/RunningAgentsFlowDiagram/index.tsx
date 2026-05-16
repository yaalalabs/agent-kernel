import React, { useCallback, useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/dist/ScrollTrigger';
import styles from './styles.module.css';

gsap.registerPlugin(ScrollTrigger);

type NodeKind = 'api' | 'message' | 'memory' | 'runner' | 'external';

type FlowNode = {
  id: string;
  label: string;
  subtitle?: string;
  kind: NodeKind;
  color?: string;
};

const FLOW_NODES: FlowNode[] = [
  { id: 'api', label: 'REST API', kind: 'api', color: '#f472b6' },
  { id: 'input', label: 'Input Message', kind: 'message', color: '#60a5fa' },
  { id: 'runner', label: 'Agent Logic Runner', subtitle: '(REST Server / Container / Lambda etc)', kind: 'runner', color: '#c084fc' },
  { id: 'memory', label: 'Agent Memory', kind: 'memory', color: '#f472b6' },
  { id: 'llm', label: 'LLM', kind: 'external', color: '#facc15' },
  { id: 'knowledge', label: 'Knowledge Graph', kind: 'external', color: '#facc15' },
  { id: 'dataSources', label: 'Other Data Sources', kind: 'external', color: '#facc15' },
  { id: 'otherApis', label: 'Other APIs', kind: 'external', color: '#facc15' },
  { id: 'output', label: 'Output Message', kind: 'message', color: '#60a5fa' },
];

const EXTERNAL_IDS = ['llm', 'knowledge', 'dataSources', 'otherApis'];

type Point = { x: number; y: number };

type NodeBounds = {
  left: number;
  top: number;
  right: number;
  bottom: number;
  cx: number;
  cy: number;
  kind: NodeKind;
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

function shortenPolyline(points: Point[], trimEnd = 9, trimStart = 0): Point[] {
  if (points.length < 2) return points;

  const result = [...points];
  if (trimStart > 0) {
    const [a, b] = result;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    result[0] = {
      x: a.x + (dx / len) * trimStart,
      y: a.y + (dy / len) * trimStart,
    };
  }
  if (trimEnd > 0) {
    const a = result[result.length - 2];
    const b = result[result.length - 1];
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    result[result.length - 1] = {
      x: b.x - (dx / len) * trimEnd,
      y: b.y - (dy / len) * trimEnd,
    };
  }
  return result;
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
      <span className={styles.flowNodeLabel}>
        {node.label}
        {node.subtitle ? <span className={styles.runnerSubtitle}>{node.subtitle}</span> : null}
      </span>
    </div>
  );
}

export default function RunningAgentsFlowDiagram() {
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
        <marker id="raArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="rgba(255,255,255,0.65)" />
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
      const kind = (el.getAttribute('data-kind') as NodeKind) || 'message';
      return {
        left: r.left - cRect.left,
        top: r.top - cRect.top,
        right: r.right - cRect.left,
        bottom: r.bottom - cRect.top,
        cx: r.left + r.width / 2 - cRect.left,
        cy: r.top + r.height / 2 - cRect.top,
        kind,
      };
    };

    const appendPath = (points: Point[], dashed = false) => {
      // Only trim simple two-point segments; ortho paths already end on node edges
      const trimEnd = !dashed && points.length === 2 ? 9 : 0;
      const trimmed = dashed ? points : shortenPolyline(points, trimEnd);
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', pointsToPath(trimmed));
      path.setAttribute('fill', 'none');
      if (dashed) {
        path.setAttribute('stroke', 'rgba(255, 255, 255, 0.4)');
        path.setAttribute('stroke-width', '1.5');
        path.setAttribute('stroke-dasharray', '5 5');
      } else {
        path.setAttribute('stroke', 'rgba(255, 255, 255, 0.65)');
        path.setAttribute('stroke-width', '2');
        path.setAttribute('marker-end', 'url(#raArrow)');
      }
      svg.appendChild(path);
    };

    const appendLine = (from: string, to: string, dashed = false) => {
      const fromBounds = boundsOf(from);
      const toBounds = boundsOf(to);
      if (!fromBounds || !toBounds) return;

      const targetCenter = { x: toBounds.cx, y: toBounds.cy };
      const sourceCenter = { x: fromBounds.cx, y: fromBounds.cy };
      const start = edgePoint(fromBounds, targetCenter);
      const end = edgePoint(toBounds, sourceCenter);
      appendPath([start, end], dashed);
    };

    appendLine('api', 'input');
    appendLine('input', 'runner');

    const runner = boundsOf('runner');
    const output = boundsOf('output');
    const api = boundsOf('api');
    if (runner && output) {
      const outTarget = { x: runner.cx, y: output.cy };
      const end = edgePoint(output, outTarget);
      appendPath([
        { x: runner.cx, y: runner.bottom },
        { x: runner.cx, y: output.cy },
        end,
      ]);
    }

    if (output && api) {
      const corner = { x: api.cx, y: output.cy };
      const start = edgePoint(output, corner);
      const end = edgePoint(api, corner);
      appendPath([start, corner, end]);
    }

    const memory = boundsOf('memory');
    if (runner && memory) {
      appendPath(
        [
          { x: runner.cx, y: runner.top },
          { x: memory.cx, y: memory.bottom },
        ],
        true
      );
    }

    const externalBounds = EXTERNAL_IDS.map((id) => boundsOf(id)).filter(Boolean) as NodeBounds[];
    if (runner && externalBounds.length > 0) {
      const busX = runner.right + (externalBounds[0].left - runner.right) * 0.45;
      const start = { x: runner.right, y: runner.cy };
      appendPath([start, { x: busX, y: runner.cy }], true);

      externalBounds.forEach((ext) => {
        const end = edgePoint(ext, { x: busX, y: ext.cy });
        appendPath(
          [
            { x: busX, y: runner.cy },
            { x: busX, y: ext.cy },
            end,
          ],
          true
        );
      });
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
      aria-label="Running AI agents: REST API sends input through an agent logic runner with memory and external services, then returns output to the API"
    >
      <div ref={containerRef} className={styles.flowScene}>
        <svg ref={svgRef} className={styles.flowSvg} aria-hidden="true" />

        <div ref={setNodeRef('api')} className={styles.slotApi}>
          <FlowNodeCard node={getNode('api')} />
        </div>

        <div className={styles.slotInputNotes}>
          <ul className={styles.inputNotes}>
            <li>Ordering</li>
            <li>Double texting</li>
            <li>Thread management</li>
          </ul>
        </div>

        <div ref={setNodeRef('input')} className={styles.slotInput}>
          <FlowNodeCard node={getNode('input')} />
        </div>

        <div ref={setNodeRef('memory')} className={styles.slotMemory}>
          <FlowNodeCard node={getNode('memory')} />
        </div>

        <div ref={setNodeRef('runner')} className={styles.slotRunner}>
          <FlowNodeCard node={getNode('runner')} />
        </div>

        <div className={styles.externalCol}>
          {EXTERNAL_IDS.map((id) => (
            <div key={id} ref={setNodeRef(id)}>
              <FlowNodeCard node={getNode(id)} />
            </div>
          ))}
        </div>

        <div ref={setNodeRef('output')} className={styles.slotOutput}>
          <FlowNodeCard node={getNode('output')} />
        </div>
      </div>
    </figure>
  );
}
