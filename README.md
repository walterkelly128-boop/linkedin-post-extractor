# 🚀 LinkedIn Post Comments & Reactions Extractor

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A modern, open-source tool to extract **comments, reactions, and author profiles** (Name, Headline, LinkedIn Profile URL, and Avatars) from any public LinkedIn post.

Supports automated session management, high-throughput extraction via internal endpoints, and one-click export to **CSV, Excel, and JSON**.

[中文文档](#中文说明) | [English Documentation](#features)

---

## ✨ Features

- 🎯 **Smart Post URL Resolution**: Automatically parses all LinkedIn post formats:
  - UGC Posts: `https://www.linkedin.com/posts/username_title-for-ugcPost-7463758057899147265-xxxx`
  - Activity Posts: `https://www.linkedin.com/posts/username_title-activity-7302346926123798528-xxxx`
  - Feed Update URLs: `https://www.linkedin.com/feed/update/urn:li:activity:...`
  - Raw URNs or numeric IDs
- 👤 **Complete Profile Enrichment**:
  - Author/Reactor Name
  - Headline / Occupation / Company
  - Direct Profile URL (`https://www.linkedin.com/in/{username}`)
  - Profile Avatar
  - Comment text, likes, reply counts, and timestamps
  - Reaction types (`LIKE`, `PRAISE`, `EMPATHY`, `APPRECIATION`, `INTEREST`, etc.)
- 🛡️ **Zero-Password Interactive Login**:
  - Run `python main.py login` once. A local browser opens for you to log in; credentials are encrypted and stored locally in `session.json` (never uploaded or leaked).
  - Also supports setting `LINKEDIN_LI_AT` in `.env`.
- 📊 **Multi-Format Export**:
  - **Excel (`.xlsx`)**: Styled worksheets for both Comments and Reactions with auto-width columns.
  - **CSV (`.csv`)**: Standard UTF-8-BOM encoded CSVs for easy import into Excel, Notion, or CRM.
  - **JSON (`.json`)**: Formatted raw structured data for developers.
- ⚡ **High Throughput**: Paged batch extraction (up to 100 reactions/50 comments per request) instead of slow DOM clicking.

---

## 📦 Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-username/linkedin-post-extractor.git
cd linkedin-post-extractor

# 2. Create and activate a virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional, if using interactive login) Install Playwright Chromium
```

---

## 🐳 Docker & Docker Desktop

You can run the extractor directly inside Docker Desktop without setting up a local Python environment!

### 1. Build the Docker Image
```bash
docker compose build
# or: docker build -t linkedin-post-extractor .
```

### 2. Configure Credentials
Copy `.env.example` to `.env` and fill in your LinkedIn `li_at` cookie:
```env
LINKEDIN_LI_AT=AQEDAxxxxxxx
```
*(Or, if you previously ran `python main.py login` on your host machine, the mounted `session.json` will be detected automatically!)*

### 3. Run Extraction with Docker
```bash
# Using Docker Compose:
docker compose run --rm extractor scrape "https://www.linkedin.com/posts/holliszhang_keyoung-hpmc-the-professional-choice-for-ugcPost-7463758057899147265-mOJK"

# Or using plain Docker:
docker run --rm -v "${PWD}/outputs:/app/outputs" --env-file .env linkedin-post-extractor scrape "<POST_URL>"
```
All extracted Excel, CSV, and JSON files will immediately appear in your local `outputs/` folder.

---

## 🚀 Quickstart

### 1. Authenticate (One-time setup)

**Option A: Interactive Login (Recommended)**
```bash
python main.py login
```
A browser window will pop up. Simply log in with your credentials or 2FA. Once you're redirected, the session will be saved automatically to `session.json`.

**Option B: Manual Cookie**
Copy `.env.example` to `.env` and fill in your `li_at` cookie:
```env
LINKEDIN_LI_AT=AQEDAxxxxxxx
```

Check session status anytime:
```bash
python main.py status
```

---

### 2. Extract Comments and Reactions

Extract both comments and reactions from a target post:
```bash
python main.py scrape "https://www.linkedin.com/posts/holliszhang_keyoung-hpmc-the-professional-choice-for-ugcPost-7463758057899147265-mOJK"
```

#### Advanced Options

```bash
# Only extract comments (up to 500)
python main.py scrape "<POST_URL>" --no-reactions --limit-comments 500

# Only extract reactions
python main.py scrape "<POST_URL>" --no-comments --limit-reactions 200

# Export only to Excel
python main.py scrape "<POST_URL>" --format excel
```

---

## 📁 Output Structure

Extracted files are saved to the `outputs/` directory:

```text
outputs/
├── ugcPost_7463758057899147265.xlsx       # Formatted multi-tab spreadsheet
├── ugcPost_7463758057899147265_comments.csv
├── ugcPost_7463758057899147265_reactions.csv
└── ugcPost_7463758057899147265.json
```

### Data Fields

| Field | Description | Example |
| :--- | :--- | :--- |
| `Author / Reactor Name` | Display name of the user | `Sarah Chen` |
| `Headline` | Title / current role | `VP of Growth at HealthTech` |
| `Profile URL` | Direct link to user's profile | `https://www.linkedin.com/in/sarahchen/` |
| `Reaction Type` | Type of engagement | `LIKE`, `PRAISE`, `EMPATHY` |
| `Comment Text` | Content of comment | `Great insights on B2B leadgen!` |
| `Likes / Replies` | Engagement count on comment | `12`, `3` |

---

<a name="中文说明"></a>
## 🇨🇳 中文说明

### 项目介绍
本项目是一个面向 GitHub 开源社区的 LinkedIn 动态互动数据抓取工具，用于提取公开帖子中的**所有点赞用户与评论用户的信息**，包含个人主页链接、昵称、Headline 头衔以及评论正文，可广泛应用于 B2B 线索挖掘、行业KOL互动分析和舆情监控。

### 核心亮点
1. **自动适配多种链接**：原生兼容 `ugcPost-...`、`activity-...`、短链和 Feed URN 等各类格式；
2. **免账号密码交互登录**：首次运行 `python main.py login` 即可本地安全登录并保存 Session，拒绝账号风控；
3. **接口级毫秒并发提取**：复用底层端点分页抓取，单次翻页最多 100 人，速度快且稳定；
4. **多样化导出**：默认自动生成精美配色的 Excel 工作簿（带自动列宽）、CSV 以及结构化 JSON 文件。

---

## ⚖️ Disclaimer

This tool is created for educational and research purposes only. Automated scraping of LinkedIn may violate LinkedIn's [User Agreement](https://www.linkedin.com/legal/user-agreement). The authors and contributors are not responsible for any misuse, account suspensions, or legal liabilities arising from the use of this software. Always comply with relevant privacy regulations (such as GDPR) when handling public profile data.

---

## 📄 License

Distributed under the [MIT License](LICENSE).


### 登录后仍拿不到点赞者主页 URL

当前版本增加了登录态浏览器兜底。即使 LinkedIn 的 Voyager `/feed/reactions` 接口拒绝请求，只要 `outputs/session.json` 中的登录 Cookie 仍有效，系统会自动：

1. 打开目标帖子；
2. 点击 Reactions 统计入口（不会点击普通 Like 按钮）；
3. 滚动点赞者弹窗的虚拟列表；
4. 从真实页面 DOM 提取 `https://www.linkedin.com/in/...` 主页 URL；
5. 将结果直接写入网页表格、JSON、CSV 和 Excel。

Docker 镜像现在会安装 Playwright Chromium。更新代码后请重新构建镜像：

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

如果登录状态已经保存，不需要重新登录；`outputs/session.json` 会通过现有 volume 持久化。


## 本地 Chrome 已登录模式

现在 Web 控制台默认优先连接本机已经登录 LinkedIn 的 Chrome，通过 Chrome DevTools Protocol（CDP）直接操作浏览器页面。这样不需要把 `li_at` 复制到程序里。

### Windows + Docker Desktop

Chrome 136 及以上版本要求远程调试使用独立的非默认 `user-data-dir`。建议使用项目专用 Chrome 配置目录；第一次启动后登录 LinkedIn，以后保持该 Chrome 会话即可。

先关闭正在运行的专用 Chrome 实例，然后 PowerShell 执行：

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
& $chrome --remote-debugging-port=9222 --user-data-dir="E:\linkedin-chrome-profile"
```

如果 Chrome 安装在当前用户目录，可以尝试：

```powershell
$chrome = "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
& $chrome --remote-debugging-port=9222 --user-data-dir="E:\linkedin-chrome-profile"
```

第一次启动该窗口后：

1. 在这个 Chrome 中打开 LinkedIn。
2. 正常登录你的 LinkedIn 账号。
3. 保持 Chrome 不要关闭。
4. 浏览器地址栏打开 `http://127.0.0.1:9222/json/version`，如果看到 JSON，说明 CDP 已开启。
5. 回到 `http://localhost:8000`，勾选「优先使用本机已登录 Chrome」。
6. 粘贴 LinkedIn 帖子 URL，点击「Start Extraction」。

程序会自动打开帖子页面，尝试读取点赞者和评论者的 `/in/...` 主页 URL，并自动导出 Excel/CSV/JSON。

### Docker 更新

```powershell
cd E:\linkedin-post-extractor
git pull origin main
docker compose down
docker compose build --no-cache
docker compose up -d
```

如果已经有镜像并且只是后续普通代码更新：

```powershell
git pull origin main
docker compose up -d --build
```

不要删除 `outputs`，其中包含持久化的 `session.json`。

如果本地 Chrome CDP 暂时不可用，程序会自动回退到现有的 `li_at` / Voyager / Playwright 路径。
