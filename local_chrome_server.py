import os,re,time,json,urllib.request,websocket
from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app=FastAPI(title="LinkedIn Local Chrome Extractor",version="3.3")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

class ExtractRequest(BaseModel):
    url:str
    limit_reactions:int=100
    limit_comments:int=50

def addr(): return os.getenv("CHROME_CDP_ADDRESS","host.docker.internal:9222")

def cdp_http(path):
    req=urllib.request.Request("http://"+addr()+path,headers={"Host":"localhost:9222"})
    with urllib.request.urlopen(req,timeout=5) as r:return json.loads(r.read())

def check_cdp():
    try:return cdp_http("/json/version")
    except Exception as e:raise RuntimeError(f"Windows Chrome CDP 不可访问：{addr()}；{e}") from e

def target():
    pages=[x for x in cdp_http("/json/list") if x.get("type")=="page"]
    if not pages:raise RuntimeError("Windows Chrome CDP 当前没有可控制的页面标签页。")
    li=[x for x in pages if "linkedin.com" in (x.get("url") or "").lower()]
    return li[0] if li else pages[0]

class CDP:
    def __init__(self,t):
        raw=check_cdp()["webSocketDebuggerUrl"].replace("ws://localhost:9222","ws://host.docker.internal:9222")
        self.ws=websocket.create_connection(raw,timeout=15,host="localhost:9222",origin="http://localhost:9222")
        self.ws.settimeout(15);self.i=0
        r=self.cmd("Target.attachToTarget",{"targetId":t["id"],"flatten":True})
        self.session=r["sessionId"]
        try:self.cmd("Target.activateTarget",{"targetId":t["id"]})
        except Exception:pass
    def close(self):
        try:self.ws.close()
        except:pass
    def cmd(self,method,params=None,session=None,timeout=20):
        self.i+=1;ident=self.i
        m={"id":ident,"method":method}
        if params is not None:m["params"]=params
        if session:m["sessionId"]=session
        self.ws.send(json.dumps(m))
        end=time.time()+timeout
        while time.time()<end:
            self.ws.settimeout(max(.2,end-time.time()))
            try:d=json.loads(self.ws.recv())
            except Exception as e:raise RuntimeError(f"CDP 等待 {method} 响应超时：{e}") from e
            if d.get("id")!=ident:continue
            if "error" in d:raise RuntimeError(f"CDP {method} 失败：{d['error']}")
            return d.get("result",{})
        raise RuntimeError(f"CDP {method} 响应超时。")
    def pagecmd(self,m,p=None,timeout=20):return self.cmd(m,p,self.session,timeout)
    def eval(self,expr,timeout=40):
        r=self.pagecmd("Runtime.evaluate",{"expression":"(async()=>("+expr+"))()","returnByValue":True,"awaitPromise":True},timeout)
        if r.get("exceptionDetails"):raise RuntimeError(str(r["exceptionDetails"]))
        return r.get("result",{}).get("value")

def nav(c,url):
    # 完全绕过 Page domain；跨 Windows/Linux CDP 附加时只使用 Runtime.evaluate。
    js="window.location.href="+json.dumps(url)
    c.eval(js,15)
    end=time.time()+20
    target_url=url.split("#",1)[0].rstrip("/")
    while time.time()<end:
        try:
            cur=c.eval("location.href",5) or ""
            if cur.startswith(target_url) or ("linkedin.com" in cur.lower() and "login" not in cur.lower() and "authwall" not in cur.lower() and cur!="about:blank"):
                break
        except Exception:
            pass
        time.sleep(.5)
    time.sleep(3)

def profile(x):
    h=x.get("href","")
    m=re.search(r"https?://(?:www\.)?linkedin\.com/in/([^/?#]+)",h,re.I)
    if not m:return None
    return {"name":(x.get("text") or "").strip() or m.group(1).replace("-"," "),"profile_url":"https://www.linkedin.com/in/"+m.group(1).rstrip("/")}

def author(c):
    return c.eval("""(()=>{for(const s of [".update-components-actor a[href*='/in/']",".feed-shared-actor__container a[href*='/in/']","a[href*='/in/'][data-test-id*='author']","a[href*='/in/'][data-view-name*='author']"]){const a=document.querySelector(s);if(a)return a.href}return ""})()""") or ""

def reactions(c,auth,limit):
    r=c.eval(f"""async()=>{
const clean=s=>(s||"").replace(/\s+/g," ").trim();
const p=a=>{let m=(a.href||"").match(/https?:\/\/(?:www\.)?linkedin\.com\/in\/([^/?#]+)/i);return m?{name:clean(a.innerText)||m[1].replace(/-/g," "),profile_url:"https://www.linkedin.com/in/"+m[1].replace(/\/$/,"")}:null};
let b=[...document.querySelectorAll("button,a,[role='button']")].find(e=>/\b\d+[\s,]*(?:reactions?|likes?)\b/i.test(clean([e.innerText,e.getAttribute("aria-label"),e.getAttribute("data-test-id"),e.getAttribute("data-view-name")].join(" "))));
if(!b)return {items:[],note:"未找到 reactions/likes 按钮"};
b.scrollIntoView({block:"center"});b.click();await new Promise(r=>setTimeout(r,1200));
let out=[],seen=new Set();
for(let z=0;z<40&&out.length<{limit};z++){
 const ds=[...document.querySelectorAll("[role='dialog'],.artdeco-modal")],root=ds[ds.length-1];if(!root)break;
 for(const a of root.querySelectorAll("a[href*='/in/']")){const q=p(a);if(q&&!seen.has(q.profile_url)){seen.add(q.profile_url);out.push(q);if(out.length>={limit})break}}
 const sc=[...root.querySelectorAll("*")].find(x=>x.scrollHeight>x.clientHeight+100)||root;sc.scrollTop=sc.scrollHeight;
 await new Promise(r=>setTimeout(r,500));
}
return {items:out,note:""};
}""",timeout=45)
    ex=auth.rstrip("/");out=[];seen=set()
    for x in (r or {}).get("items",[]):
        p=profile(x)
        if p and p["profile_url"].rstrip("/")!=ex and p["profile_url"] not in seen:seen.add(p["profile_url"]);out.append(p)
    return out[:limit],(r or {}).get("note","")
def comments(c,auth,limit):
    r=c.eval(r"""async()=>{
const clean=s=>(s||"").replace(/\s+/g," ").trim();
const p=a=>{let m=(a.href||"").match(/https?:\/\/(?:www\.)?linkedin\.com\/in\/([^/?#]+)/i);return m?{name:clean(a.innerText)||m[1].replace(/-/g," "),profile_url:"https://www.linkedin.com/in/"+m[1].replace(/\/$/,"")}:null};
let b=[...document.querySelectorAll("button,a,[role='button']")].find(e=>/\b\d+[\s,]*comments?\b/i.test(clean([e.innerText,e.getAttribute("aria-label"),e.getAttribute("data-test-id"),e.getAttribute("data-view-name")].join(" "))));
if(b){b.scrollIntoView({block:"center"});b.click();await new Promise(r=>setTimeout(r,900))}
let out=[],seen=new Set();
for(let z=0;z<35&&!({limit}>0&&out.length>={limit});z++){
 for(let a of document.querySelectorAll("a[href*='/in/']")){let q=p(a);if(!q||seen.has(q.profile_url))continue;let n=a,txt="";
  for(let i=0;i<8&&n;i++,n=n.parentElement){let s=((n.className||"")+" "+(n.getAttribute?.("data-view-name")||"")+" "+(n.getAttribute?.("data-test-id")||"")).toLowerCase();if(s.includes("comment")){txt=clean(n.innerText);break}}
  if(txt){let lines=txt.split("\n").map(clean).filter(Boolean),i=lines.findIndex(x=>x===q.name);seen.add(q.profile_url);out.push({...q,text:i>=0&&lines[i+1]?lines[i+1]:""});if(limit>0&&out.length>=limit)break}
 }
 window.scrollBy(0,1300);await new Promise(r=>setTimeout(r,500));
}
return out.slice(0,{limit}>0?{limit}:undefined);
}""",timeout=45)
    ex=auth.rstrip("/");out=[];seen=set()
    for x in r or []:
        p=profile(x)
        if p and p["profile_url"].rstrip("/")!=ex and p["profile_url"] not in seen:
            seen.add(p["profile_url"]);out.append({"name":p["name"],"profile_url":p["profile_url"],"text":x.get("text","")})
    return out[:limit] if limit>0 else out

def inspect(c):
    raw=c.eval("""JSON.stringify({
        url:location.href,
        title:document.title,
        ready:document.readyState,
        body:(document.body?.innerText||"").slice(0,5000),
        buttons:[...document.querySelectorAll("button,a,[role='button']")].slice(0,300).map(e=>({
            text:(e.innerText||"").trim(),
            aria:e.getAttribute("aria-label"),
            testid:e.getAttribute("data-test-id"),
            view:e.getAttribute("data-view-name")
        })),
        profiles:[...document.querySelectorAll("a[href*='/in/']")].slice(0,300).map(a=>({
            text:(a.innerText||"").trim(),
            href:a.href
        }))
    })""")
    if not raw:
        raise RuntimeError("Chrome Runtime.evaluate 没有返回 inspect 数据。")
    return json.loads(raw)

@app.get("/",response_class=HTMLResponse)
def home():
    return HTMLResponse("""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>LinkedIn 本机 Chrome 提取器</title><style>body{font-family:Arial;background:#f4f7fb;margin:0;color:#172033}main{max-width:1000px;margin:40px auto;background:#fff;padding:28px;border-radius:14px;box-shadow:0 5px 25px #0001}input,button{font-size:15px;padding:11px;border-radius:8px;border:1px solid #ccd3df}input{width:calc(100% - 24px)}button{background:#0a66c2;color:#fff;border:0;cursor:pointer;margin-top:12px}pre{background:#101827;color:#d7e3f4;padding:16px;border-radius:10px;overflow:auto}</style><main><h2>LinkedIn 本机 Chrome 提取器</h2><p>Windows Chrome 登录 LinkedIn；Docker 通过 CDP 直接控制，不使用 Selenium、li_at 或 Cookie 导出。</p><input id="url" placeholder="粘贴 LinkedIn 帖子 URL"><br><button onclick="run()">开始提取</button><pre id="out">等待输入...</pre><script>async function run(){const u=document.getElementById('url').value.trim();if(!u)return alert('请输入帖子 URL');const o=document.getElementById('out');o.textContent='正在连接 Windows Chrome...';try{const r=await fetch('/api/extract',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:u})});o.textContent=await r.text()}catch(e){o.textContent=e}}</script></main></html>""")

@app.get("/api/health")
def health():
    try:
        i=check_cdp();return {"ok":True,"chrome_cdp":addr(),"browser":i.get("Browser",""),"websocket":bool(i.get("webSocketDebuggerUrl"))}
    except Exception as e:return {"ok":False,"chrome_cdp":addr(),"error":str(e)}

@app.post("/api/inspect")
def api_inspect(req:ExtractRequest):
    c=None
    try:c=CDP(target());nav(c,req.url);return inspect(c)
    except Exception as e:raise HTTPException(502,detail=str(e))
    finally:
        if c:c.close()

@app.post("/api/extract")
def extract(req:ExtractRequest):
    if not re.match(r"https?://(?:www\.)?linkedin\.com/",req.url,re.I):raise HTTPException(400,detail="请输入 LinkedIn URL。")
    c=None
    try:
        c=CDP(target());nav(c,req.url)
        cur=c.eval("location.href")
        if "/login" in cur or "/authwall" in cur:raise RuntimeError("当前 Chrome 没有处于正常 LinkedIn 登录状态。")
        a=author(c);rx,note=reactions(c,a,req.limit_reactions)
        nav(c,req.url);cm=comments(c,a,req.limit_comments)
        return {"url":c.eval("location.href"),"post_author":a,"total_reactions":len(rx),"total_comments":len(cm),"reactions":rx,"comments":cm,"note":note}
    except Exception as e:raise HTTPException(502,detail=f"提取失败：{type(e).__name__}: {e}")
    finally:
        if c:c.close()

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=8766)
