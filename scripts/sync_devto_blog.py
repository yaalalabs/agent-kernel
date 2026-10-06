#!/usr/bin/env python3
"""
Sync docs/blog/*.md posts to DEV Community (dev.to).

Every post is published by the single account that owns the API key (optionally under
a DEV organization); the real authors from `authors.json` are credited in a byline at
the top of the body. The Docusaurus site stays the source of truth:

  - A blog file that has never been synced gets a new DEV article, published
    immediately, pointing its canonical URL back at kernel.yaala.ai.
  - A blog file that was already synced and then edited gets its DEV article
    updated in place.
  - What has already been synced is tracked in a small JSON state file next to
    the posts, so re-runs are idempotent.

DEV's API cannot backdate an article, so the date the post went live on the website is
stated in the "Originally published" footer instead.

Usage:
    # Write the Markdown that would be sent to DEV next to each post (no API key needed)
    python scripts/sync_devto_blog.py --preview

    # See what would be created/updated, without calling the DEV API
    python scripts/sync_devto_blog.py --dry-run

    # Find the organization id for DEVTO_ORGANIZATION_ID
    python scripts/sync_devto_blog.py --find-organization agentkernel

    # Publish new posts and update changed ones
    python scripts/sync_devto_blog.py

    # Sync just one post
    python scripts/sync_devto_blog.py --post 2026-09-14-scheduled-tasks.md

Environment:
    DEVTO_API_KEY             Required (except for --preview/--dry-run/--find-organization).
                              A DEV API key (Settings -> Extensions -> DEV Community API Keys).
    DEVTO_ORGANIZATION_ID     Optional. Publish new articles under this DEV organization
                              (the key's owner must be a member of it).

A post is skipped entirely if its frontmatter sets `devto: false`.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

DEVTO_API_URL = "https://dev.to/api"
# DEV ignores width/height on body images (it re-measures the source), so fixed-size images
# are served through DEV's own resizer at the size we want, scaled down a little since DEV's
# body column renders them larger than the website does.
DEVTO_FIXED_IMAGE_SCALE = 0.7
# Minimum non-breaking spaces padding each cell of a logo-row table (see image_row_table).
IMAGE_ROW_MIN_SPACER = 20
DEVTO_IMAGE_RESIZER = "https://media2.dev.to/dynamic/image/width={width},height={height},fit=scale-down,gravity=auto,format=auto/{url}"
# DEV's image proxy passes SVGs through labelled image/webp, so browsers can't decode them and
# shields.io badges show as broken images; shields' raster endpoint serves the same badge as PNG.
SHIELDS_SVG_URL = "https://img.shields.io/"
SHIELDS_PNG_URL = "https://raster.shields.io/"
DEFAULT_BLOG_DIR = Path("docs/blog")
DEFAULT_SITE_URL = "https://kernel.yaala.ai"
AUTHORS_FILENAME = "authors.json"
STATE_FILENAME = ".devto-sync-state.json"
PREVIEW_SUFFIX = ".devto-preview.md"
# DEV allows at most 4 tags per article, each lowercase alphanumeric only.
MAX_TAGS = 4
MAX_TAG_LENGTH = 30
# DEV rate-limits article writes; on a 429 wait (Retry-After, else this many seconds) and retry.
RATE_LIMIT_RETRIES = 5
RATE_LIMIT_DEFAULT_WAIT = 30

FILENAME_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
IMPORT_RE = re.compile(r"^import .+ from ['\"]@theme/\w+['\"];?\s*$\n?", re.MULTILINE)
TABS_RE = re.compile(r"<Tabs>(.*?)</Tabs>", re.DOTALL)
TAB_ITEM_RE = re.compile(r'<TabItem\s+value="[^"]*"\s+label="([^"]*)"[^>]*>(.*?)</TabItem>', re.DOTALL)
ADMONITION_RE = re.compile(r"^:::(\w+)(?:[ \t]+([^\n]*))?\n(.*?)\n:::[ \t]*$", re.MULTILINE | re.DOTALL)
HTML_BLOCK_RE = re.compile(r"^<div[^>]*>\n(.*?)\n</div>[ \t]*$", re.MULTILINE | re.DOTALL)
LINKED_IMG_RE = re.compile(r"<a\s[^>]*?href=\"([^\"]+)\"[^>]*>\s*(<img\s[^>]*?/?>)\s*</a>", re.DOTALL)
IMG_RE = re.compile(r"<img\s[^>]*?/?>")
STYLE_PX_RE = r"\b{}:\s*'(\d+)px'"
SIZED_IMG_RE = re.compile(r'<img src="(https?://[^"]+)" alt="([^"]*)"(?: width="(\d+)")?(?: height="(\d+)")? />')
CAPTION_RE = re.compile(r"<p(?:\s[^>]*)?>(.*?)</p>", re.DOTALL)
LEADING_H1_RE = re.compile(r"^\s*# [^\n]*\n")
CODE_FENCE_META_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})([\w+-]+)[ \t]+([^\n]*?)[ \t]*$", re.MULTILINE)


class DevtoAPIError(RuntimeError):
    pass


def devto_request(api_key: str | None, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        request = urllib.request.Request(f"{DEVTO_API_URL}{path}", data=data, method=method)
        if api_key:
            request.add_header("api-key", api_key)
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/vnd.forem.api-v1+json")
        # DEV's CDN rejects requests without a User-Agent.
        request.add_header("User-Agent", "agent-kernel-blog-sync")
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < RATE_LIMIT_RETRIES:
                retry_after = exc.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after.isdigit() else RATE_LIMIT_DEFAULT_WAIT
                print(f"  rate-limited by DEV, retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise DevtoAPIError(f"DEV API request failed ({exc.code}): {detail}") from exc
    raise AssertionError("unreachable")


def load_state(state_file: Path) -> dict:
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {}


def save_state(state_file: Path, state: dict) -> None:
    state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


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


def build_byline(authors: list) -> str:
    """DEV has no subtitle field, so the body byline is the only place the real authors are credited."""
    if not authors:
        return ""
    names = [f"[{a['name']}]({a['url']})" if a["url"] else a["name"] for a in authors]
    return f"*By {join_names(names)}*"


def convert_tabs(body: str) -> str:
    """Flatten Docusaurus <Tabs>/<TabItem> framework-switcher blocks into headed sections.

    DEV has no tabs concept; without this, the <Tabs>/<TabItem> tags are unknown
    HTML and get stripped, taking each tab's label with them.
    """
    body = IMPORT_RE.sub("", body)

    def replace_tabs(match: re.Match) -> str:
        sections = [
            f"#### {label}\n\n{content.strip()}"
            for label, content in TAB_ITEM_RE.findall(match.group(1))
        ]
        return "\n\n".join(sections)

    return TABS_RE.sub(replace_tabs, body)


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
    prose after it. A `title` is kept as a bold label above the block.
    """

    def replace_fence(match: re.Match) -> str:
        indent, fence, language, meta = match.groups()
        title = re.search(r'title="([^"]*)"', meta)
        label = f"{indent}**{title.group(1)}**\n\n" if title else ""
        return f"{label}{indent}{fence}{language}"

    return CODE_FENCE_META_RE.sub(replace_fence, body)


def png_size(path: Path) -> tuple | None:
    """Read a PNG's intrinsic (width, height) from its IHDR header, without an image library."""
    try:
        with path.open("rb") as f:
            header = f.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", header[16:24])


def img_fixed_size(tag: str, src: str, static_dir: Path | None) -> tuple | None:
    """Return (width, height) for an <img> whose JSX style pins a px width/height, else None.

    Logos are sized via `style={{height: '60px'}}`; dropping that would make DEV show them
    at full column width, so a pinned dimension is kept and the other one is derived from
    the image's intrinsic aspect ratio when the file is available locally.
    """
    width = re.search(STYLE_PX_RE.format("width"), tag)
    height = re.search(STYLE_PX_RE.format("height"), tag)
    if not width and not height:
        return None
    width = int(width.group(1)) if width else None
    height = int(height.group(1)) if height else None
    intrinsic = png_size(static_dir / src.lstrip("/")) if static_dir and src.startswith("/") else None
    if intrinsic and all(intrinsic):
        if width is None:
            width = round(height * intrinsic[0] / intrinsic[1])
        elif height is None:
            height = round(width * intrinsic[1] / intrinsic[0])
    return width, height


def img_to_markdown(tag: str, static_dir: Path | None = None) -> str:
    src = re.search(r'src="([^"]+)"', tag)
    alt = re.search(r'alt="([^"]*)"', tag)
    if not src:
        return ""
    alt_text = alt.group(1) if alt else ""
    size = img_fixed_size(tag, src.group(1), static_dir)
    if size:
        # Kept as a sized <img> here; resize_fixed_images() turns it into a pre-resized image.
        attrs = "".join(f' {name}="{value}"' for name, value in zip(("width", "height"), size) if value)
        return f'<img src="{src.group(1)}" alt="{alt_text}"{attrs} />'
    return f"![{alt_text}]({src.group(1)})"


def image_row_table(cells: list) -> str:
    """Render [(img, caption | None), ...] as a one-row table: images as the header, captions below.

    DEV sizes table columns to their content, so each image cell gets a line of non-breaking
    spaces above and below it (DEV shows images as blocks): that gives every column the same
    width, wider than the longest caption, so the logos are evenly spaced with some breathing room.
    """
    longest_caption = max((len(caption) for _, caption in cells if caption), default=0)
    spacer = "&nbsp;" * max(IMAGE_ROW_MIN_SPACER, 2 * longest_caption + 4)
    rows = [
        "| " + " | ".join(f"{spacer} {img} {spacer}" for img, _ in cells) + " |",
        "|" + ":---:|" * len(cells),
    ]
    if any(caption for _, caption in cells):
        rows.append("| " + " | ".join(caption or "" for _, caption in cells) + " |")
    return "\n".join(rows)


def group_image_rows(lines: list) -> list:
    """Collapse runs of 2+ fixed-size images (each optionally followed by a caption) into tables."""
    paragraphs, cells = [], []

    def flush() -> None:
        if len(cells) > 1:
            paragraphs.append(image_row_table(cells))
        else:
            paragraphs.extend(part for cell in cells for part in cell if part)
        cells.clear()

    for line in lines:
        if line.startswith("<img "):
            cells.append((line, None))
        elif cells and cells[-1][1] is None and line.startswith("*") and line.endswith("*"):
            cells[-1] = (cells[-1][0], line)
        else:
            flush()
            paragraphs.append(line)
    flush()
    return paragraphs


def convert_html_blocks(body: str, static_dir: Path | None = None) -> str:
    """Rewrite the JSX `<div>` image/badge/caption blocks our posts use into plain Markdown.

    DEV sanitizes most raw HTML (and the JSX `style={{...}}` props are not valid HTML,
    and `{{` would be read as a Liquid tag anyway), so images, linked badges and captions
    are converted to their Markdown equivalents and the layout-only <div> wrappers are removed.
    Images with a fixed px size become a plain sized <img>. DEV wraps every body image in a
    block-level link, so a row of two or more of them (logos, each optionally followed by a
    caption) is laid out as a Markdown table to keep them side by side.
    """

    def replace_block(match: re.Match) -> str:
        inner = LINKED_IMG_RE.sub(
            lambda m: f"[{img_to_markdown(m.group(2), static_dir)}]({m.group(1)})", match.group(1)
        )
        inner = IMG_RE.sub(lambda m: img_to_markdown(m.group(0), static_dir), inner)
        inner = CAPTION_RE.sub(lambda m: f"*{m.group(1).strip()}*", inner)
        lines = [line.strip() for line in inner.split("\n")]
        lines = [line for line in lines if line and not re.fullmatch(r"</?div[^>]*>", line)]
        return "\n\n".join(group_image_rows(lines))

    return HTML_BLOCK_RE.sub(replace_block, body)


def strip_jsx(body: str) -> str:
    """Drop the handful of JSX-only bits our MDX posts use that DEV can't render."""
    body = re.sub(r"<!--\s*truncate\s*-->\n?", "", body)
    body = re.sub(r"\sstyle=\{\{[^}]*\}\}", "", body)
    return body


def clean_mdx(body: str, static_dir: Path | None = None) -> str:
    body = convert_code_fences(body)
    return strip_jsx(convert_html_blocks(convert_admonitions(convert_tabs(body)), static_dir))


def absolutize_urls(body: str, site_url: str) -> str:
    """Rewrite root-relative links/images so DEV can resolve and mirror them."""

    def repl(match: re.Match) -> str:
        return f"{match.group(1)}{site_url}{match.group(2)}"

    body = re.sub(r"(\]\()(/[^)\s]*)", repl, body)
    body = re.sub(r'((?:src|href)=["\'])(/[^"\']*)', repl, body)
    return body


def resize_fixed_images(body: str) -> str:
    """Swap each sized <img> (absolute src) for a Markdown image pre-resized by DEV's resizer."""

    def repl(match: re.Match) -> str:
        src, alt, width, height = match.groups()
        width, height = (round(int(value) * DEVTO_FIXED_IMAGE_SCALE) if value else "" for value in (width, height))
        url = DEVTO_IMAGE_RESIZER.format(width=width, height=height, url=urllib.parse.quote(src, safe=""))
        return f"![{alt}]({url})"

    return SIZED_IMG_RE.sub(repl, body)


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


def build_tags(frontmatter: dict) -> list:
    """DEV tags are lowercase alphanumeric (no hyphens), so `ai-agents` becomes `aiagents`."""
    tags = []
    for tag in frontmatter.get("tags") or []:
        name = re.sub(r"[^a-z0-9]+", "", str(tag).lower())[:MAX_TAG_LENGTH]
        if name and name not in tags:
            tags.append(name)
        if len(tags) == MAX_TAGS:
            break
    return tags


def render_markdown(path: Path, frontmatter: dict, body: str, site_url: str, authors: list) -> tuple:
    # Posts live in docs/blog/, their root-relative images in docs/static/.
    body = resize_fixed_images(absolutize_urls(clean_mdx(body, path.parent.parent / "static"), site_url))
    body = body.replace(SHIELDS_SVG_URL, SHIELDS_PNG_URL)
    # DEV renders the article title itself, so drop the duplicate leading H1.
    body = LEADING_H1_RE.sub("", body, count=1).strip()

    byline = build_byline(authors)
    if byline:
        body = f"{byline}\n\n{body}"

    canonical_url = build_canonical_url(site_url, frontmatter["slug"])
    published_on = resolve_post_date(path, frontmatter)
    when = f" on {published_on.strftime('%B')} {published_on.day}, {published_on.year}" if published_on else ""
    body += f"\n\n---\n\n*Originally published at [kernel.yaala.ai]({canonical_url}){when}.*\n"
    return body, canonical_url


def build_article(
        path: Path,
        frontmatter: dict,
        body: str,
        site_url: str,
        authors_map: dict,
) -> dict:
    authors = resolve_authors(frontmatter, authors_map)
    content, canonical_url = render_markdown(path, frontmatter, body, site_url, authors)
    article = {
        "title": frontmatter["title"],
        "body_markdown": content,
        "published": True,
        "tags": build_tags(frontmatter),
        "canonical_url": canonical_url,
        "main_image": absolutize_url(frontmatter.get("image"), site_url),
        "description": frontmatter.get("description"),
    }
    return {key: value for key, value in article.items() if value is not None}


def content_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def article_hash(article: dict) -> str:
    """Hash what is sent (not the source), so converter fixes also refresh already-synced articles."""
    return content_hash(json.dumps(article, sort_keys=True))


def publish_article(api_key: str, organization_id: str | None, article: dict) -> dict:
    if organization_id:
        article = {**article, "organization_id": int(organization_id)}
    data = devto_request(api_key, "POST", "/articles", {"article": article})
    return {"devto_article_id": data["id"], "devto_url": data.get("url")}


def update_article(api_key: str, article_id: int, article: dict) -> dict:
    data = devto_request(api_key, "PUT", f"/articles/{article_id}", {"article": article})
    return {"devto_article_id": data["id"], "devto_url": data.get("url")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync docs/blog markdown posts to DEV Community.")
    parser.add_argument("--blog-dir", type=Path, default=DEFAULT_BLOG_DIR)
    parser.add_argument("--state-file", type=Path, default=None)
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL)
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen; call no APIs that write.")
    parser.add_argument(
        "--preview",
        action="store_true",
        help=f"Write the Markdown that would be sent to DEV to <post>{PREVIEW_SUFFIX}; call no APIs.",
    )
    parser.add_argument(
        "--find-organization",
        metavar="USERNAME",
        help="Print the id of the DEV organization with this username (dev.to/USERNAME), then exit.",
    )
    parser.add_argument(
        "--post",
        action="append",
        default=[],
        metavar="FILE",
        help="Only sync this post (file name or path under --blog-dir); repeat for several. Default: all posts.",
    )
    args = parser.parse_args()

    api_key = os.environ.get("DEVTO_API_KEY")
    organization_id = os.environ.get("DEVTO_ORGANIZATION_ID") or None
    writes = not (args.dry_run or args.preview)

    if args.find_organization:
        # Organization lookups are public, so no API key is needed.
        try:
            organization = devto_request(api_key, "GET", f"/organizations/{args.find_organization}")
        except DevtoAPIError as exc:
            print(f"No organization found at dev.to/{args.find_organization}: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"  {organization['id']}  {organization['name']!r}  (https://dev.to/{organization['username']})")
        return

    if writes and not api_key:
        print("Error: DEVTO_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    site_url = args.site_url.rstrip("/")
    state_file = args.state_file or (args.blog_dir / STATE_FILENAME)
    state = load_state(state_file)
    authors_map = load_authors(args.blog_dir)

    paths = sorted(path for path in args.blog_dir.glob("*.md") if not path.name.endswith(PREVIEW_SUFFIX))
    if args.post:
        wanted = {Path(name).name for name in args.post}
        missing = wanted - {path.name for path in paths}
        if missing:
            print(f"Error: no such post in {args.blog_dir}: {', '.join(sorted(missing))}", file=sys.stderr)
            sys.exit(1)
        paths = [path for path in paths if path.name in wanted]

    for path in paths:

        post = parse_post(path)
        frontmatter, body, raw = post["frontmatter"], post["body"], post["raw"]

        if frontmatter.get("devto") is False:
            continue

        if not frontmatter.get("title") or not frontmatter.get("slug"):
            print(f"skipping {path.name}: missing required frontmatter (title/slug)")
            continue

        article = build_article(path, frontmatter, body, site_url, authors_map)

        if args.preview:
            preview_path = path.with_name(path.name[: -len(".md")] + PREVIEW_SUFFIX)
            meta = {key: value for key, value in article.items() if key != "body_markdown"}
            preview_path.write_text(
                f"<!--\n{json.dumps(meta, indent=2)}\n-->\n\n{article['body_markdown']}", encoding="utf-8"
            )
            print(f"wrote {preview_path}")
            continue

        digest = article_hash(article)
        record = state.get(path.name)

        if record and record.get("content_hash") == digest:
            continue

        action = "update" if record else "publish"
        if args.dry_run:
            print(
                f"[dry-run] would {action} DEV article {article['title']!r} "
                f"(tags={article['tags']}, canonical={article['canonical_url']})"
            )
            continue

        if record:
            result = update_article(api_key, record["devto_article_id"], article)
        else:
            result = publish_article(api_key, organization_id, article)

        state[path.name] = {"content_hash": digest, **result}
        # Save after every post so a later failure can't cause this one to be published twice.
        save_state(state_file, state)
        print(f"{'updated' if record else 'published'} {path.name} -> {result.get('devto_url')}")


if __name__ == "__main__":
    main()
