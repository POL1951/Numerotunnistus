import unittest
from types import SimpleNamespace
import numpy as np
import numerontunnistin_paikallinen as app
import live_video


class RawTests(unittest.TestCase):
    def test_live_background_flow_cannot_extend_ocr_gap(self):
        track = SimpleNamespace(id=7, last_visual=100., last_detection=5.)
        tracker = SimpleNamespace(active={7:track}, settings=app.Settings(track_gap=2.))
        self.assertEqual(live_video.retire_live_without_ocr(tracker, 7.), [])
        self.assertEqual(live_video.retire_live_without_ocr(tracker, 7.01), [track])
        self.assertEqual(tracker.active, {})

    def test_raw_keeps_non_numeric_low_score_and_small_text(self):
        polygon = np.array([[0,0],[5,0],[5,2],[0,2]])
        engine = app.PaddleEngine.__new__(app.PaddleEngine)
        engine.ocr = SimpleNamespace(predict=lambda image: [dict(
            rec_texts=['teksti', '738', ''], rec_scores=[.1,.2,.0],
            rec_polys=[polygon,polygon,polygon])])
        found = engine.recognize(np.zeros((10,10,3),np.uint8))
        self.assertEqual([x['text'] for x in engine.last_raw], ['teksti','738',''])
        self.assertEqual([x[0] for x in found], ['738'])
        self.assertEqual(engine.last_raw[1]['confidence'], .2)
        engine.ocr.predict = lambda image: []
        self.assertEqual(engine.recognize(np.zeros((10,10,3),np.uint8)), [])
        self.assertEqual(engine.last_raw, [])


if __name__ == '__main__':
    unittest.main()
