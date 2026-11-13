# 增量治理API（产品3，治理schema 2）

现有API v2、旧/api/*→sampleapp、令牌、cookie、事件ID、SHA链及回执保持兼容。新增路由均位于 `/api/projects/{project_id}`，先进行同项目授权，再读取数据/产生ETag。没有新的全局搜索旁路。

| 方法/相对路径 | 行为 |
|---|---|
| GET /governance | 背景、材料、入口、里程碑、决策、成员、包映射、契约、资产、消费、图和并行阻塞 |
| GET /graph | 仅本项目nodes/graph/queue；hard/product/produces/coupling/contract/asset/exclusive分型 |
| GET /search?q=文字 | 仅检索已授权本项目治理对象 |
| GET /governance/export | 项目治理导出，不含凭据 |
| GET /governance/verify | 独立追加审计链校验 |
| GET /brief?task=ID | 当前原子范围的Agent说明，不含凭据 |
| POST /governance | `{request_id,expected_revision,action,payload}` |
| GET /shared | 已授权共享发布清单及本项目固定消费 |
| GET /shared/impact?ref=producer/id@version | 当前身份可见的消费者，不向提供项目SE泄露其他消费项目 |
| POST /shared | `{request_id,action,payload}`，由项目owner/SE审核 |

governance动作：knowledge、member、milestone、decision、package、handoff_propose、handoff_accept、contract_freeze、contract_propose、contract_confirm、contract_execute、asset。字段约束和可执行payload见templates与MANUAL。未知字段/类型拒绝，字符串/列表有界。角色owner/se可管理本项目；执行者不能自授管理角色；交接接受者和变更required确认人有对应单项权限。

shared动作：publish、consume、upgrade、deprecate、withdraw。版本不能覆盖，发布有显式audience和独立共享位置。消费变更与发布状态写入目录审计同一事务；敏感清单保留在本项目治理事件里。

task_spec新增可选work，包含category、role、inputs_known(bool)、inputs/outputs/contracts/assets/resources/couplings(string[])、baseline(Git40位)、acceptance。服务生成可选asset_locks(alias→{release,sha256,shared})固定每任务真实版本，项目alias升级不漂移旧任务；scope显式选择新锁才升级任务输入。不重写旧任务spec。新任务建议kind=atomic；任务包在governance.packages单独登记。旧任务仍使用原状态机，但队列显示历史/未知，不自动推断原子工作。

治理事件与任务写入共用一个项目库的BEGIN IMMEDIATE，防止不同任务并发穿透冲突检查；治理请求按actor/request_id幂等，expected_revision防覆盖。契约版本存不可变清单；提案冻结scope_hash与反向影响，确认者、迁移/测试和执行追加留痕。共享发布清单存目录库，受众在服务端过滤，私有源路径不进入发布载荷。所有SQLite库需停服务后作为整体备份或使用受控一致性流程，不能只复制运行中的主文件。

公开文档不包含项目快照、密钥或管理员入口。API授权不构成同Windows账户间的文件隔离。

## 渐进式规划（schema 2）

新增动作 planning_enable、module_plan、module_review、planning_decision、milestone_plan、milestone_review，仍使用同一个 POST /governance 请求封装、授权和追加审计。可填写 payload 见同名连字符模板。新建项目 POST /api/projects 可包含 knowledge，字段同 knowledge 动作；未填写时可以建立草稿，但不能派发执行。新项目默认 enforced；升级前项目默认 legacy，planning_enable 单向启用，不提供降级旁路。

GET /governance 新增 modules（id@version→不可变方案与追加reviews）、module_heads、planning_decisions、milestone_plans、milestone_heads、planning_policy、planning_health、module_readiness、milestone_readiness。readiness 含 scope 与阻塞；模块 ready 和阶段 passed 由当前输入推导，不由客户端直接设置。节点新增 planning 绑定，仍按项目权限返回。

module_plan 字段：id/version/title/parent/goal/scope/non_goals/owner/path/inputs/outputs/interfaces/no_interface_reason/risks/unknowns/planning_tasks/decisions/depends_on/acceptance/stage/evidence。parent 为模块ID，depends_on 为固定模块版本；均只允许本项目关系。stage=draft/research/design，ready 只能由评审推导。模块版本不可覆盖；未知项不为空、研究前置未验收/无确认结论、公共接口未冻结或跨模块产物无双方冻结边界时拒绝批准。

planning_decision 引用已验收研究/采集/文档任务及证据，固定研究任务 revision/scope/status；不能覆盖。研究任务重开或修订后原结论不再支持下游就绪，需重新研究、决策及方案版本。

work 新增可选 planning={module,purpose,question,no_interface_reason}；module 为固定 id@version，purpose=planning/execution。规划任务允许调研、采集、文档，必须明确问题；执行任务需绑定当前已批准版本并覆盖模块全部接口。无接口需显式依据。enforced 项目的无 work/无绑定任务不得通过 assign/claim；已绑定任务在 submit 时也校验当前规划，防止实施期间规划失效后直接交付。

milestone_plan 字段：id/version/goal/path/entry/modules/tasks/acceptance/method/threshold/environment/reviewer/due/risks；任务必须绑定关联模块版本。阶段可以关联模块的部分交付任务，由验收负责人核对阶段目标覆盖性。milestone_review 只允许指定项目 owner/SE（或root）评审；pass 前校验关联模块就绪、关联任务完整验收，仍须单独提交实际阶段检验的summary与evidence。不会因任务完成自动通过，也不把自由文本阈值当成自动执行的测试。

module_review 与 milestone_review 使用 {ref,scope,result,summary,evidence}。模块结果 approve/reject，阶段结果 pass/fail；必须引用最新 snapshot 给出的 scope，任务/上下文/接口/边界变化导致过期评审409。既有事件、版本及失败结论保留。快照和brief含规划与当前阻塞，不含凭据。版本升级不重写旧任务，旧版本任务由SE显式scope迁移。未登记的依赖/接口无法自动发现；“无共享接口”是需SE验证的声明。

接口影响分析同时覆盖模块接口引用、反向规划依赖与绑定任务；尚无执行任务时也纳入模块负责人确认。module_scopes固定受影响模块版本摘要，方案变化后旧影响确认失效。无模块影响时保持旧影响摘要格式兼容。


## 本地与server资料接手入口

缓存、调研、美术、归档、测试记录、日志、运行态和接手资料统一在“项目资产”的资源目录展示，原件继续留本地/server。任务详情可按任务进入，brief.resource_directory附带本角色可见的相关入口。核对机器、维护者、访问条件、内容版本/摘要与保留规则；目录登记不授予文件权限。详见[资源与接手手册](/help/resources)。
