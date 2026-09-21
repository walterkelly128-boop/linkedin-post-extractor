# LinkedIn Post Extractor

Extract **comments** and **reactions** from any LinkedIn post — including commenter profile URLs, names, headlines, comment text, and reaction types.

Uses your **local Chrome browser** (no cookies to export, no paid APIs, no account ban risk).

---

## ✨ Features

| Feature | Detail |
|---------|--------|
| 📝 Comments | Author name, headline, profile URL, comment text, timestamp |
| 👍 Reactions | Author name, headline, profile URL, reaction type (Like/Celebrate/Love…) |
| 🔗 3 URL formats | Activity ID / Activity URL / Full post URL |
| 📊 Exports | JSON + CSV (Excel-compatible UTF-8) |
| 🖥️ CLI | `python -m src.main --url <url>` |
| 🌐 REST API | FastAPI at `http://localhost:8000` |
| 🐳 Docker | Full Docker Compose setup |

---

## 🚀 Quick Start

### Step 1 — Start Chrome in debug mode

Double-click:
```
scripts\start_chrome_debug.bat
```

A Chrome window will open. **Log in to LinkedIn** if prompted. Keep the window open.

> Verify it's working: http://localhost:9222/json should return JSON.

---

### Step 2 — Run with Docker (recommended)

```bash
docker compose up
```

The API will be available at **http://localhost:8000**.

---

### Step 3 — Extract a post

**Via REST API:**
```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/posts/example-activity-7302346926123798528-dMnz"}'
```

**Via CLI (without Docker):**
```bash
pip install -r requirements.txt
python -m src.main --url "https://www.linkedin.com/posts/example-activity-7302346926123798528-dMnz"
```

Results are saved in the `output/` directory.

---

## 📥 Supported URL Formats

```
# 1. Raw Activity ID
7302346926123798528

# 2. Activity URL
https://www.linkedin.com/feed/update/urn:li:activity:7302346926123798528/

# 3. Full post URL
https://www.linkedin.com/posts/username_title-activity-7302346926123798528-dMnz
```

---

## 📤 Output Format

Results are saved as:
- `output/<activity_id>.json` — full structured data
- `output/<activity_id>_comments.csv` — comments (Excel-ready)
- `output/<activity_id>_reactions.csv` — reactions (Excel-ready)

### Comment fields
| Field | Description |
|-------|-------------|
| `author_name` | Commenter's full name |
| `author_headline` | LinkedIn headline |
| `author_profile_url` | LinkedIn profile URL |
| `comment_text` | Full comment text |
| `comment_time_str` | Timestamp (UTC) |
| `comment_type` | `comment` or `reply` |
| `is_edited` | Whether the comment was edited |

### Reaction fields
| Field | Description |
|-------|-------------|
| `author_name` | Reactor's full name |
| `author_headline` | LinkedIn headline |
| `author_profile_url` | LinkedIn profile URL |
| `reaction_type` | `LIKE`, `PRAISE`, `EMPATHY`, `APPRECIATION`, `INTEREST` |

---

## ⚙️ CLI Options

```
python -m src.main --help

Options:
  --url, -u       LinkedIn post URL or activity ID (required)
  --output, -o    Output file stem (default: output/result)
  --scroll, -s    Scroll iterations to load more (default: 5)
  --no-comments   Skip comment extraction
  --no-reactions  Skip reaction extraction
  --cdp-url       Chrome CDP URL (default: http://localhost:9222)
  --verbose, -v   Enable debug logging
```

---

## 🌐 REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check + config info |
| `/extract` | POST | Extract post data |
| `/docs` | GET | Interactive Swagger UI |

**Request body for `/extract`:**
```json
{
  "url": "https://www.linkedin.com/posts/...",
  "include_comments": true,
  "include_reactions": true,
  "scroll_count": 5
}
```

---

## 🐳 Docker Details

The Docker image does **not** install a browser. Instead, the container connects to your host machine's Chrome via:

```
ws://host.docker.internal:9222
```

This keeps the image small and avoids any browser management inside the container.

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `CHROME_CDP_URL` | `ws://host.docker.internal:9222` | Chrome CDP endpoint |
| `OUTPUT_DIR` | `/app/output` | Where to save output files |

---

## 🔧 How It Works

```
Your LinkedIn Post URL
        ↓
  Parse Activity ID  (supports 3 URL formats)
        ↓
  Connect to local Chrome via CDP
  (Chrome is already logged in to LinkedIn)
        ↓
  Navigate to post — intercept /voyager/api/ responses
        ↓
  Scroll page to trigger paginated API calls
        ↓
  Parse & deduplicate comments + reactions
        ↓
  Save JSON + CSV to output/
```

LinkedIn's frontend loads comments and reactions via its internal REST API (`/voyager/api/feed/comments`, `/voyager/api/feed/reactions`). The extractor intercepts these XHR responses directly — no fragile DOM scraping.

---

## ⚠️ Disclaimer

This tool is for **educational and personal research purposes only**.
Scraping LinkedIn may violate their [Terms of Service](https://www.linkedin.com/legal/user-agreement).
Use responsibly. Do not store personal data. Do not use for commercial purposes.

---

## 📁 Project Structure

```
linkedin-post-extractor/
├── scripts/
│   └── start_chrome_debug.bat   # Launch Chrome with debug port
├── src/
│   ├── main.py      # CLI entry point
│   ├── api.py       # FastAPI REST service
│   ├── extractor.py # Core CDP + response interception
│   ├── parser.py    # URL parsing
│   ├── models.py    # Pydantic data models
│   └── exporter.py  # JSON + CSV export
├── tests/
│   └── test_parser.py
├── output/          # Results saved here
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
