"""Windows-side Chrome Bridge for the LinkedIn extractor.

Run this on the Windows host where the dedicated, already-logged-in Chrome
is listening on 127.0.0.1:9222. The Docker app calls this bridge over HTTP.

This keeps the LinkedIn browser session on Windows; no li_at cookie is copied
to Docker.
"""

import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import uvicorn

from src.parser import parse_post_url
from src.chrome_browser import extract_with_local_chrome

BRIDGE_HOST = os.getenv("CHROME_BRIDGE_HOST", "0.0.0.0")
BRIDGE_PORT = int(os.getenv("CHROME_BRIDGE_PORT", "8765"))
BRIDGE_TOKEN = os.getenv("CHROME_BRIDGE_TOKEN", "").strip()
LOCAL_CDP_URL = os.getenv("LOCAL_CHROME_CDP_URL", "http://127.0.0.1:9222").strip()

app = FastAPI(
    title="LinkedIn Chrome Bridge",
    description="Windows bridge between Docker and an already logged-in local Chrome.",
    version="1.0.0",
)


class ExtractRequest(BaseModel):
    url: str
    include_comments: bool = True
    include_reactions: bool = True
    limit_comments: int = 50
    limit_reactions: int = 100


def check_token(x_bridge_token: Optional[str]) -> None:
    if BRIDGE_TOKEN and x_bridge_token != BRIDGE_TOKEN:
        raise HTTPException(status_code=401, detail="Chrome Bridge token 无效。")


@app.get("/health")
async def health(x_bridge_token: Optional[str] = Header(default=None)):
    check_token(x_bridge_token)
    return {
        "ok": True,
        "bridge": "windows-local-chrome",
        "cdp": LOCAL_CDP_URL,
    }


@app.post("/extract")
async def extract(
    payload: ExtractRequest,
    x_bridge_token: Optional[str] = Header(default=None),
):
    check_token(x_bridge_token)

    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="LinkedIn post URL 不能为空。")

    try:
        post = parse_post_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result, final_url = await extract_with_local_chrome(
            post=post,
            cdp_url=LOCAL_CDP_URL,
            include_comments=payload.include_comments,
            include_reactions=payload.include_reactions,
            comments_limit=payload.limit_comments,
            reactions_limit=payload.limit_reactions,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Windows 本地 Chrome 提取失败：{type(exc).__name__}: {exc}",
        ) from exc

    return {
        "result": result.model_dump(),
        "final_url": final_url,
    }


if __name__ == "__main__":
    print(f"Chrome Bridge listening on http://{BRIDGE_HOST}:{BRIDGE_PORT}")
    print(f"Using local Chrome CDP: {LOCAL_CDP_URL}")
    uvicorn.run(app, host=BRIDGE_HOST, port=BRIDGE_PORT)
