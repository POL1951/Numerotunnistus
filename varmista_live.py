"""Oikea paikallinen HTTP-MJPEG-vastaanotto, ensin esikatselu sitten GPU-OCR."""
import csv
import hashlib
import json
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import cv2
import numerontunnistin_paikallinen as app
from live_video import LiveReceiver, process_live

OUT=app.BASE/'testiaineisto/livevarmennus'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    cap=cv2.VideoCapture(str(app.BASE/'video.mp4'))
    images=[]
    for index in range(255,366,3):
        cap.set(cv2.CAP_PROP_POS_FRAMES,index)
        ok,image=cap.read()
        assert ok
        ok,encoded=cv2.imencode('.jpg',image)
        assert ok
        images.append(encoded.tobytes())
    cap.set(cv2.CAP_PROP_POS_FRAMES,0)
    ok,empty=cap.read()
    cap.release()
    ok,encoded=cv2.imencode('.jpg',empty)
    images.extend([encoded.tobytes()]*30)
    cut_connection=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            try:
                for i in range(2000):
                    data=images[i%len(images)]
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n')
                    self.wfile.flush()
                    if cut_connection.is_set():
                        cut_connection.clear()
                        return
                    time.sleep(.1)
            except (ConnectionError,OSError):
                pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    config=dict(source_type='Verkkovideo',stream_url=f'http://127.0.0.1:{server.server_port}/video',ndi_source='')
    receiver=LiveReceiver(config,lambda s:print(s,flush=True))
    receiver.start()
    root=None
    try:
        deadline=time.monotonic()+15
        while receiver.snapshot()[0] is None and time.monotonic()<deadline:
            time.sleep(.05)
        packet,_,_=receiver.snapshot()
        assert packet is not None,'HTTP-esikatselu ei saanut kuvaa'
        root=app.tk.Tk()
        root.withdraw()
        with patch.object(app,'LAST_SETTINGS',OUT/'testin_viime_asetukset.json'):
            ui=app.App(root)
        ui.source_type.set('Verkkovideo')
        ui.live_receiver=receiver
        ui.playing=True
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            root.update()
            time.sleep(.02)
        assert ui.frame is not None and ui.preview_sequence>0
        cv2.imwrite(str(OUT/'http_esikatselu.jpg'),ui.frame)
        preview_sequence=ui.preview_sequence
        print(f'Esikatselu OK, vastaanotettuja kuvia {preview_sequence}',flush=True)
        engine=app.PaddleEngine('auto',lambda s:print(s,flush=True))
        settings=replace(app.settings_from_json(app.BASE/'testiaineisto/parametrivertailu/parhaat_asetukset.json'),
                         source_type='Verkkovideo',stream_url=config['stream_url'],confirmation_count=2,
                         minimum_text_height=20,confidence=.5)
        stop=threading.Event()
        result={}
        def worker():
            try:
                output,summary=process_live(receiver,settings,engine,stop,lambda s:print(s,flush=True),lambda *a:None,OUT)
                result.update(output=str(output),summary=summary)
            except Exception as exc:
                result['error']=str(exc)
        thread=threading.Thread(target=worker)
        thread.start()
        deadline=time.monotonic()+30
        while time.monotonic()<deadline and thread.is_alive():
            root.update()
            time.sleep(.02)
        stop.set()
        thread.join(timeout=15)
        assert not thread.is_alive()
        assert 'error' not in result,result
        output=Path(result['output'])
        rows=[]
        for name in ['havainnot.csv','epavarmat.csv']:
            with (output/name).open(encoding='utf-8-sig') as file:
                found=list(csv.DictReader(file,delimiter=';'))
            rows.extend(found)
        assert result['summary']['processed_frames']>=2
        assert rows,'GPU-OCR ei tuottanut tallennettuja numeroita'
        assert all(row['vastaanotto_kellonaika'] and row['istunnon_aika_s'] for row in rows)
        assert all((output/row['tarkistuskuva']).is_file() for row in rows)
        assert receiver.sequence>preview_sequence+20
        before_generation=receiver.snapshot()[1]
        cut_connection.set()
        deadline=time.monotonic()+15
        reconnected=False
        while time.monotonic()<deadline:
            root.update()
            packet,generation,state=receiver.snapshot()
            if packet is not None and generation>before_generation and state=='Yhdistetty':
                reconnected=True
                break
            time.sleep(.05)
        assert reconnected,'HTTP-yhteys ei palautunut testikatkon jälkeen'
        result.update(preview_verified=True,gpu_ocr_verified=True,csv_clocks_verified=True,
                      accepted_csv_verified=result['summary']['saved_detections'] > 0,
                      images_verified=True,received_frames=receiver.sequence,
                      reconnect_verified=True,
                      tested_source='local HTTP MJPEG from MP4 fixture, not external camera',
                      original_program_sha256=hashlib.sha256((app.BASE/'numerontunnistin.py').read_bytes()).hexdigest())
        (OUT/'raportti.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    finally:
        receiver.disconnect()
        receiver.thread.join(timeout=4)
        server.shutdown()
        server.server_close()
        if root:
            root.destroy()


if __name__=='__main__':
    main()
