# 验收流程与证据存放

本仓库只保存验收标准、测试代码和操作方法。实际测试结果、原始日志、截图、运行数据及失败记录保存在本地/server，不纳入Git。

- 行为回归：运行 `python tools/run_checks.py`，查看本地 `evidence/checks/<批次>/RESULT.json` 与逐项日志；失败和超时不能写成通过。
- 真实界面：`tools/git_ui_check.py` 验证提交图、差异、重命名历史、逐行溯源、表单幂等与角色边界；`tools/evolution_ui_check.py` 验证治理、时间、测试和资产。桌面/手机、浅深色均需实际渲染。
- 资源目录：`tools/resource_ui_check.py` 验证分类、任务筛选、登记/更新/停用、位置历史、丢回执原请求重发、角色过滤和项目切换；HTTP反例验证目录/搜索/导出/brief/历史及交接失效。只登记实际入口，文件现状未知不能写成可用。
- 协作交付：`tools/workflow_ui_check.py` 验证任务评论/阻塞、逐项声明审核、发现处置、Git实际核验、SE待办及回退确认闭环；`tests/task_board/test_workflow.py` 使用独立HTTP/Git状态，实做反向提交、精确输入反例、部署失败恢复、任务/模块回退、权限和历史链。实际本机配置和测试结果留本地/server，不随源码发布。
- server运行：一致性备份后切换已提交源码，实测回滚与重启。同步器先停再备份；保留全部任务、治理、操作和Git审计链及项目权限。
- 自动化结果须绑定当前任务范围、固定Git输入、实际退出码、逐用例结果和产物SHA。旧范围或旧输入结果只留历史，不替代新验收。
- 正式报告与原始证据按RUNBOOK归档server，包含跨项目信息的管理员包不得给普通Agent；身份与私有恢复包单独保管。

原2026-11-13实际验收记录已完整保存在本地 `archives/source-history-20261113/ACCEPTANCE-ORIGINAL.md`，server对应目录为 `<公告板server根>/local-archives/source-history-20261113`。Git忽略规则不清除已有历史；本轮不改写Git历史。


## 第二批验收

运行tests.task_board.test_coordination与tools/coordination_ui_check.py：需求分诊/原子转换/来源不冒充依赖、换会话游标与旧范围、消息重放与个人游标、实施计划风险裁剪、真实Git增量评审及旧锚点、根因改进/WIP、GitHub协议最新检查和过期/撤权、本机文件清单真实核验与权限过滤；桌面手机浅深色。完整suite后server独立同输入运行，真实交付仅登记本项目数据，演练独立fixture。归档源/手册/工具/失败和成功证据到server；实际结果不写入Git。


第三批：tools/convergence_ui_check.py验证四组面板操作、桌面/手机/浅深色、工作台和项目切换；tests/task_board/test_convergence.py验证原子预览/发布、精确引用失效、批准规则与实际Git反例、失联资源保留/旧回调、会话与候选选择、模板参数/敏感内容/跨项目及接手包来源。执行与截图仅存evidence或server。沿用前两批回归，正式环境只登记本次实际开发记录，不放演练fixture。


原范围收口用tests/task_board/test_finishing.py验证不同Actor接续、批量事务、入口/分页/权限、条件图、历史过滤、成果跟踪；tools/finishing_ui_check.py实做字段编辑和批量操作、角色边界及四种渲染。测试证据在本地evidence/finishing-20261114及对应server归档，不计旧通过为本轮实跑。
