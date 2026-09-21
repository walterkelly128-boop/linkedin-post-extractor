"""
Core extractor: connects to local Chrome via CDP, intercepts LinkedIn's
internal /voyager/api/ responses to extract comments and reactions.

How it works:
  1. Connect to Chrome running with --remote-debugging-port=9222
  2. Open a new tab and register response interceptors
  3. Navigate to the LinkedIn post page
  4. Scroll the page to trigger pagination API calls
  5. Aggregate all intercepted JSON into structured records
"""

from __future__ import annotations

import json
import time
import logging
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Response

from .models import CommentRecord, ReactionRecord, ExtractResult
from .parser import validate_and_parse

logger = logging.getLogger(__name__)

# Default CDP endpoint (local Chrome)
DEFAULT_CDP_URL = "http://localhost:9222"

# How long to wait (ms) for the page to settle after navigation / scroll
PAGE_SETTLE_MS = 3000
SCROLL_SETTLE_MS = 2000


# ---------------------------------------------------------------------------
# Response classifier helpers
# ---------------------------------------------------------------------------

def _is_comments_response(url: str) -> bool:
    """Return True if this URL looks like a LinkedIn comments API call."""
    return "/voyager/api/feed/comments" in url or (
        "/voyager/api/graphql" in url and "comment" in url.lower()
    )


def _is_reactions_response(url: str) -> bool:
    """Return True if this URL looks like a LinkedIn reactions API call."""
    return "/voyager/api/feed/reactions" in url or (
        "/voyager/api/reactions" in url
    ) or (
        "/voyager/api/graphql" in url and "reaction" in url.lower()
    )


# ---------------------------------------------------------------------------
# JSON parsers for voyager REST responses
# ---------------------------------------------------------------------------

def _safe_str(obj: object, *keys: str) -> Optional[str]:
    """Drill into a nested dict safely, returning None if any key is missing."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return str(obj) if obj is not None else None


def _parse_profile_url(nav_url: Optional[str]) -> Optional[str]:
    """
    LinkedIn reactor/commenter profile URLs look like:
      https://www.linkedin.com/in/username?...  (already canonical)
      urn:li:member:12345  (URN format — convert to search link)
    """
    if not nav_url:
        return None
    if nav_url.startswith("https://"):
        # Strip query params for cleaner URL
        parsed = urlparse(nav_url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return nav_url


def _parse_comments_rest(data: dict, post_url: str, parent_id: Optional[str] = None) -> list[CommentRecord]:
    """Parse a voyager REST comments response into CommentRecord list."""
    records: list[CommentRecord] = []

    elements = data.get("elements", [])
    if not elements and "data" in data:
        # GraphQL wrapper
        elements = data.get("data", {}).get("commentsV2", {}).get("elements", [])

    for el in elements:
        # Author info — REST format
        commenter = el.get("commenter", {})
        actor = el.get("actor", commenter)

        name = (
            _safe_str(actor, "name", "text")
            or _safe_str(commenter, "com.linkedin.voyager.feed.MemberActor", "miniProfile", "firstName")
            or _safe_str(el, "authorInfo", "author", "name", "text")
        )
        headline = (
            _safe_str(actor, "description", "text")
            or _safe_str(commenter, "com.linkedin.voyager.feed.MemberActor", "miniProfile", "occupation")
        )
        profile_url = _parse_profile_url(
            _safe_str(actor, "navigationUrl")
            or _safe_str(actor, "url")
        )
        avatar = (
            _safe_str(actor, "image", "attributes", 0, "detailData",
                      "nonEntityProfilePicture", "vectorImage", "rootUrl")
            or _safe_str(actor, "image", "rootUrl")
        )

        # Comment content
        commentary = el.get("commentary") or el.get("comment", {})
        text = (
            _safe_str(commentary, "text", "text")
            or _safe_str(commentary, "text")
            or _safe_str(el, "message", "values", 0, "value")
        )

        comment_id = el.get("entityUrn", "").split(":")[-1] or None
        created_at = el.get("createdAt")
        time_str = None
        if created_at:
            try:
                from datetime import datetime, timezone
                time_str = datetime.fromtimestamp(
                    created_at / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S UTC")
            except Exception:
                pass

        stats = el.get("socialDetail", {}) or {}
        total_reactions = (
            stats.get("totalSocialActivityCounts", {}).get("numLikes", 0)
            or stats.get("reactionSummaries", [{}])[0].get("count", 0)
            if stats.get("reactionSummaries") else 0
        )
        total_replies = stats.get("comments", 0)

        record = CommentRecord(
            comment_id=comment_id,
            comment_type="reply" if parent_id else "comment",
            parent_comment_id=parent_id,
            author_name=name,
            author_headline=headline,
            author_profile_url=profile_url,
            author_avatar=avatar,
            comment_text=text,
            comment_time_ms=created_at,
            comment_time_str=time_str,
            is_edited=el.get("edited", False),
            is_pinned=el.get("pinned", False),
            total_reactions=total_reactions,
            total_replies=total_replies,
            post_url=post_url,
        )
        records.append(record)

        # Parse threaded replies if present
        replies_data = el.get("comments", {})
        if replies_data and isinstance(replies_data, dict):
            records.extend(_parse_comments_rest(replies_data, post_url, parent_id=comment_id))

    return records


def _parse_reactions_rest(data: dict, post_url: str) -> list[ReactionRecord]:
    """Parse a voyager REST reactions response into ReactionRecord list."""
    records: list[ReactionRecord] = []

    elements = data.get("elements", [])
    if not elements and "data" in data:
        elements = data.get("data", {}).get("reactionsByEntityAndType", {}).get("elements", [])

    for el in elements:
        actor = el.get("actor", el.get("reactor", {}))
        reaction_type = el.get("reactionType") or el.get("type")

        name = (
            _safe_str(actor, "name", "text")
            or _safe_str(actor, "firstName", "text")
        )
        headline = _safe_str(actor, "description", "text")
        profile_url = _parse_profile_url(
            _safe_str(actor, "navigationUrl")
            or _safe_str(actor, "url")
        )
        avatar = (
            _safe_str(actor, "image", "attributes", 0, "detailData",
                      "nonEntityProfilePicture", "vectorImage", "rootUrl")
            or _safe_str(actor, "image", "rootUrl")
            or _safe_str(actor, "profilePicture", "displayImage~", "elements", 0, "identifiers", 0, "identifier")
        )

        record = ReactionRecord(
            reaction_type=reaction_type,
            author_name=name,
            author_headline=headline,
            author_profile_url=profile_url,
            author_avatar=avatar,
            post_url=post_url,
        )
        records.append(record)

    return records


# ---------------------------------------------------------------------------
# Main extractor class
# ---------------------------------------------------------------------------

class LinkedInExtractor:
    """
    Connects to a locally running Chrome (--remote-debugging-port=9222)
    and extracts comments + reactions from a LinkedIn post.
    """

    def __init__(self, cdp_url: str = DEFAULT_CDP_URL, scroll_count: int = 5):
        self.cdp_url = cdp_url
        self.scroll_count = scroll_count
        self._comments: list[CommentRecord] = []
        self._reactions: list[ReactionRecord] = []
        self._errors: list[str] = []

    # ------------------------------------------------------------------
    # Response handler (called for every intercepted network response)
    # ------------------------------------------------------------------

    def _handle_response(self, response: Response, post_url: str) -> None:
        url = response.url
        if "/voyager/api/" not in url:
            return
        if response.status != 200:
            return
        try:
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            body = response.json()
        except Exception:
            return

        if _is_comments_response(url):
            logger.debug("Intercepted comments response: %s", url)
            try:
                records = _parse_comments_rest(body, post_url)
                if records:
                    logger.info("  → %d comment(s) parsed", len(records))
                    self._comments.extend(records)
            except Exception as exc:
                logger.warning("Failed to parse comments from %s: %s", url, exc)
                self._errors.append(f"Comment parse error: {exc}")

        elif _is_reactions_response(url):
            logger.debug("Intercepted reactions response: %s", url)
            try:
                records = _parse_reactions_rest(body, post_url)
                if records:
                    logger.info("  → %d reaction(s) parsed", len(records))
                    self._reactions.extend(records)
            except Exception as exc:
                logger.warning("Failed to parse reactions from %s: %s", url, exc)
                self._errors.append(f"Reaction parse error: {exc}")

    # ------------------------------------------------------------------
    # Page interaction helpers
    # ------------------------------------------------------------------

    def _scroll_to_load_more(self, page: Page) -> None:
        """Scroll the page to trigger lazy-loaded content."""
        for i in range(self.scroll_count):
            page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
            page.wait_for_timeout(SCROLL_SETTLE_MS)
            logger.debug("Scroll iteration %d/%d", i + 1, self.scroll_count)

            # Click "Load more comments" button if visible
            for btn_text in ["Load more comments", "Show more replies", "Show replies"]:
                try:
                    btn = page.get_by_text(btn_text, exact=False).first
                    if btn.is_visible(timeout=500):
                        btn.click()
                        page.wait_for_timeout(1500)
                        logger.debug("Clicked '%s' button", btn_text)
                except Exception:
                    pass

    def _open_reactions_dialog(self, page: Page) -> None:
        """Try to open the reactions list modal to trigger the reactions API call."""
        try:
            # Look for reaction count button (shows "123 reactions" or emoji + count)
            reaction_btn = page.locator(
                "button.social-counts-reactions, "
                "button[aria-label*='reaction'], "
                ".social-details-social-counts__reactions-count"
            ).first
            if reaction_btn.is_visible(timeout=2000):
                reaction_btn.click()
                page.wait_for_timeout(2000)
                logger.debug("Opened reactions dialog")
                # Scroll within the reactions modal to load more
                modal = page.locator(".artdeco-modal__content").first
                if modal.is_visible(timeout=1000):
                    for _ in range(3):
                        modal.evaluate("el => el.scrollBy(0, 300)")
                        page.wait_for_timeout(800)
                # Close the modal
                close_btn = page.locator("button[aria-label='Dismiss']").first
                if close_btn.is_visible(timeout=1000):
                    close_btn.click()
        except Exception as exc:
            logger.debug("Could not open reactions dialog: %s", exc)

    # ------------------------------------------------------------------
    # Main extraction method
    # ------------------------------------------------------------------

    def extract(
        self,
        url_or_id: str,
        include_comments: bool = True,
        include_reactions: bool = True,
    ) -> ExtractResult:
        """
        Extract comments and/or reactions from a LinkedIn post.

        Args:
            url_or_id: LinkedIn post URL or activity ID.
            include_comments: Whether to extract comments.
            include_reactions: Whether to extract reactions.

        Returns:
            ExtractResult with all found comments and reactions.
        """
        self._comments = []
        self._reactions = []
        self._errors = []

        activity_id, post_url = validate_and_parse(url_or_id)
        logger.info("Extracting post: %s (ID: %s)", post_url, activity_id)

        result = ExtractResult(post_url=post_url, activity_id=activity_id)

        with sync_playwright() as pw:
            # Connect to the already-running Chrome
            logger.info("Connecting to Chrome at %s ...", self.cdp_url)
            try:
                browser: Browser = pw.chromium.connect_over_cdp(self.cdp_url)
            except Exception as exc:
                msg = (
                    f"Cannot connect to Chrome at {self.cdp_url}.\n"
                    "Make sure Chrome is running with:\n"
                    "  chrome.exe --remote-debugging-port=9222\n"
                    f"Details: {exc}"
                )
                logger.error(msg)
                result.errors.append(msg)
                return result

            # Use the default browser context (inherits the user's login session)
            context: BrowserContext = browser.contexts[0] if browser.contexts else browser.new_context()
            page: Page = context.new_page()

            # Register network response interceptor
            page.on(
                "response",
                lambda resp: self._handle_response(resp, post_url),
            )

            try:
                logger.info("Navigating to post page ...")
                page.goto(post_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(PAGE_SETTLE_MS)

                # Verify we're on LinkedIn (not a login redirect)
                current_url = page.url
                if "linkedin.com/login" in current_url or "linkedin.com/checkpoint" in current_url:
                    msg = (
                        "Chrome redirected to LinkedIn login page.\n"
                        "Please make sure you are logged into LinkedIn in the Chrome window "
                        "that was launched with --remote-debugging-port=9222."
                    )
                    logger.error(msg)
                    result.errors.append(msg)
                    page.close()
                    return result

                logger.info("Page loaded. Starting scroll to load comments ...")

                # Trigger reactions API by opening the reactions dialog first
                if include_reactions:
                    self._open_reactions_dialog(page)

                # Scroll to load more comments
                if include_comments:
                    self._scroll_to_load_more(page)

                # Final wait for any pending requests
                page.wait_for_timeout(PAGE_SETTLE_MS)

            except Exception as exc:
                msg = f"Page interaction error: {exc}"
                logger.error(msg)
                self._errors.append(msg)
            finally:
                page.close()

        # Deduplicate by comment_id / profile_url
        seen_comment_ids: set[str] = set()
        unique_comments: list[CommentRecord] = []
        for c in self._comments:
            key = c.comment_id or f"{c.author_profile_url}::{c.comment_text}"
            if key not in seen_comment_ids:
                seen_comment_ids.add(key)
                unique_comments.append(c)

        seen_reaction_keys: set[str] = set()
        unique_reactions: list[ReactionRecord] = []
        for r in self._reactions:
            key = r.author_profile_url or f"{r.author_name}::{r.reaction_type}"
            if key not in seen_reaction_keys:
                seen_reaction_keys.add(key)
                unique_reactions.append(r)

        result.comments = unique_comments if include_comments else []
        result.reactions = unique_reactions if include_reactions else []
        result.errors = self._errors
        result.finalize()

        logger.info(
            "Done. Comments: %d, Reactions: %d, Errors: %d",
            result.total_comments,
            result.total_reactions,
            len(result.errors),
        )
        return result
