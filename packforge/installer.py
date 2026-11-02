from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from .common import PackError, digest, download_url, fetch_file, json_bytes, relative_path, target_path
from .exporter import FOLDERS, slug
from .game_runtime import prepare_runtime, runtime_spec
from .discovery import remember_installation

STATE = ".packforge/state.json"


def game_file(value: str) -> str:
    relative_path(value)
    if value != "options.txt" and ("/" not in value or value.split("/")[0] not in FOLDERS):
        raise PackError(f"Путь не относится к файлам сборки: {value}")
    return value


def read_manifest(bundle: Path) -> dict:
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != 1:
            raise PackError("Неподдерживаемый формат сборки")
        if slug(manifest["id"]) != manifest["id"]:
            raise PackError("Некорректный ID сборки")
        if not isinstance(manifest.get("name"), str) or not isinstance(manifest.get("version"), str):
            raise PackError("Некорректное название или версия сборки")
        components = manifest.get("components", {})
        if not isinstance(components.get("components"), list):
            raise PackError("Нет компонентов Prism")
        runtime_spec(manifest)
        seen = set()
        for entry in manifest["files"]:
            path = game_file(entry["path"])
            key = path.casefold()
            if key in seen:
                raise PackError(f"Повторяющийся путь: {path}")
            seen.add(key)
            if not re.fullmatch(r"[0-9a-f]{128}", entry["sha512"]):
                raise PackError(f"Некорректный SHA512: {path}")
            if type(entry["size"]) is not int or entry["size"] < 0:
                raise PackError(f"Некорректный размер: {path}")
            if "embedded" in entry:
                if (entry["embedded"] != f"overrides/{path}" or ".jar" in path.lower()
                        or "url" in entry):
                    raise PackError(f"Запрещённое вложение: {path}")
                info = archive.getinfo(entry["embedded"])
                if info.file_size != entry["size"]:
                    raise PackError(f"Размер вложения не совпадает: {path}")
            else:
                if entry.get("provider") not in ("modrinth", "curseforge"):
                    raise PackError(f"Неизвестный источник: {path}")
                download_url(entry["url"])
        paths = sorted(seen)
        for path in paths:
            parts = path.split("/")
            if any("/".join(parts[:i]) in seen for i in range(1, len(parts))):
                raise PackError(f"Конфликт файла и каталога: {path}")
    return manifest


def install(bundle: Path, destination: Path, launcher: str, *, replace_options: bool = False,
            log=print, downloader=fetch_file) -> dict:
    """Stage and verify everything before committing; roll back a failed commit."""
    manifest = read_manifest(bundle)
    if launcher not in ("prism", "legacy", "tlauncher", 'multimc', 'minecraft'):
        raise PackError("Неизвестный лаунчер")
    root = destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = target_path(root, ".packforge.lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise PackError(f"Папка занята другим установщиком. Если он закрыт, удалите {lock}") from exc
    try:
        os.close(lock_fd)
        return _install_locked(bundle, root, launcher, manifest, replace_options, log, downloader)
    finally:
        lock.unlink(missing_ok=True)


def _install_locked(bundle, root, launcher, manifest, replace_options, log, downloader):
    if launcher in ('prism','multimc'):
        dirs = [p for p in (root / "minecraft", root / ".minecraft") if p.exists()]
        if len(dirs) > 1:
            raise PackError("В экземпляре есть и minecraft, и .minecraft. Выберите корректный экземпляр")
        game = dirs[0] if dirs else root / ".minecraft"
        if game.is_symlink() or (hasattr(game, "is_junction") and game.is_junction()):
            raise PackError("Папка игры не должна быть ссылкой")
    elif launcher == 'minecraft':
        game = target_path(root, f"packforge/{manifest['id']}")
    else:
        game = root
    game.mkdir(parents=True, exist_ok=True)
    state_path = target_path(game, STATE)
    old = json.loads(state_path.read_text("utf-8")) if state_path.exists() else {}
    if old and old.get("id") != manifest["id"]:
        raise PackError("В этой папке установлена другая сборка. Выберите отдельную папку")
    if not old and not any(f["path"] == "options.txt" for f in manifest["files"]):
        raise PackError("Для первой установки необходим options.txt. Перевыгрузите сборку обновлённой утилитой")
    if launcher in ('prism','multimc') and not old and any((root / p).exists() for p in ("mmc-pack.json", "instance.cfg")):
        raise PackError("Выберите новую папку экземпляра Prism; существующий экземпляр не управляется установщиком")
    managed = old.get("files", {})
    for rel, h in managed.items():
        game_file(rel)
        if not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{128}", h):
            raise PackError("Повреждён журнал установленной сборки")
    next_files = {}
    operations = []
    count = 0
    # Stage on the same volume so each individual replacement is atomic.
    with tempfile.TemporaryDirectory(prefix=".packforge-stage-", dir=root) as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(bundle) as archive:
            for entry in manifest["files"]:
                rel = entry["path"]
                target = target_path(game, rel)
                if target.exists() and not target.is_file():
                    raise PackError(f"Ожидался файл, но найден каталог: {target}")
                current = digest(target) if target.exists() else None
                if rel == "options.txt" and current and old and not replace_options:
                    if rel in managed:
                        next_files[rel] = managed[rel]
                    log("Сохранён пользовательский options.txt")
                    continue
                next_files[rel] = entry["sha512"]
                if current == entry["sha512"]:
                    continue
                if rel.startswith("mods/") and current and rel not in managed:
                    raise PackError(f"Файл мода уже существует и не принадлежит сборке: {rel}")
                if (rel.startswith("mods/") and current and rel in managed
                        and current != managed[rel]):
                    raise PackError(f"Управляемый мод был изменён вручную: {rel}")
                staged = staging / f"file-{count}"
                count += 1
                log(f"[{count}/{len(manifest['files'])}] {rel}")
                if "embedded" in entry:
                    with archive.open(entry["embedded"]) as source, staged.open("wb") as stream:
                        shutil.copyfileobj(source, stream)
                else:
                    for attempt in range(3):
                        try:
                            downloader(entry["url"], staged, entry["size"])
                            if digest(staged) != entry["sha512"]:
                                raise PackError(f"SHA512 скачанного файла не совпадает: {rel}")
                            break
                        except (OSError, PackError) as exc:
                            if attempt == 2:
                                raise PackError(f"Не удалось скачать {rel}: {exc}") from exc
                            log(f"Повторная загрузка: {rel}")
                if staged.stat().st_size != entry["size"] or digest(staged) != entry["sha512"]:
                    raise PackError(f"Проверка целостности не пройдена: {rel}")
                operations.append((target, staged))
        new_paths = {f["path"].casefold() for f in manifest["files"]}
        for rel, old_hash in managed.items():
            if rel.casefold() in new_paths or rel == "options.txt":
                # An export without options must never remove the user's settings.
                continue
            target = target_path(game, rel)
            if target.exists():
                if not target.is_file():
                    raise PackError(f"Управляемый файл заменён каталогом: {rel}")
                if digest(target) == old_hash:
                    operations.append((target, None))
                elif rel.startswith("mods/"):
                    raise PackError(f"Старый мод изменён вручную, удалите или перенесите его: {rel}")
                else:
                    log(f"Сохранён изменённый пользователем файл: {rel}")
        installed_version = None
        if launcher not in ('prism','multimc'):
            prepared_runtime = prepare_runtime(manifest, staging, root if launcher == 'minecraft' else game, log)
            installed_version = prepared_runtime.version_id
            operations.extend(prepared_runtime.files)
        if launcher == 'minecraft':
            profile_files = [f for f in ('launcher_profiles.json','launcher_profiles_microsoft_store.json') if (root/f).exists()]
            for filename in profile_files or ['launcher_profiles.json']:
                profile_path = target_path(root,filename)
                data = json.loads(profile_path.read_text('utf-8')) if profile_path.exists() else {'profiles':{}}
                if not isinstance(data,dict) or not isinstance(data.get('profiles',{}),dict):
                    raise PackError('Повреждён файл профилей Minecraft Launcher')
                data.setdefault('profiles',{})['packforge-'+manifest['id']] = {
                    'name':manifest['name'], 'type':'custom', 'lastVersionId':installed_version,
                    'gameDir':str(game)}
                prepared_profile = staging / filename
                prepared_profile.write_bytes(json_bytes(data))
                operations.append((profile_path,prepared_profile))
        if launcher in ('prism','multimc'):
            meta = staging / "mmc-pack.json"
            meta.write_bytes(json_bytes(manifest["components"]))
            operations.append((target_path(root, "mmc-pack.json"), meta))
            if not (root / "instance.cfg").exists():
                cfg = staging / "instance.cfg"
                # No commands, accounts or JVM arguments are copied from the author.
                name = manifest["name"].replace("\n", " ").replace("\r", " ")
                cfg.write_text(f"[General]\nConfigVersion=1.2\nInstanceType=OneSix\nname={name}\n", encoding="utf-8")
                operations.append((target_path(root, "instance.cfg"), cfg))
        state = staging / "state.json"
        state.write_bytes(json_bytes({"id": manifest["id"], "version": manifest["version"],
                                      "launcher": launcher, "files": next_files,
                                      "installed_version": installed_version}))
        operations.append((state_path, state))
        backup_rel = f".packforge/backups/{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        backup = target_path(root, backup_rel)
        backup.mkdir(parents=True)
        applied = []
        try:
            for index, (target, staged) in enumerate(operations):
                # Recheck just before mutation, including metadata and state paths.
                target_path(root, target.relative_to(root).as_posix())
                target.parent.mkdir(parents=True, exist_ok=True)
                original = backup / str(index)
                existed = target.exists()
                if existed:
                    shutil.copy2(target, original)
                applied.append((target, original if existed else None))
                if staged is None:
                    target.unlink()
                else:
                    os.replace(staged, target)
            (backup / "index.json").write_bytes(json_bytes([
                {"path": str(p.relative_to(root)), "backup": b.name if b else None}
                for p, b in applied]))
        except BaseException:
            for target, original in reversed(applied):
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    shutil.copy2(original, target)
            raise
    log(f"Установлена сборка {manifest['name']} {manifest['version']}")
    log(f"Резервная копия заменённых файлов: {backup}")
    if installed_version:
        log(f"Перезапустите лаунчер и выберите установленную версию: {installed_version}")
    try:
        remember_installation(manifest["id"], launcher, root)
    except OSError as exc:
        log(f"Сборка установлена, но путь не сохранён для автопоиска: {exc}")
    return manifest
