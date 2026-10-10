"""Hyväksytyt seurannat ja tarkistettavat vaihtoehdot eri CSV-tiedostoihin."""
import csv
import json
import os
from contextlib import ExitStack
import cv2
import numpy as np
from havaintoseuranta import context_box, text_height


def save_png(path, image):
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise OSError(f'Kuvan tallennus epäonnistui: {path}')
    path.write_bytes(encoded.tobytes())


class TrackRecorder:
    def __init__(self, output, settings):
        self.output, self.settings = output, settings
        self.stack = ExitStack()
        self.saved = self.uncertain = self.suppressed = self.completed = 0
        self.last_saved = {}
        self.accepted_by_track = {}
        self.files = []
        self.accepted = self._csv('havainnot.csv', ['numero', 'videon_aika_s', 'ocr_luottamus', 'ruutu',
            'tarkistuskuva', 'seuranta_id', 'vahvistuksia', 'vahvistettu_aika_s', 'kuvan_aika_s',
            'ensi_ocr_aika_s', 'kirjaus_videon_aika_s'])
        self.review = self._csv('epavarmat.csv', ['numero', 'videon_aika_s', 'ocr_luottamus', 'ruutu',
            'tarkistuskuva', 'seuranta_id', 'havaintoja', 'syy', 'vaihtoehdot', 'kuvan_aika_s'])
        self.raw = self._file('raakahavainnot.jsonl')
        self.tracks = self._file('seurannat.jsonl')
        self.samples = self._file('naytteet.jsonl')
        self.associations = self._file('liitokset.jsonl')

    def _file(self, name):
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
        name = f'seuranta_{track.id:05d}_{observation.number}.png'
        annotated = frame.copy()
        cv2.polylines(annotated, [np.asarray(observation.polygon, np.int32)], True, (0, 160, 255), 3)
        cv2.putText(annotated, f'T{track.id}: {observation.number} {observation.confidence:.3f}',
                    (20, max(30, frame.shape[0] - 30)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 160, 255), 2)
        if self.settings.exclusion:
            a, b, c, d = self.settings.exclusion
            cv2.rectangle(annotated, (a, b), (c, d), (0, 0, 255), 2)
        save_png(self.output / 'kuvat' / name, annotated)
        from havaintoseuranta import box_of
        x1, y1, x2, y2 = context_box(box_of(observation.polygon), frame.shape)
        save_png(self.output / 'kuvat' / ('alue_' + name), frame[y1:y2, x1:x2])
        track.evidence[observation.number] = {'path': 'kuvat/' + name, 'score': observation.confidence,
                                            'time': observation.time, 'frame': observation.frame}

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
        if number is not None:
            evidence = track.evidence[number]
            first, last = confirmation[0], confirmation[-1]
            score = sum(o.confidence for o in confirmation) / len(confirmation)
            self.accepted.writerow([number, f'{first.time:.6f}', f'{score:.6f}', first.frame, evidence['path'],
                                    track.id, len(confirmation), f'{last.time:.6f}', f"{evidence['time']:.6f}",
                                    f"{min(o.time for o in track.observations[number].values()):.6f}",
                                    f'{track.last_visual:.6f}'])
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

    def flush(self):
        for file in self.files:
            file.flush()
            os.fsync(file.fileno())

    def close(self):
        self.stack.close()
