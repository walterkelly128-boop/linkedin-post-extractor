import time
import httpx
from typing import List, Dict, Any, Optional, Tuple
from rich.console import Console

from .models import (
    PostEntity, UserProfile, CommentItem, ReactionItem, ExtractionResult
)
from .config import (
    LINKEDIN_VOYAGER_BASE, DEFAULT_USER_AGENT, REQUEST_DELAY,
    HTTP_PROXY, HTTPS_PROXY
)
from .auth import get_stored_cookies

console = Console()


class LinkedInExtractor:
    """Extractor for LinkedIn post comments and reactions using Voyager API."""

    def __init__(self, cookies: Optional[Dict[str, str]] = None):
        self.cookies = cookies or get_stored_cookies()
        if not self.cookies or "li_at" not in self.cookies:
            console.print("[yellow]Warning: No valid `li_at` cookie found. Please run `python -m src.cli login` first.[/yellow]")

        self.session = self._create_session()

    def _create_session(self) -> httpx.Client:
        jsessionid = self.cookies.get("JSESSIONID", "").strip('"')
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/vnd.linkedin.normalized+json+2.1, application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "csrf-token": jsessionid,
            "x-restli-protocol-version": "2.0.0",
            "x-li-lang": "en_US",
            "x-li-page-instance": "urn:li:page:d_flagship3_feed;default",
        }
        
        proxies = {}
        if HTTP_PROXY:
            proxies["http://"] = HTTP_PROXY
        if HTTPS_PROXY:
            proxies["https://"] = HTTPS_PROXY

        return httpx.Client(
            headers=headers,
            cookies=self.cookies,
            proxies=proxies if proxies else None,
            timeout=30.0,
            follow_redirects=True,
        )

    def _parse_mini_profile(self, profile_data: Dict[str, Any]) -> UserProfile:
        """Extract standardized UserProfile from various LinkedIn member profile shapes."""
        first_name = profile_data.get("firstName", "")
        last_name = profile_data.get("lastName", "")
        name = f"{first_name} {last_name}".strip() or profile_data.get("name", "LinkedIn Member")
        
        headline = profile_data.get("occupation") or profile_data.get("headline") or ""
        public_id = profile_data.get("publicIdentifier") or profile_data.get("vanityName") or ""
        
        profile_url = f"https://www.linkedin.com/in/{public_id}/" if public_id else ""
        
        # Extract avatar url if available
        avatar_url = ""
        picture = profile_data.get("picture") or profile_data.get("profilePicture")
        if isinstance(picture, dict):
            # Voyager image format
            root_url = picture.get("rootUrl", "")
            artifacts = picture.get("artifacts", [])
            if root_url and artifacts:
                avatar_url = root_url + artifacts[-1].get("fileIdentifyingUrlPathSegment", "")
            elif "displayImageReference" in picture:
                avatar_url = picture.get("displayImageReference", {}).get("vectorImage", {}).get("rootUrl", "")

        return UserProfile(
            name=name,
            headline=headline,
            profile_url=profile_url,
            avatar_url=avatar_url,
            public_identifier=public_id,
        )

    def extract_reactions(
        self,
        post: PostEntity,
        limit: int = 100,
        reaction_type: str = "ALL"
    ) -> List[ReactionItem]:
        """
        Extract reactions from the post.
        reaction_type: 'ALL', 'LIKE', 'PRAISE', 'EMPATHY', 'APPRECIATION', 'INTEREST'
        """
        reactions: List[ReactionItem] = []
        start = 0
        count = min(100, limit) if limit > 0 else 100

        # Try with urn, fallback between ugcPost and activity if needed
        candidate_urns = [
            post.urn,
            f"urn:li:activity:{post.entity_id}" if post.entity_type == "ugcPost" else f"urn:li:ugcPost:{post.entity_id}",
        ]

        active_urn = candidate_urns[0]

        while True:
            url = f"{LINKEDIN_VOYAGER_BASE}/feed/reactions"
            params = {
                "count": count,
                "start": start,
                "entityUrn": active_urn,
                "reactionType": reaction_type,
            }

            try:
                resp = self.session.get(url, params=params)
                if resp.status_code == 404 or resp.status_code == 400:
                    # Switch to fallback URN if first attempt failed
                    if active_urn == candidate_urns[0] and len(candidate_urns) > 1:
                        active_urn = candidate_urns[1]
                        continue
                    break

                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                console.print(f"[red]Error fetching reactions: {e}[/red]")
                break

            elements = data.get("elements", [])
            if not elements:
                # Some versions put data inside 'data' or 'included'
                elements = [
                    item for item in data.get("included", [])
                    if "reactionType" in item or "reactionTypeV2" in item
                ]

            if not elements:
                break

            for el in elements:
                r_type = el.get("reactionType") or el.get("reactionTypeV2") or "LIKE"
                reactor_data = (
                    el.get("reactor", {}).get("miniProfile")
                    or el.get("reactor", {}).get("com.linkedin.voyager.feed.MemberActor", {}).get("miniProfile")
                    or el.get("reactor", {})
                )
                user = self._parse_mini_profile(reactor_data)
                
                reactions.append(
                    ReactionItem(
                        reaction_type=r_type,
                        reactor=user,
                        created_time_ms=el.get("createdAt"),
                        post_urn=active_urn,
                    )
                )

                if limit > 0 and len(reactions) >= limit:
                    return reactions[:limit]

            start += len(elements)
            time.sleep(REQUEST_DELAY)

        return reactions

    def extract_comments(
        self,
        post: PostEntity,
        limit: int = 100,
        sort_order: str = "RELEVANT"
    ) -> List[CommentItem]:
        """
        Extract comments from the post.
        sort_order: 'RELEVANT' or 'RECENT'
        """
        comments: List[CommentItem] = []
        start = 0
        count = min(50, limit) if limit > 0 else 50

        candidate_urns = [
            post.urn,
            f"urn:li:activity:{post.entity_id}" if post.entity_type == "ugcPost" else f"urn:li:ugcPost:{post.entity_id}",
        ]
        active_urn = candidate_urns[0]

        while True:
            url = f"{LINKEDIN_VOYAGER_BASE}/feed/comments"
            params = {
                "count": count,
                "start": start,
                "sortOrder": sort_order,
                "updateId": active_urn,
            }

            try:
                resp = self.session.get(url, params=params)
                if resp.status_code in (400, 404):
                    if active_urn == candidate_urns[0] and len(candidate_urns) > 1:
                        active_urn = candidate_urns[1]
                        continue
                    break

                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                console.print(f"[red]Error fetching comments: {e}[/red]")
                break

            elements = data.get("elements", [])
            if not elements:
                elements = [
                    item for item in data.get("included", [])
                    if "comment" in item or "commentV2" in item or "commentUrn" in item
                ]

            if not elements:
                break

            for el in elements:
                # Author
                commenter_data = (
                    el.get("commenter", {}).get("miniProfile")
                    or el.get("commenter", {}).get("com.linkedin.voyager.feed.MemberActor", {}).get("miniProfile")
                    or el.get("commenter", {})
                )
                author = self._parse_mini_profile(commenter_data)

                # Text
                comment_field = el.get("comment") or el.get("commentV2") or {}
                if isinstance(comment_field, dict):
                    text = comment_field.get("text", "")
                    if not text and "values" in comment_field:
                        text = "".join(v.get("value", "") for v in comment_field.get("values", []))
                else:
                    text = str(comment_field)

                # Social stats
                social_counts = el.get("socialDetail", {}).get("totalSocialActivityCounts", {})
                likes_count = social_counts.get("numLikes", 0)
                replies_count = social_counts.get("numComments", 0)

                comment_id = el.get("urn", "") or el.get("entityUrn", "")
                created_desc = el.get("created", {}).get("timeDescription", "")
                created_time_ms = el.get("created", {}).get("time")

                comments.append(
                    CommentItem(
                        comment_id=comment_id,
                        author=author,
                        text=text.strip(),
                        created_at_desc=created_desc,
                        created_time_ms=created_time_ms,
                        likes_count=likes_count,
                        replies_count=replies_count,
                        is_reply=False,
                        post_urn=active_urn,
                    )
                )

                if limit > 0 and len(comments) >= limit:
                    return comments[:limit]

            start += len(elements)
            time.sleep(REQUEST_DELAY)

        return comments

    def extract_all(
        self,
        post: PostEntity,
        include_comments: bool = True,
        include_reactions: bool = True,
        comments_limit: int = 100,
        reactions_limit: int = 100,
    ) -> ExtractionResult:
        """Extract both comments and reactions for a given post."""
        comments = []
        reactions = []

        if include_comments:
            console.print(f"[cyan]Fetching comments for {post.urn}...[/cyan]")
            comments = self.extract_comments(post, limit=comments_limit)
            console.print(f"[green][OK] Found {len(comments)} comments[/green]")

        if include_reactions:
            console.print(f"[cyan]Fetching reactions for {post.urn}...[/cyan]")
            reactions = self.extract_reactions(post, limit=reactions_limit)
            console.print(f"[green][OK] Found {len(reactions)} reactions[/green]")

        return ExtractionResult(
            post=post,
            total_comments=len(comments),
            total_reactions=len(reactions),
            comments=comments,
            reactions=reactions,
        )
