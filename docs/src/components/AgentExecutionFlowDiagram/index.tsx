import React, { useCallback, useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/dist/ScrollTrigger';
import {
  MdAssignment,
  MdBolt,
  MdFeedback,
  MdGpsFixed,
  MdHelpOutline,
  MdRefresh,
  MdTrendingUp,
  MdVisibility,
} from 'react-icons/md';
import type { IconType } from 'react-icons';
import styles from './styles.module.css';

gsap.registerPlugin(ScrollTrigger);

type StepId =
  | 'goal'
  | 'plan'
  | 'question'
  | 'act'
  | 'feedback'
  | 'observe'
  | 'improve'
  | 'repeat';

type FlowStep = {
  id: StepId;
  label: string;
  desc: string;
  Icon: IconType;
  variant: string;
};

const FLOW_STEPS: FlowStep[] = [
  {
    id: 'goal',
    label: 'Goal',
    desc: 'Understand the goal',
    Icon: MdGpsFixed,
    variant: styles.node_goal,
  },
  {
    id: 'plan',
    label: 'Plan',
    desc: 'Plan steps',
    Icon: MdAssignment,
    variant: styles.node_plan,
  },
  {
    id: 'question',
    label: 'Question',
    desc: "Clarify what's needed",
    Icon: MdHelpOutline,
    variant: styles.node_question,
  },
  {
    id: 'act',
    label: 'Act',
    desc: 'Take actions',
    Icon: MdBolt,
    variant: styles.node_act,
  },
  {
    id: 'feedback',
    label: 'Get Feedback',
    desc: 'Capture signals and outcomes',
    Icon: MdFeedback,
    variant: styles.node_feedback,
  },
  {
    id: 'observe',
    label: 'Observe',
    desc: 'Observe the results',
    Icon: MdVisibility,
    variant: styles.node_observe,
  },
  {
    id: 'improve',
    label: 'Improve',
    desc: 'Gets smarter',
    Icon: MdTrendingUp,
    variant: styles.node_improve,
  },
  {
    id: 'repeat',
    label: 'Repeat',
    desc: 'Always on, always learning',
    Icon: MdRefresh,
    variant: styles.node_repeat,
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

const LINEAR_CHAIN: Array<[StepId, StepId]> = [
  ['goal', 'plan'],
  ['plan', 'question'],
  ['question', 'act'],
  ['improve', 'repeat'],
];

const ORTHO_BRANCH: Array<[StepId, StepId]> = [
  ['act', 'feedback'],
  ['act', 'observe'],
  ['feedback', 'improve'],
  ['observe', 'improve'],
];

function FlowStepCard({
  step,
  innerRef,
}: {
  step: FlowStep;
  innerRef: (el: HTMLDivElement | null) => void;
}) {
  const { Icon } = step;

  return (
    <div
      ref={innerRef}
      data-flow-node={step.id}
      className={`${styles.flowNode} ${step.variant}`}
    >
      <Icon className={styles.flowIcon} aria-hidden />
      <h4 className={styles.flowLabel}>{step.label}</h4>
      <p className={styles.flowDesc}>{step.desc}</p>
    </div>
  );
}

function orthoPath(from: NodeBounds, to: NodeBounds, trimEnd = 9): string {
  const startX = from.right;
  const startY = from.cy;
  const endX = to.left - trimEnd;
  const endY = to.cy;
  const midX = startX + Math.max(20, (endX - startX) * 0.45);

  return `M ${startX} ${startY} H ${midX} V ${endY} H ${endX}`;
}

function straightSegment(
  from: NodeBounds,
  to: NodeBounds,
  trimEnd = 9
): { x1: number; y1: number; x2: number; y2: number } {
  const start: Point = { x: from.right, y: from.cy };
  const end: Point = { x: to.left - trimEnd, y: to.cy };
  return { x1: start.x, y1: start.y, x2: end.x, y2: end.y };
}

export default function AgentExecutionFlowDiagram() {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const nodeRefs = useRef<Record<StepId, HTMLDivElement | null>>({
    goal: null,
    plan: null,
    question: null,
    act: null,
    feedback: null,
    observe: null,
    improve: null,
    repeat: null,
  });

  const setNodeRef = (id: StepId) => (el: HTMLDivElement | null) => {
    nodeRefs.current[id] = el;
  };

  const drawLines = useCallback(() => {
    const container = containerRef.current;
    const svg = svgRef.current;
    if (!container || !svg) return;

    const cRect = container.getBoundingClientRect();
    if (cRect.width === 0) return;

    svg.setAttribute('viewBox', `0 0 ${cRect.width} ${cRect.height}`);
    svg.innerHTML = `
      <defs>
        <marker id="aeFlowArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="rgba(255,255,255,0.65)" />
        </marker>
      </defs>`;

    const boundsOf = (id: StepId): NodeBounds | null => {
      const el = nodeRefs.current[id];
      if (!el) return null;
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

    const appendPath = (d: string) => {
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', 'rgba(255, 255, 255, 0.65)');
      path.setAttribute('stroke-width', '2');
      path.setAttribute('marker-end', 'url(#aeFlowArrow)');
      svg.appendChild(path);
    };

    const appendLine = (x1: number, y1: number, x2: number, y2: number) => {
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', String(x1));
      line.setAttribute('y1', String(y1));
      line.setAttribute('x2', String(x2));
      line.setAttribute('y2', String(y2));
      line.setAttribute('fill', 'none');
      line.setAttribute('stroke', 'rgba(255, 255, 255, 0.65)');
      line.setAttribute('stroke-width', '2');
      line.setAttribute('marker-end', 'url(#aeFlowArrow)');
      svg.appendChild(line);
    };

    LINEAR_CHAIN.forEach(([fromId, toId]) => {
      const from = boundsOf(fromId);
      const to = boundsOf(toId);
      if (!from || !to) return;
      const seg = straightSegment(from, to);
      appendLine(seg.x1, seg.y1, seg.x2, seg.y2);
    });

    ORTHO_BRANCH.forEach(([fromId, toId]) => {
      const from = boundsOf(fromId);
      const to = boundsOf(toId);
      if (!from || !to) return;
      appendPath(orthoPath(from, to));
    });
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
        duration: 0.55,
        stagger: 0.07,
        ease: 'power2.out',
        scrollTrigger: {
          trigger: container,
          start: 'top 85%',
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

  const linearBeforeBranch = FLOW_STEPS.filter((s) =>
    ['goal', 'plan', 'question', 'act'].includes(s.id)
  );
  const parallelSteps = FLOW_STEPS.filter((s) =>
    ['feedback', 'observe'].includes(s.id)
  );
  const linearAfterBranch = FLOW_STEPS.filter((s) =>
    ['improve', 'repeat'].includes(s.id)
  );

  return (
    <figure
      className={styles.figure}
      aria-label="Agent execution loop: goal, plan, question, act, then get feedback and observe in parallel, improve, and repeat"
    >
      <div ref={containerRef} className={styles.flowScene} data-agent-flow-root>
        <svg ref={svgRef} className={styles.flowSvg} aria-hidden="true" />

        <div className={styles.mainRow}>
          {linearBeforeBranch.map((step) => (
            <FlowStepCard key={step.id} step={step} innerRef={setNodeRef(step.id)} />
          ))}

          <div className={styles.parallelCol}>
            {parallelSteps.map((step) => (
              <FlowStepCard key={step.id} step={step} innerRef={setNodeRef(step.id)} />
            ))}
          </div>

          {linearAfterBranch.map((step) => (
            <FlowStepCard key={step.id} step={step} innerRef={setNodeRef(step.id)} />
          ))}
        </div>
      </div>
    </figure>
  );
}
