# 第三批：规划补齐与操作收敛

正式入口 http://example-server.example-tailnet.ts.net:18785 。本指南可由其他电脑上的Agent通过Tailscale阅读；文档阅读不授予项目数据或操作权限。使用自己的项目profile，保留原actor/project_id。实例管理员密钥、原始会话与运行状态不进入模板、Git或普通Agent说明。

这一批只补齐原方案的四组能力。已有评论、验收、Git核验、回退、时间、测试和资产继续使用；不增加预算、项目组合、跨项目调度、Agent托管或持续发布系统。

## 1. 关联规划草案

入口为“框架与规划 → 关联规划草案”。Agent逐项选择修改类型、填写稳定键及现有API载荷，补充来源、依据与实际证据；保存不可覆盖的id@version。可组合模块规划、研究结论、冻结接口、原子任务创建/范围变更、里程碑、默认完成清单、用例版本和治理规则。新模块必须明确knowledge_refs，未引用材料填[]，不能省略后默认为整份项目知识。

SE打开本批，先预览，再明确选择本批同时批准的模块版本和规则版本。未选择的模块只登记版本；有未知项、未验收研究任务、未冻结接口或未就绪依赖时，不得补造通过。预览按真实依赖排序，调用原任务/治理/用例校验，在事务保存点模拟后回滚；任务、治理链与操作链均不残留预览写入。此时草案仅增加预览记录。

核对目标覆盖、拆分是否独立、路径与共享接口、验证方法，再使用预览manifest_hash批准发布。发布者必须是完成该预览的SE，所有修改在同一个项目事务里生效，任何一步失败整批不发布。原request_id和完整请求重发可取回相同回执；改变正文须新请求。预览过期会列出变化的材料、任务、接口、决策、模块或产物边界，重新预览后再决定。

章程四项背景/目标/非目标/约束是共同边界。显式引用的材料、研究结论、接口和依赖模块才影响相应模块；无关历史说明变动不使显式引用模块失效。模块卡片显示失效分类。历史模块缺少knowledge_refs时保留历史计算方式；需SE新版本明确引用，不默改旧审批。

复杂迁移或存在实现分歧时继续使用任务实施计划；模块方案覆盖充分的轻量任务不增加统一实施审批。执行中发现未知项，登记需求/评论并等待SE核定，不能把整批批准当作无限范围授权。

## 2. 批准规则的复用

入口为“治理策略 → 批准边界内复用治理规则”。SE登记不可覆盖规则版本，绑定已批准模块、有限路径、任务分类、档位、冻结接口、固定资产SHA、默认完成清单、用例版本、实施计划策略和一年内明确到期时间；核对当前context_hash后批准。代码规则须绑定已同步的项目只读仓库。

执行者在任务详情“沿用批准规则”，服务端检查当前范围、角色、模块、路径、接口和资产是否精确符合。符合时实例化固定验收清单及用例计划，沿用规则批准者的授权，不伪造逐卡评审，也不要求SE重复填写风险卡。已有验收/测试计划不可被覆盖削弱；冲突须SE先合并要求。标准任务仍需标准测试，轻量任务仍需实际验证声明和逐项审核。

规则不是Agent自行声明低风险。已知风险标志、耦合、越界路径、到期、撤回、模块评审变化、接口/资产/用例变化都会阻止复用。代码提交还读取实际Git祖先关系和基线差异，检查全部变更路径、本地资料排除、敏感目录及链接/子模块；权限、数据、生产或未知影响应由SE升级评审。“转为SE逐卡核定”只移除绑定，原证据和历史继续保留，SE需补齐当前评估。

module_covered表示复用模块方案，已有标准/严格任务实施审批门继续有效；se_review明确要求独立实施计划，即使规则轻量也须核定。旧任务未采用规则时保留原档位语义。

## 3. 尝试、会话和保守恢复

入口为任务详情“任务接手包与执行尝试”。普通任务不强制采用租约。需要跨会话/机器或比较路径时，SE先登记实际工作区入口、机器、分支、有限路径和排他资源，再批准当前范围允许的执行者/工作区、并行上限1～8、租约30～3600秒。

任务仍按原规则领取，任务负责人协调最终交付。授权执行者开始新尝试，保存attempt及lease回执。每个尝试保留基线、接口和资产版本；会话只是其中不可覆盖的引用，可登记前序会话、工具、声明模型、机器与检查点。不同模型声明不证明评审独立。

执行者在租期内续租；进展和检查点须带attempt_id/attempt_lease。完成后记录candidate/failed/cancelled、精确输入、实际运行和证据。确认旧进程停止、工作区与资源核对完成，才可声明stopped=true；无法确认则进入待恢复。失败或未采用尝试继续保留。

已选择候选后的交付/收尾检查点使用attempt_id/selection_id，输入仍须精确匹配当前选择；不再续用已结束尝试的租约，旧选择回执不能覆盖当前接续记录。

租约到期、范围变化或明确未停止都进入needs_recovery，保留工作区与资源占用，不自动释放，也不自动抢占。SE在实际机器核对进程身份、创建时间、命令、目录和资源，附证据；stopped=false继续保留占用，确认停止后stopped=true记为abandoned。该记录是有责任人的核对声明，平台不远程杀进程、不证明OS隔离。跨目录别名/链接须由SE实际确认；机器和位置登记不能替代隔离。

所有活跃/待恢复尝试结束后，SE选择当前范围已停止的candidate，生成selection_id。原任务负责人提交时填写attempt_id和selection_id，精确Git/产物输入须与选中候选一致；旧租约、旧范围、旧候选回执或仍有未核对尝试都被拒绝。任务验收、合入和运行验收继续走原门禁，选择候选不等于验收。共享同一身份的会话属于同一信任边界，应分别保存当前回执。

## 4. 工作台、上下文和模板

“SE待办与协作”按身份显示工作台：SE查看待规划批准、实施评审、验收、未决问题、失联恢复、候选选择和阶段验证；执行者查看自己的活跃任务、可领取任务及阻塞原因。不在每个tab重复交付队列。停用历史条件门不进入当前待办；回退仍在同一入口沿用原确认流程。

任务详情可读取当前接手包。接口 GET /api/projects/{project}/convergence/context?task={task} 返回当前scope、实际引用材料摘要、来源与SHA、接口/资产版本、未决发现、验收与测试计划、检查点、尝试和会话、资源入口，以及检查点之后的变化。包本身也有SHA。readback保留来源种类/ID，按现有brief、任务详情、治理或资源API读取原件；摘要不代替原件或完整日志。has_more=true时使用changes.cursor继续读取coordination/feed，处理后再显式确认消费，不把读取当完成。

也可下载 /observer-kit.zip，在非C盘证据目录执行：

```powershell
python tools/coordination_client.py --profile <本项目身份位置> --task <task-id> --context --output G:/<项目>/evidence/handoff
```

输出CONTEXT.json；可用--since传入已有四链游标。凭据单独保管。原始聊天/日志继续放本地或server并登记资源，不复制到Git。

“框架与规划 → 固定版本项目模板”组合规划、默认完成清单、用例、规则及资源分类建议。负责人和基线必须使用声明参数`${owner}`、`${baseline}`，新项目填实际值。模板不复制身份、凭据、成员、运行状态或测试通过记录。SE核定definition_hash后才可实例化；实例永远先成为草案，再按第一节核对。

本项目模板不自动跨项目。需跨项目时，导出批准定义的精确document字节与SHA，通过已有资产审核发布/显式固定消费流程共享；目标项目SE按消费SHA导入，再核定定义并实例化。撤回/禁止消费按既有共享资产规则处理。资源分类建议不创建虚构入口；实际材料仍由新项目登记。模板新版本不修改旧实例或已有项目。

## API与复制入口

新增读取为GET /convergence、/convergence?task=、/convergence/context?task=&since=、/convergence/template?ref=。均先按项目鉴权；404不泄漏其他项目存在性。health增加convergence_schema=1，旧schema和四条追加链不重写。所有写入复用POST /operations：{request_id,expected_revision,action,payload}。runner/tracker/restorer不能调用规划或治理动作；viewer只读。

四组完整载荷示例见 /templates/convergence-draft.json、convergence-rule.json、convergence-attempt.json、convergence-template.json。占位符须换成真实当前值；不能把示例证据当实际验收。准备与投递继续使用client.py的prepare-operations和post，保留同一请求以处理丢回执；409重读对象后决定。

| 动作组 | 动作 | 权限 / 固定锚点 |
|---|---|---|
| 规划 | draft_save / draft_preview / draft_publish / draft_reject | Agent可起草；SE预览/决定，固定manifest_hash |
| 规则 | rule_register / rule_review / rule_retire / rule_bind / rule_unbind | SE批准/撤回/升级；任务执行者可绑定已批准边界，固定context_hash及scope |
| 接续 | workspace_register / attempt_policy / attempt_open / attempt_heartbeat / session_attach / attempt_finish / attempt_recover / attempt_select | SE授权/恢复/选择；执行者只操作自己的有效租约，固定scope与精确输入 |
| 模板 | template_register / template_review / template_retire / template_import / template_instantiate | SE核定；执行者可实例化批准版本为草案，固定definition_hash/消费SHA |


具体选择与最短步骤先见[操作减负](/help/finishing)。字段编辑默认可用，JSON为高级入口；多参与者检查点按本人尝试区分，批量声明/审核复用原逐项校验。
