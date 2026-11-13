# 部署、恢复与归档

当前产品目录 G:/project-board；状态 G:/project-board/state；私有入口 state/_private/operator.html。入口URL不变： http://DEVELOPMENT-HOST.example-tailnet.ts.net:18785 → 127.0.0.1:24710。服务由tools/task_board.py静默管理，运行记录含PID、真实创建时间、完整命令与用途。仅用户要求持续运行的正式服务保留。

```powershell
python -B -X utf8 tools/task_board.py status
python -B -X utf8 tools/task_board.py --project sampleapp verify
python -B -X utf8 tools/task_board.py --project task-board verify
python -B -X utf8 tools/task_board.py stop
python -B -X utf8 tools/task_board.py start
python -B -X utf8 tools/task_board.py --project task-board operator
```

最后一条生成新的私有一次性管理入口，只输出位置。既有入口可能已使用/过期。项目负责人使用项目profile生成portal，不能拿全局入口给Agent。

本次从旧目录实际迁移的证据在 evidence/migration/20261113/MIGRATION.json。完整私有一致性恢复备份在同目录 `_private/recovery` 和 `_private/final-source`。这些包含身份库/配置，只交付位置。旧源状态 G:/sampleapp/offline/state/task-board 已停止，保留为迁移时恢复点；不是现用数据库。禁止同时对两份状态写入或把旧实例当当前入口使用。

迁移实跑：核对旧PID/创建时间/命令 → 停旧服务 → 每库SQLite backup与完整设置备份 → 新目录只读启动并核对head/回执 → 停新服务 → 原代码原状态实际回滚启动并核对 → 再停原服务 → 重新一致性复制 → 新目录正式启动 → 完整重启读回。原dhy330任务/335事件及head保持不变。切换工具不重置Tailscale Serve；仅核对并管理18785根handler，18781/18783保留。

故障恢复：先status并按真实身份关闭当前实例；备份当前**完整**状态（含所有项目库、目录库、管理员库、治理事件与共享发布）。选择和数据库schema匹配的代码版本，在新的非C盘目录恢复。先使用独立端口/不发布的测试实例验证所有项目head、治理链、目录链、原回执及权限。确认后停测试/当前服务，再做有界URL切换。已有新写入后不能直接恢复迁移日旧快照而丢弃新事件；必须保留当前恢复包并决定前向修复/事件恢复。禁止覆盖正在运行的SQLite文件，禁止按python/node名称批量终止。

tools/migrate.py用于首次停服迁移，目标须不存在，执行前明确source/target/old-cli/evidence。它不是每日同步工具，不应在当前生产状态重复执行。失败时关闭自己确切的新实例并恢复旧服务，保留失败记录。

发布：独立private远端 example-owner/project-board。源码与手册不含运行状态；requirements.txt用于生产依赖。回归运行tools/run_checks.py；GUI检查tools/ui_check.py需要本机Edge和requirements-dev.txt。进程、临时目录与清理记录保留到证据目录，正式截图/测试结果不作为临时文件删除。

server归档：`//example-owner/Project Workspace/project-board-archive/20261113/PROJECT-BOARD-<commit>`。源码、手册、通用Agent kit、脱敏本轮结果与SHA清单为正式交付物；管理员包可包含跨项目head/事件审计，必须放管理员目录，不发给普通Agent。私有恢复包单独留在受控私有位置。SMB失败先判断网络/认证/路径；已验证SSH example-owner@192.0.2.10、密钥位置由credential_locations取得，可作为替代归档通道。两者失败保留本机校验包与待归档记录继续开发。
