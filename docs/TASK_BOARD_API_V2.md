# 多项目公告板 API v2

本文件是通用接口规范，不包含任何项目的任务、项目列表、成员、密钥或资源。可从服务 `/api-docs.md` 获取；客户端脚本为 `/client.py`。接入其他项目无需获得某个业务项目的 Git 仓库权限。

## 认证与范围

项目接口统一为 `/api/projects/{project_id}/...`，project_id 为2～48位小写字母、数字、连字符，以字母开头。每份 Agent/项目审核者凭据固定属于一个项目。身份通过 `Authorization: Bearer <私有凭据>` 或已兑换的一次性项目网页会话传递；凭据不放在 URL、交付记录、日志或命令行中。

服务端先验证身份与项目权限，再读取任务/历史/回执、处理ETag或执行写入。Agent 更改 URL、profile 的 project_id、查询参数或提交正文，不能扩大授权。其他项目与不存在项目统一返回404，且不返回任务、项目名称、计数或ETag。本机来源、Tailscale 用户身份及网络连通本身均不授予项目权限。

| 身份 | 可见项目 | 能力 |
|---|---|---|
| 未认证 | 无 | 仅通用静态页、health、客户端及本规范 |
| Agent | 自己的一个项目 | 读范围/任务/历史/回执，领取、进度、交付、说明、范围建议 |
| 项目审核者 | 自己的一个项目 | 项目内建卡、派发、审核、返修、合入/运行验收，签发普通Agent |
| 全局管理员 | 全部项目 | 建项目、签发项目审核者，访问并管理各项目 |

项目审核者不能创建全局项目或签发其他审核者。Agent不能自我验收、合并或选角色。传输头不接受调用者声明的actor/role/project作为授权。Bearer优先于cookie，不将两个身份的权限合并。网页会话8小时，项目票据一次性、24小时内兑换；撤销身份立即使后续请求和其会话失效。已下载内容无法通过撤销从调用者电脑远程抹除。

## 项目接口

以下路径需认证，除特别说明均返回JSON；项目端点的JSON带 `project_id`。项目任务标识只在本项目内唯一，同名task/actor在不同项目互不影响。

| 方法 | 路径 | 权限及返回 |
|---|---|---|
| GET | `/api/me` | 当前身份的role、global_admin和绑定project_id，不返回密钥 |
| GET | `/api/projects` | 只列当前身份可见的项目，Agent结果只有自己的项目 |
| POST | `/api/projects` | 仅全局管理员；正文 `{id,name,description}`；创建独立空项目，201；重复ID409 |
| GET | `/api/projects/{p}` | 本项目名称、说明 |
| GET | `/api/projects/{p}/me` | 本项目角色与当前身份 |
| GET | `/api/projects/{p}/connection` | 服务地址、可选Tailscale连接IP；不含凭据 |
| GET | `/api/projects/{p}/snapshot` | 当前项目的全部任务投影与事件head，支持ETag/304，ETag含项目命名空间 |
| GET | `/api/projects/{p}/task?id={task}` | 单个任务当前范围/版本/负责人/状态/问题 |
| GET | `/api/projects/{p}/history?task={task}&after=0&limit=200` | 本项目追加历史；after为事件seq游标，limit上限1000；可省task |
| GET | `/api/projects/{p}/receipt?id={event_id}` | 指定事件及同一读快照的当前任务，供交付门禁验证 |
| GET | `/api/projects/{p}/verify` | 项目审核者/管理员校验本项目事件链与重放投影 |
| POST | `/api/projects/{p}/events` | 追加事件，201；权限、owner、revision及scope均由服务验证 |
| POST | `/api/projects/{p}/actors` | 审核者签发普通Agent；全局管理员还可签发reviewer；正文 `{actor,role?}`；响应含一次签发的私有token，不可记录/转发 |
| POST | `/api/projects/{p}/actors/revoke` | 项目审核者/管理员；正文 `{actor,reason}`；撤销本项目该身份，历史保留 |
| POST | `/api/projects/{p}/enroll` | 需该项目单独邀请码；正文 `{actor,join_key}`；只可登记agent，不支持角色字段 |
| POST | `/api/projects/{p}/access` | 已认证项目身份；正文 `{}`；返回一次性ticket，CLI保存为私有网页入口，不打印ticket |
| POST | `/api/projects/{p}/session` | 正文 `{ticket}`；兑换项目ticket，HttpOnly SameSite会话cookie；不能兑换全局ticket |
| POST | `/api/session` | 仅兑换全局管理员ticket；项目ticket不能升级为全局会话 |
| POST | `/api/logout` | 注销当前网页会话 |

兼容旧单项目接口 `/api/snapshot`、`/api/events` 等时，固定映射到原项目 `sampleapp`；不会根据调用者或query切换项目，其他项目凭据访问这些旧路径会被拒绝。新客户端必须使用项目路径。

## 事件契约

```json
{
  "request_id": "调用者预先生成并持久保存的UUID",
  "task_id": "plan/EXAMPLE",
  "action": "submit",
  "expected_revision": 3,
  "scope_version": 1,
  "payload": {
    "summary": "本轮实际交付摘要",
    "completeness": "partial",
    "deliverable_ids": ["D1"],
    "implementation_commit": "40位Git提交SHA，例子中占位文字须替换",
    "evidence": [{"path": "本项目负责人可访问的证据位置", "sha256": "文件的64位SHA256"}],
    "tests": "实际执行的测试、结果和适用范围",
    "remaining": "未完成项和具体依赖",
    "addresses": []
  }
}
```

`claim/progress/note/scope_proposal` payload为 `{summary}`。`submit` 必须由本卡owner执行，只能声明约定D项，completeness为partial/full；full须覆盖当前全部交付项。研究交付也固定承载研究记录的Git提交，不将未知结果声称通过。

审核操作仅reviewer：`create`需 `{spec,reason}`，初始expected_revision=0；spec含id/title/kind/description/deliverables，及可选parents/depends_on/allowed_paths/registered/claimable/source/priority。registered的plan需 source.packet_sha256 和 source.base_commit。`scope`以完整spec和reason追加新范围版本；`assign`需 `{owner,reason,registered?}`。`accept`需 `{submission,summary,deliverable_ids,evidence}`；`request_changes/reopen`需 `{submission,reason,findings:[{description,acceptance}]}`；`merge/native`需 `{submission,summary,commit,evidence}`。native代表卡中定义的运行环境验收，不自动解释为任一项目全部完成。

成功回执含 event_id/event_hash、revision、scope_version、project_id。同一身份、同一request_id、同一正文重试返回原回执，不重复追加；同ID不同正文409。不同项目使用各自独立的幂等空间。过期revision/scope为409，调用者重新读取并判断，不能自动改版本覆盖他人更新。返修重提的addresses引用本项目原问题ID；重提不自动关闭问题，root/审核者通过才关闭。

所有project/task/parent/dependency/actor/receipt都只在当前项目解析。证据path与hash是交接声明，服务不读取任意本机文件、不代理下载或自动共享原件；原件必须按该项目的资源/归档权限另行提供。交付声明不等于代码/资源/生产或运行验收通过。每个项目自行定义代码、资产与测试门禁，通用公告板不强制任何特定业务的基础API。

## 可移植CLI

负责人签发含 url/project_id/actor/token 的独立私有profile。仅下载通用脚本和本规范即可接入。示例均为占位路径/ID，实际目录位于本机非C盘、Git外。

```powershell
python -B -X utf8 task_board_client.py --project <项目ID> --profile <私有profile.json> projects
python -B -X utf8 task_board_client.py --profile <私有profile.json> task <任务ID>
python -B -X utf8 task_board_client.py --profile <私有profile.json> prepare --task <任务ID> --action submit --payload <payload.json> --out <event.json>
python -B -X utf8 task_board_client.py --profile <私有profile.json> post --event <event.json> --receipt <Git外receipt.json>
python -B -X utf8 task_board_client.py --profile <私有profile.json> portal --out <Git外私有入口.html>
python -B -X utf8 task_board_client.py --profile <私有profile.json> flush
```

客户端核对profile项目与显式 `--project`，服务器再独立核对凭据授权；编辑profile绕不过服务端。断网队列为profile旁 `outbox/{project_id}/{actor}/`，先保存再发送，409保留原请求。原v1无project_id的profile仅继续用于原项目，旧outbox路径保持兼容。无MagicDNS的Tailscale机器可加 `--connect-ip <该服务Tailscale地址>`，保留正确域名Host；不能将其他公网HTTP地址用作凭据目标。

## 错误、传输与隔离边界

400输入格式错误；401无效/过期身份或邀请码；403本项目角色不足；404项目不可用/未授权或本项目记录不存在；409范围/版本/归属/幂等冲突；413请求超限；415非JSON写入。写入为有长度的JSON，最大64KiB，不接受重复JSON字段、NaN或跨站Origin。无CORS；静态文件白名单与CSP继续生效。health与静态接口不返回当前项目目录。

API权限隔离不能限制同一操作系统账号直接读取磁盘、Git仓库或管理员凭据。需要文件级隔离时，调用者必须运行在独立OS账号/容器和相应目录ACL内；服务端状态与管理凭据不可挂载给项目Agent。跨电脑Agent只发对应项目profile，不共享整个状态目录、管理员入口或其他项目仓库。已有文件管理权限不会因为这次API升级自动收回。


第三批操作入口：参见 [规划与操作收敛](/help/convergence)。线上 `/help/convergence` 公开提供角色操作说明；项目数据和写入仍鉴权。框架与规划页集中批量草案及固定模板，治理页复用批准规则，任务详情登记尝试/会话、读取有来源的接手包，SE待办集中下一步。严格限定原方案四组补齐，不引入跨项目调度或Agent托管。
