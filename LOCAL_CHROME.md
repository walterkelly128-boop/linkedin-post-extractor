本机 Chrome 简化提取模式

运行方式：
1. 使用已登录 LinkedIn 的专用 Chrome，并开启 9222 调试端口。
2. pip install -r requirements-local.txt
3. python local_chrome_server.py
4. 浏览器打开 http://127.0.0.1:8766

这个模式不复制 li_at，不导出 Cookie，不点击普通 React/赞按钮，也会排除帖子作者。

如果提取结果为 0，可 POST 帖子 URL 到 /api/inspect，查看当前 LinkedIn DOM 中实际存在的按钮和个人主页链接，再针对当前页面结构调整选择器。

以后更新代码只需 git pull，然后重新运行 python local_chrome_server.py，不需要重新生成 EXE。
