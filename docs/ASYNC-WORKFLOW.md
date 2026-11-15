# Worker 异步交付与基线依赖

正式入口：http://example-server.example-tailnet.ts.net:18785 。项目上下文由项目专属身份和 `/api/projects/{project_id}/…` 固定；切换项目必须重新确认身份、任务和资源，不能混用上下文。

## 普通任务的最短路径

SE 先核定项目框架、模块、任务范围、风险及适用验收要求，冻结共享接口，再将可领取任务发布。Worker 按 [自助加入手册](/help/worker-start)加入指定项目，读取任务 brief、接手资料和固定输入，认领任务，执行、验证，然后提交候选成果。SE 异步评审、要求返修或验收；实际合入后登记基线，图和任务清单据此更新。

普通任务默认不额外要求实施计划审批、执行尝试、会话注册、检查点或平台自动化执行器。已有模块方案足够时直接执行；只有 SE 明确采用的计划门、并行尝试、风险和质量要求才增加相应步骤。轻量任务可以提交本机检查或自动化日志的原件位置、SHA256、结论及验证选择依据，由 SE 阅读核验；这是 Worker 陈述，不是平台运行证明。已知失败或尚未执行的验证不能验收为完成。引用平台运行时，最终验收仍检查当前范围、精确输入及通过结果。权限、生产、持久化数据等风险的最低门禁不因候选入队而降低。

## 留言后由 Worker 选择是否等待

`thread_open` 的 `pause:false` 表示记录问题后继续已授权的安全工作；`pause:true` 表示等待并记录等待时间。普通讨论、阻塞求助、计划偏离均可使用这一选择。没有 SE 回复也可以提交进度和候选成果。

留言者可随时用 `thread_wait` 调整自己的选择，模板见 [workflow-thread-wait.json](/templates/workflow-thread-wait.json)：

```json
{"thread":"question-id","pause":false,"summary":"独立部分不依赖此答案，继续已批准范围并保留问题待SE核对"}
```

通过 `/api/projects/{project_id}/operations` 的标准 request_id / expected_revision 信封追加动作；不额外传 task、scope 或 selection_id，服务端从线程核对当前范围。启用执行尝试时附本人有效 attempt_id / attempt_lease。网页在本人当前线程上提供“选择等待回复”或“自主继续，不等待回复”。它只调整本人的等待记录，不替别人恢复工作、不释放共享写权限或排他资源，也不会自动解决阻塞性问题。切换到其他任务后，不会为旧线程停止无关计时。

SE 正式 `stop` 决定仍有效，Worker 不能通过继续计时、调整等待或自行关闭普通讨论来覆盖它；需要 SE 改变决定或正式变更范围。SE `changes` 决定必须引用已登记的范围/接口变更。自主继续不是扩大任务或修改公共接口的授权。阻塞/偏离的问题由 SE 关闭，普通讨论作者可自行关闭；SE 回复或 Worker 不再等待本身均不等于问题已核准。

## 候选入队与验收分开

`submit` 仍使用原 API，候选必须属于本人当前任务和范围，明确完整/部分交付项，提交实现 Git 锚点或非代码原件 SHA、工作记录、结论及证据引用。错误身份、过期范围、无效输入、外项目或不匹配输入的运行引用仍被拒绝。

以下情况允许先进入 `submitted`（候选待评审）队列：未决评论/发现、缺少逐项审核、验证未通过、尚未完成的人工或外部条件门、SE 尚未选择已停止的执行尝试。已配置尝试的候选须先由执行者确认停止、登记结果；活跃或失效尝试仍不能冒充候选。SE 选择同一候选后，无须仅为补 selection_id 再提交一次。

接收回执不声明测试通过或任务完成。任务详情的 `delivery_readiness` 展示 candidate_received、ready_for_acceptance、blockers、verification_origin 和 dependency_lock_state；准备度不代替有权 SE 阅读原件或实际执行验收。缺少历史消费锁标为 unknown_legacy，不补造旧记录。项目待办集中显示候选；明细列出验收前应处理的障碍。未决阻塞、失败质量、无效治理规则、计划门和显式 submit 条件门均在 `accept` 继续检查，submit 条件门被推迟到验收，未被删除。

SE 核对本次精确输入，处理发现、逐项标准及适用质量证据后再 accept；实现合入、运行验收仍使用原 merge/native 流程。登记基线不会替 SE 执行 Git merge、push 或部署。Worker 可以去认领独立任务，已有写路径、排他资源和 WIP 约束仍按项目设置执行。

## 依赖按成果和消费基线解锁

同一项目 `depends_on` 表示硬前置，按前置任务分类推导要求：

| 前置成果 | 默认要求 |
| --- | --- |
| research / documentation | knowledge：当前成果已验收，有确定版本 |
| collection / generation | artifact：当前成果已验收，有确定版本 |
| infrastructure / frontend / backend / library / test / integration / release | code：当前成果已合入，真实 Git 关系证明实现被合入且合入提交包含在下游固定 baseline 中 |
| 历史未知分类 | 等待 SE 核定，不能凭旧 DONE 自动解锁 |

可在任务 spec 添加可选 `dependency_requirements` 映射，例如：

```json
{"up/code":{"kind":"code","stage":"native_accepted","repo":"main"},"up/research":{"kind":"knowledge","stage":"accepted"}}
```

键必须在本任务 depends_on 内；stage 可为 accepted、merged、native_accepted。已知代码依赖不能降为 knowledge/artifact 或仅 accepted。默认推导足够时不填映射。代码核验使用项目批准的只读 Git 仓库；多仓库需明确 repo，不能猜仓库。已明确的生产方/消费方仓库必须一致；跨仓库工具或构建产物走既有固定版本资产消费，不混用 Git 祖先关系。Squash/rebase 等不能证明原实现被合入时，先按既有映射或重新核验流程处理，禁止仅写一条合入声明放行。

前置未合入、下游基线尚未包含合入、当前成果重开/回退、未决审核或锚点未知时，依赖保持阻塞。代码无需每条依赖重复人工解锁，但 SE 必须实际合入并更新消费基线。知识或普通原件无需伪造代码合入。

领取事件固定 dependency_locks（生产方范围、提交/产物、合入及消费基线）。领取后成果锚点改变，SE 验收被拦截，需追加范围并重新领取，不能静默漂移；单纯留言不改变成果锚点。任务池、任务详情和依赖图使用同一解析规则；硬依赖箭头可查看成果类型、要求阶段和当前阻塞原因。历史完成状态保持原样，不追写通过记录。

以上机制只协调任务，不启动 Agent 会话或替 Worker 执行工程命令。
