import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from numerontunnistin_paikallinen import Settings
from havaintoseuranta import Track, Observation
from seurannan_tallennus import TrackRecorder
from tallennusrajat import StorageBudget, RotatingText, IMAGE_RESERVE


class StorageTests(unittest.TestCase):
    def make_track(self, recorder, variants, accepted=False):
        box = (20, 20, 80, 60)
        track = Track(1, box, 1, 1, 1, np.array([50, 40]), None)
        image = np.random.default_rng(4).integers(0, 255, (120, 160, 3), dtype=np.uint8)
        for number in variants:
            for frame in range(3):
                obs = Observation(number, .99, np.array([[20,20],[80,20],[80,60],[20,60]]), frame*.25, frame)
                track.add(obs)
                recorder.observation(track, obs, image)
        if not accepted:
            track.review_reasons.add('test_review')
        return track

    def test_uncertain_event_has_at_most_three_jpegs_all_rows_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            recorder = TrackRecorder(path, Settings())
            track = self.make_track(recorder, ['1','2','3','4','5'])
            self.assertFalse(list(path.rglob('*.jpg')))
            recorder.finalize(track)
            recorder.close()
            self.assertEqual(len(list(path.rglob('*.jpg'))), 3)
            with (path/'epavarmat.csv').open(encoding='utf-8-sig') as file:
                rows = list(csv.DictReader(file, delimiter=';'))
            self.assertEqual(len(rows), 5)
            self.assertEqual(sum(bool(row['tarkistuskuva']) for row in rows), 3)

    def test_best_accepted_frame_and_one_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            recorder = TrackRecorder(path, Settings())
            track = self.make_track(recorder, ['33'], accepted=True)
            # Later weaker images do not overwrite the best frame.
            obs = Observation('33', .8, np.array([[20,20],[80,20],[80,60],[20,60]]), 1, 4)
            track.add(obs)
            recorder.observation(track, obs, np.zeros((120,160,3),np.uint8))
            recorder.finalize(track)
            recorder.close()
            self.assertEqual(len(list(path.rglob('*.jpg'))), 1)
            with (path/'havainnot.csv').open(encoding='utf-8-sig') as file:
                row = next(csv.DictReader(file, delimiter=';'))
            self.assertEqual(row['kuvan_aika_s'], '0.000000')
            self.assertTrue((path/row['tarkistuskuva']).read_bytes().startswith(b'\xff\xd8'))

    def test_low_space_continues_csv_and_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            messages = []
            recorder = TrackRecorder(Path(directory), Settings(), report=messages.append)
            track = self.make_track(recorder, ['33'], accepted=True)
            with patch.object(recorder.storage, 'free', return_value=IMAGE_RESERVE-1):
                recorder.finalize(track)
            recorder.close()
            self.assertEqual(recorder.saved, 1)
            self.assertFalse(list(Path(directory).rglob('*.jpg')))
            self.assertTrue(any('KUVATALLENNUS KESKEYTETTY' in message for message in messages))
            with (Path(directory)/'havainnot.csv').open(encoding='utf-8-sig') as file:
                self.assertEqual(next(csv.DictReader(file, delimiter=';'))['tarkistuskuva'], '')

    def test_image_write_error_continues_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            messages = []
            recorder = TrackRecorder(Path(directory), Settings(), report=messages.append)
            track = self.make_track(recorder, ['33'], accepted=True)
            with patch.object(Path, 'write_bytes', side_effect=OSError('disk failed')):
                recorder.finalize(track)
            recorder.close()
            self.assertEqual(recorder.saved, 1)
            self.assertTrue(any('disk failed' in message for message in messages))

    def test_debug_budget_and_rotation_never_touch_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            csv_path = path/'havainnot.csv'
            csv_path.write_text('keep', encoding='utf-8')
            budget = StorageBudget(path)
            with patch('tallennusrajat.DEBUG_LIMIT', 10):
                self.assertTrue(budget.write_image(path/'a.png', b'12345', debug=True))
                self.assertFalse(budget.write_image(path/'b.png', b'123456', debug=True))
            log = RotatingText(path/'technical.jsonl', limit=20)
            for _ in range(100):
                log.write('0123456789\n')
            log.flush(); log.close()
            parts = list(path.glob('technical.jsonl*'))
            self.assertEqual(len(parts), 4)
            self.assertTrue(all(p.stat().st_size <= 20 for p in parts))
            self.assertEqual(csv_path.read_text(), 'keep')

    def test_csv_write_failure_is_reported_and_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            messages = []
            recorder = TrackRecorder(Path(directory), Settings(), report=messages.append)
            with patch('seurannan_tallennus.os.fsync', side_effect=OSError('CSV disk full')):
                with self.assertRaisesRegex(OSError, 'CSV disk full'):
                    recorder.flush()
            recorder.close()
            self.assertTrue(any('CSV' in message and 'disk full' in message for message in messages))

    def test_live_normal_mode_never_saves_ocr_inputs(self):
        import threading
        import live_video as live
        from test_live import Feed
        feed = Feed()
        for source in ('NDI', 'Verkkovideo'):
            stop = threading.Event()
            class Engine:
                device = 'test'
                last_raw = []
                def recognize(self, image):
                    stop.set()
                    return []
            with tempfile.TemporaryDirectory() as directory:
                settings = Settings(source_type=source, stream_url='http://localhost/video')
                output, _ = live.process_live(feed, settings, Engine(), stop,
                    lambda text: None, lambda *a: None, Path(directory))
                self.assertFalse((output/'ocr_syotteet').exists())
                self.assertFalse((output/'debug').exists())
                self.assertFalse(list(output.rglob('*.png')))
                self.assertFalse(list(output.rglob('*.mp4')))


if __name__ == '__main__':
    unittest.main()
