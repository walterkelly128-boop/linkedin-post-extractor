import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Store session in outputs directory so it survives Docker volume mounts safely
SESSION_FILE = OUTPUT_DIR / "session.json"
LEGACY_SESSION_FILE = BASE_DIR / "session.json"

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

# Current LinkedIn web reaction query. LinkedIn may rotate persisted-query hashes;
# this can be overridden without changing code when LinkedIn deploys a new hash.
LINKEDIN_REACTIONS_QUERY_ID = os.getenv(
    "LINKEDIN_REACTIONS_QUERY_ID",
    "voyagerSocialDashReactions.41ebf31a9f4c4a84e35a49d5abc9010b",
).strip()
