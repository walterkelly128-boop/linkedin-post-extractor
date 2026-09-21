import json
import time
from pathlib import Path
from typing import Dict, Optional, Tuple
import httpx
from rich.console import Console

from .config import SESSION_FILE, LEGACY_SESSION_FILE, LINKEDIN_LI_AT, DEFAULT_USER_AGENT

console = Console()


def parse_cookie_input(raw: str) -> Dict[str, str]:
    """
    Parse any cookie format provided by the user:
    - Raw li_at string (e.g. 'AQEDAWJ4...')
    - Full HTTP Cookie header (e.g. 'bcookie=...; JSESSIONID="ajax:..."; li_at=AQED...')
    - String with 'Cookie: ...' prefix
    - JSON array of cookie objects (from Cookie-Editor / EditThisCookie)
    - JSON dictionary of cookie key-values
    """
    if not raw or not isinstance(raw, str):
        return {}
    raw = raw.strip()
    if not raw:
        return {}

    # Strip leading "Cookie:" or "cookie:"
    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1].strip()

    # Case 1: JSON format
    if raw.startswith("{") or raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return {c["name"]: c["value"] for c in data if isinstance(c, dict) and "name" in c and "value" in c}
            elif isinstance(data, dict):
                if "cookies" in data and isinstance(data["cookies"], list):
                    return {c["name"]: c["value"] for c in data["cookies"] if isinstance(c, dict) and "name" in c and "value" in c}
                return {k: str(v) for k, v in data.items()}
        except Exception:
            pass

    # Case 2: key=value pairs separated by semicolon or newline
    if ";" in raw or "\n" in raw or "=" in raw:
        delimiter = "\n" if ("\n" in raw and ";" not in raw) else ";"
        result: Dict[str, str] = {}
        for part in raw.split(delimiter):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k:
                    result[k] = v
        if result and ("li_at" in result or len(result) > 1):
            return result

    # Case 3: Raw single token assumed to be li_at
    return {"li_at": raw}


def verify_linkedin_session(cookies: Optional[Dict[str, str]] = None) -> Tuple[bool, str, Optional[str]]:
    """
    Verify if the current LinkedIn session cookie (li_at) is actually valid by making a live probe.
    Returns: (is_valid: bool, status_message: str, user_name: Optional[str])
    """
    if cookies is None:
        cookies = get_stored_cookies()

    li_at = cookies.get("li_at", "").strip()
    if not li_at:
        return False, "未配置 Cookie", None

    raw_jsessionid = cookies.get("JSESSIONID", "").strip()
    # Normalize jsessionid: csrf-token header takes ajax:... (without quotes), cookie takes "ajax:..."
    csrf_token = raw_jsessionid.strip('"')
    if not csrf_token:
        csrf_token = "ajax:0123456789012345678"

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/vnd.linkedin.normalized+json+2.1, application/json",
        "csrf-token": csrf_token,
        "x-restli-protocol-version": "2.0.0",
    }
    cookie_dict = dict(cookies)
    cookie_dict["li_at"] = li_at
    if raw_jsessionid:
        cookie_dict["JSESSIONID"] = raw_jsessionid if raw_jsessionid.startswith('"') else f'"{raw_jsessionid}"'

    try:
        r = httpx.get("https://www.linkedin.com/voyager/api/me", cookies=cookie_dict, headers=headers, follow_redirects=False, timeout=8.0)
        if r.status_code == 200:
            data = r.json()
            first = data.get("firstName", "")
            last = data.get("lastName", "")
            name = f"{first} {last}".strip() or "LinkedIn Member"
            return True, f"有效 (已登录: {name})", name
        elif r.status_code in (301, 302, 303, 307):
            set_cookie = r.headers.get("set-cookie", "")
            if "delete me" in set_cookie:
                msg = (
                    "Cookie 已失效 (领英返回 delete me)。常见原因：\n"
                    "1. 在浏览器复制 Cookie 后点击了“退出登录 (Sign Out)”导致服务端作废；\n"
                    "2. 缺少与 li_at 配套的 JSESSIONID，领英触发了 CSRF 安全防御拦截。\n"
                    "建议：在浏览器保持登录状态，直接复制完整的 Cookie 标头或同时提供配套的 JSESSIONID。"
                )
                return False, msg, None
            return False, f"未通过认证 (HTTP {r.status_code} 重定向至登录页)", None
        elif r.status_code in (401, 403):
            return False, f"认证失败 (HTTP {r.status_code} 无权限，请检查账号是否受限)", None
        else:
            return False, f"领英响应异常 (HTTP {r.status_code})", None
    except Exception as e:
        return False, f"连接领英验证失败: {e}", None


def get_stored_cookies() -> Dict[str, str]:
    """
    Retrieve LinkedIn authentication cookies from session.json or environment.
    Returns a dict with cookie names and values.
    """
    cookies: Dict[str, str] = {}

    # Check potential session file locations (only if they are actual files, not directories)
    candidate_files = [SESSION_FILE, LEGACY_SESSION_FILE]

    for sf in candidate_files:
        if sf.exists() and sf.is_file():
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for c in data:
                            if isinstance(c, dict) and "name" in c and "value" in c:
                                cookies[c["name"]] = c["value"]
                    elif isinstance(data, dict):
                        if "cookies" in data and isinstance(data["cookies"], list):
                            for c in data["cookies"]:
                                if isinstance(c, dict) and "name" in c and "value" in c:
                                    cookies[c["name"]] = c["value"]
                        else:
                            cookies = {k: str(v) for k, v in data.items()}
                if "li_at" in cookies:
                    break
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to read {sf}: {e}[/yellow]")

    # Fallback to LINKEDIN_LI_AT environment variable
    if "li_at" not in cookies and LINKEDIN_LI_AT:
        parsed_env = parse_cookie_input(LINKEDIN_LI_AT)
        cookies.update(parsed_env)

    return cookies


def save_cookies(cookies_input) -> Path:
    """Save cookie list or dict or raw string to SESSION_FILE."""
    # Ensure parent directory exists
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    if isinstance(cookies_input, str):
        parsed = parse_cookie_input(cookies_input)
        cookies_list = [{"name": k, "value": v} for k, v in parsed.items()]
    elif isinstance(cookies_input, dict):
        cookies_list = [{"name": k, "value": str(v)} for k, v in cookies_input.items()]
    elif isinstance(cookies_input, list):
        cookies_list = cookies_input
    else:
        raise ValueError("Unsupported cookies format")

    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies_list, f, indent=2)
    return SESSION_FILE


def login_interactive(timeout_seconds: int = 180) -> bool:
    """
    Launch a visible browser for the user to log in to LinkedIn once.
    Once logged in (detected by the presence of `li_at` cookie and /feed redirection),
    automatically save the cookies into session.json.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        console.print("[red]Error: playwright is not installed. Run: pip install playwright && playwright install chromium[/red]")
        return False

    console.print("[cyan]Opening browser for LinkedIn login...[/cyan]")
    console.print("[dim]Please complete the login in the opened browser window. Waiting up to 3 minutes...[/dim]")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        start_time = time.time()
        logged_in = False

        while time.time() - start_time < timeout_seconds:
            current_cookies = context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in current_cookies}

            if "li_at" in cookie_dict:
                logged_in = True
                save_cookies(current_cookies)
                console.print(f"[bold green][OK] Login successful! Credentials securely saved to {SESSION_FILE}[/bold green]")
                break

            time.sleep(1.5)

        browser.close()

        if not logged_in:
            console.print("[bold red][X] Login timed out or cancelled. Please try again.[/bold red]")
            return False

        return True
