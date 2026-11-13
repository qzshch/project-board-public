"""Credential-free, project-specific delegation packet generator."""
from .governance import Governance
from .store import BoardError

def build_brief(store, task_id, project, url):
    task=store.get(task_id);spec=task['spec'];w=spec.get('work')
    if not w:raise BoardError('历史任务包尚未核定原子输入，不能自动派发',409)
    g=Governance(store).snapshot()
    return {'project_id':project,'api_base':url+'/api/projects/'+project,'task_id':task_id,
            'role':w['role'],'scope_version':task['scope_version'],'scope_hash':task['scope_hash'],
            'baseline':w['baseline'],'read_materials':g['knowledge'].get('materials',[]),
            'constraints':g['knowledge'].get('constraints','待SE填写'),
            'allowed_paths':spec['allowed_paths'],'inputs':w['inputs'],'outputs':w['outputs'],
            'contracts':{ref:g['contracts'].get(ref) for ref in w['contracts']},
            'assets':{ref:g['assets'].get(ref) or g['consumption'].get(ref) for ref in w['assets']},
            'exclusive_resources':w['resources'],'couplings':w['couplings'],'acceptance':w['acceptance'],
            'instruction':'向本项目负责人领取项目身份文件；禁止取得全局管理密钥。读取任务最新revision后prepare claim并post。只在允许目录实现，公共修改先scope_proposal，由SE走接口影响提案。提交冻结Git40位提交、来源SHA、证据SHA、测试及剩余范围；保存服务回执。返修必须引用open finding ID，重提不会自动关闭，审核通过后关闭。合并/运行验收/归档由SE分别记录。凭据不进Git。API权限不替代OS文件隔离。',
            'receipt_path':'<本项目证据目录>/<task_id>/receipt.json','findings':task['findings']}
