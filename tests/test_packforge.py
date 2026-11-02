import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from packforge.common import PackError, download_url, relative_path
from packforge.exporter import export_pack
from packforge.installer import STATE, install, read_manifest
from packforge.providers import Resolver, fingerprint
from packforge.game_runtime import RuntimeResult


class FakeResolver:
    def resolve(self, files):
        return {h: {"provider": "modrinth", "url": "https://cdn.modrinth.com/test.jar",
                    "project_id": "test", "file_id": "1"} for _, h in files}


class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.instance = self.root / "prism"
        self.game = self.instance / ".minecraft"
        (self.game / "mods").mkdir(parents=True)
        (self.game / "config").mkdir()
        (self.instance / "mmc-pack.json").write_text(json.dumps({"formatVersion": 1, "components": [
            {"uid": "net.minecraft", "version": "1.20.1"},
            {"uid": "net.fabricmc.fabric-loader", "version": "0.16.9"},
        ]}))
        (self.game / "mods/a.jar").write_bytes(b"test mod v1")
        (self.game / "config/a.json").write_text('{"a": 1}')
        (self.game / "options.txt").write_text("music:0.5")
        self.bundle = self.root / "test.pack.zip"
        self.destination = self.root / "target"
        self.downloaded = b"test mod v1"
        self.runtime = patch("packforge.installer.prepare_runtime",
                             return_value=RuntimeResult("fabric-loader-0.16.9-1.20.1", []))
        self.prepare_runtime = self.runtime.start()
        self.addCleanup(self.runtime.stop)
        self.remember_patch = patch("packforge.installer.remember_installation")
        self.remember = self.remember_patch.start()
        self.addCleanup(self.remember_patch.stop)

    def export(self, options=False, resolver=None, version="1"):
        return export_pack(self.instance, self.bundle, pack_id="test", name="Тест", version=version,
                           resolver=resolver or FakeResolver(), log=lambda _: None)

    def download(self, url, output, size):
        output.write_bytes(self.downloaded)

    def install(self, launcher="legacy", **kwargs):
        return install(self.bundle, self.destination, launcher, downloader=self.download,
                       log=lambda _: None, **kwargs)

    def test_export_contains_links_not_jars_or_accounts(self):
        (self.game / "saves").mkdir()
        (self.game / "saves/world.dat").write_bytes(b"personal")
        self.export()
        with zipfile.ZipFile(self.bundle) as z:
            self.assertEqual(set(z.namelist()), {"manifest.json", "overrides/config/a.json", "overrides/options.txt"})
            manifest = json.loads(z.read("manifest.json"))
            self.assertIn("url", next(f for f in manifest["files"] if f["path"].endswith(".jar")))

    def test_options_are_always_included(self):
        self.export()
        self.assertIn("options.txt", [f["path"] for f in read_manifest(self.bundle)["files"]])

    def test_export_game_folder_from_another_launcher(self):
        export_pack(self.game,self.bundle,pack_id='other',name='Other',version='1',
                    minecraft='1.21.1',loader='NeoForge',loader_version='21.1.1',
                    resolver=FakeResolver(),log=lambda _:None)
        manifest = read_manifest(self.bundle)
        self.assertEqual(manifest['minecraft'],'1.21.1')
        self.assertEqual(manifest['loaders'],[{'name':'NeoForge','version':'21.1.1'}])

    def test_game_folder_requires_explicit_runtime(self):
        with self.assertRaises(PackError):
            export_pack(self.game,self.bundle,pack_id='other',name='Other',version='1')

    def test_multimc_target_uses_instance_format(self):
        self.export()
        self.install('multimc')
        self.prepare_runtime.assert_not_called()
        self.assertTrue((self.destination/'mmc-pack.json').is_file())
        self.assertEqual((self.destination/'.minecraft/options.txt').read_text(),'music:0.5')

    def test_official_launcher_keeps_existing_profiles_and_isolates_game(self):
        self.export()
        self.destination.mkdir()
        profiles = self.destination/'launcher_profiles.json'
        profiles.write_text(json.dumps({'profiles':{'existing':{'name':'Existing'}},'settings':{'custom':True}}))
        self.install('minecraft')
        updated = json.loads(profiles.read_text())
        self.assertEqual(updated['profiles']['existing'],{'name':'Existing'})
        self.assertEqual(updated['settings'],{'custom':True})
        self.assertEqual(updated['profiles']['packforge-test']['lastVersionId'],'fabric-loader-0.16.9-1.20.1')
        self.assertTrue((self.destination/'packforge/test/mods/a.jar').is_file())
        self.assertFalse((self.destination/'mods').exists())
        from packforge.discovery import installation_at
        self.assertEqual(installation_at(self.destination,'test').launcher,'minecraft')

    def test_export_requires_options(self):
        (self.game / "options.txt").unlink()
        with self.assertRaisesRegex(PackError, 'options.txt'):
            self.export()

    def test_first_install_replaces_existing_options_with_backup(self):
        self.export()
        self.destination.mkdir()
        (self.destination / 'options.txt').write_text('previous game settings')
        self.install()
        self.assertEqual((self.destination / 'options.txt').read_text(), 'music:0.5')
        backups = self.destination / '.packforge/backups'
        self.assertTrue(any(p.is_file() and p.read_bytes() == b'previous game settings'
                            for p in backups.rglob('*') if p.name != 'index.json'))

    def test_install_all_three_launchers(self):
        self.export(True)
        for launcher in ("prism", "legacy", "tlauncher"):
            with self.subTest(launcher=launcher):
                self.destination = self.root / f"installed-{launcher}"
                self.install(launcher)
                game = self.destination / ".minecraft" if launcher == "prism" else self.destination
                self.assertEqual((game / "mods/a.jar").read_bytes(), self.downloaded)
                self.assertTrue((game / STATE).exists())
                if launcher == "prism":
                    self.assertTrue((self.destination / "mmc-pack.json").exists())

    def test_update_removes_only_owned_mods_and_preserves_options(self):
        self.export(True)
        self.install()
        (self.destination / "mods/personal.jar").write_bytes(b"personal")
        (self.destination / "options.txt").write_text("user settings")
        (self.game / "mods/a.jar").unlink()
        (self.game / "mods/b.jar").write_bytes(b"new version")
        self.downloaded = b"new version"
        self.export(True, version="2")
        self.install()
        self.assertFalse((self.destination / "mods/a.jar").exists())
        self.assertEqual((self.destination / "mods/b.jar").read_bytes(), b"new version")
        self.assertTrue((self.destination / "mods/personal.jar").exists())
        self.assertEqual((self.destination / "options.txt").read_text(), "user settings")
        self.assertEqual(json.loads((self.destination / STATE).read_text())["version"], "2")
        self.install(replace_options=True)
        self.assertEqual((self.destination / "options.txt").read_text(), "music:0.5")

    def test_bad_download_leaves_previous_installation_untouched(self):
        self.export()
        self.install()
        previous = (self.destination / STATE).read_bytes()
        (self.game / "mods/a.jar").write_bytes(b"new")
        (self.game / "config/a.json").write_text("changed")
        self.export(version="2")
        self.downloaded = b"corrupt"
        with self.assertRaises(PackError):
            self.install()
        self.assertEqual((self.destination / "mods/a.jar").read_bytes(), b"test mod v1")
        self.assertEqual((self.destination / "config/a.json").read_text(), '{"a": 1}')
        self.assertEqual((self.destination / STATE).read_bytes(), previous)
        self.assertFalse((self.destination / ".packforge.lock").exists())

    def test_failed_commit_rolls_back(self):
        self.export()
        self.install()
        previous = (self.destination / STATE).read_bytes()
        (self.game / "config/a.json").write_text("changed")
        self.export(version="2")
        import os
        original = os.replace

        def fail_state(source, target):
            if Path(target).name == "state.json":
                raise OSError("Simulated disk failure")
            return original(source, target)

        with patch("packforge.installer.os.replace", side_effect=fail_state):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual((self.destination / "config/a.json").read_text(), '{"a": 1}')
        self.assertEqual((self.destination / STATE).read_bytes(), previous)

    def test_runtime_failure_does_not_apply_pack_changes(self):
        self.export()
        self.install()
        previous = (self.destination / STATE).read_bytes()
        (self.game / "config/a.json").write_text("new config")
        self.export(version="2")
        self.prepare_runtime.side_effect = PackError("No connection to Mojang")
        with self.assertRaises(PackError):
            self.install()
        self.assertEqual((self.destination / "config/a.json").read_text(), '{"a": 1}')
        self.assertEqual((self.destination / STATE).read_bytes(), previous)

    def test_runtime_files_participate_in_rollback(self):
        self.export()
        self.install()
        library = self.destination / "libraries/test.jar"
        library.parent.mkdir()
        library.write_bytes(b"old library")
        prepared = self.root / "new-library.jar"
        prepared.write_bytes(b"new library")
        self.prepare_runtime.return_value = RuntimeResult("fabric-test", [(library, prepared)])
        import os
        original = os.replace

        def fail_state(source, target):
            if Path(target).name == "state.json":
                raise OSError("Simulated failure after runtime publish")
            return original(source, target)

        with patch("packforge.installer.os.replace", side_effect=fail_state):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual(library.read_bytes(), b"old library")

    def test_modified_old_mod_blocks_update(self):
        self.export()
        self.install()
        (self.destination / "mods/a.jar").write_bytes(b"manual change")
        (self.game / "mods/a.jar").unlink()
        self.export()
        with self.assertRaises(PackError):
            self.install()
        self.assertEqual((self.destination / "mods/a.jar").read_bytes(), b"manual change")

    def test_unowned_mod_conflict(self):
        self.export()
        (self.destination / "mods").mkdir(parents=True)
        (self.destination / "mods/a.jar").write_bytes(b"another mod")
        with self.assertRaises(PackError):
            self.install()

    def test_unresolved_export_never_silently_omits_mod(self):
        self.export()
        previous = self.bundle.read_bytes()
        empty = FakeResolver()
        empty.resolve = lambda _: {}
        with self.assertRaises(PackError):
            self.export(resolver=empty)
        self.assertEqual(self.bundle.read_bytes(), previous)
        self.assertTrue(self.bundle.with_suffix(".unresolved.json").exists())

    def test_nested_jar_never_embedded(self):
        (self.game / "config/helper.jar").write_bytes(b"helper")
        self.export()
        with zipfile.ZipFile(self.bundle) as z:
            self.assertFalse(any(".jar" in name for name in z.namelist()))
        manifest = read_manifest(self.bundle)
        self.assertIn("url", next(f for f in manifest["files"] if "helper.jar" in f["path"]))

    def test_path_and_url_validation(self):
        for value in ("../mods/a", "/abs", "mods/../../a", "C:/a", "mods\\a", "mods/CON.jar", "mods/a:ads", "mods/a."):
            with self.subTest(path=value), self.assertRaises(PackError):
                relative_path(value)
        for value in ("http://cdn.modrinth.com/a", "https://evil.test/a", "https://cdn.modrinth.com.evil.test/a"):
            with self.subTest(url=value), self.assertRaises(PackError):
                download_url(value)

    def test_tampered_manifest_rejected(self):
        self.export()
        manifest = read_manifest(self.bundle)
        manifest["files"][0]["path"] = "../outside.jar"
        with zipfile.ZipFile(self.bundle, "w") as z:
            z.writestr("manifest.json", json.dumps(manifest))
        with self.assertRaises(PackError):
            self.install()

    def test_windows_case_collision_rejected(self):
        self.export()
        with zipfile.ZipFile(self.bundle) as z:
            manifest = json.loads(z.read("manifest.json"))
            data = z.read("overrides/config/a.json")
        duplicate = dict(next(f for f in manifest['files'] if f['path'].startswith('mods/')))
        duplicate["path"] = duplicate["path"].upper()
        manifest["files"].append(duplicate)
        with zipfile.ZipFile(self.bundle, "w") as z:
            z.writestr("manifest.json", json.dumps(manifest))
            z.writestr("overrides/config/a.json", data)
            z.writestr("overrides/options.txt", "music:0.5")
        with self.assertRaises(PackError):
            read_manifest(self.bundle)

    def test_curseforge_matching_verifies_sha1(self):
        path = self.game / "mods/a.jar"
        data = path.read_bytes()
        sha512 = hashlib.sha512(data).hexdigest()
        cf = {"data": {"exactMatches": [{"file": {
            "fileFingerprint": fingerprint(data), "hashes": [{"algo": 1, "value": hashlib.sha1(data).hexdigest()}],
            "downloadUrl": "https://edge.forgecdn.net/files/test.jar", "id": 123, "modId": 456,
        }}]}}
        with patch("packforge.providers.api", side_effect=[{}, cf]):
            resolved = Resolver("secret", log=lambda _: None).resolve([(path, sha512)])
        self.assertEqual(resolved[sha512]["provider"], "curseforge")
        cf["data"]["exactMatches"][0]["file"]["hashes"][0]["value"] = "wrong"
        with patch("packforge.providers.api", side_effect=[{}, cf]):
            self.assertEqual(Resolver("secret", log=lambda _: None).resolve([(path, sha512)]), {})

    def test_curseforge_restricted_download_is_unresolved(self):
        path = self.game / "mods/a.jar"
        data = path.read_bytes()
        cf = {"data": {"exactMatches": [{"file": {
            "fileFingerprint": fingerprint(data), "hashes": [{"algo": 1, "value": hashlib.sha1(data).hexdigest()}],
            "downloadUrl": None, "id": 123, "modId": 456,
        }}]}}
        with patch("packforge.providers.api", side_effect=[{}, cf]):
            self.assertEqual(Resolver("secret", log=lambda _: None).resolve([(path, "a")]), {})

    def test_fingerprint_whitespace(self):
        self.assertEqual(fingerprint(b"hello world\r\n\t"), fingerprint(b"helloworld"))
        self.assertEqual(fingerprint(b""), 0x5BD15E36)


if __name__ == "__main__":
    unittest.main()
