"""
LinkedIn local-Chrome extractor.

Architecture:
  Windows Chrome (logged in, CDP :9222)
        ^
        | host.docker.internal:9222
        |
  Docker: FastAPI + Selenium

No li_at/cookie export is required.
"""
import os
import re
import time
import urllib.request
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException

app = FastAPI(title="LinkedIn Local Chrome Extractor", version="2.2")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class ExtractRequest(BaseModel):
    url: str
    limit_reactions: int = 100
    limit_comments: int = 50

_DRIVER = None

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

def get_driver():
    global _DRIVER
    if _DRIVER is not None:
        try:
            _ = _DRIVER.current_url
            return _DRIVER
        except Exception:
            try:
                _DRIVER.quit()
            except Exception:
                pass
            _DRIVER = None

    cdp = get_cdp_address()
    info = check_cdp()
    browser = info.get("Browser", "")
    ws = info.get("webSocketDebuggerUrl", "")

    options = Options()
    options.add_experimental_option("debuggerAddress", cdp)
    options.page_load_strategy = "eager"

    try:
        _DRIVER = webdriver.Chrome(options=options)
        _DRIVER.set_page_load_timeout(20)
        _DRIVER.set_script_timeout(15)
        return _DRIVER
    except Exception as exc:
        _DRIVER = None
        raise RuntimeError(
            f"Selenium 无法 attach Windows Chrome。"
            f"CDP={cdp}；Browser={browser}；WebSocket={'yes' if ws else 'no'}；"
            f"请确认专用 Chrome 使用 --remote-debugging-address=0.0.0.0。"
            f"原始错误：{exc}"
        ) from exc

def clean_profile(url):
    m = re.search(r"https?://(?:www\.)?linkedin\.com/in/([^/?#]+)", url or "", re.I)
    return "https://www.linkedin.com/in/" + m.group(1).rstrip("/") if m else ""

def profile_from_link(a):
    url = clean_profile(a.get_attribute("href") or "")
    if not url:
        return None
    name = (a.text or "").strip() or url.rstrip("/").split("/")[-1].replace("-", " ").title()
    return {"name": name, "profile_url": url}

def is_visible(el):
    try: return el.is_displayed()
    except Exception: return False

def find_count_button(d, words):
    for el in d.find_elements(By.CSS_SELECTOR, "button,a,[role='button']"):
        try:
            if not is_visible(el): continue
            text = " ".join([el.text or "", el.get_attribute("aria-label") or "",
                             el.get_attribute("data-test-id") or "", el.get_attribute("data-view-name") or ""])
            if re.search(r"\b\d+[\s,]*(?:" + "|".join(words) + r")\b", text, re.I):
                return el
        except StaleElementReferenceException:
            continue
    return None

def scroll_modal(d, root):
    d.execute_script("""
        const el=arguments[0];
        const nodes=[el,...el.querySelectorAll('*')];
        const target=nodes.find(x=>x.scrollHeight>x.clientHeight+100)||el;
        target.scrollTop=target.scrollHeight;
    """, root)

def dialog_profiles(d, excluded, limit):
    dialogs=d.find_elements(By.CSS_SELECTOR, "[role='dialog'],.artdeco-modal")
    if not dialogs: return []
    root=dialogs[-1]
    out=[]; seen=set()
    for a in root.find_elements(By.CSS_SELECTOR, "a[href*='/in/']"):
        try:
            p=profile_from_link(a)
            if not p or p["profile_url"] in excluded or p["profile_url"] in seen: continue
            seen.add(p["profile_url"]); out.append(p)
            if limit>0 and len(out)>=limit: break
        except StaleElementReferenceException:
            continue
    return out

def get_post_author(d):
    selectors=[
        ".update-components-actor a[href*='/in/']",
        ".feed-shared-actor__container a[href*='/in/']",
        "a[href*='/in/'][data-test-id*='author']",
        "a[href*='/in/'][data-view-name*='author']",
    ]
    for selector in selectors:
        for a in d.find_elements(By.CSS_SELECTOR, selector):
            p=profile_from_link(a)
            if p: return p["profile_url"]
    return ""

def extract_reactions(d, author, limit):
    excluded={author} if author else set()
    button=find_count_button(d, ["reactions?","likes?"])
    if button is None:
        return [], "未找到带数字的 reactions/likes 元素；程序没有点击普通 React 按钮。"
    d.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
    d.execute_script("arguments[0].click();", button)
    time.sleep(1.0)
    results=[]; seen=set(); stagnant=0; last=0
    for _ in range(30):
        for p in dialog_profiles(d, excluded, limit):
            if p["profile_url"] not in seen:
                seen.add(p["profile_url"]); results.append(p)
        if limit>0 and len(results)>=limit: break
        dialogs=d.find_elements(By.CSS_SELECTOR, "[role='dialog'],.artdeco-modal")
        if not dialogs: break
        scroll_modal(d, dialogs[-1]); time.sleep(.45)
        if len(results)==last: stagnant+=1
        else: stagnant=0; last=len(results)
        if stagnant>=4: break
    try: d.find_element(By.TAG_NAME,"body").send_keys("\ue00c")
    except Exception: pass
    return results[:limit] if limit>0 else results, ""

def find_comment_button(d):
    for el in d.find_elements(By.CSS_SELECTOR, "button,a,[role='button']"):
        try:
            if not is_visible(el): continue
            text=" ".join([el.text or "",el.get_attribute("aria-label") or "",
                           el.get_attribute("data-test-id") or "",el.get_attribute("data-view-name") or ""])
            if re.search(r"\b\d*[\s,]*comments?\b", text, re.I): return el
        except StaleElementReferenceException:
            continue
    return None

def extract_comments(d, author, limit):
    excluded={author} if author else set()
    button=find_comment_button(d)
    if button is not None:
        try:
            d.execute_script("arguments[0].scrollIntoView({block:'center'});",button)
            d.execute_script("arguments[0].click();",button)
        except Exception:
            try: button.click()
            except Exception: pass
        time.sleep(.8)
    results=[]; seen=set()
    for _ in range(20):
        for a in d.find_elements(By.CSS_SELECTOR,"a[href*='/in/']"):
            try:
                p=profile_from_link(a)
                if not p or p["profile_url"] in excluded or p["profile_url"] in seen: continue
                card=a.find_element(By.XPATH,
                    "./ancestor::*[contains(@class,'comment') or contains(@class,'comments') "
                    "or contains(@data-view-name,'comment') or contains(@data-test-id,'comment')][1]")
                text=(card.text or "").strip()
                if not text: continue
                lines=[x.strip() for x in text.splitlines() if x.strip()]
                comment_text=""
                if p["name"] in lines:
                    i=lines.index(p["name"])
                    if i+1<len(lines): comment_text=lines[i+1]
                seen.add(p["profile_url"])
                results.append({"name":p["name"],"profile_url":p["profile_url"],"text":comment_text})
                if limit>0 and len(results)>=limit: return results
            except Exception:
                continue
        d.execute_script("window.scrollBy(0,1400);"); time.sleep(.5)
    return results[:limit] if limit>0 else results

def inspect_page(d):
    return d.execute_script("""
      const clean=s=>(s||'').replace(/\\s+/g,' ').trim().slice(0,400);
      return {
        url:location.href,title:document.title,
        buttons:[...document.querySelectorAll('button,a,[role="button"]')].slice(0,250).map(e=>({
          text:clean(e.innerText),aria:e.getAttribute('aria-label'),
          testid:e.getAttribute('data-test-id'),view:e.getAttribute('data-view-name')
        })),
        profiles:[...document.querySelectorAll('a[href*="/in/"]')].slice(0,200).map(a=>({
          text:clean(a.innerText),href:a.href
        }))
      };
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
<p>Windows Chrome 负责登录 LinkedIn；Docker 负责提取。无需复制 li_at/Cookie。</p>
<input id="url" placeholder="粘贴 LinkedIn 帖子 URL"><br>
<button onclick="run()">开始提取</button><pre id="out">等待输入...</pre>
<script>async function run(){const u=document.getElementById('url').value.trim();if(!u)return alert('请输入帖子 URL');
const o=document.getElementById('out');o.textContent='正在连接 Windows Chrome...';
try{const r=await fetch('/api/extract',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:u})});
o.textContent=await r.text()}catch(e){o.textContent=e}}</script></main></html>""")

@app.get("/api/health")
def health():
    try:
        info=check_cdp()
        return {"ok":True,"chrome_cdp":get_cdp_address(),"browser":info.get("Browser",""),"websocket":bool(info.get("webSocketDebuggerUrl"))}
    except Exception as exc:
        return {"ok":False,"chrome_cdp":get_cdp_address(),"error":str(exc)}

@app.post("/api/inspect")
def inspect(req: ExtractRequest):
    try:
        d=get_driver()
        d.get(req.url); time.sleep(2); return inspect_page(d)
    except Exception as exc:
        raise HTTPException(status_code=502,detail=str(exc)) from exc

@app.post("/api/extract")
def extract(req: ExtractRequest):
    if not re.match(r"https?://(?:www\.)?linkedin\.com/",req.url,re.I):
        raise HTTPException(status_code=400,detail="请输入 LinkedIn URL。")
    try:
        d=get_driver()
        d.get(req.url); time.sleep(2)
        if "/login" in d.current_url or "/authwall" in d.current_url:
            raise RuntimeError("当前 Chrome 没有处于正常 LinkedIn 登录状态。")
        author=get_post_author(d)
        reactions,note=extract_reactions(d,author,req.limit_reactions)
        d.get(req.url); time.sleep(1)
        comments=extract_comments(d,author,req.limit_comments)
        return {"url":d.current_url,"post_author":author,"total_reactions":len(reactions),
                "total_comments":len(comments),"reactions":reactions,"comments":comments,"note":note}
    except WebDriverException as exc:
        raise HTTPException(status_code=502,detail=f"Chrome 操作失败：{exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502,detail=f"提取失败：{type(exc).__name__}: {exc}") from exc

if __name__=="__main__":
    import uvicorn
    print("LinkedIn Local Chrome Extractor: http://0.0.0.0:8766")
    print("Chrome CDP:", get_cdp_address())
    uvicorn.run(app,host="0.0.0.0",port=8766)
