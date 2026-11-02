import json
import tempfile
import unittest
from pathlib import Path

from packforge.preferences import load_settings, save_settings
from packforge.prism_instances import list_instances


class ExportPreferencesTests(unittest.TestCase):
    def test_preferences_roundtrip_excludes_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'settings.json'
            data = dict(last_instance='D:/Prism/instances/a', prism_roots=['D:/Prism'], api_key='secret',
                        profiles={'D:/Prism/instances/a':dict(pack_id='a',version='2.0',name='Сборка',
                            include_options=True,make_exe=False,output='D:/exports',curseforge_key='secret')})
            save_settings(data,path)
            saved = load_settings(path)
            self.assertNotIn('secret',path.read_text('utf-8'))
            self.assertEqual(saved['profiles'][data['last_instance']]['version'],'2.0')
            self.assertTrue(saved['profiles'][data['last_instance']]['include_options'])
            path.write_text('broken json')
            self.assertEqual(load_settings(path),{})

    def test_prism_custom_instances_names_and_duplicate_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prism = root/'portable'
            instance = prism/'custom/instance-id'
            instance.mkdir(parents=True)
            (instance/'mmc-pack.json').write_text('{}')
            (instance/'instance.cfg').write_text('[General]\nname=Моя сборка\n',encoding='utf-8')
            (prism/'prismlauncher.cfg').write_text('[General]\nInstanceDir=custom\n')
            (prism/'custom/not-an-instance').mkdir()
            found = list_instances([prism,prism/'custom'],launchers=[],appdata=root/'app')
            self.assertEqual(len(found),1)
            self.assertEqual(found[0].path,instance.resolve())
            self.assertEqual(found[0].name,'Моя сборка')
