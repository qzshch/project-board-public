# 新独立会话入口

当前正式服务已部署到server：http://example-server.example-tailnet.ts.net:18785；PC仅为开发仓库，旧PC运行入口已停用。原有演练工作区已从线上清理。后续接手先读 [操作手册](docs/MANUAL.md)、[验收台账](docs/ACCEPTANCE.md) 和 [运行/回滚](docs/RUNBOOK.md)；下文保留最初移交背景，不能当作当前部署状态。

用户要求把公告板作为独立产品，另开会话完成五项升级。本仓库是专门为该会话准备的G盘独立Git仓库，不是示例项目worktree。

先读：

1. [用户原文](docs/USER-REQUEST-20261113.md)。
2. [交接上下文、已验与未实现范围](docs/HANDOFF-20261113.md)。
3. AGENTS.md。
4. legacy-v2/SOURCE-MANIFEST.json及相邻源码，仅作为拆离参考。

你接手的第一步是核对交接锚点，建立本项目里程碑与原子任务，并完成源代码/运行数据从示例项目项目拆离；随后连续推进其余升级和完整手册。不要假定复制了参考代码就已解耦，也不要重新从头调查已通过的认证/事件机制。

当前线上入口：http://DEVELOPMENT-HOST.example-tailnet.ts.net:18785 。公告板自身已存在的运行时project_id是 `task-board`；独立文件夹叫 `project-board`，两者不是同一层ID。示例项目project_id是 `sampleapp`，保持不变。应用中的新会话/项目ID由Codex创建，不等同运行时project_id。

线上在你完成可回滚迁移前继续由旧目录提供服务。本移交没有复制运行数据库、密钥或私有恢复检查点。授权工具在真正需要迁移/管理时按交接中的**位置**使用，不输出原值。
