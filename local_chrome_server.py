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
// LinkedIn's comment sorter is often a custom popover. Do not assume the
// "Most relevant" text itself is the clickable node. First find the visible
// sorter control, click it, then inspect the newly-created menu/popover and
// click the actual "Most recent" item.
let sorterClicked=false;
const sorterCandidates=[...document.querySelectorAll("button,a,[role='button'],div,span")].filter(e=>{
  const t=clean(e.innerText||e.getAttribute("aria-label")||"");
  const r=e.getBoundingClientRect();
  return /^most relevant$/i.test(t)&&r.width>0&&r.height>0;
});
const sorter=sorterCandidates.sort((a,b)=>{
  const aa=a.closest("button,[role='button'],a")?1:0;
  const bb=b.closest("button,[role='button'],a")?1:0;
  return bb-aa;
})[0];
if(sorter){
  const target=sorter.closest("button,[role='button'],a")||sorter;
  target.scrollIntoView({block:"center"});
  target.dispatchEvent(new MouseEvent("mousedown",{bubbles:true,cancelable:true,view:window}));
  target.dispatchEvent(new MouseEvent("mouseup",{bubbles:true,cancelable:true,view:window}));
  target.click();
  sorterClicked=true;
  await new Promise(r=>setTimeout(r,900));
}

// Find the actual visible menu item. LinkedIn may render it as a div/span,
// with the clickable ancestor several levels above it.
let recentClicked=false;
for(let pass=0;pass<8&&!recentClicked;pass++){
  const candidates=[...document.querySelectorAll("body *")].filter(e=>{
    const t=clean(e.innerText||e.getAttribute("aria-label")||"");
    const r=e.getBoundingClientRect();
    if(!/^most recent$/i.test(t)||r.width<=0||r.height<=0)return false;
    const s=getComputedStyle(e);
    return s.visibility!=="hidden"&&s.display!=="none";
  });
  const recent=candidates.sort((a,b)=>{
    const ca=a.closest("[role='menuitem'],button,[role='option'],li,[role='button']")?1:0;
    const cb=b.closest("[role='menuitem'],button,[role='option'],li,[role='button']")?1:0;
    return cb-ca;
  })[0];
  if(recent){
    let target=recent.closest("[role='menuitem'],[role='option'],button,[role='button'],li,a");
    if(!target){
      target=recent.parentElement||recent;
      for(let k=0;k<4&&target;k++,target=target.parentElement){
        const tt=clean(target.innerText||"");
        if(/^most recent$/i.test(tt))break;
      }
    }
    if(target){
      target.scrollIntoView({block:"center"});
      target.dispatchEvent(new MouseEvent("mousedown",{bubbles:true,cancelable:true,view:window}));
      target.dispatchEvent(new MouseEvent("mouseup",{bubbles:true,cancelable:true,view:window}));
      target.click();
      recentClicked=true;
      await new Promise(r=>setTimeout(r,1200));
      break;
    }
  }
  await new Promise(r=>setTimeout(r,500));
}

// Wait for LinkedIn to finish replacing the comment list. The selected
// sorter should now read "Most recent" rather than "Most relevant".
for(let pass=0;pass<12;pass++){
  const txt=clean((document.body?document.body.innerText:"")||"");
  if(/Most recent/i.test(txt)&&!/Most relevant\s+Most recent/i.test(txt)){
    await new Promise(r=>setTimeout(r,500));
    if(pass>=4)break;
  }
  await new Promise(r=>setTimeout(r,600));
}


