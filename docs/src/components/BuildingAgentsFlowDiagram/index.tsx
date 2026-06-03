import React, { useCallback, useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/dist/ScrollTrigger';
import styles from './styles.module.css';

gsap.registerPlugin(ScrollTrigger);

type NodeKind = 'message' | 'guardrail' | 'memory' | 'supervisor' | 'agent' | 'tool';

type FlowNode = {
  id: string;
  label: string;
  kind: NodeKind;
  color?: string;
};

const FLOW_NODES: FlowNode[] = [
  { id: 'input', label: 'Input Message', kind: 'message', color: '#f472b6' },
  { id: 'guardIn', label: 'Guardrails', kind: 'guardrail', color: '#c084fc' },
  { id: 'memory', label: 'Agent Memory', kind: 'memory', color: '#4ade80' },
  { id: 'supervisor', label: 'Supervisor Agent', kind: 'supervisor', color: '#00ddff' },
  { id: 'general', label: 'General Agent', kind: 'agent', color: '#c084fc' },
  { id: 'travel', label: 'Travel Expert Agent', kind: 'agent', color: '#c084fc' },
  { id: 'booking', label: 'Booking Agent', kind: 'agent', color: '#c084fc' },
  { id: 'toolDest', label: 'Destination Discovery Tool', kind: 'tool', color: '#facc15' },
  { id: 'toolKnowledge', label: 'Localized Knowledge Query Tool', kind: 'tool', color: '#facc15' },
  { id: 'toolFlight', label: 'Flight Booking Tool', kind: 'tool', color: '#facc15' },
  { id: 'toolHotel', label: 'Hotel Booking Tool', kind: 'tool', color: '#facc15' },
  { id: 'toolLang', label: 'Language Detection and Translation Tool', kind: 'tool', color: '#facc15' },
  { id: 'guardOut', label: 'Guardrails', kind: 'guardrail', color: '#c084fc' },
  { id: 'output', label: 'Output Message', kind: 'message', color: '#f472b6' },
];

const CONNECTIONS: Array<{
  from: string;
  to: string;
  dashed?: boolean;
}> = [
  { from: 'input', to: 'guardIn' },
  { from: 'guardIn', to: 'supervisor' },
  { from: 'supervisor', to: 'general', dashed: true },
  { from: 'supervisor', to: 'travel', dashed: true },
  { from: 'supervisor', to: 'booking', dashed: true },
  { from: 'travel', to: 'toolFlight', dashed: true },
  { from: 'travel', to: 'toolHotel', dashed: true },
  { from: 'travel', to: 'toolKnowledge', dashed: true },
  { from: 'travel', to: 'toolDest', dashed: true },
  { from: 'travel', to: 'toolLang', dashed: true },
  { from: 'booking', to: 'toolKnowledge', dashed: true },
  { from: 'booking', to: 'toolDest', dashed: true },
  { from: 'booking', to: 'toolLang', dashed: true },
  { from: 'booking', to: 'toolFlight', dashed: true },
  { from: 'booking', to: 'toolHotel', dashed: true },
  { from: 'coreZone', to: 'guardOut' },
  { from: 'guardOut', to: 'output' },
];

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

  const isCircle = bounds.kind === 'supervisor' || bounds.kind === 'agent';
  if (isCircle) {
    const halfW = (bounds.right - bounds.left) / 2;
    const halfH = (bounds.bottom - bounds.top) / 2;
    const radius = Math.min(halfW, halfH) - pad;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    return {
      x: bounds.cx + (dx / len) * radius,
      y: bounds.cy + (dy / len) * radius,
    };
  }

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

function shortenSegment(
  start: Point,
  end: Point,
  trimEnd = 0,
  trimStart = 0
): { x1: number; y1: number; x2: number; y2: number } {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  return {
    x1: start.x + (dx / len) * trimStart,
    y1: start.y + (dy / len) * trimStart,
    x2: end.x - (dx / len) * trimEnd,
    y2: end.y - (dy / len) * trimEnd,
  };
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

export default function BuildingAgentsFlowDiagram() {
  const containerRef = useRef<HTMLDivElement>(null);
  const coreZoneRef = useRef<HTMLDivElement>(null);
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
        <marker id="baArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="rgba(255,255,255,0.65)" />
        </marker>
      </defs>`;

    const boundsOf = (id: string): NodeBounds | null => {
      if (id === 'coreZone') {
        const zone = coreZoneRef.current;
        if (!zone) return null;
        const r = zone.getBoundingClientRect();
        if (r.width === 0) return null;
        return {
          left: r.left - cRect.left,
          top: r.top - cRect.top,
          right: r.right - cRect.left,
          bottom: r.bottom - cRect.top,
          cx: r.left + r.width / 2 - cRect.left,
          cy: r.top + r.height / 2 - cRect.top,
          kind: 'message',
        };
      }

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

    // ── Helper: draw a solid pulse line (used for main flow) ──────────────
    const drawSolidLine = (
      x1: number, y1: number,
      x2: number, y2: number,
      withArrow = true
    ) => {
      const dx = x2 - x1;
      const dy = y2 - y1;
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      const trimEnd = withArrow ? 9 : 0;
      const ex = x2 - (dx / len) * trimEnd;
      const ey = y2 - (dy / len) * trimEnd;

      const base = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      base.setAttribute('x1', String(x1));
      base.setAttribute('y1', String(y1));
      base.setAttribute('x2', String(ex));
      base.setAttribute('y2', String(ey));
      base.setAttribute('stroke', 'rgba(255,255,255,0.2)');
      base.setAttribute('stroke-width', '2');
      base.setAttribute('fill', 'none');
      svg.appendChild(base);

      const pulse = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      pulse.setAttribute('x1', String(x1));
      pulse.setAttribute('y1', String(y1));
      pulse.setAttribute('x2', String(ex));
      pulse.setAttribute('y2', String(ey));
      pulse.setAttribute('stroke', 'rgba(255,255,255,0.7)');
      pulse.setAttribute('stroke-width', '2');
      pulse.setAttribute('fill', 'none');
      pulse.setAttribute('class', styles.pulseFlow);
      if (withArrow) pulse.setAttribute('marker-end', 'url(#baArrow)');
      svg.appendChild(pulse);
    };

    // ── Helper: draw orthogonal comb from one agent to multiple tools ─────
    // Pattern: horizontal from agent right edge → vertical trunk → horizontal branches to each tool
    const drawCombLines = (agentId: string, toolIds: string[]) => {
      const agent = boundsOf(agentId);
      if (!agent) return;

      const toolBounds = toolIds
        .map((id) => ({ id, b: boundsOf(id) }))
        .filter((t): t is { id: string; b: NodeBounds } => t.b !== null);
      if (toolBounds.length === 0) return;

      // Start: right edge of agent circle
      const startX = agent.right;
      const startY = agent.cy;

      // Trunk X: halfway between agent right and tool left edge
      const firstTool = toolBounds[0].b;
      const trunkX = firstTool.left - 18;

      // Vertical extent of trunk: from first tool cy to last tool cy
      const topY = toolBounds[0].b.cy;
      const botY = toolBounds[toolBounds.length - 1].b.cy;

      const STROKE = 'rgba(255,255,255,0.22)';
      const DASH = '5 5';
      const W = '1.5';

      const mkPath = (d: string) => {
        const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        p.setAttribute('d', d);
        p.setAttribute('fill', 'none');
        p.setAttribute('stroke', STROKE);
        p.setAttribute('stroke-width', W);
        p.setAttribute('stroke-dasharray', DASH);
        p.setAttribute('class', styles.dashedFlow);
        svg.appendChild(p);
      };

      // Horizontal stem: agent right → trunk
      mkPath(`M ${startX} ${startY} H ${trunkX}`);

      // Vertical trunk
      mkPath(`M ${trunkX} ${topY} V ${botY}`);

      // Horizontal branches: trunk → each tool left edge
      toolBounds.forEach(({ b }) => {
        mkPath(`M ${trunkX} ${b.cy} H ${b.left}`);
      });
    };

    // 1. Input Message → Guardrails (forced horizontal, right→left)
    const inputB   = boundsOf('input');
    const guardInB = boundsOf('guardIn');
    if (inputB && guardInB) {
      drawSolidLine(inputB.right, inputB.cy, guardInB.left, guardInB.cy, true);
    }

    // 2. Guardrails → Supervisor Agent (right edge of guardIn → circle edge)
    const supervisorB = boundsOf('supervisor');
    if (guardInB && supervisorB) {
      const start = edgePoint(guardInB,    { x: supervisorB.cx, y: supervisorB.cy });
      const end   = edgePoint(supervisorB, { x: guardInB.cx,    y: guardInB.cy });
      drawSolidLine(start.x, start.y, end.x, end.y, true);
    }

    // 3. coreZone right edge → output Guardrails left edge (forced horizontal)
    const coreB     = boundsOf('coreZone');
    const guardOutB = boundsOf('guardOut');
    if (coreB && guardOutB) {
      drawSolidLine(coreB.right, coreB.cy, guardOutB.left, guardOutB.cy, true);
    }

    // 4. output Guardrails → Output Message (forced vertical, bottom→top)
    const outputB = boundsOf('output');
    if (guardOutB && outputB) {
      drawSolidLine(guardOutB.cx, guardOutB.bottom, outputB.cx, outputB.top, true);
    }

    // ── Supervisor → agents (straight dashed, short) ──────────────────────
    const supervisorAgentConns: Array<[string, string]> = [
      ['supervisor', 'general'],
      ['supervisor', 'travel'],
      ['supervisor', 'booking'],
    ];

    supervisorAgentConns.forEach(([fromId, toId]) => {
      const from = boundsOf(fromId);
      const to   = boundsOf(toId);
      if (!from || !to) return;

      const start = edgePoint(from, { x: to.cx, y: to.cy });
      const end   = edgePoint(to,   { x: from.cx, y: from.cy });

      const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      p.setAttribute('d', `M ${start.x} ${start.y} L ${end.x} ${end.y}`);
      p.setAttribute('fill', 'none');
      p.setAttribute('stroke', 'rgba(255,255,255,0.22)');
      p.setAttribute('stroke-width', '1.5');
      p.setAttribute('stroke-dasharray', '5 5');
      p.setAttribute('class', styles.dashedFlow);
      svg.appendChild(p);
    });

    // ── Agent → tools: orthogonal comb ───────────────────────────────────

    // Travel expert → all 5 tools
    drawCombLines('travel', ['toolDest', 'toolKnowledge', 'toolFlight', 'toolHotel', 'toolLang']);

    // Booking agent → its tools
    drawCombLines('booking', ['toolKnowledge', 'toolDest', 'toolLang', 'toolFlight', 'toolHotel']);

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
      aria-label="Multi-agent architecture: input passes through guardrails, a supervisor coordinates specialist agents with tools, then output guardrails produce the response"
    >
      <div ref={containerRef} className={styles.flowScene}>
        <svg ref={svgRef} className={styles.flowSvg} aria-hidden="true" />

        <div ref={setNodeRef('input')} className={styles.slotInput}>
          <FlowNodeCard node={getNode('input')} />
        </div>

        <div ref={setNodeRef('guardIn')} className={styles.slotGuardIn}>
          <FlowNodeCard node={getNode('guardIn')} />
        </div>

        <div ref={coreZoneRef} className={styles.coreZone}>
          <p className={styles.coreZoneLabel}>Multi-Agent System</p>

          <div ref={setNodeRef('memory')} className={styles.slotMemory}>
            <FlowNodeCard node={getNode('memory')} />
          </div>

          <div className={styles.coreRow}>
            <div ref={setNodeRef('supervisor')} className={styles.slotSupervisor}>
              <FlowNodeCard node={getNode('supervisor')} />
            </div>

            <div className={styles.agentsCol}>
              <div ref={setNodeRef('general')} className={styles.slotAgent}>
                <FlowNodeCard node={getNode('general')} />
              </div>
              <div ref={setNodeRef('travel')} className={styles.slotAgent}>
                <FlowNodeCard node={getNode('travel')} />
              </div>
              <div ref={setNodeRef('booking')} className={styles.slotAgent}>
                <FlowNodeCard node={getNode('booking')} />
              </div>
            </div>

            <div className={styles.toolsCol}>
              <div ref={setNodeRef('toolDest')} className={styles.slotTool}>
                <FlowNodeCard node={getNode('toolDest')} />
              </div>
              <div ref={setNodeRef('toolKnowledge')} className={styles.slotTool}>
                <FlowNodeCard node={getNode('toolKnowledge')} />
              </div>
              <div ref={setNodeRef('toolFlight')} className={styles.slotTool}>
                <FlowNodeCard node={getNode('toolFlight')} />
              </div>
              <div ref={setNodeRef('toolHotel')} className={styles.slotTool}>
                <FlowNodeCard node={getNode('toolHotel')} />
              </div>
              <div ref={setNodeRef('toolLang')} className={styles.slotTool}>
                <FlowNodeCard node={getNode('toolLang')} />
              </div>
            </div>
          </div>
        </div>

        <div className={styles.outputStack}>
          <div ref={setNodeRef('guardOut')} className={styles.slotGuardOut}>
            <FlowNodeCard node={getNode('guardOut')} />
          </div>
          <div className={styles.outputConnector} aria-hidden="true" />
          <div ref={setNodeRef('output')} className={styles.slotOutput}>
            <FlowNodeCard node={getNode('output')} />
          </div>
        </div>
      </div>
    </figure>
  );
}
