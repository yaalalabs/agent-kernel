import React, { useEffect, useState } from 'react';
import clsx from 'clsx';
import { TbChevronUp } from 'react-icons/tb';
import styles from './styles.module.css';

/**
 * Returns to the top of the page. It appears after some scrolling, and steps aside while the
 * chat panel is open.
 */
export default function ScrollToTopButton(): JSX.Element {
  const [scrolled, setScrolled] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const visible = scrolled && !chatOpen;

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 240);
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const onOpen = () => setChatOpen(true);
    const onClose = () => setChatOpen(false);
    window.addEventListener('chatbot:open', onOpen);
    window.addEventListener('chatbot:close', onClose);
    return () => {
      window.removeEventListener('chatbot:open', onOpen);
      window.removeEventListener('chatbot:close', onClose);
    };
  }, []);

  // After the scroll this button hides, so focus must not stay on it: it goes to the main
  // content, which is where a keyboard user would start reading from the top.
  const toTop = () => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' });
    const main = document.querySelector<HTMLElement>('main') ?? document.body;
    if (!main.hasAttribute('tabindex')) main.setAttribute('tabindex', '-1');
    main.focus({ preventScroll: true });
  };

  return (
    <button
      type="button"
      className={clsx(styles.button, visible && styles.visible)}
      onClick={toTop}
      tabIndex={visible ? 0 : -1}
      aria-hidden={!visible}
      aria-label="Scroll to top"
      title="Scroll to top"
    >
      <TbChevronUp aria-hidden="true" />
    </button>
  );
}
