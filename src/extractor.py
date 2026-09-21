import time
import re
import json
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


from urllib.parse import urlparse

def clean_linkedin_profile_url(raw_url: str) -> Tuple[str, str]:
    """Normalize any LinkedIn profile URL and extract vanity identifier."""
    if not raw_url:
        return "", ""
    parsed = urlparse(raw_url.strip())
    path = parsed.path
    m = re.search(r'/in/([^/?#]+)', path)
    if m:
        vanity = m.group(1).rstrip('/')
        return f"https://www.linkedin.com/in/{vanity}", vanity
    clean_url = raw_url.split("?")[0]
    return clean_url, ""


class LinkedInExtractor:
    """Extractor for LinkedIn post comments and reactions using Voyager API with HTML fallback."""

    def __init__(self, cookies: Optional[Dict[str, str]] = None):
        self.cookies = cookies or get_stored_cookies()
        if not self.cookies or "li_at" not in self.cookies:
            console.print("[yellow]Warning: No valid `li_at` cookie found. Public fallback mode will be used.[/yellow]")

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
        
        client_kwargs = {
            "headers": headers,
            "cookies": self.cookies,
            "timeout": 30.0,
            "follow_redirects": False,
        }
        active_proxy = HTTPS_PROXY or HTTP_PROXY
        if active_proxy:
            try:
                return httpx.Client(proxy=active_proxy, **client_kwargs)
            except TypeError:
                return httpx.Client(proxies=active_proxy, **client_kwargs)

        return httpx.Client(**client_kwargs)

    def _get_candidate_urns(self, post: PostEntity) -> List[str]:
        """Get prioritized candidate URNs to try for comments and reactions."""
        urns: List[str] = []
        if post.activity_urn and post.activity_urn not in urns:
            urns.append(post.activity_urn)
        if post.urn not in urns:
            urns.append(post.urn)
        
        alt_urn = f"urn:li:activity:{post.entity_id}" if post.entity_type == "ugcPost" else f"urn:li:ugcPost:{post.entity_id}"
        if alt_urn not in urns:
            urns.append(alt_urn)

        return urns

    def _parse_mini_profile(self, profile_data: Dict[str, Any]) -> UserProfile:
        """Extract standardized UserProfile from various LinkedIn member profile shapes."""
        first_name = profile_data.get("firstName", "")
        last_name = profile_data.get("lastName", "")
        name = f"{first_name} {last_name}".strip() or profile_data.get("name", "LinkedIn Member")
        
        headline = profile_data.get("occupation") or profile_data.get("headline") or ""
        public_id = profile_data.get("publicIdentifier") or profile_data.get("vanityName") or ""
        
        profile_url = f"https://www.linkedin.com/in/{public_id}/" if public_id else ""
        
        avatar_url = ""
        picture = profile_data.get("picture") or profile_data.get("profilePicture")
        if isinstance(picture, dict):
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

    def extract_reactions_from_html(self, post: PostEntity, html: Optional[str] = None) -> Tuple[List[ReactionItem], int]:
        """
        Fallback parser that extracts public reactions stats from the HTML page.
        Returns (reactions_list, public_likes_count).
        """
        if not html:
            try:
                resp = httpx.get(
                    post.original_url,
                    headers={
                        "User-Agent": DEFAULT_USER_AGENT,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    timeout=15.0,
                    follow_redirects=True,
                )
                html = resp.text
            except Exception as e:
                console.print(f"[yellow]Failed to fetch HTML for public reactions: {e}[/yellow]")
                return [], 0

        public_likes = 0
        matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
        for raw in matches:
            try:
                data = json.loads(raw.strip())
                stats = data.get("interactionStatistic", [])
                if isinstance(stats, dict):
                    stats = [stats]
                for s in stats:
                    if "LikeAction" in s.get("interactionType", ""):
                        public_likes = max(public_likes, s.get("userInteractionCount", 0))
            except Exception:
                pass

        if public_likes == 0:
            m = re.search(r'data-test-id="social-actions__reaction-count"[^>]*>\s*(\d+)', html)
            if m:
                public_likes = int(m.group(1))

        reactions = []
        if public_likes > 0:
            reactions.append(
                ReactionItem(
                    reaction_type="LIKE",
                    reactor=UserProfile(
                        name=f"Public Reactions ({public_likes} likes)",
                        headline="[Notice] Detailed reactor list requires login with `li_at` cookie. Total likes detected on public post.",
                        profile_url=post.original_url,
                        public_identifier="",
                    ),
                    post_urn=post.activity_urn or post.urn,
                )
            )

        return reactions, public_likes

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

        candidate_urns = self._get_candidate_urns(post)
        active_urn = candidate_urns[0]

        has_auth = bool(self.cookies and self.cookies.get("li_at"))

        if has_auth:
            while True:
                url = f"{LINKEDIN_VOYAGER_BASE}/feed/reactions"
                params = {
                    "count": count,
                    "start": start,
                    "entityUrn": active_urn,
                }
                if reaction_type and reaction_type.upper() != "ALL":
                    params["reactionType"] = reaction_type.upper()

                try:
                    resp = self.session.get(url, params=params)
                    if resp.status_code in (301, 302, 303, 307, 401, 403):
                        console.print(f"[yellow]Note (HTTP {resp.status_code}): LinkedIn session unauthenticated for reactions list.[/yellow]")
                        break
                    if resp.status_code in (400, 404):
                        curr_idx = candidate_urns.index(active_urn)
                        if curr_idx + 1 < len(candidate_urns):
                            active_urn = candidate_urns[curr_idx + 1]
                            continue
                        break

                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    console.print(f"[red]Error fetching reactions via API: {e}[/red]")
                    break

                elements = data.get("elements", [])
                if not elements:
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

        # Fallback to public HTML reactions if API returned 0
        if not reactions:
            console.print("[cyan]Checking public page for reactions...[/cyan]")
            html_reactions, _ = self.extract_reactions_from_html(post)
            reactions = html_reactions

        return reactions

    def extract_comments_from_html(self, post: PostEntity) -> List[CommentItem]:
        """
        Fallback parser that extracts public comments from JSON-LD schema & HTML DOM.
        Captures commenter name, full profile URL (https://www.linkedin.com/in/...),
        avatar, and comment text.
        """
        if not post.original_url.startswith("http"):
            return []

        html_comments: List[CommentItem] = []
        try:
            resp = httpx.get(
                post.original_url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=15.0,
                follow_redirects=True,
            )
            html = resp.text

            # 1. Map author names to profile URLs and avatars from HTML DOM
            author_map: Dict[str, Dict[str, str]] = {}
            author_links = re.findall(
                r'<a[^>]+href="([^"]*(?:linkedin\.com/in/[^"]+|/in/[^"]+))"[^>]*>(.*?)</a>',
                html, re.DOTALL
            )
            for href, inner in author_links:
                is_comment = (
                    "comment_actor" in href
                    or "comment__author" in inner
                    or "comment__author" in href
                    or "comment" in href
                )
                clean_name = re.sub(r'<[^>]+>', '', inner).strip()
                if clean_name and not clean_name.lower().startswith("view profile"):
                    profile_url, vanity = clean_linkedin_profile_url(href)
                    author_entry = {
                        "name": clean_name,
                        "profile_url": profile_url,
                        "public_identifier": vanity,
                        "avatar_url": "",
                    }
                    if is_comment or clean_name.lower() not in author_map:
                        author_map[clean_name.lower()] = author_entry

            avatar_links = re.findall(
                r'<a[^>]+href="([^"]*(?:linkedin\.com/in/[^"]+|/in/[^"]+))"[^>]*>.*?data-delayed-url="([^"]+)"',
                html, re.DOTALL
            )
            for href, avatar_url in avatar_links:
                _, vanity = clean_linkedin_profile_url(href)
                for k, v in author_map.items():
                    if v.get("public_identifier") == vanity:
                        v["avatar_url"] = avatar_url

            dom_comment_urns = re.findall(r'data-semaphore-content-urn="([^"]+)"', html)
            valid_comment_urns = [u for u in dom_comment_urns if "comment" in u]

            # 2. Parse comments from JSON-LD
            matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
            for raw in matches:
                try:
                    data = json.loads(raw.strip())
                    items = data.get("comment", [])
                    if isinstance(items, dict):
                        items = [items]
                    for idx, c in enumerate(items):
                        creator = c.get("creator", {})
                        name = creator.get("name", "LinkedIn Member")
                        text = c.get("text", "")
                        date_pub = c.get("datePublished", "")
                        likes_cnt = c.get("interactionStatistic", {}).get("userInteractionCount", 0)

                        author_info = author_map.get(name.lower())
                        if not author_info:
                            if len(author_map) == 1:
                                author_info = list(author_map.values())[0]
                            else:
                                for k, v in author_map.items():
                                    if name.lower() in k or k in name.lower():
                                        author_info = v
                                        break

                        profile_url = author_info["profile_url"] if author_info else ""
                        avatar_url = author_info.get("avatar_url", "") if author_info else ""
                        public_id = author_info.get("public_identifier", "") if author_info else ""

                        author = UserProfile(
                            name=name,
                            headline="",
                            profile_url=profile_url,
                            avatar_url=avatar_url,
                            public_identifier=public_id,
                        )

                        comment_urn = (
                            valid_comment_urns[idx] if idx < len(valid_comment_urns)
                            else f"public_comment_{idx + 1}"
                        )

                        html_comments.append(
                            CommentItem(
                                comment_id=comment_urn,
                                author=author,
                                text=text.strip(),
                                created_at_desc=date_pub,
                                likes_count=likes_cnt,
                                replies_count=0,
                                is_reply=False,
                                post_urn=post.activity_urn or post.urn,
                            )
                        )
                except Exception:
                    pass
        except Exception as e:
            console.print(f"[yellow]Public HTML fallback note: {e}[/yellow]")

        return html_comments


    def extract_comments(
        self,
        post: PostEntity,
        limit: int = 100,
        sort_order: str = "RELEVANT"
    ) -> List[CommentItem]:
        """
        Extract comments from the post via Voyager API, with HTML fallback.
        """
        comments: List[CommentItem] = []
        start = 0
        count = min(50, limit) if limit > 0 else 50

        candidate_urns = self._get_candidate_urns(post)
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
                if resp.status_code in (301, 302, 303, 307, 401, 403):
                    console.print(f"[yellow]Note (HTTP {resp.status_code}): LinkedIn session unauthenticated, checking public page...[/yellow]")
                    break
                if resp.status_code in (400, 404):
                    curr_idx = candidate_urns.index(active_urn)
                    if curr_idx + 1 < len(candidate_urns):
                        active_urn = candidate_urns[curr_idx + 1]
                        continue
                    break

                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                console.print(f"[red]Error fetching comments via API: {e}[/red]")
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
                commenter_data = (
                    el.get("commenter", {}).get("miniProfile")
                    or el.get("commenter", {}).get("com.linkedin.voyager.feed.MemberActor", {}).get("miniProfile")
                    or el.get("commenter", {})
                )
                author = self._parse_mini_profile(commenter_data)

                comment_field = el.get("comment") or el.get("commentV2") or {}
                if isinstance(comment_field, dict):
                    text = comment_field.get("text", "")
                    if not text and "values" in comment_field:
                        text = "".join(v.get("value", "") for v in comment_field.get("values", []))
                else:
                    text = str(comment_field)

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

        # If API returned 0 comments, try public HTML fallback!
        if not comments:
            console.print("[cyan]Trying public HTML fallback for comments...[/cyan]")
            comments = self.extract_comments_from_html(post)

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
            target_urn = post.activity_urn or post.urn
            console.print(f"[cyan]Fetching comments for {target_urn}...[/cyan]")
            comments = self.extract_comments(post, limit=comments_limit)
            console.print(f"[green][OK] Found {len(comments)} comments[/green]")

        if include_reactions:
            target_urn = post.activity_urn or post.urn
            console.print(f"[cyan]Fetching reactions for {target_urn}...[/cyan]")
            reactions = self.extract_reactions(post, limit=reactions_limit)
            console.print(f"[green][OK] Found {len(reactions)} reactions[/green]")

        # Detect if reactions came from public aggregate fallback
        is_public_reaction = any("Public Reactions" in r.reactor.name for r in reactions)
        notes = None
        public_likes = 0
        if is_public_reaction:
            for r in reactions:
                m = re.search(r'\((\d+)\s+likes\)', r.reactor.name)
                if m:
                    public_likes = int(m.group(1))
            notes = (
                f"Public Post Stats: {public_likes} likes found. "
                "Notice: LinkedIn only displays individual reactor profile links to logged-in users. Configure your `li_at` cookie to scrape the full reactor profiles list."
            )
        elif not reactions and include_reactions:
            notes = "No reactions found. If this post has reactions, configure your `li_at` cookie to access them."

        return ExtractionResult(
            post=post,
            total_comments=len(comments),
            total_reactions=len(reactions),
            public_likes_count=public_likes,
            notes=notes,
            comments=comments,
            reactions=reactions,
        )

