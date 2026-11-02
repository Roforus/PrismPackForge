import json
import os
import tempfile
from pathlib import Path


def settings_path():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'PrismPackForge/export-settings.json'


def load_settings(path=None):
    try:
        data = json.loads((path or settings_path()).read_text('utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data, path=None):
    # Explicit whitelist: never persist credentials or arbitrary widget contents.
    clean = {k: data[k] for k in ('last_instance', 'prism_roots','game_roots','last_launcher') if k in data}
    clean['profiles'] = {key: {k: value[k] for k in
        ('pack_id', 'name', 'version', 'output', 'include_options', 'make_exe','minecraft','loader','loader_version') if k in value}
        for key, value in data.get('profiles', {}).items() if isinstance(value, dict)}
    last = data.get('last_export')
    if isinstance(last,dict):
        clean['last_export'] = {k:last[k] for k in ('instance','launcher','pack_id','name','version',
            'output','make_exe','minecraft','loader','loader_version','exported_at') if k in last}
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(json.dumps(clean, ensure_ascii=False, indent=2).encode('utf-8'))
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
