# 评论、逐项验收、SE待办与受控回退

正式服务在server。进入“SE待办与协作”查看当前项目的下一步事项；打开任务查看评论、验收项、逐条发现、Git核验和回退单。执行者只看到自己相关的待办，项目SE看到本项目待办，项目身份不能查询其他项目。普通成员可读本项目记录，待办不是全实例索引。

## 评论与阻塞

先领取任务，再通过“发起讨论 / 阻塞 / 偏离说明”选择类型。普通讨论可由项目协作者参加；阻塞或偏离由当前执行者提出。写明问题、已尝试方法、原计划与实际差异、受影响步骤、仍可独立推进的部分及需要SE决定的事项。接收人使用本项目Actor ID，SE表示项目负责人。勾选暂停会将本人时间记录转为等待，任务仍保留负责人和排他写范围。

评论不改变任务scope，也不释放资源。暂停后执行者可以结束会话；新会话读取任务brief里的collaboration和当前评论后接续。平台记录协作事实，不会替你终止外部Agent进程或自动启动其他Agent。

SE可以普通回复，也可“SE记录决策”：continue按当前授权继续；changes按正式变更继续；stop继续暂停。普通回复不能解除阻塞。changes须关联实际scope事件ID，或本项目contract_execute的“序号:哈希”；讨论中的同意不能代替范围、接口影响确认。执行者核对当前范围决定后“确认障碍已解决”，结束该线程产生的等待时段；实际恢复作业再主动开始时间记录，不能将离线等待当工时。

SE可以明确记录线程解决或停止跟进；旧范围线程继续保留，范围修改不会悄悄清除未解决障碍。偏离说明要区分准备变更与已经发生；已经发生的越界不能用补评论自动合法化。详情显示最近消息，完整线程和历史仍可读取；已读位置属于个人，不修改他人的游标。

## 验收计划与逐项评审

SE在任务内“核定结构化验收计划”，给每条标准分配稳定ID、交付项ID、可判定预期、inspection/manual/automated验证方式。所有交付项必须被覆盖。可引用项目完成清单的不可变版本；清单项实例化为DOD-编号验收项，一并声明和审核，不随以后模板更新漂移。

计划固定当前scope_hash及scope_version。修改标准用新计划ID，保留旧计划。范围更新后旧计划、声明和审核不能替代新范围；历史任务未启用此计划时保留原门禁，不补造通过记录。

执行者逐条“声明此项验证结果”，固定git:完整提交或sha256:真实产物，附实际结果、运行ID及证据SHA。automated标准必须引用实际通过、当前范围代次和精确输入的运行；手工声明不冒充机器执行。SE逐条核对声明ID并记录通过/不通过。严格任务的审核身份必须不同于任务执行身份；这不证明它来自另一个模型或独立外部人工，不能夸大审核独立性。

执行者完成声明后按原任务协议submit；SE逐项通过且所有阻塞性发现解决后，才能按原协议accept。原测试计划、严格审核、合入和运行门禁继续执行。计划中的Git核验要求不会取代这些门禁。

## 逐条发现和返修

SE或tester可以提出独立发现，记录问题、复现及返修验收、阻塞性、关联验收项、提交/文件/行/资源锚点及继承的旧发现ID。资源锚点只登记位置，不上传原件；不填凭据或管理员入口。

执行者以fixed或rejected提交修复或异议的可证伪依据、精确输入、运行及证据。两者都只是声明，状态转为待复核，不自动关闭。SE复核为fixed、dismissed或reopen；异议不能直接当成修复。阻塞发现必须核对本次交付输入，旧处置不能自动覆盖新提交。历史发现和处置链保留，不以新一轮提交、范围更新或更换计划删除问题。

## 实际Git证据

任务的结构化计划可指定本项目已绑定仓库并要求Git核验。执行者或SE填写固定基线、实现提交、本阶段目标提交及submit/merge/native阶段。服务端通过项目只读镜像核对真实对象、基线一致性、祖先关系、实际文件路径及本地资料排除规则。输出只读观察及匹配的精确输入运行，原始资料不因核验上传Git。

submit核验用于交付和验收；merge/native分别核验实现到本阶段目标关系，并要求最终目标有当前范围代次的实际通过运行。祖先关系不能使旧测试覆盖后续改动。Squash、rebase或cherry-pick无法满足原祖先链时，先明确新的交付输入、范围与验证，不能伪造祖先关系或跳过核验。

## 回退工作流

SE“发起回退预览”，选择task/module/code/deploy/asset，写明目标、影响起点任务、原因、数据/接口/原件处置及验证方案。预览固定任务记录、范围代次、模块head、接口状态；代码回退还固定当前分支、完整提交、合并主线和逐提交任务映射，并计算实际路径及下游影响。混合提交和未声明的影响需SE审核，系统不能从diff推断全部业务风险。

所列任务负责人、项目SE、接口拥有者逐一确认同一manifest_hash，再由SE批准。影响或目标分支改变时方案过期，取消后重新预览。被取消、失败和已应用的记录保留；不要重用回退ID。

类型与操作：

| 类型 | 目标填写 | 执行与完成条件 |
|---|---|---|
| task | 任务ID，target填历史create/scope事件ID或current | current表示撤回当前有效成果并重新规划；应用时追加新scope，保留ID和历史，重新评估/验证。涉及接口切换仍须完成原变更流程 |
| module | 模块ID，target填模块@历史版本 | 复制成restore-回退ID的新版本，不覆盖历史；新版本未经评审，不自动迁移所有任务 |
| code | 项目仓库、当前target_ref/base及完整commits | 本机批准执行器在隔离工作区生成反向提交和candidate.bundle，实际检查后回传；不推送。经项目原授权流程将候选合入目标，再用精确最终输入运行验证，由SE应用 |
| deploy | 本机已批准目标ID，target填批准发布ID | 只执行本机固定发布映射、兼容性声明和读回命令；失败尝试恢复原发布并读回。项目SE不因此取得实例全局权限 |
| asset | 本项目消费别名，target填仍可用的固定共享发布引用 | 先按现有固定消费upgrade流程显式切换并验证，再由回退单核对版本/SHA；旧任务asset_locks保持，需SE显式scope迁移 |

task/module可同时包含代码反向提交，先完成候选、集成与验证，再应用元数据。回退后的旧范围结果不再允许新交付，需形成新范围并重新核定。代码回退不恢复数据库写入、server原件或已发送的外部消息；数据库和不可逆动作必须有明确的前向修复或受控恢复方案，禁止恢复整实例旧库丢弃其他项目的新事件。

执行中取消只是请求，不会立即释放资源或宣称已经停止。执行器租约过期后不自动重派；SE核对进程、工作区和资源并附实际证据，才能“核对失联执行器并结束”。旧执行者不能以过期租约成功回传。

## 项目回退执行器

下载[独立回退工具包](/rollback-kit.zip)。Python3.11+及psutil；代码回退需要Git。先签发本项目普通身份，再授予restorer角色；SE用rollback_executor明确允许code/deploy、仓库/目标ID及启用状态。restorer只领取、续租和回传批准回退，不领取开发任务、改治理或批准自己的回退。

本机操作人另在Git外填写[配置模板](/templates/rollback-runner-config.json)，批准精确回退单摘要。配置的代码仓库必须为本机已授权路径，scratch/output分离并放非C盘；checks是本机批准的固定argv。工具执行受信代码，进程组隔离用于清理，不是OS安全沙箱。代码不通过时保留失败证据，不生成成功结论。

```sh
python tools/rollback_runner.py --profile <本项目restorer身份> --config <本机私有配置> --id <回退单ID>
```

部署配置由本机管理员填写：deployments[目标ID]含expected_current、probe_argv、releases[发布ID]；每个发布包含固定argv、完整commit及compatible=true。probe_argv必须返回JSON {release,commit}。执行前核对expected_current，执行后核对目标发布与提交；失败恢复原发布。命令/路径/凭据配置只在本机，不从评论、任务或网页取得，不导出给普通Agent。即使接口批准了目标，本机未批准准确方案/发布仍不执行。

工具生成正式RESULT.json、过程日志、必要的candidate.bundle和冻结FINISH.json；本次临时工作区finally清理。网络丢回执时重跑同一工具只重发FINISH.json，不重复实际回退。409或租约过期须保留原请求并由SE核对回传状态；不能删除输出目录重跑、重写成功或自动放宽版本。

## API和模板

路径均以/api/projects/<project_id>为前缀。GET /workflow读取工作流；/workflow/task?task=ID读取本任务；/workflow/inbox读取当前身份待办。写入使用POST /operations，封装request_id/expected_revision/action/payload，与现有操作链共享幂等事务。评论不会增加任务scope或revision。新动作和字段：

| 动作 | payload |
|---|---|
| thread_open | task/scope/scope_version/id/kind/title/body/to/pause/affected_step |
| thread_reply、thread_read | thread/body；thread/count |
| thread_decide | thread/decision/summary/reference |
| thread_ack、thread_resolve | thread/summary |
| criteria_defaults | id/items(字符串数组)/reason |
| criteria_plan | task/scope/scope_version/id/items({id,deliverable,expected,method}数组)/defaults/git_required/repo/reason |
| criteria_claim | task/scope/scope_version/plan/criterion/input_anchor/summary/runs/evidence |
| criteria_review | task/scope/scope_version/plan/criterion/claim/result/summary/evidence |
| review_open | task/scope/scope_version/id/criterion/description/acceptance/blocking/anchor({commit,path,line,resource})/previous |
| review_disposition | task/scope/scope_version/finding/status/input_anchor/summary/runs/evidence |
| review_resolve | task/scope/scope_version/finding/disposition/result/summary/evidence |
| git_check | task/scope/scope_version/repo/baseline/implementation/target/phase/reason |
| rollback_plan | id/kind/object/target/tasks/repo/target_ref/base/commits/mainlines/mapping/reason/data_plan/tests |
| rollback_confirm、rollback_approve | id/manifest_hash/summary |
| rollback_cancel、rollback_recover | id/summary；id/summary/evidence |
| rollback_apply | id/manifest_hash/summary/runs/commit/evidence |
| rollback_executor | actor/kinds/targets/enabled/reason |
| rollback_claim、rollback_heartbeat | id/manifest_hash；id/lease（专属执行器） |
| rollback_finish | id/lease/status/commit/evidence/artifacts/summary（专属执行器） |

模板目录提供对应workflow-* payload。读取task当前scope_hash、scope_version填入，不使用全零占位。证据为真实路径/SHA；公共模板不含身份、实际状态或管理员入口。

```sh
python client.py --profile <本项目身份> prepare-operations --action thread_open --payload <已填写workflow-thread.json> --out <证据目录>/request.json
python client.py --profile <本项目身份> request --endpoint /api/operations --payload <证据目录>/request.json --out <证据目录>/receipt.json
```

丢回执重发冻结原请求；409重读后明确决定，不能自动覆盖。SE待办和任务brief含未决评论、验收计划、发现与回退事项。接手前核对它们，不因历史任务状态显示已验收就忽略正在进行的回退。

新增模块可用knowledge_refs明确引用材料位置：章程四项和所列材料进入评审摘要，无关材料更新不使其失效。缺失引用仍阻断，旧模块缺省维持原整体知识摘要，升级用新规划版本，不改写旧评审。


并行写入：工作流比较本次操作实际依赖的对象。无关测试心跳或另一线程更新不使原冻结请求失效；同一线程出现新事实/决策、验收声明被改或输入范围变化仍冲突。服务保留原请求及版本，并在回执标出independent_changes_since；这不是客户端重写请求或盲目覆盖。

若部署恢复或临时资源清理无法确认，执行器回传needs_recovery，保持交付阻塞。SE须附进程、资源和实际运行状态证据完成恢复，不能把失败当已还原。已经切换的部署不能用取消抹去，须验收或新建恢复单。


## 需求、接续与持续改进

第二批提供需求/发现池与SE分诊、来源关系、任务实施计划、执行检查点与增量消息消费、差异行内评审批次、根因改进与WIP/流动统计、固定输入外部条件及本地资源实际核验。入口为“需求与改进”、任务详情及原时间/质量/资产页。轻量任务无额外审批，旧任务显式采用后才增加实施门禁；换会话不自动释放资源。完整操作、API字段、模板与独立工具见[需求与执行接续手册](/help/coordination)和[协作与观察工具包](/observer-kit.zip)。
