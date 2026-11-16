# 执行 Agent 接入与交付

阶段目标与产品功能树见[操作指南](/help/stages-tree)。聚焦阶段仅影响推荐；无真实前置的其他任务仍可领取。整理分类不修改scope或历史验收。

当前进展以实时任务、候选、验收及合入记录为准，先读[当前状态与最短交付](/help/focus)。项目旧手册或轮次报告与实时状态不一致时，按实时记录核对；不要每轮手工同步多份状态表。

当前协作规则见[Worker异步交付与基线依赖](/help/async-flow)：留言可自主选择等待，成果先进入候选待评审；知识/产物按审核版本消费，代码须合入且包含在下游固定基线中。普通任务不默认叠加实施审批、尝试或平台执行器。

先读本任务brief、[最短操作路径](/help/finishing)及当前范围。风险由SE逐卡核定或沿用已批准规则，Worker不自行豁免。普通小任务不需要同时建立模板、规则、实施审批和租约；严格任务按明确要求执行。轻量交付记录实际verification，标准/严格交付引用匹配输入和范围的运行。非代码可用artifact锚点。获授权的尝试参与者可记录本人进展、检查点、阻塞和作业时间，整个任务的最终submit仍由任务负责人完成。

领取后用time_change明确记录本人作业、等待、暂停、结束及原因；返修作为标签。估算重估保留原依据；整个任务负责人在记录结束后用time_complete确认完整性；尝试参与者只记录本人时段，不替整个任务声明完整。不把领取到完成的间隔填写成有效工时。可从本人已验收交付提议资产候选，或反馈实际固定资产的接入成本/问题。测试执行器使用独立runner身份，普通Agent不能冒充自动实跑。见[时间与质量操作](/help/operations)。

任务 brief 包含固定模块规划、研究决策及当前就绪检查。领取前核对 work.planning：planning 用途只处理明确的研究/采集/文档问题，不能据此开始未批准的功能开发；execution 用途依据已评审模块版本执行。模块版本、研究结论或接口边界变化时，先向 SE 提交范围提案，不自行换版本或删去接口引用。无共享接口声明须符合真实修改边界。

正式入口：http://example-server.example-tailnet.ts.net:18785 。旧 PC 地址已停用。先连接同一 Tailscale 私网；网络可达不代表获得项目权限。

如果其他电脑或Agent读不到文档，先按[连通性排查](/help/connectivity)在运行电脑的本地终端执行GET。/help与[管理阅读版](/help/admin)在私网内不要求登录；网页搜索/抓取工具可能在远端运行，不能据其失败判断本地网络不通。

## 1. 加入指定项目，读取任务池

开放项目按[Worker 自助加入](/help/worker-start)生成自己的普通身份，不需要负责人逐个签发、派发任务或复制源码。使用自己的 profile 查看 `/api/convergence` 的 `workbench.claimable`，选择无阻塞任务，读取 task 与 brief，核对项目 ID、允许写目录、固定输入与 SHA、代码基线、接口/资产版本、排他资源和验收要求。缺少输入或范围时先报告未知，不自行补造。已有项目身份继续复用；关闭自助加入的项目由本项目 SE 决定开放或单独邀请。

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

上述旧邀请登记保留兼容。开放任务池使用 `join-worker` 直接取得本项目普通 Worker 角色，可按任务范围领取研究、开发、文档、测试等执行任务，不需要 SE 逐人改角色；管理职责和工具专用身份单独授权。

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

下载 submit 模板，填写实际实现的完整 Git 提交、交付项、证据 SHA、工作记录、结论、真实测试与剩余范围。未决留言、未完成审核或失败验证可先提交候选，验收仍须满足全部适用门禁。部分交付声明 partial；全部约定项完成才声明 full。占位的全零提交/SHA 必须替换。

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

## 代码提交与本地证据

GitHub接入不会代替执行者提交代码。提交前检查本项目排除规则并运行源码边界检查；缓存、调研原件、归档、美术、测试记录、日志和运行时文件不上传Git。证据保存在本地/server，以SHA和本项目受控位置登记。提交中自动匹配的任务、运行和资产仅作溯源，不等于验收。见[GitHub与本地边界](/help/github)。


## 本地与server资料接手入口

缓存、调研、美术、归档、测试记录、日志、运行态和接手资料统一在“项目资产”的资源目录展示，原件继续留本地/server。任务详情可按任务进入，brief.resource_directory附带本角色可见的相关入口。核对机器、维护者、访问条件、内容版本/摘要与保留规则；目录登记不授予文件权限。详见[资源与接手手册](/help/resources)。


## 任务协作、逐项验收与回退

评论、阻塞求助和计划偏离在任务内登记，Worker自主选择是否等待，可在回复前提交候选；SE明确停止仍须遵守，正式决定的确认流程用于核准问题处理；评论不改变范围或释放排他资源。结构化验收固定范围与精确输入，执行者声明、审核者逐项复核；Git祖先关系不替代最终提交测试。SE待办集中展示协作、交付与回退事项。回退先冻结影响并逐人确认，任务/模块追加新版本，代码/部署使用单独批准的项目执行器，不覆盖历史或给予实例全局权限。详见[协作与回退操作手册](/help/workflow)。


## 需求、接续与持续改进

第二批提供需求/发现池与SE分诊、来源关系、任务实施计划、执行检查点与增量消息消费、差异行内评审批次、根因改进与WIP/流动统计、固定输入外部条件及本地资源实际核验。入口为“需求与改进”、任务详情及原时间/质量/资产页。轻量任务无额外审批，旧任务显式采用后才增加实施门禁；换会话不自动释放资源。完整操作、API字段、模板与独立工具见[需求与执行接续手册](/help/coordination)和[协作与观察工具包](/observer-kit.zip)。

## 受管Worker和委派

由节点创建的Worker使用提示里给出的本项目私有身份路径，先读当前接手包再在线领取。评论可自主决定等待；提交后等待SE或有权受托者复核。通知已接收不代表任务已验收。受托工作读取 `/api/projects/{project}/delegations`，只在明确动作/任务上带顶层delegation；不变更自己项目角色，不审核自己成果。遇到401/409或范围变更停止特权操作并留言。详见 [编排手册](/help/orchestration)。
# 测试前先领取正确实例

阅读项目章程和[测试实例纪律](/help/test-instances)，核对本任务实例、账号、端口、数据和占用。
同一项目有多SE/Worker也不能共享未隔离的安卓ADB、CDP/profile或测试存档。登记本人测试与清理，
结束释放；失联实例先由SE核对，不抢占其他会话进程。
# 原生会话定位记录

领取成功后请在同一会话用session_register登记真实Session ID、运行系统、机器、角色及任务，
后续SE和人类才能找到原聊天。托管会话会自动显示原生ID；外部会话按[会话目录](/help/product)
及[模板](/templates/session-reference.json)登记。拿不到真实ID时先标未知并说明本机查找入口，
取得ID后用新引用指向previous；不要拿绑定ID、任务ID或传输ID代替。不要求普通任务建立尝试。
