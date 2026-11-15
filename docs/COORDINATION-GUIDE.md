# 第二批：需求、执行接续、评审与改进

当前协作规则见[Worker异步交付与基线依赖](/help/async-flow)：留言可自主选择等待，成果先进入候选待评审；知识/产物按审核版本消费，代码须合入且包含在下游固定基线中。普通任务不默认叠加实施审批、尝试或平台执行器。

正式服务在server。入口“需求与改进”负责尚未成为任务的新问题；原“SE待办与协作”负责当前协作与待办。任务详情增加“实施计划、接续与增量评审”。时间与质量页增加流动和覆盖视图，项目资产增加实际核验结果。轻量任务沿用风险裁剪，旧任务不因升级自动增加审批。

## 需求与来源

Worker发现范围外问题，可在任务详情“登记需求/发现”，记录现象、目标、依据和来源任务、评论thread、评审finding、运行run、资源resource或intake。原任务继续按原授权执行；问题妨碍当前任务时，另外使用阻塞线程，不能以新建需求替代停止或变更授权。

SE分诊为补充调研、批准进入规划、暂缓、拒绝、重复或已解决，写明依据。重复记录保留，不能成环。批准/调研后可以“从需求建立任务”，粘贴完整任务spec，系统在同一事务创建planned任务并登记派生来源；它不会自动领取或绕过模块、风险、依赖与接口门禁。也可以关联已有任务/模块并记为planned。

discovered_from为执行中发现，derived_from为派生，related为相关，supersedes为替代。它们都不产生硬前置；执行顺序仍由任务depends_on控制。公开来源不允许引用管理/实例私有资源，不能以关系名泄漏其他项目对象。

## 实施计划与审批裁剪

执行者或SE可登记不可覆盖的实施计划版本：步骤、预计写路径、验证安排、风险、停止条件。路径必须在任务已授权范围内。计划固定scope_hash/version、Git基线、当前验收计划及实际消费接口摘要。

SE按任务显式启用execution_policy：light不增加审批；standard由SE选择required；strict且涉及生产、持久化数据、权限、共享资产或未知影响时，启用后不能用required=false免去审批。历史任务未启用仍保留原协议。计划可在领取前由SE准备，或对正在执行任务补充后再继续交付。

SE批准当前计划；严格任务审核Actor须与执行者不同，但不证明模型独立。范围、引用接口或验收计划变化后，原批准失效，需新的实施计划版本及核定。无关模块更新不修改本卡计划。计划不替代正式scope/接口变更。

## 检查点与换会话接手

任务负责人保存不可覆盖检查点：当前真实Git/产物锚点、已完成、剩余、实际测试、未决障碍、仍占用资源、下一步及重新核对条件。session只填可交接的会话标识，不粘贴聊天全文、身份或凭据。检查点是执行者声明，不能据此认定外部进程已经退出。

接手时读取项目brief.continuation或任务coordination.resume。最近检查点标明当前/旧范围，提供自该检查点之前固定四链游标起的增量入口；含检查点本身，可由稳定事件ID去重。仍应核对实际任务、未决线程、发现、接口/资产和工作区。范围改变保留旧检查点，不能拿旧声明代替当前核对。Agent失联不自动释放排他资源或重派。

## 可靠增量消费

GET /coordination/feed?cursor=...&limit=50提供四条项目账本的稳定游标，每页最多100条、安全扫描最多200条。它按链顺序续读，不保证四链时间的全局顺序；items是元数据通知，读取对象的最新授权视图后再决定。has_more=true时按返回cursor继续，即使本页没有可见items。游标不包含身份，不能授予其他项目访问权限。

delivered、read、processed分别表示送达、阅读和应用处理，游标只属于当前Actor/consumer，不能后退，阅读/处理不能超过已送达。处理确认不解决阻塞、不代替验收。每条通知以chain:seq去重；不要拿时间戳去重。

下载[独立协作与观察工具包](/observer-kit.zip)，在非C盘项目目录使用Python3.11+。工具不包含实际身份、配置或项目数据。

```sh
python tools/coordination_client.py --profile <本项目身份> --consumer worker --output <本项目证据目录>/feed
python tools/coordination_client.py --profile <本项目身份> --consumer worker --output <本项目证据目录>/resume --task <任务ID>
```

消费命令有限执行一页；循环/外部Agent唤醒由已有本机工具明确安排。批次先落盘，再推进送达；业务确实处理后才用--processed。ACK.json冻结原请求，网络丢回执时原样重发。409保留原文件，由SE核对当前消费状态；不删除pending盲目重跑。下游处理应按稳定事件ID幂等，本机制是至少一次送达，不声称外部副作用恰好一次。

## 增量代码评审

SE从任务“查看差异并批量评审”选择已绑定仓库、真实base/target。读取文件差异后在具体行加入发现，整理成一个评审批次，填写统一复现/返修验收。每条发现进入第一批的独立处置流程，执行者不能自己关闭。没有行内发现时也可保存本批已查看的范围与结论。

后续批次previous指向上一批，base必须等于其target。界面展示这一批实际修改和所有未决发现；提交输入改变后旧锚点标为旧输入，不自动挪到新行。删除行用left、增加行用right。缺失文件、非法行、本地资料路径或未同步提交均不能建立有效批次。增量评审减少重复阅读，最终输入的测试及验收门禁继续生效。

## 流动效率与改进

时间页区分原有显式申报工时、自然历时和新流动指标：claim到submit、submit到accept、accept到merge、merge到native，显示样本数/P50/P80、按UTC日的提交/验收/返修、首次提交返修率、当前重新打开的发现和模块在制计数。缺少某阶段事件时没有样本，不能填零；每次终点匹配最近的此前起点，保留返修轮次。

这些是任务历时指标，不是DORA的生产部署指标。关键路径仍为依赖/估算参考，未纳入设备队列、工作日或资源可用日历，不把它当可靠完工日期。

SE设置模块WIP上限，可warn提示或enforce限制新领取。沿用原ACTIVE集合，阻塞等待和返修中的任务仍计数并持有原资源；超限不强行停掉已有任务。任务包不是额外任务，不重复计数。

SE对评审发现核定根因为需求不清、接口偏差、输入缺失、实现错误、测试遗漏、环境、规划或未知，核定修订保留。improvement关联已有任务、用例或资产，记录改进假设、实际结果或未验证、运行与证据；结果为观察记录，不自动证明因果或共享资产。新增测试仍须原用例/套件/验证流程，资产仍须候选提炼与固定版本审核。

## 外部条件门

SE建立不可覆盖条件门，固定任务scope/version、精确输入、约束阶段claim/submit/accept/merge/native、类型及有效期。claim使用任务基线输入，其余用当前阶段的实际输入；submit阶段的门在候选接收后、SE accept时检查，允许先入待评审但不能假通过；不同输入使用不同门版本/范围，不能把一次CI通过外推到之后提交。旧范围门保留且阻止继续使用旧规划；SE须按当前gate_hash记录gate_retire的撤销/替代依据，再核定新范围和有效门配置。停用保留历史，不把条件变为已通过。

- github_checks：固定仓库、提交、检查名及GitHub App ID来源，观察同一App的最新同名检查；仅completed+success通过，pending/failed/skipped/neutral都不冒充成功。
- github_pr：固定PR和提交，核对base仓库及merged，输入须为PR head或明确merge_commit。
- human：项目授权管理Actor确认，固定条件摘要；名称不证明自然人参与。
- timer：UTC not_before条件；时间到只满足此门，不自动交付或验收。

GitHub观察必须来自明确授权的本项目runner，并由本机操作人批准准确gate_hash、repository；检查门同时固定app_id来源。项目只读Git镜像的SSH密钥不自动成为GitHub API凭据；需要时本机token_file使用该仓库必要只读权限，不传给server普通Agent。观察器只访问固定api.github.com端点，拒绝重定向、有界分页，保存精确输入证据。授权撤销、对象变化、观察过期或后续失败/pending回报会使门失效。它是批准观察器的实际回报，不是不可伪造的硬件证明。

## 本地资源核验

SE登记runner角色，再observer_authorize批准condition/resource及具体对象。runner原身份不自动获得观察授权，网页批准也不替代本机批准。使用[本机配置模板](/templates/project-observer-config.json)，准确固定project_id、entry_hash或gate_hash及本机路径/仓库；不从网页字段取得执行命令。

file核对固定文件SHA；manifest核对明确JSON清单及每个相对文件；directory仅确认目录存在，HTTP仅对本机批准且与登记一致的稳定入口HEAD。后两者显示reachable，不显示内容verified。manifest格式为 {files:{"relative/path":"sha256"}} 或值为 {sha256:...}；最多512项、总计256MiB，拒绝越界、链接和凭据目录。原件不上传。

```sh
python tools/project_observer.py --profile <本项目runner身份> --config <本机私有配置> --target <批准对象ID> --output <正式证据目录>/observations
```

有限执行一次观察，记录真实字节/协议结果、时间、SHA及冻结PENDING.json；丢回执只重发，不重新核验。409要保留核验记录并核对新范围，不复用旧观察。文件或清单错误不能登记verified；入口版本、授权或有效期改变后历史核验显示过期。读取管理/实例资源仍须原权限，SE授权观察不能绕过目录可见范围。文件现状在观察之后还可能变化，消费者读取时仍应核对。

## API与模板

所有读写先项目鉴权。GET /coordination[?task=ID]返回需求、关系、检查点、实施计划、评审批次、根因、改进、WIP、条件门、实际观察、个人消费位置和聚合；task读取额外返回resume。GET /coordination/feed返回items/cursor/head/has_more/scanned。健康检查coordination_schema=1。

写入仍为POST /operations，外层request_id/expected_revision/action/payload。动作及完整payload见coordination-*模板：intake_open/intake_decide/intake_convert/source_link/checkpoint/execution_policy/execution_plan/execution_review/review_batch/root_cause/improvement/wip_policy/condition_gate/gate_confirm/gate_retire/observer_authorize。工具回报condition_observe/resource_observe及个人consumer_ack遵守本指南字段；模板只提供待填占位，不包含实际状态或凭据。

客户端prepare-operations冻结请求后发送，按原回执重试。仅消费确认、追加需求、固定检查点和带版本的观察允许无关操作并行；同对象改变仍冲突。新增内容共享原operations事务与审计链，任务创建在同事务追加原events，不重写历史。上线/回滚沿用部署手册的一致性备份与单实例写入规则。

GitHub协议依据：[Checks API](https://docs.github.com/en/rest/checks/runs)、[Pull requests API](https://docs.github.com/en/rest/pulls/pulls)。观察器使用固定REST版本2026-03-10，仓库只读权限：Checks read / Pull requests read；不创建检查或合并PR。


当前最短路径见[操作减负](/help/finishing)。获批尝试的参与者以本人有效租约保存检查点、阻塞和时段，不取得最终交付权；resume提供attempt_checkpoints。feed支持task筛选及项目公共边界标识；继续分页保留task，同一consumer不混用筛选与全量流。
