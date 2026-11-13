"""Explicit JSON adapter. No business project is imported by initialization."""
import hashlib
import json
from pathlib import Path
from .store import BoardError, fields, task_spec

def import_catalog(path):
    path = Path(path)
    value = json.loads(path.read_text('utf8'))
    fields(value, {'entries'}, {'entries'})
    if type(value['entries']) is not list:
        raise BoardError('entries必须是列表')
    for entry in value['entries']:
        fields(entry, {'spec','status','owner'}, {'spec','status'})
        task_spec(entry['spec'])
        if entry['status'] not in ('planned','reported','baseline_merged','unknown'):
            raise BoardError('导入状态必须显式声明历史边界')
    return value['entries'], {'adapter':'json-v1','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
