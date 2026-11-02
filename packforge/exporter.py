from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from .common import PackError, digest, json_bytes, relative_path
from .providers import Resolver

FOLDERS = ("mods", "config", "defaultconfigs", "kubejs", "scripts", "resourcepacks",
           "shaderpacks", "global_packs", "datapacks")
LOADERS = {"net.fabricmc.fabric-loader": "Fabric", "net.minecraftforge": "Forge",
           "net.neoforged": "NeoForge", "org.quiltmc.quilt-loader": "Quilt"}


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-")
    if not result:
        raise PackError("Укажите ID сборки латиницей, например my-pack")
    relative_path(result)
    return result


def export_pack(instance: Path, output: Path, *, pack_id: str | None = None, name: str,
                version: str, curseforge_key: str = "",
                resolver=None, log=print, minecraft=None, loader=None, loader_version=None) -> Path:
    instance = instance.resolve()
    from .source_identity import source_id, save_source_id, validate_id
    pack_id = validate_id(pack_id) if pack_id else source_id(instance)
    if not name.strip() or not version.strip():
        raise PackError("Название и версия сборки обязательны")
    from .sources import read_source
    game, components = read_source(instance, minecraft, loader, loader_version)
    minecraft = next((c["version"] for c in components["components"]
                      if c["uid"] == "net.minecraft"), None)
    if not minecraft:
        raise PackError("В mmc-pack.json не указана версия Minecraft")
    unsupported = [c["uid"] for c in components["components"]
                   if c["uid"] not in {*LOADERS, "net.minecraft", "org.lwjgl", "org.lwjgl3",
                                      "net.fabricmc.intermediary", "org.quiltmc.quilt-mappings"}]
    if unsupported or (instance / "patches").exists() or (instance / "jarmods").exists():
        raise PackError(f"Пользовательские компоненты/патчи пока не поддерживаются: {unsupported}")
    if game.is_symlink() or (hasattr(game, "is_junction") and game.is_junction()):
        raise PackError("Папка игры не должна быть ссылкой")
    candidates = []
    for folder in FOLDERS:
        root = game / folder
        if root.exists():
            candidates.extend([root, *root.rglob("*")])
    if not (game / "options.txt").is_file():
        raise PackError("В сборке нет options.txt. Запустите игру в Prism, настройте её и закройте перед экспортом")
    candidates.append(game / "options.txt")
    sources = []
    for path in sorted(candidates):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise PackError(f"Ссылки не экспортируются: {path}")
        if not path.is_file():
            continue
        rel = relative_path(path.relative_to(game).as_posix())
        # Prism mod metadata is local bookkeeping, not part of the pack.
        if ".index" in path.relative_to(game).parts:
            continue
        sources.append((path, rel, digest(path)))
    remote = [(p, h) for p, rel, h in sources
              if rel.startswith(("mods/", "resourcepacks/", "shaderpacks/"))
              or ".jar" in p.name.lower()]
    links = (resolver or Resolver(curseforge_key, log)).resolve(remote)
    unresolved = [str(p.relative_to(game)) for p, h in remote if h not in links]
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = output.with_suffix(".unresolved.json")
    if unresolved:
        report.write_bytes(json_bytes({"unresolved": unresolved, "hint":
            "Файлы не найдены на Modrinth/CurseForge или запрещена прямая загрузка. "
            "Для CurseForge задайте CURSEFORGE_API_KEY. JAR в установщик не встраиваются."}))
        raise PackError(f"Не найдены ссылки для {len(unresolved)} файлов. Отчёт: {report}")
    save_source_id(instance,pack_id)
    manifest = {"format": 1, "id": pack_id, "name": name.strip(), "version": version.strip(),
                "minecraft": minecraft, "components": components,
                "loaders": [{"name": LOADERS[c["uid"]], "version": c["version"]}
                            for c in components["components"] if c["uid"] in LOADERS], "files": []}
    remote_hashes = {h for _, h in remote}
    with tempfile.TemporaryDirectory(prefix="packforge-export-") as tmp:
        archive = Path(tmp) / "pack.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path, rel, h in sources:
                entry = {"path": rel, "sha512": h, "size": path.stat().st_size}
                if h in remote_hashes:
                    entry.update(links[h])
                else:
                    entry["embedded"] = f"overrides/{rel}"
                    bundle.write(path, entry["embedded"])
                if digest(path) != h:
                    raise PackError(f"Файл изменился во время экспорта: {path}")
                manifest["files"].append(entry)
            bundle.writestr("manifest.json", json_bytes(manifest))
        # Copy to the destination filesystem, then publish atomically.
        import shutil
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copyfile(archive, temporary)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    report.unlink(missing_ok=True)
    log(f"Экспортировано {len(sources)} файлов: {output}")
    return output


def build_exe(bundle: Path, output: Path, log=print) -> Path:
    if sys.platform != "win32":
        raise PackError("Windows EXE нужно собирать на Windows")
    bundle, output = bundle.resolve(), output.resolve()
    from .installer import read_manifest
    read_manifest(bundle)
    if output.suffix.lower() != ".exe":
        raise PackError("Имя установщика должно оканчиваться на .exe")
    output.parent.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        from .standalone import attach_pack
        template = Path(sys._MEIPASS) / "installer-template.exe"
        if not template.is_file():
            raise PackError("В EXE отсутствует шаблон установщика")
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            attach_pack(template, bundle, temporary)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        log(f"Установщик готов: {output}")
        return output
    with tempfile.TemporaryDirectory(prefix="packforge-build-") as tmp:
        root = Path(tmp)
        import shutil
        payload = root / "pack.zip"
        shutil.copy2(bundle, payload)
        entry = root / "installer_entry.py"
        entry.write_text("from packforge.installer_ui import main\nmain()\n", encoding="utf-8")
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
                   "--windowed", "--name", output.stem, "--distpath", str(root / "dist"),
                   "--workpath", str(root / "build"), "--specpath", str(root),
                   "--paths", str(Path(__file__).resolve().parent.parent),
                   "--collect-data", "minecraft_launcher_lib",
                   "--add-data", f"{payload}{os.pathsep}payload", str(entry)]
        log("Сборка EXE через PyInstaller…")
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            raise PackError("Не удалось собрать EXE. Установите pip install -e .[build]\n" + result.stderr[-6000:])
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copy2(root / "dist" / f"{output.stem}.exe", temporary)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    log(f"Установщик готов: {output}")
    return output
