"""Opt-in integration: real game/Java/Fabric + mod install and EXE build.

Run from repository root: python scripts/smoke_test.py [--build]
Only disposable fixture game files are written, under .verification/. Large download.
"""
import json
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlencode

from packforge.common import digest, fetch_file
from packforge.exporter import build_exe, export_pack
from packforge.installer import install
from packforge.providers import api


def main():
    root = Path(__file__).resolve().parent.parent / ".verification"
    instance = root / "source"
    game = instance / ".minecraft"
    (game / "mods").mkdir(parents=True, exist_ok=True)
    query = urlencode({"game_versions": '["1.20.1"]', "loaders": '["fabric"]'})
    version = api(f"https://api.modrinth.com/v2/project/modmenu/version?{query}")[0]
    remote = next(f for f in version["files"] if f.get("primary"))
    mod = game / "mods" / remote["filename"]
    fetch_file(remote["url"], mod, remote["size"])
    assert digest(mod) == remote["hashes"]["sha512"]
    (instance / "mmc-pack.json").write_text(json.dumps({"formatVersion": 1, "components": [
        {"uid": "net.minecraft", "version": "1.20.1"},
        {"uid": "net.fabricmc.fabric-loader", "version": "0.16.9"},
    ]}), encoding="utf-8")
    (game / "config").mkdir(exist_ok=True)
    (game / "config/verification.json").write_text('{"smoke_test": true}', encoding="utf-8")
    (game / "options.txt").write_text('music:0.5\n', encoding='utf-8')
    bundle = export_pack(instance, root / "smoke.pack.zip", pack_id="smoke-test",
                         name="Проверка установщика", version="1.0.0")
    with zipfile.ZipFile(bundle) as archive:
        assert not any(".jar" in name.lower() for name in archive.namelist())
    for launcher in ("prism", "legacy", "tlauncher"):
        target = root / f"installed-{launcher}"
        install(bundle, target, launcher)
        installed_game = target / ".minecraft" if launcher == "prism" else target
        assert digest(installed_game / "mods" / mod.name) == digest(mod)
        if launcher != "prism":
            state = json.loads((installed_game / ".packforge/state.json").read_text("utf-8"))
            version_id = state["installed_version"]
            assert version_id == "fabric-loader-0.16.9-1.20.1"
            assert (installed_game / "versions" / version_id / f"{version_id}.json").is_file()
            assert (installed_game / "versions/1.20.1/1.20.1.jar").is_file()
    if "--build" in sys.argv:
        build_exe(bundle, root / "smoke-setup.exe")
    print("PASS: real mod download, game/Java/Fabric install, jar-free bundle and three targets")


if __name__ == "__main__":
    main()
