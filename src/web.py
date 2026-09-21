import os
import traceback
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel

from .parser import parse_post_url
from .extractor import LinkedInExtractor
from .auth import get_stored_cookies, save_cookies
from .exporter import export_to_excel, export_to_csv, export_to_json
from .config import BASE_DIR, OUTPUT_DIR, SESSION_FILE
from .models import ExtractionResult

app = FastAPI(
    title="LinkedIn Post Comments & Reactions Extractor",
    description="Docker Desktop Web Console for LinkedIn social engagement extraction.",
    version="1.0.0",
)

TEMPLATES_DIR = BASE_DIR / "templates"
INDEX_FILE = TEMPLATES_DIR / "index.html"


# Global exception handler so frontend always gets clean JSON instead of raw HTML 500
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    status_code = exc.status_code if isinstance(exc, HTTPException) else 500
    detail = exc.detail if isinstance(exc, HTTPException) else f"{type(exc).__name__}: {str(exc)}"
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "error_type": type(exc).__name__},
    )


class CookiePayload(BaseModel):
    li_at: str


class ExtractPayload(BaseModel):
    url: str
    li_at: Optional[str] = None
    include_comments: bool = True
    include_reactions: bool = True
    limit_comments: int = 50
    limit_reactions: int = 100


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    if not INDEX_FILE.exists():
        return HTMLResponse("<h3>Dashboard template not found in /templates/index.html</h3>", status_code=404)
    return FileResponse(INDEX_FILE, media_type="text/html")


@app.get("/api/status")
async def get_status():
    cookies = get_stored_cookies()
    has_li_at = bool(cookies.get("li_at"))
    li_at_preview = (cookies.get("li_at", "")[:8] + "...") if has_li_at else ""
    return {
        "authenticated": has_li_at,
        "li_at_preview": li_at_preview,
        "source": "session.json" if SESSION_FILE.exists() else "environment",
    }


@app.post("/api/cookie")
async def update_cookie(payload: CookiePayload):
    cookie_val = payload.li_at.strip()
    if not cookie_val:
        raise HTTPException(status_code=400, detail="Cookie cannot be empty.")

    # Save to session.json safely
    data = [
        {"name": "li_at", "value": cookie_val},
        {"name": "JSESSIONID", "value": '"ajax:0123456789012345678"'},
    ]
    try:
        save_cookies(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to persist cookie: {e}")

    return {"success": True, "message": "Cookie saved successfully."}


@app.post("/api/extract", response_model=ExtractionResult)
async def extract_data(payload: ExtractPayload):
    url_input = payload.url.strip()
    if not url_input:
        raise HTTPException(status_code=400, detail="Please provide a LinkedIn post URL.")

    try:
        post = parse_post_url(url_input)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cookies = get_stored_cookies()
    
    # If user provided li_at directly in the payload, use it!
    if payload.li_at and payload.li_at.strip():
        cookies["li_at"] = payload.li_at.strip()
        if "JSESSIONID" not in cookies:
            cookies["JSESSIONID"] = '"ajax:0123456789012345678"'
            
    if not cookies or "li_at" not in cookies or not cookies["li_at"]:
        raise HTTPException(
            status_code=401,
            detail="No LinkedIn session cookie found. Please enter your `li_at` cookie in 'Configure Cookie' first."
        )

    extractor = LinkedInExtractor(cookies=cookies)
    try:
        result = extractor.extract_all(
            post=post,
            include_comments=payload.include_comments,
            include_reactions=payload.include_reactions,
            comments_limit=payload.limit_comments,
            reactions_limit=payload.limit_reactions,
        )
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"LinkedIn API extraction error: {err}")

    # Generate output files automatically so they are ready for download
    try:
        export_to_excel(result)
        export_to_csv(result)
        export_to_json(result)
    except Exception as err:
        print(f"Warning: Failed to export files: {err}")

    return result


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Requested file does not exist.")

    media_type = "application/octet-stream"
    if filename.endswith(".xlsx"):
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif filename.endswith(".csv"):
        media_type = "text/csv"
    elif filename.endswith(".json"):
        media_type = "application/json"

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
    )
