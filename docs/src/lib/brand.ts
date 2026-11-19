/**
 * Open Agent Kernel brand palette for code that cannot read CSS variables
 * (canvas, WebGL, colour strings assembled in JavaScript).
 *
 * Keep in sync with the tokens in src/css/custom.css and with branding/README.md.
 * Stylesheets use the CSS variables instead of importing this module.
 */
export const BRAND = {
  orange: '#FF5E32',
  prussian: '#02284F',
  dusk: '#3F598A',
  sky: '#ABCEE1',
  ice: '#B1CDFF',
  bg: '#011428',
} as const;

export type BrandColor = keyof typeof BRAND;

const BRAND_RGB: Record<BrandColor, readonly [number, number, number]> = {
  orange: [255, 94, 50],
  prussian: [2, 40, 79],
  dusk: [63, 89, 138],
  sky: [171, 206, 225],
  ice: [177, 205, 255],
  bg: [1, 20, 40],
};

/** `rgba(r, g, b, alpha)` string for a brand colour. */
export function brandRgba(color: BrandColor, alpha: number): string {
  const [r, g, b] = BRAND_RGB[color];
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** `0xRRGGBB` number for a brand colour, as three.js expects. */
export function brandInt(color: BrandColor): number {
  const [r, g, b] = BRAND_RGB[color];
  return (r << 16) | (g << 8) | b;
}

/** Channels scaled to 0..1, for shader attributes. */
export function brandUnit(color: BrandColor): [number, number, number] {
  const [r, g, b] = BRAND_RGB[color];
  return [r / 255, g / 255, b / 255];
}

/* ── Theme-aware colours for canvas and WebGL ──────────────────────────────
   The site has a dark and a light mode. Stylesheets get that for free from the
   CSS variables; code that paints pixels has to read them. These helpers read
   the `--ak-*-rgb` tokens from the document and cache them until the mode changes. */

export type ThemeToken = 'bg' | 'fg' | 'blue' | 'sky' | 'dusk' | 'prussian' | 'primary';

const THEME_FALLBACK: Record<ThemeToken, string> = {
  bg: '1, 20, 40',
  fg: '255, 255, 255',
  blue: '177, 205, 255',
  sky: '171, 206, 225',
  dusk: '63, 89, 138',
  prussian: '2, 40, 79',
  primary: '255, 94, 50',
};

let themeCache: Partial<Record<ThemeToken, string>> = {};
let themeObserver: MutationObserver | null = null;
const themeListeners = new Set<() => void>();

function watchTheme(): void {
  if (themeObserver || typeof document === 'undefined') return;
  themeObserver = new MutationObserver(() => {
    themeCache = {};
    themeListeners.forEach((listener) => listener());
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}

/** The `r, g, b` channels of a theme token in the current colour mode. */
export function themeChannels(token: ThemeToken): string {
  if (typeof document === 'undefined') return THEME_FALLBACK[token];
  watchTheme();
  let value = themeCache[token];
  if (!value) {
    value = getComputedStyle(document.documentElement).getPropertyValue(`--ak-${token}-rgb`).trim() || THEME_FALLBACK[token];
    themeCache[token] = value;
  }
  return value;
}

/** `rgba(r, g, b, alpha)` for a theme token in the current colour mode. */
export function themeRgba(token: ThemeToken, alpha: number): string {
  return `rgba(${themeChannels(token)}, ${alpha})`;
}

/** `0xRRGGBB` for a theme token in the current colour mode, as three.js expects. */
export function themeInt(token: ThemeToken): number {
  const [r, g, b] = themeChannels(token).split(',').map((part) => parseInt(part, 10));
  return (r << 16) | (g << 8) | b;
}

/** Run `listener` whenever the colour mode changes. Returns the unsubscribe function. */
export function onThemeChange(listener: () => void): () => void {
  watchTheme();
  themeListeners.add(listener);
  return () => {
    themeListeners.delete(listener);
  };
}
