import json
import tempfile
import unittest
from pathlib import Path

from packforge.discovery import (Discovery, detect_launchers, find_installations,
                                 installation_at, launcher_kind, remember_installation)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.app = self.home / "AppData/Roaming"
        self.local = self.home / "AppData/Local"
        self.env = {"APPDATA": str(self.app), "LOCALAPPDATA": str(self.local), "PATH": ""}
        self.registry = self.home / "index.json"

    def launcher(self, name, folder=None):
        path = (folder or self.local / "Programs" / name.removesuffix(".exe")) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture, not an executable")
        return path

    def pack(self, target, kind="legacy", pack_id="my-pack", version="1.0"):
        game = target / ".minecraft" if kind == "prism" else target
        (game / ".packforge").mkdir(parents=True, exist_ok=True)
        (game / ".packforge/state.json").write_text(json.dumps({"id": pack_id, "version": version,
                                                                "launcher": kind, "files": {}}))
        if kind == "prism":
            (target / "mmc-pack.json").write_text('{}')
        return target

    def detect(self, **kwargs):
        return detect_launchers(home=self.home, env=self.env, registered=[], **kwargs)

    def find(self, **kwargs):
        return find_installations("my-pack", [], registry=self.registry, standard_roots=False, **kwargs)

    def test_no_launchers_and_no_recommendation(self):
        result = Discovery(self.detect(), self.find())
        self.assertEqual(result.launchers, [])
        self.assertIsNone(result.recommended_launcher)
        self.assertIsNone(result.recommended_update)

    def test_only_installed_launchers_in_priority_order(self):
        self.launcher("TLauncher.exe")
        self.assertEqual([x.kind for x in self.detect()], ["tlauncher"])
        self.launcher("LegacyLauncher.exe")
        self.assertEqual([x.kind for x in self.detect()], ["legacy", "tlauncher"])
        self.launcher("prismlauncher.exe", self.local / "Programs/PrismLauncher")
        found = self.detect()
        self.assertEqual([x.kind for x in found], ["prism", "legacy", "tlauncher"])
        self.assertEqual(Discovery(found, []).recommended_launcher.kind, "prism")

    def test_portable_launcher_and_configured_prism_instances(self):
        portable = self.home / "custom-portable"
        executable = self.launcher("prismlauncher.exe", portable)
        (portable / "prismlauncher.cfg").write_text('[General]\nInstanceDir=custom-instances\n')
        self.pack(portable / "custom-instances/old-pack", "prism")
        launchers = self.detect(portable_paths=[executable])
        self.assertEqual(launchers[0].instances_dir, portable / "custom-instances")
        found = find_installations("my-pack", launchers, registry=self.registry, standard_roots=False)
        self.assertEqual(found[0].destination, portable / "custom-instances/old-pack")

    def test_data_folders_and_downloaded_installers_are_not_installed_launchers(self):
        (self.app / "PrismLauncher").mkdir(parents=True)
        self.launcher("PrismLauncher-Setup.exe", self.home / "Downloads")
        self.launcher("TLauncher-Installer.exe", self.home / "Downloads")
        self.assertEqual(self.detect(), [])
        self.assertIsNone(launcher_kind(Path("TLauncher-Installer.exe")))

    def test_index_finds_custom_install_even_if_launcher_removed(self):
        target = self.pack(self.home / "arbitrary/place/my-pack", "tlauncher")
        remember_installation("my-pack", "tlauncher", target, self.registry)
        result = Discovery([], self.find())
        self.assertEqual(result.recommended_update.destination, target)

    def test_stale_index_is_ignored(self):
        target = self.pack(self.home / "removed")
        remember_installation("my-pack", "legacy", target, self.registry)
        (target / ".packforge/state.json").unlink()
        self.assertEqual(self.find(), [])

    def test_update_search_uses_id_not_name_and_deduplicates(self):
        target = self.pack(self.home / "custom/renamed-instance", "prism", version="2.0")
        self.pack(self.home / "custom/same-name-other-id", pack_id="other-pack")
        remember_installation("my-pack", "prism", target, self.registry)
        found = self.find(search_roots=[self.home / "custom", target])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].version, "2.0")
        self.assertEqual(found[0].destination, target)

    def test_multiple_updates_prefer_prism_then_legacy(self):
        self.pack(self.home / "games/tl", "tlauncher")
        self.pack(self.home / "games/ll", "legacy")
        prism = self.pack(self.home / "games/prism", "prism")
        found = self.find(search_roots=[self.home / "games"])
        self.assertEqual(Discovery([], found).recommended_update.destination, prism)

    def test_corrupt_state_and_registry_do_not_break_search(self):
        self.registry.write_text('not json')
        target = self.pack(self.home / "bad")
        (target / ".packforge/state.json").write_text('not json')
        self.assertEqual(self.find(search_roots=[target]), [])
        self.assertIsNone(installation_at(target, "my-pack"))

    def test_successful_registration_replaces_same_path_and_preserves_other_packs(self):
        one = self.pack(self.home / "one")
        two = self.pack(self.home / "two", pack_id="second")
        remember_installation("my-pack", "legacy", one, self.registry)
        remember_installation("second", "legacy", two, self.registry)
        remember_installation("my-pack", "legacy", one, self.registry)
        self.assertEqual(len(json.loads(self.registry.read_text())), 2)


if __name__ == "__main__":
    unittest.main()
