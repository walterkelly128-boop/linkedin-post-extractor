"""
LinkedIn local-Chrome extractor.

Architecture:
  Windows Chrome (logged in, CDP :9222)
        ^
        | host.docker.internal:9222
        |
  Docker: FastAPI + direct Chrome DevTools Protocol

No li_at/cookie export is required.
"""
import os
import re
import time
import json
import urllib.request
import socket
import socketserver
import threading
import select

import websocket
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="LinkedIn Local Chrome Extractor", version="3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ExtractRequest(BaseModel):
    url: str
    limit_reactions: int = 100
    limit_comments: int = 50


def get_cdp_address():
    return os.getenv("CHROME_CDP_ADDRESS", "host.docker.internal:9222")


def cdp_request(path):
    address = get_cdp_address()
    req = urllib.request.Request(
        f"http://{address}{path}",
        headers={"Host": "localhost:9222"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def check_cdp():
    address = get_cdp_address()
    try:
        return cdp_request("/json/version")
    except Exception as exc:
        raise RuntimeError(
            f"Windows Chrome CDP 不可访问：{address}；"
            f"已使用 Host: localhost:9222；{exc}"
        ) from exc


def get_page_target():
    targets = cdp_request("/json/list")
    pages = [x for x in targets if x.get("type") == "page"]
    if not pages:
        raise RuntimeError("Windows Chrome CDP 当前没有可控制的页面标签页。")
    # Prefer an existing LinkedIn page, otherwise use the first normal page.
    linkedin = [x for x in pages if "linkedin.com" in (x.get("url") or "").lower()]
    return linkedin[0] if linkedin else pages[0]


class CDPPage:
    def __init__(self, target):
        raw = target.get("webSocketDebuggerUrl", "")
        if not raw:
            raise RuntimeError("Chrome 页面没有提供 webSocketDebuggerUrl。")
        self.url = raw.replace("ws://localhost:9222", "ws://host.docker.internal:9222")
        self.ws = websocket.create_connection(
            self.url,
            timeout=15,
            host="localhost:9222",
            origin="http://localhost:9222",
        )
        self.ws.settimeout(15)
        self._id = 0

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass

    def command(self, method, params=None, timeout=15):
        self._id += 1
        ident = self._id
        msg = {"id": ident, "method": method}
        if params is not None:
            msg["params"] = params
        self.ws.send(json.dumps(msg))
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.2, deadline - time.time())
            self.ws.settimeout(remaining)
            try:
                raw = self.ws.recv()
            except Exception as exc:
                raise RuntimeError(f"CDP 等待 {method} 响应超时：{exc}") from exc
            if not raw:
                raise RuntimeError("Chrome CDP WebSocket 已断开。")
            data = json.loads(raw)
            if data.get("id") != ident:
                continue
            if "error" in data:
                raise RuntimeError(f"CDP {method} 失败：{data['error']}")
            return data.get("result", {})
        raise RuntimeError(f"CDP {method} 响应超时。")

    def evaluate(self, expression, await_promise=True, timeout=30):
        result = self.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"]
            raise RuntimeError(
                detail.get("text")
                or detail.get("exception", {}).get("description")
                or "JavaScript 执行失败"
            )
        return result.get("result", {}).get("value")


def wait_for_page(page, seconds=2.5):
    time.sleep(seconds)
    # Make sure the document is alive and readable.
    page.evaluate("document.readyState", await_promise=False, timeout=5)


def navigate(page, url):
    page.command("Page.enable")
    page.command("Runtime.enable")
    page.command("Page.navigate", {"url": url}, timeout=15)
    wait_for_page(page, 2.5)


def js_profile_from_anchor(a):
    href = a.get("href", "")
    m = re.search(r"https?://(?:www\.)?linkedin\.com/in/([^/?#]+)", href, re.I)
    if not m:
        return None
    profile_url = "https://www.linkedin.com/in/" + m.group(1).rstrip("/")
    name = (a.get("text") or "").strip()
    if not name:
        name = m.group(1).replace("-", " ").title()
    return {"name": name, "profile_url": profile_url}


def get_post_author(page):
    value = page.evaluate(r"""
(() => {
  const sels = [
    ".update-components-actor a[href*='/in/']",
    ".feed-shared-actor__container a[href*='/in/']",
    "a[href*='/in/'][data-test-id*='author']",
    "a[href*='/in/'][data-view-name*='author']"
  ];
  for (const s of sels) {
    const a = document.querySelector(s);
    if (a) return a.href || "";
  }
  return "";
})()
""")
    return value or ""


def extract_reactions(page, author, limit):
    excluded = {author.rstrip("/")} if author else set()
    result = page.evaluate(r"""
async (limit) => {
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const profile = a => {
    const href = a.href || "";
    const m = href.match(/^https?:\/\/(?:www\.)?linkedin\.com\/in\/([^/?#]+)/i);
    if (!m) return null;
    return {
      name: clean(a.innerText) || m[1].replace(/-/g, " "),
      profile_url: "https://www.linkedin.com/in/" + m[1].replace(/\/$/, "")
    };
  };
  const buttons = [...document.querySelectorAll("button,a,[role='button']")];
  const rx = buttons.find(e => {
    const t = clean([e.innerText, e.getAttribute("aria-label"),
      e.getAttribute("data-test-id"), e.getAttribute("data-view-name")].join(" "));
    return /\b\d+[\s,]*(?:reactions?|likes?)\b/i.test(t);
  });
  if (!rx) return {items: [], note: "未找到带数字的 reactions/likes 元素；没有点击普通 React 按钮。"};
  rx.scrollIntoView({block:"center"});
  rx.click();
  await new Promise(r => setTimeout(r, 900));

  const out = [], seen = new Set();
  const collect = () => {
    const dialogs = [...document.querySelectorAll("[role='dialog'],.artdeco-modal")];
    const root = dialogs[dialogs.length - 1];
    if (!root) return false;
    for (const a of root.querySelectorAll("a[href*='/in/']")) {
      const p = profile(a);
      if (!p || seen.has(p.profile_url)) continue;
      seen.add(p.profile_url);
      out.push(p);
      if (limit > 0 && out.length >= limit) return true;
    }
    return false;
  };
  let stagnant = 0, previous = 0;
  for (let i=0; i<35 && !(limit > 0 && out.length >= limit); i++) {
    if (collect()) break;
    const dialogs = [...document.querySelectorAll("[role='dialog'],.artdeco-modal")];
    const root = dialogs[dialogs.length - 1];
    if (!root) break;
    const nodes = [root, ...root.querySelectorAll("*")];
    const scroller = nodes.find(x => x.scrollHeight > x.clientHeight + 100) || root;
    scroller.scrollTop = scroller.scrollHeight;
    await new Promise(r => setTimeout(r, 450));
    if (out.length === previous) stagnant++; else stagnant = 0;
    previous = out.length;
    if (stagnant >= 5) break;
  }
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key:"Escape", bubbles:true}));
  return {items: out.slice(0, limit > 0 ? limit : undefined), note: ""};
}
""", await_promise=True, timeout=35, )
    items = []
    note = ""
    if isinstance(result, dict):
        for item in result.get("items", []):
            p = js_profile_from_anchor(item)
            if p and p["profile_url"].rstrip("/") not in excluded:
                if p["profile_url"] not in {x["profile_url"] for x in items}:
                    items.append(p)
        note = result.get("note", "")
    return items[:limit] if limit > 0 else items, note


def extract_comments(page, author, limit):
    excluded = {author.rstrip("/")} if author else set()
    result = page.evaluate(r"""
async (limit) => {
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const profile = a => {
    const href = a.href || "";
    const m = href.match(/^https?:\/\/(?:www\.)?linkedin\.com\/in\/([^/?#]+)/i);
    if (!m) return null;
    return {
      name: clean(a.innerText) || m[1].replace(/-/g, " "),
      profile_url: "https://www.linkedin.com/in/" + m[1].replace(/\/$/, "")
    };
  };

  const buttons = [...document.querySelectorAll("button,a,[role='button']")];
  const cb = buttons.find(e => {
    const t = clean([e.innerText, e.getAttribute("aria-label"),
      e.getAttribute("data-test-id"), e.getAttribute("data-view-name")].join(" "));
    return /\b\d*[\s,]*comments?\b/i.test(t);
  });
  if (cb) {
    cb.scrollIntoView({block:"center"});
    cb.click();
    await new Promise(r => setTimeout(r, 700));
  }

  const out = [], seen = new Set();
  const collect = () => {
    for (const a of document.querySelectorAll("a[href*='/in/']")) {
      const p = profile(a);
      if (!p || seen.has(p.profile_url)) continue;
      let node = a;
      let text = "";
      for (let i=0; i<7 && node; i++, node=node.parentElement) {
        const cls = String(node.className || "").toLowerCase();
        const dv = String(node.getAttribute?.("data-view-name") || "").toLowerCase();
        const dt = String(node.getAttribute?.("data-test-id") || "").toLowerCase();
        if (cls.includes("comment") || dv.includes("comment") || dt.includes("comment")) {
          text = clean(node.innerText);
          break;
        }
      }
      if (!text) continue;
      const lines = text.split("\n").map(clean).filter(Boolean);
      let comment = "";
      const idx = lines.findIndex(x => x === p.name);
      if (idx >= 0 && lines[idx + 1]) comment = lines[idx + 1];
      seen.add(p.profile_url);
      out.push({...p, text: comment});
      if (limit > 0 && out.length >= limit) return true;
    }
    return false;
  };

  let stagnant = 0, previous = 0;
  for (let i=0; i<25 && !(limit > 0 && out.length >= limit); i++) {
    if (collect()) break;
    window.scrollBy(0, 1300);
    await new Promise(r => setTimeout(r, 500));
    if (out.length === previous) stagnant++; else stagnant = 0;
    previous = out.length;
    if (stagnant >= 5) break;
  }
  return out.slice(0, limit > 0 ? limit : undefined);
}
""", await_promise=True, timeout=35)
    items = []
    seen = set()
    if isinstance(result, list):
        for item in result:
            p = js_profile_from_anchor(item)
            if not p or p["profile_url"].rstrip("/") in excluded or p["profile_url"] in seen:
                continue
            seen.add(p["profile_url"])
            items.append({
                "name": p["name"],
                "profile_url": p["profile_url"],
                "text": item.get("text", "") if isinstance(item, dict) else "",
            })
    return items[:limit] if limit > 0 else items


def inspect_page(page):
    return page.evaluate(r"""
() => {
  const clean=s=>(s||"").replace(/\s+/g," ").trim().slice(0,400);
  return {
    url:location.href,
    title:document.title,
    buttons:[...document.querySelectorAll("button,a,[role='button']")].slice(0,250).map(e=>({
      text:clean(e.innerText),
      aria:e.getAttribute("aria-label"),
      testid:e.getAttribute("data-test-id"),
      view:e.getAttribute("data-view-name")
    })),
    profiles:[...document.querySelectorAll("a[href*='/in/']")].slice(0,200).map(a=>({
      text:clean(a.innerText),
      href:a.href
    }))
  };
}
""")


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>LinkedIn 本机 Chrome 提取器</title>
<style>body{font-family:Arial;background:#f4f7fb;margin:0;color:#172033}
main{max-width:1000px;margin:40px auto;background:#fff;padding:28px;border-radius:14px;box-shadow:0 5px 25px #0001}
input,button{font-size:15px;padding:11px;border-radius:8px;border:1px solid #ccd3df}
input{width:calc(100% - 24px)}button{background:#0a66c2;color:#fff;border:0;cursor:pointer;margin-top:12px}
pre{background:#101827;color:#d7e3f4;padding:16px;border-radius:10px;overflow:auto}</style>
<main><h2>LinkedIn 本机 Chrome 提取器</h2>
<p>Windows Chrome 负责登录 LinkedIn；Docker 通过 Chrome DevTools Protocol 直接控制，不使用 Selenium、li_at 或 Cookie 导出。</p>
<input id="url" placeholder="粘贴 LinkedIn 帖子 URL"><br>
<button onclick="run()">开始提取</button><pre id="out">等待输入...</pre>
<script>async function run(){const u=document.getElementById('url').value.trim();if(!u)return alert('请输入帖子 URL');
const o=document.getElementById('out');o.textContent='正在连接 Windows Chrome...';
try{const r=await fetch('/api/extract',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:u})});
o.textContent=await r.text()}catch(e){o.textContent=e}}</script></main></html>""")


@app.get("/api/health")
def health():
    try:
        info = check_cdp()
        return {
            "ok": True,
            "chrome_cdp": get_cdp_address(),
            "browser": info.get("Browser", ""),
            "websocket": bool(info.get("webSocketDebuggerUrl")),
        }
    except Exception as exc:
        return {"ok": False, "chrome_cdp": get_cdp_address(), "error": str(exc)}


@app.post("/api/inspect")
def inspect(req: ExtractRequest):
    page = None
    try:
        check_cdp()
        page = CDPPage(get_page_target())
        navigate(page, req.url)
        return inspect_page(page)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if page:
            page.close()


@app.post("/api/extract")
def extract(req: ExtractRequest):
    if not re.match(r"https?://(?:www\.)?linkedin\.com/", req.url, re.I):
        raise HTTPException(status_code=400, detail="请输入 LinkedIn URL。")
    page = None
    try:
        check_cdp()
        page = CDPPage(get_page_target())
        navigate(page, req.url)

        current = page.evaluate("location.href")
        if "/login" in current or "/authwall" in current:
            raise RuntimeError("当前 Chrome 没有处于正常 LinkedIn 登录状态。")

        author = get_post_author(page)
        reactions, note = extract_reactions(page, author, req.limit_reactions)

        navigate(page, req.url)
        comments = extract_comments(page, author, req.limit_comments)

        return {
            "url": page.evaluate("location.href"),
            "post_author": author,
            "total_reactions": len(reactions),
            "total_comments": len(comments),
            "reactions": reactions,
            "comments": comments,
            "note": note,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"提取失败：{type(exc).__name__}: {exc}",
        ) from exc
    finally:
        if page:
            page.close()


if __name__ == "__main__":
    import uvicorn
    print("LinkedIn Local Chrome Extractor: http://0.0.0.0:8766")
    print("Chrome CDP:", get_cdp_address())
    uvicorn.run(app, host="0.0.0.0", port=8766)
