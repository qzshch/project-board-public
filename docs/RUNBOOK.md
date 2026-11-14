# 部署、恢复与归档

当前正式服务部署在 **server**，与PC开关机无关。独立开发仓库仍在G:/project-board。

- 正式入口：http://example-server.example-tailnet.ts.net:18785（Tailscale私网）；无MagicDNS时客户端用 `--connect-ip 100.64.0.10` 保持规范Host。
- server根目录：`/srv/project-board`。
- 代码使用不可变 `releases/<版本>/source`，当前目录与提交以 `state/connection.json` 的 `code_root` / `code_commit` 为准；运行状态：`state`；独立Python环境：`.venv`。
- 正式服务：用户级systemd `project-board.service`，已enable，用户Linger=yes，退出失败会自动重启。
- server Tailscale Serve仅管理18785→server 127.0.0.1:24710。PC原18781/18783不变，PC公告板应用和原18785入口已停用。
- 私有管理入口在server `state/_private/operator.html`。普通Agent只获得自己的项目身份文件。

在server的已授权SSH会话执行：

```sh
systemctl --user status project-board.service
systemctl --user restart project-board.service
journalctl --user -u project-board.service --no-pager -n 50
BOARD_CODE_ROOT=$('/srv/project-board/.venv/bin/python' -c "import json; print(json.load(open('/srv/project-board/state/connection.json'))['code_root'])")
'/srv/project-board/.venv/bin/python' -B "$BOARD_CODE_ROOT/tools/task_board.py" --state '/srv/project-board/state' --project task-board verify
```

生成新的私有管理入口时，将最后的 `verify` 改为 `operator`，只输出位置。项目负责人用自己的profile生成portal；不要给执行Agent全局入口。已有客户端保留原token与project_id，将profile.url改为server正式地址即可；不重新注册、不扩大权限。

PC运行数据已迁出，原state只保留MIGRATED_TO.json指针。PC端start/init/project操作拒绝重建旧实例。后续部署必须按本段server路径执行，不能再启动PC主服务。

本次server迁移、快速重启、图与tab验收、演练清理证据见 `evidence/nas-ui-20261113`。保留真实项目的任务/事件ID、历史链及权限；演练项目、身份、当前私有资产、共享可见版本和生成文件已移除。只留不可变历史审计和清理摘要，不能重用退役项目/资产ID。

下面是前一轮PC拆离迁移的历史恢复记录，不是当前部署路径：

本次从旧目录实际迁移的证据在 evidence/migration/20261113/MIGRATION.json。完整私有一致性恢复备份在同目录 `_private/recovery` 和 `_private/final-source`。这些包含身份库/配置，只交付位置。旧源状态 G:/sampleapp/offline/state/task-board 已停止，保留为迁移时恢复点；不是现用数据库。禁止同时对两份状态写入或把旧实例当当前入口使用。

迁移实跑：核对旧PID/创建时间/命令 → 停旧服务 → 每库SQLite backup与完整设置备份 → 新目录只读启动并核对head/回执 → 停新服务 → 原代码原状态实际回滚启动并核对 → 再停原服务 → 重新一致性复制 → 新目录正式启动 → 完整重启读回。原dhy330任务/335事件及head保持不变。切换工具不重置Tailscale Serve；仅核对并管理18785根handler，18781/18783保留。

故障恢复：先status并按真实身份关闭当前实例；备份当前**完整**状态（含所有项目库、目录库、管理员库、治理事件与共享发布）。选择和数据库schema匹配的代码版本，在新的非C盘目录恢复。先使用独立端口/不发布的测试实例验证所有项目head、治理链、目录链、原回执及权限。确认后停测试/当前服务，再做有界URL切换。已有新写入后不能直接恢复迁移日旧快照而丢弃新事件；必须保留当前恢复包并决定前向修复/事件恢复。禁止覆盖正在运行的SQLite文件，禁止按python/node名称批量终止。

tools/migrate.py用于首次停服迁移，目标须不存在，执行前明确source/target/old-cli/evidence。它不是每日同步工具，不应在当前生产状态重复执行。失败时关闭自己确切的新实例并恢复旧服务，保留失败记录。

发布：独立private远端 example-owner/project-board。源码与手册不含运行状态；requirements.txt用于生产依赖。回归运行tools/run_checks.py；GUI检查tools/ui_check.py需要本机Edge和requirements-dev.txt。进程、临时目录与清理记录保留到证据目录，正式截图/测试结果不作为临时文件删除。

规划治理升级（schema 2）：增加的治理字段仍位于既有项目治理事件，不迁移/重写任务链或身份库。新项目默认规划门禁，旧项目按缺省legacy读取；禁止为了展示新界面给真实历史任务伪造模块/研究结论。使用 tools/planning_ui_check.py 做隔离端到端表单与桌面/手机浅深色检查。正式部署停server服务后做完整一致性备份与源码检查点，切换源码，核对原项目head/治理head/凭据摘要，实测源码回滚、再切回新版本并重启读回。演练只用独立fixture状态和端口，不在生产创建演练项目。

server归档：`//example-owner/Project Workspace/project-board-archive/20261113/PROJECT-BOARD-<commit>`。源码、手册、通用Agent kit、脱敏本轮结果与SHA清单为正式交付物；管理员包可包含跨项目head/事件审计，必须放管理员目录，不发给普通Agent。私有恢复包单独留在受控私有位置。SMB失败先判断网络/认证/路径；已验证SSH example-owner@192.0.2.10、密钥位置由credential_locations取得，可作为替代归档通道。两者失败保留本机校验包与待归档记录继续开发。

产品4：操作记录在每项目operations_events追加链中，与任务写入同事务串行；备份需包括该表。项目自动化执行器为独立项目身份与服务，使用quality_runner.py、受控工作仓库及本机批准套件摘要，不运行全局管理员身份。执行器存储按runner-config配置，保留正式output、清理scratch。主服务部署前保留一致性状态与源码检查点，验证旧版本回滚后再恢复候选，校验任务/治理/操作链。旧版源码不支持operations，但不应删除新表。

执行器运行依赖：server 的 Git 使用项目内 `.venv/bin/git` 启动器，实际文件在 `runtime/git/package`；不依赖系统 Git。安装包按 Debian 包索引 SHA256 校验，记录在 server `evidence/git-prerequisite/RESULT.json`。预检和质量服务显式将项目 `.venv/bin` 加入 PATH；固定提交从已校验 bundle 导入项目专用 bare 仓库。该运行依赖和一致性备份均须随实例恢复保留。

质量服务为用户级 `project-board-quality.service`，仅本项目 runner 身份，配置在 `state/_private/runner/task-board.json`，身份在 `state/_private/roles/board-quality.json`；不将文件内容放进协作说明。使用 `systemctl --user status/restart project-board-quality.service` 管理；日志用 `journalctl --user -u project-board-quality.service` 查看。固定输入仓库、临时导出和正式结果分别在 `runners/task-board/repository`、`scratch`、`output`。没有任务时保持等待；停止/重启前核对正在执行与租约，服务留足45秒完成取消和清理。共享资源锁目录不得作为临时文件清理。

GitHub只读服务按项目使用 `project-board-git-<project>.service`，运行 `tools/github_tracker.py --watch`。配置和部署密钥位于状态根 `_private`，镜像在 `state/git-mirrors`，都不进入源码或普通Agent包。每仓库独立只读部署密钥，固定GitHub SSH主机公钥在 `_private/github-known-hosts`（由官方HTTPS API meta核对获取）。服务有界查询/拉取、项目锁、失败保留与非快进记录。发布停服一致性备份时一并停止这些同步器，恢复后核对所有Git链并启动原已启用服务；禁止复制正在同步的镜像作一致性恢复点。详见[GitHub接入](/help/github)。


资源目录schema1复用项目治理追加链，无文件搬迁或独立扫描服务。恢复须同时保留治理库和实际本地/server原件，登记不是原件备份。常规项目目录变化使待接受的SE交接失效；operator-专用实例入口仍仅全局管理员可读，不随项目owner转交。公开手册/help/resources可给其他Agent，实际目录及历史先按项目、再按角色过滤。自动运行入口来自原回执，文件现状未知，不能宣称面板已经复核文件或赋予OS权限。


## 任务协作、逐项验收与回退

评论、阻塞求助和计划偏离在任务内登记，SE正式决定后由执行者确认恢复；评论不改变范围或释放排他资源。结构化验收固定范围与精确输入，执行者声明、审核者逐项复核；Git祖先关系不替代最终提交测试。SE待办集中展示协作、交付与回退事项。回退先冻结影响并逐人确认，任务/模块追加新版本，代码/部署使用单独批准的项目执行器，不覆盖历史或给予实例全局权限。详见[协作与回退操作手册](/help/workflow)。


## 第二批协调能力升级

新增coordination_schema1，沿用operations追加链与原项目SQLite事务；不重写旧事件，不给历史任务补造计划/检查点/实际核验。新增观察器为有限本机工具，需项目runner独立授权及本机准确配置批准，不自动增加常驻服务。部署前跑完整回归、第二批GUI及Git边界；停止三个既有服务后建立一致性备份，按原流程切换/实际源码回滚/恢复候选/重启，校验所有原四链固定前缀。API及公开手册、独立工具包可达性同时验收。
