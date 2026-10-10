"""NDI-kuvan OCR sekä jatkuva vastaanotto nykyisillä, muuttamattomilla rajoilla."""
import json
import threading
import time
from dataclasses import asdict
from datetime import datetime

import cv2
import numpy as np
import numerontunnistin_paikallinen as app
from live_video import LiveReceiver, LiveDiagnostics, process_live
from havaintoseuranta import intersection

ROOT=app.BASE/'testiaineisto/ndi_ocr_diagnostiikka'


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    settings=app.settings_from_json(app.LAST_SETTINGS)
    if settings.source_type!='NDI':
        raise RuntimeError('Valitse NDI nykyiseen asetustiedostoon ennen testiä; testi ei muuta asetuksia.')
    receiver=LiveReceiver(dict(source_type='NDI',ndi_source=settings.ndi_source,stream_url=''),
                          lambda s:print(s,flush=True))
    receiver.start()
    result=dict(settings=asdict(settings),single_image_test=False,continuous_test=False)
    try:
        deadline=time.monotonic()+20
        packet=None
        while time.monotonic()<deadline:
            packet,_,_=receiver.snapshot()
            if packet is not None:
                break
            time.sleep(.05)
        if packet is None:
            result.update(status='source_unavailable',state=receiver.snapshot()[2],received_frames=receiver.sequence)
            print(json.dumps(result,ensure_ascii=False),flush=True)
            return
        cv2.imwrite(str(ROOT/'ndi_vastaanottokuva.png'),packet.image)
        age=time.monotonic()-packet.monotonic
        assert age>=0
        engine=app.PaddleEngine(settings.device,lambda s:print(s,flush=True))
        h,w=packet.image.shape[:2]
        x1,y1,x2,y2=settings.roi or (0,0,w,h)
        for box in (settings.roi,settings.exclusion):
            if box and not (0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h):
                raise ValueError('Tallennettu rajaus ei mahdu NDI-kuvaan; rajoja ei muutettu.')
        crop=packet.image[y1:y2,x1:x2].copy()
        if settings.exclusion and intersection((x1,y1,x2,y2),settings.exclusion):
            a,b,c,d=settings.exclusion
            crop[max(0,b-y1):min(y2,d)-y1,max(0,a-x1):min(x2,c)-x1]=255
        start=time.monotonic()
        print('YHDEN NDI-KUVAN OCR ALKU '+datetime.now().astimezone().isoformat(),flush=True)
        found=engine.recognize(crop)
        duration=time.monotonic()-start
        print(f'YHDEN NDI-KUVAN OCR LOPPU {duration:.3f} s, numeroita {len(found)}',flush=True)
        result.update(single_image_test=True,first_duration=duration,image_age=age,
                      first_detections=[[n,s,p.tolist()] for n,s,p in found])
        diagnostics=LiveDiagnostics()
        stop=threading.Event()
        timer=threading.Timer(12,stop.set)
        timer.start()
        before=receiver.sequence
        try:
            output,summary=process_live(receiver,settings,engine,stop,lambda s:print(s,flush=True),
                                        lambda *a:None,ROOT,diagnostics)
        finally:
            timer.cancel()
        assert summary['ocr_submitted']>0 and summary['ocr_completed']>0
        assert receiver.sequence>before
        result.update(status='passed',continuous_test=True,output=str(output),summary=summary,
                      diagnostics=diagnostics.snapshot(),received_frames=receiver.sequence)
        print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    finally:
        (ROOT/'raportti.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        receiver.disconnect()
        receiver.thread.join(timeout=4)


if __name__=='__main__':
    main()
