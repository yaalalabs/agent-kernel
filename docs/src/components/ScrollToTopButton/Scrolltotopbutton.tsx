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

  return (
    <button
      type="button"
      className={clsx(styles.button, visible && styles.visible)}
      onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
      tabIndex={visible ? 0 : -1}
      aria-hidden={!visible}
      aria-label="Scroll to top"
      title="Scroll to top"
    >
      <TbChevronUp aria-hidden="true" />
    </button>
  );
}
