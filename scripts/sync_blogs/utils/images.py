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

MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^\s)>]+)")
HTML_IMG_RE = re.compile(r"<img\s[^>]*?src=[\"']([^\"']+)[\"']")
FRONTMATTER_IMAGE_RE = re.compile(r"^image:[ \t]*[\"']?([^\s\"']+)", re.MULTILINE)


def is_svg(url: str) -> bool:
    return urllib.parse.urlsplit(url).path.lower().endswith(".svg")


def find_svg_images(paths: list) -> list:
    """Return (path, line, url) for every SVG image in the given posts (body or frontmatter `image`)."""
    found = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        frontmatter = FRONTMATTER_RE.match(text)
        matches = [m for regex in (MD_IMAGE_RE, HTML_IMG_RE) for m in regex.finditer(text)]
        if frontmatter:
            matches += FRONTMATTER_IMAGE_RE.finditer(text, frontmatter.start(1), frontmatter.end(1))
        for match in sorted(matches, key=lambda m: m.start()):
            if is_svg(match.group(1)):
                found.append((path, text.count("\n", 0, match.start()) + 1, match.group(1)))
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
