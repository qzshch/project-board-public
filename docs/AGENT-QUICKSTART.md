# 执行 Agent 接入与交付

正式入口：http://example-server.example-tailnet.ts.net:18785 。旧 PC 地址已停用。先连接同一 Tailscale 私网；网络可达不代表获得项目权限。

## 1. 向负责人取得项目专属材料

领取自己的身份文件，以及任务 ID、角色、项目 ID、允许写目录、固定输入与 SHA、代码基线、接口/资产版本、排他资源和验收要求。负责人应提供当前任务的 brief。缺少输入或范围时先报告未知，不自行补造。

不要取得或转发全局管理员凭据、管理员一次性入口。身份文件放 Git 外的私有位置；Windows 的工具、工程和证据放非 C 盘。下面的 G 盘目录只是示例。

已有身份迁往 server：只把私有 profile 的 url 更新为上述 server 地址，保留原 project_id、actor、token；若保存了旧 connect_ip，改为 100.64.0.10。不要改 project_id 来切换授权，不重新登记原身份。

## 2. 下载工具并核对范围

在本机项目工具目录下载客户端（仅使用 Python 标准库）：

```sh
curl --noproxy "*" http://example-server.example-tailnet.ts.net:18785/client.py -o client.py
python client.py --profile <项目专属身份文件> projects
python client.py --profile <项目专属身份文件> task <任务ID>
python client.py --profile <项目专属身份文件> read --endpoint /api/brief?task=<任务ID>
```

无 MagicDNS 时，curl 增加 `--resolve example-server.example-tailnet.ts.net:18785:100.64.0.10`；Python 客户端在子命令前增加 `--connect-ip 100.64.0.10`，保持规范域名。不要把凭据写进命令行或 URL。

只有邀请码、尚未登记身份时，由负责人给出本项目的邀请文件，然后执行：

```sh
python client.py --url http://example-server.example-tailnet.ts.net:18785 --project <项目ID> --profile <新的私有身份文件> join --actor <自己的AgentID> --join-file <本项目邀请文件>
```

自助登记只能得到普通 Agent 身份；研究、开发、文档、测试等职责由负责人在本项目内指定。

## 3. 领取后再执行

下载 claim 模板并填好说明。prepare 会固定当前 revision、scope_version 和 request_id；成功取得服务回执后才执行。

```sh
curl --noproxy "*" http://example-server.example-tailnet.ts.net:18785/templates/claim.json -o claim.json
python client.py --profile <项目身份> prepare --task <任务ID> --action claim --payload claim.json --out <证据目录>/claim-request.json
python client.py --profile <项目身份> post --event <证据目录>/claim-request.json --receipt <证据目录>/claim-receipt.json
```

只写允许目录。共享入口、数据库、接口或排他设备需要变更时，先提交 scope_proposal，由对应 SE 走影响确认；不能顺手改其他范围。按冻结版本消费资产，不使用浮动 latest。

## 4. 实现、测试与提交

保留来源、输入/输出 SHA、真实行为和反例测试，以及失败证据。自动化静默启动，记录自己启动的进程 PID、真实创建时间、命令和用途，并在成功、失败、取消、超时后清理自己的临时资源。

下载 submit 模板，填写实际实现的完整 Git 提交、交付项、证据 SHA、真实测试、剩余范围。部分交付声明 partial；全部约定项完成才声明 full。占位的全零提交/SHA 必须替换。

```sh
curl --noproxy "*" http://example-server.example-tailnet.ts.net:18785/templates/submit.json -o submit.json
python client.py --profile <项目身份> prepare --task <任务ID> --action submit --payload submit.json --out <证据目录>/submit-request.json
python client.py --profile <项目身份> post --event <证据目录>/submit-request.json --receipt <证据目录>/submit-receipt.json
```

网络失败时保留 outbox，flush 重发原请求。409 时保留旧请求、重读范围后再决定，不能自动修改 revision 覆盖他人更新。回执应核对服务事件 ID、哈希和当前 submission。

## 5. 返修、验收与交接

返修后重读任务，修复并重提，在 addresses 中引用开放 finding ID。重提不会自动关闭问题，审核通过后才关闭。Agent 不自我验收或合并；负责人分别记录审核、合入、运行验收和归档。

若要使用浏览器，生成自己的项目一次性入口，放在 Git 外，不转发该入口：

```sh
python client.py --profile <项目身份> portal --out <私有目录>/project-entry.html
```

API 权限不代替操作系统文件隔离。其他项目的私有材料、身份或资源不属于自己的可读范围。

继续阅读：[负责人/继承 SE 操作](/help/owner)、[通用 API](/help/api)、[治理 API](/help/governance)、[模板目录](/help/templates)。
