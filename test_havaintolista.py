"""Havaintolistan sijoittelu, vastaanottoajat ja koko istunnon CSV-vienti."""
import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import tkinter as tk
import numerontunnistin_paikallinen as app
from live_video import LiveRecorder


class ObservationListTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.settings_patch = patch.object(app, 'LAST_SETTINGS', Path(self.temp.name)/'last.json')
        self.settings_patch.start()
        self.ui = app.App(self.root)
        self.root.update()

    def tearDown(self):
        for callback in self.root.tk.call('after', 'info'):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.settings_patch.stop()
        self.temp.cleanup()

    def export(self):
        path = Path(self.temp.name)/'list.csv'
        with patch.object(app.filedialog, 'asksaveasfilename', return_value=str(path)):
            self.ui.export_observations()
        self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
        with path.open(encoding='utf-8-sig', newline='') as file:
            return list(csv.reader(file, delimiter=';'))

    def test_panel_is_right_of_video_and_resizes(self):
        ui = self.ui
        self.assertEqual(tuple(ui.observation_list['columns']), ('numero', 'aika'))
        for geometry in ('1550x1000', '1450x850'):
            self.root.geometry(geometry)
            self.root.update()
            self.assertEqual(ui.results_panel.winfo_width(), 300)
            self.assertGreaterEqual(ui.results_panel.winfo_x(), ui.canvas.winfo_x()+ui.canvas.winfo_width())
            self.assertLessEqual(abs(ui.results_panel.winfo_height()-ui.canvas.winfo_y()-ui.canvas.winfo_height()), 10)

    def test_mp4_sorted_export_while_busy_preserves_list(self):
        for number, timestamp in [('0033', 3661), ('96', 7), ('172', 60)]:
            self.ui.add_observation(dict(numero=number, videon_aika_s=timestamp))
        self.ui.busy = True
        expected = [['numero', 'videon_aika'], ['96', '00:00:07'],
                    ['172', '00:01:00'], ['0033', '01:01:01']]
        self.assertEqual(self.export(), expected)
        self.ui.stop_run()
        self.ui.events.put(('done', None))
        self.ui.poll()
        self.assertEqual(self.export(), expected)
        self.assertEqual(len(self.ui.observation_rows), 3)

    def test_live_time_uses_preserved_reception_clock(self):
        self.ui.observation_live = True
        recorder = LiveRecorder.__new__(LiveRecorder)
        recorder.clocks = {'2.500000': datetime(2026, 10, 11, 8, 35, 7).timestamp()}
        row = recorder.accepted_event(dict(numero='0033', videon_aika_s='2.500000'))
        self.ui.events.put(('observation', row))
        self.ui.poll()
        self.assertEqual(self.export(), [['numero', 'kellonaika'], ['0033', '08:35:07']])

    def test_scroll_follows_newest_unless_reading_older_rows(self):
        for i in range(100):
            self.ui.add_observation(dict(numero=str(i), videon_aika_s=i))
        self.root.update()
        self.assertAlmostEqual(self.ui.observation_list.yview()[1], 1, places=2)
        self.ui.observation_list.yview_moveto(0)
        self.root.update()
        self.ui.add_observation(dict(numero='101', videon_aika_s=101))
        self.root.update()
        self.assertEqual(self.ui.observation_list.yview()[0], 0)


if __name__ == '__main__':
    unittest.main()
