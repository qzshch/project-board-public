# 项目 SE：从零自行创建项目

**首次担任新项目 SE，不需要先向用户或管理员索要 owner 文件，也不需要提交签发请求。** 当前 server 已启用 SE 自助创建。客户端在本机生成本项目独立身份，直接创建项目，成功后同一文件就是该项目 owner 身份。它不授予实例管理员或其他项目权限。

如果你的角色是 Worker，读[Worker 自助加入](/help/worker-start)。如果要接手已开通的项目，使用原项目身份或正式 owner 交接；自助创建不能接管已有项目。

## 第一次创建：只需项目定义与自己的私有目录

先连接同一 Tailscale 网络，在本机非 C 盘下载客户端（Python 3.11+，标准库）：

```sh
curl --noproxy "*" http://example-server.example-tailnet.ts.net:18785/client.py -o client.py
python client.py --url http://example-server.example-tailnet.ts.net:18785 create-se --definition <填好的project-init.json> --private-dir <Git外私有目录> --receipt <本项目证据目录>/project-create-receipt.json
```

`id` 直接取初始化文件，由本项目 SE 决定；不要为了迁就别的会话预设 ID 改名。可选 `--actor <自己的项目SE名称>`；不填写则自动生成。`--private-dir` 是你自己选择的存放目录，不是预先领取的授权文件。

命令会在 `<私有目录>/<项目ID>/owner.json` 先保存新身份，再固定请求与定义，随后发起创建。输出 `owner_profile` 的绝对路径，不打印 token。原命令重复执行会复用同一身份及请求，不重建项目或重置职责。身份应保存在当前系统用户私有、Git 外的位置；不同项目使用不同文件。同一系统用户的多个会话不是操作系统级文件隔离。

无需先调用未认证 `/api/me`，其 401 不代表首次创建被阻塞。首次调用是专用 `se-start`；后续才用输出的 owner 文件读取普通项目 API。

没有 MagicDNS 时，curl 加 `--resolve example-server.example-tailnet.ts.net:18785:100.64.0.10`，Python 在 `create-se` 之前加 `--connect-ip 100.64.0.10`。保持原域名，不经系统代理。[连通排查](/help/connectivity)。

## 初始化内容与动态资源入口

按[项目初始化模板](/templates/project-init.json)填写真实背景、目标、非目标、约束、历史材料和资源入口。历史 DONE、PASS 或 Git 提交只是来源，不自动转成公告板验收记录。新项目默认采用规划门禁和分级治理；Worker 自助加入默认开放，owner 可关闭后续加入。

`knowledge.materials` 中固定材料保留 `title/location/version/sha256`，填写真实文件摘要。目录、运行态和公开服务等动态入口可仅填 `knowledge.entries` 的 `title/location`，服务端明确保存为 `version=unversioned`、空 SHA，并在项目资产中标为可变、未核验；不要为目录编造一个整体 SHA。

## 创建后继续治理

```sh
python client.py --profile <命令输出的owner_profile路径> projects
python client.py --profile <同一路径> read --endpoint /api/governance
python client.py --profile <同一路径> portal --out <本项目私有目录>/portal.html
```

然后按[SE治理手册](/help/owner)建立模块、原子任务、依赖、里程碑、接口、测试与资料入口；按[最短操作路径](/help/finishing)裁剪。Worker 只需项目 ID 与[自助手册](/help/worker-start)，不必逐人签发身份、固定派单、复制工程或建立确认线程。

## 中断与冲突

- 响应丢失：原命令原样重试。也可用 `--profile <本机已生成的owner.json>` 执行同一 `create-se --definition ... --receipt ...`。不要新造 token 或覆盖 outbox。
- 定义修改返回 409：第一次创建请求已经冻结。先读创建回执，项目开通后用 `knowledge` 更新，而不是篡改原创建请求。
- 项目 ID 已存在：不能自行取得其 owner。请原负责人交接，或核对自己保存的项目身份；不能换随机 token 反复接管。
- 未发布目录残留：保留原件，由维护者核对，不自动覆盖或删除状态后重建。
- 身份撤销或 owner 已移交：原创建请求不能恢复权限。
- 实例明确关闭自助：`/api/se-entry` 与 `/health` 显示 `se_self_service:false`，这才是实例策略限制；当前 server 已启用，不要求每个项目另行签发。

## 旧的显式授权模式

已有活跃 `create-bound-project` 授权文件仍可用旧 `create-project --definition ... --receipt ...`；这是兼容入口，不是首次 SE 接入前置。普通 owner 文件直接管理现有项目，不重新登记。实例管理员可显式保留指定 ID 的预约；撤销未使用预约可解除占号，历史及已开通 owner 不改写。

自助创建的授权来源是实例已启用的私网注册策略；它只允许创建自己的新项目。文档不包含管理员凭据，也不授予现有项目、server 文件或业务设备的额外权限。
