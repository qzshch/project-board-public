# 项目自动化测试执行器

执行器可运行在项目工作站或server。公告板只管理请求、权限、租约、结果和证据，不在HTTP请求中执行命令。每个项目使用独立runner身份、代码仓库、临时目录和证据目录。

## 准备与批准

先从[独立执行器包](/runner-kit.zip)下载，解压到本项目非C盘目录。包仅含通用客户端/执行器、依赖说明与SHA清单，不含任何身份、运行数据或管理员入口；不需要复制公告板完整仓库。用本机Python 3.11+在非C盘环境安装requirements.txt，再执行tools/quality_runner.py。

1. 负责人登记不可变测试用例、自动化套件和任务测试计划。套件命令、环境与排他资源需要审核。
2. 负责人签发本项目身份，登记成员角色runner，再用runner动作授权相同环境标识。不要使用全局管理员身份运行执行器。
3. 在执行电脑准备已经含有固定Git提交的本项目仓库。由本机操作者检查套件命令并将manifest_hash填入本机runner-config.json的approved_suites。网络上的新套件不会自动得到本机执行授权。
4. 配置workspace为本项目仓库，scratch为独立临时根，output为正式证据目录。Windows均使用非C盘路径；scratch与仓库不得互相包含。配置与身份放Git外。

这是受信代码执行器，Git导出和进程组隔离不等于OS安全沙箱。只批准可信命令；不可信代码应另放专用OS账户/容器/隔离机器，不与其他项目或管理凭据共享磁盘权限。检查整个子进程链是否静默，不批准弹窗或启动脱离管理的后台服务的脚本。

## 请求与执行

用prepare-operations冻结run_request，tasks可一次关联多张卡，scopes逐一固定当前scope_hash，input_anchor为git:完整提交。执行器仓库缺少该提交时记录blocked，不改用默认分支或当前HEAD。

```sh
python client.py --profile <本项目身份> prepare-operations --action run_request --payload <已填写run-request.json> --out <证据目录>/run-request.json
python client.py --profile <本项目身份> request --endpoint /api/operations --payload <证据目录>/run-request.json --out <证据目录>/queue-receipt.json
python tools/quality_runner.py --profile <本项目runner身份> --config <本机runner-config.json> --run <运行ID>
```

持续监听本机已批准套件：

```sh
python tools/quality_runner.py --profile <本项目runner身份> --config <本机runner-config.json> --watch
```

--watch明确保持服务运行。无MagicDNS时加--connect-ip 100.64.0.10。执行器每5秒检查队列，只领取本机批准的套件；服务重启后可重新领取过期租约的运行。常驻实例应由本机服务管理器启动；Windows静默启动，server使用独立systemd用户服务，不能对项目公告板主服务另开副本。

## 实跑与留档

执行器导出固定Git版本，拒绝越界路径、链接和超限导出；使用隔离临时HOME/缓存/fixture，默认不继承其他环境变量或凭据。命令使用argv，不经shell。总超时、取消、续租失败和异常均终止自己创建的进程组/Windows Job，核对PID/创建时间并等待子进程退出。

输出逐用例退出码、耗时与状态；日志SHA清单、真实产物SHA、进程身份、环境与回执保存在output。临时导出和测试数据finally清理；失败日志和正式产物保留。若文件链接、占用或其他条件阻止清理，结果为blocked并记录具体遗留路径，不绕过保护。若回传无法确认，保留UNCONFIRMED.txt与原结果，不能在公告板声称通过。

失败、阻塞、超时和取消不会覆盖为通过。修复后新建运行；不要修改旧日志、删除失败用例或盲目重试直到一次成功。代码/任务范围/用例版本不同的旧结果不能代替当前验证。

新代码版本须先经获授权通道同步到执行器仓库；例如从本项目受控Git远端或经SHA核对的Git bundle更新。不能复制其他业务仓库作为依赖，不能让项目执行器取得全局Git/server管理凭据。

完整字段见[操作API](/help/operations)，填写模板见[模板目录](/help/templates)。

同一机器的多个项目执行器可在配置中指定同一个resource_root（Windows非C盘），用本机文件锁串行化相同资源名。锁文件仅使用资源名摘要，不透露其他项目身份；不可为解决排队而清理其他项目或共享锁缓存。服务收到SIGTERM/SIGINT后停止领取、终止自己正在执行的进程组、回传取消并清理，服务管理器应留至少45秒退出时间。


## 需求、接续与持续改进

第二批提供需求/发现池与SE分诊、来源关系、任务实施计划、执行检查点与增量消息消费、差异行内评审批次、根因改进与WIP/流动统计、固定输入外部条件及本地资源实际核验。入口为“需求与改进”、任务详情及原时间/质量/资产页。轻量任务无额外审批，旧任务显式采用后才增加实施门禁；换会话不自动释放资源。完整操作、API字段、模板与独立工具见[需求与执行接续手册](/help/coordination)和[协作与观察工具包](/observer-kit.zip)。
