"""Toistettava video.mp4-parametrivertailu; totuutta käytetään vain arviointiin."""
import argparse
import copy
import csv
import hashlib
import itertools
import json
import pickle
import shutil
import threading
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import cv2
import numerontunnistin_paikallinen as app
from seurannan_tallennus import TrackRecorder

ROOT = app.BASE / 'testiaineisto' / 'parametrivertailu'


def seconds(value):
    minutes, seconds_part = value.strip().split('.')
    if not 0 <= int(seconds_part) < 60:
        raise ValueError(value)
    return int(minutes) * 60 + int(seconds_part)


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def evaluate(tracks, settings, truth):
    accepted, by_track, last_saved, seen = [], {}, {}, set()
    for track in tracks:
        seen.update(track.observations)
        number, confirmation, _ = track.decision(settings)
        if number is None:
            continue
        if any(by_track.get(parent) == number for parent in track.possible_parent_ids):
            continue
        if number in last_saved and track.last_visual-last_saved[number] < settings.duplicate_seconds:
            continue
        by_track[track.id] = number
        last_saved[number] = track.last_visual
        times = [o.time for o in confirmation]
        # CSV rajaa näkyvyyden sekunnin tarkkuudella. Raportoidaan tarkka
        # osuma ja erikseen yhden sekunnin toleranssi, ei piiloteta eroa.
        exact = number in truth and any(truth[number][0] <= t <= truth[number][1] for t in times)
        tolerant = number in truth and any(truth[number][0]-1 <= t <= truth[number][1]+1 for t in times)
        accepted.append(dict(number=number, track=track.id, times=times, exact=exact, tolerant=tolerant))
    numbers = [a['number'] for a in accepted]
    good = {a['number'] for a in accepted if a['tolerant']}
    return dict(accepted=accepted, correct=sorted(good),
                review=sorted((set(truth) & seen) - set(numbers)),
                missing=sorted(set(truth)-seen),
                wrong=[a for a in accepted if a['number'] not in truth],
                outside_time=[a for a in accepted if a['number'] in truth and not a['tolerant']],
                duplicates={n:numbers.count(n)-1 for n in set(numbers) if numbers.count(n)>1},
                exact_count=len({a['number'] for a in accepted if a['exact']}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--first-experiment', action='store_true', help='Aja ja tallenna vain ensimmäinen näyteväli.')
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    truth = {}
    with (app.BASE / 'numerot.csv').open(encoding='utf-8-sig', newline='') as f:
        for number, start, end in csv.reader(f, delimiter=';'):
            truth[number] = [seconds(start), seconds(end)]
    assert seconds('01.08') == 68 and seconds('00.5') == 5
    dump(ROOT / 'vertailutotuus.json', truth)
    for name in ['parametrivertailu.py', 'numerontunnistin_paikallinen.py', 'havaintoseuranta.py', 'seurannan_tallennus.py', 'numerot.csv']:
        shutil.copyfile(app.BASE / name, ROOT / name)
    dump(ROOT / 'lahteet.json', {name:hashlib.sha256((app.BASE/name).read_bytes()).hexdigest()
                              for name in ['video.mp4', 'numerot.csv', 'numerontunnistin_paikallinen.py', 'havaintoseuranta.py', 'seurannan_tallennus.py']})
    cache_path = ROOT / 'ocr.jsonl'
    cache = {r['sha256']:r['detections'] for r in map(json.loads, cache_path.read_text().splitlines())} if cache_path.exists() else {}
    live = None
    class Engine:
        device = 'gpu:0'
        def recognize(self, frame):
            nonlocal live
            digest = hashlib.sha256(frame.tobytes()).hexdigest()
            if digest not in cache:
                if live is None:
                    live = app.PaddleEngine('auto', lambda s: print(s, flush=True))
                    self.device = live.device
                found = live.recognize(frame)
                cache[digest] = [[n,float(s),p.tolist()] for n,s,p in found]
                with cache_path.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(dict(sha256=digest, detections=cache[digest]))+'\n')
            return [(n,s,np.array(p,np.int32)) for n,s,p in cache[digest]]
    base = app.Settings(interval=.25, roi=None, exclusion=(0,0,270,112), confirmation_count=2,
                        confirmation_window=4, dominance_share=.65)
    dump(ROOT / 'koesuunnitelma.json', dict(base_settings=asdict(base),
         intervals=[.5,.25,.1], heights=[12,20,28], confidence=[.5,.7,.85],
         confirmation_count=[2,3,4], confirmation_window=[2,4], dominance_share=[.65,.8],
         dominance_ratio=[2,3], combinations=648))
    results, track_sets = [], {}
    for interval in [.5, .25, .1]:
        folder = ROOT / f'naytevali_{interval}'
        folder.mkdir(exist_ok=True)
        state = folder / 'seurannat.pkl'
        if state.exists():
            with state.open('rb') as f:
                tracks, output = pickle.load(f)
        else:
            tracks = []
            class Capture(TrackRecorder):
                def finalize(self, track, interrupted=False):
                    tracks.append(copy.deepcopy(track))
                    super().finalize(track, interrupted)
            app.TrackRecorder = Capture
            cv2.setRNGSeed(1234)
            output, summary = app.process_video(app.BASE/'video.mp4', replace(base, interval=interval), Engine(),
                                                threading.Event(), lambda s: print(s, flush=True), lambda *a: None, folder)
            dump(folder/'ajo_tulos.json', dict(output=str(output), summary=summary))
            with state.open('wb') as f:
                pickle.dump((tracks, output), f)
        track_sets[interval] = (tracks, output)
        # Nämä parametrit vaikuttavat päätökseen, eivät seurantajakoon.
        for height, confidence, count, window, share, ratio in itertools.product(
                [12.,20.,28.], [.5,.7,.85], [2,3,4], [2.,4.], [.65,.8], [2.,3.]):
            settings = replace(base, interval=interval, minimum_text_height=height, confidence=confidence,
                               confirmation_count=count, confirmation_window=window,
                               dominance_share=share, dominance_ratio=ratio)
            result = evaluate(tracks, settings, truth)
            result['settings'] = asdict(settings)
            results.append(result)
        dump(ROOT/'valitulokset.json', results)
        dump(ROOT/'tila.json', dict(status='running', completed_experiments=len(track_sets),
                                   evaluated_settings=len(results), single_image_ocr_verified=True))
        print(f'VALMIS näyteväli {interval}: {len(results)} asetusta', flush=True)
        if args.first_experiment:
            return
    def rank(r):
        return (len(r['wrong'])+len(r['outside_time'])+sum(r['duplicates'].values()),
                -len(r['correct']), -r['exact_count'], -r['settings']['confirmation_count'],
                -r['settings']['confidence'], -r['settings']['minimum_text_height'],
                -r['settings']['interval'], -r['settings']['dominance_ratio'], -r['settings']['dominance_share'])
    results.sort(key=rank)
    best = results[0]
    dump(ROOT/'parhaat_asetukset.json', best['settings'])
    dump(ROOT/'paras_tulos.json', best)
    best_folder = ROOT/'paras_ajo'
    best_folder.mkdir(exist_ok=True)
    tracks, output = track_sets[best['settings']['interval']]
    shutil.copytree(output/'kuvat', best_folder/'kuvat', dirs_exist_ok=True)
    recorder = TrackRecorder(best_folder, app.Settings(**best['settings']))
    try:
        for track in tracks:
            recorder.finalize(track)
    finally:
        recorder.close()
    dump(best_folder/'ajo.json', dict(video=str(app.BASE/'video.mp4'), settings=best['settings'],
                                    source_run=str(output), mode='same_tracks_recomputed_acceptance'))
    lines = ['# Parametrivertailun loppuraportti', '',
             f'Vertailussa {len(results)} asetusta, video.mp4 ja 10 CSV-numeroa.',
             'Aikamuoto: minuutit.sekunnit; 01.08 = 68 s ja 00.5 = 5 s.',
             'Koko kuva; poissulku (0, 0, 270, 112) peittää yläreunan aikaleiman.',
             'OCR-välimuisti on syötekuvan SHA256-tunnisteella. Jokainen näyteväli ajettiin omalla liikkeenseurannalla.',
             'OCR/kokoraja, vahvistukset ja dominanssi arvioitiin samoista seurantajaksoista sovelluksen päätösfunktiolla.',
             'Seurannan katkon sieto 2 s, aikaesto 10 s ja liitoksen turvarajat säilyivät.', '',
             f"Paras: {len(best['correct'])}/10 oikeaa; tarkka aikaosuma {best['exact_count']}/10.",
             f"Väärät: {len(best['wrong'])}; aikavälin ulkopuolella: {len(best['outside_time'])}; kaksoiskirjaukset: {best['duplicates']}.",
             f"Tarkistettavat: {best['review']}; kokonaan puuttuvat: {best['missing']}.",
             'Aikaosuma tarkoittaa vahvistusruutujen osumista näkyvyysaikaväliin; myös ±1 s tulos raportoidaan CSV:n sekuntitarkkuuden vuoksi.', '',
             '```json', json.dumps(best['settings'], ensure_ascii=False, indent=2), '```', '',
             '| Näyteväli | Oikeat | Tarkka aika | Väärät | Ajan ulkopuolella | Kaksoiskirjaukset |',
             '|---|---:|---:|---:|---:|---:|']
    for interval in [.5,.25,.1]:
        r = min((r for r in results if r['settings']['interval']==interval), key=rank)
        lines.append(f"| {interval} | {len(r['correct'])} | {r['exact_count']} | {len(r['wrong'])} | {len(r['outside_time'])} | {sum(r['duplicates'].values())} |")
    lines += ['', 'Valinta minimoi ensin väärät hyväksynnät, aikaikkunan ulkopuoliset hyväksynnät ja kaksoiskirjaukset, sitten maksimoi oikeat ja tarkat aikaosumat. Tasatilanteessa suositaan vahvempaa ruututukea ja tiukempia OCR/kokorajoja, sitten harvempaa näytteenottoa.',
              'Asetukset on sovitettu tähän yhteen videoon. Yleistymistä ei ole mitattu erillisellä videolla; aikaosumat eivät mittaa maalilinjan ylityksiä.',
              'Välitulokset: valitulokset.json. OCR: ocr.jsonl. Paras ajo kuvineen: paras_ajo/. Parhaat asetukset: parhaat_asetukset.json.',
              'Uusinta: .\\.venv\\Scripts\\python.exe parametrivertailu.py. Tallennetut seurantajaksot ja OCR mahdollistavat jatkamisen.']
    (ROOT/'LOPPURAPORTTI.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    dump(ROOT/'tila.json', dict(status='complete', completed_experiments=len(track_sets),
                               evaluated_settings=len(results), best_settings=best['settings'],
                               single_image_ocr_verified=True))
    print(json.dumps(best, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
