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
            selectors = [
                'button[aria-label*="reaction" i]',
                'button[aria-label*="reactions" i]',
                '.social-details-social-counts__reactions',
                'button.social-details-social-counts__reactions',
                '[data-test-id*="reaction"]',
            ]
            clicked = False
            for selector in selectors:
                loc = page.locator(selector)
                count = await loc.count()
                for i in range(min(count, 8)):
                    try:
                        item = loc.nth(i)
                        if await item.is_visible():
                            await item.click(timeout=4000)
                            clicked = True
                            break
                    except Exception:
                        continue
                if clicked:
                    break

            if not clicked:
                # Prefer the numeric reaction-count control. Clicking the
                # generic "React" button only changes the current user's
                # reaction and does not open the list of people.
                count_candidates = page.locator("button, a, span, div").filter(
                    has_text=re.compile(r"\b\d+\s+reactions?\b", re.I)
                )
                count = await count_candidates.count()
                for i in range(min(count, 20)):
                    try:
                        item = count_candidates.nth(i)
                        if await item.is_visible():
                            await item.click(timeout=4000)
                            clicked = True
                            break
                    except Exception:
                        continue

            if not clicked:
                candidates = page.locator("button, a").filter(
                    has_text=re.compile(r"\breactions?\b", re.I)
                )
                count = await candidates.count()
                for i in range(min(count, 10)):
                    try:
                        item = candidates.nth(i)
                        label = (await item.get_attribute("aria-label") or "").lower()
                        text_value = (await item.inner_text()).strip().lower()
                        if "react" == text_value or label == "react":
                            continue
                        if await item.is_visible():
                            await item.click(timeout=4000)
                            clicked = True
                            break
                    except Exception:
                        continue

            if not clicked:
                raise RuntimeError(
                    f"已连接本地 Chrome，但在 LinkedIn 帖子页面没有找到“Reactions/点赞”入口。"
                    f"当前页面：{page.url}"
                )

            await page.wait_for_timeout(1800)

            dialogs = page.locator('div[role="dialog"]')
            if await dialogs.count():
                try:
                    await dialogs.last.wait_for(state="visible", timeout=5000)
                except Exception:
                    pass

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
                    await page.mouse.wheel(0, 1800)

                await page.wait_for_timeout(800)
                if len(reactions) == last:
                    stagnant += 1
                else:
                    stagnant = 0
                    last = len(reactions)
                if stagnant >= 4:
                    break

            if not reactions:
                visible_links = page.locator('a[href*="/in/"], a[href*="linkedin.com/in/"]')
                visible_count = await visible_links.count()
                for i in range(visible_count):
                    try:
                        link = visible_links.nth(i)
                        if not await link.is_visible():
                            continue
                        parent = link.locator("xpath=..")
                        card_text = await parent.inner_text()
                        profile = await _profile_from_link(link, card_text)
                        if not profile or profile.profile_url in seen:
                            continue
                        seen.add(profile.profile_url)
                        reactions.append(ReactionItem(reaction_type="LIKE", reactor=profile, post_urn=post.activity_urn or post.urn))
                        if reactions_limit > 0 and len(reactions) >= reactions_limit:
                            break
                    except Exception:
                        continue

            try:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(500)
            except Exception:
                pass

        if include_comments:
            await page.goto(post.original_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)
            for _ in range(12):
                current_seen = {c.author.profile_url for c in comments}
                new_comments = await _extract_comments_from_page(
                    page, post, current_seen, comments_limit
                )
                existing_urls = {c.author.profile_url for c in comments}
                for comment in new_comments:
                    if comment.author.profile_url not in existing_urls:
                        comments.append(comment)
                        existing_urls.add(comment.author.profile_url)
                if comments_limit > 0 and len(comments) >= comments_limit:
                    break
                await page.mouse.wheel(0, 1800)
                await page.wait_for_timeout(900)

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
