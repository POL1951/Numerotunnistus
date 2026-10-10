"""Lukupainotteinen paikallisen OCR:n diagnoosi projektin .venv-tulkilla."""
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / 'testiaineisto' / 'parametrivertailu' / 'ocr_diagnoosi'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for mode in ['tavallinen', 'parametrivertailu']:
        result = subprocess.run([sys.executable, str(Path(__file__)), mode],
                                capture_output=True, text=True, encoding='utf-8', errors='replace',
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        (OUT / f'{mode}_traceback.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
        print(f'--- {mode} ---\n{result.stdout}{result.stderr}', flush=True)
        results[mode] = {'returncode': result.returncode}
    import numerontunnistin_paikallinen as app
    checks = []
    for role in ['PP-OCRv4_mobile_det', 'PP-OCRv4_mobile_rec']:
        directory = BASE / '.models' / 'paddlex' / 'official_models' / role
        for filename in ['inference.yml', 'inference.json', 'inference.pdiparams']:
            path = directory / filename
            for operation in ['stat', 'open_read']:
                row = dict(path=str(path), operation=operation)
                try:
                    if operation == 'stat':
                        row['size'] = path.stat().st_size
                    else:
                        with path.open('rb') as f:
                            row['read_bytes'] = len(f.read(32))
                    row['ok'] = True
                except Exception:
                    row['ok'] = False
                    row['traceback'] = traceback.format_exc()
                    print(row['traceback'], flush=True)
                checks.append(row)
    (OUT / 'tiedostot.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'tulos.json').write_text(json.dumps(results, indent=2), encoding='utf-8')


def child(mode):
    if mode == 'parametrivertailu':
        import parametrivertailu
        app = parametrivertailu.app
    else:
        import numerontunnistin_paikallinen as app
    metadata = dict(executable=sys.executable, prefix=sys.prefix, base_prefix=sys.base_prefix,
                    cwd=os.getcwd(), app_file=app.__file__, base=str(app.BASE),
                    model_root=str(app.BASE / '.models' / 'paddlex' / 'official_models'),
                    environment={k: v for k, v in os.environ.items()
                                 if k.startswith(('PADDLE', 'PYTHON', 'CUDA', 'OMP')) or k in ['TEMP', 'TMP', 'USERPROFILE']})
    (OUT / f'{mode}_ymparisto.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)
    engine = app.PaddleEngine('auto', lambda s: print(s, flush=True))
    cap = app.cv2.VideoCapture(str(BASE / 'video.mp4'))
    cap.set(app.cv2.CAP_PROP_POS_MSEC, 8000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError('Testikuva 8 s puuttuu')
    frame[:112, :270] = 255
    found = engine.recognize(frame)
    data = {'device': engine.device, 'time': 8, 'detections': [[n, s, p.tolist()] for n, s, p in found]}
    (OUT / f'{mode}_yksi_kuva.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(json.dumps(data), flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 2:
        child(sys.argv[1])
    else:
        main()
