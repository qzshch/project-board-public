# GitHub 与代码提交追踪

“代码与提交”页追踪 GitHub 仓库中的实际提交，展示父子关系、合并、分支、标签、作者、日期、说明、变更统计、固定版本差异、文件历史和逐行溯源。Git 作者身份是提交中的声明，不自动证明实际执行者或工作量。GitHub 仓库绑定不会创建远端，也不会暂存、提交、推送或上传项目目录。

## 源码与本地/server资料分开

Git 中保存审核纳入的源码、构建声明、操作说明、测试代码和刻意编写的小型可复现 fixture。缓存、原始调研、历史归档、美术原件及媒体、测试执行记录、日志、数据库、运行状态、下载与构建产物留本地/server。测试代码与测试运行记录是两类东西。

任务、测试运行和资产登记只引用所需的位置、固定版本和 SHA；不复制原文件到 GitHub。私有位置与摘要也可能敏感，只在该项目授权范围记录。公开文档与可提交的代码注释不要写私有证据位置；跨项目共享仍走资产发布审核，不因仓库接入自动开放。

默认规则见[可下载gitignore模板](/gitignore.txt)。每个仓库仍需人工将相应规则纳入自己的 `.gitignore`；页面管理存储规则不修改远端。项目可添加本地保留模式，对必须纳入的单个小型运行资源/fixture可逐文件给出审核依据；身份、state、runtime、.env等不能用例外放行。

提交前运行本地检查（检查已跟踪/已暂存路径，不修改索引）：

```sh
python tools/check_git_boundary.py --repo <本项目仓库> --out <本地或server证据目录>/git-boundary.json
```

检查拒绝后，将真实数据保存在本地/server，再由负责人决定如何整理索引。`.gitignore`不会删除已有Git文件或历史；此工具只告警，不删除本地文件、不重写Git历史。若已有敏感内容进入Git，需单独处理泄漏和凭据撤销，不能靠忽略规则宣称已清除。

## 接入与权限

1. 项目负责人在“管理资料”绑定仓库ID、GitHub `owner/name`、显示名称和依据。支持多个仓库，仓库ID不可改绑为另一个远端；换仓库时新建ID并停用旧ID，保留历史。
2. 实例管理员配置server专用裸镜像与该仓库的**只读部署密钥**。每仓库一把密钥；不复制个人全局GitHub私钥或PAT到server，不把令牌、密码、凭据位置填入项目表单。
3. 管理员私有 `state/_private/github.json` 中 `projects[project_id][repo_id]` 为 `{repository:"owner/name",key:"<本实例_private下的密钥文件>"}`。签发项目身份并授予 `tracker` 角色；该角色不能开发任务、改变治理或运行测试。
4. server启用项目专用 `tools/github_tracker.py --state <server状态根> --project <项目ID> --profile <本项目tracker身份> --watch`。只读拉取每60秒一次，手动请求5秒内检查。网络失败保留旧快照和失败状态；没有成功时间不宣称已接入。

镜像在 `state/git-mirrors/<project>/<repo>.git`。此位置自身属于运行态，不上传Git。同步只拉 GitHub已存在的对象与引用，不读取/上传项目的本地资料，不执行仓库代码或子模块，也不自动拉取Git LFS媒体；密钥须在GitHub登记为 `read_only=true`。server主机密钥由管理员核对可信GitHub指纹后加入SSH known_hosts，不能关闭验证。

同步器为受信本机程序，不是OS沙箱。实例内磁盘隔离仍由server账户/目录权限负责。源码也受项目读取授权，已获公告板项目读取权的成员可读该项目镜像；项目管理员应使其与仓库保密范围一致。撤销项目凭据立即阻止新查询，停用仓库后不再提供其代码；镜像保留用于受控审计，不自动删除。

## 使用与关联

选择仓库与分支/标签，历史固定为当次完整SHA；后台同步不会使正在浏览的分页漂移，点击“查看最新提交”才更新。可按提交说明、作者和文件路径筛选。提交详情可查看父提交、分别对比合并的父版本、变更文件、逐行来源及GitHub链接。版本比较是两个快照的直接差异，不是自动合并/验收结论。

任务的 baseline/implementation/merge/native SHA、测试固定Git输入和候选资产来源自动与相同提交关联，均仅来自本项目。负责人还可显式关联提交到任务当前范围并说明依据；范围变化后旧关联标历史。消息中写任务ID不自动构成验收，未匹配的提交显示无关联。

已误跟踪的本地保留路径显示告警，默认不读取正文/差异。同步检测分支非快进变化并保留记录，不能把强推抹掉的可见提交误称为未发生；旧对象不自动清理。仅追踪Git元数据与代码，不托管PR审查、Issue同步或GitLens的IDE内联编辑功能。

## API v1

所有路径先按项目鉴权，前缀 `/api/projects/{project}/git`。

GET 根为仓库、策略、同步状态和追加记录版本；GET `/verify` 验证本项目Git审计链。GET `/log?repo=ID&ref=完整SHA或已同步引用&offset=0&q=&author=&path=` 每页50；返回固定anchor与next。GET `/commit?repo=&commit=SHA`；`/compare?repo=&base=SHA&head=SHA`；`/patch?repo=&base=SHA或空树&head=SHA&path=`；`/tree?repo=&head=SHA&path=`；`/blame?repo=&head=SHA&path=&start=1` 每页200行。Git查询12秒、结果限额，超限显示413；网络失败502，未配置409，越界/类型400，正文保留策略403，越权404。

POST 根采用 `{request_id,expected_revision,action,payload}`，同身份同请求幂等、版本冲突409、不自动覆盖。action：bind `{id,repository,title,reason}`；enable `{repo,enabled,reason}`；sync_request `{repo,reason}`；policy `{patterns:[],exceptions:{相对路径:依据},reason}`；link `{repo,commit,task,scope,reason}`；sync_result仅同步器/经理，含固定绑定和请求号、已实际镜像的refs、default_branch、alerts、rewritten、error。所有写入与任务串行事务，原事件链不改写。网页不接受命令、磁盘路径或Git凭据。

后台未变化的轮询只更新本地检查时间，不每分钟复制完整审计快照；引用、错误状态、策略或显式请求变化才追加Git事件。检查时间是运行观测，不代替不可变提交与审计链。提交元数据采用一次批读取，避免每个列表行独立启动Git。

实现依据：[Git log](https://git-scm.com/docs/git-log)、[Git blame](https://git-scm.com/docs/git-blame)、[GitHub部署密钥](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)。

CLI冻结和发送：`python client.py --profile <本项目身份> prepare-git --action bind --payload <已填写git-binding.json> --out <证据目录>/git-bind-request.json`，再使用`request --endpoint /api/git --payload <原请求文件> --out <回执文件>`。绑定、存储边界、任务关联和同步请求模板均在[模板目录](/help/templates)。

本产品既有的legacy-v2参考快照与原始交接/验收记录也按此规则保留到本地/server，当前源码只留交接索引与验收流程；原件及SHA映射由管理员保管，既有Git历史不改写。路径检查不能替代内容、许可和密钥审查。
