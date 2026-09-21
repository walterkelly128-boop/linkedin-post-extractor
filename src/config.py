import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE = OUTPUT_DIR / "session.json"
LEGACY_SESSION_FILE = BASE_DIR / "session.json"

LINKEDIN_LI_AT = os.getenv("LINKEDIN_LI_AT", "").strip()

HTTP_PROXY = os.getenv("HTTP_PROXY", "").strip()
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "").strip()

REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1.5"))

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

LINKEDIN_VOYAGER_BASE = "https://www.linkedin.com/voyager/api"

LINKEDIN_REACTIONS_QUERY_ID = os.getenv(
    "LINKEDIN_REACTIONS_QUERY_ID",
    "voyagerSocialDashReactions.41ebf31a9f4c4a84e35a49d5abc9010b",
).strip()

# Docker Desktop reaches the Windows host through host.docker.internal.
# For Playwright CDP, prefer the browser websocket URL directly. Chrome 153
# can reject the HTTP /json/version discovery request from inside Docker.
CHROME_CDP_URL = os.getenv(
    "CHROME_CDP_URL",
    "ws://host.docker.internal:9222/devtools/browser",
).strip()
CHROME_CDP_TIMEOUT = float(os.getenv("CHROME_CDP_TIMEOUT", "15").strip() or "15")
