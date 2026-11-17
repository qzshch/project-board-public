"""Prepare a bounded historical draft from explicit project files, never an account scan."""
import argparse,hashlib,json,uuid
from pathlib import Path
from tools.task_board_client import read,save


def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def prepare(profile,package,roots):
    if package.get('project_id')!=profile.get('project_id'):raise ValueError('整理包与项目身份不匹配')
    draft=package['draft'];allowed=[Path(x).resolve(strict=True) for x in roots]
    if not allowed:raise ValueError('需明确允许核对原件的本机目录')
    sources=[draft['archive'],*[e['origin'] for e in draft['entries']]];checked=[]
    for source in sources:
        original=Path(source['path']);path=original.resolve(strict=True)
        if not any(path.is_relative_to(root) for root in allowed):raise ValueError('来源在本次允许的目录之外')
        if not path.is_file() or any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in [original,*original.parents]):raise ValueError('只核对明确的普通文件，不遍历链接/目录')
        if sha(path)!=source['sha256']:raise ValueError('来源SHA256不匹配，保留原草案核对')
        checked.append({'path':str(path),'sha256':source['sha256']})
    return {'request_id':uuid.uuid4().hex,'project_id':package['project_id'],'action':'submit','payload':draft},checked


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',required=True);parser.add_argument('--file',required=True);parser.add_argument('--root',action='append',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
    output=Path(args.out)
    if output.exists():raise ValueError('冻结请求已存在；网络重试直接重发原文件，不重新生成ID')
    request,checked=prepare(read(args.profile),read(args.file),args.root)
    save(output,request);save(output.with_suffix('.sources.json'),{'project_id':request['project_id'],'checked':checked,'note':'File integrity correspondence, not billing or task acceptance proof'})
    print(json.dumps({'request':str(output.resolve()),'checked_files':len(checked),'next':'Use project client request --endpoint /api/retrospectives with this frozen request'}))
if __name__=='__main__':main()
