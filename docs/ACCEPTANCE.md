# 本轮实际验收（2026-11-13）

本项目独立仓库的实跑证据，不借用旧位置76项通过。原交接与legacy-v2历史保留，不改写原业务任务或事件。

| 范围 | 本轮结果 | 本机证据 |
|---|---|---|
| 基线 | 26份参考文件逐字节SHA复核；独立private远端已建立 | evidence/independence-20261113/BASELINE.json |
| 独立回归 | 85项通过，无失败/错误/跳过；含原状态机/权限兼容和新增治理/资产/交付反例 | evidence/checks/20261113-191302/RESULT.json及stderr.log |
| 空安装 | 真实空状态启动/新建项目/专属身份/领取/重启/原回执读回，7项通过；临时状态与服务已清理 | evidence/standalone/20261113-191411/RESULT.json |
| 迁移 | 停服一致性完整备份、独立候选启动、原代码原状态真实回滚、再次切换及完整重启 | evidence/migration/20261113/MIGRATION.json |
| 原历史 | dhy仍330任务/335事件，head df30c6125fae27a53bb9ba721c20922b00caa8c83ea4b16ac5e339506e4a19e6；原凭据作用域/回执保留 | migration与live结果 |
| GUI | 实际Edge 1280/375、浅/深色；18项通过，表单保存、分类、图、切项目与撤权清空；无JS错误/横向溢出；辅助进程归零 | evidence/ui/20261113-191207/RESULT.json及截图 |
| 全新项目/角色 | onboarding-20261113-190645；研究、开发、文档、测试四角色通过真实server执行13次操作；有实际失败测试→返修→重提→审核→Git分支合并→运行验收→SE接受交接 | evidence/drill/20261113-190645/RESULT.json、各原始角色结果、artifacts.bundle |
| 独立可重跑测试产物 | bundle包含真正可执行的tests/label/test_normalize.py；独立测试角色在server运行该文件，对合并后源码SHA进行4项行为/反例检查 | demo-test-generate与Git bundle |
| 契约影响 | 未确认切换409；直接/反向/耦合范围固定；各相关角色确认后执行；旧版本与提案审计保留 | 治理回归及drill原始结果 |
| 共享资产 | 审核受众、不可变版本、提供方更新不浮动消费、显式升级/弃用/撤回；每任务另锁真实版本/SHA，项目alias升级不改旧任务，撤回检查旧锁 | 回归与evidence/live/20261113-191205/RESULT.json（13项） |
| 交接与清理 | 接受后原owner管理降权；临时执行身份撤销，只保留项目专属继承owner；server临时文件和本地工程脚手架已清理，正式源码历史保留bundle | drill结果与processes.jsonl |

本轮早期失败记录保留：一次脚本把Git正常stderr误判为失败；一次远端Tailscale读请求暂时不可达，后续无凭据健康探测确认服务/转发正常；另一次全流程已完成后Windows只读Git对象清理失败，已验证bundle后按精确归属清理并单独记录恢复。未删除失败断言或改写旧结果。最新成功演练已运行提交的真实测试文件，且finally清理完整。

`legacy-v2/test_handoff.py` 与原check_board_delivery.py是dhy专项foundation门禁，不纳入通用依赖；新通用tools/check_delivery.py用真实范围、基线、项目、身份、回执、版本/资产锁和允许路径验证，具有独立正反例。

不宣称历史任务包已全部拆成已完成原子任务：本轮仅对公告板17项新升级逐项核定和验收；原dhy任务包仍保留原状态/证据，新图将未核定关系标未知。新项目角色/API授权不构成同Windows账户的文件隔离。

最终代码提交、正式URL验证、任务回执/里程碑完成登记、server逐文件SHA校验及最终资源核对以 evidence/release/20261113/RELEASE.json 为发行清单。私有恢复包和身份只交付位置，不进入源码/普通Agent包。
