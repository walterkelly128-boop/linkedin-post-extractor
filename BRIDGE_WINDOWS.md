# Windows Chrome Bridge

这个 Bridge 让 Docker 中的 LinkedIn Extractor 使用 Windows 上已经登录 LinkedIn 的 Chrome。

## 推荐方式：GitHub Actions 直接构建 EXE

你不需要在 Windows 安装 Python，也不需要 pip。

1. 打开本仓库 GitHub 的 Actions。
2. 运行 Build Windows Chrome Bridge。
3. 下载工件 chrome-bridge-windows。
4. 解压得到 chrome-bridge.exe。
5. 放到项目目录的 dist\chrome-bridge.exe。

然后在项目根目录运行：

powershell
.\start_chrome_bridge.ps1

脚本会自动：
- 检查 Chrome；
- 启动专用 Chrome CDP :9222；
- 启动 Windows Chrome Bridge :8765；
- Bridge 在 Windows 本机通过 CDP 操作已经登录的 Chrome。

第一次运行后，在专用 Chrome 中登录 LinkedIn。以后保持这个 Chrome 配置目录即可。

## Docker 配置

项目 .env 使用：

CHROME_BRIDGE_URL=http://host.docker.internal:8765

然后：

powershell
docker compose up -d --build

测试 Windows Bridge：

powershell
Invoke-RestMethod "http://127.0.0.1:8765/health"

测试 Docker 到 Bridge：

powershell
docker compose exec extractor python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8765/health', timeout=10).read().decode())"

两个测试都应该返回 ok: true。

## 使用

打开：

http://localhost:8000

勾选“优先使用本机已登录 Chrome”，输入 LinkedIn 帖子 URL，然后开始提取。

整个过程中 LinkedIn 登录会话留在 Windows Chrome 中，不需要把 li_at Cookie 复制到 Docker。

## 本地构建 EXE（可选）

如果以后 Windows 已经安装完整 Python，也可以：

powershell
.\build_bridge.ps1

生成：

dist\chrome-bridge.exe

## 安全

Bridge 为了让 Docker Desktop 可以访问，默认监听 0.0.0.0:8765。

建议只在本机使用，不要把 8765 端口映射到公网。

如需额外保护，可以在 Windows Bridge 和 Docker .env 中设置相同的：

CHROME_BRIDGE_TOKEN=随机长字符串

