import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from packforge.common import PackError
from packforge.game_runtime import prepare_runtime, runtime_spec


def manifest(loader="Fabric", version="0.16.9", mc="1.20.1"):
    uids = {"Fabric": "net.fabricmc.fabric-loader", "Forge": "net.minecraftforge",
            "Quilt": "org.quiltmc.quilt-loader", "NeoForge": "net.neoforged"}
    components = [{"uid": "net.minecraft", "version": mc}]
    if loader:
        components.append({"uid": uids[loader], "version": version})
    return {"minecraft": mc, "components": {"components": components}}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.game = self.root / "game"
        self.game.mkdir()
        self.staging = self.root / "stage"
        self.staging.mkdir()

    def vanilla(self, mc, directory, callback=None):
        directory = Path(directory)
        version = directory / "versions" / mc
        version.mkdir(parents=True, exist_ok=True)
        (version / f"{mc}.json").write_text(json.dumps({"javaVersion": {"component": "java-runtime-gamma"}}))
        (version / f"{mc}.jar").write_bytes(b"vanilla-client")

    def loader_install(self, mc, directory, **kwargs):
        directory = Path(directory)
        version = directory / "versions/test-loader-version"
        version.mkdir(parents=True, exist_ok=True)
        (version / "test-loader-version.json").write_text('{"id":"test-loader-version"}')
        (directory / "launcher_profiles.json").write_text('{"accounts": "do-not-publish"}')
        libs = directory / "libraries"
        libs.mkdir(exist_ok=True)
        (libs / "loader.jar").write_bytes(b"modloader")
        return "test-loader-version"

    def test_all_loaders_use_exact_versions(self):
        for name, version in [("Fabric", "0.16.9"), ("Quilt", "0.26.4"),
                              ("Forge", "47.4.0"), ("NeoForge", "21.1.1")]:
            with self.subTest(loader=name):
                stage = self.staging / name
                stage.mkdir()
                loader = MagicMock()
                loader.get_installed_version.return_value = "test-loader-version"
                loader.install.side_effect = self.loader_install
                with patch("packforge.game_runtime.mod_loader.get_mod_loader", return_value=loader) as get_loader, \
                     patch("packforge.game_runtime.mc_install.install_minecraft_version", side_effect=self.vanilla), \
                     patch("packforge.game_runtime.runtime.get_executable_path", return_value="managed-java.exe"):
                    result = prepare_runtime(manifest(name, version), stage, self.game, log=lambda _: None)
                get_loader.assert_called_once_with(name.lower())
                self.assertEqual(loader.install.call_args.kwargs["loader_version"], version)
                self.assertEqual(loader.install.call_args.args[0], "1.20.1")
                if name in ("Forge", "NeoForge"):
                    self.assertEqual(loader.install.call_args.kwargs["java"], "managed-java.exe")
                self.assertEqual(result.version_id, "test-loader-version")
                self.assertFalse(any(p.name == "launcher_profiles.json" for p, _ in result.files))
                self.assertFalse((self.game / "versions").exists())

    def test_vanilla_without_loader(self):
        with patch("packforge.game_runtime.mc_install.install_minecraft_version", side_effect=self.vanilla), \
             patch("packforge.game_runtime.mod_loader.get_mod_loader") as get_loader:
            result = prepare_runtime(manifest(None), self.staging, self.game, log=lambda _: None)
        get_loader.assert_not_called()
        self.assertEqual(result.version_id, "1.20.1")

    def test_cached_files_are_copies_and_unchanged_files_are_not_published(self):
        libs = self.game / "libraries"
        libs.mkdir()
        (libs / "shared.jar").write_bytes(b"cached")

        def modify_cache(mc, directory, callback=None):
            self.vanilla(mc, directory, callback)
            self.assertEqual((Path(directory) / "libraries/shared.jar").read_bytes(), b"cached")
            (Path(directory) / "libraries/shared.jar").write_bytes(b"new library")

        with patch("packforge.game_runtime.mc_install.install_minecraft_version", side_effect=modify_cache):
            result = prepare_runtime(manifest(None), self.staging, self.game, log=lambda _: None)
        self.assertEqual((libs / "shared.jar").read_bytes(), b"cached")
        self.assertIn(libs / "shared.jar", [p for p, _ in result.files])

    def test_java_is_downloaded_when_missing(self):
        loader = MagicMock()
        loader.get_installed_version.return_value = "test-loader-version"
        loader.install.side_effect = self.loader_install
        with patch("packforge.game_runtime.mod_loader.get_mod_loader", return_value=loader), \
             patch("packforge.game_runtime.mc_install.install_minecraft_version", side_effect=self.vanilla), \
             patch("packforge.game_runtime.runtime.get_executable_path", side_effect=[None, "downloaded-java.exe"]), \
             patch("packforge.game_runtime.runtime.install_jvm_runtime") as install_java:
            prepare_runtime(manifest("Forge", "47.4.0"), self.staging, self.game, log=lambda _: None)
        self.assertEqual(install_java.call_args.args[0], "java-runtime-gamma")
        self.assertEqual(loader.install.call_args.kwargs["java"], "downloaded-java.exe")

    def test_forge_prism_version_normalized_without_selecting_latest(self):
        self.assertEqual(runtime_spec(manifest("Forge", "1.20.1-47.4.0")), ("1.20.1", "forge", "47.4.0"))

    def test_conflicting_and_unsafe_versions_rejected(self):
        invalid = manifest()
        invalid["components"]["components"].append({"uid": "net.minecraftforge", "version": "47.4.0"})
        with self.assertRaises(PackError):
            runtime_spec(invalid)
        with self.assertRaises(PackError):
            runtime_spec(manifest(version="../../evil"))
        invalid = manifest()
        invalid["minecraft"] = "1.21.1"
        with self.assertRaises(PackError):
            runtime_spec(invalid)

    def test_download_failure_does_not_modify_live_runtime(self):
        with patch("packforge.game_runtime.mc_install.install_minecraft_version", side_effect=OSError("offline")):
            with self.assertRaises(PackError):
                prepare_runtime(manifest(None), self.staging, self.game, log=lambda _: None)
        self.assertFalse((self.game / "versions").exists())

    def test_missing_client_is_not_reported_as_success(self):
        with patch("packforge.game_runtime.mc_install.install_minecraft_version"):
            with self.assertRaises(PackError):
                prepare_runtime(manifest(None), self.staging, self.game, log=lambda _: None)


if __name__ == "__main__":
    unittest.main()
