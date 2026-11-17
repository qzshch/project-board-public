# 跨机器Agent编排与有界委派

## 机器接入一次，项目身份分别使用

任意可访问server公告板的Tailscale电脑均可接入，不绑定固定机器名单。Tailscale解决连通性；人类平台所有者或实例维护者仍需授权该节点允许处理的项目，本机另行固定项目根、角色、实际运行时启动命令及并行上限。server不发送Shell、环境变量、可执行路径或任意RPC。

1. 人类登录面板，选择项目，进入“Agent编排与委派”，在“授权新机器”填写稳定节点ID和Tailscale名称。下载一次性私有接入文件，30分钟有效。节点ID不能覆盖或重新使用已撤销身份；换机器使用新ID。
2. 目标电脑下载 [节点工具包](/node-kit.zip)，解压到C盘外的专属目录，使用Python3.11+环境安装包内 `requirements.txt`。复制 `templates/agent-node-config.json` 到Git外私有位置，修改URL、节点ID、状态目录、允许项目、工作根与角色。移除未安装运行时，填本机实际CLI argv；不能照抄示例路径。
3. 使用 `python -m tools.agent_node --config G:/board-node/config.json --enroll G:/board-node/node-pair.json --probe` 接入并探测。供应商密钥仅由本机运行时按其既有配置读取，禁止放在命令行、接入文件、公告板或Git中。成功后一次性pair文件不再需要，按本机私有文件规则清理。
4. 使用 `python -m tools.agent_node --config G:/board-node/config.json` 持续运行接入端。自动化部署请由本机维护者配置隐藏窗口启动，保留PID、真实创建时间和日志；不要运行会另开窗口的批处理包装。同一状态目录只允许一个接入端。关闭接入端会清理它启动的运行时及子进程，原会话与收据保留，重启后恢复原ID。

模型还需要获准访问server公告板。Codex本机argv可显式使用 `codex -c sandbox_workspace_write.network_access=true app-server`；这由本机维护者配置，server不能发来该开关。其他运行时按原生权限策略预先允许本项目必需的文件和公告板访问。运行时请求额外审批时接入端不自动批准，先由原机器维护者核对；不可把“网络被沙箱禁止”解释成公告板未授权。

原生权限通道阻止工具时，节点把真实 `approval_required` 状态和一次去重通知交给SE，面板可见；不会伪造Worker已留言或自动批准命令。由本机维护者通过原应用核定项目所需权限后，再通知原会话继续。未实现的Zcode auto模式以及会跳过原权限判断的模式，不作为自动解决办法。

本机维护者也可在运行时私有config预先写入 `approved_commands`：每项必须有完全相同的 `command`、固定 `cwd`、`script` 的绝对路径和该文件 `sha256`。仅对本节点已创建/恢复的会话核对当前文件后，回答Zcode Bash或Codex命令执行的一次原生许可；不接受命令前缀/正则，也不接受额外沙箱放宽。内容或参数改变即不批准，server和项目SE不能通过API下发这些规则。规则与脚本应由本机维护者保护，勿从未审查的项目文件自动导入；未配置的请求仍留作本机授权卡点。DeepSeek SDK未声明支持的许可形状继续拒绝，由其本机运行配置核定。

每条规则还必须写 `project` 与 `role`，可再写具体 `binding`；Worker不会复用SE或其他项目的规则。固定客户端命令可以引用节点注入的 `PROJECT_BOARD_PROFILE` 与 `PROJECT_BOARD_PROJECT` 环境变量，身份仍来自本次绑定，不在命令里放token。模型只看到当前项目/角色/工作根适用的命令。实际一次许可在节点私有日志记录命令摘要、脚本哈希和原会话，不声称是人类现场批准。

Windows子会话能访问的工具链可能不同于当前终端。尤其Codex沙箱未必能执行用户AppData下的解释器；本机维护者需选择对子会话可执行的已授权工具位置。请用实际工具动作核对，不能只检查宿主机上文件存在。Zcode的 `ZCODE_HOME` 不是完整的配置/会话隔离开关，独立配置与存储应按安装版本真实设置核对，不能据它宣称已隔离。

项目根和节点状态放C盘外；应用既有配置与凭据不由公告板迁移。若运行时默认产生项目缓存，按该运行时的本机配置固定到项目/server目录。允许项目可登记多个根别名；SE只选择别名，不能在HTTP请求中注入磁盘路径。节点开通项目集合需要扩展时由实例维护者重新授权新节点ID，不能由项目Agent扩展。

## 四种运行时分别适配

| 运行时 | 本机固定启动方式 | 模型与权限 |
| --- | --- | --- |
| Codex | `codex app-server` | 读取实际 `model/list`；创建及恢复固定cwd/model，使用workspace-write与原生on-request审批 |
| Zcode | `node <已安装的zcode.cjs> app-server --surface terminal` | 其NDJSON没有jsonrpc字段；配置确切 `providerId/modelId`，通过原生连通检测才报告可用；明确使用edit模式，不采用CLI默认yolo |
| DeepSeek Harness | `dsh --profile sdk`，或本机等效可执行argv | 官方SDK JSON-RPC协议；每个连接固定provider/model，握手必须验证路由；会话ID由接入端固定 |
| Antigravity CLI | 已安装CLI的绝对路径加 `acp`，例如 `agy.exe acp --log-file G:/board-node/private-state/acp.log --disable-telemetry` | 官方ACP1握手，读取原生会话availableModels，与本机models允许清单取交集；使用原生sessionId，固定default模式和所选模型 |

Antigravity在绑定表单中选择 `antigravity`，可作为SE或Worker。SE需在该节点的项目配置中允许se角色并提供本项目se_profile；Worker身份仍由原节点绑定流程签发。任何Tailscale电脑都可配置，不依赖当前PC路径。请先由本机维护者完成CLI登录；节点复用既有登录，不打开浏览器或替用户登录，也不把Google凭据送往server。

Antigravity使用 `session/new`、`session/load`、`session/prompt` 和 `session/cancel`。记录CLI返回的原生ID，不能把公告板绑定ID当作会话ID，也不用“最近会话”接续。一个ACP prompt直到该轮结束才返回；节点保留异步请求，同会话忙碌时通知排队，避免把新通知变成对正在执行任务的steering。发送回执表示已发往原进程，不证明模型已完成或任务已验收；逐轮终止状态保留在节点私有processes目录。通信中断/未知终止状态进入待核对，不自动重放输入。

Antigravity未核准的权限请求按ACP取消本次请求并通知SE。`approved_commands`只支持实际 `run_command` 的一次命令许可，必须匹配本机项目、角色、cwd、完整命令和脚本SHA；不批准Daemon、额外工作根、未知工具或always权限。原CLI中已允许的权限规则仍由本机维护者负责，default模式不构成OS文件隔离。节点不启用 `--dangerously-skip-permissions`。额外权限在原机器核对后，由SE通知原会话继续。

异常先在面板和节点原始收据中核对；若输入结果为needs_recovery，SE通过原recover动作确认，再明确resume原绑定。不能换会话ID或重复派发来绕过不确定结果。取消只向本适配器持有的原会话发送，不关闭用户其他CLI或桌面会话。

模型发现只证明CLI声明可用，不代表每个模型已通过实际推理。官方协议参考：[Antigravity ACP](https://antigravity.google/docs/ide/extensions/acp)。尚未识别的ACP Token字段保持缺采样；可以按[事后整理](/help/retrospective)核对显式原件，不将同一轮的逐步用量与最终累计值相加。

Zcode安装版本若需要 provider 文件路径，可在本机config的 `environment` 指定 `ZCODE_BUILTIN_PROVIDER_CONFIG_FILE` 与 `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE`，仅保存路径，勿复制密钥到公共模板。供应商路由名称可能留有旧配置，实际探测失败就不可派发。更换安装版本、路由或本机配置后重新探测并重启接入端。

Zcode路由要求推理级别时，在该运行时本机config增加 `"model_options":{"实际provider/model":{"reasoningLevel":"实际支持的值"}}`，探测和创建使用同一组选项，不猜测供应商可用级别。原生“正在运行”拒绝作为忙碌留队处理，不会因一次状态竞争丢掉通知。

同一组选项也随每次输入明确传给Zcode，避免其旧式输入路径重置选择。DeepSeek SDK可在本机运行时config指定 `"reasoning_effort":"实际支持的值"`，由初始化握手核定。模型探测验证助手实际输出；不能因为用户提示中有预期文本或运行时确认接收，就认定模型已正常执行。

DeepSeek SDK支持排队输入、原会话恢复及状态通知；当前官方SDK没有单会话取消方法，面板停止请求会明确返回不支持，需在原节点核对处理，不能为停止一位Worker关闭其他人的会话。SDK审批与问题请求不自动批准。未安装、未登录、路由不可用、探测失败或90秒无心跳的运行时均不可派发。控制面握手通过不等于模型执行、代码测试或交付已通过。

## SE派发与异步通知

SE在面板选择在线节点、运行时、实际模型、工作根、角色和当前已发布任务，点击“创建并派发”。也可用本项目身份向 `POST /api/projects/{project}/orchestration` 发送 [绑定模板](/templates/agent-binding.json)，先把原请求与request_id持久保存。当前版本一个任务只绑定一个原Worker会话，防止重复派发；多路实现继续使用既有执行尝试与明确的工作区规划。

Worker绑定由服务端签发独立的本项目Worker身份，只有该节点可领取，不会取得SE或实例维护凭据。节点把身份保存本机私有路径，提示中仅提供路径。Worker自行在线核对任务、领取并工作；任务不就绪时登记具体阻塞，不能绕过领取门禁。

SE会话绑定必须先在本机项目config中允许 `"roles":["se","worker"]` 并指定 `"se_profile":"G:/private/this-project-owner.json"`。节点只读取这份本项目身份，不会从server领取owner身份。未绑定到运行时的SE继续使用原SE待办，系统不声称已唤醒它。创建的是新的受管会话；不会自动控制用户当前打开的其他聊天。

创建会话和首条模型输入是两个独立持久工作单。Worker评论/提交通知项目SE绑定；SE或人类对原线程的回复/决定通知该任务原Worker。原事件ID去重，节点重启不重复新建通知，绑定创建前的旧评论不会全部重放。运行时忙碌时保留队列等空闲，不抢占输入、不重建会话。Worker自主决定是否等待的现有规则保持；SE正式stop仍按现有任务门禁执行。

SE也可对已有绑定发送 `notify`、`resume` 或 `stop`，payload为 `{"binding":"原绑定ID","summary":"具体操作说明"}`。`resume`在原session ID继续并读取当前公告板上下文；不是创建替代会话。受管会话的原始聊天和日志留在节点，公告板记录项目、机器、模型、会话ID及安全的状态摘要。

任务正式范围改变后，节点会停止按旧范围继续。SE核对并更新任务后，向原绑定发送resume，并在payload明确带 `previous_scope`（原绑定范围）、`scope` 和 `scope_version`（当前任务范围与代次）。服务端原子核对这三项，保留原会话、节点、角色和项目。存在结果未知的旧动作时先处理恢复，不能用改范围释放它；普通评论不需要这一额外步骤。

## 传输结果未知时

节点准备、发送、等待及清理期间每15秒续租。90秒无有效续租的工作单进入 `needs_recovery`，保留绑定和资源占用，不能自动重复发模型输入。`accepted`只表示运行时已接收，实际任务仍须submit→SE复核→accept/merge/native及原测试、Git、依赖门禁。

SE读取 `GET /api/projects/{project}/orchestration` 查看工作单。先在原节点查看 `state/receipts/{job}.json`、对应report收据和运行时原session，确认是否已创建/接收/运行。不要改本机 `attempting` 收据来强行重试。

人工核对后可发送 `action:"recover"`，payload包含 `job,session,status,summary,evidence`；status只能为 `accepted` 或 `failed`，evidence填真实本机收据/证据位置。已有会话不能换ID。已确认创建的原会话接收输入使用新明确的resume工作单；确认未执行的动作由SE重新决定，恢复不会自动重放旧副作用。收据和原失败保留。撤销节点只撤销后续控制面权限，失联工作是否停止仍需原机器核对；如需撤销Worker项目权限，另用既有身份撤销流程。

节点还会核对本机 `state/bindings` 中原项目、角色、身份、工作根和会话ID，服务端SE填写一个session ID本身不能接管其他聊天。恢复时保留并备份节点私有状态、绑定和收据；本机归属记录丢失时先恢复其原备份，不通过编辑收据、猜测ID或新建替代会话绕过核对。

## SE按工作判断是否下放

普通Worker本来就可做研究、材料整理、测试执行和规划草案；SE只负责关键范围、接口和发布决定。无需为普通领取与提交增加委派表单。

独立复核、手工测试记录、测试运行请求，以及轻量/标准任务的验收与基线登记，可由SE明确授权具体Worker。面板提供任务、精确scope/version、当前输入锚点、动作和期限，默认授权一天；[模板](/templates/delegation-grant.json)最长30天。`GET /api/projects/{project}/delegations` 返回当前可见授权、精确任务锚点和候选受托者。

允许动作是 `criteria_review,review_resolve,run_request,manual_run,accept,merge,native,request_changes`。调用原 `/operations` 或 `/events` 时，在顶层加 `"delegation":"授权ID"`，其余原请求与证据要求保持。不会改变Worker项目角色，不能借授权管理成员、批准公共接口或发布其他任务。需要多任务测试时分别授权与运行，不将单任务授权扩成整套项目权限。

实现者/曾提交该任务成果者不能受托复核自己任务；不同身份不证明不同模型独立。严格任务的最终验收、基线处置保留给SE/人类。原验收项、测试、实际Git和运行门禁不会因为委派而跳过。撤销、过期、范围/成果变更会阻止后续新操作；已完成的相同请求可读回原回执，审计保留授权ID、操作者和结论。遇到权限、持久化、生产或未知影响，交回SE重新核定。

本机规则示例（Git Bash语法；路径、项目和SHA必须按本机真实值填写，示例不授予权限）：

```json
{
  "approved_commands": [{
    "project": "your-project",
    "role": "worker",
    "command": "\"G:/tools/python/python.exe\" -B \"G:/board-node/tools/task_board_client.py\" --profile \"$PROJECT_BOARD_PROFILE\" status",
    "cwd": "G:/your-project",
    "script": "G:/board-node/tools/task_board_client.py",
    "sha256": "REPLACE_WITH_ACTUAL_SCRIPT_SHA256"
  }]
}
```

需要发送评论、领取和交付时，本机维护者可另核准固定的客户端 `request --endpoint /api/operations --payload board-operation.json --out board-operation-receipt.json` 与 `post --event board-event.json --receipt board-event-receipt.json` 命令；Worker用文件填写冻结请求，API仍核对项目身份、范围和权限。不要把任意Shell或可变命令前缀列入规则。

公告板隔离项目API、身份引用和受管会话上下文；原应用的其他插件权限和操作系统文件权限仍由本机维护者配置。同一OS账号下的Agent不构成文件级硬隔离，强隔离应使用独立账号或容器及专用运行配置。
# 原生会话与用量补充

会话绑定必须保留运行时返回的原生 Session ID。Agent协作和任务详情提供统一目录，
可按ID、系统、机器、任务和角色搜索、复制、导出；绑定/任务/传输ID不能代替原生ID。
已有外部会话可用session_register登记并保留previous接续，未知保持未知，不能因此获得控制权。
节点包现含usage_collector；已识别Codex累计通知写入本机持久队列，按项目绑定归因，
断线重放同一样本。其他协议未识别字段保持缺采样，不猜测Token。详见[产品操作](/help/product)。

实际ACP的usage_update.used/size表示当前上下文占用与容量，不能当累计Token消耗。节点不据此编造input/output。协议口径见[ACP v1 prompt turn](https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/prompt-turn.mdx)。未显式指定日志路径时，节点将原生日志写到本次受控进程的证据目录，避免多个会话争用同一日志。
