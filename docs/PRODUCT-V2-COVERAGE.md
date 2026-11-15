# 工作空间 v2 旧能力承接

以下43组保留原真实渲染器、字段和操作；新导航只调整入口。行为门禁由现有回归继续核验，原型演示状态不作为实现结论。

| 分组 | 能力 | 保留内容 | 原实现 |
|---|---|---|---|
| 项目定义 | 背景与目标 | 背景、目标、非目标、约束、历史说明 | workspace.js / governance.py |
| 项目定义 | 材料与入口 | 材料原件、版本、SHA、入口、角色可见范围 | workspace.js / resources.js |
| 规划 | 模块完整定义 | 目标、路径、职责、非目标、输入输出、未知项、风险 | planning.js |
| 规划 | 规划调研与决定 | 规划前置调研、模块依赖、结论与来源任务 | planning.js / coordination.js |
| 规划 | 接口冻结与变更 | 版本、签名、单位、错误、事务、幂等、消费者、兼容 | workspace.js / governance.py |
| 规划 | 里程碑与阶段验证 | 目标、达成路径、进入条件、方法、阈值、环境、负责人、计划、实际证据 | planning.js |
| 规划 | 关联规划草案与批量审议 | 草案版本、来源引用、选择项、预览摘要、证据 | convergence.js |
| 规划 | 流程模板 | 不可变模板、参数、敏感性、消费版本 | convergence.js |
| 依赖图 | 多模块与任务规模 | 模块包含、完整节点计数、搜索、聚合、跨模块边界 | workspace.js / graph-layout.js |
| 依赖图 | 不同关系语义 | 硬前置、产物、接口、共享修改、排他资源、条件门、固定资产 | governance.py / coordination.py |
| 依赖图 | 真实解锁与估算 | 成果类型、审核状态、代码基线包含、缺失估算、范围版本 | dependencies.py / timing.py |
| 任务 | 任务包与原子任务 | 分类、角色、层次、交付物、历史映射、是否发布 | app.js / finishing.js |
| 任务 | 执行范围与冲突 | scope/version、基线、读写路径、输入输出、接口、资产、排他资源 | governance.py / store.py |
| 任务 | 候选与最终交付分离 | 成果、工作记录、结论、证据、待审条件、来源性质 | workflow.js / assurance.py |
| 协作 | 评论、阻塞和偏离 | 自主等待、SE停止、未读、回复、明确决定、执行者确认 | workflow.js |
| 协作 | 结构化验收 | 默认完成清单版本、稳定标准ID、精确输入、声明、逐项结论 | workflow.js / finishing.js |
| 协作 | 逐条发现与增量评审 | 严重/阻塞、锚点、修复或异议、修复提交、复核运行、历史继承 | workflow.js / coordination.js |
| 协作 | 回退工作流 | 任务/模块/代码/部署、影响快照、所需确认、执行器、证据 | workflow.js |
| 接续 | 尝试、工作区与租约 | 执行者、分支、机器、写路径、资源、租约、候选选择 | convergence.js |
| 接续 | 会话与上下文包 | 实际会话引用、前序、模型声明、检查点、固定版本、变化游标 | coordination.js / convergence.js |
| 治理 | 分级风险与批准规则 | 项目默认、当前scope风险、适用路径/类型、冻结引用、有效期、失效条件 | operations.js / convergence.js |
| 治理 | 角色与继承 | 成员、职责、Actor类型、可见范围、交接说明 | workspace.js / projects.py |
| 质量 | 完整用例库 | 版本、优先级、目标、前置、输入、步骤、预期、环境、退役 | operations.js / quality.py |
| 质量 | 实际测试运行 | 固定输入、scope、真实环境、逐例结果、退出码、时长、产物SHA | operations.js / quality.py |
| 质量 | 自动套件与执行器 | 本机批准摘要、命令白名单、超时、资源、产物路径、租约 | quality.py / quality_runner.py |
| 质量 | 外部条件与观察器 | CI/PR/人类/时间门、固定输入、TTL、授权、当前有效性 | coordination.js |
| Git | 绑定与首次接入 | 仓库ID、owner/name、授权状态、镜像、可信主机、同步回执 | git_tracking.py:mirror / GITHUB-GUIDE.md |
| Git | 提交与引用 | 分支/标签、搜索、作者、提交图、强推或改写告警 | git.js / github_tracker.py |
| Git | 文件与差异溯源 | 文件树、内容、比较、blame、任务/运行/资产关联 | git.js / git_reader.py |
| Git | 证据精确核验 | 仓库、基线、实现、测试、评审、合入、部署锚点 | workflow.py / git_tracking.py |
| 资产 | 本地/server目录 | 缓存、调研、美术、归档、测试记录、日志、运行态、机器、权限、保留 | resources.js / resources.py |
| 资产 | 实际资源核验 | 观察者授权、入口摘要、观察SHA、状态、TTL与失效原因 | coordination.js |
| 资产 | 沉淀与跨项目复用 | 候选、提炼、适用/不适用、许可/敏感性、验证、不可变版本、消费锁 | operations.js / learning.py |
| 资产 | 复用反馈与成本 | 实际接入工时、预估节省、问题、来源任务和消费者 | operations.js |
| 时间 | 时段与校正 | 投入/等待/暂停/返工、原因、阶段、人员/Agent、开始结束、校正依据 | operations.js / timing.py |
| 时间 | 估算与期限 | 低/中/高、规模、不确定性、工具环境、due、历史重估 | operations.js / timing.py |
| 时间 | 路径与校准 | 硬依赖估算路径、未知项、自动运行成本、等待、P50/P80、固定共享基准 | operations.js / timing.py |
| 改进 | 根因、WIP与流动 | 返工根因、首次返修率、评审排队、覆盖、WIP限制、改进假设与实效 | coordination.js |
| Agent | 人类与项目身份 | 独立人类登录、全项目读取、Agent Bearer边界、密码/会话 | human_auth.py / login.js |
| Agent | 接管诊断与最短路径 | 当前角色真实卡点、规划/基线/环境/材料、下一步 | readiness.py / finishing.js |
| Agent | 节点、运行时与受管会话 | 项目/根/角色/模型、本机策略、创建/原会话接续、未知结果与本机归属 | agent-console.js / orchestration.py |
| Agent | 有界委派 | 任务、当前输入、动作、受托者、期限、撤销、审计 | delegation.py / agent-console.js |
| 新需求 | 需求、缺陷与Token新模型 | 产品目标、版本变更、任务覆盖、缺陷复测、用量口径与覆盖 | product-workspace-v1/guide.html |
