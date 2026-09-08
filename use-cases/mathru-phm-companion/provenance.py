"""Provenance rules for the clinical data files.

Every clinical value in this project comes from a published Ministry of Health document,
never from the model. These helpers make that claim checkable rather than decorative: a data
file may only assert `status: sourced` once it can say where its values came from.

The status check is deliberately strict. Only the exact string `sourced` counts as populated;
anything else, including a typo, is treated as a placeholder and fails toward escalation. The
alternative - treating "not the string placeholder" as populated - would let a one-character
mistake silently switch the danger-sign table from escalating everything to trusting nothing.
"""

from __future__ import annotations

from typing import Any

SOURCED = "sourced"
PLACEHOLDER = "placeholder"

TODO_MARKER = "TODO"

REQUIRED_FIELDS = (
    "source",
    "publisher",
    "document_date",
    "url",
    "retrieved",
    "cross_checked_against",
    "clinician_review",
)

# Re-uploads of unknown vintage. Convenient, unverifiable, and banned as a citation.
BANNED_HOSTS = ("scribd.com", "docslib", "vdocuments", "coursehero", "studocu", "academia.edu")

# A source must be the government original, or WHO where the local list is thinner.
ALLOWED_HOSTS = ("gov.lk", "who.int")


def is_sourced(data: dict[str, Any]) -> bool:
    """Whether a data file's values may be used. Only an exact `sourced` qualifies."""
    return data.get("status") == SOURCED


def provenance_problems(data: dict[str, Any]) -> list[str]:
    """Every reason this file may not claim `sourced`. Empty means it may.

    Checked regardless of the file's current status, so a file can be validated before its
    status is flipped.
    """
    problems: list[str] = []
    block = data.get("provenance")

    if not isinstance(block, dict):
        return ["no provenance block"]

    for field in REQUIRED_FIELDS:
        value = block.get(field)
        if value is None or not str(value).strip():
            problems.append(f"provenance.{field} is empty")
        elif TODO_MARKER in str(value):
            problems.append(f"provenance.{field} is still {TODO_MARKER}")

    url = str(block.get("url") or "").lower()
    if url and TODO_MARKER not in url:
        if any(host in url for host in BANNED_HOSTS):
            problems.append(f"provenance.url cites a banned re-upload host: {url}")
        elif not any(host in url for host in ALLOWED_HOSTS):
            problems.append(f"provenance.url is not a {' or '.join(ALLOWED_HOSTS)} source: {url}")

    return problems
