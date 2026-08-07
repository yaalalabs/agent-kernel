import React, {
  type ReactElement,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import ExecutionEnvironment from '@docusaurus/ExecutionEnvironment';
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
}

type Props = WrapperProps<typeof MermaidType>;

const MIN_SCALE = 0.25;
const MAX_SCALE = 8;
const ZOOM_STEP = 1.2;
const STAGE_PADDING = 48;

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
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [fitScale, setFitScale] = useState(1);
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
      const initial = clampScale(Math.min(fit, 2));
      fittedRef.current = true;
      setFitScale(initial);
      setScale(initial);
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
    setOffset({ x: 0, y: 0 });
  }, [fitScale]);

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
          <MermaidOriginal {...props} />
        </div>
      </div>
      <div className={styles.hint}>Scroll to zoom, drag to pan</div>
    </div>,
    document.body,
  );
}

export default function MermaidWrapper(props: Props): ReactElement {
  const [isOpen, setIsOpen] = useState(false);
  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);

  return (
    <>
      <div className={styles.wrapper}>
        <MermaidOriginal {...props} />
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
