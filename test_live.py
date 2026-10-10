"""Live-putken katko-, puskuri-, tunnus- ja tallennustestit."""
import csv
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import live_video as live
import numerontunnistin_paikallinen as app


class Feed:
    def __init__(self):
        self.started = time.monotonic()
        self.stop = threading.Event()
        self.generation = 0
        self.sequence = 0

    def snapshot(self):
        self.sequence += 1
        return live.LiveFrame(np.zeros((180,320,3),np.uint8),time.monotonic(),time.time(),
                              self.sequence,self.generation),self.generation,'Yhdistetty'


class LiveTests(unittest.TestCase):
    def test_url_validation_and_redaction(self):
        for url in ['192.168.1.4', 'http://', 'file:///tmp/video', 'rtsp://camera:bad/stream']:
            with self.assertRaises(ValueError):
                live.validate_url(url)
        self.assertEqual(live.safe_url('rtsp://user:secret@camera:554/stream?password=secret'),
                         'rtsp://camera:554/stream')

    def test_live_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'settings.json'
            settings = app.Settings(source_type='Verkkovideo',stream_url='http://localhost/video')
            app.save_settings_json(path,settings)
            self.assertEqual(app.settings_from_json(path),settings)

    def test_live_gui_save_without_connection_and_changed_source_guard(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(app,'LAST_SETTINGS',Path(temp)/'last.json'):
            root=app.tk.Tk()
            root.withdraw()
            try:
                ui=app.App(root)
                settings=app.Settings(source_type='Verkkovideo',stream_url='http://localhost/video')
                ui.apply_settings(settings)
                exported=Path(temp)/'export.json'
                with patch.object(app.filedialog,'asksaveasfilename',return_value=str(exported)):
                    ui.save_settings()
                self.assertEqual(app.settings_from_json(exported),settings)
                ui.live_receiver=Feed()
                ui.live_receiver.config=dict(source_type='Verkkovideo',stream_url='http://localhost/other')
                with patch.object(app.messagebox,'showerror') as error,patch.object(app.threading,'Thread') as worker:
                    ui.start()
                error.assert_called_once()
                worker.assert_not_called()
            finally:
                root.destroy()

    def test_reception_keeps_latest_while_consumer_waits(self):
        class Pipe:
            def close(self):
                pass
        class Process:
            stdout = Pipe()
            def poll(self):
                return None
            def terminate(self):
                pass
            def wait(self,timeout=None):
                pass
        receiver=live.LiveReceiver({'source_type':'Verkkovideo'})
        count=0
        def read(stream):
            nonlocal count
            count+=1
            if count>20:
                newest,_,_=receiver.snapshot()
                self.assertEqual(newest.sequence,20)
                self.assertTrue(np.all(newest.image==20))
                self.assertEqual(newest.generation,1)
                self.assertGreaterEqual(time.monotonic()-newest.monotonic,0)
                receiver.stop.set()
                raise EOFError()
            return dict(shape=[2,2,3],wall=time.time(),
                        monotonic=time.monotonic()+(3 if count>=10 else 0)),bytes([count])*12
        with patch.object(live,'spawn',return_value=Process()),patch.object(live,'read_packet',side_effect=read):
            receiver.start()
            receiver.thread.join(timeout=2)
        self.assertEqual(receiver.sequence,20)
        self.assertFalse(receiver.thread.is_alive())
        self.assertFalse(hasattr(receiver,'queue'))

    def test_reconnection_during_ocr_drops_result_and_breaks_evidence(self):
        feed=Feed()
        stop=threading.Event()
        calls=0
        class Engine:
            device='test'
            def recognize(self,frame):
                nonlocal calls
                calls+=1
                if calls==2:
                    feed.generation+=1
                if calls==3:
                    stop.set()
                return [('233',.99,np.array([[60,60],[100,60],[100,95],[60,95]]))]
        with tempfile.TemporaryDirectory() as temp:
            out,summary=live.process_live(feed,app.Settings(interval=.01,confirmation_count=2,
                source_type='Verkkovideo',stream_url='http://user:secret@localhost/video?token=secret'),
                Engine(),stop,lambda s:None,lambda *a:None,Path(temp))
            tracks=[json.loads(l) for l in (out/'seurannat.jsonl').read_text().splitlines()]
            self.assertEqual(summary['saved_detections'],0)
            self.assertEqual(len(tracks),2)
            self.assertEqual([len(t['havainnot']) for t in tracks],[1,1])
            self.assertNotEqual(tracks[0]['seuranta_id'],tracks[1]['seuranta_id'])
            self.assertIn('live_yhteyskatko',tracks[0]['syyt'])
            with (out/'epavarmat.csv').open(encoding='utf-8-sig') as file:
                rows=list(csv.DictReader(file,delimiter=';'))
            self.assertTrue(rows)
            self.assertTrue(all(row['vastaanotto_kellonaika'] and row['istunnon_aika_s'] for row in rows))
            self.assertTrue(all((out/row['tarkistuskuva']).is_file() for row in rows))
            self.assertNotIn('secret',(out/'ajo.json').read_text())

    def test_empty_ocr_results_still_count_start_end_and_completion(self):
        feed=Feed()
        stop=threading.Event()
        diagnostics=live.LiveDiagnostics()
        messages=[]
        class Engine:
            device='test'
            def recognize(self,frame):
                state=diagnostics.snapshot()
                self_test.assertEqual(state['phase'],'OCR-kutsu käynnissä')
                self_test.assertEqual(state['submitted'],1)
                self_test.assertEqual(state['completed'],0)
                stop.set()
                return []
        self_test=self
        with tempfile.TemporaryDirectory() as temp:
            out,summary=live.process_live(feed,app.Settings(interval=.01),Engine(),stop,
                                        messages.append,lambda *a:None,Path(temp),diagnostics)
            state=diagnostics.snapshot()
            self.assertEqual((state['submitted'],state['completed']),(1,1))
            self.assertIsNotNone(state['first_start'])
            self.assertIsNotNone(state['first_end'])
            self.assertGreaterEqual(state['first_duration'],0)
            self.assertEqual(summary['ocr_completed'],1)
            self.assertEqual(summary['saved_detections'],0)
            self.assertTrue(any('ALKU' in m for m in messages))
            self.assertTrue(any('LOPPU' in m and 'numeroita 0' in m for m in messages))

    def test_ocr_error_has_complete_traceback_and_unfinished_counter(self):
        feed=Feed()
        diagnostics=live.LiveDiagnostics()
        class Engine:
            device='test'
            def recognize(self,frame):
                raise RuntimeError('OCR-testivirhe')
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError,'OCR-testivirhe'):
                live.process_live(feed,app.Settings(),Engine(),threading.Event(),lambda s:None,
                                  lambda *a:None,Path(temp),diagnostics)
            state=diagnostics.snapshot()
            self.assertEqual((state['submitted'],state['completed']),(1,0))
            self.assertIn('Traceback (most recent call last)',state['error'])
            self.assertIn('in recognize',state['error'])
            self.assertTrue(state['first_failed'])
            self.assertIsNotNone(state['first_end'])
            self.assertGreaterEqual(state['first_duration'],0)
            self.assertTrue(list(Path(temp).glob('*/virhe.txt')))

    def test_gui_shows_empty_counters_and_full_worker_traceback(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(app,'LAST_SETTINGS',Path(temp)/'last.json'), \
                patch.object(app,'BASE',Path(temp)):
            root=app.tk.Tk()
            root.withdraw()
            try:
                ui=app.App(root)
                ui.source_type.set('NDI')
                ui.engine=type('Engine',(),dict(preference='auto',device='test'))()
                with patch.object(app,'process_live',side_effect=RuntimeError('Live-työntekijän testivirhe')):
                    ui.worker(Feed(),app.Settings(source_type='NDI'))
                with patch.object(app.messagebox,'showerror') as error:
                    ui.poll()
                self.assertIn('OCR:lle annettu 0',ui.live_counters.get())
                self.assertIn('OCR valmistunut 0',ui.live_counters.get())
                self.assertIn('työntekijäsäikeen virhe',ui.live_counters.get())
                self.assertIn('Traceback (most recent call last)',ui.log.get('1.0','end'))
                self.assertIn('Live-työntekijän testivirhe',ui.log.get('1.0','end'))
                self.assertIn('Traceback',error.call_args.args[1])
                self.assertTrue(list(Path(temp).glob('paikalliset_tulokset/live_diagnostiikka/*.jsonl')))
            finally:
                root.destroy()

    def test_waiting_for_frame_is_distinguishable_from_running_ocr(self):
        feed=Feed()
        stop=threading.Event()
        def snapshot():
            stop.set()
            return None,0,'Yhdistetään'
        feed.snapshot=snapshot
        diagnostics=live.LiveDiagnostics()
        class Engine:
            device='test'
            def recognize(self,frame):
                raise AssertionError('OCR ei saa alkaa ilman kuvaa')
        with tempfile.TemporaryDirectory() as temp:
            live.process_live(feed,app.Settings(),Engine(),stop,lambda s:None,lambda *a:None,
                              Path(temp),diagnostics)
            entries=[json.loads(line) for line in diagnostics.path.read_text().splitlines()]
            self.assertTrue(any(e['phase']=='odottaa uutta vastaanottokuvaa' for e in entries))
            self.assertEqual(diagnostics.snapshot()['submitted'],0)


if __name__=='__main__':
    unittest.main()
