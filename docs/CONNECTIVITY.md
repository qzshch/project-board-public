# 其他电脑与 Agent 连通性

server 正式地址：http://example-server.example-tailnet.ts.net:18785 。所有命令应在外部 Agent 实际运行的那台电脑本地执行。

## 1. 区分网络与应用身份

- /help、/help/admin、/help/owner、/help/agent 是私网内无需登录的通用文档。
- 项目列表、任务、图、材料和写操作仍需要本项目身份。
- /help/operator、/help/deployment、/manual.md 需要实例管理员身份；不要给普通 Agent 发全局凭据。

连接同一 Tailscale 网络，或由网络管理员共享 server，并确认网络访问规则允许 TCP 18785。只安装 Tailscale、登录了另一套不相通的网络，不能自动访问 server。

## 2. Windows 本地检查

在 PowerShell 中用 curl.exe，避免旧版 PowerShell 的 curl 别名：

```powershell
curl.exe --noproxy "*" --connect-timeout 5 --max-time 15 -sS -o NUL -w "%{http_code}\n" http://example-server.example-tailnet.ts.net:18785/help
```

如果域名无法解析，保留规范域名并指定 server 的已知 Tailscale IP：

```powershell
curl.exe --noproxy "*" --connect-timeout 5 --max-time 15 --resolve "example-server.example-tailnet.ts.net:18785:100.64.0.10" -sS -o NUL -w "%{http_code}\n" http://example-server.example-tailnet.ts.net:18785/help
```

同样检查 /help/admin，应返回 200。--resolve 只能排除 DNS 问题，不能代替加入私网或取得网络访问授权。不要以裸 IP URL 代替规范域名，服务会校验 Host。

Linux/macOS 使用 curl，输出文件 NUL 改为 /dev/null。Python 客户端在子命令前加 --connect-ip 100.64.0.10，可保留规范 Host。

## 3. 按结果排查

| 结果 | 含义及下一步 |
|---|---|
| 普通域名失败，--resolve 返回 200 | 网络已通，检查 MagicDNS/本地 DNS |
| 两种方式均超时或无法连接 | 检查 Tailscale 在线状态、server 可达性、ACL/防火墙的 TCP 18785 权限 |
| /help 返回 200，Agent 网页工具失败 | 改用这台电脑的本地终端/Python；网页工具可能运行在无法访问私网的远端 |
| 文档返回 200，项目 API 返回 401/403 | 网络正常，检查项目身份、角色或会话；文档阅读权限不等于操作权限 |
| 外项目 API 返回 404 | 不通过猜测项目ID扩权；向负责人核对正确项目和授权 |

如仍失败，向负责人提供本地 GET 的状态码/错误文字、是否加入同一网络、域名和 --resolve 两种结果。不要发送 token、身份文件内容或私有管理链接。
