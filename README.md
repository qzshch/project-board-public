# 项目公告板

独立的多项目协作管理工具。示例项目是其第一个使用项目，不是本产品的父项目。

运行代码、空项目初始化、部署状态均在本项目；不依赖游戏planning/foundation或资源。支持项目知识与角色交接、分类原子任务/任务包映射、依赖与耦合冲突、版本冻结和影响确认、私有资产与不可变共享版本。旧任务/事件/权限与回执保持兼容。

入口与数据：`http://example-server.example-tailnet.ts.net:18785`；服务与状态均在server，PC不再运行公告板。server状态为`/srv/project-board/state`，用户级systemd管理。独立private远端：[example-owner/project-board](https://github.com/example-owner/project-board)。运行身份/管理入口不进Git，只交付位置。

从 [操作手册](docs/MANUAL.md) 开始；[治理API](docs/API-GOVERNANCE.md)、[部署/回滚](docs/RUNBOOK.md)、[验收台账](docs/ACCEPTANCE.md)、[可复制模板](templates/) 提供完整执行路径。用户原文和移交基线保留在docs；legacy-v2仅为历史参考，旧位置测试不计本轮。

```powershell
python -B -X utf8 tools/task_board.py status  # PC显示已迁移指针；server服务用systemctl --user status project-board.service
python -B -X utf8 tools/task_board_client.py --profile <本机项目专属身份> read --endpoint /api/verify
python -B -X utf8 tools/run_checks.py
```

所有新项目、构建、测试和缓存放C盘之外。正式归档到server；临时进程静默并按真实身份清理。公告板权限管理不替代操作系统账户/文件隔离。
