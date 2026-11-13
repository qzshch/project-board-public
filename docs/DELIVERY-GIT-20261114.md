# GitHub提交追踪交付边界

用户要求项目对接GitHub、提供类似GitLens的提交追踪，同时缓存、调研、历史归档、美术资产、测试记录、日志、运行时内容保留本地/server。

冻结新增接口 git-tracking@1：项目内 `/git` 读写；Git追踪schema1。写请求request_id/expected_revision/action/payload，在项目SQLite中串行追加SHA审计，原任务/治理/operations/APIv2保持兼容。来源和消费者为server同步器、Web、标准库Agent客户端；GitReader只接收固定Git参数，网页不能配置主机、路径或命令。UTC秒与ISO时间，提交40位SHA；错误400/403/404/409/413/502/503。任务、测试与资产均按本项目权限和固定SHA关联；不自动改变交付/验收状态。

交付包含：多仓库绑定；仓库专属只读部署密钥与server定时拉取；拓扑父子图与合并、分支/标签、提交详情、统计/差异、两版本比较、文件历史和逐行归属；固定SHA分页；非快进与同步失败审计；项目本地保留策略、gitignore模板和提交前只读检查；同步操作手册；独立fixture正反例、桌面手机浅深色、server真实私有仓库读取与重启/备份/回滚验证。

不执行git add/commit/push，不上传本地数据、不改业务项目仓库或历史，不自动复制LFS媒体，不把Git作者声明当工作量/验收。PR/Issue流程与IDE编辑不在本轮范围。
