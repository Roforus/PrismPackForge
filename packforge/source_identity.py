"""A portable pack identity stored alongside the source, independently of UI cache."""
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

from .common import PackError, json_bytes

IDENTITY_FILE = '.packforge-export.json'


def validate_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*',value):
        raise PackError('ID должен содержать латинские строчные буквы, цифры, дефис или подчёркивание')
    from .common import relative_path
    relative_path(value)
    return value


def source_id(folder: Path):
    for filename in (IDENTITY_FILE,'.packforge/state.json','.minecraft/.packforge/state.json','minecraft/.packforge/state.json'):
        path = folder/filename
        if path.exists():
            try:
                data = json.loads(path.read_text('utf-8'))
                return validate_id(data['id'])
            except (OSError,ValueError,KeyError,TypeError) as exc:
                raise PackError(f'Не удалось прочитать ID сборки: {path}') from exc
    generated = re.sub(r'[^a-z0-9_-]+','-',folder.name.lower()).strip('-')
    try:
        return validate_id(generated)
    except PackError:
        # No file is written until export; this value becomes permanent on export.
        return 'pack-'+uuid.uuid5(uuid.NAMESPACE_URL,str(folder.resolve())).hex[:12]


def save_source_id(folder: Path, pack_id: str):
    pack_id = validate_id(pack_id)
    path = folder/IDENTITY_FILE
    if path.is_symlink():
        raise PackError(f'Файл ID не должен быть ссылкой: {path}')
    data = {'format':1,'id':pack_id}
    with tempfile.NamedTemporaryFile(dir=folder,delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(json_bytes(data))
    try:
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)
