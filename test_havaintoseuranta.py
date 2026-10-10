"""Vahvistuksen, ristiriitojen, seurantaidentiteetin ja rajauksen regressiotestit."""
import csv
import json
import threading
import unittest
import tempfile
from pathlib import Path
import cv2
import numpy as np
import numerontunnistin_paikallinen as app
from havaintoseuranta import BibTracker, Track, Observation

OUTPUT = app.BASE / 'testiaineisto' / 'seurantatestit'


def polygon(x=60, y=60, w=40, h=25):
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.int32)


def track_with(observations):
    track = Track(1, (60, 60, 100, 85), 0, 0, 0, np.array([80, 72]), None)
    for number, time, index, confidence in observations:
        track.add(Observation(number, confidence, polygon(), time, index))
    return track


def write_video(name, frame, frames=20, fps=10):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / name
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), fps,
                             (frame.shape[1], frame.shape[0]))
    if not writer.isOpened():
        raise RuntimeError('Testivideon kirjoitus epäonnistui')
    for _ in range(frames):
        writer.write(frame)
    writer.release()
    return path


class Tests(unittest.TestCase):
    def test_geometry_reconnects_expanded_box_after_occlusion_without_text_matching(self):
        frame = np.full((240, 640, 3), 220, dtype=np.uint8)
        tracker = BibTracker(app.Settings(track_gap=2))
        added, _ = tracker.update(frame, 0, 0, [('28', .99, polygon(h=12))])
        track = added[0][0]
        track.velocity = np.array([60., 0.])
        added, _ = tracker.update(frame, 1.5, 45, [('81', .99, polygon(x=180, h=60))])
        self.assertEqual(added[0][0].id, track.id)
        self.assertEqual(set(track.observations), {'28', '81'})

    def test_small_boxes_are_kept_but_do_not_confirm_or_veto(self):
        track = track_with([('28', i * .2, i, .99) for i in range(3)])
        track.add(Observation('8', .9999, polygon(h=12), 1, 30))
        self.assertEqual(track.decision(app.Settings(minimum_text_height=20))[0], '28')
        self.assertIn('8', track.observations)
        small = track_with([])
        for i in range(3):
            small.add(Observation('7', .9999, polygon(h=12), i * .2, i))
        number, _, reasons = small.decision(app.Settings(minimum_text_height=20))
        self.assertIsNone(number)
        self.assertIn('liian_pieni_numero', reasons)
        self.assertEqual(small.decision(app.Settings(minimum_text_height=0))[0], '7')

    def test_size_gate_uses_original_polygon_height_and_not_digit_count(self):
        for text in ['7', '28', '819']:
            track = track_with([])
            for i in range(3):
                track.add(Observation(text, .99, polygon(w=12, h=25), i * .2, i))
            self.assertEqual(track.decision(app.Settings(minimum_text_height=20))[0], text)
        with self.assertRaises(ValueError):
            app.Settings(minimum_text_height=float('nan')).validate()

    def test_one_and_two_digit_numbers_can_be_confirmed(self):
        for number in ['7', '28']:
            track = track_with([(number, i * 0.5, i, 0.99) for i in range(3)])
            self.assertEqual(track.decision(app.Settings())[0], number)

    def test_same_frame_does_not_add_confirmation(self):
        track = track_with([('28', 0, 0, 0.9), ('28', 0, 0, 0.99), ('28', 0.5, 15, 0.99)])
        self.assertIsNone(track.decision(app.Settings())[0])
        self.assertEqual(len(track.observations['28']), 2)

    def test_window_and_count_are_adjustable(self):
        track = track_with([('28', 0, 0, 0.99), ('28', 2, 60, 0.99), ('28', 4, 120, 0.99)])
        self.assertIsNone(track.decision(app.Settings(confirmation_window=3))[0])
        self.assertEqual(track.decision(app.Settings(confirmation_window=4))[0], '28')
        self.assertIsNone(track.decision(app.Settings(confirmation_count=4, confirmation_window=4))[0])

    def test_late_conflict_never_prefers_longest_or_majority(self):
        for first, alternative in [('8', '888'), ('888', '8')]:
            track = track_with([(first, i * 0.5, i, 0.99) for i in range(4)])
            self.assertEqual(track.decision(app.Settings())[0], first)
            track.add(Observation(alternative, 0.9999, polygon(), 10, 300))
            number, _, reasons = track.decision(app.Settings(dominance_enabled=False))
            self.assertIsNone(number)
            self.assertIn('ristiriitaiset_numerot', reasons)
            self.assertEqual(set(track.observations), {first, alternative})

    def test_low_confidence_variant_is_preserved(self):
        track = track_with([('7', i * 0.5, i, 0.99) for i in range(3)] + [('77', 1.5, 45, 0.1)])
        self.assertEqual(track.decision(app.Settings())[0], '7')
        self.assertIn('77', track.observations)

    def test_dominance_requires_many_frames_and_quality_not_length(self):
        for winner, other in [('7', '819'), ('819', '7')]:
            track = track_with([(winner, i * .2, i, .98) for i in range(8)] + [(other, 2, 30, .9999)])
            self.assertEqual(track.decision(app.Settings())[0], winner)
            self.assertIn(other, track.observations)
            self.assertIsNone(track.decision(app.Settings(dominance_enabled=False))[0])
            self.assertIsNone(track.decision(app.Settings(dominance_share=.95))[0])
            track.review_reasons.add('epavarma_seurantaliitos')
            self.assertIsNone(track.decision(app.Settings())[0])

    def test_dominance_rejects_persistent_alternative_and_bad_quality(self):
        track = track_with([('7', i * .2, i, .98) for i in range(10)] +
                           [('819', 2.5, 30, .99), ('819', 2.6, 31, .99)])
        self.assertIsNone(track.decision(app.Settings())[0])
        self.assertEqual(track.decision(app.Settings(dominance_max_alternative_frames=2))[0], '7')
        for o in track.observations['7'].values():
            o.association_quality = .5
        self.assertIsNone(track.decision(app.Settings(dominance_max_alternative_frames=2))[0])

    def test_approaching_runner_cannot_shrink_onto_background_runner(self):
        frame = np.full((240, 640, 3), 220, dtype=np.uint8)
        tracker = BibTracker(app.Settings())
        first, _ = tracker.update(frame, 0, 0, [('7', .99, polygon(w=100, h=60))])
        second, _ = tracker.update(frame, .5, 15, [('7', .99, polygon(x=80, w=25, h=13))])
        self.assertNotEqual(first[0][0].id, second[0][0].id)

    def test_identity_does_not_follow_number_text(self):
        rng = np.random.default_rng(2026)
        frame = rng.integers(0, 180, (240, 640, 3), dtype=np.uint8)
        tracker = BibTracker(app.Settings())
        first, _ = tracker.update(frame, 0, 0, [('28', 0.99, polygon(50)), ('81', 0.99, polygon(350))])
        ids = {o.number: t.id for t, o in first}
        second, _ = tracker.update(frame, 0.5, 15, [('81', 0.99, polygon(50)), ('28', 0.99, polygon(350))])
        self.assertEqual({o.number: t.id for t, o in second}, {'81': ids['28'], '28': ids['81']})
        self.assertEqual(len(tracker.active), 2)
        self.assertTrue(all(t.decision(app.Settings())[0] is None for t in tracker.active.values()))

    def test_already_assigned_partner_is_not_an_ambiguity(self):
        frame = np.zeros((240, 320, 3), np.uint8)
        tracker = BibTracker(app.Settings())
        tracker.update(frame, 0, 0, [('28', 0.99, polygon(80, 80, 20, 20)),
                                     ('81', 0.99, polygon(140, 80, 20, 20))])
        _, retired = tracker.update(frame, 0.5, 15, [('28', 0.99, polygon(110, 80, 20, 20)),
                                       ('81', 0.99, polygon(142, 80, 20, 20))])
        self.assertFalse(retired)
        self.assertFalse(tracker.association_events)
        self.assertTrue(all(not t.review_reasons for t in tracker.active.values()))

    def test_real_ambiguity_cuts_evidence_and_quarantines_boundary_frame(self):
        frame = np.zeros((240, 320, 3), np.uint8)
        tracker = BibTracker(app.Settings())
        tracker.update(frame, 0, 0, [('28', .99, polygon(80, 80, 20, 20)),
                                    ('81', .99, polygon(140, 80, 20, 20))])
        _, retired = tracker.update(frame, .5, 15, [('28', .99, polygon(110, 80, 20, 20))])
        self.assertEqual(len(retired), 2)
        self.assertTrue(tracker.association_events)
        children = [t for t in tracker.active.values() if t.possible_parent_ids]
        self.assertTrue(children)
        self.assertTrue(all(all(o.frame == 15 and o.association_quality == 0
            for frames in t.observations.values() for o in frames.values()) for t in children))
        self.assertTrue(all(t.decision(app.Settings())[0] is None for t in children))

    def test_post_boundary_segment_can_confirm_without_parent_votes(self):
        track = track_with([])
        track.possible_parent_ids = {8, 9}
        track.add(Observation('7', .99, polygon(), 0, 0, association_quality=0))
        track.add(Observation('81', .99, polygon(), .5, 15))
        track.add(Observation('81', .99, polygon(), 1, 30))
        self.assertIsNone(track.decision(app.Settings(confirmation_count=3))[0])
        track.add(Observation('81', .99, polygon(), 1.5, 45))
        number, confirmed, _ = track.decision(app.Settings(confirmation_count=3))
        self.assertEqual(number, '81')
        self.assertEqual([o.frame for o in confirmed], [15,30,45])
        self.assertIn('7', track.observations)
        self.assertEqual(len(track.decision_details['hylatyt_ruudut']), 1)

    def test_parent_segment_cannot_fill_short_child_confirmation(self):
        parent = track_with([('7', i*.5, i, .99) for i in range(2)])
        child = track_with([('7', 1.5, 45, .99)])
        child.possible_parent_ids = {parent.id}
        self.assertIsNone(parent.decision(app.Settings())[0])
        self.assertIsNone(child.decision(app.Settings())[0])

    def test_boundary_descendant_does_not_duplicate_after_cooldown(self):
        from seurannan_tallennus import TrackRecorder
        OUTPUT.mkdir(parents=True, exist_ok=True)
        parent = track_with([('7', i*.5, i, .99) for i in range(3)])
        child = track_with([('7', 20+i*.5, 600+i, .99) for i in range(3)])
        child.id = 2
        child.last_visual = 22
        child.possible_parent_ids = {parent.id}
        for track in [parent, child]:
            track.evidence['7'] = {'path': 'test.png', 'score': .99, 'time': 0, 'frame': 0}
        with tempfile.TemporaryDirectory(dir=OUTPUT) as folder:
            recorder = TrackRecorder(Path(folder), app.Settings(duplicate_seconds=10))
            try:
                recorder.finalize(parent)
                recorder.finalize(child)
                self.assertEqual(recorder.saved, 1)
                self.assertEqual(recorder.suppressed, 1)
                self.assertTrue(child.decision_details['estavat_ehdot'])
            finally:
                recorder.close()

    def test_visual_continuity_survives_missing_ocr(self):
        frame = np.random.default_rng(19).integers(0, 180, (180, 320, 3), dtype=np.uint8)
        tracker = BibTracker(app.Settings(track_gap=0.5))
        tracker.update(frame, 0, 0, [('7', 0.99, polygon())])
        for i in range(1, 101):
            self.assertFalse(tracker.advance(frame, i / 10))
        added, retired = tracker.update(frame, 10, 100, [('77', 0.99, polygon())])
        self.assertFalse(retired)
        self.assertEqual(added[0][0].id, 1)
        self.assertEqual(set(added[0][0].observations), {'7', '77'})

    def test_clock_mask_and_overlap_rejection(self):
        path = write_video('poissulku.mp4', np.zeros((120, 200, 3), np.uint8))
        class Engine:
            device = 'test'
            def recognize(self, frame):
                assert np.all(frame[:50, :80] == 255)
                assert np.all(frame[70:, 100:] == 0)
                # Myös maskiin silti osuva OCR-laatikko hylätään geometrian perusteella.
                return [('9', 0.999, polygon(20, 20, 20, 20)), ('12', 0.99, polygon(110, 70, 30, 20))]
        out, summary = app.process_video(path, app.Settings(interval=0.5, exclusion=(0, 0, 80, 50)),
            Engine(), threading.Event(), lambda *a: None, lambda *a: None, OUTPUT)
        self.assertEqual(summary['saved_detections'], 1)
        self.assertEqual(summary['excluded_detections'], 4)
        with (out / 'havainnot.csv').open(encoding='utf-8-sig') as file:
            self.assertEqual([r['numero'] for r in csv.DictReader(file, delimiter=';')], ['12'])

    def test_same_visible_track_is_written_once_after_ten_seconds(self):
        frame = np.random.default_rng(72).integers(0, 180, (120, 240, 3), dtype=np.uint8)
        path = write_video('jatkuva_16s.mp4', frame, frames=80, fps=5)
        class Engine:
            device = 'test'
            def recognize(self, frame):
                return [('7', 0.99, polygon(70, 40, 40, 30))]
        out, summary = app.process_video(path, app.Settings(interval=1, duplicate_seconds=10),
            Engine(), threading.Event(), lambda *a: None, lambda *a: None, OUTPUT)
        self.assertEqual(summary['processed_frames'], 16)
        self.assertEqual(summary['saved_detections'], 1)
        self.assertEqual(summary['completed_tracks'], 1)
        self.assertFalse((out / 'debug').exists())

    def test_interrupted_track_is_not_accepted(self):
        track = track_with([('7', i / 2, i, 0.99) for i in range(3)])
        self.assertEqual(track.decision(app.Settings())[0], '7')
        self.assertIn('keskeytetty_seuranta', track.decision(app.Settings(), interrupted=True)[2])


if __name__ == '__main__':
    unittest.main()
