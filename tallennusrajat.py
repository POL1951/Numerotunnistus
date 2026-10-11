"""Kilpailun kuvarajat ja kierrätettävät tekniset lokit (CSV:t eivät kierrä)."""
import os
import shutil
import time
from pathlib import Path

MIB = 1024 * 1024
LOG_LIMIT = 2 * MIB
LOG_BACKUPS = 3
DEBUG_LIMIT = 256 * MIB
IMAGE_RESERVE = 256 * MIB
WARN_FREE = 1024 * MIB


class RotatingText:
    def __init__(self, path, report=lambda text: None, limit=LOG_LIMIT):
        self.path = Path(path)
        self.report, self.limit = report, limit
        self.disabled = False
        self.file = None

    def write(self, text):
        if self.disabled:
            return
        try:
            data = text.encode('utf-8')
            if len(data) > self.limit:
                self.report(f'Teknisen lokin liian suuri merkintä ohitettu: {self.path.name}')
                return
            if self.file is None:
                self.file = self.path.open('ab')
            if self.file.tell() + len(data) > self.limit:
                self.file.close()
                self.file = None
                for i in range(LOG_BACKUPS, 0, -1):
                    source = self.path if i == 1 else Path(str(self.path) + f'.{i-1}')
                    target = Path(str(self.path) + f'.{i}')
                    if source.exists():
                        os.replace(source, target)
                self.file = self.path.open('ab')
            self.file.write(data)
        except OSError as exc:
            self.disabled = True
            self.report(f'Teknisen lokin kirjoitusvirhe, loki keskeytetty: {self.path}: {exc}')

    def flush(self):
        if self.file and not self.disabled:
            try:
                self.file.flush()
                os.fsync(self.file.fileno())
            except OSError as exc:
                self.disabled = True
                self.report(f'Teknisen lokin kirjoitusvirhe: {self.path}: {exc}')

    def close(self):
        if self.file:
            try:
                self.file.close()
            except OSError as exc:
                self.disabled = True
                self.report(f'Teknisen lokin sulkemisvirhe: {self.path}: {exc}')
            finally:
                self.file = None


class StorageBudget:
    def __init__(self, output, report=lambda text: None, notify=None):
        self.output = Path(output)
        self.report, self.notify = report, notify
        self.debug_bytes = 0
        self.images_stopped = False
        self.debug_stopped = False
        self.warned = False
        self.last_status = 0

    def free(self):
        return shutil.disk_usage(self.output).free

    def image_allowed(self, size):
        if self.images_stopped:
            return False
        try:
            enough = self.free() >= IMAGE_RESERVE + size
        except OSError as exc:
            self.report(f'Levyn vapaan tilan tarkistus epäonnistui: {exc}')
            enough = False
        if not enough:
            self.stop_images('Vapaa levytila alle 256 MiB:n vararajan.')
        return enough

    def stop_images(self, reason):
        if not self.images_stopped:
            self.images_stopped = True
            self.report(f'KUVATALLENNUS KESKEYTETTY: {reason} Tunnistus ja havainto-CSV jatkuvat niin kauan kuin kirjoittaminen onnistuu.')
            self.status(force=True)

    def write_image(self, path, data, debug=False):
        if debug and (self.debug_stopped or self.debug_bytes + len(data) > DEBUG_LIMIT):
            if not self.debug_stopped:
                self.debug_stopped = True
                self.report('Debug-kuvien tallennusraja 256 MiB saavutettu; debug-kuvatallennus päättyi.')
                self.status(force=True)
            return False
        if not self.image_allowed(len(data)):
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            self.stop_images(f'Kuvan kirjoitusvirhe: {path}: {exc}')
            return False
        if debug:
            self.debug_bytes += len(data)
        return True

    def status(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_status < 5:
            return
        self.last_status = now
        try:
            used = sum(p.stat().st_size for p in self.output.rglob('*') if p.is_file())
            free = self.free()
        except OSError as exc:
            self.report(f'Levytilan mittausvirhe: {exc}')
            return
        if free < WARN_FREE and not self.warned:
            self.warned = True
            self.report('VAROITUS: levyn vapaa tila alle 1 GiB.')
        if self.notify:
            self.notify(dict(output=str(self.output), used=used, free=free,
                             images_stopped=self.images_stopped, debug_stopped=self.debug_stopped))
