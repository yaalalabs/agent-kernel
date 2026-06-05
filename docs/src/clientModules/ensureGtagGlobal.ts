/**
 * @docusaurus/plugin-google-gtag calls `window.gtag` on SPA navigations without checking
 * that it exists. If the inline bootstrap in <head> is blocked (CSP, privacy extensions)
 * or has not run yet, `window.gtag` can be missing and navigation throws.
 *
 * Mirrors the official stub: queue calls on `dataLayer` until the real gtag.js is ready.
 */
function ensureGtagGlobal(): void {
  if (typeof window === 'undefined') return;

  const win = window as Window & {
    dataLayer?: IArguments[] | unknown[];
    gtag?: unknown;
  };

  if (!Array.isArray(win.dataLayer)) {
    win.dataLayer = [];
  }

  if (typeof win.gtag === 'function') {
    return;
  }

  win.gtag = function gtag() {
    (win.dataLayer as IArguments[]).push(arguments);
  };
}

ensureGtagGlobal();

export function onClientEntry(): void {
  ensureGtagGlobal();
}
