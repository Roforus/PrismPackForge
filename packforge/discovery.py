"""Read-only launcher/pack discovery and a per-user index of successful installs."""
from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from .common import json_bytes

PRIORITY = {"prism": 0, "legacy": 1, "tlauncher": 2, "multimc":3, "minecraft":4}
NAMES = {"prism": "Prism Launcher", "legacy": "Legacy Launcher", "tlauncher": "TLauncher",
         "multimc":"MultiMC", "minecraft":"Minecraft Launcher"}
DOWNLOADS = {
    "prism": "https://prismlauncher.org/download/windows/",
    "legacy": "https://llaun.ch/en",
    "tlauncher": "https://tlauncher.org/en/install-on-windows.html",
    "multimc":"https://multimc.org/", "minecraft":"https://www.minecraft.net/download",
}


@dataclass(frozen=True)
class Launcher:
    kind: str
    executable: Path
    game_roots: tuple[Path, ...]
    instances_dir: Path | None = None

    @property
    def name(self):
        return NAMES[self.kind]


@dataclass(frozen=True)
class Installation:
    pack_id: str
    version: str
    launcher: str
    destination: Path


@dataclass
class Discovery:
    launchers: list[Launcher]
    installations: list[Installation]

    @property
    def recommended_launcher(self) -> Launcher | None:
        return min(self.launchers, key=lambda x: PRIORITY[x.kind], default=None)

    @property
    def recommended_update(self) -> Installation | None:
        return min(self.installations, key=lambda x: (PRIORITY[x.launcher], str(x.destination)), default=None)


def index_path() -> Path:
    override = os.environ.get("PACKFORGE_REGISTRY")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "PrismPackForge/installations.json"


def _read_json(path: Path, default):
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            return default
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError, UnicodeError):
        return default


def installation_at(destination: Path, pack_id: str, launcher: str | None = None) -> Installation | None:
    destination = destination.resolve()
    for game in (destination, destination / ".minecraft", destination / "minecraft", destination/'packforge'/pack_id):
        state = _read_json(game / ".packforge/state.json", {})
        if not isinstance(state, dict) or state.get("id") != pack_id:
            continue
        kind = state.get("launcher")
        if kind not in PRIORITY or (launcher is not None and kind != launcher):
            continue
        actual_destination = game.parent if kind in ('prism','multimc') and game.name in (".minecraft", "minecraft") else game
        if kind == 'minecraft' and game.parent.name == 'packforge':
            actual_destination = game.parent.parent
        if kind in ('prism','multimc') and not (actual_destination / "mmc-pack.json").is_file():
            continue
        return Installation(pack_id, str(state.get("version", "?")), kind, actual_destination)
    return None


def remember_installation(pack_id: str, launcher: str, destination: Path, path: Path | None = None):
    """Call after a successful transaction; stale index entries are never trusted."""
    path = path or index_path()
    entries = _read_json(path, [])
    if not isinstance(entries, list):
        entries = []
    key = str(destination.resolve())
    entries = [e for e in entries if isinstance(e, dict) and e.get("destination") != key]
    entries.append({"id": pack_id, "launcher": launcher, "destination": key})
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(json_bytes(entries))
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def launcher_kind(path: Path) -> str | None:
    name = path.name.lower()
    if path.suffix.lower() not in (".exe", ".jar") or any(s in name for s in ("setup", "installer", "unins")):
        return None
    if name.startswith("prismlauncher"):
        return "prism"
    if name.startswith('multimc'):
        return 'multimc'
    if name.replace(' ','').startswith('minecraftlauncher'):
        return 'minecraft'
    if name.startswith(("legacylauncher", "tl_legacy", "tllegacy")):
        return "legacy"
    if name.startswith("tlauncher"):
        return "tlauncher"
    return None


def _registry_paths() -> list[Path]:
    if sys.platform != "win32":
        return []
    import winreg
    result = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for section in (r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                            r"Software\Microsoft\Windows\CurrentVersion\App Paths"):
                try:
                    with winreg.OpenKey(hive, section, 0, winreg.KEY_READ | view) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                                    values = {}
                                    for j in range(winreg.QueryInfoKey(sub)[1]):
                                        name, value, _ = winreg.EnumValue(sub, j)
                                        if isinstance(value, str):
                                            values[name] = value
                                    text = " ".join(values.get(k, "") for k in ("DisplayName", "", "DisplayIcon"))
                                    if not any(n in text.lower().replace(" ", "") for n in ("prismlauncher", "legacylauncher", "tlauncher",'multimc','minecraftlauncher')):
                                        continue
                                    for name in ("InstallLocation", "DisplayIcon", ""):
                                        value = values.get(name, "").strip()
                                        if value:
                                            # DisplayIcon may be quoted and end with an icon index.
                                            value = re.sub(r",\s*-?\d+$", "", value).strip('"')
                                            result.append(Path(os.path.expandvars(value)))
                            except OSError:
                                continue
                except OSError:
                    continue
    return result


def _prism_instances(data: Path, filename='prismlauncher.cfg') -> Path:
    config = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        config.read(data / filename, encoding="utf-8")
        value = config.get("General", "InstanceDir", fallback="instances")
        path = Path(os.path.expandvars(value))
        return (data / path).resolve() if not path.is_absolute() else path.resolve()
    except (OSError, configparser.Error, ValueError):
        return data / "instances"


def _configured_games(files: list[Path]) -> list[Path]:
    result = []
    for config in files:
        try:
            if config.stat().st_size > 1024 * 1024:
                continue
            for line in config.read_text("utf-8", errors="replace").splitlines():
                match = re.match(r"\s*(?:minecraft\.gamedir|minecraft\.directory|gameDir)\s*[=:]\s*(.+)", line)
                if match:
                    value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), match[1])
                    value = value.replace("\\:", ":").replace("\\\\", "\\")
                    p = Path(os.path.expandvars(value.strip()))
                    result.append(p if p.is_absolute() else config.parent / p)
        except OSError:
            continue
    return result


def detect_launchers(*, home: Path | None = None, env: dict | None = None,
                     registered: list[Path] | None = None, portable_paths=()) -> list[Launcher]:
    home, env = home or Path.home(), os.environ if env is None else env
    app = Path(env.get("APPDATA", str(home / "AppData/Roaming")))
    local = Path(env.get("LOCALAPPDATA", str(home / "AppData/Local")))
    program_roots = [Path(env[k]) for k in ("ProgramFiles", "ProgramFiles(x86)") if env.get(k)]
    roots = [local / "Programs", app, home / "Desktop", home / "Downloads", home / "scoop/apps/prismlauncher/current",
             *program_roots]
    candidates = [Path(p) for p in portable_paths]
    candidates.extend(_registry_paths() if registered is None else registered)
    for command in ("prismlauncher.exe", "LegacyLauncher.exe", "TLauncher.exe", 'MultiMC.exe','MinecraftLauncher.exe'):
        executable = shutil.which(command, path=env.get("PATH", ""))
        if executable:
            candidates.append(Path(executable))
    folders = ("PrismLauncher", "Prism Launcher", "LegacyLauncher", "Legacy Launcher", "TLauncher", ".tlauncher", ".minecraft", 'MultiMC', 'Minecraft Launcher')
    for root in roots:
        candidates.append(root)
        candidates.extend(root / folder for folder in folders)
    # Registered directories and usual directories are shallow, bounded scans.
    files = []
    for candidate in candidates:
        try:
            if candidate.is_file():
                files.append(candidate)
            elif candidate.is_dir():
                files.extend(p for p in islice(candidate.iterdir(), 2000) if p.is_file())
        except OSError:
            continue
    found = []
    seen = set()
    for executable in files:
        kind = launcher_kind(executable)
        if not kind or kind in seen:
            continue
        executable = executable.resolve()
        if kind in ('prism','multimc'):
            filename = 'multimc.cfg' if kind == 'multimc' else 'prismlauncher.cfg'
            data = executable.parent if (executable.parent / filename).is_file() or kind == 'multimc' else app / "PrismLauncher"
            instances = _prism_instances(data,filename)
            games = (instances,)
        else:
            instances = None
            configs = [executable.parent / "tlauncher-2.0.properties"]
            if kind == "legacy":
                configs += [app / ".tlauncher/legacy/tlauncher-2.0.properties",
                            app / ".tlauncher/legacy/legacy.properties"]
                defaults = [app / ".tlauncher/legacy/Minecraft/game", app / ".minecraft"]
            else:
                configs += [app / ".tlauncher/tlauncher-2.0.properties"]
                defaults = [app / ".minecraft"]
            games = tuple(dict.fromkeys(p.resolve() for p in [*_configured_games(configs), *defaults]))
        found.append(Launcher(kind, executable, games, instances))
        seen.add(kind)
    return sorted(found, key=lambda launcher: PRIORITY[launcher.kind])


def find_installations(pack_id: str, launchers: list[Launcher], *, search_roots=(),
                       registry: Path | None = None, max_depth=6, standard_roots=True) -> list[Installation]:
    result = {}

    def add(installation):
        if installation:
            result[str(installation.destination).casefold()] = installation

    entries = _read_json(registry or index_path(), [])
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id") == pack_id and isinstance(entry.get("destination"), str):
                try:
                    add(installation_at(Path(entry["destination"]), pack_id))
                except (OSError, ValueError):
                    continue
    app = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
    roots = [*(p for launcher in launchers for p in launcher.game_roots), *search_roots]
    if standard_roots:
        roots.extend([app / "PrismLauncher/instances", app / ".minecraft", app / ".tlauncher/legacy/Minecraft/game"])
    skip = {"assets", "libraries", "runtime", "mods", "config", "saves", "screenshots", "logs",
            "node_modules", ".git", ".venv", "venv", "__pycache__", "resourcepacks", "shaderpacks", ".packforge"}
    visited_roots = set()
    for root in roots:
        root = Path(root).resolve()
        if root in visited_roots or not root.is_dir():
            continue
        visited_roots.add(root)
        for visited, (directory, dirs, _) in enumerate(os.walk(root, followlinks=False)):
            if visited >= 10000:
                break
            current = Path(directory)
            if ".packforge" in dirs:
                add(installation_at(current, pack_id))
            depth = len(current.relative_to(root).parts)
            dirs[:] = [d for d in dirs if d.lower() not in skip and not d.startswith(".packforge-stage-")
                       and not (current / d).is_symlink()
                       and not (hasattr(current / d, "is_junction") and (current / d).is_junction())] if depth < max_depth else []
    return sorted(result.values(), key=lambda x: (PRIORITY[x.launcher], str(x.destination)))


def discover(pack_id: str, *, portable_paths=(), search_roots=()) -> Discovery:
    launchers = detect_launchers(portable_paths=portable_paths)
    return Discovery(launchers, find_installations(pack_id, launchers, search_roots=search_roots))
