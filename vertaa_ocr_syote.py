"""Vertaa tallennettua live-OCR-syötettä samaan MP4:n PaddleEngine-toteutukseen."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numerontunnistin_paikallinen as app


def compare(path, engine):
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f'Kuvaa ei voitu lukea: {path}')
    before = hashlib.sha256(image.tobytes()).hexdigest()
    engine.recognize(image)
    first = list(engine.last_raw)
    engine.recognize(image.copy())
    second = list(engine.last_raw)
    return dict(path=str(path), shape=list(image.shape), dtype=str(image.dtype), channels='BGR',
        sha256=before, unchanged=before == hashlib.sha256(image.tobytes()).hexdigest(),
        implementation='numerontunnistin_paikallinen.PaddleEngine (sama MP4/live)',
        raw_first=first, raw_second=second, identical=first == second)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('images', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    settings = app.settings_from_json(app.LAST_SETTINGS)
    engine = app.PaddleEngine(settings.device, print)
    results = [compare(path, engine) for path in args.images]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
