"""
CLI entry point for LinkedIn Post Extractor.

Usage:
    python -m src.main --url <linkedin_post_url> [options]

Examples:
    python -m src.main --url "https://www.linkedin.com/posts/example-activity-7302346926123798528-dMnz"
    python -m src.main --url 7302346926123798528 --output output/my_post --scroll 10
    python -m src.main --url <url> --no-reactions
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .extractor import LinkedInExtractor, DEFAULT_CDP_URL
from .exporter import save_all


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkedin-extractor",
        description="Extract comments and reactions from a LinkedIn post using your local Chrome browser.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported URL formats:
  7302346926123798528
  https://www.linkedin.com/feed/update/urn:li:activity:7302346926123798528/
  https://www.linkedin.com/posts/username-activity-7302346926123798528-xxxx

Before running, start Chrome with:
  scripts\\start_chrome_debug.bat   (Windows)
        """,
    )
    parser.add_argument(
        "--url", "-u",
        required=True,
        help="LinkedIn post URL or activity ID",
    )
    parser.add_argument(
        "--output", "-o",
        default="output/result",
        help="Output file stem (default: output/result). "
             "Files will be saved as <stem>.json, <stem>_comments.csv, <stem>_reactions.csv",
    )
    parser.add_argument(
        "--scroll", "-s",
        type=int,
        default=5,
        help="Number of scroll iterations to load more content (default: 5, max: 30)",
    )
    parser.add_argument(
        "--no-comments",
        action="store_true",
        help="Skip comment extraction",
    )
    parser.add_argument(
        "--no-reactions",
        action="store_true",
        help="Skip reaction extraction",
    )
    parser.add_argument(
        "--cdp-url",
        default=DEFAULT_CDP_URL,
        help=f"Chrome DevTools Protocol URL (default: {DEFAULT_CDP_URL})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    _setup_logging(args.verbose)

    logger = logging.getLogger(__name__)

    extractor = LinkedInExtractor(cdp_url=args.cdp_url, scroll_count=args.scroll)

    logger.info("Starting extraction for: %s", args.url)

    result = extractor.extract(
        url_or_id=args.url,
        include_comments=not args.no_comments,
        include_reactions=not args.no_reactions,
    )

    if result.errors and not result.comments and not result.reactions:
        logger.error("Extraction failed:")
        for err in result.errors:
            logger.error("  %s", err)
        return 1

    # Save outputs
    paths = save_all(result, args.output)

    print("\n" + "=" * 60)
    print(f"  ✅ Extraction complete!")
    print(f"  📝 Comments  : {result.total_comments}")
    print(f"  👍 Reactions : {result.total_reactions}")
    if result.errors:
        print(f"  ⚠️  Warnings  : {len(result.errors)}")
    print("=" * 60)
    print(f"  📄 JSON      : {paths['json']}")
    print(f"  📊 Comments  : {paths['comments_csv']}")
    print(f"  📊 Reactions : {paths['reactions_csv']}")
    print("=" * 60 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
