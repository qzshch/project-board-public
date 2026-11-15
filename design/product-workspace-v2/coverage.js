'use strict';
// Inventory from the current product's UI/actions. A destination is a design
// commitment, not a claim that every old workflow is implemented in this mock.
const continuityRows=[
 ['项目定义','背景与目标','背景、目标、非目标、约束、历史说明','项目概览 / 资料与里程碑','更新项目资料、保留来源','workspace.js / governance.py','示意待补'],
 ['项目定义','材料与入口','材料原件、版本、SHA、入口、角色可见范围','资料与里程碑 / 项目资产','登记、更新、定位原件','workspace.js / resources.js','示意待补'],
 ['规划','模块完整定义','目标、路径、职责、非目标、输入输出、未知项、风险','规划与依赖 → 模块详情','新增规划版本、核对当前评审失效原因','planning.js','字段保留待交互'],
 ['规划','规划调研与决定','规划前置调研、模块依赖、结论与来源任务','规划与依赖 → 规划依据','调查、记录决策、逐步展开','planning.js / coordination.js','字段保留待交互'],
 ['规划','接口冻结与变更','版本、签名、单位、错误、事务、幂等、消费者、兼容','规划与依赖 → 接口与影响','冻结、提出变更、逐人确认影响与迁移','workspace.js / governance.py','字段保留待交互'],
 ['规划','里程碑与阶段验证','目标、达成路径、进入条件、方法、阈值、环境、负责人、计划、实际证据','资料与里程碑 → 阶段验证','登记计划、记录阶段检验、回读当前范围','planning.js','示意待补'],
 ['规划','关联规划草案与批量审议','草案版本、来源引用、选择项、预览摘要、证据','规划与依赖 → 草案','保存、预览、批准原子发布、退回','convergence.js','字段保留待交互'],
 ['规划','流程模板','不可变模板、参数、敏感性、消费版本','规划与依赖 → 模板','核定、实例化草案、撤回、显式导入','convergence.js','字段保留待交互'],
 ['依赖图','多模块与任务规模','模块包含、完整节点计数、搜索、聚合、跨模块边界','规划与依赖 → 关系图','12模块/1200任务演示；聚合、全量、局部、表格','workspace.js / graph-layout.js','新增交互原型'],
 ['依赖图','不同关系语义','硬前置、产物、接口、共享修改、排他资源、条件门、固定资产','关系图 → 图层与节点详情','分层筛选；硬依赖成环与耦合分开核定','governance.py / coordination.py','新增交互原型'],
 ['依赖图','真实解锁与估算','成果类型、审核状态、代码基线包含、缺失估算、范围版本','关系图 / 任务详情 / 时间与效率','解释领取与验收阻塞；不把可达关系当旧测试覆盖','dependencies.py / timing.py','字段保留待交互'],
 ['任务','任务包与原子任务','分类、角色、层次、交付物、历史映射、是否发布','任务与验收','创建范围、编辑草案、领取；不把包等价全部完成','app.js / finishing.js','示意待补'],
 ['任务','执行范围与冲突','scope/version、基线、读写路径、输入输出、接口、资产、排他资源','任务详情 → 范围','原子核对领取、拒绝越界、范围追加版本','governance.py / store.py','字段保留待交互'],
 ['任务','候选与最终交付分离','成果、工作记录、结论、证据、待审条件、来源性质','任务详情 → 交付','提交候选、返修、验收、合入、运行验收','workflow.js / assurance.py','示意待补'],
 ['协作','评论、阻塞和偏离','自主等待、SE停止、未读、回复、明确决定、执行者确认','我的工作台 / 任务详情 → 讨论','开线程、回复、决定、确认、解决；不自动改范围','workflow.js','字段保留待交互'],
 ['协作','结构化验收','默认完成清单版本、稳定标准ID、精确输入、声明、逐项结论','任务详情 → 验收矩阵','声明、批量复核；旧发现不能丢','workflow.js / finishing.js','字段保留待交互'],
 ['协作','逐条发现与增量评审','严重/阻塞、锚点、修复或异议、修复提交、复核运行、历史继承','任务详情 → 评审','提出、处置、独立核准、差异行内分批复核','workflow.js / coordination.js','字段保留待交互'],
 ['协作','回退工作流','任务/模块/代码/部署、影响快照、所需确认、执行器、证据','任务 / 模块详情 → 回退','预览、确认、批准、执行、失败/失联恢复、验收应用','workflow.js','字段保留待交互'],
 ['接续','尝试、工作区与租约','执行者、分支、机器、写路径、资源、租约、候选选择','任务详情 → 执行与接续','启用、领取、续租、失败、取消、恢复、选择候选','convergence.js','字段保留待交互'],
 ['接续','会话与上下文包','实际会话引用、前序、模型声明、检查点、固定版本、变化游标','任务详情 → 接手包','附接、接续、增量消费；失联不自动释放共享资源','coordination.js / convergence.js','字段保留待交互'],
 ['治理','分级风险与批准规则','项目默认、当前scope风险、适用路径/类型、冻结引用、有效期、失效条件','项目设置 → 治理 / 任务风险','核定、沿用、撤回、升级；未知不自报低风险绕过','operations.js / convergence.js','字段保留待交互'],
 ['治理','角色与继承','成员、职责、Actor类型、可见范围、交接说明','项目设置 → 角色与权限','授予/撤销项目身份、继承交接；不转发全局凭据','workspace.js / projects.py','示意待补'],
 ['质量','完整用例库','版本、优先级、目标、前置、输入、步骤、预期、环境、退役','测试与质量 → 用例','创建版本、选择测试计划、退役','operations.js / quality.py','示意待补'],
 ['质量','实际测试运行','固定输入、scope、真实环境、逐例结果、退出码、时长、产物SHA','测试与质量 → 运行详情','请求、排队、读取、取消；失败和重试保留','operations.js / quality.py','示意待补'],
 ['质量','自动套件与执行器','本机批准摘要、命令白名单、超时、资源、产物路径、租约','测试与质量 → 套件与执行器','批准、授权、续租、取消确认；HTTP不执行任意命令','quality.py / quality_runner.py','字段保留待交互'],
 ['质量','外部条件与观察器','CI/PR/人类/时间门、固定输入、TTL、授权、当前有效性','规划与依赖 → 条件门 / 测试与质量','建立、观察、过期、确认、替代','coordination.js','字段保留待交互'],
 ['Git','绑定与首次接入','仓库ID、owner/name、授权状态、镜像、可信主机、同步回执','代码与交付 → 仓库接入','下一轮补SE自助的受控接入；现有管理员私有配置门禁仍在线','git_tracking.py:mirror / GITHUB-GUIDE.md','新增交互原型'],
 ['Git','提交与引用','分支/标签、搜索、作者、提交图、强推或改写告警','代码与交付 → 提交','同步请求、引用选择、真实提交查询','git.js / github_tracker.py','示意待补'],
 ['Git','文件与差异溯源','文件树、内容、比较、blame、任务/运行/资产关联','代码与交付 → 文件与差异','浏览、比较、行内评审、原件定位','git.js / git_reader.py','示意待补'],
 ['Git','证据精确核验','仓库、基线、实现、测试、评审、合入、部署锚点','任务详情 → Git核验','逐阶段核对；rebase/squash等映射或重验','workflow.py / git_tracking.py','字段保留待交互'],
 ['资产','本地/NAS目录','缓存、调研、美术、归档、测试记录、日志、运行态、机器、权限、保留','项目资产 → 资源目录','登记、版本/可变性、原件完整性、可达性、退役','resources.js / resources.py','示意待补'],
 ['资产','实际资源核验','观察者授权、入口摘要、观察SHA、状态、TTL与失效原因','项目资产 → 可用性','本机观察、读取受控结果；目录登记不等于授予文件权限','coordination.js','字段保留待交互'],
 ['资产','沉淀与跨项目复用','候选、提炼、适用/不适用、许可/敏感性、验证、不可变版本、消费锁','项目资产 → 资产沉淀','提炼、验证、私有发布、显式审核共享、撤销/弃用影响','operations.js / learning.py','字段保留待交互'],
 ['资产','复用反馈与成本','实际接入工时、预估节省、问题、来源任务和消费者','项目资产 → 使用反馈 / 复盘','记录事实与假设，不将预估收益当实测','operations.js','字段保留待交互'],
 ['时间','时段与校正','投入/等待/暂停/返工、原因、阶段、人员/Agent、开始结束、校正依据','时间与效率 → 工时明细','记录、停止、核定完整、校正；空白不为零','operations.js / timing.py','示意待补'],
 ['时间','估算与期限','低/中/高、规模、不确定性、工具环境、due、历史重估','时间与效率 → 估算','当前scope估算与实际比较，历史记录保留','operations.js / timing.py','字段保留待交互'],
 ['时间','路径与校准','硬依赖估算路径、未知项、自动运行成本、等待、P50/P80、固定共享基准','时间与效率 → 分析','样本不足不输出精确预测；不并入自然历时','operations.js / timing.py','字段保留待交互'],
 ['改进','根因、WIP与流动','返工根因、首次返修率、评审排队、覆盖、WIP限制、改进假设与实效','项目复盘 / 工作台','核定、关联任务/用例/资产、验证改进','coordination.js','字段保留待交互'],
 ['Agent','人类与项目身份','独立人类登录、全项目读取、Agent Bearer边界、密码/会话','全局账户 / 项目设置','登录、退出、改密；Agent不能继承浏览器人类Cookie','human_auth.py / login.js','示意待补'],
 ['Agent','接管诊断与最短路径','当前角色真实卡点、规划/基线/环境/材料、下一步','我的工作台 → 就绪诊断','自助SE创建、Worker加入、保留冻结幂等重试','readiness.py / finishing.js','示意待补'],
 ['Agent','节点、运行时与受管会话','项目/根/角色/模型、本机策略、创建/原会话接续、未知结果与本机归属','Agent协作 → 节点与会话','一次配对、能力探测、派发、通知、停止、保守恢复','agent-console.js / orchestration.py','示意待补'],
 ['Agent','有界委派','任务、当前输入、动作、受托者、期限、撤销、审计','Agent协作 → 委派','授权/撤销独立复核；自签和严格最终动作继续拦截','delegation.py / agent-console.js','示意待补'],
 ['新需求','需求、缺陷与Token新模型','产品目标、版本变更、任务覆盖、缺陷复测、用量口径与覆盖','需求池 / 缺陷池 / 时间与效率','v1保留交互，并用本轮承接核对补设计；不宣称生产实现','product-workspace-v1/guide.html','新增交互原型']
].map((r,i)=>({id:'KEEP-'+String(i+1).padStart(2,'0'),group:r[0],title:r[1],fields:r[2],destination:r[3],actions:r[4],source:r[5],prototype:r[6]}));
function renderCapabilityCoverage(){const rows=continuityRows;$('page').innerHTML=header('旧版承接核对','减少首屏噪声，不减少字段、审计、门禁或可执行操作。',btn('阅读补充设计','design-section','data-section="continuity"','primary'))+`<div class="notice warning">v1并未完整展示旧能力。下列${rows.length}项是对照源码列出的承接要求；“保留待交互”不等于已经在原型中实现。上线前需逐项以实际入口、读写和反例验证。</div><div class="toolbar"><input id="coverage-query" type="search" aria-label="搜索承接能力" placeholder="搜索回退、冻结、用例、Git、租约…"><label><span class="sr-only">承接分类</span><select id="coverage-group"><option>全部分类</option>${[...new Set(rows.map(r=>r.group))].map(g=>`<option>${g}</option>`).join('')}</select></label></div><div id="coverage-rows"></div>`;function draw(){const q=$('coverage-query').value.toLowerCase(),group=$('coverage-group').value,visible=rows.filter(r=>(group==='全部分类'||r.group===group)&&Object.values(r).join(' ').toLowerCase().includes(q));$('coverage-rows').innerHTML=`<div class="filter-note">${visible.length} / ${rows.length} 项 · 来源与目标入口可展开核对</div><div class="table-wrap"><table aria-label="旧版能力承接清单"><thead><tr><th>已有能力</th><th>新入口</th><th>原型覆盖</th></tr></thead><tbody>${visible.map(r=>`<tr><td><button class="item-title" data-coverage="${r.id}">${esc(r.title)}</button><span class="small muted">${r.id} · ${r.group}</span></td><td class="small">${esc(r.destination)}</td><td class="small">${esc(r.prototype)}</td></tr>`).join('')}</tbody></table></div>`;} $('coverage-query').oninput=draw;$('coverage-group').onchange=draw;draw();}
let repoDemo={stage:'未接入',authorization:'已预授权',request:0};
function renderRepositoryOnboarding(){const ready=repoDemo.stage==='就绪';$('page').innerHTML=header('代码与交付','仓库绑定、外部授权、NAS同步与任务Git门禁分别给出状态。',manager()?btn(ready?'重新核验固定对象':'开始项目只读接入','repo-connect','','primary'):'')+`<div class="notice">仓库接入为下一轮设计演示，不会操作GitHub、NAS密钥或真实同步器。真实F02的实例缺配置问题尚未由本原型修复。</div><div class="grid-two section-gap"><section class="panel"><div class="panel-header"><h3>项目仓库 main · 演示</h3>${badge(repoDemo.stage)}</div><dl class="details-grid"><div><dt>绑定</dt><dd>example/project-board<br><span class="small muted">沿用已有repo_id，不重新bind</span></dd></div><div><dt>权限</dt><dd>Contents / Metadata只读<br>不push、不执行仓库代码</dd></div><div><dt>实例基础接入</dt><dd>已配置（演示）<br>凭据由平台托管，不给SE</dd></div><div><dt>当前任务门禁</dt><dd>${ready?'Git对象可读；仍须重读依赖与实际任务范围':'缺接入，不等于任务测试失败'}</dd></div></dl><div class="form-field section-gap"><label for="repo-scenario">演示外部授权情形</label><select id="repo-scenario"><option ${repoDemo.authorization==='已预授权'?'selected':''}>已预授权</option><option ${repoDemo.authorization==='尚未授权'?'selected':''}>尚未授权</option><option ${repoDemo.authorization==='已撤销'?'selected':''}>已撤销</option></select></div><p class="small muted">预授权只适用于实例策略允许且GitHub安装已授予的仓库。公告板SE角色不能凭空授予GitHub权限。</p></section><section class="panel"><h3>接入阶段与下一步</h3><ol class="compact-list secondary"><li>验证项目SE与现有仓库绑定</li><li>核对GitHub的仓库级只读授权</li><li>平台受限代理建立/更新专属镜像</li><li>首次同步并检查真实目标提交、引用</li><li>回写结果；SE自行重读任务门禁</li></ol><div class="notice ${ready?'':'warning'} section-gap">${esc(repoDemo.stage==='等待仓库授权'?'下一步：仓库拥有者（也可以是有GitHub仓库管理权的SE本人）将该仓库加入App授权范围。无需让公告板管理员手写私有配置。':repoDemo.stage==='授权已撤销'?'授权撤销后停止新查询；历史回执保留，不能使用旧就绪状态继续验收。':ready?'只读接入就绪不自动领取、验收或合入任务；原严格范围与基线门禁继续生效。':'SE可以发起、查询、重试本项目接入，平台不接收任意磁盘路径、私钥、命令或主机。')}</div><div class="section-gap">${btn('查看完整权限边界','design-section','data-section="repo-selfservice"','link-button')}</div></section></div>`;$('repo-scenario').onchange=e=>{repoDemo.authorization=e.target.value;repoDemo.stage=e.target.value==='已撤销'?'授权已撤销':'未接入';renderRepositoryOnboarding();};}
document.addEventListener('click',e=>{const row=e.target.closest('[data-coverage]');if(row){const r=continuityRows.find(r=>r.id===row.dataset.coverage);modal(r.title,`<dl class="details-grid"><div><dt>原入口与源码</dt><dd>${esc(r.source)}</dd></div><div><dt>新设计入口</dt><dd>${esc(r.destination)}</dd></div></dl><h3 class="section-gap">必须保留的信息</h3><p class="prose">${esc(r.fields)}</p><h3 class="section-gap">必须保留的操作与门禁</h3><p class="prose">${esc(r.actions)}</p><div class="notice warning section-gap">当前原型：${esc(r.prototype)}。交互原型覆盖与完整生产承接必须分别验收，不以本表替代实际功能。</div>`);}if(e.target.closest('[data-action="repo-connect"]')){if(!manager())return;if(repoDemo.authorization==='尚未授权')repoDemo.stage='等待仓库授权';else if(repoDemo.authorization==='已撤销')repoDemo.stage='授权已撤销';else{repoDemo.stage='就绪';repoDemo.request++;}renderRepositoryOnboarding();notify(repoDemo.stage==='就绪'?'演示接入回执已生成；未执行真实Git同步。':'已给出明确责任方和下一步，不放宽任务依赖。');}});
