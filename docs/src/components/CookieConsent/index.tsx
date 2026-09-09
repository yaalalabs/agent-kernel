import React, { useEffect, useState } from 'react';
import Link from '@docusaurus/Link';
import styles from './styles.module.css';

const CONSENT_KEY = 'ak_cookie_consent';

type ConsentState = 'granted' | 'denied' | null;

function updateGtagConsent(value: 'granted' | 'denied') {
  if (typeof window !== 'undefined' && typeof (window as any).gtag === 'function') {
    (window as any).gtag('consent', 'update', { analytics_storage: value });
  }
}

export default function CookieConsent(): JSX.Element | null {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(CONSENT_KEY) as ConsentState;
    if (!stored) {
      setVisible(true);
    }
  }, []);

  function accept() {
    localStorage.setItem(CONSENT_KEY, 'granted');
    updateGtagConsent('granted');
    setVisible(false);
  }

  function decline() {
    localStorage.setItem(CONSENT_KEY, 'denied');
    updateGtagConsent('denied');
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div className={styles.banner} role="dialog" aria-modal="true" aria-label="Cookie consent">
      <div className={styles.text}>
        <span>
          We use analytics cookies to understand how visitors use our documentation and improve it.
          Your IP address is anonymized and no personal data is sold or shared.
          You can browse the site without accepting; declining has no effect on access to content.{' '}
          <Link to="/cookie-policy">Cookie Policy</Link> ·{' '}
          <Link to="/privacy-policy">Privacy Policy</Link>
        </span>
      </div>
      <div className={styles.actions}>
        <button className={styles.decline} onClick={decline}>
          Decline
        </button>
        <button className={styles.accept} onClick={accept}>
          Accept
        </button>
      </div>
    </div>
  );
}
