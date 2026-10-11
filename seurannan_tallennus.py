"""Hyväksytyt seurannat ja tarkistettavat vaihtoehdot eri CSV-tiedostoihin."""
import csv
import json
import os
from contextlib import ExitStack
import cv2
import numpy as np
from havaintoseuranta import context_box, text_height
from tallennusrajat import RotatingText, StorageBudget


def save_png(path, image):
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise OSError(f'Kuvan tallennus epäonnistui: {path}')
    path.write_bytes(encoded.tobytes())


ACCEPTED_FIELDS = ['numero', 'videon_aika_s', 'ocr_luottamus', 'ruutu',
    'tarkistuskuva', 'seuranta_id', 'vahvistuksia', 'vahvistettu_aika_s', 'kuvan_aika_s',
    'ensi_ocr_aika_s', 'kirjaus_videon_aika_s']


class TrackRecorder:
    def __init__(self, output, settings, on_accepted=None, report=lambda text: None, on_storage=None):
        self.on_accepted = on_accepted
        self.report = report
        self.storage = StorageBudget(output, report, on_storage)
        self.pending_images = {}
        self.output, self.settings = output, settings
        self.stack = ExitStack()
        self.saved = self.uncertain = self.suppressed = self.completed = 0
        self.last_saved = {}
        self.accepted_by_track = {}
        self.files = []
        self.accepted = self._csv('havainnot.csv', ACCEPTED_FIELDS)
        self.review = self._csv('epavarmat.csv', ['numero', 'videon_aika_s', 'ocr_luottamus', 'ruutu',
            'tarkistuskuva', 'seuranta_id', 'havaintoja', 'syy', 'vaihtoehdot', 'kuvan_aika_s'])
        self.raw = self._file('raakahavainnot.jsonl')
        self.tracks = self._file('seurannat.jsonl')
        self.samples = self._file('naytteet.jsonl')
        self.associations = self._file('liitokset.jsonl')

    def _file(self, name):
        if name.endswith('.jsonl'):
            file = RotatingText(self.output / name, self.report)
            self.stack.callback(file.close)
        else:
            file = self.stack.enter_context((self.output / name).open('w', newline='', encoding='utf-8-sig' if name.endswith('.csv') else 'utf-8'))
        self.files.append(file)
        return file

    def _csv(self, name, header):
        writer = csv.writer(self._file(name), delimiter=';')
        writer.writerow(header)
        return writer

    def observation(self, track, observation, frame):
        self.raw.write(json.dumps(observation.serializable(), ensure_ascii=False) + '\n')
        previous = track.evidence.get(observation.number)
        if previous is not None and previous['score'] >= observation.confidence:
            return
        # Yksi edustava paras kuva/vaihtoehto/seuranta. Tiedoston sisältö ja kuvan aika raportoidaan yhdessä.
        name = f'seuranta_{track.id:05d}_{observation.number}.jpg'
        annotated = frame.copy()
        cv2.polylines(annotated, [np.asarray(observation.polygon, np.int32)], True, (0, 160, 255), 3)
        cv2.putText(annotated, f'T{track.id}: {observation.number} {observation.confidence:.3f}',
                    (20, max(30, frame.shape[0] - 30)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 160, 255), 2)
        if self.settings.exclusion:
            a, b, c, d = self.settings.exclusion
            cv2.rectangle(annotated, (a, b), (c, d), (0, 0, 255), 2)
        track.evidence[observation.number] = {'path': '', 'score': observation.confidence,
                                            'time': observation.time, 'frame': observation.frame}
        self.pending_images.get(track.id, {}).pop(observation.number, None)
        # Muistissa paras kuva/vaihtoehto; levylle vasta tapahtuman päätöshetkellä.
        if not self.storage.images_stopped:
            try:
                ok, encoded = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
            except cv2.error as exc:
                self.report(f'Tarkistuskuvan koodausvirhe: {exc}')
                return
            if ok:
                self.pending_images.setdefault(track.id, {})[observation.number] = (name, encoded.tobytes())
            else:
                self.report('Tarkistuskuvan JPEG-koodaus epäonnistui.')

    def debug_image(self, path, image):
        if not self.settings.debug_frames or self.storage.debug_stopped or self.storage.images_stopped:
            return False
        try:
            ok, encoded = cv2.imencode('.png', image)
        except cv2.error as exc:
            self.report(f'Debug-kuvan koodausvirhe: {exc}')
            return False
        if not ok:
            self.report('Debug-kuvan koodaus epäonnistui.')
            return False
        return self.storage.write_image(path, encoded.tobytes(), debug=True)

    def _save_event_images(self, track, number):
        pending = self.pending_images.pop(track.id, {})
        review = sorted((n for n in track.evidence if n != number),
                        key=lambda n: track.evidence[n]['score'], reverse=True)[:3 if number is None else 2]
        selected = ([number] if number is not None else []) + review
        for variant in selected:
            if variant in pending:
                name, data = pending[variant]
                if self.storage.write_image(self.output / 'kuvat' / name, data):
                    track.evidence[variant]['path'] = 'kuvat/' + name

    def finalize(self, track, interrupted=False):
        number, confirmation, reasons = track.decision(self.settings, interrupted)
        def block(reason, measured, operator, limit):
            check = {'ehto': reason, 'mitattu': measured, 'vertailu': operator,
                     'raja': limit, 'tayttyy': False}
            track.decision_details.setdefault('ehdot', []).append(check)
            track.decision_details.setdefault('estavat_ehdot', []).append(check)
            track.decision_details['syyt'] = [reason]
        if number is not None:
            if any(self.accepted_by_track.get(parent) == number for parent in track.possible_parent_ids):
                reasons = ['aiemman_todistejakson_saman_numeron_kirjaus']
                block(reasons[0], [parent for parent in sorted(track.possible_parent_ids)
                      if self.accepted_by_track.get(parent) == number], 'tyhja', [])
                number = None
                self.suppressed += 1
        if number is not None:
            # Lisäesto erillisille seurannoille; ei yhdistä niiden identiteettejä.
            previous = self.last_saved.get(number)
            if previous is not None and track.last_visual - previous < self.settings.duplicate_seconds:
                reasons = ['uuden_seurannan_saman_numeron_aikaesto']
                block(reasons[0], track.last_visual - previous, '>=', self.settings.duplicate_seconds)
                number = None
                self.suppressed += 1
            else:
                self.last_saved[number] = track.last_visual
        alternatives = {n: len(frames) for n, frames in track.observations.items()}
        self._save_event_images(track, number)
        if number is not None:
            evidence = track.evidence[number]
            first, last = confirmation[0], confirmation[-1]
            score = sum(o.confidence for o in confirmation) / len(confirmation)
            accepted_row = [number, f'{first.time:.6f}', f'{score:.6f}', first.frame, evidence['path'],
                                    track.id, len(confirmation), f'{last.time:.6f}', f"{evidence['time']:.6f}",
                                    f"{min(o.time for o in track.observations[number].values()):.6f}",
                                    f'{track.last_visual:.6f}']
            self.accepted.writerow(accepted_row)
            self.saved += 1
            self.accepted_by_track[track.id] = number
        for variant, frames in track.observations.items():
            if variant == number:
                continue
            evidence = track.evidence[variant]
            first = min(frames.values(), key=lambda o: o.time)
            variant_reasons = reasons or (['liian_pieni_numero'] if all(
                text_height(o.polygon) < self.settings.minimum_text_height for o in frames.values())
                else ['heikompi_vaihtoehto'] if number is not None and any(
                    o.confidence >= self.settings.confidence for o in frames.values()) else ['matala_ocr_luottamus'])
            self.review.writerow([variant, f'{first.time:.6f}', f"{evidence['score']:.6f}", evidence['frame'],
                                  evidence['path'], track.id, len(frames), ','.join(variant_reasons),
                                  json.dumps(alternatives, ensure_ascii=False), f"{evidence['time']:.6f}"])
            self.uncertain += 1
        self.tracks.write(json.dumps({'seuranta_id': track.id, 'hyvaksytty_numero': number,
            'syyt': reasons, 'vaihtoehdot': alternatives, 'loppuaika_s': track.last_visual,
            'havainnot': [o.serializable() for frames in track.observations.values() for o in frames.values()],
            'kuvat': track.evidence, 'paatoksen_perusteet': track.decision_details,
            'mahdolliset_edeltajat': sorted(track.possible_parent_ids),
            'todistejakson_rajat': track.boundary_events}, ensure_ascii=False) + '\n')
        self.completed += 1
        self.flush()
        if number is not None and self.on_accepted is not None:
            self.on_accepted(self.accepted_event(dict(zip(ACCEPTED_FIELDS, accepted_row))))

    def accepted_event(self, row):
        return row

    def flush(self):
        for file in self.files:
            try:
                file.flush()
                if not isinstance(file, RotatingText):
                    os.fsync(file.fileno())
            except OSError as exc:
                self.report(f'Havainto-CSV:n kirjoitusvirhe: {exc}')
                raise
        self.storage.status()

    def close(self):
        try:
            self.stack.close()
        finally:
            self.storage.status(force=True)
