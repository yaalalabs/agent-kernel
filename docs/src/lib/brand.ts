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
