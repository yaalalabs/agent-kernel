/**
 * @docusaurus/plugin-google-gtag calls `window.gtag` on SPA navigations without checking
 * that it exists. If the inline bootstrap in <head> is blocked (CSP, privacy extensions)
 * or has not run yet, `window.gtag` can be missing and navigation throws.
 *
 * Mirrors the official stub: queue calls on `dataLayer` until the real gtag.js is ready.
 * Also implements Consent Mode v2: analytics_storage is denied by default until the user
 * accepts via the cookie consent banner.
 */

const CONSENT_KEY = 'ak_cookie_consent';

function ensureGtagGlobal(): void {
  if (typeof window === 'undefined') return;

  const win = window as Window & {
    dataLayer?: IArguments[] | unknown[];
    gtag?: Function;
  };

  if (!Array.isArray(win.dataLayer)) {
    win.dataLayer = [];
  }

  if (typeof win.gtag !== 'function') {
    win.gtag = function gtag() {
      (win.dataLayer as IArguments[]).push(arguments);
    };
  }

  // Consent Mode v2: deny by default before any GA4 event fires
  win.gtag('consent', 'default', {
    analytics_storage: 'denied',
    ad_storage: 'denied',
  });

  // Restore previously granted consent so returning visitors aren't re-prompted
  if (localStorage.getItem(CONSENT_KEY) === 'granted') {
    win.gtag('consent', 'update', { analytics_storage: 'granted' });
  }
}

ensureGtagGlobal();

export function onClientEntry(): void {
  ensureGtagGlobal();
}
