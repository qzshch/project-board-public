# 项目专属执行说明（负责人填写）

通用操作指南：http://example-server.example-tailnet.ts.net:18785/help/agent 。正式服务在server，旧PC地址已停用。本说明与项目专属身份分开交付，不包含管理员入口。

- project_id / API base：从本项目brief复制；服务入口与profile授权必须一致。
- 原子任务ID、执行角色、scope_version / scope_hash：从当前卡复制。
- 可读材料：标题、固定版本、位置、SHA256；只能交付本项目已授权内容。
- 基线：完整Git提交；输入来源与SHA；实际取得方法和验证结果。
- 允许写目录：工程相对路径；禁止修改其他范围。
- 固定接口：id@version，签名、单位、错误、事务、幂等、owner。
- 固定资产：本项目alias、producer/id@version、SHA、许可/敏感性。
- 排他资源：设备/端口/数据库/公共入口；谁持有、何时归还。
- 公共修改：先scope_proposal；接口走影响提案，由相关owner/SE确认。
- 测试：行为与反例；独立状态/端口；失败证据不删。
- 证据：实现提交、输入与输出SHA、测试日志；不要放凭据。
- 回执：claim/submit/返修重提的服务事件ID、哈希和current_submission_id。
- 返修：引用open finding ID，重提不自动关闭，等待审核。
- 清理：静默子进程，记录PID/创建时间/命令，finally清理自己的临时文件/进程。

项目身份由负责人通过私有渠道单独签发。不能索取全局管理员身份；API权限不替代操作系统隔离。领取成功后再执行；未取得输入或冻结版本时报告未知并暂停依赖部分。
