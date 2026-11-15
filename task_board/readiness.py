"""Read-only explanations using the same gates as the live task pool."""
from collections import Counter
from .convergence import snapshot

GUIDANCE=[
 ('输入','inputs','补齐真实来源/材料入口；未知项先登记调研任务'),
 ('范围','scope','SE核定本次范围及写路径，不把全部历史任务同时发布'),
 ('风险','risk','由SE按实际影响核定，普通任务沿用已批准规则'),
 ('模块','module','核对当前模块决定，历史登记可保留为历史'),
 ('接口','interface','并行共享接口先固定版本，独立部分继续'),
 ('依赖','dependency','等待所需成果及对应基线；不要伪造前置通过'),
 ('实施','plan','仅当前策略要求时补充实施计划'),
 ('测试','test','核对测试输入锚点、环境和实际运行，日志留资源目录'),
 ('Git','git','绑定真实仓库和精确提交；原始资料保留Git外'),
 ('发布','publication','SE确认执行边界后将当前就绪任务发布给Worker'),
]
def diagnose(store,actor):
    view=snapshot(store,actor)['workbench'];counts=Counter();rows=[]
    for task in view['claimable']:
        reasons=[]
        for message in task['blockers']:
            match=next(((code,step) for word,code,step in GUIDANCE if word.casefold() in message.casefold()),('other','按该条实际门禁核对；不可通过修改历史状态绕过'))
            counts[match[0]]+=1;reasons.append({'code':match[0],'reason':message,'next':match[1]})
        rows.append({**task,'diagnosis':reasons,'ready':not reasons})
    return {'schema':1,'role':view['role'],'read_only':True,'ready':sum(x['ready'] for x in rows),'blocked':sum(not x['ready'] for x in rows),'categories':dict(counts),'tasks':rows,'pending':view['items'],'history':'历史DONE/PASS仅是来源登记；当前任务按当前范围验证','transport':'502/503/504可暂退避；固定请求ID与正文重试，409必须重读判断','guide':'/help/project-readiness'}
