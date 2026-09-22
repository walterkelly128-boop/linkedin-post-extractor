import re
from typing import List, Tuple

from .models import PostEntity, ReactionItem, CommentItem, UserProfile, ExtractionResult
from .extractor import clean_linkedin_profile_url


async def _profile_from_link(link, card_text=""):
    href = await link.get_attribute("href") or ""
    if "/in/" not in href:
        return None
    url, vanity = clean_linkedin_profile_url(href)
    if not vanity:
        return None
    try:
        name = (await link.inner_text()).strip()
    except Exception:
        name = ""
    lines = [x.strip() for x in card_text.splitlines() if x.strip()]
    if not name and lines:
        name = lines[0]
    if not name:
        name = vanity.replace("-", " ").title()
    headline = ""
    for line in lines:
        if line != name:
            headline = line
            break
    return UserProfile(
        name=name,
        headline=headline,
        profile_url=url,
        public_identifier=vanity,
    )


async def _reaction_links(page, seen, post, limit):
    results = []
    dialogs = page.locator('div[role="dialog"]')
    root = dialogs.last if await dialogs.count() else page
    links = root.locator('a[href*="/in/"], a[href*="linkedin.com/in/"]')
    count = await links.count()
    for i in range(count):
        try:
            link = links.nth(i)
            parent = link.locator("xpath=..")
            try:
                card_text = await parent.inner_text()
            except Exception:
                card_text = ""
            profile = await _profile_from_link(link, card_text)
            if not profile or profile.profile_url in seen:
                continue
            seen.add(profile.profile_url)
            results.append(
                ReactionItem(
                    reaction_type="LIKE",
                    reactor=profile,
                    post_urn=post.activity_urn or post.urn,
                )
            )
            if limit > 0 and len(results) >= limit:
                break
        except Exception:
            continue
    return results



async def _click_most_recent_comments(page):
    """Switch LinkedIn's comment sort to Most recent and wait for the list to refresh."""
    # LinkedIn has changed the DOM for this control several times. Try the
    # visible sort control first, then the menu item. We intentionally match
    # only comment-sort labels, never the generic "React" control.
    sort_labels = [
        "Most relevant",
        "Most Relevant",
        "Relevant",
        "Sort by",
    ]
    clicked_sort = False

    for label in sort_labels:
        candidates = page.get_by_text(label, exact=True)
        try:
            count = await candidates.count()
            for i in range(min(count, 10)):
                item = candidates.nth(i)
                if not await item.is_visible():
                    continue
                try:
                    await item.click(timeout=2500)
                    clicked_sort = True
                    await page.wait_for_timeout(700)
                    break
                except Exception:
                    continue
            if clicked_sort:
                break
        except Exception:
            continue

    # Some versions expose the control through an aria-label instead of text.
    if not clicked_sort:
        candidates = page.locator(
            'button[aria-label*="relevant" i], '
            'button[aria-label*="sort" i], '
            '[role="button"][aria-label*="relevant" i]'
        )
        try:
            for i in range(min(await candidates.count(), 20)):
                item = candidates.nth(i)
                if await item.is_visible():
                    await item.click(timeout=2500)
                    clicked_sort = True
                    await page.wait_for_timeout(700)
                    break
        except Exception:
            pass

    if not clicked_sort:
        return False

    # After opening the sort menu, click the actual "Most recent" option.
    recent_labels = ["Most recent", "Most Recent", "Recent"]
    for label in recent_labels:
        candidates = page.get_by_text(label, exact=True)
        try:
            count = await candidates.count()
            for i in range(min(count, 10)):
                item = candidates.nth(i)
                if not await item.is_visible():
                    continue
                try:
                    await item.click(timeout=3000)
                    await page.wait_for_timeout(1800)
                    return True
                except Exception:
                    continue
        except Exception:
            continue

    # Fallback for menuitem/button variants.
    candidates = page.locator(
        '[role="menuitem"], [role="option"], button, '
        '[data-view-name*="sort" i]'
    )
    try:
        for i in range(min(await candidates.count(), 100)):
            item = candidates.nth(i)
            if not await item.is_visible():
                continue
            txt = (await item.inner_text()).strip()
            aria = (await item.get_attribute("aria-label") or "").strip()
            if txt.lower() == "most recent" or aria.lower() == "most recent":
                await item.click(timeout=3000)
                await page.wait_for_timeout(1800)
                return True
    except Exception:
        pass

    return False

def _comment_cards(page):
    selectors = [
        "article.comments-comment-item",
        "div.comments-comment-item",
        "li.comments-comment-item",
        "[data-test-id='comments-comment-item']",
        "[data-view-name='comment']",
        "article[data-id*='comment']",
        "div[data-id*='comment']",
        "li[data-id*='comment']",
        ".comments-comment-entity",
        ".comments-comments-list__comment-item",
    ]
    return selectors


async def _extract_comments_from_page(page, post, seen, limit):
    comments = []
    cards = None
    for selector in _comment_cards(page):
        loc = page.locator(selector)
        if await loc.count():
            cards = loc
            break
    if cards is None:
        return comments

    count = await cards.count()
    for i in range(count):
        try:
            card = cards.nth(i)
            links = card.locator('a[href*="/in/"], a[href*="linkedin.com/in/"]')
            if not await links.count():
                continue
            card_text = await card.inner_text()
            profile = await _profile_from_link(links.first, card_text)
            if not profile or profile.profile_url in seen:
                continue
            seen.add(profile.profile_url)

            text = ""
            text_selectors = [
                ".comments-comment-item__main-content",
                ".update-components-text",
                ".feed-shared-inline-show-more-text",
                "[data-test-id='comment-text']",
            ]
            for selector in text_selectors:
                node = card.locator(selector)
                if await node.count():
                    text = (await node.first.inner_text()).strip()
                    if text:
                        break

            if not text:
                lines = [x.strip() for x in card_text.splitlines() if x.strip()]
                if profile.name in lines:
                    try:
                        idx = lines.index(profile.name)
                        text = lines[idx + 1] if idx + 1 < len(lines) else ""
                    except ValueError:
                        text = ""

            comments.append(
                CommentItem(
                    comment_id=f"chrome:{profile.public_identifier}:{i}",
                    author=profile,
                    text=text,
                    created_at_desc="",
                    created_time_ms=None,
                    likes_count=0,
                    replies_count=0,
                    is_reply=False,
                    post_urn=post.activity_urn or post.urn,
                )
            )
            if limit > 0 and len(comments) >= limit:
                break
        except Exception:
            continue
    return comments


async def _resolve_cdp_websocket_url(cdp_url: str, timeout_seconds: float = 15) -> str:
    """Resolve Chrome's exact browser WebSocket URL from /json/version."""
    import asyncio
    import json
    import socket
    from urllib.parse import urlparse

    raw = (cdp_url or "").strip().rstrip("/")
    if raw.startswith("ws://") or raw.startswith("wss://"):
        if "/devtools/browser/" in raw:
            return raw
        raise RuntimeError(
            "CHROME_CDP_URL 使用了不完整的 WebSocket 地址；"
            "请使用 http://host.docker.internal:9222，让程序自动发现 browser UUID。"
        )
    if not raw:
        raw = "http://host.docker.internal:9222"

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RuntimeError(f"无效的 CHROME_CDP_URL: {cdp_url}")

    version_url = raw + "/json/version"

    def fetch():
        from urllib.request import Request, urlopen
        req = Request(
            version_url,
            headers={"Host": f"127.0.0.1:{parsed.port or 80}"},
        )
        with urlopen(req, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8")

    try:
        payload = await asyncio.to_thread(fetch)
    except Exception as exc:
        raise RuntimeError(
            f"无法从 Docker 读取 Windows Chrome CDP: {version_url}；{exc}"
        ) from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Chrome /json/version 返回的内容不是有效 JSON。") from exc

    ws_url = str(data.get("webSocketDebuggerUrl") or "").strip()
    if not ws_url:
        raise RuntimeError("Chrome /json/version 未返回 webSocketDebuggerUrl。")

    reported = urlparse(ws_url)
    if reported.hostname in ("127.0.0.1", "localhost", "::1", "host.docker.internal"):
        # Chrome rejects a WebSocket request whose Host header is a hostname.
        # Playwright sends Host: host.docker.internal here, so use the numeric
        # Docker Desktop host IP instead.
        try:
            connect_host = socket.gethostbyname(parsed.hostname)
        except OSError as exc:
            raise RuntimeError(
                f"无法解析 Docker 主机地址 {parsed.hostname}；{exc}"
            ) from exc
        netloc = connect_host
        if reported.port:
            netloc += f":{reported.port}"
        ws_url = reported._replace(netloc=netloc).geturl()
    return ws_url


async def extract_with_local_chrome(
    post: PostEntity,
    cdp_url: str,
    include_comments: bool = True,
    include_reactions: bool = True,
    comments_limit: int = 50,
    reactions_limit: int = 100,
) -> Tuple[ExtractionResult, str]:
    """
    Connect to an already logged-in local Chrome through Chrome DevTools Protocol.
    Uses Playwright Async API because FastAPI/Uvicorn runs an asyncio event loop.
    Chrome owns the LinkedIn session; no li_at is copied into the app.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed in the container.") from exc

    async with async_playwright() as p:
        resolved_cdp_url = await _resolve_cdp_websocket_url(cdp_url, timeout_seconds=15)
        # Connect to the resolved WebSocket endpoint. Chrome 153 requires
        # a loopback Host header, but Playwright's CDP HTTP discovery rewrites
        # the WebSocket URL to 127.0.0.1 when that header is supplied. Resolve
        # the endpoint ourselves and pass the Host header on the WS handshake.
        browser = await p.chromium.connect_over_cdp(
            resolved_cdp_url,
            headers={"Host": "127.0.0.1:9222"},
            timeout=30000,
        )
        contexts = browser.contexts
        if not contexts:
            raise RuntimeError("Chrome CDP 已连接，但没有可用的浏览器上下文。")

        context = contexts[0]
        pages = context.pages
        page = None
        for candidate in pages:
            try:
                if "linkedin.com" in candidate.url:
                    page = candidate
                    break
            except Exception:
                pass

        if page is None:
            page = await context.new_page()

        await page.goto(post.original_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        current_url = page.url
        if "/login" in current_url or "/authwall" in current_url:
            raise RuntimeError(
                "本地 Chrome 已连接，但 LinkedIn 当前页面处于登录/安全墙页面。"
                "请确认该 Chrome 窗口本身可以正常打开 LinkedIn 帖子。"
            )

        reactions: List[ReactionItem] = []
        comments: List[CommentItem] = []

        if include_reactions:
            # IMPORTANT: never click LinkedIn's normal "React" toggle.
            # It can change the logged-in user's reaction. We only open the
            # reactor list through an explicit reaction-count element.
            count_candidates = page.locator(
                'button[aria-label*="reactions" i], '
                'a[aria-label*="reactions" i], '
                '[data-test-id*="social-counts" i], '
                '.social-details-social-counts__reactions'
            )
            clicked = False
            count = await count_candidates.count()
            for i in range(min(count, 20)):
                try:
                    item = count_candidates.nth(i)
                    if not await item.is_visible():
                        continue
                    text_value = (await item.inner_text()).strip()
                    aria = (await item.get_attribute("aria-label") or "").strip()
                    # Require a numeric reaction count. Do not click "React".
                    if re.search(r"\b\d+\s+reactions?\b", text_value, re.I) or re.search(
                        r"\b\d+\s+reactions?\b", aria, re.I
                    ):
                        await item.click(timeout=4000)
                        clicked = True
                        break
                except Exception:
                    continue

            if clicked:
                await page.wait_for_timeout(1800)
                seen = set()
                stagnant = 0
                last = 0

                for _ in range(35):
                    reactions.extend(await _reaction_links(page, seen, post, reactions_limit))
                    if reactions_limit > 0 and len(reactions) >= reactions_limit:
                        break

                    dialogs = page.locator('div[role="dialog"]')
                    if await dialogs.count():
                        dialog = dialogs.last
                        try:
                            await dialog.evaluate(
                                """el => {
                                  const nodes=[el,...el.querySelectorAll('*')];
                                  const target=nodes.find(n=>n.scrollHeight>n.clientHeight+100);
                                  if(target) target.scrollTop=target.scrollHeight;
                                  else el.scrollTop=el.scrollHeight;
                                }"""
                            )
                        except Exception:
                            await page.mouse.wheel(0, 1800)
                    else:
                        break

                    await page.wait_for_timeout(800)
                    if len(reactions) == last:
                        stagnant += 1
                    else:
                        stagnant = 0
                        last = len(reactions)
                    if stagnant >= 4:
                        break

                try:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(500)
                except Exception:
                    pass

        if include_comments:
            # Reload the post so reaction modal state cannot interfere.
            await page.goto(post.original_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)

            # Expand the comments section if LinkedIn exposes a comment count
            # button. Never click a reaction/React control here.
            comment_buttons = page.locator(
                'button[aria-label*="comment" i], '
                'button[data-test-id*="comment" i], '
                'button[data-view-name*="comment" i]'
            )
            bc = await comment_buttons.count()
            for i in range(min(bc, 20)):
                try:
                    item = comment_buttons.nth(i)
                    if not await item.is_visible():
                        continue
                    txt = (await item.inner_text()).strip()
                    aria = (await item.get_attribute("aria-label") or "").strip()
                    if re.search(r"\b\d*\s*comments?\b", txt, re.I) or re.search(
                        r"\b\d*\s*comments?\b", aria, re.I
                    ):
                        await item.click(timeout=4000)
                        await page.wait_for_timeout(1200)
                        break
                except Exception:
                    continue

            # IMPORTANT: LinkedIn's default "Most relevant" view can hide
            # comments that are lower in the ranking. Switch to "Most recent"
            # before collecting anything, then allow the list to refresh.
            switched = await _click_most_recent_comments(page)
            if switched:
                await page.wait_for_timeout(1500)

            # Scroll the comments list repeatedly. LinkedIn virtualizes this
            # list, so a single DOM query only sees the currently rendered cards.
            stagnant_rounds = 0
            previous_count = 0
            for _ in range(35):
                current_seen = {c.author.profile_url for c in comments if c.author.profile_url}
                new_comments = await _extract_comments_from_page(
                    page, post, current_seen, comments_limit
                )
                existing_urls = {c.author.profile_url for c in comments if c.author.profile_url}
                for comment in new_comments:
                    if comment.author.profile_url and comment.author.profile_url in existing_urls:
                        continue
                    comments.append(comment)
                    if comment.author.profile_url:
                        existing_urls.add(comment.author.profile_url)

                if comments_limit > 0 and len(comments) >= comments_limit:
                    break

                if len(comments) == previous_count:
                    stagnant_rounds += 1
                else:
                    stagnant_rounds = 0
                    previous_count = len(comments)

                await page.mouse.wheel(0, 1400)
                await page.wait_for_timeout(1000)

                if stagnant_rounds >= 6:
                    break

        result = ExtractionResult(
            post=post,
            total_comments=len(comments),
            total_reactions=len(reactions),
            public_likes_count=0,
            notes=(
                f"✅ 已使用本地 Chrome 已登录会话直接提取。"
                f"点赞者 {len(reactions)} 人，评论者 {len(comments)} 人。"
            ),
            comments=comments[:comments_limit] if comments_limit > 0 else comments,
            reactions=reactions[:reactions_limit] if reactions_limit > 0 else reactions,
        )
        return result, page.url
