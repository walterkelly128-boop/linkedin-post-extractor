import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_FILE = BASE_DIR / "session.json"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Cookie / Auth configuration
LINKEDIN_LI_AT = os.getenv("LINKEDIN_LI_AT", "").strip()

# Proxy
HTTP_PROXY = os.getenv("HTTP_PROXY", "").strip()
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "").strip()

# Default request delay
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1.5"))

# Common Headers
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

LINKEDIN_VOYAGER_BASE = "https://www.linkedin.com/voyager/api"
