import React, {
  type ReactElement,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import ExecutionEnvironment from '@docusaurus/ExecutionEnvironment';
import { useColorMode } from '@docusaurus/theme-common';
import mermaid from 'mermaid';
import elkLayouts from '@mermaid-js/layout-elk';
import MermaidOriginal from '@theme-original/Mermaid';
import type MermaidType from '@theme/Mermaid';
import type { WrapperProps } from '@docusaurus/types';
import styles from './styles.module.css';

/**
 * @docusaurus/theme-mermaid initializes mermaid but never registers extra
 * layout engines, so the `layout: 'elk'` option in docusaurus.config.js would
 * silently fall back to dagre without this. Module evaluation runs before any
 * render of this chunk (the same mermaid singleton), which keeps elkjs inside
 * the code-split mermaid chunk instead of the main bundle.
 */
if (ExecutionEnvironment.canUseDOM) {
  mermaid.registerLayoutLoaders(elkLayouts);

  // layout-elk deep-clones subgraph nodes with JSON.parse(JSON.stringify(node))
  // (render chunk, drawNodes; still present in 0.2.2), and those nodes carry DOM
  // references (labelData.labelNode, the domId d3 selection whose _parents
  // includes <html>). A bare DOM element stringifies as "{}", but once GSAP has
  // animated an element it attaches an enumerable `_gsap` cache whose `target`
  // points back at the element, so the clone throws "Converting circular
  // structure to JSON" on every subgraph diagram reached by client-side
  // navigation. Serializing a DOM element is never meaningful; make it inert.
  if (!Object.getOwnPropertyDescriptor(Element.prototype, 'toJSON')) {
    Object.defineProperty(Element.prototype, 'toJSON', {
      value: () => undefined,
      writable: true,
      configurable: true,
    });
  }
}

type Props = WrapperProps<typeof MermaidType>;

/**
 * The palette for diagrams on the light page. docusaurus.config.js holds the dark one, and the
 * theme can pass only one set of variables to mermaid, so the light set travels with each
 * diagram as an init directive (see `forColorMode`).
 *
 * Nodes that a diagram colours itself (`style X fill:..., color:...`) always set both the fill
 * and the text colour, so they read on either background. These variables cover everything
 * else: plain nodes, edges and their labels, groups, and the parts of sequence diagrams.
 */
const LIGHT_VARIABLES = {
  darkMode: false,
  background: '#FFFFFF',
  textColor: '#02284F',
  // nodes
  primaryColor: '#EEF3FB',
  primaryTextColor: '#02284F',
  primaryBorderColor: '#3F598A',
  mainBkg: '#EEF3FB',
  nodeBorder: '#3F598A',
  // edges + labels
  lineColor: '#3F598A',
  edgeLabelBackground: '#FFFFFF',
  // subgraphs / clusters
  clusterBkg: '#F6F8FC',
  clusterBorder: '#B9C8E0',
  titleColor: '#02284F',
  // secondary/tertiary (misc fills)
  secondaryColor: '#E1EAF7',
  secondaryTextColor: '#02284F',
  secondaryBorderColor: '#3F598A',
  tertiaryColor: '#F6F8FC',
  tertiaryTextColor: '#02284F',
  tertiaryBorderColor: '#B9C8E0',
  // sequence diagrams
  actorBkg: '#EEF3FB',
  actorBorder: '#3F598A',
  actorTextColor: '#02284F',
  actorLineColor: '#8FA1C2',
  signalColor: '#3F598A',
  signalTextColor: '#02284F',
  labelBoxBkgColor: '#E1EAF7',
  labelBoxBorderColor: '#3F598A',
  labelTextColor: '#02284F',
  loopTextColor: '#3F598A',
  noteBkgColor: '#FFF0EA',
  noteBorderColor: '#F2A98F',
  noteTextColor: '#02284F',
  activationBkgColor: '#E1EAF7',
  activationBorderColor: '#3F598A',
  sequenceNumberColor: '#FFFFFF',
};

const LIGHT_DIRECTIVE = `%%{init: ${JSON.stringify({ theme: 'base', themeVariables: LIGHT_VARIABLES })}}%%`;

/**
 * The diagram source for a colour mode. On the dark page it is unchanged. On the light page it
 * gains the light palette as an init directive, placed after any front matter, which has to
 * stay first.
 */
function forColorMode(source: string, colorMode: string): string {
  if (colorMode !== 'light') return source;
  const frontMatter = /^\s*---\r?\n[\s\S]*?\r?\n---[ \t]*\r?\n/.exec(source);
  if (!frontMatter) return `${LIGHT_DIRECTIVE}\n${source}`;
  return `${frontMatter[0]}${LIGHT_DIRECTIVE}\n${source.slice(frontMatter[0].length)}`;
}

const MIN_SCALE = 0.25;
const MAX_SCALE = 8;
const ZOOM_STEP = 1.2;
const STAGE_PADDING = 48;
// Below this stage width a diagram fitted to the screen is too small to read.
const NARROW_STAGE = 600;
// Room for the toolbar above a diagram that opens from its top edge.
const TOOLBAR_CLEARANCE = 72;

function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

function ExpandIcon(): ReactElement {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M15 3h6v6" />
      <path d="M9 21H3v-6" />
      <path d="M21 3l-7 7" />
      <path d="M3 21l7-7" />
    </svg>
  );
}

function CloseIcon(): ReactElement {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M18 6L6 18" />
      <path d="M6 6l12 12" />
    </svg>
  );
}

function MermaidLightbox({
  onClose,
  ...props
}: Props & { onClose: () => void }): ReactElement {
  const { colorMode } = useColorMode();
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [fitScale, setFitScale] = useState(1);
  const [fitOffset, setFitOffset] = useState({ x: 0, y: 0 });
  const fittedRef = useRef(false);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    baseX: number;
    baseY: number;
    moved: boolean;
  } | null>(null);

  // aria-modal promises modal semantics: move focus into the dialog on open
  // and hand it back to the opener (the Expand button) on close.
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();
    return () => previouslyFocused?.focus();
  }, []);

  // Close on Escape and lock body scroll while open.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  // Once the diagram has rendered, scale it to fit the stage.
  useEffect(() => {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    if (!stage || !canvas) {
      return undefined;
    }
    const observer = new ResizeObserver(() => {
      if (fittedRef.current) {
        return;
      }
      const width = canvas.offsetWidth;
      const height = canvas.offsetHeight;
      if (!width || !height) {
        return;
      }
      const fit = Math.min(
        (stage.clientWidth - STAGE_PADDING) / width,
        (stage.clientHeight - STAGE_PADDING) / height,
      );
      // On a phone the fitted diagram is still too small to read. It opens at twice that size,
      // from its top left corner, and the reader drags it: the labels are legible at once.
      const narrow = stage.clientWidth < NARROW_STAGE;
      const initial = clampScale(narrow ? fit * 2 : Math.min(fit, 2));
      const overX = (width * initial - stage.clientWidth) / 2;
      const overY = (height * initial - stage.clientHeight) / 2;
      const start = narrow
        ? {
            x: overX > 0 ? overX + STAGE_PADDING / 2 : 0,
            y: overY > 0 ? overY + TOOLBAR_CLEARANCE : 0,
          }
        : { x: 0, y: 0 };
      fittedRef.current = true;
      setFitScale(initial);
      setFitOffset(start);
      setScale(initial);
      setOffset(start);
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  // Wheel zoom needs a non-passive listener so we can prevent page scroll.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) {
      return undefined;
    }
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const factor = event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
      setScale((current) => clampScale(current * factor));
    };
    stage.addEventListener('wheel', onWheel, { passive: false });
    return () => stage.removeEventListener('wheel', onWheel);
  }, []);

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) {
        return;
      }
      stageRef.current?.setPointerCapture(event.pointerId);
      dragRef.current = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        baseX: offset.x,
        baseY: offset.y,
        moved: false,
      };
    },
    [offset],
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag || drag.pointerId !== event.pointerId) {
        return;
      }
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        drag.moved = true;
      }
      setOffset({ x: drag.baseX + dx, y: drag.baseY + dy });
    },
    [],
  );

  const onPointerUp = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      dragRef.current = null;
      // A plain click on the dark backdrop (not a drag, not on the diagram)
      // closes the viewer.
      if (drag && !drag.moved && event.target === stageRef.current) {
        onClose();
      }
    },
    [onClose],
  );

  const zoomIn = useCallback(
    () => setScale((current) => clampScale(current * ZOOM_STEP)),
    [],
  );
  const zoomOut = useCallback(
    () => setScale((current) => clampScale(current / ZOOM_STEP)),
    [],
  );
  const reset = useCallback(() => {
    setScale(fitScale);
    setOffset(fitOffset);
  }, [fitScale, fitOffset]);

  return createPortal(
    <div
      className={styles.overlay}
      role="dialog"
      aria-modal="true"
      aria-label="Diagram viewer"
    >
      <div className={styles.toolbar}>
        <button
          type="button"
          className={styles.toolbarButton}
          onClick={zoomOut}
          aria-label="Zoom out"
          title="Zoom out"
        >
          &minus;
        </button>
        <span className={styles.zoomLevel}>{Math.round(scale * 100)}%</span>
        <button
          type="button"
          className={styles.toolbarButton}
          onClick={zoomIn}
          aria-label="Zoom in"
          title="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          className={`${styles.toolbarButton} ${styles.resetButton}`}
          onClick={reset}
          title="Reset view"
        >
          Reset
        </button>
        <button
          ref={closeButtonRef}
          type="button"
          className={styles.toolbarButton}
          onClick={onClose}
          aria-label="Close diagram viewer"
          title="Close (Esc)"
        >
          <CloseIcon />
        </button>
      </div>
      <div
        ref={stageRef}
        className={styles.stage}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div
          ref={canvasRef}
          className={styles.canvas}
          style={{
            transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
          }}
        >
          <MermaidOriginal {...props} value={forColorMode(props.value, colorMode)} />
        </div>
      </div>
      <div className={styles.hint}>Scroll to zoom, drag to pan</div>
    </div>,
    document.body,
  );
}

export default function MermaidWrapper(props: Props): ReactElement {
  const { colorMode } = useColorMode();
  const [isOpen, setIsOpen] = useState(false);
  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);

  return (
    <>
      <div className={styles.wrapper}>
        <MermaidOriginal {...props} value={forColorMode(props.value, colorMode)} />
        <button
          type="button"
          className={styles.expandButton}
          onClick={open}
          aria-label="Expand diagram"
          title="Expand diagram"
        >
          <ExpandIcon />
          <span className={styles.expandLabel}>Expand</span>
        </button>
      </div>
      {isOpen && <MermaidLightbox {...props} onClose={close} />}
    </>
  );
}
