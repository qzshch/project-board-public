# 分级治理、时间、测试与资产操作 API

产品4新增 operations schema 1，任务 API v2、规划 schema 2 保持兼容。所有接口以 `/api/projects/{project_id}` 为前缀，先鉴权再读取或返回内容。执行器不能获得其他项目或全局管理权限。

| 方法 | 相对路径 | 内容 |
|---|---|---|
| GET | /operations | 策略、范围评估、估算与时间、用例/套件/测试计划、执行器/运行、资产候选/反馈和派生报表 |
| GET | /operations/verify | 本项目追加操作链完整性 |
| POST | /operations | `{request_id,expected_revision,action,payload}` |

与任务写入使用同一项目SQLite的BEGIN IMMEDIATE。request_id绑定操作者与完整请求；相同请求重试返回原回执，冲突409后重读并由调用者决定。审计事件禁止更新/删除，包含前一哈希。界面和客户端都不能覆盖历史。

## 分级治理

policy={profile,reason}，profile=light/standard/strict，由owner/SE设置。新项目可通过创建请求governance_profile选择，默认standard。历史项目策略缺省未启用；明确采用后不可用自由文本取消门禁。项目档位是默认值，任务按实际风险分别核定。

assess={task,scope,level,flags,reason}，scope需当前任务scope_hash。风险可选public_interface/cross_module/persistent_data/permission/production/shared_asset/unknown_impact。后五项抬升为strict；公共接口/跨模块至少standard，任务及模块声明的共享接口也会自动抬升。影响事实仍需SE审查，系统不能静态发现未登记的事实。assess_package={package,scopes,level,flags,reason}可一次评估任务包全部当前范围，任一子任务不满足最低要求则整体拒绝；包整体等级取最高值，不强迫其他子任务重复同样证据。

light需项目简要上下文、当前风险评估、可核验的交付锚点与verification={method,summary,reason}，method=inspection/manual/automated/not_applicable。无需另造报告或新增自动用例；inspection与不适用须有实际结果和依据。证据可空。共享接口、硬前置、资源和权限约束照常检查。

standard/strict需已评审模块版本、当前范围test_plan以及实际通过的匹配输入运行。strict的手工验证与验收需独立于任务执行者，并保留证据。任务范围变化后评估/计划/运行均不能顶替新范围。

submit新增test_runs运行ID数组、verification和artifact={ref,sha256}。代码仍使用implementation_commit；research/collection/generation/documentation可使用真实产物锚点，不强制伪造Git实现提交，work.baseline可为artifact:sha256:64位摘要。非代码不必走代码merge；若记录代码合入仍需真实Git提交。

## 时间与估算

estimate={task,scope,low,likely,high,due,size,uncertainty,context,reason}，投入单位为分钟，0<low<=likely<=high；size=small/medium/large，uncertainty=low/medium/high；context写执行者/模型、工具、环境、复用条件。due为空或带时区ISO时间。每次重估追加版本，保留原始估算和依据。

time_change={task,scope,mode,phase,reason,rework}。mode=work/wait/pause/stop，phase=research/design/implementation/testing/review/integration/release/asset/governance，rework为布尔。服务端记录UTC时刻，同一执行者切换状态时关闭上一时段，避免把并行任务重复算为同一人的投入。返修是作业子集，不额外重复相加。任务负责人记录本人工作，经理可记录自己的审核协调。

time_close={session,reason}由经理关闭遗留时段；time_correct={session,seconds,reason}由经理校正已关闭时段，不能超过原自然区间，原值保留。time_complete={task,scope,summary}确认当前范围记录完整；存在未关闭时段时拒绝。

报表区分申报投入、等待、暂停、观察历时、阶段、返修、治理成本、逾期、估算偏差与完整性。历史未记录投入为null，不从领取到验收的间隔反推工时。P50/P80只对本项目同分类/规模/不确定性/执行背景、已完成且已确认记录完整的任务取样，至少5个其他样本，否则显示样本不足。硬前置路径只依据当前投入估算，不包含排他资源和审核排队；缺估算时明确标不完整。不同项目的基准须先脱敏提炼并按共享资产显式发布，不能跨项目自动索引私有数据。

## 用例、计划与运行

case的完整字段见test-case.json模板：不可变id/version、kind=manual/automated、priority=normal/critical、targets（task:ID、module:ID@version、contract:ID@version）、前置、输入、步骤、预期行为/反例、环境、资源。owner/SE或tester可编写。新增版本不覆盖旧版本；测试计划固定具体版本。

suite={id,version,commands,environment,resources,timeout_seconds,artifact_paths}，commands每项为{case,argv}，用例不可重复，超时1～900秒。经理批准套件，执行器工作站还须独立批准snapshot给出的manifest_hash；两者都通过才执行。argv数组无shell拼接，{python}为执行器解释器。artifact_paths仅允许导出根下的普通文件，真实SHA由执行器计算。

test_plan={task,scope,cases,reason}由经理选择当前范围用例；严格任务不能遗漏已登记的关键用例。系统提供按任务/模块/接口关联的建议，不能把未登记覆盖关系当作测试齐全。

runner={actor,environment,enabled,reason}。先签发项目普通身份，再由owner授予runner角色和此项授权。runner只可run_claim/run_heartbeat/run_finish，不能领取开发任务、改策略/用例或自行请求执行。工作站配置与身份文件放Git外，详见执行器指南。

run_request={tasks,scopes,suite,input_anchor,reason}，scopes映射必须逐一匹配当前scope_hash；input_anchor=git:40位提交。一轮可绑定多张任务，避免重复执行。经理、tester或任务负责人可请求；套件必须覆盖计划自动用例。

manual_run={tasks,scopes,input_anchor,reason,results,evidence,artifacts}。仅记录计划中的手动用例；results逐项含case/status/exit_code(null)/seconds/summary；不声称它是机器实跑。手动与自动运行可共同覆盖一个计划。input_anchor也可为sha256:64位产物。所有测试计划用例需通过，blocked/failed/cancelled/timeout不算通过。

run_claim={run,suite_hash}返回租约ID、固定套件与输入；资源锁检查其他运行及活跃任务。租约30秒，工作站每5秒续租；过期工作站不能回传成功。run_heartbeat={run,lease}返回cancel与expires。运行中取消保持资源直到执行器终止确认或租约到期；run_cancel={run,reason}不把任务失败改成成功。过期租约重新领取记录旧尝试；最终失败后重新请求产生新run，不覆盖旧失败。

run_finish={run,lease,status,results,artifacts,evidence,environment,summary}。逐用例结果必须覆盖套件命令，自动通过需真实零退出码；环境与逐例耗时留档。artifacts每项{path,sha256,location}。输入和任务范围不匹配的结果不得用于新交付。受信执行器凭据是执行回传信任边界，不是远程硬件证明；不得交给普通开发Agent冒充实跑。

## 资产沉淀

candidate为不可覆盖版本，含名称、类型、source_tasks/source_scopes、解决问题、适用/不适用范围、依赖和维护者。任务执行者可提议本人交付；后续提炼、核验与登记由经理处理。

candidate_refine固定验证input_anchor、artifact_path、真实sha256、许可、敏感性、位置、共享资格及提炼说明。candidate_validate引用已通过、匹配来源任务范围和输入锚点的运行；来源须已验收，产物路径和SHA必须出现在实际核验结果中。可共享资产必须有批准执行器的实跑；私人非代码资产可使用明确的手工检验声明。

candidate_promote将已验证候选与本项目治理中的私有资产版本在同一事务登记，不自动共享。采用分级策略后，publish必须有该提炼与验证来源，原许可/敏感性/受众和版本锁仍生效。测试用例、数据与工具可分别使用test_case/test_data/test_tool类型。

candidate_retire关闭候选后续推广，不会跨项目自动撤回已发布版本；已共享版本另走deprecate/withdraw并说明消费影响。asset_feedback绑定消费任务实际asset_locks，分别记录outcome、实测integration_minutes、可空的预估estimated_saved_minutes及issues。预估节省不当作实测收益，发布者不能通过反馈索引其他项目私有任务。

case_retire={ref,mode,reason}由经理管理用例生命周期，mode=deprecated/withdrawn。建议列表仅取最新活跃版本及适用的关键用例；旧计划不自动漂移。弃用禁止新计划选择，撤回还阻止执行/验收与资产验证使用该用例。任务绑定同时保存scope_hash和scope_version，即使修改后又恢复相同描述，也不能重新使用旧评估、估算完整性或运行结果。

工时基准：客户端export-benchmark --out <非C盘正式文件>导出至少5样本的聚合组，不含任务/人员ID；context仍须负责人脱敏审核。可作为methodology资产经提炼验证后发布。消费项目明确consume固定版本后，用benchmark_import={asset,document,reason}提交原始UTF-8 JSON文本；SHA必须逐字节匹配固定消费。新项目本地样本不足时可参考匹配的获批基准，不合并不同基准的分位数，显示来源与样本数；撤回版本不再用于新预测，旧估算仍留档。

member可选actor_kind=human/agent/unknown；经理配置后，时间时段固定当时分类，不以角色名推断人员/Agent。项目内同一执行者的时段不重叠；人/Agent投入、自动化运行时间分别统计。报告列出等待、返修与治理成本的可复盘方向，这些是改进线索，不是自动因果结论。


## 本地与server资料接手入口

缓存、调研、美术、归档、测试记录、日志、运行态和接手资料统一在“项目资产”的资源目录展示，原件继续留本地/server。任务详情可按任务进入，brief.resource_directory附带本角色可见的相关入口。核对机器、维护者、访问条件、内容版本/摘要与保留规则；目录登记不授予文件权限。详见[资源与接手手册](/help/resources)。
