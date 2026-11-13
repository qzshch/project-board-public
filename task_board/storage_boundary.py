"""Source control is not the storage backend for project evidence or assets."""
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

LOCAL_DIRS = frozenset({'.cache','cache','caches','runtime','state','_private','evidence',
    'logs','log','test-results','test-records','reports','coverage','htmlcov','playwright-report',
    'research','investigations','archives','archive','backups','art-assets','artwork',
    'raw-assets','assets','art','textures','sprites','models','media','recordings','captures','downloads','build','dist','node_modules','.venv','__pycache__'})
LOCAL_SUFFIXES = frozenset({'.log','.sqlite','.sqlite3','.db','.tmp','.pyc','.psd','.psb','.blend',
    '.fbx','.obj','.exr','.kra','.ai','.wav','.mp3','.mp4','.mov','.onnx','.safetensors',
    '.zip','.7z','.rar','.tar','.gz','.png','.jpg','.jpeg','.webp','.gif','.tiff','.svg','.ico',
    '.ttf','.otf','.woff','.woff2','.glb','.gltf','.stl','.fig','.sketch','.aep',
    '.jsonl','.ndjson','.pid','.sock','.rdb','.prof','.pstats','.lcov','.trace','.har'})


def reason(path, patterns=(), exceptions=None):
    """Literal reviewed exceptions never override credentials/runtime protection."""
    parts=PurePosixPath(path).parts
    if not parts:return '无效路径'
    lower=[x.casefold() for x in parts];name=lower[-1]
    if any(x in {'_private','state','runtime','.git','.ssh'} for x in lower) or name=='.env' or name.startswith('.env.'):
        return '身份或运行状态应留在本地/NAS'
    if path in (exceptions or {}):return None
    if any(x in LOCAL_DIRS for x in lower) or PurePosixPath(name).suffix in LOCAL_SUFFIXES:
        return '缓存、调研、归档、美术/媒体、测试记录或运行产物应留在本地/NAS'
    if any(fnmatchcase(path,p) for p in patterns):return '项目指定本地保留路径'
    return None


def ignore_template():
    return '# Local/NAS data: never added or uploaded by the tracker.\n'+'\n'.join(
        sorted(d+'/' for d in LOCAL_DIRS))+'\n'+\
        '\n'.join('*'+s for s in sorted(LOCAL_SUFFIXES))+'\n.env\n.env.*\n'
