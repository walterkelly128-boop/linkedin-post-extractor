"""
FastAPI REST service for LinkedIn Post Extractor.

Start with:
    uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload

Or via Docker:
    docker compose up
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .extractor import LinkedInExtractor, DEFAULT_CDP_URL
from .exporter import save_all
from .models import ExtractRequest, ExtractResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="LinkedIn Post Extractor",
    description=(
        "Extract comments and reactions from LinkedIn posts "
        "using your locally running Chrome browser."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CDP_URL = os.getenv("CHROME_CDP_URL", DEFAULT_CDP_URL)
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", summary="Health check")
def health() -> dict:
    return {
        "status": "ok",
        "cdp_url": CDP_URL,
        "output_dir": str(OUTPUT_DIR),
        "time": datetime.utcnow().isoformat(),
    }


@app.post("/extract", response_model=ExtractResult, summary="Extract post comments and reactions")
def extract(req: ExtractRequest) -> ExtractResult:
    """
    Extract comments and reactions from a LinkedIn post.

    The tool connects to your local Chrome browser (already logged into LinkedIn)
    via Chrome DevTools Protocol.

    **Before calling this endpoint**, make sure Chrome is running with:
    ```
    chrome.exe --remote-debugging-port=9222
    ```
    """
    logger.info("API extract request: %s", req.url)

    extractor = LinkedInExtractor(
        cdp_url=CDP_URL,
        scroll_count=req.scroll_count,
    )

    try:
        result = extractor.extract(
            url_or_id=req.url,
            include_comments=req.include_comments,
            include_reactions=req.include_reactions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during extraction")
        raise HTTPException(status_code=500, detail=str(exc))

    # Auto-save to output directory
    if result.activity_id:
        stem = OUTPUT_DIR / result.activity_id
        try:
            paths = save_all(result, stem)
            logger.info("Saved results to: %s", {k: str(v) for k, v in paths.items()})
        except Exception as exc:
            logger.warning("Could not save output files: %s", exc)

    return result
