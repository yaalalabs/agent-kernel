#!/usr/bin/env python3
"""
Sync docs/blog/*.md posts to a Medium publication (or a personal Medium profile).

Medium's public API was closed to new integrations on 2025-01-01: Medium no longer
issues new integration tokens, and - even for tokens issued before that date - there
is no endpoint to update or delete a post once it has been created. Given those two
constraints, this script only ever *creates* new Medium posts:

  - Every blog file that has never been synced before gets a new Medium post
    (a draft by default, so a human reviews and hits "Publish" on Medium's side).
  - A blog file that was already synced and then edited is left alone; the script
    prints a warning instead of creating a duplicate or trying to patch the
    original (Medium's API has no way to do the latter).
  - What has already been synced is tracked in a small JSON state file next to
    the posts, so re-runs are idempotent.

Usage:
    # See what would be created, without calling the Medium API
    python scripts/sync_medium_blog.py --dry-run

    # Find the publicationId for MEDIUM_PUBLICATION_ID
    python scripts/sync_medium_blog.py --list-publications

    # Create drafts for every not-yet-synced post
    python scripts/sync_medium_blog.py

Environment:
    MEDIUM_INTEGRATION_TOKEN   Required. A Medium integration token
                               (Settings -> Security and apps -> Integration tokens).
    MEDIUM_PUBLICATION_ID      Optional. Publish under this publication instead of
                               the token owner's personal profile.

A post is skipped entirely if its frontmatter sets `medium: false`.
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

import markdown
import yaml

MEDIUM_API_BASE = "https://api.medium.com/v1"
DEFAULT_BLOG_DIR = Path("docs/blog")
DEFAULT_SITE_URL = "https://kernel.yaala.ai"
AUTHORS_FILENAME = "authors.json"
MAX_TAGS = 5

FILENAME_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
IMPORT_RE = re.compile(r"^import .+ from ['\"]@theme/\w+['\"];?\s*$\n?", re.MULTILINE)
TABS_RE = re.compile(r"<Tabs>(.*?)</Tabs>", re.DOTALL)
TAB_ITEM_RE = re.compile(r'<TabItem\s+value="[^"]*"\s+label="([^"]*)"[^>]*>(.*?)</TabItem>', re.DOTALL)
ADMONITION_RE = re.compile(r"^:::(\w+)(?:[ \t]+([^\n]*))?\n(.*?)\n:::[ \t]*$", re.MULTILINE | re.DOTALL)


class MediumAPIError(RuntimeError):
    pass


def medium_request(token: str, method: str, path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"{MEDIUM_API_BASE}{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
    )
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    request.add_header("Accept-Charset", "utf-8")
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise MediumAPIError(f"Medium API {method} {path} failed ({exc.code}): {detail}") from exc


def get_authenticated_user(token: str) -> dict:
    return medium_request(token, "GET", "/me")["data"]


def list_publications(token: str, user_id: str) -> list:
    return medium_request(token, "GET", f"/users/{user_id}/publications")["data"]


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


def build_byline_html(authors: list) -> str:
    if not authors:
        return ""
    parts = [f'<a href="{a["url"]}">{a["name"]}</a>' if a["url"] else a["name"] for a in authors]
    return f"<p><em>By {', '.join(parts)}</em></p>"


def convert_tabs(body: str) -> str:
    """Flatten Docusaurus <Tabs>/<TabItem> framework-switcher blocks into headed sections.

    Medium has no tabs concept; without this, the <Tabs>/<TabItem> tags are unrecognized
    HTML and get dropped by Medium's own sanitizer, taking each tab's label with them.
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


def strip_jsx(body: str) -> str:
    """Drop the handful of JSX-only bits our MDX posts use that Medium can't render."""
    body = re.sub(r"<!--\s*truncate\s*-->", "", body)
    body = re.sub(r"\sstyle=\{\{[^}]*\}\}", "", body)
    return body


def clean_mdx(body: str) -> str:
    return strip_jsx(convert_admonitions(convert_tabs(body)))


def absolutize_urls(body: str, site_url: str) -> str:
    """Rewrite root-relative links/images so Medium can resolve and mirror them."""

    def repl(match: re.Match) -> str:
        return f"{match.group(1)}{site_url}{match.group(2)}"

    body = re.sub(r"(\]\()(/[^)\s]*)", repl, body)
    body = re.sub(r'((?:src|href)=["\'])(/[^"\']*)', repl, body)
    return body


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


def render_html(
        frontmatter: dict,
        body: str,
        site_url: str,
        authors_map: dict,
        published_on: datetime.date | None = None,
) -> tuple:
    body = absolutize_urls(clean_mdx(body), site_url)
    html = markdown.markdown(body, extensions=["fenced_code", "tables", "sane_lists"])

    byline = build_byline_html(resolve_authors(frontmatter, authors_map))
    if byline:
        marker = "</h1>"
        idx = html.find(marker)
        insert_at = idx + len(marker) if idx != -1 else 0
        html = html[:insert_at] + byline + html[insert_at:]

    canonical_url = build_canonical_url(site_url, frontmatter["slug"])
    date_text = f" on {published_on.day} {published_on:%B %Y}" if published_on else ""
    html += f'\n<p><em>Originally published{date_text} at <a href="{canonical_url}">kernel.yaala.ai</a>.</em></p>'
    return html, canonical_url


def content_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_medium_post(
        token: str,
        user_id: str,
        publication_id: str | None,
        frontmatter: dict,
        body: str,
        site_url: str,
        authors_map: dict,
        published_on: datetime.date | None,
        publish_status: str,
        notify_followers: bool,
        dry_run: bool,
) -> dict:
    html, canonical_url = render_html(frontmatter, body, site_url, authors_map, published_on)
    tags = [str(tag)[:25] for tag in (frontmatter.get("tags") or [])][:MAX_TAGS]
    payload = {
        "title": frontmatter["title"],
        "contentFormat": "html",
        "content": html,
        "canonicalUrl": canonical_url,
        "tags": tags,
        "publishStatus": publish_status,
        "notifyFollowers": notify_followers,
    }

    if dry_run:
        print(
            f"[dry-run] would create Medium post {payload['title']!r} "
            f"(status={publish_status}, tags={tags}, canonical={canonical_url})"
        )
        return {"medium_post_id": "dry-run", "medium_url": canonical_url}

    endpoint = f"/publications/{publication_id}/posts" if publication_id else f"/users/{user_id}/posts"
    data = medium_request(token, "POST", endpoint, payload)["data"]
    return {"medium_post_id": data["id"], "medium_url": data.get("url")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync docs/blog markdown posts to Medium.")
    parser.add_argument("--blog-dir", type=Path, default=DEFAULT_BLOG_DIR)
    parser.add_argument("--state-file", type=Path, default=None)
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL)
    parser.add_argument("--publish-status", choices=["draft", "public", "unlisted"], default="draft")
    parser.add_argument("--notify-followers", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen; call no APIs that write.")
    parser.add_argument(
        "--list-publications",
        action="store_true",
        help="Print the publications this token can post to (with their id), then exit.",
    )
    args = parser.parse_args()

    token = os.environ.get("MEDIUM_INTEGRATION_TOKEN")
    if not token:
        print("Error: MEDIUM_INTEGRATION_TOKEN is not set.", file=sys.stderr)
        sys.exit(1)

    user = get_authenticated_user(token)
    print(f"Authenticated to Medium as {user['username']} (id={user['id']})")

    if args.list_publications:
        for pub in list_publications(token, user["id"]):
            print(f"  {pub['id']}  {pub['name']!r}")
        return

    publication_id = os.environ.get("MEDIUM_PUBLICATION_ID")
    state_file = args.state_file or (args.blog_dir / ".medium-sync-state.json")
    state = load_state(state_file)
    state_changed = False
    authors_map = load_authors(args.blog_dir)

    for path in sorted(args.blog_dir.glob("*.md")):
        post = parse_post(path)
        frontmatter, body, raw = post["frontmatter"], post["body"], post["raw"]

        if frontmatter.get("medium") is False:
            continue

        if not frontmatter.get("title") or not frontmatter.get("slug"):
            print(f"skipping {path.name}: missing required frontmatter (title/slug)")
            continue

        digest = content_hash(raw)
        record = state.get(path.name)

        if record and record.get("content_hash") == digest:
            continue

        if record:
            print(
                f"warning: {path.name} changed after it was already synced to Medium "
                f"({record.get('medium_url')}). Medium's API cannot update an existing "
                f"post - edit it by hand on medium.com if the change should carry over."
            )
            continue

        result = create_medium_post(
            token=token,
            user_id=user["id"],
            publication_id=publication_id,
            frontmatter=frontmatter,
            body=body,
            site_url=args.site_url.rstrip("/"),
            authors_map=authors_map,
            published_on=resolve_post_date(path, frontmatter),
            publish_status=args.publish_status,
            notify_followers=args.notify_followers,
            dry_run=args.dry_run,
        )

        if not args.dry_run:
            state[path.name] = {
                "content_hash": digest,
                "medium_post_id": result["medium_post_id"],
                "medium_url": result.get("medium_url"),
                "publish_status": args.publish_status,
            }
            state_changed = True
            print(f"synced {path.name} -> {result.get('medium_url')}")

    if state_changed:
        save_state(state_file, state)
        print(f"updated {state_file}")


if __name__ == "__main__":
    main()
