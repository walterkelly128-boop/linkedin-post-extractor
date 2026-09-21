import re
from urllib.parse import urlparse, unquote
from .models import PostEntity


def parse_post_url(url_or_id: str) -> PostEntity:
    """
    Parse any LinkedIn post URL, URN string, or numeric ID into a normalized PostEntity.
    
    Supported examples:
    - https://www.linkedin.com/posts/holliszhang_keyoung-hpmc-the-professional-choice-for-ugcPost-7463758057899147265-mOJK
    - https://www.linkedin.com/posts/username_title-activity-7302346926123798528-dMnz
    - https://www.linkedin.com/feed/update/urn:li:activity:7302346926123798528/
    - https://www.linkedin.com/feed/update/urn:li:ugcPost:7463758057899147265/
    - urn:li:activity:7302346926123798528
    - urn:li:ugcPost:7463758057899147265
    - 7463758057899147265
    """
    clean_input = url_or_id.strip()
    unquoted = unquote(clean_input)

    # 1. Check for explicit urn:li:(ugcPost|activity|share):<id>
    urn_match = re.search(r"urn:li:(ugcPost|activity|share):(\d+)", unquoted)
    if urn_match:
        entity_type = urn_match.group(1)
        entity_id = urn_match.group(2)
        return PostEntity(
            entity_type=entity_type,
            entity_id=entity_id,
            urn=f"urn:li:{entity_type}:{entity_id}",
            original_url=clean_input,
        )

    # 2. Check for slug patterns: ugcPost-<id> or activity-<id>
    slug_match = re.search(r"(ugcPost|activity)-(\d+)", unquoted)
    if slug_match:
        entity_type = slug_match.group(1)
        entity_id = slug_match.group(2)
        return PostEntity(
            entity_type=entity_type,
            entity_id=entity_id,
            urn=f"urn:li:{entity_type}:{entity_id}",
            original_url=clean_input,
        )

    # 3. Check for pure digits
    digit_match = re.match(r"^(\d{15,20})$", clean_input)
    if digit_match:
        entity_id = digit_match.group(1)
        # Default to activity if only numeric ID is given
        return PostEntity(
            entity_type="activity",
            entity_id=entity_id,
            urn=f"urn:li:activity:{entity_id}",
            original_url=clean_input,
        )

    raise ValueError(
        f"Unable to parse LinkedIn post entity from input: '{clean_input}'.\n"
        f"Please provide a valid LinkedIn post link containing ugcPost/activity ID or URN."
    )
