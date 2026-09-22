# Windows Chrome + Docker 模式

## 架构

- Windows 专用 Chrome：保存 LinkedIn 登录状态，开放 CDP 9222
- Docker：运行 FastAPI + Selenium
- Docker 通过 `host.docker.internal:9222` 连接 Windows Chrome
- 不复制 `li_at`
- 不导出 Cookie
- 不需要 chrome-bridge.exe
- 不需要 Docker 内运行 Chrome

## 第一次运行

PowerShell：

```powershell
.start_local_chrome.ps1
```

第一次打开的专用 Chrome 中登录 LinkedIn。

然后：

```powershell
docker compose up -d --build
```

浏览器打开：

```
http://127.0.0.1:8766
```

## 更新代码

```powershell
git pull
docker compose up -d --build
```

## 查看日志

```powershell
docker compose logs -f
```

## 测试 Docker API

```powershell
Invoke-RestMethod "http://127.0.0.1:8766/api/health"
```

正常应返回：

```json
{"ok":true,"chrome_cdp":"host.docker.internal:9222"}
```

如果提取仍然是 0 人，不要再安装 Python 依赖，先使用：

```
POST /api/inspect
```

检查 LinkedIn 当前 DOM，再针对真实页面结构修改提取器。
