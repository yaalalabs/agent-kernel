import React, { useEffect, useRef, useState } from 'react';
import { gsap } from 'gsap';
import styles from './styles.module.css';

const ScrollToTopButton: React.FC = () => {
  const [scrolled, setScrolled] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const rippleRef = useRef<HTMLSpanElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const visible = scrolled && !chatOpen;

  /* ── Scroll visibility ── */
  useEffect(() => {
    const onScroll = () => {
      if (typeof window === 'undefined') return;
      setScrolled(window.scrollY > 240);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  /* ── Listen for chatbot open/close events ── */
  useEffect(() => {
    const onOpen  = () => setChatOpen(true);
    const onClose = () => setChatOpen(false);
    window.addEventListener('chatbot:open',  onOpen);
    window.addEventListener('chatbot:close', onClose);
    return () => {
      window.removeEventListener('chatbot:open',  onOpen);
      window.removeEventListener('chatbot:close', onClose);
    };
  }, []);

  /* ── Enter / Exit animation ── */
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    if (visible) {
      gsap.killTweensOf(el);
      gsap.fromTo(
        el,
        { scale: 0.4, opacity: 0, y: 20 },
        { scale: 1, opacity: 1, y: 0, duration: 0.55, ease: 'back.out(2.2)' }
      );
    } else {
      gsap.killTweensOf(el);
      gsap.to(el, { scale: 0.4, opacity: 0, y: 20, duration: 0.3, ease: 'power2.in' });
    }
  }, [visible]);

  /* ── Hover ── */
  const handleMouseEnter = () => {
    if (!buttonRef.current || !svgRef.current) return;
    gsap.to(buttonRef.current, { y: -5, scale: 1.08, duration: 0.28, ease: 'power2.out' });
    gsap.fromTo(svgRef.current, { y: 3 }, { y: -2, duration: 0.28, ease: 'power2.out' });
  };

  const handleMouseLeave = () => {
    if (!buttonRef.current || !svgRef.current) return;
    gsap.to(buttonRef.current, { y: 0, scale: 1, duration: 0.35, ease: 'elastic.out(1, 0.5)' });
    gsap.to(svgRef.current,   { y: 0,            duration: 0.35, ease: 'elastic.out(1, 0.5)' });
  };

  /* ── Click ── */
  const handleClick = () => {
    if (typeof window === 'undefined') return;

    if (rippleRef.current) {
      gsap.fromTo(
        rippleRef.current,
        { scale: 0, opacity: 0.7 },
        { scale: 2.8, opacity: 0, duration: 0.55, ease: 'power2.out' }
      );
    }

    if (buttonRef.current) {
      gsap.timeline()
        .to(buttonRef.current, { scale: 0.88, duration: 0.1, ease: 'power2.in' })
        .to(buttonRef.current, { scale: 1.05, duration: 0.2, ease: 'power2.out' })
        .to(buttonRef.current, { scale: 1,    duration: 0.35, ease: 'elastic.out(1.2, 0.5)' });
    }

    if (svgRef.current) {
      gsap.timeline()
        .to(svgRef.current, { y: -8, opacity: 0, duration: 0.2, ease: 'power2.in' })
        .set(svgRef.current, { y: 8 })
        .to(svgRef.current,  { y: 0, opacity: 1, duration: 0.3, ease: 'power2.out' });
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  if (!visible && containerRef.current === null) return null;

  return (
    <div ref={containerRef} className={styles.container} style={{ opacity: 0 }}>
      <button
        ref={buttonRef}
        className={styles.button}
        onClick={handleClick}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        aria-label="Scroll to top"
        title="Scroll to top"
      >
        <span ref={rippleRef} className={styles.ripple} aria-hidden="true" />

        <svg
          ref={svgRef}
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={styles.icon}
        >
          <polyline points="18 15 12 9 6 15" />
        </svg>
      </button>
    </div>
  );
};

export default ScrollToTopButton;