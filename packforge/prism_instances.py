import configparser
import os
from dataclasses import dataclass
from pathlib import Path

from .discovery import detect_launchers, _prism_instances


@dataclass(frozen=True)
class PrismInstance:
    path: Path
    name: str


def list_instances(extra_roots=(), launchers=None, appdata=None):
    app = appdata or Path(os.environ.get('APPDATA', str(Path.home() / 'AppData/Roaming')))
    roots = [_prism_instances(app / 'PrismLauncher')]
    roots.append(_prism_instances(app / 'MultiMC','multimc.cfg'))
    for launcher in detect_launchers() if launchers is None else launchers:
        if launcher.kind in ('prism','multimc') and launcher.instances_dir:
            roots.append(launcher.instances_dir)
    for root in map(Path, extra_roots):
        roots.append(_prism_instances(root,'multimc.cfg') if (root/'multimc.cfg').is_file()
                     else _prism_instances(root) if (root / 'prismlauncher.cfg').is_file()
                     else root / 'instances' if (root / 'instances').is_dir() else root)
    found = {}
    for root in roots:
        try:
            candidates = [root] if (root / 'mmc-pack.json').is_file() else list(root.iterdir())
        except OSError:
            continue
        for instance in candidates:
            if not (instance / 'mmc-pack.json').is_file():
                continue
            name = instance.name
            config = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                config.read(instance / 'instance.cfg', encoding='utf-8-sig')
                name = config.get('General', 'name', fallback=name)
            except (OSError, configparser.Error, UnicodeError):
                pass
            found[str(instance.resolve()).casefold()] = PrismInstance(instance.resolve(), name)
    return sorted(found.values(), key=lambda x: (x.name.casefold(), str(x.path)))
