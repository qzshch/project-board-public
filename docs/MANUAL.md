# 项目公告板操作手册

产品4的分级治理、时间、用例/运行与资产提炼使用独立追加操作链，接口与流程见[操作API](/help/operations)和[自动化执行器](/help/runner)。旧项目不会自动得到伪造的工时或测试；负责人显式采用分级策略。新项目可选择治理档位，轻量任务免重型模块和额外报告，高风险要求不能被裁剪。

对外协作入口：[管理阅读版](http://example-server.example-tailnet.ts.net:18785/help/admin)、[负责人/SE](http://example-server.example-tailnet.ts.net:18785/help/owner)、[执行Agent](http://example-server.example-tailnet.ts.net:18785/help/agent)、[模板](http://example-server.example-tailnet.ts.net:18785/help/templates)。这份完整手册含实例管理员私有操作，网页版本 `/help/operator` 需要管理员会话；/help/admin提供无须登录的协作阅读版。

适用于没有本会话历史的总负责人、继承SE和执行Agent。产品正式入口为 http://example-server.example-tailnet.ts.net:18785 。该入口属于Tailscale私网；传输可达不代表已获得项目权限。独立源码在 G:/project-board，运行状态在 server /srv/project-board/state。示例项目只是一个消费项目，project_id=sampleapp；公告板自身project_id=task-board。目录名、Codex项目ID和运行时project_id不是同一层。

## 1. 初始化与身份

新安装从空项目开始，不读取任何业务planning。Python 3.11+，生命周期管理依赖psutil，服务和Agent客户端使用标准库HTTP/SQLite。测试和浏览器验收的附加依赖见 requirements-dev.txt。

```powershell
cd G:/project-board
python -m venv G:/project-board-demo/.venv
G:/project-board-demo/.venv/Scripts/python.exe -m pip install --no-cache-dir -r requirements.txt
python -B -X utf8 tools/task_board.py --state G:/project-board-demo/state init --public-url http://127.0.0.1:24991 --port 24991
python -B -X utf8 tools/task_board.py --state G:/project-board-demo/state start
```

不要对当前生产状态重新init或另开serve。当前生产生命周期用server上的 `systemctl --user start|status|stop project-board.service`（详见RUNBOOK）；服务PID和真实创建时间在state/service.json。静默启动由工具实现；未知端口/进程所有权会拒绝操作。

全局操作者在server的已授权SSH会话创建生产项目，并签发项目负责人身份。前面的本机空安装示例仅为隔离安装说明，不是当前生产实例。先复制templates/project-init.json，填写项目ID、名称、背景简介；目标必须是新的ID。

```powershell
'/srv/project-board/.venv/bin/python' -B '<当前发布源码目录>/tools/new_project.py' --state '/srv/project-board/state' --definition '<已填写项目定义路径>' --owner lead-one --out '/srv/project-board/state/_private/roles/example-owner.json'
```

此工具只在本机读取全局管理凭据，输出项目负责人身份文件的**位置**。将该项目专属文件通过已授权私有渠道交给负责人。Windows客户端示例中的profile是经私有渠道保存到G盘的项目身份副本。它不能创建/枚举其他项目。管理员入口在server state/_private/operator.html，仅供全局操作者。项目负责人可用下面的portal命令获得自己的项目会话，不使用全局入口。

```powershell
python tools/task_board_client.py --profile G:/project-board-private/profiles/example-owner.json portal --out G:/project-board-private/profiles/example-owner.html
python tools/task_board_client.py --profile G:/project-board-private/profiles/example-owner.json read --endpoint /api/governance
```

另一台电脑先连同一Tailscale网络。无MagicDNS时加 `--connect-ip 100.64.0.10`，规范Host仍保持原域名。不要把profile中的project_id改成其他项目；服务端授权绑定令牌。签发或登记必须使用目标项目：浏览器Agent接入说明可下载通用client.py与API文档；项目邀请码仅能注册普通Agent。项目内 `/api/actors` 由owner/SE签发普通身份；随后用member动作授予研究、开发、文档、测试或SE职责。owner授予SE，SE不能提升自己或其他管理者。旧reviewer兼容其原项目审核职责。

## 2. 项目材料与里程碑

治理schema 2已加入“框架与规划”。新项目创建支持背景、目标、约束、历史材料与资源入口，默认启用规划门禁；既有项目仍为历史兼容模式，由负责人核定后显式启用。完整的模块/渐进式规划、研究结论、接口覆盖、里程碑检验流程见[负责人指南](/help/owner)第3节及[治理API](/help/governance)。先模块规划与研究、后原子任务派发；任务完成不自动通过阶段验收。

负责人在“项目概览→管理资料”维护背景、目标、非目标、约束、必读材料、入口、决策、里程碑。材料和入口包含标题、位置、版本、SHA256；更新追加治理事件，旧版本不会改写。新路径或材料标题随项目授权，不能拿别项目私有链接当共享材料。材料文件本身须经获授权通道交付，公告板不替代文件服务或操作系统权限。

CLI操作采用“读当前版本→冻结请求→发送原请求→保存回执”，模板是payload，不含凭据：

```powershell
python tools/task_board_client.py --profile <项目身份文件> prepare-governance --action knowledge --payload templates/knowledge.json --out <证据目录>/knowledge-request.json
python tools/task_board_client.py --profile <项目身份文件> request --endpoint /api/governance --payload <证据目录>/knowledge-request.json --out <证据目录>/knowledge-receipt.json
```

同一请求ID重试相同内容返回原回执。409意味着资料或范围已变化：保留旧请求，重新读后由负责人决定新请求，不自动覆盖。milestone的passed必须附验收证据；“计划已写好”不代表里程碑通过。decision记录变更依据、证据和操作者。

## 3. 原子任务、任务包与并行

任务是可独立验收的原子范围；任务包是组合/派发单元，在“依赖与并行”保留包→任务映射和旧来源。旧包没有足够细节就标未知，不把历史包的完成状态复制到新原子任务。

任务分类：research、collection、generation、infrastructure、frontend、backend、library、documentation、test、integration、release。分类与planned/active/submitted/changes_requested/accepted/merged/native_accepted等工作状态分开。每张任务卡还包括目标、交付项、可写相对路径、输入/输出、角色、Git基线、固定接口/资产版本、排他资源、共享修改耦合、验收条件。

用界面“新建范围”填写原子分类，或修改templates/task-create.json的完整create请求。task-create的expected_revision=0；不要将模板的示例request_id复用于另一张卡。

硬前置depends_on形成DAG，不能有环或引用不存在的任务。产物输入/输出、共享文件/接口/数据库、设备/端口排他分别建模。未知输入会阻止领取。领取和派发在任务库同一SQLite事务内重查前置验收、角色、写路径（含Windows大小写与目录前缀）、接口冻结、资产固定/撤回、资源和耦合冲突。两个不同任务争同一写目录也只有一个能领取。活跃/待审/返修/部分交付仍持有冲突范围；由SE通过正式范围调整/验收处理，不根据空闲CPU释放资源。

界面tab分开：任务列表/交付与验收队列仅在“任务与验收”；其他tab显示自己的内容。“依赖与并行”实际绘制全部已授权任务及已记录关系：实线箭头为硬前置，虚线为任务包/任务族层级，两者不等价。可按任务族筛选、定位任务、缩放与滚动，点击节点查看详情，不截断为40项。原子分类未知的历史节点仍展示，不编造未记录依赖。辅助检查清单默认折叠。“依赖与并行”里的队列是当前建议；领取时会再次检查。原有历史任务仍保留兼容状态机，但不会被新图自动认定为已核定原子任务。图只返回当前项目节点，不用浏览器隐藏代替权限控制。board只管理协作约定，不能阻止同Windows账号下的任意磁盘写入；需要更强隔离时应分别配置OS账户/容器/目录权限。

## 4. 冻结接口与变更影响

在“接口冻结”登记不可变id@version，填写拥有者、签名/字段、单位、错误、事务、幂等、来源、生产者/消费者、兼容窗口及证据。不能覆盖冻结版本；新版本先单独冻结。任务固定版本，不能用latest。

破坏性切换走contract_propose，指定旧/新版本、迁移与测试清单。服务计算直接任务、反向硬依赖、产物和共享修改/路径关联范围，冻结受影响scope_hash与负责人。contract_confirm必须由接口拥有者、项目owner/SE及受影响任务负责人逐一确认，确认使用当前impact_hash。范围有变化须重新提案。全部确认后contract_execute才退役旧版本；现有任务scope改到新版本还会检查已执行提案。独立范围可继续，不为一处变更停掉整个项目。

## 5. 私有资产与共享版本

“项目资产→登记私有资产”默认保留在本项目。带不可变版本、来源、许可、敏感性、内容SHA、位置、负责人和验收证据。只有shareable=true、sensitivity=public、许可明确且类型为skill/methodology/infrastructure的通用资产可以被显式审核发布。游戏专属内容、账号、密钥及未知许可不可发布为通用资产。

发布时另填共享受众（明确项目ID或*）、**专门审核的共享位置**、审核依据和证据。共享清单不携带原私有路径、私有任务、审核证据路径或其他消费项目身份。不可变版本由producer/id@version标识。

consume把本项目alias固定到一个发布版本和哈希；提供方发布v2不改变alias原来的v1。任务创建/范围冻结时，服务还生成work.asset_locks，将每个alias锁到实际发布版本和SHA。消费项目后来主动升级alias，既有任务仍使用原锁，brief返回原版本。任务要升级输入，须由SE显式scope提交当前获批的新asset_locks并重新派发。历史未记录锁的范围标未知，不用当前alias倒推历史。withdraw检查任务自己的锁，不因alias升级而绕过。upgrade由消费项目负责人选择、批准并附消费验证。deprecate保留已有引用并提示迁移；withdraw阻止新增消费和依赖该版本的新任务领取，保留历史引用/哈希供追溯。撤回不能恢复，需发布新版本。影响查询仅返回自己有权查看的消费者；全局操作者可以执行跨项目协调，提供方SE不会因生产者身份获知其他项目私有任务。

资产CLI也先冻结请求ID：

```powershell
python tools/task_board_client.py --profile <项目身份文件> prepare-shared --action consume --payload templates/asset-consume.json --out <证据目录>/consume-request.json
python tools/task_board_client.py --profile <项目身份文件> request --endpoint /api/shared --payload <证据目录>/consume-request.json --out <证据目录>/consume-receipt.json
```

## 6. 给执行Agent的说明与任务闭环

负责人应按templates/agent-brief.md交付**项目专属**说明。可从 `/api/projects/{project_id}/brief?task={task_id}` 或客户端 `read --endpoint /api/brief?task=...` 生成当前任务数据：API base、project_id、角色、可读材料和版本、基线与scope_hash、输入/输出、允许目录、接口/资产版本、排他资源、验收与回执、开放返修项。它不含凭据。任务尚未核定work信息时服务拒绝生成派发包。

Agent收到自己的profile后：

1. 读取任务与brief，核对project_id、角色、允许目录、基线、输入SHA、接口/资产固定版本和验收。拿不到输入/版本就scope_proposal，不编造。
2. 用客户端prepare生成claim事件，再post。prepare会读revision/scope_version并固定request_id。等待领取成功回执后执行。
3. 只在允许目录实现。公共入口/数据库/接口/设备变更先提案，不能顺手修改其他任务范围。保留来源和失败证据；临时进程静默启动并登记身份、finally清理。
4. 实际运行行为与反例测试；冻结40位Git实现提交和证据SHA。提交说明覆盖实际deliverable_ids、full或partial、tests、remaining及返修addresses。只完成部分必须声明partial。
5. post保存服务回执。网络失败原请求留在outbox；flush重发原ID。冲突不自动重定基线。通过receipt查询核对服务事件ID/哈希和current_submission_id。
6. SE审核accept或request_changes。返修保留原提交，Agent重提引用open finding IDs；重提本身不关闭问题，accept之后才关闭。
7. SE分别记录merge和native运行验收，引用当前submission及已合入完整Git提交。通用native表示本产品实际运行验收，不要求游戏客户端。不能拿提交声明当合入或运行结论。
8. 归档来源、固定输入、实现提交、测试、证据/回执/返修记录和哈希清单。凭据、会话、一次性入口和管理员跨项目快照不得放入普通Agent包或Git。

```powershell
python tools/task_board_client.py --profile <项目身份文件> prepare --task impl/label --action claim --payload templates/claim.json --out <证据目录>/claim-request.json
python tools/task_board_client.py --profile <项目身份文件> post --event <证据目录>/claim-request.json --receipt <证据目录>/claim-receipt.json
python tools/task_board_client.py --profile <项目身份文件> prepare --task impl/label --action submit --payload templates/submit.json --out <证据目录>/submit-request.json
python tools/task_board_client.py --profile <项目身份文件> post --event <证据目录>/submit-request.json --receipt <证据目录>/submit-receipt.json
```

通用交付门禁tools/check_delivery.py对比当前task/服务record/receipt/manifest和真实Git changed_files：项目、执行者、提交ID/哈希、scope_version/hash、基线、接口/资产版本与目录都须匹配。游戏专项foundation门禁仍留在原业务项目；通用框架不导入它。门禁不代替人工代码审核或OS隔离。

## 7. 实时调整与继承SE

执行中先scope_proposal追加说明，由SE计算影响后scope追加新范围版本。旧事件不删；旧scope_version提交会409，Agent必须读新卡后再决定是否领取。目录/接口公共耦合不能通过改名消失。

owner先签发项目专属SE身份并member登记职责；handoff_propose记录未决风险、必读版本、活跃任务/排他范围及冻结接口摘要。继承SE读完后handoff_accept引用scope摘要，服务重查任务/契约是否变化；不一致要重新交接。接受后原owner降为viewer、管理权限撤销，新SE成为owner。需要完全移除项目读取时再由新owner或全局操作者revoke原身份，保留审计。不要将全局admin.json当继承凭据。

## 8. 验收、迁移与归档

本轮验收和真实演练入口见docs/ACCEPTANCE.md。可复跑tools/run_checks.py、tools/ui_check.py；都使用独立fixture/端口并保留失败证据，不读取游戏资源。真实server演练脚本只通过stdin收到自己项目的角色凭据，远端临时文件finally清理。

迁移/回滚和故障恢复见docs/RUNBOOK.md。正式归档保留在server管理员目录；Agent只接收本项目材料/回执与通用client/API。私有恢复备份仅交付位置，不放Git或普通包。


资源目录schema1复用项目治理追加链，无文件搬迁或独立扫描服务。恢复须同时保留治理库和实际本地/server原件，登记不是原件备份。常规项目目录变化使待接受的SE交接失效；operator-专用实例入口仍仅全局管理员可读，不随项目owner转交。公开手册/help/resources可给其他Agent，实际目录及历史先按项目、再按角色过滤。自动运行入口来自原回执，文件现状未知，不能宣称面板已经复核文件或赋予OS权限。
