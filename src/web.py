import os
import traceback
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel

from .parser import parse_post_url
from .extractor import LinkedInExtractor
from .auth import get_stored_cookies, save_cookies, verify_linkedin_session, parse_cookie_input
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
    cookie_input: Optional[str] = None
    li_at: Optional[str] = None
    jsessionid: Optional[str] = None


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
    has_jsessionid = bool(cookies.get("JSESSIONID"))
    is_valid, status_msg, user_name = verify_linkedin_session(cookies) if has_li_at else (False, "未配置 Cookie", None)
    return {
        "configured": has_li_at,
        "has_jsessionid": has_jsessionid,
        "authenticated": is_valid,
        "status_message": status_msg,
        "user_name": user_name,
        "li_at_preview": li_at_preview,
        "source": "session.json" if SESSION_FILE.exists() else "environment",
    }


@app.post("/api/cookie")
async def update_cookie(payload: CookiePayload):
    raw_input = (payload.cookie_input or payload.li_at or "").strip()
    if not raw_input and not payload.jsessionid:
        raise HTTPException(status_code=400, detail="Cookie 输入不能为空。")

    cookies_dict = parse_cookie_input(raw_input) if raw_input else {}
    if payload.jsessionid and payload.jsessionid.strip():
        cookies_dict["JSESSIONID"] = payload.jsessionid.strip()

    if not cookies_dict.get("li_at"):
        # If user supplied only jsessionid or invalid format
        stored = get_stored_cookies()
        if "li_at" in stored:
            stored.update(cookies_dict)
            cookies_dict = stored
        else:
            raise HTTPException(status_code=400, detail="未能识别到 li_at Cookie。请提供完整的 Cookie 字符串或直接填写 li_at。")

    try:
        save_cookies(cookies_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存 Cookie 失败: {e}")

    # Verify immediately with probe
    is_valid, status_msg, user_name = verify_linkedin_session(cookies_dict)

    return {
        "success": True,
        "valid": is_valid,
        "user_name": user_name,
        "has_jsessionid": bool(cookies_dict.get("JSESSIONID")),
        "message": status_msg,
    }


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
    
    # If user provided cookie directly in the payload, parse and merge it!
    if payload.li_at and payload.li_at.strip():
        parsed = parse_cookie_input(payload.li_at.strip())
        cookies.update(parsed)
            
    # If li_at is missing, extractor will run in public fallback mode (extracting public comments & like counts)
    has_cookie = bool(cookies and cookies.get("li_at"))
    if not has_cookie:
        cookies = {}

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
