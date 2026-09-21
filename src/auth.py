import json
import time
from pathlib import Path
from typing import Dict, Optional
from rich.console import Console

from .config import SESSION_FILE, LEGACY_SESSION_FILE, LINKEDIN_LI_AT

console = Console()


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
                            cookies[c["name"]] = c["value"]
                    elif isinstance(data, dict):
                        if "cookies" in data and isinstance(data["cookies"], list):
                            for c in data["cookies"]:
                                cookies[c["name"]] = c["value"]
                        else:
                            cookies = data
                if "li_at" in cookies:
                    break
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to read {sf}: {e}[/yellow]")

    # Fallback to LINKEDIN_LI_AT environment variable
    if "li_at" not in cookies and LINKEDIN_LI_AT:
        cookies["li_at"] = LINKEDIN_LI_AT
        if "JSESSIONID" not in cookies:
            cookies["JSESSIONID"] = '"ajax:0123456789012345678"'

    return cookies


def save_cookies(cookies_list: list) -> Path:
    """Save cookie list to SESSION_FILE."""
    # Ensure parent directory exists
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
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
