"""
LinkedIn URL parser — extracts Activity ID from 3 supported URL formats.

Supported formats:
  1. Raw ID:          7302346926123798528
  2. Activity URL:    https://www.linkedin.com/feed/update/urn:li:activity:7302346926123798528/
  3. Full post URL:   https://www.linkedin.com/posts/username_title-activity-7302346926123798528-dMnz
"""

from __future__ import annotations

import re
from typing import Optional, Tuple


# Regex patterns for the three URL formats
_PATTERNS = [
    # Activity URN in URL: /feed/update/urn:li:activity:XXXXXXXXXX
    re.compile(r"urn:li:activity:(\d{15,25})"),
    # Full post URL: -activity-XXXXXXXXXX- at the end
    re.compile(r"-activity-(\d{15,25})[-/]?"),
    # Bare numeric ID (15–25 digits, whole string)
    re.compile(r"^\s*(\d{15,25})\s*$"),
]

# LinkedIn post base URL
LINKEDIN_POST_BASE = "https://www.linkedin.com/feed/update/urn:li:activity:{}"


def extract_activity_id(url_or_id: str) -> Optional[str]:
    """
    Extract the LinkedIn Activity ID from any supported URL format.

    Args:
        url_or_id: LinkedIn post URL, activity URL, or bare activity ID.

    Returns:
        The activity ID string (digits only), or None if not recognised.
    """
    for pattern in _PATTERNS:
        match = pattern.search(url_or_id)
        if match:
            return match.group(1)
    return None


def build_post_url(activity_id: str) -> str:
    """Build a canonical LinkedIn post URL from an activity ID."""
    return LINKEDIN_POST_BASE.format(activity_id)


def validate_and_parse(raw: str) -> Tuple[str, str]:
    """
    Validate input and return (activity_id, post_url).

    Raises:
        ValueError: If the input cannot be parsed as a LinkedIn post URL.
    """
    activity_id = extract_activity_id(raw.strip())
    if not activity_id:
        raise ValueError(
            f"Cannot parse LinkedIn post URL or ID: {raw!r}\n"
            "Supported formats:\n"
            "  • Raw ID:        7302346926123798528\n"
            "  • Activity URL:  https://www.linkedin.com/feed/update/urn:li:activity:7302346926123798528/\n"
            "  • Full post URL: https://www.linkedin.com/posts/username-activity-7302346926123798528-xxxx"
        )
    post_url = build_post_url(activity_id)
    return activity_id, post_url
