import json
import traceback
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .parser import parse_post_url
from .extractor import LinkedInExtractor
from .auth import get_stored_cookies, save_cookies, verify_linkedin_session, parse_cookie_input
from .exporter import export_to_excel, export_to_csv, export_to_json
from .config import BASE_DIR, OUTPUT_DIR, SESSION_FILE
from .models import ExtractionResult, ReactionItem, UserProfile
from .chrome_browser import extract_with_local_chrome
from .config import CHROME_CDP_URL

app = FastAPI(
    title="LinkedIn Post Comments & Reactions Extractor",
    description="Docker Desktop Web Console for LinkedIn social engagement extraction.",
    version="1.0.0",
)

# Enable CORS so browser console snippets on linkedin.com can post directly to localhost:8000
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    use_local_chrome: bool = True


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

    if has_li_at:
        is_valid, status_msg, user_name = verify_linkedin_session(cookies)
    else:
        is_valid, status_msg, user_name = False, "未配置 Cookie", None

    # "configured" is persistence state, not the same thing as a successful
    # live Voyager probe. Never turn a stored li_at into "logged out" merely
    # because the verification endpoint requires a companion JSESSIONID.
    stored_only = has_li_at and not is_valid
    return {
        "configured": has_li_at,
        "has_jsessionid": has_jsessionid,
        "authenticated": is_valid,
        "stored": has_li_at,
        "stored_only": stored_only,
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

    # Preferred mode: connect to the user's already logged-in local Chrome.
    # This does not copy or store Chrome cookies in the application.
    if payload.use_local_chrome:
        try:
            result, _ = extract_with_local_chrome(
                post=post,
                cdp_url=CHROME_CDP_URL,
                include_comments=payload.include_comments,
                include_reactions=payload.include_reactions,
                comments_limit=payload.limit_comments,
                reactions_limit=payload.limit_reactions,
            )
            try:
                export_to_excel(result)
                export_to_csv(result)
                export_to_json(result)
            except Exception as err:
                print(f"Warning: Failed to export local Chrome results: {err}")
            return result
        except Exception as chrome_err:
            print(f"[Local Chrome] {chrome_err}; falling back to stored li_at/Voyager mode.")

    cookies = get_stored_cookies()
    
    # If the user supplies li_at on the extraction form, persist it too so a
    # page refresh does not require entering it again.
    if payload.li_at and payload.li_at.strip():
        parsed = parse_cookie_input(payload.li_at.strip())
        cookies.update(parsed)
        try:
            save_cookies(cookies)
        except Exception as exc:
            print(f"Warning: failed to persist inline LinkedIn cookie: {exc}")

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


class ReactorInput(BaseModel):
    name: str
    profile_url: str
    headline: Optional[str] = ""
    reaction_type: Optional[str] = "LIKE"


class ImportReactionsPayload(BaseModel):
    post_url: Optional[str] = None
    reactors: List[ReactorInput]


@app.post("/api/import_reactions", response_model=ExtractionResult)
async def import_reactions(payload: ImportReactionsPayload):
    """
    Import reactor list collected via browser console/helper directly into the dashboard.
    Updates the post results, re-exports Excel/CSV, and returns the result.
    """
    if not payload.reactors:
        raise HTTPException(status_code=400, detail="未提供点赞者数据。")

    url = (payload.post_url or "").strip()
    post = None
    if url:
        try:
            post = parse_post_url(url)
        except Exception:
            pass

    # Find existing JSON in outputs
    existing_result = None
    if post:
        json_file = OUTPUT_DIR / f"{post.entity_type}_{post.entity_id}.json"
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    existing_result = ExtractionResult(**data)
            except Exception:
                pass

    if not existing_result:
        # Look for most recent json
        import os
        json_files = sorted(OUTPUT_DIR.glob("*.json"), key=os.path.getmtime, reverse=True)
        for jf in json_files:
            if jf.name == "session.json":
                continue
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    existing_result = ExtractionResult(**data)
                    post = existing_result.post
                    break
            except Exception:
                pass

    if not post:
        if not url:
            url = "https://www.linkedin.com/feed/"
        try:
            post = parse_post_url(url)
        except Exception:
            from .models import PostEntity
            post = PostEntity(
                entity_type="post",
                entity_id="imported",
                urn="urn:li:post:imported",
                original_url=url,
            )

    if not existing_result:
        existing_result = ExtractionResult(
            post=post,
            total_comments=0,
            total_reactions=0,
            comments=[],
            reactions=[],
        )

    # Convert incoming reactors
    new_reactions = []
    for r in payload.reactors:
        vanity = ""
        if "/in/" in r.profile_url:
            vanity = r.profile_url.rstrip("/").split("/in/")[-1].split("?")[0]

        clean_url = r.profile_url.split("?")[0]
        new_reactions.append(
            ReactionItem(
                reaction_type=r.reaction_type or "LIKE",
                reactor=UserProfile(
                    name=r.name,
                    profile_url=clean_url,
                    headline=r.headline or "",
                    public_identifier=vanity,
                ),
                post_urn=post.activity_urn or post.urn,
            )
        )

    existing_result.reactions = new_reactions
    existing_result.total_reactions = len(new_reactions)
    existing_result.notes = f"✅ 成功通过浏览器助手导入 {len(new_reactions)} 位点赞者的完整主页链接！"

    # Export to Excel, CSV, JSON
    try:
        export_to_excel(existing_result)
        export_to_csv(existing_result)
        export_to_json(existing_result)
    except Exception as e:
        print(f"Export error: {e}")

    return existing_result
