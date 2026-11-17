# Worker事后整理与归档

在“时间与效率”的“事后整理与归档”使用。它是项目收尾或发现缺采样时的可选批次，不是普通任务新增必填步骤。Worker整理，SE核定，待审核内容不计入统计。最新版草案待审或退回时，上一版已批准记录继续生效。

可直接发给其他Agent的[Worker说明](/templates/retrospective-worker.md)、[整理包模板](/templates/retrospective-package.json)及[整理工具包](/retrospective-kit.zip)均不含实际身份或项目资料。

## 最短操作

1. SE给Worker本项目ID、时间段、允许的来源目录/原生Session ID和自己的项目接入入口。Worker先读当前任务、`/sessions`、`/usage`和`/operations`；已有记录仅引用，不换ID重录。
2. 原件留本地/server。生成MANIFEST.json，明确机器、真实位置、访问条件、SHA256、内容时间段与缺失清单。SE可安排原件归档到项目专用server目录；本工具不会搬迁、删除或上传原件。
3. Worker生成 `{project_id,draft}` 整理包。可只有归档入口与缺失说明，entries为空；不要为补齐页面伪造历史。每批最多64条明确补录，原始日志不塞入表单。
4. 在网页上传整理包并提交，或用下列工具核对本机原件、生成冻结请求后通过原客户端提交。网络失败只重发冻结原请求，不重新生成ID。
5. SE展开批次，核对原件、会话归属、任务范围、累计基线、工时依据和重复项，写核定理由。批准后Token进入原用量账本；历史工时进入时间统计；统一归档入口自动出现在“项目资产 → 历史快照 → 事后整理归档”。后台只验证元数据，不读取Worker磁盘，也不确认供应商账单。

```sh
python -m tools.retrospective_client --profile <自己的本项目身份> --file <整理包.json> --root <明确允许核对的本机项目目录> --out <Git外目录>/archive-request.json
python tools/task_board_client.py --profile <自己的本项目身份> request --endpoint /api/retrospectives --payload <Git外目录>/archive-request.json --out <Git外目录>/archive-receipt.json
```

`--root`可重复。工具只检查逐条明确引用的普通文件及其摘要，不遍历整个目录或链接，不读取身份内容；无法从本机核对的远程原件应先由有权节点核对，再整理材料。应用既有凭据/配置不因归档而迁移。清单核对和哈希对应并不证明内容真实或完整，仍由SE判断。

## 补录条目

共同字段：`id,kind,actor,session,task,scope,scope_version,start,end,phase,origin,reason`。
UTC秒时间段必须在批次period内。origin为 `{path,sha256}`，记录原件而非密钥/身份。actor必须属于本项目；任务范围可为当前或能从原事件链核对的历史版本，未知范围只写缺失清单。阶段可为research/design/implementation/testing/review/integration/release/asset/governance或unknown，分类依实际活动，不因SE角色自动算治理。

- `kind=usage`另填 `model,attribution,basis`。model未知填unknown，不能猜测实际模型。attribution为bound_task/project_overhead/unattributed；空任务的scope为空、scope_version为0。用量必须有本项目已登记且属于原执行者的Session ID；Worker不能借补录获得该会话的控制权。
- `basis={mode:"call",before:null,after:{input,output,cache_read,cache_write,reasoning}}`：逐调用增量。每个计数非负整数或null；input+output为总量，缓存/推理为子集。
- 累计读数使用 `mode:"cumulative"`，before和after填写实际原件读数；服务端计算差值。before未知填null，整个差值保持未知，不能把第一条累计读数当本段新增。计数下降拒绝入账，先核对重置和计数流。
- `kind=time`另填 `seconds,mode,rework`。mode为work/wait/pause；seconds为有依据的有效秒数，不超过自然区间；rework为独立布尔标签。未知工时不建条目，写missing。时间补录需关联已有任务；无法对应任务的项目协调时间先归档说明。批准补录不自动声明任务时间完整，更不替代任务验收。

来源已存在用量且无法证明区间不重叠时会拒绝整批入账。特别是旧累计流没有可靠区间信息时，只归档核对说明，不重建一条新流。相同会话的多个任务条目也不能覆盖相同用量区间。同一执行者的历史时段不得与已登记作业/等待时段重叠；不同Worker可同时作业。

## 审核、修订与权限

项目路径 `GET/POST /api/projects/<project>/retrospectives`。POST包为 `{request_id,project_id,action,payload}`，项目ID必须匹配当前身份。

- `action=submit`：payload为模板draft，稳定批次id从version=1开始。修订同批次递增version，保留所有旧草案和核定。普通Worker仅修订自己的批次；SE可核对修订。
- `action=decide`：payload为 `{id,version,draft_hash,decision,reason}`，decision为approved/rejected。只有本项目管理者可审核，按精确草案摘要比较并交换；旧版本不能通过。批准与用量入账在同一项目事务中完成，任何条目冲突时整批保持待核定。

已批准用量的条目ID、执行者、会话、任务、范围和时间区间不能移走；计数纠错沿用同条目，原账本追加修订而非覆盖。已批准工时按最新核定版本投影，旧版本保留；修订后的时间完整性须重新确认。不能通过修订把历史范围迁到当前范围。审核不会重写原任务、测试或验收。

整理账本独立于operations全量快照，原始记录不在每次任务操作中复制。Token仍使用原token_usage账本，原执行者、整理者、SE核定者和来源区间分别记录。报表继续区分导入/采集/手填/估算；历史补录不是自动采集或实际货币成本。
