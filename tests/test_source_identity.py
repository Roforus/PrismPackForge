import json
import tempfile
import unittest
from pathlib import Path

from packforge.common import PackError
from packforge.preferences import load_settings, save_settings
from packforge.source_identity import source_id, save_source_id, IDENTITY_FILE


class SourceIdentityTests(unittest.TestCase):
    def test_source_identity_survives_rename_and_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'first-name'
            folder.mkdir()
            save_source_id(folder,source_id(folder))
            renamed = folder.with_name('renamed')
            folder.rename(renamed)
            self.assertEqual(source_id(renamed),'first-name')
            save_source_id(renamed,'custom-id')
            self.assertEqual(source_id(renamed),'custom-id')

    def test_installed_pack_identity_is_used_before_folder_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/'.minecraft/.packforge').mkdir(parents=True)
            (folder/'.minecraft/.packforge/state.json').write_text('{"id":"published-id"}')
            self.assertEqual(source_id(folder),'published-id')

    def test_corrupt_identity_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/IDENTITY_FILE).write_text('broken')
            with self.assertRaises(PackError):
                source_id(folder)

    def test_last_export_snapshot_roundtrip_does_not_store_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'cache.json'
            snapshot = {'instance':'D:/pack','name':'Pack','version':'1.0','pack_id':'pack',
                        'output':'D:/out','launcher':'Prism Launcher','api_key':'secret'}
            save_settings({'last_export':snapshot,'profiles':{}},path)
            saved = load_settings(path)['last_export']
            self.assertEqual(saved['instance'],'D:/pack')
            self.assertNotIn('secret',path.read_text())
