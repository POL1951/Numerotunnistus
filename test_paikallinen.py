"""Toistettavat tekniset testit; --ocr suorittaa myös oikean PaddleOCR-testin."""
import csv
import json
import sys
import threading
import time
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
import cv2
import numpy as np
import numerontunnistin_paikallinen as app

ARTIFACTS = app.BASE / 'testiaineisto'


def make_video():
    ARTIFACTS.mkdir(exist_ok=True)
    path = ARTIFACTS / 'numerot_testi.mp4'
    frame = np.full((540, 960, 3), 255, np.uint8)
    for i, number in enumerate(['1', '2', '3', '4', '5', '6', '7', '8', '9', '123']):
        x, y = 35 + (i % 5) * 185, 150 + (i // 5) * 220
        cv2.putText(frame, number, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (960, 540))
    if not writer.isOpened():
        raise RuntimeError('MP4-testivideon kirjoitus epäonnistui')
    for _ in range(20):
        writer.write(frame)
    writer.release()
    return path


class FakeEngine:
    device = 'test'
    preference = 'auto'
    def recognize(self, frame):
        time.sleep(0.02)  # Hitaampi kuin testin 0,01 s näyteväli.
        def polygon(x):
            return np.array([[x, 20], [x + 30, 20], [x + 30, 50], [x, 50]])
        return [('1', 0.98, polygon(20)), ('9', 0.90, polygon(180)),
                ('123', 0.85, polygon(350)), ('1', 0.70, polygon(20))]


class Tests(unittest.TestCase):
    def setUp(self):
        self.settings_temp = tempfile.TemporaryDirectory()
        self.settings_redirect = patch.object(app, 'LAST_SETTINGS', Path(self.settings_temp.name) / 'last.json')
        self.settings_redirect.start()

    def tearDown(self):
        self.settings_redirect.stop()
        self.settings_temp.cleanup()

    def test_numbers(self):
        for n in range(1, 10):
            self.assertEqual(app.numeric_text(str(n)), str(n))
        self.assertEqual(app.numeric_text(' 00123 '), '123')
        for text in ['0', 'runner123', '1O', '-2', '12.3', '']:
            self.assertIsNone(app.numeric_text(text))

    def test_duplicate_boundary(self):
        f = app.DuplicateFilter(10)
        self.assertTrue(f.accept('1', 0))
        self.assertFalse(f.accept('1', 9.9))
        self.assertTrue(f.accept('1', 10))
        self.assertTrue(f.accept('9', 10))

    def test_video_pipeline(self):
        path = make_video()
        out, summary = app.process_video(path, app.Settings(interval=0.01, duplicate_seconds=1),
                                         FakeEngine(), threading.Event(), print, lambda *args: None,
                                         ARTIFACTS / 'tekniset_tulokset')
        self.assertEqual(summary['processed_frames'], 20)
        self.assertEqual(summary['saved_detections'], 3)
        self.assertFalse((out / 'debug').exists())
        self.assertEqual(len(list((out / 'kuvat').glob('*.jpg'))), 3)
        self.assertFalse(list((out / 'kuvat').glob('*.png')))
        with (out / 'havainnot.csv').open(encoding='utf-8-sig') as file:
            rows = list(csv.DictReader(file, delimiter=';'))
        self.assertEqual({r['numero'] for r in rows}, {'1', '9', '123'})
        self.assertEqual({float(r['videon_aika_s']) for r in rows}, {0})

    def test_stop_after_current_frame(self):
        stop = threading.Event()
        out, summary = app.process_video(make_video(), app.Settings(interval=0.1), FakeEngine(), stop,
                                         print, lambda *args: stop.set(), ARTIFACTS / 'tekniset_tulokset')
        self.assertTrue(summary['stopped'])
        self.assertEqual(summary['processed_frames'], 1)
        self.assertEqual(summary['saved_detections'], 0)
        self.assertEqual(summary['uncertain_candidates'], 3)

    def test_interval_confidence_and_roi(self):
        class CroppedEngine(FakeEngine):
            def recognize(inner, frame):
                self.assertEqual(frame.shape[:2], (200, 400))
                return super(CroppedEngine, inner).recognize(frame)
        out, summary = app.process_video(make_video(), app.Settings(interval=0.5, duplicate_seconds=0,
                                         confidence=0.95, roi=(20, 30, 420, 230), debug_frames=True), CroppedEngine(),
                                         threading.Event(), print, lambda *args: None,
                                         ARTIFACTS / 'tekniset_tulokset')
        self.assertEqual(summary['processed_frames'], 4)
        self.assertEqual(summary['saved_detections'], 1)
        self.assertEqual(summary['uncertain_candidates'], 2)
        self.assertEqual(len(list((out / 'debug').glob('*.png'))), 8)
        with (out / 'havainnot.csv').open(encoding='utf-8-sig') as file:
            rows = list(csv.DictReader(file, delimiter=';'))
        self.assertEqual([float(r['videon_aika_s']) for r in rows], [0])
        self.assertEqual(float(rows[0]['vahvistettu_aika_s']), 1.0)
        self.assertEqual({r['numero'] for r in rows}, {'1'})

    def test_gui(self):
        root = app.tk.Tk()
        root.withdraw()
        ui = app.App(root)
        root.update()
        ui.frame = np.zeros((540, 960, 3), np.uint8)
        ui.draw()
        ui.set_busy(True)
        ui.set_busy(False)
        root.update()
        with patch.object(app.filedialog, 'askopenfilename', return_value=str(make_video())):
            ui.open_video()
        self.assertEqual(ui.frame.shape[:2], (540, 960))
        ui.transform = (1, 1, 0, 0)
        ui.draw_target.set('exclusion')
        with patch.object(ui, 'draw'):
            ui.drag_start(SimpleNamespace(x=10, y=10))
            ui.drag_end(SimpleNamespace(x=80, y=55))
        self.assertEqual(ui.exclusion, (10, 10, 80, 55))
        self.assertIsNone(ui.roi)
        ui.clear_exclusion()
        ui.draw_target.set('roi')
        ui.seek_video('5')
        ui.toggle_preview()
        ui.toggle_preview()
        ui.interval.set('0.5')
        ui.engine = FakeEngine()
        real_process = app.process_video
        def redirected(*args, **kwargs):
            return real_process(*args, **kwargs, output_root=ARTIFACTS / 'gui_tulokset')
        main_id = threading.get_ident()
        original_note = ui.note
        def main_thread_note(text):
            self.assertEqual(threading.get_ident(), main_id)
            original_note(text)
        ui.note = main_thread_note
        with patch.object(app, 'process_video', side_effect=redirected):
            ui.start()
            deadline = time.monotonic() + 10
            while ui.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            self.assertFalse(ui.busy)
        self.assertIn('Valmis:', ui.status.get())
        ui.close()


def real_ocr():
    if '--offline' in sys.argv:
        import socket
        def deny_network(*args, **kwargs):
            raise RuntimeError('Verkkoyhteys estetty offline-testissä')
        socket.socket.connect = deny_network
        socket.socket.connect_ex = deny_network
        socket.create_connection = deny_network
        socket.getaddrinfo = deny_network
    path = make_video()
    started = time.perf_counter()
    engine = app.PaddleEngine('cpu' if '--cpu' in sys.argv else 'auto', print)
    init_seconds = time.perf_counter() - started
    out, summary = app.process_video(path, app.Settings(interval=0.5, duplicate_seconds=0), engine,
                                     threading.Event(), print, lambda *args: None,
                                     ARTIFACTS / 'ocr_tulokset')
    with (out / 'havainnot.csv').open(encoding='utf-8-sig') as file:
        rows = list(csv.DictReader(file, delimiter=';'))
    numbers = sorted({row['numero'] for row in rows}, key=int)
    result = {'device': engine.device, 'initialization_seconds': init_seconds,
              'numbers': numbers, 'summary': summary, 'output': str(out)}
    suffix = ('_cpu' if '--cpu' in sys.argv else '_gpu') + ('_offline' if '--offline' in sys.argv else '')
    (ARTIFACTS / f'ocr_testiraportti{suffix}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    assert summary['processed_frames'] == 4
    assert len(numbers) >= 2, 'Usean numeron tunnistus ei onnistunut synteettisellä videolla'
    assert any(str(n) in numbers for n in range(1, 10)), 'Yksinumeroinen havainto puuttui'


if __name__ == '__main__':
    if '--ocr' in sys.argv:
        real_ocr()
    else:
        unittest.main()
