"""Install launcher-compatible game versions without modifying active game files."""
from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from minecraft_launcher_lib import install as mc_install, mod_loader, runtime

from .common import PackError, digest, relative_path, target_path

LOADER_IDS = {"Fabric": "fabric", "Forge": "forge", "NeoForge": "neoforge", "Quilt": "quilt"}
COMPONENT_IDS = {"net.fabricmc.fabric-loader": "Fabric", "net.minecraftforge": "Forge",
                 "net.neoforged": "NeoForge", "org.quiltmc.quilt-loader": "Quilt"}
RUNTIME_FOLDERS = ("versions", "libraries", "assets", "runtime")


@dataclass
class RuntimeResult:
    version_id: str
    # (active destination, verified/prepared source). Used by the pack transaction.
    files: list[tuple[Path, Path]]


def version_token(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]*", value):
        raise PackError(f"Некорректная версия Minecraft/загрузчика: {value!r}")
    relative_path(value)
    return value


def runtime_spec(manifest: dict) -> tuple[str, str | None, str | None]:
    """Use authoritative Prism components, not independently editable display labels."""
    components = manifest["components"]["components"]
    minecrafts = [c for c in components if c.get("uid") == "net.minecraft"]
    loaders = [c for c in components if c.get("uid") in COMPONENT_IDS]
    if len(minecrafts) != 1 or len(loaders) > 1:
        raise PackError("Нужны одна версия Minecraft и не более одного модлоадера")
    mc = version_token(minecrafts[0].get("version"))
    if mc != manifest.get("minecraft"):
        raise PackError("Версия Minecraft в манифесте не совпадает с компонентами Prism")
    if not loaders:
        return mc, None, None
    component = loaders[0]
    name = COMPONENT_IDS[component["uid"]]
    version = version_token(component.get("version"))
    if name == "Forge":
        version = version.removeprefix(f"{mc}-")
    return mc, LOADER_IDS[name], version


def _copy_cache(source: Path, destination: Path) -> None:
    """Use copies, never hardlinks: upstream installers may overwrite cached files."""
    if not source.exists():
        return
    if not source.is_dir():
        raise PackError(f"Ожидалась папка файлов Minecraft: {source}")
    for item in [source, *source.rglob("*")]:
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise PackError(f"Ссылки в файлах Minecraft не поддерживаются: {item}")
    shutil.copytree(source, destination, dirs_exist_ok=True)


def prepare_runtime(manifest: dict, staging: Path, game: Path, log=print) -> RuntimeResult:
    mc, loader_id, loader_version = runtime_spec(manifest)
    loader = mod_loader.get_mod_loader(loader_id) if loader_id else None
    expected_id = loader.get_installed_version(mc, loader_version) if loader else mc
    version_token(expected_id)
    prepared = staging / "minecraft-runtime"
    prepared.mkdir()
    log("Подготовка Minecraft: копирование имеющихся библиотек, ресурсов и Java…")
    # Do not copy other installed profiles or launcher account/settings files.
    for folder in ("libraries", "assets", "runtime"):
        _copy_cache(target_path(game, folder), prepared / folder)
    for version in dict.fromkeys((mc, expected_id)):
        _copy_cache(target_path(game, f"versions/{version}"), prepared / "versions" / version)

    last_status = 0.0

    def status(text):
        nonlocal last_status
        now = time.monotonic()
        if now - last_status >= 0.5:
            log(f"Minecraft: {text}")
            last_status = now

    callback = {"setStatus": status}
    try:
        log(f"Установка Minecraft {mc}…")
        mc_install.install_minecraft_version(mc, prepared, callback=callback)
        java = None
        if loader:
            # All four upstream installers (and Forge processors) run through Java.
            # Prefer Mojang's runtime for this exact game version over PATH/JAVA_HOME.
            base_json = prepared / "versions" / mc / f"{mc}.json"
            info = json.loads(base_json.read_text("utf-8"))
            component = info.get("javaVersion", {}).get("component", "jre-legacy")
            if loader_id in ("fabric", "quilt") and info.get("javaVersion", {}).get("majorVersion", 8) < 17:
                component = "java-runtime-gamma"
            java = runtime.get_executable_path(component, prepared)
            if not java:
                log(f"Установка Java ({component}) для модлоадера…")
                runtime.install_jvm_runtime(component, prepared, callback=callback)
                java = runtime.get_executable_path(component, prepared)
            if not java:
                raise PackError("Не удалось установить Java для модлоадера")
            # Windows distributions may expose javaw; processors need console Java.
            console_java = Path(java).with_name("java.exe")
            if console_java.is_file():
                java = str(console_java)
        if loader:
            log(f"Установка {loader.get_name()} {loader_version} для Minecraft {mc}…")
            installed_id = loader.install(mc, prepared, loader_version=loader_version,
                                          callback=callback, java=java)
            if installed_id != expected_id:
                raise PackError(f"Модлоадер создал неожиданную версию: {installed_id}")
        for relative in (f"versions/{mc}/{mc}.jar", f"versions/{expected_id}/{expected_id}.json"):
            if not target_path(prepared, relative).is_file():
                raise PackError(f"Установка Minecraft не завершена: отсутствует {relative}")
    except PackError:
        raise
    except Exception as exc:
        raise PackError(f"Не удалось установить Minecraft {mc} / {loader_id or 'Vanilla'} "
                        f"{loader_version or ''}: {exc}") from exc

    operations = []
    # Upstream may create launcher_profiles.json for its installer; never publish it.
    # Only version/runtime data is included in the pack transaction, never accounts.
    for folder in RUNTIME_FOLDERS:
        source_root = prepared / folder
        if not source_root.exists():
            continue
        for source in sorted(source_root.rglob("*")):
            rel = source.relative_to(prepared).as_posix()
            target_path(prepared, rel)  # Reject generated symlinks before reading/copying.
            if not source.is_file():
                continue
            target = target_path(game, rel)
            if target.exists() and not target.is_file():
                raise PackError(f"Вместо файла Minecraft найден каталог: {target}")
            if not target.exists() or digest(source) != digest(target):
                operations.append((target, source))
    log(f"Подготовлена версия {expected_id}; новых/изменённых файлов: {len(operations)}")
    return RuntimeResult(expected_id, operations)
