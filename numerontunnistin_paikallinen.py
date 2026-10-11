"""Paikallinen MP4-kilpailunumerotesti. Ei Claude- tai NDI-riippuvuuksia."""
from __future__ import annotations

import csv
import json
import math
import os
import queue
import re
import threading
import time
import traceback
from dataclasses import dataclass, asdict
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

BASE = Path(__file__).resolve().parent
LAST_SETTINGS = BASE / 'viimeksi_kaytetyt_asetukset.json'
# Mallit ja kirjaston välimuisti pidetään projektissa.
os.environ.setdefault("PADDLE_HOME", str(BASE / ".models" / "paddle"))
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(BASE / ".models" / "paddlex"))
os.environ.setdefault("OMP_NUM_THREADS", "2")

import cv2
import numpy as np
from PIL import Image, ImageTk
from havaintoseuranta import BibTracker, intersection, box_of, context_box
from seurannan_tallennus import TrackRecorder, ACCEPTED_FIELDS
from live_video import LiveReceiver, LiveDiagnostics, discover_ndi, ndi_python, process_live, safe_url, safe_traceback, validate_url


@dataclass(frozen=True)
class Settings:
    source_type: str = 'MP4-tiedosto'
    ndi_source: str = 'LOCALHOST (VM33_0176E)'
    stream_url: str = ''
    interval: float = 1.0
    duplicate_seconds: float = 10.0
    confidence: float = 0.5
    device: str = "auto"
    roi: tuple[int, int, int, int] | None = None
    exclusion: tuple[int, int, int, int] | None = None
    confirmation_count: int = 3
    confirmation_window: float = 3.0
    track_gap: float = 2.0
    debug_frames: bool = False
    minimum_text_height: float = 20.0
    dominance_enabled: bool = True
    dominance_share: float = 0.8
    dominance_ratio: float = 3.0
    dominance_confidence: float = 0.8
    dominance_track_quality: float = 0.7
    dominance_max_alternative_frames: int = 1

    def validate(self):
        if self.source_type not in ('MP4-tiedosto', 'NDI', 'Verkkovideo'):
            raise ValueError('Tuntematon lähdetyyppi.')
        if self.source_type == 'Verkkovideo':
            validate_url(self.stream_url)
        for value in [self.dominance_share, self.dominance_confidence, self.dominance_track_quality]:
            if not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError('Vahvimman vaihtoehdon osuudet ja laaturajat: anna arvo väliltä (0, 1].')
        if not math.isfinite(self.dominance_ratio) or self.dominance_ratio <= 1:
            raise ValueError('Tukisuhteen pitää olla yli 1.')
        if not isinstance(self.dominance_max_alternative_frames, int) or self.dominance_max_alternative_frames < 0:
            raise ValueError('Poikkeavan vaihtoehdon enimmäisruudut: anna vähintään 0.')
        if not math.isfinite(self.minimum_text_height) or self.minimum_text_height < 0:
            raise ValueError('Numerorivin vähimmäiskorkeus: anna vähintään 0 pikseliä.')
        if not math.isfinite(self.interval) or self.interval <= 0:
            raise ValueError("Näytteenottovälin pitää olla positiivinen sekuntimäärä.")
        if not math.isfinite(self.duplicate_seconds) or self.duplicate_seconds < 0:
            raise ValueError("Kaksoishavaintojen eston pitää olla vähintään 0 sekuntia.")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Luottamusrajan pitää olla välillä 0–1.")
        if self.device not in ("auto", "cpu", "gpu"):
            raise ValueError("Tuntematon laitevalinta.")
        if not isinstance(self.confirmation_count, int) or self.confirmation_count < 2:
            raise ValueError("Vahvistus vaatii vähintään kaksi eri videoruutua.")
        for value, title in [(self.confirmation_window, 'Vahvistuksen aikaikkuna'),
                             (self.track_gap, 'Seurannan katkon sieto')]:
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{title}: anna positiivinen sekuntimäärä.")


def settings_from_json(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('Asetustiedoston pitää sisältää JSON-objekti.')
    defaults = asdict(Settings())
    unknown = set(data) - set(defaults)
    if unknown:
        raise ValueError('Tuntemattomat asetukset: ' + ', '.join(sorted(unknown)))
    values = {**defaults, **data}
    for key, default in defaults.items():
        value = values[key]
        if key in ('roi', 'exclusion'):
            if value is not None:
                if (not isinstance(value, (list, tuple)) or len(value) != 4
                        or any(type(v) is not int for v in value)
                        or not (0 <= value[0] < value[2] and 0 <= value[1] < value[3])):
                    raise ValueError(f'{key}: anna null tai neljä kelvollista pikselikoordinaattia.')
                values[key] = tuple(value)
        elif type(default) is bool:
            if type(value) is not bool:
                raise ValueError(f'{key}: arvon pitää olla true tai false.')
        elif type(default) is int:
            if type(value) is not int:
                raise ValueError(f'{key}: arvon pitää olla kokonaisluku.')
        elif type(default) is float:
            if type(value) not in (int, float):
                raise ValueError(f'{key}: arvon pitää olla luku.')
        elif not isinstance(value, str):
            raise ValueError(f'{key}: arvon pitää olla teksti.')
    settings = Settings(**values)
    settings.validate()
    return settings


def save_settings_json(path, settings):
    settings.validate()
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def numeric_text(text):
    """Hyväksy kokonainen numeroteksti; älä arvaa O/0 tai I/1."""
    clean = re.sub(r"\s+", "", str(text))
    if re.fullmatch(r"[0-9]{1,8}", clean) and int(clean) > 0:
        return str(int(clean))
    return None


class DuplicateFilter:
    def __init__(self, seconds):
        self.seconds = seconds
        self.last_saved = {}

    def accept(self, number, video_seconds):
        last = self.last_saved.get(number)
        if self.seconds > 0 and last is not None and video_seconds - last < self.seconds:
            return False
        self.last_saved[number] = video_seconds
        return True


class PaddleEngine:
    def __init__(self, preference, report):
        import paddle
        from paddleocr import PaddleOCR
        self.preference = preference
        self.device = "cpu"
        if preference != "cpu" and paddle.is_compiled_with_cuda():
            try:
                if paddle.device.cuda.device_count() > 0:
                    paddle.set_device("gpu:0")
                    # Suorita oikea GPU-operaatio ennen laitteen ilmoittamista.
                    (paddle.ones([2, 2]) @ paddle.ones([2, 2])).numpy()
                    self.device = "gpu:0"
            except Exception as exc:
                if preference == "gpu":
                    raise RuntimeError(f"GPU ei käytettävissä: {exc}") from exc
                report(f"GPU-tarkistus epäonnistui, käytetään CPU:ta: {exc}")
        if preference == "gpu" and self.device == "cpu":
            raise RuntimeError("GPU pyydetty, mutta Paddle ei löydä toimivaa CUDA-laitetta.")
        report(f"Alustetaan PaddleOCR-mobiilimallit ({self.device.upper()}).")
        local_models = BASE / ".models" / "paddlex" / "official_models"
        model_dirs = {}
        for role, name in [("text_detection", "PP-OCRv4_mobile_det"),
                           ("text_recognition", "PP-OCRv4_mobile_rec")]:
            directory = local_models / name
            if (directory / "inference.yml").is_file() and (directory / "inference.pdiparams").is_file():
                model_dirs[role + "_model_dir"] = str(directory)
        self.ocr = PaddleOCR(
            text_detection_model_name="PP-OCRv4_mobile_det",
            text_recognition_model_name="PP-OCRv4_mobile_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device=self.device,
            cpu_threads=2,
            enable_mkldnn=False,
            text_det_limit_side_len=960,
            text_det_limit_type="max",
            text_rec_score_thresh=0.0,
            **model_dirs,
        )

    def recognize(self, image):
        found = []
        self.last_raw = []
        for result in self.ocr.predict(image):
            for text, score, polygon in zip(result["rec_texts"], result["rec_scores"], result["rec_polys"]):
                self.last_raw.append(dict(text=str(text), confidence=float(score),
                                          polygon=np.asarray(polygon).tolist()))
                number = numeric_text(text)
                if number is not None:
                    found.append((number, float(score), np.asarray(polygon, dtype=np.int32)))
        return found


def save_png(path, image):
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise OSError(f"Kuvan pakkaus epäonnistui: {path}")
    path.write_bytes(encoded.tobytes())


def process_video(path, settings, engine, stop, report, preview, output_root=None, on_accepted=None, on_storage=None):
    """OCR valituista näytteistä, liikkeenseuranta myös niiden välisistä ruuduista."""
    settings.validate()
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("Videota ei voitu avata.")
    output = recorder = None
    tracker = BibTracker(settings)
    count = motion_frames = excluded = 0
    started = time.perf_counter()
    ocr_seconds = tracking_seconds = 0.0
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Videon FPS puuttuu. Muunna video vakionopeuksiseksi MP4:ksi.")
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        output = (output_root or BASE / "paikalliset_tulokset") / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output.mkdir(parents=True)
        (output / 'kuvat').mkdir()
        if settings.debug_frames:
            (output / 'debug').mkdir()
        settings_metadata = asdict(settings)
        settings_metadata['stream_url'] = safe_url(settings.stream_url)
        metadata = {'video': str(Path(path).resolve()), 'settings': settings_metadata,
                    'device': engine.device, 'fps': fps, 'frame_count': total,
                    'timestamp_source': 'OpenCV POS_MSEC, fallback frame_index/fps',
                    'acceptance_policy': 'spatial_track_consensus_until_end'}
        (output / 'ajo.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
        report(f'Tulokset: {output}. Vahvistus odottaa seurannan päättymistä.')
        recorder = TrackRecorder(output, settings, on_accepted=on_accepted, report=report, on_storage=on_storage)
        recorder.storage.status(force=True)
        index = next_index = sample = 0
        last_timestamp = -1.0
        while not stop.is_set() and cap.grab():
            if index < next_index and not tracker.active:
                index += 1
                continue
            ok, frame = cap.retrieve()
            if not ok:
                raise RuntimeError(f'Videoruudun {index} purkaminen epäonnistui.')
            timestamp = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if not math.isfinite(timestamp) or timestamp < 0 or (index > 0 and timestamp <= last_timestamp):
                timestamp = index / fps
            if timestamp <= last_timestamp:
                raise RuntimeError('Videon aikaleimat eivät etene. Muunna video vakionopeuksiseksi.')
            last_timestamp = timestamp
            tick = time.perf_counter()
            retired = tracker.advance(frame, timestamp)
            tracking_seconds += time.perf_counter() - tick
            motion_frames += 1
            for track in retired:
                recorder.finalize(track)
            if index < next_index:
                index += 1
                continue
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = settings.roi or (0, 0, w, h)
            for box, title in [(settings.roi, 'Tunnistusalue'), (settings.exclusion, 'Poissulkualue')]:
                if box and not (0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h):
                    raise ValueError(f'{title} ei mahdu videoruutuun.')
            crop = frame[y1:y2, x1:x2].copy()
            if settings.exclusion:
                a, b, c, d = settings.exclusion
                if intersection((x1, y1, x2, y2), settings.exclusion):
                    crop[max(0, b - y1):min(y2, d) - y1,
                         max(0, a - x1):min(x2, c) - x1] = 255
            tick = time.perf_counter()
            recorder.samples.write(json.dumps({'ruutu': index, 'videon_aika_s': timestamp,
                'naytevali_s': settings.interval, 'roi': [x1, y1, x2, y2]}) + '\n')
            detections = [(n, s, p + np.array([x1, y1])) for n, s, p in engine.recognize(crop)]
            ocr_seconds += time.perf_counter() - tick
            if settings.exclusion:
                excluded += sum(intersection(box_of(p), settings.exclusion) > 0 for _, _, p in detections)
            tick = time.perf_counter()
            added, retired = tracker.update(frame, timestamp, index, detections)
            for event in tracker.association_events:
                recorder.associations.write(json.dumps(event, ensure_ascii=False) + '\n')
            tracker.association_events.clear()
            tracking_seconds += time.perf_counter() - tick
            for track in retired:
                recorder.finalize(track)
            count += 1
            annotated = frame.copy()
            cv2.rectangle(annotated, (x1, y1), (x2 - 1, y2 - 1), (255, 180, 0), 2)
            if settings.exclusion:
                a, b, c, d = settings.exclusion
                cv2.rectangle(annotated, (a, b), (c, d), (0, 0, 255), 2)
            for track, observation in added:
                recorder.observation(track, observation, frame)
                colour = (0, 0, 255) if len(track.candidates(settings.confidence, settings.minimum_text_height)) > 1 else (0, 180, 255)
                polygon = np.asarray(observation.polygon, np.int32)
                cv2.polylines(annotated, [polygon], True, colour, 2)
                px, py = polygon.min(axis=0)
                cv2.putText(annotated, f'T{track.id}: {observation.number} {observation.confidence:.2f}',
                            (int(px), max(18, int(py) - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)
            if settings.debug_frames:
                name = f'ruutu_{index:09d}_{timestamp:.3f}s.png'
                recorder.debug_image(output / 'debug' / name, annotated)
                recorder.debug_image(output / 'debug' / ('alue_' + name), crop)
            recorder.flush()
            preview(annotated, timestamp, count, recorder.saved)
            sample += 1
            next_index = max(index + 1, round(sample * settings.interval * fps))
            index += 1
        for track in tracker.finish():
            recorder.finalize(track, interrupted=stop.is_set())
        summary = {'stopped': stop.is_set(), 'processed_frames': count, 'motion_frames': motion_frames,
                   'saved_detections': recorder.saved, 'uncertain_candidates': recorder.uncertain,
                   'completed_tracks': recorder.completed, 'suppressed_detections': recorder.suppressed,
                   'excluded_detections': excluded, 'elapsed_seconds': time.perf_counter() - started,
                   'ocr_seconds': ocr_seconds, 'tracking_seconds': tracking_seconds}
        (output / 'yhteenveto.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        return output, summary
    except Exception:
        if output is not None:
            (output / 'virhe.txt').write_text(traceback.format_exc(), encoding='utf-8')
        if recorder is not None:
            for track in tracker.finish():
                track.review_reasons.add('ajo_virhe')
                recorder.finalize(track, interrupted=True)
        raise
    finally:
        if recorder is not None:
            recorder.close()
        cap.release()


SETTING_HELP = {
    'source_type': 'MP4 käyttää videon aikaa; NDI ja verkkovideo vastaanottohetken aikaa.',
    'ndi_source': 'Päivitä lähteet ja valitse löydetty NDI-lähettäjä. Tarkista ensin esikatselu.',
    'stream_url': 'Täydellinen RTSP/HTTP-videovirran URL. Pelkkä IP ei riitä. Asetus-JSON voi sisältää salasanan.',
    'interval': 'OCR-näytteiden tavoiteväli sekunteina (> 0). Pienempi lisää näytteitä; live-nopeutta rajoittaa käsittely.',
    'duplicate_seconds': 'Eri seurantojen saman numeron aikaesto (s, ≥ 0; 0 poistaa tämän eston). Edeltäjäesto säilyy.',
    'confidence': 'Yksittäisen OCR-havainnon vähimmäisluottamus (0–1). Suurempi karsii enemmän vahvistuksia.',
    'device': 'auto kokeilee GPU:ta ja voi käyttää CPU:ta. cpu pakottaa CPU:n; gpu vaatii toimivan GPU:n.',
    'roi': 'Vedä keltainen tunnistusalue. Vain sen pikselit annetaan OCR:lle; Koko kuva poistaa rajauksen.',
    'exclusion': 'Vedä punainen poissulkualue. Se peitetään OCR-kuvasta; myös sitä leikkaavat numerolaatikot hylätään.',
    'confirmation_count': 'Vähintään näin monta saman numeron kelvollista eri ruutua aikaikkunassa (kokonaisluku ≥ 2).',
    'confirmation_window': 'Vahvistusten liukuva aikaikkuna sekunteina (> 0). Suurempi sallii harvemmat havaintoajat.',
    'track_gap': 'Seurannan katkoraja (s > 0). Livessä myös OCR-todisteen puuttuminen päättää seurannan.',
    'debug_frames': 'Tallentaa kaikki käsitellyt OCR-näytekuvat. Lisää levytilaa ja I/O:ta; ei muuta hyväksymisehtoja.',
    'minimum_text_height': 'OCR-polygoniin perustuva korkeus alkuperäisen kuvan pikseleinä (≥ 0), ei esikatselun mittakaavassa.',
    'dominance_enabled': 'Sallii useasta kelvollisesta numerovaihtoehdosta vahvimman vain kaikkien tukiehtojen täyttyessä.',
    'dominance_share': 'Sekä painotetun tuen että ruutumäärän vähimmäisosuus (0 < arvo ≤ 1); vain usean vaihtoehdon tilanteessa.',
    'dominance_ratio': 'Vahvimman painotettu tuki / toiseksi vahvimman tuki (> 1). Suurempi vaatii selvemmän eron.',
    'dominance_confidence': 'Vahvimman kaikkien kelvollisten ruutujen OCR-luottamusten tavallinen keskiarvo (0 < arvo ≤ 1).',
    'dominance_track_quality': 'Vahvimman kelvollisten ruutujen liitoslaadun keskiarvon alaraja (0 < arvo ≤ 1). Suurempi on parempi.',
    'dominance_max_alternative_frames': 'Enintään näin monta kelvollista ruutua kutakin muuta numeroa kohti erikseen (kokonaisluku ≥ 0).',
}


class SettingTooltip:
    """Lyhyt paikallinen selite ilman muutoksia asetusten arvoihin."""
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.timer = self.window = None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')
        widget.bind('<Destroy>', self.hide, add='+')

    def schedule(self, event=None):
        self.hide()
        self.timer = self.widget.after(450, self.show)

    def show(self):
        self.timer = None
        if not self.widget.winfo_exists():
            return
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.geometry(f'+{self.widget.winfo_rootx()}+{self.widget.winfo_rooty()+self.widget.winfo_height()+5}')
        tk.Label(self.window, text=self.text, wraplength=390, justify='left',
                 background='#fffbd6', foreground='#202020', relief='solid',
                 borderwidth=1, padx=8, pady=6).pack()

    def hide(self, event=None):
        if self.timer is not None:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


class App:
    def __init__(self, root):
        self.root = root
        root.title("Paikallinen kilpailunumerontunnistin – MP4-testi")
        root.geometry("1550x1000")
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, minsize=300)
        root.rowconfigure(0, weight=1)
        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky='nsew')
        footer = ttk.Frame(root)
        footer.grid(row=1, column=0, columnspan=2, sticky='ew')
        self.results_panel = ttk.Frame(root, width=300, padding=8)
        self.results_panel.grid(row=0, column=1, sticky='nsew')
        self.results_panel.grid_propagate(False)
        self.results_panel.columnconfigure(0, weight=1)
        self.results_panel.rowconfigure(2, weight=1)
        self.path = None
        self.cap = None
        self.frame = None
        self.roi = None
        self.exclusion = None
        self.transform = None
        self.drag = None
        self.busy = False
        self.playing = False
        self.preview_serial = 0
        self.closing = False
        self.stop = threading.Event()
        self.events = queue.Queue()
        self.frames = queue.Queue(maxsize=1)
        self.engine = None
        self.live_receiver = None
        self.preview_sequence = 0
        self.last_received_count = 0
        self.live_diagnostics = LiveDiagnostics()
        self.worker_thread = None
        self.status = tk.StringVar(value="Avaa MP4-video. GPU/CPU tarkistetaan tunnistuksen alkaessa.")
        source_row = ttk.Frame(left, padding=8)
        source_row.pack(fill='x')
        self.source_type = tk.StringVar(value='MP4-tiedosto')
        self.ndi_source = tk.StringVar(value='LOCALHOST (VM33_0176E)')
        self.stream_url = tk.StringVar()
        ttk.Label(source_row, text='Lähdetyyppi').pack(side='left')
        self.source_combo = ttk.Combobox(source_row, textvariable=self.source_type,
            values=['MP4-tiedosto', 'NDI', 'Verkkovideo'], state='readonly', width=14)
        self.source_combo.pack(side='left', padx=5)
        self.source_combo.bind('<<ComboboxSelected>>', lambda e: self.source_changed())
        self.refresh_sources_button = ttk.Button(source_row, text='Päivitä lähteet', command=self.refresh_sources)
        self.refresh_sources_button.pack(side='left')
        self.ndi_combo = ttk.Combobox(source_row, textvariable=self.ndi_source, state='readonly', width=30)
        self.ndi_combo.pack(side='left', padx=5)
        self.connect_button = ttk.Button(source_row, text='Yhdistä', command=self.connect_live)
        self.connect_button.pack(side='left')
        self.disconnect_button = ttk.Button(source_row, text='Katkaise', command=self.disconnect_live)
        self.disconnect_button.pack(side='left', padx=5)
        url_row = ttk.Frame(left, padding=(8,0))
        url_row.pack(fill='x')
        ttk.Label(url_row, text='RTSP/HTTP-videovirran URL').pack(side='left')
        self.url_entry = ttk.Entry(url_row, textvariable=self.stream_url, width=60)
        self.url_entry.pack(side='left', padx=5, fill='x', expand=True)
        self.live_state = tk.StringVar(value='Live: katkaistu')
        ttk.Label(left, textvariable=self.live_state).pack(anchor='w', padx=12)
        self.live_metrics = tk.StringVar(value='OCR: ei käynnissä')
        ttk.Label(left, textvariable=self.live_metrics).pack(anchor='w', padx=12)
        self.live_counters = tk.StringVar(value='Vastaanotettu 0 | OCR:lle annettu 0 | OCR valmistunut 0')
        ttk.Label(left, textvariable=self.live_counters, wraplength=1200).pack(anchor='w', padx=12)
        self.first_ocr_status = tk.StringVar(value='Ensimmäinen OCR-kutsu: ei alkanut')
        ttk.Label(left, textvariable=self.first_ocr_status, wraplength=1200).pack(anchor='w', padx=12)
        bar = ttk.Frame(left, padding=8)
        bar.pack(fill="x")
        self.open_button = ttk.Button(bar, text="Avaa MP4", command=self.open_video)
        self.open_button.pack(side="left")
        self.play_button = ttk.Button(bar, text="Esikatselu / tauko", command=self.toggle_preview)
        self.play_button.pack(side="left", padx=5)
        self.clear_button = ttk.Button(bar, text="Koko kuva", command=self.clear_roi)
        self.clear_button.pack(side="left")
        self.clear_exclusion_button = ttk.Button(bar, text="Poista poissulkualue", command=self.clear_exclusion)
        self.clear_exclusion_button.pack(side="left", padx=5)
        self.start_button = ttk.Button(bar, text="Aloita alusta", command=self.start)
        self.start_button.pack(side="left", padx=5)
        self.stop_button = ttk.Button(bar, text="Pysäytä", command=self.stop_run, state="disabled")
        self.stop_button.pack(side="left")
        files = ttk.Frame(left, padding=(8, 0))
        files.pack(fill='x')
        self.load_settings_button = ttk.Button(files, text='Lataa asetukset', command=self.load_settings)
        self.load_settings_button.pack(side='left')
        self.save_settings_button = ttk.Button(files, text='Tallenna asetukset', command=self.save_settings)
        self.save_settings_button.pack(side='left', padx=5)
        self.help_button = ttk.Button(files, text='Ohje', command=self.show_help)
        self.help_button.pack(side='left', padx=5)
        self.area_values = tk.StringVar()
        ttk.Label(files, textvariable=self.area_values).pack(side='left', padx=10)
        options = ttk.Frame(left, padding=8)
        options.pack(fill="x")
        self.interval = tk.StringVar(value="1.0")
        self.duplicate = tk.StringVar(value="10.0")
        self.confidence = tk.StringVar(value="0.5")
        self.device = tk.StringVar(value="auto")
        self.actual_device = tk.StringVar(value="Tunnistuslaite: ei vielä alustettu")
        self.confirmations = tk.StringVar(value='3')
        self.confirmation_window = tk.StringVar(value='3.0')
        self.track_gap = tk.StringVar(value='2.0')
        self.minimum_height = tk.StringVar(value='20')
        self.debug_frames = tk.BooleanVar(value=False)
        self.dominance_enabled = tk.BooleanVar(value=True)
        self.dominance_share = tk.StringVar(value='0.8')
        self.dominance_ratio = tk.StringVar(value='3')
        self.dominance_confidence = tk.StringVar(value='0.8')
        self.dominance_quality = tk.StringVar(value='0.7')
        self.dominance_alternatives = tk.StringVar(value='1')
        self.draw_target = tk.StringVar(value='roi')
        self.setting_variables = {
            'source_type': self.source_type, 'ndi_source': self.ndi_source, 'stream_url': self.stream_url,
            'interval': self.interval, 'duplicate_seconds': self.duplicate,
            'confidence': self.confidence, 'device': self.device,
            'confirmation_count': self.confirmations, 'confirmation_window': self.confirmation_window,
            'track_gap': self.track_gap, 'minimum_text_height': self.minimum_height,
            'debug_frames': self.debug_frames, 'dominance_enabled': self.dominance_enabled,
            'dominance_share': self.dominance_share, 'dominance_ratio': self.dominance_ratio,
            'dominance_confidence': self.dominance_confidence,
            'dominance_track_quality': self.dominance_quality,
            'dominance_max_alternative_frames': self.dominance_alternatives,
        }
        self.settings_widgets = []
        for title, var in [("Näyteväli (s)", self.interval), ("Saman numeron esto eri seurannoille (s; 0=pois)", self.duplicate),
                           ("OCR-raja (0–1)", self.confidence),
                           ('Numerorivin väh. korkeus (px)', self.minimum_height)]:
            ttk.Label(options, text=title).pack(side="left", padx=(8, 3))
            entry = ttk.Entry(options, textvariable=var, width=7)
            entry.pack(side="left")
            self.settings_widgets.append(entry)
        ttk.Label(options, text="Laite").pack(side="left", padx=8)
        combo = ttk.Combobox(options, textvariable=self.device, values=["auto", "cpu", "gpu"], width=7, state="readonly")
        combo.pack(side="left")
        self.device_combo = combo
        self.settings_widgets.append(combo)
        more = ttk.Frame(left, padding=8)
        more.pack(fill='x')
        for title, var in [('Vahvistusruutuja (väh. 2)', self.confirmations),
                           ('Vahvistuksen aikaikkuna (s)', self.confirmation_window),
                           ('Seurannan katkon sieto (s)', self.track_gap)]:
            ttk.Label(more, text=title).pack(side='left', padx=(8, 3))
            entry = ttk.Entry(more, textvariable=var, width=7)
            entry.pack(side='left')
            self.settings_widgets.append(entry)
        debug = ttk.Checkbutton(more, text='Debug (enint. 256 MiB): kaikki OCR-näytekuvat', variable=self.debug_frames)
        debug.pack(side='left', padx=10)
        self.settings_widgets.append(debug)
        drawing = ttk.Frame(left, padding=(12, 0))
        dominance = ttk.Frame(left, padding=8)
        dominance.pack(fill='x')
        check = ttk.Checkbutton(dominance, text='Hyväksy vahvin vaihtoehto', variable=self.dominance_enabled)
        check.pack(side='left')
        self.settings_widgets.append(check)
        for title, var in [('Tukiosuus', self.dominance_share), ('Tukisuhde', self.dominance_ratio),
                           ('Keski-OCR', self.dominance_confidence), ('Liitoslaatu', self.dominance_quality),
                           ('Poikkeaman enimm. ruudut', self.dominance_alternatives)]:
            ttk.Label(dominance, text=title).pack(side='left', padx=(8, 3))
            entry = ttk.Entry(dominance, textvariable=var, width=5)
            entry.pack(side='left')
            self.settings_widgets.append(entry)
        drawing.pack(fill='x')
        for title, value in [('Rajaa tunnistusalue (keltainen)', 'roi'),
                             ('Rajaa kellon poissulkualue (punainen)', 'exclusion')]:
            radio = ttk.Radiobutton(drawing, text=title, variable=self.draw_target, value=value)
            radio.pack(side='left', padx=(0, 20))
            self.settings_widgets.append(radio)
        ttk.Label(left, textvariable=self.actual_device).pack(anchor="w", padx=12)
        ttk.Label(left, text="Valitse rajauksen tyyppi ja vedä hiirellä. Numero vahvistetaan useasta ruudusta ja kirjataan seurannan päättyessä.").pack(anchor="w", padx=12)
        ttk.Label(left, text='Tulosten ajat ovat OCR-havaintoaikoja. Maalilinjan ylitystä ei mitata.').pack(anchor='w', padx=12)
        self.observation_rows = []
        self.observation_live = False
        ttk.Label(self.results_panel, text='Tunnistetut numerot').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.export_button = ttk.Button(self.results_panel, text='Vie lista CSV:ksi', command=self.export_observations, state='disabled')
        self.export_button.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        self.observation_list = ttk.Treeview(self.results_panel, columns=('numero', 'aika'), show='headings')
        self.observation_list.heading('numero', text='Numero')
        self.observation_list.heading('aika', text='Videon aika')
        for key in ('numero', 'aika'):
            self.observation_list.column(key, width=125, minwidth=70, anchor='w')
        self.observation_list.grid(row=2, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(self.results_panel, command=self.observation_list.yview)
        scroll.grid(row=2, column=1, sticky='ns')
        self.observation_list.configure(yscrollcommand=scroll.set)
        self.canvas = tk.Canvas(left, background="#202020", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=8)
        self.canvas.bind("<ButtonPress-1>", self.drag_start)
        self.canvas.bind("<B1-Motion>", self.drag_move)
        self.canvas.bind("<ButtonRelease-1>", self.drag_end)
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.seek = ttk.Scale(footer, from_=0, to=1, command=self.seek_video)
        self.seek.pack(fill="x", padx=12)
        self.storage_status = tk.StringVar(value='Tulokset: ei istuntoa | debug-raja 256 MiB | kuvien vararaja 256 MiB')
        ttk.Label(footer, textvariable=self.storage_status, wraplength=1450).pack(fill='x', padx=12)
        self.position = ttk.Label(footer, text="0.000 s")
        self.position.pack(anchor="w", padx=12)
        ttk.Label(footer, textvariable=self.status, wraplength=1050).pack(fill="x", padx=12, pady=8)
        self.log = tk.Text(footer, height=5, state="disabled")
        self.log.pack(fill="x", padx=8, pady=(0, 8))
        self.setting_tooltips = []
        for widget in self.settings_widgets:
            option = 'variable' if isinstance(widget, (ttk.Checkbutton, ttk.Radiobutton)) else 'textvariable'
            variable = str(widget.cget(option))
            key = next((key for key, var in self.setting_variables.items() if str(var) == variable), None)
            if variable == str(self.draw_target):
                key = str(widget.cget('value'))
            if key in SETTING_HELP:
                self.setting_tooltips.append(SettingTooltip(widget, SETTING_HELP[key]))
        for widget, key in [(self.source_combo, 'source_type'), (self.ndi_combo, 'ndi_source'),
                            (self.url_entry, 'stream_url'), (self.clear_button, 'roi'),
                            (self.clear_exclusion_button, 'exclusion')]:
            self.setting_tooltips.append(SettingTooltip(widget, SETTING_HELP[key]))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.apply_settings(Settings())
        if LAST_SETTINGS.exists():
            try:
                self.apply_settings(settings_from_json(LAST_SETTINGS))
                self.note('Viimeksi käytetyt asetukset palautettu.')
            except (OSError, ValueError, TypeError) as exc:
                self.note(f'Viime asetusten palautus epäonnistui: {exc}')
        root.after(100, self.poll)

    def add_observation(self, row):
        if self.observation_live:
            timestamp = float(row['vastaanotto_aikaleima'])
            shown = datetime.fromtimestamp(timestamp).astimezone().strftime('%H:%M:%S')
        else:
            timestamp = float(row['videon_aika_s'])
            seconds = max(0, int(timestamp))
            shown = f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'
        position = next((i for i, old in enumerate(self.observation_rows)
                         if old['timestamp'] > timestamp), len(self.observation_rows))
        follow = self.observation_list.yview()[1] >= 0.999
        children = self.observation_list.get_children()
        top = self.observation_list.identify_row(1)
        if not top and children:
            top = children[min(len(children)-1, int(self.observation_list.yview()[0]*len(children)))]
        entry = dict(numero=row['numero'], aika=shown, timestamp=timestamp)
        self.observation_rows.insert(position, entry)
        item = self.observation_list.insert('', position, values=(entry['numero'], shown))
        if follow:
            self.observation_list.see(self.observation_list.get_children()[-1])
        elif top:
            index = self.observation_list.index(top)
            self.observation_list.yview_moveto(index / len(self.observation_rows))
        self.export_button.configure(state='normal')

    def export_observations(self):
        path = filedialog.asksaveasfilename(title='Tallenna nimellä',
            defaultextension='.csv', initialfile='havainnot.csv',
            filetypes=[('CSV-tiedosto', '*.csv')])
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as file:
                writer = csv.writer(file, delimiter=';')
                writer.writerow(['numero', 'kellonaika' if self.observation_live else 'videon_aika'])
                writer.writerows((row['numero'], row['aika']) for row in self.observation_rows)
        except OSError as exc:
            messagebox.showerror('CSV-vienti', str(exc))
            return
        self.note(f'Viety {len(self.observation_rows)} havaintoa: {path}')

    def show_help(self):
        path = BASE / 'ASETUKSET.md'
        try:
            content = path.read_text(encoding='utf-8-sig')
        except OSError as exc:
            messagebox.showerror('Asetusohje', f'Ohjetta ei voitu avata: {path}\n{exc}')
            return
        window = tk.Toplevel(self.root)
        window.title('Asetusohje – ASETUKSET.md')
        window.geometry('1000x750')
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill='both', expand=True)
        scroll = ttk.Scrollbar(frame)
        scroll.pack(side='right', fill='y')
        text = tk.Text(frame, wrap='word', padx=10, pady=10,
                       font=('Segoe UI', 11), yscrollcommand=scroll.set)
        text.pack(fill='both', expand=True)
        scroll.configure(command=text.yview)
        text.tag_configure('heading', font=('Segoe UI', 14, 'bold'), spacing1=12, spacing3=6)
        for line in content.splitlines(keepends=True):
            if line.startswith('#'):
                text.insert('end', line.lstrip('#').lstrip(), 'heading')
            else:
                text.insert('end', line)
        text.configure(state='disabled')
        ttk.Button(window, text='Sulje', command=window.destroy).pack(pady=(0, 8))
        window.bind('<Escape>', lambda event: window.destroy())
        text.focus_set()
        return window

    def current_settings(self):
        defaults = asdict(Settings())
        values = {}
        for key, variable in self.setting_variables.items():
            value = variable.get()
            default = defaults[key]
            if type(default) is float:
                value = float(value.replace(',', '.'))
            elif type(default) is int:
                value = int(value)
            values[key] = value
        settings = Settings(**values, roi=self.roi, exclusion=self.exclusion)
        settings.validate()
        return settings

    def apply_settings(self, settings):
        if self.live_receiver is not None:
            self.disconnect_live()
        for key, value in asdict(settings).items():
            if key in self.setting_variables:
                self.setting_variables[key].set(value)
        self.roi, self.exclusion = settings.roi, settings.exclusion
        self.drag = None
        self.start_button.configure(text='Aloita alusta' if settings.source_type == 'MP4-tiedosto' else 'Aloita tunnistus')
        self.draw()

    def source_changed(self):
        if not self.busy:
            self.disconnect_live()
            self.start_button.configure(text='Aloita alusta' if self.source_type.get() == 'MP4-tiedosto' else 'Aloita tunnistus')

    def refresh_sources(self):
        if self.busy:
            return
        self.refresh_sources_button.configure(state='disabled')
        self.live_state.set('NDI-lähteitä etsitään…')
        def discover():
            try:
                self.events.put(('ndi_sources', discover_ndi()))
            except Exception as exc:
                self.events.put(('ndi_error', str(exc)))
        threading.Thread(target=discover, daemon=True).start()

    def connect_live(self):
        if self.busy:
            return
        try:
            kind = self.source_type.get()
            if kind == 'MP4-tiedosto':
                self.open_video()
                return
            if kind == 'NDI':
                ndi_python()
                if not self.ndi_source.get():
                    raise ValueError('Päivitä NDI-lähteet ja valitse lähde.')
            else:
                validate_url(self.stream_url.get())
            config = dict(source_type=kind, ndi_source=self.ndi_source.get(), stream_url=self.stream_url.get())
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror('Videolähde', str(exc))
            return
        self.disconnect_live()
        if self.cap:
            self.cap.release()
            self.cap = None
        self.live_receiver = LiveReceiver(config, lambda s: self.events.put(('live_state', s)))
        self.preview_sequence = 0
        self.last_received_count = 0
        self.playing = True
        self.frame = None
        self.live_receiver.start()

    def disconnect_live(self):
        if self.live_receiver:
            self.last_received_count = self.live_receiver.sequence
            self.live_receiver.disconnect()
            self.live_receiver = None
        self.playing = False
        self.live_state.set('Live: katkaistu')
        if self.busy:
            self.stop.set()

    def load_settings(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(title='Lataa asetukset', filetypes=[('JSON-asetukset', '*.json')])
        if not path:
            return
        try:
            settings = settings_from_json(path)
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror('Asetukset', str(exc))
            return
        self.apply_settings(settings)
        self.note(f'Asetukset ladattu: {path}')

    def save_settings(self):
        if self.busy:
            return
        try:
            settings = self.current_settings()
        except ValueError as exc:
            messagebox.showerror('Asetukset', str(exc))
            return
        path = filedialog.asksaveasfilename(title='Tallenna asetukset', defaultextension='.json',
                                          initialfile='asetukset.json', filetypes=[('JSON-asetukset', '*.json')])
        if not path:
            return
        try:
            save_settings_json(path, settings)
        except OSError as exc:
            messagebox.showerror('Asetukset', str(exc))
            return
        self.note(f'Asetukset tallennettu: {path}')

    def note(self, text):
        self.status.set(text)
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def open_video(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(filetypes=[("MP4-video", "*.mp4"), ("Kaikki videot", "*.*")])
        if not path:
            return
        candidate = cv2.VideoCapture(path)
        ok, frame = candidate.read()
        if not ok:
            candidate.release()
            messagebox.showerror("Video", "Videota ei voitu avata tai ensimmäistä ruutua lukea.")
            return
        self.playing = False
        if self.cap:
            self.cap.release()
        self.cap, self.path, self.frame = candidate, path, frame
        self.disconnect_live()
        self.source_type.set('MP4-tiedosto')
        self.start_button.configure(text='Aloita alusta')
        self.seek.configure(to=max(0, candidate.get(cv2.CAP_PROP_FRAME_COUNT) - 1))
        self.seek.set(0)
        self.note(f"Video: {path}")
        self.draw()

    def seek_video(self, value):
        if self.busy or not self.cap or self.playing:
            return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(float(value)))
        ok, frame = self.cap.read()
        if ok:
            self.frame = frame
            self.position.configure(text=f"{self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000:.3f} s")
            self.draw()

    def toggle_preview(self):
        if self.live_receiver is not None:
            self.playing = not self.playing
            return
        if self.busy or not self.cap:
            return
        self.playing = not self.playing
        self.preview_serial += 1
        if self.playing:
            self.preview_tick(self.preview_serial)

    def preview_tick(self, serial):
        if serial != self.preview_serial or not self.playing or self.busy or self.closing:
            return
        ok, frame = self.cap.read()
        if not ok:
            self.playing = False
            return
        self.frame = frame
        self.seek.set(max(0, self.cap.get(cv2.CAP_PROP_POS_FRAMES) - 1))
        self.position.configure(text=f"{self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000:.3f} s")
        self.draw()
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.root.after(max(1, round(1000 / fps)) if fps > 0 else 40, lambda: self.preview_tick(serial))

    def draw(self):
        self.area_values.set(f'Tunnistusalue: {self.roi or "koko kuva"} | Poissulku: {self.exclusion or "ei"}')
        if self.frame is None:
            return
        h, w = self.frame.shape[:2]
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        scale = min(cw / w, ch / h)
        dw, dh = max(1, round(w * scale)), max(1, round(h * scale))
        ox, oy = (cw - dw) / 2, (ch - dh) / 2
        self.transform = (dw / w, dh / h, ox, oy)
        rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
        self.photo = ImageTk.PhotoImage(Image.fromarray(rgb).resize((dw, dh)))
        self.canvas.delete("all")
        self.canvas.create_image(ox, oy, image=self.photo, anchor="nw")
        for box, colour in [(self.roi, '#ffbf00'), (self.exclusion, '#ff4040')]:
            if box is None:
                continue
            sx, sy, ox, oy = self.transform
            x1, y1, x2, y2 = box
            self.canvas.create_rectangle(ox + x1 * sx, oy + y1 * sy, ox + x2 * sx, oy + y2 * sy,
                                         outline=colour, width=2)

    def image_point(self, event):
        sx, sy, ox, oy = self.transform
        h, w = self.frame.shape[:2]
        return (min(w, max(0, round((event.x - ox) / sx))),
                min(h, max(0, round((event.y - oy) / sy))))

    def drag_start(self, event):
        if self.busy or self.frame is None or self.transform is None:
            return
        self.playing = False
        self.drag = self.image_point(event)
        self.drag_target = self.draw_target.get()

    def drag_move(self, event):
        if self.drag is None or self.busy:
            return
        x, y = self.image_point(event)
        a, b = self.drag
        setattr(self, self.drag_target, (min(x, a), min(y, b), max(x, a), max(y, b)))
        self.draw()

    def drag_end(self, event):
        if self.drag is None:
            return
        self.drag_move(event)
        self.drag = None
        box = getattr(self, self.drag_target)
        if box and (box[2] - box[0] < 5 or box[3] - box[1] < 5):
            setattr(self, self.drag_target, None)
        self.draw()

    def clear_roi(self):
        if not self.busy:
            self.roi = None
            self.draw()

    def clear_exclusion(self):
        if not self.busy:
            self.exclusion = None
            self.draw()

    def set_busy(self, busy):
        self.busy = busy
        for widget in [self.open_button, self.play_button, self.clear_button, self.clear_exclusion_button,
                       self.load_settings_button, self.save_settings_button, self.start_button, self.seek,
                       self.source_combo, self.ndi_combo, self.refresh_sources_button,
                       self.connect_button, self.url_entry] + self.settings_widgets:
            widget.configure(state="disabled" if busy else "normal")
        if not busy:
            self.device_combo.configure(state="readonly")
            self.source_combo.configure(state='readonly')
            self.ndi_combo.configure(state='readonly')
        if self.live_receiver is not None:
            self.play_button.configure(state='normal')
        self.stop_button.configure(state="normal" if busy else "disabled")

    def start(self):
        if self.busy or (self.source_type.get() == 'MP4-tiedosto' and not self.path):
            return
        if self.source_type.get() != 'MP4-tiedosto':
            if self.live_receiver is None or self.live_receiver.snapshot()[0] is None:
                messagebox.showerror('Videolähde', 'Yhdistä ensin live-lähteeseen ja varmista esikatselu.')
                return
        try:
            settings = self.current_settings()
            if settings.source_type != 'MP4-tiedosto':
                active = self.live_receiver.config
                if (settings.source_type != active['source_type']
                        or (settings.source_type == 'NDI' and settings.ndi_source != active['ndi_source'])
                        or (settings.source_type == 'Verkkovideo' and settings.stream_url != active['stream_url'])):
                    raise ValueError('Lähdeasetukset muuttuivat. Yhdistä valittuun lähteeseen uudelleen ennen tunnistusta.')
            if self.frame is not None:
                h, w = self.frame.shape[:2]
                for box in (settings.roi, settings.exclusion):
                    if box and not (0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h):
                        raise ValueError('Ladattu rajaus ei mahdu videoon. Muuta rajausta ennen ajoa.')
        except ValueError as exc:
            messagebox.showerror("Asetukset", str(exc))
            return
        try:
            save_settings_json(LAST_SETTINGS, settings)
        except OSError as exc:
            self.note(f'Viime asetusten tallennus epäonnistui: {exc}')
        self.playing = self.source_type.get() != 'MP4-tiedosto'
        self.observation_live = settings.source_type != 'MP4-tiedosto'
        self.observation_list.heading('aika', text='Kellonaika' if self.observation_live else 'Videon aika')
        self.observation_rows.clear()
        self.observation_list.delete(*self.observation_list.get_children())
        self.export_button.configure(state="disabled")
        self.stop.clear()
        self.live_diagnostics = LiveDiagnostics()
        self.set_busy(True)
        self.note("Tunnistus käynnistyy; odota mallien alustusta.")
        # Kaikki Tk-arvot luetaan yllä pääsäikeessä; työntekijä saa vain tilannekuvan.
        source = self.path if settings.source_type == 'MP4-tiedosto' else self.live_receiver
        self.worker_thread = threading.Thread(target=self.worker, args=(source, settings), daemon=True)
        self.worker_thread.start()

    def worker(self, path, settings):
        report = lambda text: self.events.put(("status", text))
        diagnostics = self.live_diagnostics
        try:
            diagnostics.report = report
            if settings.source_type != 'MP4-tiedosto':
                diagnostics.attach(BASE / 'paikalliset_tulokset' / 'live_diagnostiikka' / 'tyontekija.jsonl')
            diagnostics.update(phase='OCR-mallin alustus')
            if self.engine is None or self.engine.preference != settings.device:
                self.engine = None
                self.engine = PaddleEngine(settings.device, report)
            report(f"Tunnistus käyttää {'GPU:ta' if self.engine.device.startswith('gpu') else 'CPU:ta'} ({self.engine.device}).")
            self.events.put(("device", self.engine.device))
            diagnostics.update(phase='OCR-malli valmis; siirrytään live-käsittelyyn')
            if self.stop.is_set():
                return
            def preview(frame, timestamp, count, saved):
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    pass
                self.frames.put_nowait((frame, timestamp, count, saved))
            if settings.source_type == 'MP4-tiedosto':
                output, summary = process_video(path, settings, self.engine, self.stop, report, preview,
                    on_accepted=lambda row: self.events.put(("observation", row)),
                    on_storage=lambda state: self.events.put(("storage", state)))
            else:
                output, summary = process_live(path, settings, self.engine, self.stop, report,
                    lambda *a: None, diagnostics=diagnostics,
                    on_accepted=lambda row: self.events.put(("observation", row)),
                    on_storage=lambda state: self.events.put(("storage", state)))  # Esikatselu pysyy pääsäikeessä.
            self.events.put(('final_counts', summary))
            report(f"{'Pysäytetty' if summary['stopped'] else 'Valmis'}: {summary['processed_frames']} kuvaa, "
                   f"{summary['saved_detections']} hyväksyttyä, {summary['uncertain_candidates']} tarkistettavaa vaihtoehtoa, "
                   f"{summary['elapsed_seconds']:.1f} s. Tulokset: {output}")
        except Exception as exc:
            error = safe_traceback(traceback.format_exc(), settings.stream_url)
            diagnostics.update(phase='työntekijäsäikeen virhe', error=error, active_start=None)
            report('Työntekijäsäikeen virhe:\n' + error)
            self.events.put(("error", error))
        finally:
            if diagnostics.snapshot()['error'] is None:
                diagnostics.update(phase='työntekijäsäie päättyi', active_start=None)
            self.events.put(("done", None))

    def stop_run(self):
        self.stop.set()
        self.stop_button.configure(state="disabled")
        self.note("Pysäytys pyydetty. Keskeneräinen mallilataus tai OCR-kutsu valmistuu ensin.")

    def poll(self):
        if self.source_type.get() != 'MP4-tiedosto':
            diagnostics = self.live_diagnostics.snapshot()
            if self.live_receiver:
                self.last_received_count = self.live_receiver.sequence
            received = self.last_received_count
            alive = bool(self.worker_thread and self.worker_thread.is_alive())
            active = diagnostics['active_duration']
            duration = f' | käynnissä {active:.2f} s' if active is not None else ''
            self.live_counters.set(f"Vastaanotettu {received} | OCR:lle annettu {diagnostics['submitted']} | "
                                  f"OCR valmistunut {diagnostics['completed']} | säie {'käynnissä' if alive else 'ei käynnissä'} | "
                                  f"{diagnostics['phase']}{duration}")
            if diagnostics['first_start']:
                end = diagnostics['first_end'] or 'odottaa valmistumista'
                first_duration = diagnostics['first_duration']
                elapsed = f'{first_duration:.3f} s' if first_duration is not None else 'kesken'
                failed = ' | VIRHE' if diagnostics['first_failed'] else ''
                self.first_ocr_status.set(f"Ensimmäinen OCR: alku {diagnostics['first_start']} | loppu {end} | kesto {elapsed}{failed}")
            else:
                self.first_ocr_status.set('Ensimmäinen OCR-kutsu: ei alkanut')
        if self.live_receiver and self.playing:
            packet, generation, state = self.live_receiver.snapshot()
            if packet and packet.sequence != self.preview_sequence:
                self.preview_sequence = packet.sequence
                self.frame = packet.image
                self.draw()
                self.position.configure(text=f'Istunnon aika {packet.monotonic-self.live_receiver.started:.3f} s | vastaanottokuvan ikä {time.monotonic()-packet.monotonic:.2f} s')
        try:
            frame, timestamp, count, saved = self.frames.get_nowait()
            self.frame = frame
            self.draw()
            self.position.configure(text=f"{timestamp:.3f} s | käsitelty {count} kuvaa | tallennettu {saved} havaintoa")
        except queue.Empty:
            pass
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "storage":
                warning = ' | KUVATALLENNUS KESKEYTETTY' if value['images_stopped'] else ''
                low = ' | VÄHÄN LEVYTILAA' if value['free'] < 1024**3 else ''
                debug = ' | debug-raja saavutettu' if value['debug_stopped'] else ''
                self.storage_status.set(f"Tulokset: {value['output']} | istunto {value['used']/1024**2:.1f} MiB | vapaa {value['free']/1024**3:.2f} GiB | debug-raja 256 MiB{warning}{low}{debug}")
            elif kind == "observation":
                self.add_observation(value)
            elif kind == "done":
                self.set_busy(False)
                self.live_metrics.set('OCR: pysäytetty')
            elif kind == 'live_state':
                if self.live_receiver:
                    self.live_state.set('Live: ' + self.live_receiver.snapshot()[2])
            elif kind == 'ndi_sources':
                self.refresh_sources_button.configure(state='disabled' if self.busy else 'normal')
                self.ndi_combo.configure(values=value)
                if value and self.ndi_source.get() not in value:
                    self.ndi_source.set(next((s for s in value if 'VM33_0176E' in s), value[0]))
                self.live_state.set(f'NDI: löytyi {len(value)} lähdettä' if value else 'NDI: lähteitä ei löytynyt')
            elif kind == 'ndi_error':
                self.refresh_sources_button.configure(state='disabled' if self.busy else 'normal')
                self.live_state.set(value)
                if not self.closing:
                    messagebox.showerror('NDI', value)
            elif kind == "device":
                self.actual_device.set(f"Tunnistuslaite: {'GPU' if value.startswith('gpu') else 'CPU'} ({value})")
            elif kind == 'final_counts':
                self.position.configure(text=f"{self.position.cget('text').split('|')[0].strip()} | "
                    f"hyväksytty {value['saved_detections']} | tarkistettavia vaihtoehtoja {value['uncertain_candidates']}")
            elif kind == "error":
                if not self.closing:
                    messagebox.showerror("Tunnistusvirhe", value)
            else:
                if isinstance(value, str) and value.startswith('Live OCR '):
                    self.live_metrics.set(value)
                else:
                    self.note(value)
        if self.closing and not self.busy:
            if self.cap:
                self.cap.release()
            self.root.destroy()
            return
        self.root.after(100, self.poll)

    def close(self):
        self.closing = True
        self.disconnect_live()
        self.playing = False
        if self.busy:
            self.stop_run()
        else:
            if self.cap:
                self.cap.release()
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
