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
2. SE在“代码与交付 → 仓库只读接入”申请server专属公钥，私钥只保留server。项目SE不需要server SSH或实例管理员身份。
3. **优先复用SE本机已有GitHub管理授权**：使用下述本机工具，通过已有 `gh` 登录或 Git credential helper 为绑定仓库登记同一server公钥，明确要求 `read_only=true`；GitHub凭据不传给公告板。也可到本仓库GitHub设置的 Deploy keys 添加面板公钥，**不勾选 Allow write access**，然后点击“我已登记公钥，核验并接入”。两者均无需另建token或找实例管理员。
   可选兼容方式：没有可复用登录且不采用手动登记时，由仓库有权者提供**只选当前仓库的fine-grained授权**，Administration读写仅用于登记公钥，在专用授权框输入。该框继续拒绝classic PAT；不向聊天、评论、普通表单或Git提交凭据。授权只在内存使用，不持久化；选择范围须在GitHub正确配置，平台不能反向证明它未选其他仓库。
4. server受控代理完成专属镜像、固定远端拉取、refs与真实对象核验并登记原Git审计链。新接入仓库由统一代理每60秒检查；旧项目专属同步器兼容保留。失败显示负责方和下一步，旧快照保留。网络响应未知时先按同一公钥核对，不重复创建。

原实现的卡点是：SE只能绑定仓库，读取器还依赖管理员手工配置私有镜像。现在授权成功后由受控代理填好这个接入，已有repo ID和Git证据门禁保持。SE拥有公告板项目权限不等于拥有任意GitHub仓库权限；外部仓库未授权时明确等待仓库有权者，不再要求实例管理员代建。

首次部署由平台运维核对GitHub known_hosts并安装统一受控同步代理，一次设置后无需为每个新项目编辑配置。旧的人工接入配置作为兼容路径保留。GitHub部署密钥的`read_only`语义及管理权限见[官方API](https://docs.github.com/en/rest/deploy-keys/deploy-keys)。

### SE本机最短路径

下载 [GitHub接入工具包](/github-kit.zip)，解压到项目的非C盘工具目录，安装包中 `requirements.txt`（Python 3.11+、psutil）。使用**本项目SE身份**执行，路径按实际替换：

```sh
python tools/github_connect.py --profile G:/项目私有目录/owner.json --repo main --evidence G:/项目接入记录/github
```

默认先复用有效 `gh` 登录，再尝试 Git credential helper；可用 `--credential-source gh` 或 `--credential-source git` 明确选择。不会自动登录、弹窗、生成token或推送代码。登录账号必须实际具有**目标仓库部署密钥管理权限**；能clone/push、仅持有SSH源码写权限或口头许可不一定足够。缺少权限时先核对本机账号/仓库授权，不要默认要求用户生成token或请公告板管理员代办。

工具只访问绑定仓库的GitHub元数据和部署密钥API；先核对同一公钥，存在则复用，网络结果未知时原命令重试，不重复建密钥。同一公钥已有写权限时不会自动删除或降权。完成后只把项目/仓库/公钥发给server；服务端用server私钥独立核验GitHub返回的**仓库身份、读取能力与明确只读拒写**。拒写检查只进行无输入的协议握手，不发送引用更新、对象包或执行仓库代码；连接错误、错误仓库、可写密钥和未知响应均不视为通过。实际refs/对象同步成功才显示 `ready`；同步失败可从原状态继续。

只读密钥的生命周期仍受GitHub规则影响：删除用于创建它的PAT或撤销OAuth授权可能连带删除部署密钥，不能承诺“立即撤销且接入不受影响”；变更授权后应重新核对接入状态。[GitHub官方说明](https://docs.github.com/en/rest/deploy-keys/deploy-keys)。

API：项目路径下 `/git-onboarding?repo=ID` 查询状态；POST `/git-onboarding/request`、`/sync` 载荷为`{repo}`；新 `/complete` 为`{repo,repository,public_key}`，只接受当前服务端绑定与公钥并独立核验，不接受“已只读”等客户端结论。`/authorize`兼容载荷为`{repo,grant}`，仍为敏感专用端点，禁止记录载荷。各路径均要求项目经理权限，不能跨项目使用；本机工具不需要server SSH、私钥或全局身份。GitHub授权与项目身份分别核对。

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


## 本地与server资料接手入口

缓存、调研、美术、归档、测试记录、日志、运行态和接手资料统一在“项目资产”的资源目录展示，原件继续留本地/server。任务详情可按任务进入，brief.resource_directory附带本角色可见的相关入口。核对机器、维护者、访问条件、内容版本/摘要与保留规则；目录登记不授予文件权限。详见[资源与接手手册](/help/resources)。


## 任务协作、逐项验收与回退

评论、阻塞求助和计划偏离在任务内登记，Worker自主选择是否等待，可在回复前提交候选；SE明确停止仍须遵守，问题核准和范围变更由SE处理；评论不改变范围或释放排他资源。结构化验收固定范围与精确输入，执行者声明、审核者逐项复核；Git祖先关系不替代最终提交测试。SE待办集中展示协作、交付与回退事项。回退先冻结影响并逐人确认，任务/模块追加新版本，代码/部署使用单独批准的项目执行器，不覆盖历史或给予实例全局权限。详见[协作与回退操作手册](/help/workflow)。
