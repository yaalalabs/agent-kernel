#!/usr/bin/env python3
"""
Sync docs/blog/*.md posts to a Hashnode publication.

Every post is published by the single account that owns the publication (the token
owner); the real authors from `authors.json` are credited in the post's subtitle and
in a byline at the top of the body. The Docusaurus site stays the source of truth:

  - A blog file that has never been synced gets a new Hashnode post, published
    immediately, backdated to the date it went live on the website, and pointing
    its canonical URL back at kernel.yaala.ai.
  - A blog file that was already synced and then edited gets its Hashnode post
    updated in place (Hashnode's API supports updates, unlike Medium's).
  - What has already been synced is tracked in a small JSON state file next to
    the posts, so re-runs are idempotent.

Usage:
    # Write the Markdown that would be sent to Hashnode next to each post (no token needed)
    python scripts/sync_hashnode_blog.py --preview

    # See what would be created/updated, without calling the Hashnode API
    python scripts/sync_hashnode_blog.py --dry-run

    # Find the publication id for HASHNODE_PUBLICATION_ID
    python scripts/sync_hashnode_blog.py --find-publication agentkernel.hashnode.dev

    # Publish new posts and update changed ones
    python scripts/sync_hashnode_blog.py

    # Sync just one post
    python scripts/sync_hashnode_blog.py --post 2026-09-14-scheduled-tasks.md

Environment:
    HASHNODE_PAT              Required (except for --preview/--dry-run). A Hashnode
                              Personal Access Token (Account settings -> Developer).
    HASHNODE_PUBLICATION_ID   Required (except for --preview/--find-publication). The
                              publication to publish to. Its API access needs the Pro plan.

A post is skipped entirely if its frontmatter sets `hashnode: false`.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

# gql.hashnode.com was retired on 2026-05-13 and now 301s to an announcement page.
HASHNODE_API_URL = "https://gql-beta.hashnode.com"
DEFAULT_BLOG_DIR = Path("docs/blog")
DEFAULT_SITE_URL = "https://kernel.yaala.ai"
AUTHORS_FILENAME = "authors.json"
STATE_FILENAME = ".hashnode-sync-state.json"
PREVIEW_SUFFIX = ".hashnode-preview.md"
MAX_TAGS = 15

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

PUBLISH_POST_MUTATION = """
mutation PublishPost($input: PublishPostInput!) {
  publishPost(input: $input) { post { id url } }
}
"""

UPDATE_POST_MUTATION = """
mutation UpdatePost($input: UpdatePostInput!) {
  updatePost(input: $input) { post { id url } }
}
"""

FIND_PUBLICATION_QUERY = """
query FindPublication($host: String!) {
  publication(host: $host) { id title url isTeam }
}
"""


class HashnodeAPIError(RuntimeError):
    pass


def hashnode_request(token: str, query: str, variables: dict) -> dict:
    request = urllib.request.Request(
        HASHNODE_API_URL,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        method="POST",
    )
    # Hashnode expects the raw Personal Access Token, without a "Bearer" prefix.
    request.add_header("Authorization", token)
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HashnodeAPIError(f"Hashnode API request failed ({exc.code}): {detail}") from exc
    if payload.get("errors"):
        messages = "; ".join(error.get("message", str(error)) for error in payload["errors"])
        raise HashnodeAPIError(f"Hashnode API returned errors: {messages}")
    return payload["data"]


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


def build_subtitle(authors: list) -> str | None:
    """Hashnode shows the subtitle right under the title - the most visible place to credit authors."""
    if not authors:
        return None
    return f"By {join_names([a['name'] for a in authors])}"


def build_byline(authors: list) -> str:
    if not authors:
        return ""
    names = [f"[{a['name']}]({a['url']})" if a["url"] else a["name"] for a in authors]
    return f"*By {join_names(names)}*"


def convert_tabs(body: str) -> str:
    """Flatten Docusaurus <Tabs>/<TabItem> framework-switcher blocks into headed sections.

    Hashnode has no tabs concept; without this, the <Tabs>/<TabItem> tags are unknown
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


def img_to_markdown(tag: str) -> str:
    src = re.search(r'src="([^"]+)"', tag)
    alt = re.search(r'alt="([^"]*)"', tag)
    return f"![{alt.group(1) if alt else ''}]({src.group(1)})" if src else ""


def convert_html_blocks(body: str) -> str:
    """Rewrite the JSX `<div>` image/badge/caption blocks our posts use into plain Markdown.

    Hashnode's Markdown renderer drops most raw HTML (and the JSX `style={{...}}` props
    are not valid HTML anyway), so images, linked badges and captions are converted to
    their Markdown equivalents and the layout-only <div> wrappers are removed.
    """

    def replace_block(match: re.Match) -> str:
        inner = LINKED_IMG_RE.sub(lambda m: f"[{img_to_markdown(m.group(2))}]({m.group(1)})", match.group(1))
        inner = IMG_RE.sub(lambda m: img_to_markdown(m.group(0)), inner)
        inner = CAPTION_RE.sub(lambda m: f"*{m.group(1).strip()}*", inner)
        lines = [line.strip() for line in inner.split("\n")]
        return "\n\n".join(line for line in lines if line and not re.fullmatch(r"</?div[^>]*>", line))

    return HTML_BLOCK_RE.sub(replace_block, body)


def strip_jsx(body: str) -> str:
    """Drop the handful of JSX-only bits our MDX posts use that Hashnode can't render."""
    body = re.sub(r"<!--\s*truncate\s*-->\n?", "", body)
    body = re.sub(r"\sstyle=\{\{[^}]*\}\}", "", body)
    return body


def clean_mdx(body: str) -> str:
    return strip_jsx(convert_html_blocks(convert_admonitions(convert_tabs(body))))


def absolutize_urls(body: str, site_url: str) -> str:
    """Rewrite root-relative links/images so Hashnode can resolve and mirror them."""

    def repl(match: re.Match) -> str:
        return f"{match.group(1)}{site_url}{match.group(2)}"

    body = re.sub(r"(\]\()(/[^)\s]*)", repl, body)
    body = re.sub(r'((?:src|href)=["\'])(/[^"\']*)', repl, body)
    return body


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


def build_hashnode_slug(slug: str) -> str:
    """Hashnode slugs are a single path segment; use the last segment of the Docusaurus slug."""
    return slug.strip("/").split("/")[-1]


def build_tags(frontmatter: dict) -> list:
    tags = []
    for tag in (frontmatter.get("tags") or [])[:MAX_TAGS]:
        slug = re.sub(r"[^a-z0-9]+", "-", str(tag).lower()).strip("-")
        if slug:
            tags.append({"slug": slug, "name": str(tag)})
    return tags


def render_markdown(frontmatter: dict, body: str, site_url: str, authors: list) -> tuple:
    body = absolutize_urls(clean_mdx(body), site_url)
    # Hashnode renders the post title itself, so drop the duplicate leading H1.
    body = LEADING_H1_RE.sub("", body, count=1).strip()

    byline = build_byline(authors)
    if byline:
        body = f"{byline}\n\n{body}"

    canonical_url = build_canonical_url(site_url, frontmatter["slug"])
    body += f"\n\n---\n\n*Originally published at [kernel.yaala.ai]({canonical_url}).*\n"
    return body, canonical_url


def build_post_input(
        path: Path,
        frontmatter: dict,
        body: str,
        site_url: str,
        authors_map: dict,
) -> dict:
    authors = resolve_authors(frontmatter, authors_map)
    content, canonical_url = render_markdown(frontmatter, body, site_url, authors)
    post_input = {
        "title": frontmatter["title"],
        "subtitle": build_subtitle(authors),
        "contentMarkdown": content,
        "slug": build_hashnode_slug(frontmatter["slug"]),
        "tags": build_tags(frontmatter),
        "originalArticleURL": canonical_url,
        "coverImage": absolutize_url(frontmatter.get("image"), site_url),
        "metaDescription": frontmatter.get("description"),
    }
    published_on = resolve_post_date(path, frontmatter)
    if published_on:
        post_input["publishedAt"] = f"{published_on.isoformat()}T00:00:00.000Z"
    return {key: value for key, value in post_input.items() if value is not None}


def content_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def publish_post(token: str, publication_id: str, post_input: dict) -> dict:
    data = hashnode_request(token, PUBLISH_POST_MUTATION, {"input": {"publicationId": publication_id, **post_input}})
    post = data["publishPost"]["post"]
    return {"hashnode_post_id": post["id"], "hashnode_url": post.get("url")}


def update_post(token: str, post_id: str, post_input: dict) -> dict:
    data = hashnode_request(token, UPDATE_POST_MUTATION, {"input": {"id": post_id, **post_input}})
    post = data["updatePost"]["post"]
    return {"hashnode_post_id": post["id"], "hashnode_url": post.get("url")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync docs/blog markdown posts to Hashnode.")
    parser.add_argument("--blog-dir", type=Path, default=DEFAULT_BLOG_DIR)
    parser.add_argument("--state-file", type=Path, default=None)
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL)
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen; call no APIs that write.")
    parser.add_argument(
        "--preview",
        action="store_true",
        help=f"Write the Markdown that would be sent to Hashnode to <post>{PREVIEW_SUFFIX}; call no APIs.",
    )
    parser.add_argument(
        "--find-publication",
        metavar="HOST",
        help="Print the id of the publication at HOST (e.g. agentkernel.hashnode.dev), then exit.",
    )
    parser.add_argument(
        "--post",
        action="append",
        default=[],
        metavar="FILE",
        help="Only sync this post (file name or path under --blog-dir); repeat for several. Default: all posts.",
    )
    args = parser.parse_args()

    token = os.environ.get("HASHNODE_PAT")
    publication_id = os.environ.get("HASHNODE_PUBLICATION_ID")
    writes = not (args.dry_run or args.preview)

    if (writes or args.find_publication) and not token:
        print("Error: HASHNODE_PAT is not set.", file=sys.stderr)
        sys.exit(1)

    if args.find_publication:
        publication = hashnode_request(token, FIND_PUBLICATION_QUERY, {"host": args.find_publication})["publication"]
        if not publication:
            print(f"No publication found at {args.find_publication}.", file=sys.stderr)
            sys.exit(1)
        print(f"  {publication['id']}  {publication['title']!r}  ({publication['url']})")
        return

    if writes and not publication_id:
        print("Error: HASHNODE_PUBLICATION_ID is not set.", file=sys.stderr)
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

        if frontmatter.get("hashnode") is False:
            continue

        if not frontmatter.get("title") or not frontmatter.get("slug"):
            print(f"skipping {path.name}: missing required frontmatter (title/slug)")
            continue

        post_input = build_post_input(path, frontmatter, body, site_url, authors_map)

        if args.preview:
            preview_path = path.with_name(path.name[: -len(".md")] + PREVIEW_SUFFIX)
            meta = {key: value for key, value in post_input.items() if key != "contentMarkdown"}
            preview_path.write_text(
                f"<!--\n{json.dumps(meta, indent=2)}\n-->\n\n{post_input['contentMarkdown']}", encoding="utf-8"
            )
            print(f"wrote {preview_path}")
            continue

        digest = content_hash(raw)
        record = state.get(path.name)

        if record and record.get("content_hash") == digest:
            continue

        action = "update" if record else "publish"
        if args.dry_run:
            print(
                f"[dry-run] would {action} Hashnode post {post_input['title']!r} "
                f"(slug={post_input['slug']}, tags={[t['slug'] for t in post_input['tags']]}, "
                f"canonical={post_input['originalArticleURL']})"
            )
            continue

        if record:
            result = update_post(token, record["hashnode_post_id"], post_input)
        else:
            result = publish_post(token, publication_id, post_input)

        state[path.name] = {"content_hash": digest, **result}
        # Save after every post so a later failure can't cause this one to be published twice.
        save_state(state_file, state)
        print(f"{'updated' if record else 'published'} {path.name} -> {result.get('hashnode_url')}")


if __name__ == "__main__":
    main()
