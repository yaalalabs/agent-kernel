#!/usr/bin/env python3
"""
Fail if any docs/blog post uses an SVG image (see utils/images.py for why).

Run by the docs deploy workflow before the website is built, so a post with an SVG image
stops the deploy before anything is published.

Usage:
    python scripts/sync_blogs/check_images.py
"""

import argparse
from pathlib import Path

from utils.common import DEFAULT_BLOG_DIR
from utils.images import check_blog_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail if any blog post uses an SVG image.")
    parser.add_argument("--blog-dir", type=Path, default=DEFAULT_BLOG_DIR)
    args = parser.parse_args()
    check_blog_dir(args.blog_dir)
    print("No SVG images in blog posts.")


if __name__ == "__main__":
    main()
