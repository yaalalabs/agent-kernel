"""Helpers shared by the blog sync scripts (devto.py, hashnode.py)."""

import datetime
import hashlib
import json
import re
from pathlib import Path

import yaml

DEFAULT_BLOG_DIR = Path("docs/blog")
DEFAULT_SITE_URL = "https://kernel.yaala.ai"
AUTHORS_FILENAME = "authors.json"
FILENAME_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
IMPORT_RE = re.compile(r"^import .+ from ['\"]@theme/\w+['\"];?\s*$\n?", re.MULTILINE)
TABS_RE = re.compile(r"<Tabs>(.*?)</Tabs>", re.DOTALL)
TAB_ITEM_RE = re.compile(r'<TabItem\s+value="[^"]*"\s+label="([^"]*)"[^>]*>(.*?)</TabItem>', re.DOTALL)
ADMONITION_RE = re.compile(r"^:::(\w+)(?:[ \t]+([^\n]*))?\n(.*?)\n:::[ \t]*$", re.MULTILINE | re.DOTALL)
HTML_BLOCK_RE = re.compile(r"^<div[^>]*>\n(.*?)\n</div>[ \t]*$", re.MULTILINE | re.DOTALL)
LINKED_IMG_RE = re.compile(r"<a\s[^>]*?href=\"([^\"]+)\"[^>]*>\s*(<img\s[^>]*?/?>)\s*</a>", re.DOTALL)
IMG_RE = re.compile(r"<img\s[^>]*?/?>")
CAPTION_RE = re.compile(r"<p(?:\s[^>]*)?>(.*?)</p>", re.DOTALL)
LEADING_H1_RE = re.compile(r"^\s*# [^\n]*\n")
# Both syncs write <post>.<platform>-preview.md next to the posts (--preview); never sync those.
PREVIEW_FILE_SUFFIX = "-preview.md"
CODE_FENCE_META_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})([\w+-]+)[ \t]+([^\n]*?)[ \t]*$", re.MULTILINE)
# shields.io badges are SVGs, which DEV can't display (its image proxy labels them image/webp)
# and posts may not use (see utils/images.py); shields' raster endpoint serves the same badge as PNG.
SHIELDS_SVG_URL = "https://img.shields.io/"
SHIELDS_PNG_URL = "https://raster.shields.io/"
# On a rate-limit response, wait (Retry-After, else this many seconds) and retry, this many times.
RATE_LIMIT_RETRIES = 5
RATE_LIMIT_DEFAULT_WAIT = 30


def load_state(state_file: Path) -> dict:
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {}


def save_state(state_file: Path, state: dict) -> None:
    state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def list_posts(blog_dir: Path) -> list:
    return sorted(path for path in blog_dir.glob("*.md") if not path.name.endswith(PREVIEW_FILE_SUFFIX))


def is_hidden_on_site(frontmatter: dict) -> bool:
    """True for a Docusaurus `draft` (left out of the production build) or `unlisted` post.

    Neither is meant to be public on the website, so neither may be published elsewhere.
    """
    return frontmatter.get("draft") is True or frontmatter.get("unlisted") is True


def parse_post(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    if not match:
        raise ValueError(f"{path}: missing YAML frontmatter")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    return {"frontmatter": frontmatter, "body": match.group(2), "raw": raw}


def load_authors(blog_dir: Path) -> dict:
    authors_path = blog_dir / AUTHORS_FILENAME
    if not authors_path.exists():
        return {}
    return json.loads(authors_path.read_text(encoding="utf-8"))


def resolve_authors(frontmatter: dict, authors_map: dict) -> list:
    keys = frontmatter.get("authors") or []
    if isinstance(keys, str):
        keys = [keys]
    resolved = []
    for key in keys:
        info = authors_map.get(key, {})
        resolved.append({"name": info.get("name", key), "url": info.get("url")})
    return resolved


def join_names(names: list) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} & {names[-1]}"


def convert_admonitions(body: str) -> str:
    """Turn Docusaurus `:::type Title ... :::` admonitions into a plain blockquote."""

    def replace_admonition(match: re.Match) -> str:
        title = (match.group(2) or match.group(1)).strip().capitalize()
        quoted = "\n".join(f"> {line}".rstrip() for line in match.group(3).strip().split("\n"))
        return f"> **{title}**\n>\n{quoted}"

    return ADMONITION_RE.sub(replace_admonition, body)


def convert_code_fences(body: str) -> str:
    """Strip Docusaurus fence metadata (```yaml title="config.yaml") down to the bare language.

    DEV only recognizes a single language word after the opening fence; anything more and the
    fence is not opened, so the block renders as plain text and the next fence swallows the
    prose after it. CommonMark renderers ignore everything after the language, dropping the
    title. So the title is kept as a bold label above the block.
    """

    def replace_fence(match: re.Match) -> str:
        indent, fence, language, meta = match.groups()
        title = re.search(r'title="([^"]*)"', meta)
        label = f"{indent}**{title.group(1)}**\n\n" if title else ""
        return f"{label}{indent}{fence}{language}"

    return CODE_FENCE_META_RE.sub(replace_fence, body)


def raster_shields_badges(body: str) -> str:
    return body.replace(SHIELDS_SVG_URL, SHIELDS_PNG_URL)


def rate_limit_wait(retry_after: str | None) -> int:
    """Seconds to wait before retrying a rate-limited request: the server's Retry-After, else a default."""
    return int(retry_after) if retry_after and retry_after.isdigit() else RATE_LIMIT_DEFAULT_WAIT


def absolutize_url(url: str | None, site_url: str) -> str | None:
    if url and url.startswith("/"):
        return f"{site_url}{url}"
    return url


def resolve_post_date(path: Path, frontmatter: dict) -> datetime.date | None:
    """Return the date the post went live on the website, the same way Docusaurus picks it.

    A frontmatter `date` wins; otherwise the `YYYY-MM-DD-` filename prefix is used.
    """
    value = frontmatter.get("date")
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value.strip()[:10])
        except ValueError:
            pass
    match = FILENAME_DATE_RE.match(path.name)
    if match:
        return datetime.date(*(int(part) for part in match.groups()))
    return None


def build_canonical_url(site_url: str, slug: str) -> str:
    slug = slug if slug.startswith("/") else f"/{slug}"
    return f"{site_url}/blog{slug}"


def content_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
