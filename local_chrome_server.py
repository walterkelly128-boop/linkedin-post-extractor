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
        r=self.pagecmd("Runtime.evaluate",{"expression":expr,"returnByValue":True,"awaitPromise":True},timeout)
        if r.get("exceptionDetails"):raise RuntimeError(str(r["exceptionDetails"]))
        return r.get("result",{}).get("value")

def nav(c,url):
    # 跨 Windows/Linux CDP 附加时只使用 Runtime.evaluate；同一 URL 时强制刷新，避免复用旧 DOM。
    target_url=url.split("#",1)[0].rstrip("/")
    cur=c.eval("location.href",5) or ""
    if cur.split("#",1)[0].rstrip("/")==target_url:
        c.eval("location.reload()",15)
    else:
        c.eval("window.location.href="+json.dumps(url),15)
    end=time.time()+25
    while time.time()<end:
        try:
            cur=c.eval("location.href",5) or ""
            state=c.eval("document.readyState",5) or ""
            body=c.eval("(document.body ? document.body.innerText : "")||''",5) or ""
            if cur.split("#",1)[0].rstrip("/")==target_url and state=="complete" and len(body)>500:
                break
        except Exception:
            pass
        time.sleep(.5)
    time.sleep(3)

def profile(x):
    if not isinstance(x,dict): return None
    h=x.get("profile_url") or x.get("href") or ""
    m=re.search(r"https?://(?:www\.)?linkedin\.com/in/([^/?#]+)",h,re.I)
    if not m:return None
    name=(x.get("name") or x.get("text") or "").strip()
    return {"name":name or m.group(1).replace("-"," "),"profile_url":"https://www.linkedin.com/in/"+m.group(1).rstrip("/")}


def author(c):
    return c.eval(r"""(()=>{const clean=s=>(s||"").replace(/\s+/g," ").trim();
for(const s of [".update-components-actor a[href*='/in/']",".feed-shared-actor__container a[href*='/in/']","a[href*='/in/'][data-test-id*='author']","a[href*='/in/'][data-view-name*='author']"]){const a=document.querySelector(s);if(a)return a.href}
const path=(location.pathname.match(/^\/posts\/([^/?#]+)/i)||[])[1]||"";
const slug=path.split("-ugcPost-")[0].replace(/-$/,"");
if(slug){for(const a of document.querySelectorAll("a[href*='/in/']")){const m=(a.href||"").match(/linkedin\.com\/in\/([^/?#]+)/i);if(m&&m[1].toLowerCase()===slug.toLowerCase())return a.href;}}
const follow=[...document.querySelectorAll("button,a,[role='button']")].find(e=>/^follow\s+/i.test(clean(e.getAttribute("aria-label")||e.innerText||"")));
if(follow){let n=follow;for(let i=0;i<5&&n;i++,n=n.parentElement){const a=n.querySelector("a[href*='/in/']");if(a)return a.href;}}
return ""})()""") or ""

def current_profile(c):
    return c.eval(r"""(()=>{
const norm=s=>(s||"").replace(/\s+/g," ").trim();
const anchors=[...document.querySelectorAll("a[href*='/in/']")];
const me=[...document.querySelectorAll("button,a,[role='button']")].find(e=>{
  const v=norm((e.getAttribute("aria-label")||"")+" "+(e.innerText||""));
  return /^me(?:$|\s)/i.test(v);
});
if(me){
  let n=me;
  for(let i=0;i<8&&n;i++,n=n.parentElement){
    const a=n.querySelector("a[href*='/in/']");
    if(a)return a.href;
  }
}
const candidates=anchors.filter(a=>{
  let n=a;
  for(let i=0;i<5&&n;i++,n=n.parentElement){
    const t=norm(n.innerText||"");
    if(/\bMe\b/i.test(t)&&t.length<500)return true;
  }
  return false;
});
if(candidates[0]?.href)return candidates[0].href;
const joe=[...document.querySelectorAll("a[href*='/in/']")].find(a=>{
  const h=(a.href||"").toLowerCase();
  const t=norm(a.innerText||"");
  return h.includes("/in/joe-hua-2313363a") || /^joe hua$/i.test(t);
});
if(joe)return joe.href;
return "";
})()""") or ""

def reactions(c,auth,author_url,limit):
    js=r"""(async function(){
const clean=s=>(s||"").replace(/\s+/g," ").trim();
const p=a=>{const m=(a.href||"").match(/https?:\/\/(?:www\.)?linkedin\.com\/in\/([^/?#]+)/i);return m?{name:clean(a.innerText)||m[1].replace(/-/g," "),profile_url:"https://www.linkedin.com/in/"+m[1].replace(/\/$/,"")}:null};
const all=[...document.querySelectorAll("button,a,[role='button']")];
const btn=all.find(e=>/\b\d+[\s,]*(?:reactions?|likes?)\b/i.test(clean([e.innerText,e.getAttribute("aria-label"),e.getAttribute("data-test-id"),e.getAttribute("data-view-name")].join(" "))));
if(!btn)return {items:[],note:"未找到 reactions/likes 按钮"};
btn.scrollIntoView({block:"center"});btn.click();
await new Promise(r=>setTimeout(r,2500));
let root=null,seed=null;
for(const a of document.querySelectorAll("a[href*='/in/']")){
  let n=a;
  for(let i=0;i<18&&n;i++,n=n.parentElement){
    const t=clean(n.innerText||"");
    const count=n.querySelectorAll("a[href*='/in/']").length||0;
    if(/\bAll\s+\d+\s+\d+\b/i.test(t)&&count>=2){root=n;seed=a;break}
  }
  if(root)break;
}
if(!root){
  const candidates=[...document.querySelectorAll("div,section")].filter(x=>/\bAll\s+\d+\s+\d+\b/i.test(clean(x.innerText||""))&&x.querySelectorAll("a[href*='/in/']").length>=2);
  root=candidates.sort((a,b)=>a.querySelectorAll("a[href*='/in/']").length-b.querySelectorAll("a[href*='/in/']").length)[0]||null;
}
let out=[],seen=new Set();
if(root){
  for(const a of root.querySelectorAll("a[href*='/in/']")){
    const q=p(a);if(!q||seen.has(q.profile_url))continue;
    seen.add(q.profile_url);out.push(q);if(out.length>=__LIMIT__)break;
  }
}
return {items:out,note:root?"":"未定位到包含 All N N 的 reactions 用户容器"};
})()""";
    r=c.eval(js.replace("__LIMIT__",str(limit)),timeout=55)
    ex=auth.rstrip("/") if auth else ""
    au=author_url.rstrip("/") if author_url else ""
    out=[];seen=set()
    for x in (r or {}).get("items",[]):
        p=profile(x)
        if p and p["profile_url"].rstrip("/")!=ex and p["profile_url"].rstrip("/")!=au and p["profile_url"] not in seen:
            seen.add(p["profile_url"]);out.append(p)
    return out[:limit],(r or {}).get("note","")

def comments(c,auth,limit):
    js=r"""(async function(){
const clean=s=>(s||"").replace(/\s+/g," ").trim();
const profileFrom=a=>{
  const m=(a.href||"").match(/https?:\/\/(?:www\.)?linkedin\.com\/in\/([^/?#]+)/i);
  if(!m)return null;
  let name=clean(a.innerText||"");
  if(!name){
    let n=a;
    for(let i=0;i<6&&n;i++,n=n.parentElement){
      const vals=[...(n.querySelectorAll("a[href*='/in/']")||[])].map(x=>clean(x.innerText||"")).filter(Boolean);
      const v=vals.find(x=>!/^Joe Hua$/i.test(x));
      if(v){name=v;break}
    }
  }
  // LinkedIn may expose the same person's name twice in the profile anchor,
  // e.g. "Dhulquarnayne Babs 3rd+ Dhulquarnayne Babs • 3rd+ ...".
  // Keep only the actual display name and remove connection metadata.
  name=name.split(/\s*[•·]\s*/)[0].trim();
  name=name.replace(/\s+(?:1st|2nd|3rd)\+?\s+/ig," ").trim();
  const words=name.split(/\s+/);
  if(words.length>=2 && words.length%2===0){
    const half=words.length/2;
    if(words.slice(0,half).join(" ").toLowerCase()===words.slice(half).join(" ").toLowerCase()){
      name=words.slice(0,half).join(" ");
    }
  }
  return {name:name||m[1].replace(/-/g," "),profile_url:"https://www.linkedin.com/in/"+m[1].replace(/\/$/,"")};
};
const clickVisibleText=async(text)=>{
  const nodes=[...document.querySelectorAll("button,a,[role='button'],li")].filter(e=>{
    const s=clean(e.innerText||e.getAttribute("aria-label")||"");
    const r=e.getBoundingClientRect();
    return new RegExp("^"+text+"$","i").test(s)&&(!r||r.width>0&&r.height>0);
  });
  const e=nodes[nodes.length-1];
  if(e){e.scrollIntoView({block:"center"});e.click();await new Promise(r=>setTimeout(r,2200));return true}
  return false;
};
const els=[...document.querySelectorAll("button,a,[role='button']")];
const cb=els.find(e=>/\b\d+[\s,]*comments?\b/i.test(clean([e.innerText,e.getAttribute("aria-label"),e.getAttribute("data-test-id"),e.getAttribute("data-view-name")].join(" "))));
if(cb){cb.scrollIntoView({block:"center"});cb.click();await new Promise(r=>setTimeout(r,1800));}
// Open the comment sort menu and force "Most recent".
// LinkedIn loads the newly sorted comments asynchronously; merely clicking the
// menu is not enough. Wait for the menu to close, the text/order to change,
// then repeatedly scroll the actual comment list to trigger virtualized loading.
const sortCandidates=[...document.querySelectorAll("button,a,[role='button'],div,span")].filter(e=>{
  const t=clean(e.innerText||e.getAttribute("aria-label")||"");
  const r=e.getBoundingClientRect();
  return /^most relevant$/i.test(t)&&r.width>0&&r.height>0;
});
const sort=sortCandidates.find(e=>e.closest("button,[role='button'],a"))||sortCandidates[0];
if(sort){
  const target=sort.closest("button,[role='button'],a")||sort;
  target.scrollIntoView({block:"center"});
  target.dispatchEvent(new MouseEvent("mousedown",{bubbles:true,cancelable:true,view:window}));
  target.dispatchEvent(new MouseEvent("mouseup",{bubbles:true,cancelable:true,view:window}));
  target.click();
  await new Promise(r=>setTimeout(r,1000));
}
let recentClicked=false;
for(let pass=0;pass<10&&!recentClicked;pass++){
  const recentCandidates=[...document.querySelectorAll("body *")].filter(e=>{
    const t=clean(e.innerText||e.getAttribute("aria-label")||"");
    const r=e.getBoundingClientRect();
    if(!/^most recent$/i.test(t)||r.width<=0||r.height<=0)return false;
    const s=getComputedStyle(e);
    return s.visibility!=="hidden"&&s.display!=="none";
  });
  const recent=recentCandidates.find(e=>e.closest("[role='menuitem'],[role='option'],button,[role='button'],li,a"))||recentCandidates[0];
  if(recent){
    const target=recent.closest("[role='menuitem'],[role='option'],button,[role='button'],li,a")||recent;
    target.scrollIntoView({block:"center"});
    target.dispatchEvent(new MouseEvent("mousedown",{bubbles:true,cancelable:true,view:window}));
    target.dispatchEvent(new MouseEvent("mouseup",{bubbles:true,cancelable:true,view:window}));
    target.click();
    recentClicked=true;
    await new Promise(r=>setTimeout(r,2200));
    break;
  }
  await new Promise(r=>setTimeout(r,500));
}

// Poll for the sorted list and its lazy-loaded content.
for(let pass=0;pass<14;pass++){
  const body=clean((document.body?document.body.innerText:"")||"");
  const recentVisible=/Most recent/i.test(body);
  const relevantVisible=/Most relevant/i.test(body);
  const boxes=[...document.querySelectorAll("div,section,ul,main")].filter(e=>{
    const t=clean(e.innerText||"");
    return t.length>30&&t.length<20000 &&
      e.scrollHeight>e.clientHeight+80 &&
      (/Follow/i.test(t)||/comments?/i.test(t));
  });
  for(const box of boxes.slice(0,16)){
    const step=Math.max(300,Math.floor(box.clientHeight*0.8));
    const max=Math.max(0,box.scrollHeight-box.clientHeight);
    box.scrollTop=Math.min(max,box.scrollTop+step);
  }
  window.scrollBy(0,500);
  await new Promise(r=>setTimeout(r,850));
  if(pass>=5 && recentVisible && !relevantVisible){
    await new Promise(r=>setTimeout(r,1200));
  }
}
const finalBoxes=[...document.querySelectorAll("div,section,ul,main")].filter(e=>{
  const t=clean(e.innerText||"");
  return t.length>30&&t.length<20000&&e.scrollHeight>e.clientHeight+80&&
         (/Follow/i.test(t)||/comments?/i.test(t));
});
for(const box of finalBoxes.slice(0,16)){
  box.scrollTop=Math.max(0,box.scrollHeight-box.clientHeight);
}
await new Promise(r=>setTimeout(r,1500));

// A comment card in the current LinkedIn DOM has a profile link and a nearby
// container with 1-3 profile links, a Follow action, a timestamp and the
// comment text. Do not use LinkedIn's unstable generated class names.
const cards=[];
const seenCards=new Set();
for(const a of document.querySelectorAll("a[href*='/in/']")){
  const q=profileFrom(a); if(!q)continue;
  let n=a,box=null;
  for(let k=0;k<=8&&n;k++,n=n.parentElement){
    const txt=clean(n.innerText||"");
    const links=n.querySelectorAll("a[href*='/in/']").length||0;
    if(links>=1&&links<=3&&txt.length>=45&&txt.length<1800&&
       /\bFollow\b/i.test(txt)&&
       /(?:\b\d+[smhdwmy]\b|\b\d+\s*(?:day|days|week|weeks|month|months|hour|hours)\b)/i.test(txt)){
      const lines=(n.innerText||"").split("\n").map(clean).filter(Boolean);
      const qi=lines.findIndex(x=>x.toLowerCase()===q.name.toLowerCase());
      if(qi>=0){box=n;break}
      // The anchor text can be empty; accept the compact comment card shape.
      if(k>=3) {box=n;break}
    }
  }
  if(!box)continue;
  const key=q.profile_url+"|"+clean(box.innerText||"");
  if(seenCards.has(key))continue;
  seenCards.add(key);
  cards.push({q,box});
}

const out=[];
for(const {q,box} of cards){
  const lines=(box.innerText||"").split("\n").map(clean).filter(Boolean);
  let text="";
  // Prefer the text after the Follow/timestamp metadata and before reaction counts.
  for(let i=0;i<lines.length;i++){
    const s=lines[i];
    if(!s||/^follow$/i.test(s)||/^(like|reply|more|dismiss)$/i.test(s)||/^\d+$/.test(s)||
       /^\d+\s*(?:likes?|replies?|comments?)$/i.test(s))continue;
    if(/^\d+[smhdwmy]$/i.test(s)||/^\d+\s*(?:day|days|week|weeks|month|months|hour|hours)$/i.test(s))continue;
    if(/^(?:2nd|3rd|1st)\+$/i.test(s))continue;
    if(/^[A-Za-z.]+\s+(?:2nd|3rd|1st)\+$/i.test(s))continue;
    if(i>0 && lines.slice(0,i).some(x=>/^follow$/i.test(x))){text=s;break}
  }
  if(!text){
    const raw=clean(box.innerText||"");
    const m=raw.match(/(?:\b\d+[smhdwmy]\b|\b\d+\s*(?:day|days|week|weeks|month|months|hour|hours)\b)\s+Follow\s+(.+?)(?=\s+\d+(?:\s+\d+){0,2}(?:\s|$))/i);
    if(m)text=clean(m[1]);
  }
  if(text && !out.some(x=>x.profile_url===q.profile_url))out.push({...q,text});
  if(out.length>=__LIMIT__)break;
}
return out;
})()""";
    r=c.eval(js.replace("__LIMIT__",str(limit)),timeout=70)
    ex=auth.rstrip("/");out=[];seen=set()
    for x in r or []:
        p=profile(x)
        if p and p["profile_url"].rstrip("/")!=ex and p["profile_url"] not in seen:
            seen.add(p["profile_url"]);out.append({"name":p["name"],"profile_url":p["profile_url"],"text":x.get("text","")})
    return out[:limit]

def inspect(c):
    raw=c.eval("""JSON.stringify({
        url:location.href,
        title:document.title,
        ready:document.readyState,
        body:((document.body ? document.body.innerText : "")||"").slice(0,5000),
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

@app.post("/api/debug-reactions")
def api_debug_reactions(req:ExtractRequest):
    c=None
    try:
        c=CDP(target());nav(c,req.url)
        js=r"""(async function(){
const clean=s=>(s||"").replace(/\s+/g," ").trim();
const els=[...document.querySelectorAll("button,a,[role='button']")];
const btn=els.find(e=>/\b\d+[\s,]*(?:reactions?|likes?)\b/i.test(clean([e.innerText,e.getAttribute("aria-label"),e.getAttribute("data-test-id"),e.getAttribute("data-view-name")].join(" "))));
const before=btn?{text:clean(btn.innerText),aria:btn.getAttribute("aria-label"),tag:btn.tagName}:null;
if(btn){btn.scrollIntoView({block:"center"});btn.click();await new Promise(r=>setTimeout(r,2500));}
const links=[...document.querySelectorAll("a[href*='/in/']")].map(a=>{
 let n=a,anc=[];
 for(let i=0;i<6&&n;i++,n=n.parentElement){
   anc.push({tag:n.tagName||"",cls:(typeof n.className==="string"?n.className:"").slice(0,250),testid:n.getAttribute("data-test-id"),view:n.getAttribute("data-view-name"),text:clean(n.innerText).slice(0,500)});
 }
 return {text:clean(a.innerText),href:a.href,ancestors:anc};
});
const containers=[...document.querySelectorAll("[role='dialog'],.artdeco-modal,section,[class*='modal'],[class*='dialog']")]
 .filter(x=>/reaction|people who reacted|like/i.test(clean(x.innerText)))
 .slice(0,10).map(x=>({
   tag:x.tagName,cls:(typeof x.className==="string"?x.className:"").slice(0,500),
   role:x.getAttribute("role"),text:clean(x.innerText).slice(0,6000),
   scrollHeight:x.scrollHeight,clientHeight:x.clientHeight,scrollTop:x.scrollTop,
   children:x.querySelectorAll("a[href*='/in/']").length
 }));
return {before,after:{url:location.href,title:document.title},link_count:links.length,links:links.slice(0,80),containers};
})()""";
        return c.eval(js,55)
    except Exception as e:
        raise HTTPException(502,detail=f"调试失败：{type(e).__name__}: {e}")
    finally:
        if c:c.close()

@app.post("/api/debug-comments")
def api_debug_comments(req:ExtractRequest):
    c=None
    try:
        c=CDP(target());nav(c,req.url)
        js=r"""(async function(){
const clean=s=>(s||"").replace(/\s+/g," ").trim();
const all=[...document.querySelectorAll("button,a,[role='button'],li")];
const cb=all.find(e=>/\b\d+[\s,]*comments?\b/i.test(clean([e.innerText,e.getAttribute("aria-label"),e.getAttribute("data-test-id"),e.getAttribute("data-view-name")].join(" "))));
if(cb){cb.scrollIntoView({block:"center"});cb.click();await new Promise(r=>setTimeout(r,1400));}
let sort=[...document.querySelectorAll("button,a,[role='button'],[role='menuitem'],li")].find(e=>/^most relevant$/i.test(clean(e.innerText||e.getAttribute("aria-label")||"")));
if(sort){sort.scrollIntoView({block:"center"});sort.click();await new Promise(r=>setTimeout(r,700));}
const recentCandidates=[...document.querySelectorAll("button,a,[role='button'],[role='menuitem'],li,div,span")].filter(e=>{
  const r=e.getBoundingClientRect();
  return /^most recent$/i.test(clean(e.innerText||e.getAttribute("aria-label")||""))&&r.width>0&&r.height>0;
});
const recent=recentCandidates[recentCandidates.length-1];
if(recent){
  recent.scrollIntoView({block:"center"});
  const clickTarget=recent.closest("button,a,[role='button'],[role='menuitem'],li")||recent;
  clickTarget.click();
  await new Promise(r=>setTimeout(r,2600));
}

// Expand visible "replies"/"reply" controls so replies are included in the
// comment list. This is intentionally limited to reply controls, never Like.
for(let pass=0;pass<4;pass++){
  const replies=[...document.querySelectorAll("button,a,[role='button']")].filter(e=>{
    const t=clean(e.innerText||e.getAttribute("aria-label")||"");
    return /^(?:\d+\s+)?repl(?:y|ies)$/i.test(t) || /^show\s+\d+\s+repl(?:y|ies)$/i.test(t);
  });
  if(!replies.length)break;
  for(const e of replies.slice(0,12)){
    try{e.scrollIntoView({block:"center"});e.click();await new Promise(r=>setTimeout(r,500));}catch(_){}
  }
  await new Promise(r=>setTimeout(r,800));
}
const anchors=[...document.querySelectorAll("a[href*='/in/']")];
const commentAnchors=anchors.filter(a=>/dhulquarnayne|comment/i.test(clean(a.innerText)+" "+a.href));
const inspectAnchor=a=>{
 let arr=[],n=a;
 for(let k=0;k<16&&n;k++,n=n.parentElement){
   const txt=clean(n.innerText||"");
   arr.push({level:k,tag:n.tagName,cls:(typeof n.className==="string"?n.className:"").slice(0,500),testid:n.getAttribute("data-test-id"),view:n.getAttribute("data-view-name"),role:n.getAttribute("role"),links:n.querySelectorAll("a[href*='/in/']").length||0,text:txt.slice(0,2500)});
 }
 return {href:a.href,text:clean(a.innerText),ancestors:arr};
};
const texts=[...document.querySelectorAll("div,p,span")].filter(e=>/Can I get a sample/i.test(clean(e.innerText||""))).slice(0,5).map(e=>({tag:e.tagName,cls:(typeof e.className==="string"?e.className:"").slice(0,500),text:clean(e.innerText).slice(0,2000),parent:e.parentElement?{tag:e.parentElement.tagName,cls:(typeof e.parentElement.className==="string"?e.parentElement.className:"").slice(0,500),text:clean(e.parentElement.innerText).slice(0,2500)}:null}));
return {url:location.href,body:clean((document.body ? document.body.innerText : "")||"").slice(0,9000),commentAnchors:commentAnchors.slice(0,10).map(inspectAnchor),commentTextNodes:texts,allProfiles:anchors.slice(0,30).map(a=>({text:clean(a.innerText),href:a.href}))};
})()""";
        return c.eval(js,60)
    except Exception as e:
        raise HTTPException(502,detail=f"调试评论失败：{type(e).__name__}: {e}")
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
        a=author(c);me=current_profile(c)
        rx,note=reactions(c,me,a,req.limit_reactions)
        nav(c,req.url);cm=comments(c,me,req.limit_comments)
        return {"url":c.eval("location.href"),"post_author":a,"total_reactions":len(rx),"total_comments":len(cm),"reactions":rx,"comments":cm,"note":note}
    except Exception as e:raise HTTPException(502,detail=f"提取失败：{type(e).__name__}: {e}")
    finally:
        if c:c.close()

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=8766)
