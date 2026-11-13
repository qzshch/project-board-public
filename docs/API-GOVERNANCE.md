# 增量治理API（产品3，治理schema 1）

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

task_spec新增可选work，包含category、role、inputs_known(bool)、inputs/outputs/contracts/assets/resources/couplings(string[])、baseline(Git40位)、acceptance。不重写旧任务spec。新任务建议kind=atomic；任务包在governance.packages单独登记。旧任务仍使用原状态机，但队列显示历史/未知，不自动推断原子工作。

治理事件与任务写入共用一个项目库的BEGIN IMMEDIATE，防止不同任务并发穿透冲突检查；治理请求按actor/request_id幂等，expected_revision防覆盖。契约版本存不可变清单；提案冻结scope_hash与反向影响，确认者、迁移/测试和执行追加留痕。共享发布清单存目录库，受众在服务端过滤，私有源路径不进入发布载荷。所有SQLite库需停服务后作为整体备份或使用受控一致性流程，不能只复制运行中的主文件。

公开文档不包含项目快照、密钥或管理员入口。API授权不构成同Windows账户间的文件隔离。
