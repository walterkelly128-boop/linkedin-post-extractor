import re
from typing import List, Tuple

from .models import PostEntity, ReactionItem, CommentItem, UserProfile, ExtractionResult
from .extractor import clean_linkedin_profile_url


def _profile_from_link(link, card_text=""):
    href = link.get_attribute("href") or ""
    if "/in/" not in href:
        return None
    url, vanity = clean_linkedin_profile_url(href)
    if not vanity:
        return None
    name = (link.inner_text() or "").strip()
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


def _reaction_links(page, seen, post, limit):
    results = []
    dialogs = page.locator('div[role="dialog"]')
    root = dialogs.last if dialogs.count() else page
    links = root.locator('a[href*="/in/"]')
    for i in range(links.count()):
        try:
            link = links.nth(i)
            profile = _profile_from_link(link, link.locator("xpath=..").inner_text())
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
    ]
    for selector in selectors:
        loc = page.locator(selector)
        if loc.count():
            return loc
    return None


def _extract_comments_from_page(page, post, seen, limit):
    comments = []
    cards = _comment_cards(page)
    if cards is None:
        return comments

    for i in range(cards.count()):
        try:
            card = cards.nth(i)
            links = card.locator('a[href*="/in/"]')
            if not links.count():
                continue
            profile = _profile_from_link(links.first, card.inner_text())
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
                if node.count():
                    text = (node.first.inner_text() or "").strip()
                    if text:
                        break

            if not text:
                lines = [x.strip() for x in card.inner_text().splitlines() if x.strip()]
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


def extract_with_local_chrome(
    post: PostEntity,
    cdp_url: str,
    include_comments: bool = True,
    include_reactions: bool = True,
    comments_limit: int = 50,
    reactions_limit: int = 100,
) -> Tuple[ExtractionResult, str]:
    """
    Connect to an already logged-in local Chrome through Chrome DevTools Protocol.
    The Chrome process owns the LinkedIn session; no li_at is copied into the app.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed in the container.") from exc

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url, timeout=15000)
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
            page = context.new_page()

        page.goto(post.original_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        if "/login" in page.url or "/authwall" in page.url:
            raise RuntimeError("本地 Chrome 没有保持 LinkedIn 登录状态，请先在该 Chrome 窗口登录 LinkedIn。")

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
                for i in range(min(loc.count(), 8)):
                    try:
                        item = loc.nth(i)
                        if item.is_visible():
                            item.click(timeout=4000)
                            clicked = True
                            break
                    except Exception:
                        continue
                if clicked:
                    break

            if not clicked:
                candidates = page.locator("button, a").filter(has_text=re.compile(r"\\breactions?\\b", re.I))
                for i in range(min(candidates.count(), 10)):
                    try:
                        item = candidates.nth(i)
                        if item.is_visible():
                            item.click(timeout=4000)
                            clicked = True
                            break
                    except Exception:
                        continue

            if clicked:
                page.wait_for_timeout(1200)
                seen = set()
                stagnant = 0
                last = 0
                for _ in range(35):
                    reactions.extend(_reaction_links(page, seen, post, reactions_limit))
                    if reactions_limit > 0 and len(reactions) >= reactions_limit:
                        break
                    dialogs = page.locator('div[role="dialog"]')
                    if dialogs.count():
                        dialog = dialogs.last
                        try:
                            dialog.evaluate(
                                """el => {
                                  const nodes=[el,...el.querySelectorAll('*')];
                                  const target=nodes.find(n=>n.scrollHeight>n.clientHeight+100);
                                  if(target) target.scrollTop=target.scrollHeight;
                                  else el.scrollTop=el.scrollHeight;
                                }"""
                            )
                        except Exception:
                            page.mouse.wheel(0, 1800)
                    else:
                        page.mouse.wheel(0, 1800)
                    page.wait_for_timeout(800)
                    if len(reactions) == last:
                        stagnant += 1
                    else:
                        stagnant = 0
                        last = len(reactions)
                    if stagnant >= 4:
                        break

                # Close reaction dialog so comments are accessible.
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                except Exception:
                    pass

        if include_comments:
            page.goto(post.original_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            # Scroll the post into the comments area and allow lazy loading.
            for _ in range(12):
                comments = _extract_comments_from_page(
                    page, post, {c.author.profile_url for c in comments}, comments_limit
                )
                if comments_limit > 0 and len(comments) >= comments_limit:
                    break
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(900)

        result = ExtractionResult(
            post=post,
            total_comments=len(comments),
            total_reactions=len(reactions),
            public_likes_count=0,
            notes="✅ 已使用本地 Chrome 已登录会话直接提取点赞者和评论者主页链接。",
            comments=comments[:comments_limit] if comments_limit > 0 else comments,
            reactions=reactions[:reactions_limit] if reactions_limit > 0 else reactions,
        )
        return result, page.url
