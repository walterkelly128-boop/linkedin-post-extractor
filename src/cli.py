import sys
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Ensure UTF-8 output on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from .parser import parse_post_url
from .auth import login_interactive, get_stored_cookies, verify_linkedin_session
from .extractor import LinkedInExtractor
from .exporter import export_to_csv, export_to_json, export_to_excel
from .config import SESSION_FILE

app = typer.Typer(
    name="linkedin-post-extractor",
    help="Extract comments, reactions, and author profiles from LinkedIn posts.",
    add_completion=False,
)
console = Console(safe_box=True)


@app.command()
def login(timeout: int = typer.Option(180, "--timeout", "-t", help="Timeout in seconds for login")):
    """
    Launch a local browser window to sign in to LinkedIn once.
    Your session cookies will be saved securely in session.json.
    """
    console.print(Panel.fit(
        "[bold cyan]LinkedIn Extractor - Interactive Login[/bold cyan]\n"
        "A browser window will open. Please log into your LinkedIn account.\n"
        "Once logged in, credentials will be saved locally for subsequent extractions.",
        border_style="cyan",
    ))
    success = login_interactive(timeout_seconds=timeout)
    if not success:
        sys.exit(1)


@app.command()
def status():
    """Check the status of stored LinkedIn session cookies."""
    cookies = get_stored_cookies()
    if not cookies or "li_at" not in cookies:
        console.print("[bold red][!] Not logged in.[/bold red] Run: [cyan]python main.py login[/cyan] or set LINKEDIN_LI_AT in .env")
        return

    source = "session.json" if SESSION_FILE.exists() else ".env (LINKEDIN_LI_AT)"
    console.print(f"Verifying session via {source}...")
    is_valid, msg, user_name = verify_linkedin_session(cookies)
    if is_valid:
        console.print(f"[bold green][OK] Session verified and active![/bold green] (Logged in as: [bold cyan]{user_name}[/bold cyan])")
        console.print(f"[dim]li_at preview: {cookies['li_at'][:10]}...[/dim]")
    else:
        console.print(f"[bold red][!] Session check failed:[/bold red] {msg}")
        console.print("[yellow]Hint: LinkedIn rejected the li_at cookie. Please log in to linkedin.com in your browser (keep the tab open), copy the fresh li_at from F12 -> Application -> Cookies, and update it.[/yellow]")



@app.command()
def web(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host address to bind"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to listen on"),
):
    """
    Launch the interactive Web UI Dashboard (ideal for Docker Desktop).
    """
    import uvicorn
    console.print(Panel.fit(
        f"[bold cyan]LinkedIn Extractor - Web Console[/bold cyan]\n"
        f"Server starting at: [bold underline green]http://{host}:{port}[/bold underline green]\n"
        f"Open the URL in your browser to start extracting with interactive Web UI!",
        border_style="green",
    ))
    uvicorn.run("src.web:app", host=host, port=port, reload=False)


@app.command()
def scrape(
    url: str = typer.Argument(..., help="LinkedIn post URL, activity link, or post ID"),
    comments: bool = typer.Option(True, "--comments/--no-comments", help="Extract comments"),
    reactions: bool = typer.Option(True, "--reactions/--no-reactions", help="Extract reactions"),
    limit_comments: int = typer.Option(100, "--limit-comments", "-lc", help="Max comments to fetch (0 for all)"),
    limit_reactions: int = typer.Option(100, "--limit-reactions", "-lr", help="Max reactions to fetch (0 for all)"),
    output_format: str = typer.Option("all", "--format", "-f", help="Output format: csv, json, excel, all"),
):
    """
    Extract comments and reactions from a specified LinkedIn post.
    """
    try:
        post = parse_post_url(url)
    except ValueError as e:
        console.print(f"[bold red]Input Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    console.print(Panel.fit(
        f"[bold cyan]Target Post Detected[/bold cyan]\n"
        f"- Type: [yellow]{post.entity_type}[/yellow]\n"
        f"- ID:   [green]{post.entity_id}[/green]\n"
        f"- URN:  [bold]{post.urn}[/bold]",
        border_style="blue",
    ))

    cookies = get_stored_cookies()
    if not cookies or "li_at" not in cookies:
        console.print(
            "[bold yellow]Notice:[/bold yellow] No active session found.\n"
            "Please run [cyan]python main.py login[/cyan] to authenticate first, or add LINKEDIN_LI_AT to .env."
        )
        raise typer.Exit(code=1)

    extractor = LinkedInExtractor(cookies=cookies)

    with console.status("[bold green]Extracting data from LinkedIn...[/bold green]"):
        result = extractor.extract_all(
            post=post,
            include_comments=comments,
            include_reactions=reactions,
            comments_limit=limit_comments,
            reactions_limit=limit_reactions,
        )

    # Display Comments Preview Table
    if result.comments:
        c_table = Table(title=f"Comments Preview ({len(result.comments)} Total)", border_style="cyan")
        c_table.add_column("Author", style="bold green")
        c_table.add_column("Headline", style="dim", max_width=35)
        c_table.add_column("Comment Text", max_width=45)
        c_table.add_column("Profile URL", style="blue")

        for c in result.comments[:5]:
            c_table.add_row(
                c.author.name,
                c.author.headline or "N/A",
                c.text.replace("\n", " ")[:60] + ("..." if len(c.text) > 60 else ""),
                c.author.profile_url or "N/A",
            )
        console.print(c_table)

    # Display Reactions Preview Table
    if result.reactions:
        r_table = Table(title=f"Reactions Preview ({len(result.reactions)} Total)", border_style="magenta")
        r_table.add_column("Reactor Name", style="bold magenta")
        r_table.add_column("Reaction Type", style="yellow")
        r_table.add_column("Headline", style="dim", max_width=35)
        r_table.add_column("Profile URL", style="blue")

        for r in result.reactions[:5]:
            r_table.add_row(
                r.reactor.name,
                r.reaction_type,
                r.reactor.headline or "N/A",
                r.reactor.profile_url or "N/A",
            )
        console.print(r_table)

    # Exporting
    console.print("\n[bold]Exporting results:[/bold]")
    saved_files = []

    if output_format in ("json", "all"):
        j_path = export_to_json(result)
        saved_files.append(str(j_path))

    if output_format in ("csv", "all"):
        c_paths = export_to_csv(result)
        saved_files.extend([str(p) for p in c_paths])

    if output_format in ("excel", "xlsx", "all"):
        x_path = export_to_excel(result)
        saved_files.append(str(x_path))

    for f in saved_files:
        console.print(f" [green][OK][/green] Saved to: [bold underline]{f}[/bold underline]")

    console.print("\n[bold green]Extraction finished successfully![/bold green]")


def main():
    app()


if __name__ == "__main__":
    main()
