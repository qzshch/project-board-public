"""Whitelisted operational docs, with private operator material kept separate."""
import html
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
PUBLIC_TEMPLATES=frozenset({
    'agent-brief.md','se-handoff.md','archive-checklist.md','project-init.json',
    'knowledge.json','member.json','milestone.json','package.json','contract-freeze.json',
    'contract-change.json','asset-private.json','asset-publish.json','asset-consume.json',
    'claim.json','submit.json','rework.json','handoff-propose.json','delivery-manifest.json','task-create.json',
    'module-plan.json','module-review.json','planning-decision.json','milestone-plan.json','milestone-review.json','planning-enable.json',
})
DOCS={
    '/help/agent':('执行 Agent','docs/AGENT-QUICKSTART.md',False),
    '/help/owner':('负责人 / 继承 SE','docs/OWNER-GUIDE.md',False),
    '/help/api':('任务与身份 API','docs/TASK_BOARD_API_V2.md',False),
    '/help/governance':('治理 API','docs/API-GOVERNANCE.md',False),
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

正式入口：http://example-server.example-tailnet.ts.net:18785 。旧 PC 入口已停用；资料、身份和材料仍按项目授权。

## 交给其他会话的入口

- [负责人 / 继承 SE 操作指南](/help/owner)：新项目准备、知识与角色、原子任务、冻结接口与资产、派发、审核返修、归档和交接。
- [执行 Agent 接入与交付](/help/agent)：领取项目身份、核对 brief、登记/领取、实现测试、保存回执、返修重提。
- [管理手册 · 协作阅读版](/help/admin)：所有协作 Agent 可阅读管理流程，阅读文档不授予操作权限。
- [其他电脑与 Agent 连通性](/help/connectivity)：Tailscale、DNS、本地执行通道和权限问题的排查步骤。
- [可复制模板目录](/help/templates)：项目、任务、接口、资产、交付、交接和归档模板。
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
