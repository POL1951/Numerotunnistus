"""Rajattu livevastaanotto ja paikallisen tunnistuslogiikan liveajo."""
import importlib.util
import hashlib
import json
import os
import struct
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, unquote

import numpy as np
from havaintoseuranta import BibTracker, box_of, intersection
from seurannan_tallennus import TrackRecorder, save_png
from tallennusrajat import RotatingText

BASE = Path(__file__).resolve().parent
BRIDGE = BASE / 'live_vastaanotin.py'


def validate_url(url):
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in ('rtsp', 'rtsps', 'http', 'https') or not parts.hostname:
            raise ValueError()
        parts.port
    except ValueError:
        raise ValueError('Anna täydellinen RTSP/HTTP-videovirran URL, esimerkiksi rtsp://kamera/virta. Pelkkä IP-osoite ei riitä.') from None
    return url


def safe_url(url):
    # Myös kyselyparametrit voivat sisältää salasanan tai pääsyavaimen.
    try:
        parts = urlsplit(url)
        host = parts.netloc.rsplit('@', 1)[-1]
        return urlunsplit((parts.scheme, host, parts.path, '', ''))
    except ValueError:
        return '[videovirran osoite]'


def safe_traceback(text, url):
    if not url:
        return text
    text = text.replace(url, safe_url(url))
    try:
        password = urlsplit(url).password
        if password:
            text = text.replace(password, '[salasana poistettu]').replace(unquote(password), '[salasana poistettu]')
    except ValueError:
        pass
    return text


def ndi_python():
    if importlib.util.find_spec('NDIlib'):
        return sys.executable
    candidate = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'Python/pythoncore-3.14-64/python.exe'
    package = candidate.parent / 'Lib/site-packages/NDIlib'
    if candidate.is_file() and package.is_dir():
        return str(candidate)
    raise RuntimeError('NDI-vastaanottokirjasto NDIlib (ndi-python) puuttuu. Asennettua NDI-Python-ympäristöä ei löytynyt; MP4 ja verkkovideo toimivat erikseen.')


def spawn(config):
    executable = ndi_python() if config['source_type'] == 'NDI' else sys.executable
    process = subprocess.Popen([executable, '-u', str(BRIDGE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    process.stdin.write((json.dumps(config) + '\n').encode('utf-8'))
    process.stdin.flush()
    process.stdin.close()
    process.stdin = None
    return process


def read_exact(stream, count):
    chunks = bytearray()
    while len(chunks) < count:
        data = stream.read(count-len(chunks))
        if not data:
            raise EOFError('Vastaanottoprosessi päättyi')
        chunks.extend(data)
    return bytes(chunks)


def read_packet(stream):
    length = struct.unpack('<I', read_exact(stream, 4))[0]
    if length > 65536:
        raise RuntimeError('Virheellinen vastaanottopaketin otsake')
    header = json.loads(read_exact(stream, length))
    size = header['bytes']
    if not 0 <= size <= 128 * 1024 * 1024:
        raise RuntimeError('Virheellinen kuvakoko')
    return header, read_exact(stream, size)


def terminate(process):
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    if process.stdout:
        process.stdout.close()


def discover_ndi():
    process = spawn({'source_type': 'NDI', 'discover': True})
    try:
        data, _ = process.communicate(timeout=8)
        import io
        header, _ = read_packet(io.BytesIO(data))
        if 'error' in header:
            raise RuntimeError(header['error'])
        return header['sources']
    finally:
        terminate(process)


@dataclass(frozen=True)
class LiveFrame:
    image: np.ndarray
    monotonic: float
    wall: float
    sequence: int
    generation: int


class LiveReceiver:
    """Yksi tuorein kuva; vastaanotto toimii aina OCR:stä riippumatta."""
    def __init__(self, config, report=lambda s: None):
        self.config, self.report = config, report
        self.started = time.monotonic()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        self.generation = self.sequence = 0
        self.state = 'Yhdistetään'
        self.process = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return self.latest, self.generation, self.state

    def _state(self, state):
        with self.lock:
            self.state = state
        self.report(state)

    def _run(self):
        retry = 1
        while not self.stop.is_set():
            self._state('Yhdistetään' if retry == 1 else 'Yhdistetään uudelleen')
            process = None
            try:
                process = spawn(self.config)
                self.process = process
                if self.stop.is_set():
                    break
                last_frame_time = None
                while not self.stop.is_set():
                    header, data = read_packet(process.stdout)
                    received_monotonic = time.monotonic()
                    if 'error' in header:
                        raise RuntimeError(header['error'])
                    shape = header['shape']
                    if len(shape) != 3 or shape[2] != 3:
                        raise RuntimeError('Videon värimuoto ei ole BGR')
                    image = np.frombuffer(data, dtype=np.uint8).reshape(shape)
                    with self.lock:
                        # NDI voi palauttaa saman vastaanottimen yhteyden itse.
                        # Pitkä kuvakatko muodostaa silti uuden todistejakson.
                        if last_frame_time is not None and header['monotonic']-last_frame_time > 2:
                            self.generation += 1
                        last_frame_time = header['monotonic']
                        self.sequence += 1
                        # Python 3.14:n ja 3.11:n absoluuttisia kellolukemia
                        # ei verrata. Ikä alkaa valmiin kuvan vastaanotosta
                        # tässä samassa prosessissa, joka laskee sen iän.
                        self.latest = LiveFrame(image, received_monotonic, header['wall'], self.sequence, self.generation)
                        connected = self.state != 'Yhdistetty'
                        self.state = 'Yhdistetty'
                    if connected:
                        self.report('Yhdistetty')
                    retry = 1
            except Exception as exc:
                if not self.stop.is_set():
                    # Verkkolähteen poikkeustekstiä ei koskaan lokiteta.
                    self._state(str(exc) if self.config['source_type'] == 'NDI' else 'Yhteys katkesi; uusi yritys odottaa')
            finally:
                terminate(process)
                self.process = None
                with self.lock:
                    self.latest = None
                    self.generation += 1
            if self.stop.wait(retry):
                break
            retry = min(retry * 2, 8)
        self._state('Katkaistu')

    def disconnect(self):
        self.stop.set()
        process = self.process
        if process and process.poll() is None:
            process.terminate()  # purkaa myös mahdollisen blokkaavan pipe-luvun


class ClockCSV:
    def __init__(self, writer, clocks):
        self.writer, self.clocks = writer, clocks

    def writerow(self, row):
        wall = self.clocks.get(row[1])
        self.writer.writerow(row + [datetime.fromtimestamp(wall).astimezone().isoformat(timespec='milliseconds') if wall else '', row[1]])


class LiveRecorder(TrackRecorder):
    def __init__(self, output, settings, report=lambda text: None, on_storage=None):
        self.clocks = {}
        super().__init__(output, settings, report=report, on_storage=on_storage)

    def accepted_event(self, row):
        # Same received frame timestamp as the existing automatic CSV row.
        return dict(row, vastaanotto_aikaleima=self.clocks[row['videon_aika_s']])

    def _csv(self, name, header):
        writer = super()._csv(name, header + ['vastaanotto_kellonaika', 'istunnon_aika_s'])
        return ClockCSV(writer, self.clocks)


class LiveDiagnostics:
    """OCR-vaihe näkyy myös silloin, kun kutsu odottaa tai ei löydä numeroita."""
    def __init__(self):
        self.lock = threading.Lock()
        self.path = None
        self.writer = None
        self.report = lambda text: None
        self.data = dict(phase='ei käynnissä', submitted=0, completed=0, processed=0,
                         discarded=0, first_start=None, first_end=None, first_duration=None,
                         first_failed=False, active_start=None, error=None)

    def attach(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.writer:
            self.writer.close()
        self.writer = RotatingText(self.path, lambda text: self.report(text))
        self.update(phase='työntekijäsäie käynnistyi')

    def update(self, **changes):
        with self.lock:
            if all(self.data.get(k) == v for k,v in changes.items()):
                return
            self.data.update(changes)
            if self.path:
                self.writer.write(json.dumps(dict(time=datetime.now().astimezone().isoformat(), **self.data),
                                             ensure_ascii=False)+'\n')
                self.writer.flush()
                self.writer.close()  # Vastaanottaja ja GUI voivat jäädä eloon istunnon jälkeen.

    def snapshot(self):
        with self.lock:
            data = dict(self.data)
        data['active_duration'] = (time.monotonic()-data['active_start']) if data['active_start'] is not None else None
        return data


def retire_live_without_ocr(tracker, timestamp):
    """Taustan optinen virtaus ei pidä live-lappua elossa ilman OCR-todistetta."""
    retired = []
    for track in list(tracker.active.values()):
        if timestamp - track.last_detection > tracker.settings.track_gap:
            retired.append(tracker.active.pop(track.id))
    return retired


def process_live(receiver, settings, engine, stop, report, preview, output_root=None, diagnostics=None, on_accepted=None, on_storage=None):
    diagnostics = diagnostics or LiveDiagnostics()
    diagnostics.report = report
    diagnostics.update(phase='live-ajon tallennuksen alustus')
    settings.validate()
    output = (output_root or BASE/'paikalliset_tulokset') / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output.mkdir(parents=True)
    (output/'kuvat').mkdir()
    if settings.debug_frames:
        (output/'debug').mkdir()
    metadata = asdict(settings)
    metadata['stream_url'] = safe_url(metadata.get('stream_url', ''))
    (output/'ajo.json').write_text(json.dumps(dict(settings=metadata, source_type=settings.source_type,
        device=engine.device, timestamp_source='local reception wall clock and monotonic session time',
        age_clock=time.get_clock_info('monotonic').implementation,
        time_meaning='OCR-havainnon vastaanottoaika, ei virallinen maaliintuloaika'), ensure_ascii=False, indent=2), encoding='utf-8')
    recorder = LiveRecorder(output, settings, report=report, on_storage=on_storage)
    recorder.on_accepted = on_accepted
    recorder.storage.status(force=True)
    audit = recorder._file('ocr_raakatekstit.jsonl')
    chain = recorder._file('ocr_seurantaketju.jsonl')
    sample_dir = output/'ocr_syotteet'
    if settings.debug_frames:
        sample_dir.mkdir()
    replay_verified = False
    last_tracking_status = None
    diagnostics.attach(output/'ocr_diagnostiikka.jsonl')
    tracker = BibTracker(settings)
    generation = None
    sequence = 0
    count = motion = 0
    next_ocr = 0.
    started = time.monotonic()
    last_shape = None
    report(f'Live-tulokset: {output}')
    diagnostics.update(phase='odottaa ensimmäistä vastaanottokuvaa')

    def boundary(reason):
        nonlocal tracker, last_shape
        for track in tracker.finish():
            track.review_reasons.add(reason)
            recorder.finalize(track, interrupted=True)
        # Numerointi jatkuu, mutta identiteetit ja virtaus alkavat alusta.
        next_id = tracker.next_id
        tracker = BibTracker(settings)
        tracker.next_id = next_id
        last_shape = None

    try:
        while not stop.is_set() and not receiver.stop.is_set():
            packet, current_generation, state = receiver.snapshot()
            if generation is not None and current_generation != generation:
                boundary('live_yhteyskatko')
                next_ocr = 0.
            generation = current_generation
            if packet is None or packet.sequence == sequence:
                diagnostics.update(phase='odottaa uutta vastaanottokuvaa')
                stop.wait(.02)
                continue
            sequence = packet.sequence
            frame = packet.image
            timestamp = packet.monotonic - receiver.started
            if last_shape is not None and frame.shape != last_shape:
                boundary('live_resoluutio_muuttui')
            last_shape = frame.shape
            diagnostics.update(phase='liikkeenseuranta')
            for track in tracker.advance(frame, timestamp):
                recorder.finalize(track)
            motion += 1
            if packet.monotonic < next_ocr:
                diagnostics.update(phase='odottaa seuraavaa näyteaikaa')
                continue
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = settings.roi or (0,0,w,h)
            for box in (settings.roi, settings.exclusion):
                if box and not (0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h):
                    raise ValueError('Rajaus ei mahdu livevideoon. Muuta rajausta ja aloita tunnistus uudelleen.')
            crop = frame[y1:y2,x1:x2].copy()
            if settings.exclusion:
                a,b,c,d = settings.exclusion
                if intersection((x1,y1,x2,y2), settings.exclusion):
                    crop[max(0,b-y1):min(y2,d)-y1,max(0,a-x1):min(x2,c)-x1] = 255
            recorder.clocks[f'{timestamp:.6f}'] = packet.wall
            recorder.samples.write(json.dumps(dict(ruutu=sequence,videon_aika_s=timestamp,
                istunnon_aika_s=timestamp,vastaanotto_kellonaika=datetime.fromtimestamp(packet.wall).astimezone().isoformat(),
                yhteysjakso=generation))+'\n')
            state = diagnostics.snapshot()
            submitted = state['submitted'] + 1
            ocr_started = time.monotonic()
            started_wall = datetime.now().astimezone().isoformat(timespec='milliseconds')
            changes = dict(phase='OCR-kutsu käynnissä', submitted=submitted, active_start=ocr_started,
                           input_frame=sequence, input_shape=list(crop.shape), input_dtype=str(crop.dtype))
            if submitted == 1:
                changes['first_start'] = started_wall
                report(f'Ensimmäinen OCR-kutsu ALKU {started_wall} | ruutu {sequence} | kuva {crop.shape}, {crop.dtype}')
            diagnostics.update(**changes)
            input_hash = hashlib.sha256(crop.tobytes()).hexdigest()
            preserved_input = crop.copy()
            source_hash = hashlib.sha256(frame.tobytes()).hexdigest()
            found = engine.recognize(crop)
            duration = time.monotonic()-ocr_started
            ocr_ended_wall = datetime.now().astimezone().isoformat(timespec='milliseconds')
            raw = getattr(engine, 'last_raw', [])
            # Syötekuvat vain debugissa; kaikki tekniset lokit kiertävät kokorajalla.
            capture = settings.debug_frames and not recorder.storage.debug_stopped and not recorder.storage.images_stopped
            sample = None
            if capture:
                sample = f'ocr_syotteet/ruutu_{sequence:09d}'
                input_saved = recorder.debug_image(output/(sample+'_ocr.png'), preserved_input)
                recorder.debug_image(output/(sample+'_vastaanotto.png'), frame)
                if not input_saved:
                    sample = None
                    capture = False
            audit.write(json.dumps(dict(ruutu=sequence, aika_s=timestamp, raakatekstit=raw,
                numeroiksi_tulkitut=[n for n,_,_ in found], kuva=sample, shape=list(crop.shape),
                dtype=str(crop.dtype), kanavat='BGR', strides=list(crop.strides),
                owns_data=bool(crop.flags.owndata), input_sha256=input_hash,
                input_unchanged=input_hash == hashlib.sha256(crop.tobytes()).hexdigest(),
                source_sha256=source_hash,
                source_unchanged=source_hash == hashlib.sha256(frame.tobytes()).hexdigest()),
                ensure_ascii=False)+'\n')
            if capture:
                report('OCR raakatekstit ennen suodatusta: '+json.dumps(raw, ensure_ascii=False)+
                       f' | täsmällinen syöte: {output/(sample+"_ocr.png")}')
            if capture and found and raw and not replay_verified:
                # Sama tallennettu syöte ja sama PaddleEngine kuin MP4-polussa.
                import cv2
                saved_image = cv2.imdecode(np.frombuffer((output/(sample+'_ocr.png')).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
                engine.recognize(saved_image)
                replay = dict(kuva=sample+'_ocr.png', original_raw=raw,
                    replay_raw=getattr(engine,'last_raw',[]),
                    pixels_identical=np.array_equal(saved_image,preserved_input),
                    raw_identical=raw == getattr(engine,'last_raw',[]),
                    implementation='PaddleEngine, yhteinen MP4/live-toteutus')
                try:
                    (output/'ocr_syotevertailu.json').write_text(json.dumps(replay,ensure_ascii=False,indent=2),encoding='utf-8')
                except OSError as exc:
                    report(f'Debug-vertailun kirjoitusvirhe: {exc}')
                report(f'Tallennetun OCR-syötteen vertailu: samat pikselit {replay["pixels_identical"]}, samat raakatekstit {replay["raw_identical"]}')
                replay_verified = True
            completed = state['completed']+1
            changes = dict(phase='OCR-kutsu valmistui', completed=completed, active_start=None,
                           last_duration=duration, detections=len(found))
            if submitted == 1:
                ended_wall = ocr_ended_wall
                changes.update(first_end=ended_wall, first_duration=duration)
                report(f'Ensimmäinen OCR-kutsu LOPPU {ended_wall} | kesto {duration:.3f} s | numeroita {len(found)}')
            diagnostics.update(**changes)
            detections = [(n,s,p+np.array([x1,y1])) for n,s,p in found]
            # Katko OCR-kutsun aikana: tulos ei saa tulla seuraavaan jaksoon.
            _, after_generation, _ = receiver.snapshot()
            if after_generation != generation or receiver.stop.is_set():
                diagnostics.update(discarded=diagnostics.snapshot()['discarded']+1,
                                   phase='OCR-tulos hylätty yhteyskatkon vuoksi')
                continue
            diagnostics.update(phase='seurannan ja kuvien tallennus')
            added, retired = tracker.update(frame,timestamp,sequence,detections)
            for event in tracker.association_events:
                recorder.associations.write(json.dumps(event,ensure_ascii=False)+'\n')
            tracker.association_events.clear()
            for track in retired:
                recorder.finalize(track)
            for track, observation in added:
                recorder.observation(track, observation, frame)
            for track in retire_live_without_ocr(tracker, timestamp):
                report(f'Live-seuranta {track.id} päättyi: viimeisestä OCR-havainnosta '
                       f'{timestamp-track.last_detection:.3f} s > katkoraja {settings.track_gap:.3f} s.')
                recorder.finalize(track)
            active_status = []
            for track in tracker.active.values():
                number, confirmation, reasons = track.decision(settings)
                active_status.append(dict(seuranta_id=track.id, ehdokas=track.decision_details.get('vahvin'),
                    hyvaksyttavissa=number, syyt=reasons,
                    estavat_ehdot=track.decision_details.get('estavat_ehdot'),
                    odottaa_seurannan_paattymista=True,
                    viimeisesta_ocr_havainnosta_s=timestamp-track.last_detection,
                    viimeisesta_visuaalisesta_havainnosta_s=timestamp-track.last_visual))
            chain.write(json.dumps(dict(ruutu=sequence, aktiiviset=active_status,
                liitetyt=[dict(numero=o.number,seuranta_id=t.id) for t,o in added],
                kirjattu=recorder.saved, epavarmat=recorder.uncertain),ensure_ascii=False)+'\n')
            tracking_status = tuple((s['seuranta_id'],s['ehdokas'],s['hyvaksyttavissa'],tuple(s['syyt'])) for s in active_status)
            if tracking_status != last_tracking_status:
                report('Live-seuranta: '+json.dumps(active_status,ensure_ascii=False)+
                       f' | CSV-kirjauksia {recorder.saved}')
                last_tracking_status = tracking_status
            recorder.flush()
            count += 1
            diagnostics.update(processed=count)
            if settings.debug_frames:
                recorder.debug_image(output/'debug'/f'ruutu_{sequence:09d}.png',frame)
            now = time.monotonic()
            preview(frame,timestamp,count,recorder.saved)
            report(f'Live OCR {count/max(now-started,.001):.2f} näytettä/s | käsittelyviive {now-packet.monotonic:.2f} s | CSV {recorder.saved} | aktiivisia seurantoja {len(tracker.active)}')
            next_ocr = packet.monotonic + settings.interval
    except Exception:
        error = safe_traceback(traceback.format_exc(), settings.stream_url)
        state = diagnostics.snapshot()
        changes = dict(phase='työntekijäsäikeen virhe', error=error, active_start=None)
        if state['submitted']==1 and state['completed']==0 and state['active_start'] is not None:
            ended_wall = datetime.now().astimezone().isoformat(timespec='milliseconds')
            duration = time.monotonic()-state['active_start']
            changes.update(first_end=ended_wall, first_duration=duration, first_failed=True)
            report(f'Ensimmäinen OCR-kutsu LOPPU (VIRHE) {ended_wall} | kesto {duration:.3f} s')
        diagnostics.update(**changes)
        (output/'virhe.txt').write_text(error, encoding='utf-8')
        boundary('live_kasittelyvirhe')
        raise
    finally:
        for track in tracker.finish():
            recorder.finalize(track, interrupted=True)
        summary = dict(stopped=True,processed_frames=count,motion_frames=motion,saved_detections=recorder.saved,
                       uncertain_candidates=recorder.uncertain,elapsed_seconds=time.monotonic()-started,
                       ocr_submitted=diagnostics.snapshot()['submitted'],ocr_completed=diagnostics.snapshot()['completed'])
        (output/'yhteenveto.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        recorder.close()
        if diagnostics.snapshot()['error'] is None:
            diagnostics.update(phase='työntekijäsäie päättyi', active_start=None)
    return output, summary
