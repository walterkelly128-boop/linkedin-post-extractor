import re
from urllib.parse import urlparse, unquote
from typing import Optional
import httpx

from .models import PostEntity
from .config import DEFAULT_USER_AGENT


def resolve_canonical_activity_urn(url: str, timeout: float = 6.0) -> Optional[str]:
    """
    Fetch public HTML metadata to resolve the real canonical `urn:li:activity:<id>`.
    Essential for UGC posts where ugcPost ID differs from the feed activity ID.
    """
    if not url.startswith("http://") and not url.startswith("https://"):
        return None

    try:
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            html = resp.text

            # Reaction requests are keyed by the post's UGC URN, which can differ
            # from the activity URN in the permalink. Prefer the UGC URN when present.
            m_ugc = re.search(r'urn:li:ugcPost:(\\d+)', html)
            if m_ugc:
                return f"urn:li:ugcPost:{m_ugc.group(1)}"

            # 1. Search for lnkd:url meta tag
            # e.g. <meta property="lnkd:url" content="...urn:li:activity:7503358105997725696">
            m_lnkd = re.search(r'property=["\']lnkd:url["\']\s+content=["\'][^"\']*urn:li:activity:(\d+)', html)
            if m_lnkd:
                return f"urn:li:activity:{m_lnkd.group(1)}"

            # 2. Search for canonical link
            # e.g. <link rel="canonical" href="...activity-7503358105997725696...">
            m_canon = re.search(r'activity-(\d+)', html)
            if m_canon:
                return f"urn:li:activity:{m_canon.group(1)}"

            # 3. Search for any activity URN
            m_any = re.search(r'urn:li:activity:(\d+)', html)
            if m_any:
                return f"urn:li:activity:{m_any.group(1)}"
    except Exception:
        pass

    return None


def parse_post_url(url_or_id: str, resolve_canonical: bool = True) -> PostEntity:
    """
    Parse any LinkedIn post URL, URN string, or numeric ID into a normalized PostEntity.
    """
    clean_input = url_or_id.strip()
    unquoted = unquote(clean_input)

    entity_type = "activity"
    entity_id = ""

    # 1. Check for explicit urn:li:(ugcPost|activity|share):<id>
    urn_match = re.search(r"urn:li:(ugcPost|activity|share):(\d+)", unquoted)
    if urn_match:
        entity_type = urn_match.group(1)
        entity_id = urn_match.group(2)

    # 2. Check for slug patterns: ugcPost-<id> or activity-<id>
    elif re.search(r"(ugcPost|activity)-(\d+)", unquoted):
        slug_match = re.search(r"(ugcPost|activity)-(\d+)", unquoted)
        entity_type = slug_match.group(1)
        entity_id = slug_match.group(2)

    # 3. Check for pure digits
    elif re.match(r"^(\d{15,20})$", clean_input):
        entity_id = clean_input
        entity_type = "activity"

    else:
        raise ValueError(
            f"Unable to parse LinkedIn post entity from input: '{clean_input}'.\n"
            f"Please provide a valid LinkedIn post link containing ugcPost/activity ID or URN."
        )

    base_urn = f"urn:li:{entity_type}:{entity_id}"
    activity_urn = None

    if entity_type == "activity":
        activity_urn = base_urn
    elif resolve_canonical and (clean_input.startswith("http://") or clean_input.startswith("https://")):
        # Resolve real canonical activity URN from public page HTML
        activity_urn = resolve_canonical_activity_urn(clean_input)

    return PostEntity(
        entity_type=entity_type,
        entity_id=entity_id,
        urn=base_urn,
        activity_urn=activity_urn,
        original_url=clean_input,
    )
