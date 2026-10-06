"""Serve the site SVGs that blog posts use as PNGs, for DEV Community and Hashnode.

Neither platform can show an SVG body or cover image (DEV's image proxy serves SVGs
labelled image/webp, so browsers can't decode them), and neither has a public upload API.
So every root-relative `.svg` image is pointed at wsrv.nl, an open-source image proxy that
fetches the SVG from the website and returns it as a PNG; both platforms mirror the image
when the post is published or updated.
"""

import re
import urllib.parse
from pathlib import Path

RASTER_PROXY_URL = "https://wsrv.nl/?url={url}&output=png{size}"
# Rendered at 2x the SVG's own width so the PNG stays sharp on high-DPI screens.
RASTER_SCALE = 2
# A root-relative .svg in a Markdown image/link or an src/href attribute.
SITE_SVG_RE = re.compile(r"(\]\(|(?:src|href)=[\"'])(/[^)\s\"']+\.svg)(?=[)\"'])")
SVG_WIDTH_RE = re.compile(r"<svg\b[^>]*?\swidth=[\"'](\d+(?:\.\d+)?)(?:px)?[\"']")


def svg_width(svg_path: Path) -> float | None:
    try:
        match = SVG_WIDTH_RE.search(svg_path.read_text(encoding="utf-8"))
    except OSError:
        return None
    return float(match.group(1)) if match else None


def raster_url(url: str | None, site_url: str, static_dir: Path) -> str | None:
    """Return a PNG URL for a root-relative .svg URL; any other URL is returned unchanged."""
    if not (url and url.startswith("/") and url.endswith(".svg")):
        return url
    # wsrv.nl keeps an SVG at its intrinsic size unless asked for an explicit width.
    width = svg_width(static_dir / url.lstrip("/"))
    size = f"&w={round(width * RASTER_SCALE)}" if width else ""
    return RASTER_PROXY_URL.format(url=urllib.parse.quote(f"{site_url}{url}", safe=""), size=size)


def raster_site_svgs(body: str, site_url: str, static_dir: Path) -> str:
    """Point every root-relative .svg image in a post body at its PNG rendering."""
    return SITE_SVG_RE.sub(lambda m: f"{m.group(1)}{raster_url(m.group(2), site_url, static_dir)}", body)
