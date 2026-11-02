import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from packforge.export_ui import ExporterUI
from packforge.prism_instances import PrismInstance


class ExportUiTests(unittest.TestCase):
    def setUp(self):
        try:
            probe = tk.Tk()
            probe.destroy()
        except tk.TclError:
            self.skipTest('Tk display is unavailable')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.items = [PrismInstance(root/'prism','Prism pack','prism'),
                      PrismInstance(root/'multimc','MultiMC pack','multimc')]
        for name,value in [('load_settings',{}),('list_instances',self.items)]:
            p = patch('packforge.export_ui.'+name,return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = patch('packforge.export_ui.save_settings')
        self.save = p.start()
        self.addCleanup(p.stop)
        p = patch('packforge.appearance.save_theme')
        p.start()
        self.addCleanup(p.stop)
        self.ui = ExporterUI()
        self.ui.window.root.update()
        def close():
            root = self.ui.window.root
            for timer in root.tk.call('after','info'):
                root.after_cancel(timer)
            root.destroy()
        self.addCleanup(close)

    def update(self):
        self.ui.window.root.update()

    def test_instance_launcher_filters_packs_and_hides_runtime_fields(self):
        ui = self.ui
        self.assertEqual(len(ui.available),1)
        self.assertEqual(ui.instance.get(),str(self.items[0].path))
        self.assertFalse(ui.game_frame.winfo_ismapped())
        ui.launcher.set('MultiMC')
        ui.change_launcher()
        self.update()
        self.assertEqual(ui.instance.get(),str(self.items[1].path))
        self.assertTrue(ui.instance_frame.winfo_ismapped())
        self.assertFalse(ui.game_frame.winfo_ismapped())

    def test_game_folder_and_vanilla_have_only_relevant_fields(self):
        ui = self.ui
        ui.launcher.set('Modrinth App')
        ui.change_launcher()
        self.update()
        self.assertFalse(ui.instance_frame.winfo_ismapped())
        self.assertTrue(ui.game_frame.winfo_ismapped())
        ui.loader.set('Fabric')
        ui.update_loader()
        self.update()
        self.assertTrue(ui.loader_row.winfo_ismapped())
        ui.loader.set('Vanilla')
        ui.update_loader()
        self.update()
        self.assertFalse(ui.loader_row.winfo_ismapped())

    def test_advanced_settings_and_theme_mode(self):
        ui = self.ui
        ui.open_settings()
        self.update()
        self.assertTrue(ui.dialog.winfo_exists())
        ui.key.set('session-secret')
        ui.pack_id.set('permanent-id')
        ui.remember()
        saved = self.save.call_args.args[0]
        self.assertEqual(saved['profiles'][ui.instance.get()]['pack_id'],'permanent-id')
        self.assertNotIn('session-secret',str(saved))
        ui.window.set_theme_mode('dark')
        self.assertEqual(ui.window.theme_button.cget('text'),'☀')
        ui.window.set_theme_mode('light')
        self.assertEqual(ui.window.theme_button.cget('text'),'☾')
        with patch('packforge.appearance.system_theme',return_value='dark'):
            ui.window.set_theme_mode('system')
            self.assertEqual(ui.window.theme,'dark')

    def test_last_export_is_updated_only_after_success(self):
        ui = self.ui
        ui.name.set('Release')
        old = {'instance':'previous','version':'old'}
        ui.settings['last_export'] = old
        with patch.object(ui.window,'run_task') as run:
            ui.start()
            self.assertIs(ui.settings['last_export'],old)
            run.call_args.kwargs['on_success']()
        self.assertEqual(ui.settings['last_export']['name'],'Release')
        self.assertEqual(ui.settings['last_export']['instance'],str(self.items[0].path.resolve()))
        ui.version.set('new draft')
        ui.remember()
        self.assertEqual(ui.settings['last_export']['version'],'1.0.0')

    def test_cached_id_cannot_replace_source_id(self):
        from packforge.source_identity import save_source_id
        folder = self.items[0].path
        folder.mkdir()
        save_source_id(folder,'source-id')
        self.ui.profiles[str(folder)] = {'pack_id':'cached-id'}
        self.ui.load_profile(folder,'Pack')
        self.assertEqual(self.ui.pack_id.get(),'source-id')
