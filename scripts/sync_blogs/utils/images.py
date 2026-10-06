"""SVG images are not allowed in blog posts.

DEV Community and Hashnode cannot display SVG images (DEV's image proxy serves SVGs labelled
image/webp, so browsers can't decode them) and neither has an upload API, so a post with an
SVG image would publish with a broken image. Posts must use PNG/JPEG/GIF/WebP instead; the
docs deploy and both sync scripts fail before anything is published if one is found.
"""

import re
import sys
import urllib.parse
from pathlib import Path

from utils.common import FRONTMATTER_RE, list_posts

# Alt text may contain one level of [brackets].
ALT = r"!\[((?:[^\[\]]|\[[^\]]*\])*)\]"
MD_IMAGE_RE = re.compile(ALT + r"\(\s*<?([^\s)>]+)")
# Reference-style `![alt][label]`, `![alt][]` and `![alt]`, resolved through `[label]: url` definitions.
MD_REF_IMAGE_RE = re.compile(ALT + r"(?!\()(?:\[([^\]]*)\])?")
MD_REF_DEF_RE = re.compile(r"^[ \t]{0,3}\[([^\]]+)\]:[ \t]*<?([^\s>]+)", re.MULTILINE)
HTML_IMG_RE = re.compile(r"<img\s(?:[^>]*?\s)?src=[\"']([^\"']+)[\"']")
FRONTMATTER_IMAGE_RE = re.compile(r"^image:[ \t]*[\"']?([^\s\"']+)", re.MULTILINE)
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
# DEV rewrites shields.io badges to raster.shields.io PNGs (see devto.py), so they are allowed.
ALLOWED_SVG_HOSTS = {"img.shields.io"}


def is_svg(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.path.lower().endswith(".svg") and parts.netloc.lower() not in ALLOWED_SVG_HOSTS


def blank_code_blocks(text: str) -> str:
    """Blank out fenced code blocks (keeping line breaks), so example Markdown in them is ignored."""
    lines, fence = text.split("\n"), None
    for i, line in enumerate(lines):
        match = FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
                lines[i] = ""
        else:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) and not line.strip().strip(fence[0]):
                fence = None
            lines[i] = ""
    return "\n".join(lines)


def find_svg_images(paths: list) -> list:
    """Return (path, line, url) for every SVG image in the given posts (body or frontmatter `image`)."""
    found = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        frontmatter = FRONTMATTER_RE.match(text)
        body_start = frontmatter.start(2) if frontmatter else 0
        body = text[:body_start] + blank_code_blocks(text[body_start:])
        images = [(m.start(), m.group(2)) for m in MD_IMAGE_RE.finditer(body)]
        images += [(m.start(), m.group(1)) for m in HTML_IMG_RE.finditer(body)]
        definitions = {label.strip().lower(): url for label, url in MD_REF_DEF_RE.findall(body)}
        for m in MD_REF_IMAGE_RE.finditer(body):
            url = definitions.get((m.group(2) or m.group(1)).strip().lower())
            if url:
                images.append((m.start(), url))
        if frontmatter:
            images += [(m.start(), m.group(1)) for m in FRONTMATTER_IMAGE_RE.finditer(text, frontmatter.start(1), frontmatter.end(1))]
        for start, url in sorted(images):
            if is_svg(url):
                found.append((path, text.count("\n", 0, start) + 1, url))
    return found


def fail_on_svg_images(paths: list) -> None:
    """Exit with an error listing every SVG image, so nothing is published with a broken image."""
    found = find_svg_images(paths)
    if not found:
        return
    print("Error: SVG images are not allowed in blog posts (DEV Community and Hashnode can't display them).", file=sys.stderr)
    for path, line, url in found:
        print(f"  {path}:{line}: {url}", file=sys.stderr)
    print("Convert them to PNG and reference the .png instead.", file=sys.stderr)
    sys.exit(1)


def check_blog_dir(blog_dir: Path) -> None:
    fail_on_svg_images(list_posts(blog_dir))
