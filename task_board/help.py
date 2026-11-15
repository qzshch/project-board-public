"""Whitelisted operational docs, with private operator material kept separate."""
import html
import hashlib
import io
import json
import zipfile
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]

def observer_kit():
    files={name:(ROOT/name).read_bytes() for name in ('tools/task_board_client.py','tools/coordination_client.py','tools/project_observer.py')}
    files['tools/__init__.py']=b''
    files['README.md']=b'Python 3.11+ project-scoped collaboration and observation kit. Read /help/coordination. Profiles and operator-approved configurations must be supplied separately and kept outside Git. No agent launch or arbitrary command execution.\n'
    files['MANIFEST.json']=json.dumps({k:hashlib.sha256(v).hexdigest() for k,v in files.items()},sort_keys=True,indent=2).encode()
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():
            entry=zipfile.ZipInfo(name,(2026,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.create_system=3;entry.external_attr=0o100644<<16;z.writestr(entry,data)
    return output.getvalue()


def runner_kit(rollback=False):
    """Only executable client sources, never state/config/identities."""
    files={name:(ROOT/name).read_bytes() for name in ('tools/quality_runner.py','tools/task_board_client.py','tools/owned_process.py','tools/runner_process.py')}
    if rollback:files['tools/rollback_runner.py']=(ROOT/'tools/rollback_runner.py').read_bytes()
    files['tools/__init__.py']=b''
    files['requirements.txt']=b'psutil>=6,<8\n'
    files['README.md']=('Project-scoped runner kit. Python 3.11+. Install requirements in a non-C project environment.\nRead http://example-server.example-tailnet.ts.net:18785/help/runner\nObtain only your project runner profile; approve exact suite hashes locally. No credentials are included.\n').encode()
    if rollback:files['README.md']+=b'Rollback runner: read /help/workflow; obtain a separate project restorer profile and locally approve the exact manifest and fixed targets. Creates candidates without push.\n'
    files['MANIFEST.json']=json.dumps({name:hashlib.sha256(data).hexdigest() for name,data in files.items()},sort_keys=True,indent=2).encode()
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as bundle:
        for name,data in files.items():
            entry=zipfile.ZipInfo(name,(2026,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.create_system=3;entry.external_attr=0o100644<<16
            bundle.writestr(entry,data)
    return output.getvalue()
PUBLIC_TEMPLATES=frozenset({
    'workflow-thread-wait.json','task-dependency-requirements.json',
    'finishing-actions.json',
    'convergence-draft.json','convergence-rule.json','convergence-attempt.json','convergence-template.json',
    'coordination-intake.json','coordination-triage.json','coordination-convert.json','coordination-link.json','coordination-checkpoint.json','coordination-plan-policy.json','coordination-plan.json','coordination-plan-review.json','coordination-review-batch.json','coordination-root-cause.json','coordination-improvement.json','coordination-wip.json','coordination-gate.json','coordination-gate-retire.json','coordination-gate-confirm.json','coordination-observer.json','project-observer-config.json',
    'workflow-thread.json','workflow-decision.json','workflow-thread-ack.json','workflow-criteria-plan.json','workflow-criteria-claim.json','workflow-criteria-review.json','workflow-review-finding.json','workflow-review-disposition.json','workflow-review-resolve.json','workflow-git-check.json','workflow-rollback-plan.json','workflow-rollback-confirm.json','workflow-rollback-approve.json','workflow-rollback-apply.json','rollback-runner-config.json',
    'resource-entry.json','resource-retire.json',
    'git-binding.json','git-storage-policy.json','git-task-link.json','git-sync.json',
    'agent-brief.md','se-handoff.md','archive-checklist.md','project-init.json',
    'knowledge.json','member.json','milestone.json','package.json','contract-freeze.json',
    'contract-change.json','asset-private.json','asset-publish.json','asset-consume.json',
    'claim.json','submit.json','rework.json','handoff-propose.json','delivery-manifest.json','task-create.json',
    'governance-policy.json','risk-assessment.json','work-estimate.json','work-time.json','test-case.json','automation-suite.json','quality-plan.json','run-request.json','manual-run.json','runner-config.json','asset-candidate.json','asset-refinement.json','asset-validation.json','asset-promotion.json','asset-feedback.json',
    'package-assessment.json','work-time-complete.json','work-time-correct.json','work-time-close.json','runner-authorization.json','run-cancel.json','asset-retire.json',
    'benchmark-import.json','test-case-retire.json',
    'module-plan.json','module-review.json','planning-decision.json','milestone-plan.json','milestone-review.json','planning-enable.json',
})
DOCS={
    '/help/async-flow':('Worker异步交付与基线依赖','docs/ASYNC-WORKFLOW.md',False),
    '/help/worker-start':('Worker自助加入与认领','docs/WORKER-START.md',False),
    '/help/project-start':('项目SE自助开通与owner身份','docs/PROJECT-START.md',False),
    '/help/finishing':('选择最短路径：接续与操作减负','docs/FINISHING-GUIDE.md',False),
    '/help/convergence':('规划、治理复用、尝试与操作收敛','docs/CONVERGENCE-GUIDE.md',False),
    '/help/coordination':('需求、执行接续、增量评审与实际观察','docs/COORDINATION-GUIDE.md',False),
    '/help/workflow':('评论、验收、SE待办与受控回退','docs/WORKFLOW-GUIDE.md',False),
    '/help/resources':('本地与NAS资源目录及Agent接手','docs/RESOURCE-GUIDE.md',False),
    '/help/github':('GitHub提交与本地存储边界','docs/GITHUB-GUIDE.md',False),
    '/help/agent':('执行 Agent','docs/AGENT-QUICKSTART.md',False),
    '/help/owner':('负责人 / 继承 SE','docs/OWNER-GUIDE.md',False),
    '/help/api':('任务与身份 API','docs/TASK_BOARD_API_V2.md',False),
    '/help/governance':('治理 API','docs/API-GOVERNANCE.md',False),
    '/help/operations':('治理、时间、质量与资产操作','docs/API-OPERATIONS.md',False),
    '/help/runner':('项目测试执行器','docs/RUNNER-GUIDE.md',False),
    '/help/admin':('管理手册 · 协作阅读版','docs/ADMIN-READONLY-GUIDE.md',False),
    '/help/connectivity':('其他电脑与 Agent 连通性','docs/CONNECTIVITY.md',False),
    '/help/operator':('实例管理员私有操作手册','docs/MANUAL.md',True),
    '/help/deployment':('实例运行与恢复','docs/RUNBOOK.md',True),
}
RAW_DOCS={
    '/agent-guide.md':('docs/AGENT-QUICKSTART.md',False),
    '/owner-guide.md':('docs/OWNER-GUIDE.md',False),
    '/manual.md':('docs/MANUAL.md',True),
}
INDEX='''# 使用手册

当前异步协作规则：[自主等待、候选待评审和依赖解锁](/help/async-flow)。普通任务直接认领、工作、提交候选；SE异步验收并推进基线。

作为 Worker，先读[自助加入与认领](/help/worker-start)：只需指定项目入口，自行生成普通身份，从任务池领取并交付；不向负责人索要owner身份。

首次担任新项目SE，先读[SE直接创建项目](/help/project-start)：create-se在本机自行生成身份并创建新项目，不需要先索要owner文件或提交逐项目签发请求；已有项目仍按原owner交接。

先读[最短操作路径](/help/finishing)：一次性轻量任务、同类规则复用、多会话尝试、高风险完整流程分别处理，不要求每张任务叠加所有机制。

正式入口：http://example-server.example-tailnet.ts.net:18785 。旧 PC 入口已停用；资料、身份和材料仍按项目授权。

## 交给其他会话的入口

- [负责人 / 继承 SE 操作指南](/help/owner)：新项目准备、知识与角色、原子任务、冻结接口与资产、派发、审核返修、归档和交接。
- [执行 Agent 接入与交付](/help/agent)：领取项目身份、核对 brief、登记/领取、实现测试、保存回执、返修重提。
- [管理手册 · 协作阅读版](/help/admin)：所有协作 Agent 可阅读管理流程，阅读文档不授予操作权限。
- [其他电脑与 Agent 连通性](/help/connectivity)：Tailscale、DNS、本地执行通道和权限问题的排查步骤。
- [分级治理、时间、测试与资产](/help/operations)、[自动化执行器](/help/runner)、[独立执行器下载](/runner-kit.zip)：风险裁剪、工时估算与实测、用例/运行以及候选提炼闭环。
- [可复制模板目录](/help/templates)：项目、任务、接口、资产、交付、交接和归档模板。
- [GitHub代码提交追踪](/help/github)：提交图、差异、文件历史、逐行溯源与本地/NAS存储边界。
- [本地与NAS资源目录](/help/resources)：在项目资产页查找缓存、调研、美术、归档、测试记录、日志、运行态与接手入口。
- [协作、逐项验收与受控回退](/help/workflow)：阻塞求助、偏离决策、精确Git核验、SE待办和回退执行器。
- [需求、接续与改进](/help/coordination)：需求分诊、执行检查点、增量评审、流动效率、外部条件和本地资源核验；[独立协作与观察工具包](/observer-kit.zip)。
- [规划与操作收敛](/help/convergence)：关联规划草案、批准规则复用、执行尝试与保守接手、角色工作台和固定版本模板。
- [任务与身份 API](/help/api)、[治理 API](/help/governance)；[下载标准库客户端](/client.py)。

把对应角色的指南链接和本项目说明发给其他会话。项目身份通过私有渠道单独交付，不放在文档链接里。

## 管理员专用

[实例管理员私有操作手册](/help/operator)和[部署 / 恢复](/help/deployment)需要当前浏览器已启用实例管理员会话。项目协作阅读版 /help/admin 不要求登录，但项目数据和所有操作仍按原身份鉴权。

## 已有身份迁移

保留原 actor、token、project_id，只更新 profile.url 为 NAS 入口；旧 connect_ip 改为 100.64.0.10。不重新登记或扩大项目权限。
'''

def inline(value):
    result=[]
    for token in re.split(r'(`[^`]+`|\[[^\]]+\]\([^)]+\))',value):
        if token.startswith('`') and token.endswith('`'):result.append('<code>'+html.escape(token[1:-1])+'</code>');continue
        match=re.fullmatch(r'\[([^\]]+)\]\(([^)]+)\)',token)
        if match:
            label,url=match.groups();parsed=urlsplit(url)
            if (parsed.scheme in ('http','https') and not parsed.username and not parsed.password) or (url.startswith('/') and not url.startswith('//')):
                result.append('<a href="'+html.escape(url,quote=True)+'">'+html.escape(label)+'</a>');continue
        result.append(html.escape(token))
    return ''.join(result)

def render_markdown(value):
    """Small safe renderer for our headings, lists, code fences and links."""
    out=[];paragraph=[];code=None;list_kind=None;table=False
    def flush():
        if paragraph:out.append('<p>'+inline(' '.join(paragraph))+'</p>');paragraph.clear()
    def close_list():
        nonlocal list_kind
        if list_kind:out.append('</'+list_kind+'>');list_kind=None
    def close_table():
        nonlocal table
        if table:out.append('</tbody></table></div>');table=False
    for line in value.splitlines():
        if code is None and line.startswith('|') and line.endswith('|'):
            flush();close_list();cells=line[1:-1].split('|')
            if all(re.fullmatch(r'\s*:?-+:?\s*',cell) for cell in cells):continue
            if not table:out.append('<div class="docs-table"><table><tbody>');table=True
            out.append('<tr>'+''.join('<td>'+inline(cell.strip())+'</td>' for cell in cells)+'</tr>');continue
        close_table()
        if line.startswith('```'):
            flush();close_list()
            if code is None:code=[]
            else:out.append('<pre><code>'+html.escape('\n'.join(code))+'</code></pre>');code=None
            continue
        if code is not None:code.append(line);continue
        if not line.strip():flush();close_list();continue
        heading=re.match(r'^(#{1,4}) (.+)$',line)
        if heading:flush();close_list();level=len(heading[1]);out.append(f'<h{level}>'+inline(heading[2])+f'</h{level}>');continue
        item=re.match(r'^(?:([-*]) |(\d+)\. )(.+)$',line)
        if item:
            flush();kind='ul' if item[1] else 'ol'
            if list_kind!=kind:close_list();out.append('<'+kind+'>');list_kind=kind
            out.append('<li>'+inline(item[3])+'</li>');continue
        close_list();paragraph.append(line)
    flush();close_list();close_table()
    if code is not None:out.append('<pre><code>'+html.escape('\n'.join(code))+'</code></pre>')
    return '\n'.join(out)

def document_page(title, body):
    navigation=' · '.join('<a href="'+path+'">'+label+'</a>' for path,label in [('/','公告板'),('/help','手册首页'),('/help/owner','负责人 / SE'),('/help/agent','执行 Agent'),('/help/templates','模板')])
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>'+html.escape(title)+' · 公告板手册</title><link rel="stylesheet" href="/tokens.css"><link rel="stylesheet" href="/theme.css"><link rel="stylesheet" href="/help.css"></head><body><main class="docs-shell"><nav aria-label="手册导航">'+navigation+'</nav><article>'+render_markdown(body)+'</article></main></body></html>').encode('utf8')

def template_index():
    return '# 可复制模板\n\n模板是待填写的通用说明，不含身份和实际项目数据。全零提交/SHA及尖括号内容不能作为实测证据。\n\n'+'\n'.join('- ['+name+'](/templates/'+name+')' for name in sorted(PUBLIC_TEMPLATES))
