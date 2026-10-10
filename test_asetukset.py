"""JSON-asetusten ja käyttöliittymän pysyvyyden tarkistukset ilman OCR:ää."""
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import numerontunnistin_paikallinen as app


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.last = self.folder / 'last.json'
        self.redirect = patch.object(app, 'LAST_SETTINGS', self.last)
        self.redirect.start()

    def tearDown(self):
        self.redirect.stop()
        self.temp.cleanup()

    def test_all_comparison_fields_in_gui_run_save_and_restart(self):
        # Tests must also work in a fresh checkout without private recordings/results.
        from test_paikallinen import make_video
        video = make_video()
        settings = replace(app.settings_from_json(app.BASE / 'examples/asetukset.example.json'),
                           exclusion=(0, 0, 270, 112))
        source = self.folder / 'parhaat_asetukset.json'
        app.save_settings_json(source, settings)
        root = app.tk.Tk()
        root.withdraw()
        try:
            ui = app.App(root)
            with patch.object(app.filedialog, 'askopenfilename', return_value=str(source)):
                ui.load_settings()
            self.assertEqual(asdict(ui.current_settings()), asdict(settings))
            self.assertIn(str(settings.exclusion), ui.area_values.get())
            with patch.object(app.filedialog, 'askopenfilename', return_value=str(video)):
                ui.open_video()
            self.assertEqual(ui.exclusion, settings.exclusion)
            saved = self.folder / 'export.json'
            with patch.object(app.filedialog, 'asksaveasfilename', return_value=str(saved)):
                ui.save_settings()
            self.assertEqual(asdict(app.settings_from_json(saved)), asdict(settings))
            ui.path = str(video)
            with patch.object(app.threading, 'Thread') as thread:
                ui.start()
                self.assertEqual(asdict(thread.call_args.kwargs['args'][1]), asdict(settings))
            self.assertEqual(asdict(app.settings_from_json(self.last)), asdict(settings))
            ui.cap.release()
        finally:
            root.destroy()
        root = app.tk.Tk()
        root.withdraw()
        try:
            restored = app.App(root)
            self.assertEqual(asdict(restored.current_settings()), asdict(settings))
            restored.set_busy(True)
            self.assertEqual(str(restored.load_settings_button['state']), 'disabled')
            self.assertEqual(str(restored.save_settings_button['state']), 'disabled')
        finally:
            root.destroy()

    def test_invalid_load_keeps_current_values(self):
        invalid = self.folder / 'invalid.json'
        invalid.write_text(json.dumps({'interval': .1, 'debug_frames': 'false'}), encoding='utf-8')
        root = app.tk.Tk()
        root.withdraw()
        try:
            ui = app.App(root)
            previous = ui.current_settings()
            with patch.object(app.filedialog, 'askopenfilename', return_value=str(invalid)), \
                    patch.object(app.messagebox, 'showerror') as error:
                ui.load_settings()
            error.assert_called_once()
            self.assertEqual(ui.current_settings(), previous)
        finally:
            root.destroy()

    def test_roi_and_bom_roundtrip(self):
        path = self.folder / 'roi.json'
        settings = app.Settings(roi=(10, 20, 300, 400), exclusion=(0, 0, 50, 60))
        path.write_text(json.dumps(asdict(settings)), encoding='utf-8-sig')
        self.assertEqual(app.settings_from_json(path), settings)
        app.save_settings_json(path, settings)
        self.assertEqual(app.settings_from_json(path), settings)

    def test_invalid_ranges_types_and_unknown_fields(self):
        path = self.folder / 'bad.json'
        for data in [{'roi': [0, 0, 0, 10]}, {'confirmation_count': True},
                     {'confidence': 2}, {'interval': float('nan')}, {'unknown': 1}, []]:
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(ValueError):
                app.settings_from_json(path)


if __name__ == '__main__':
    unittest.main()
