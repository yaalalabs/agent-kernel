import React, { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import clsx from 'clsx';

type RevealProps = {
  children: ReactNode;
  /** The element to render. */
  as?: 'div' | 'section' | 'li' | 'article';
  /** Milliseconds to wait before the fade, to stagger a few siblings. Keep it under 300. */
  delay?: number;
  className?: string;
  id?: string;
};

/**
 * The one entrance effect on the site: content below the fold fades up once as it enters the view.
 * It never hides content from a visitor who cannot see the effect: without script, with reduced
 * motion, and for anything already on screen when the page loads, the content is simply there.
 * Styles live in custom.css with the rest of the design system.
 */
export default function Reveal({ children, as: Tag = 'div', delay = 0, className, id }: RevealProps): JSX.Element {
  const element = useRef<HTMLElement>(null);
  const [state, setState] = useState<'still' | 'waiting' | 'shown'>('still');

  useEffect(() => {
    const node = element.current;
    if (!node || !('IntersectionObserver' in window)) return undefined;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined;
    // On screen already: leave it alone, so nothing flashes after the page has painted.
    if (node.getBoundingClientRect().top < window.innerHeight) return undefined;
    setState('waiting');
    const seen = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        setState('shown');
        seen.disconnect();
      },
      { rootMargin: '0px 0px -8% 0px' },
    );
    seen.observe(node);
    return () => seen.disconnect();
  }, []);

  const style = delay ? ({ '--ak-reveal-delay': `${delay}ms` } as CSSProperties) : undefined;
  return React.createElement(
    Tag,
    {
      ref: element,
      id,
      style,
      className: clsx(state === 'waiting' && 'ak-reveal--waiting', state === 'shown' && 'ak-reveal--shown', className),
    },
    children,
  );
}
