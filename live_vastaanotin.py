"""Vastaanottoprosessi. Kuvapaketit stdoutiin, osoite vain stdinistä."""
import json
import struct
import sys
import time


def packet(header, data=b''):
    header['bytes'] = len(data)
    encoded = json.dumps(header).encode('utf-8')
    out = sys.stdout.buffer
    out.write(struct.pack('<I', len(encoded)))
    out.write(encoded)
    out.write(data)
    out.flush()


def ndi_find(ndi):
    finder = ndi.find_create_v2(ndi.FindCreate())
    if not finder:
        raise RuntimeError('NDI-haku ei käynnistynyt')
    time.sleep(2)
    return finder, ndi.find_get_current_sources(finder) or []


def run_ndi(config):
    import NDIlib as ndi
    import numpy as np
    if not ndi.initialize():
        raise RuntimeError('NDI-alustus epäonnistui')
    recv = None
    finder = None
    try:
        finder, sources = ndi_find(ndi)
        if config.get('discover'):
            packet({'sources': [s.ndi_name for s in sources]})
            return
        source = next((s for s in sources if s.ndi_name == config['ndi_source']), None)
        if source is None:
            raise RuntimeError('Valittua NDI-lähdettä ei löytynyt')
        options = ndi.RecvCreateV3()
        options.color_format = ndi.RECV_COLOR_FORMAT_BGRX_BGRA
        options.bandwidth = ndi.RECV_BANDWIDTH_HIGHEST
        options.allow_video_fields = False
        recv = ndi.recv_create_v3(options)
        if not recv:
            raise RuntimeError('NDI-vastaanotin ei käynnistynyt')
        ndi.recv_connect(recv, source)
        last = time.monotonic()
        while True:
            result = ndi.recv_capture_v2(recv, 500)
            if result[0] == ndi.FRAME_TYPE_VIDEO:
                video = result[1]
                try:
                    image = np.ascontiguousarray(video.data[:, :, :3]).copy()
                    now, wall = time.monotonic(), time.time()
                finally:
                    ndi.recv_free_video_v2(recv, video)
                packet({'shape': list(image.shape), 'monotonic': now, 'wall': wall}, image.tobytes())
                last = now
            elif result[0] == ndi.FRAME_TYPE_AUDIO:
                ndi.recv_free_audio_v2(recv, result[2])
            elif result[0] == getattr(ndi, 'FRAME_TYPE_METADATA', 3):
                ndi.recv_free_metadata(recv, result[3])
            if time.monotonic() - last > 5:
                raise RuntimeError('NDI-kuvavirta katkesi tai kuvaa ei saatu')
    finally:
        if recv:
            ndi.recv_destroy(recv)
        if finder:
            ndi.find_destroy(finder)
        ndi.destroy()


def run_network(config):
    import cv2
    cap = cv2.VideoCapture()
    try:
        # Natiivikirjaston stderr on vanhemman toimesta DEVNULL: URL-tunnuksia
        # ei voi vuotaa FFmpeg/OpenCV-diagnostiikasta lokiin.
        ok = cap.open(config['stream_url'], cv2.CAP_FFMPEG,
                      [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000])
        if not ok:
            raise RuntimeError('Verkkovideota ei voitu avata; tarkista virran URL ja yhteys')
        while True:
            ok, image = cap.read()
            now, wall = time.monotonic(), time.time()
            if not ok:
                raise RuntimeError('Verkkovideon kuvavirta katkesi')
            packet({'shape': list(image.shape), 'monotonic': now, 'wall': wall}, image.tobytes())
    finally:
        cap.release()


if __name__ == '__main__':
    try:
        config = json.loads(sys.stdin.readline())
        if config['source_type'] == 'NDI':
            run_ndi(config)
        else:
            run_network(config)
    except Exception as exc:
        # Verkkovirheen teksti voi sisältää tunnuksia: älä välitä sitä.
        message = str(exc) if 'config' in globals() and config.get('source_type') == 'NDI' else 'Verkkovideon vastaanotto epäonnistui'
        packet({'error': message})
