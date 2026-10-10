"""Numerolapun paikallinen seuranta geometrian, optisen virtauksen ja värin avulla.

Numerotekstiä ei käytetä seurantojen yhdistämiseen. Epäselvä liitos merkitään
tarkistettavaksi; yksikään vaihtoehtoinen numero ei voita pituutensa perusteella.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import cv2
import numpy as np


def box_of(polygon):
    points = np.asarray(polygon, dtype=np.float32).reshape(-1, 2)
    return tuple(np.r_[points.min(axis=0), points.max(axis=0)].tolist())


def text_height(polygon):
    """OCR-rivin korkeus alkuperäisen videon pikseleinä, kallistus huomioiden."""
    p = np.asarray(polygon, dtype=float).reshape(4, 2)
    return float(min(np.linalg.norm(p[0] - p[3]), np.linalg.norm(p[1] - p[2])))


def center(box):
    return np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])


def size(box):
    return np.maximum([box[2] - box[0], box[3] - box[1]], 1)


def intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def iou(a, b):
    overlap = intersection(a, b)
    return overlap / max(1, np.prod(size(a)) + np.prod(size(b)) - overlap)


def context_box(box, shape):
    """Numerorivin ympäriltä myös paitaa; ei numerotekstin vertailua."""
    w, h = size(box)
    height, width = shape[:2]
    return (max(0, int(box[0] - 0.6 * w)), max(0, int(box[1] - 1.8 * h)),
            min(width, int(box[2] + 0.6 * w)), min(height, int(box[3] + 0.8 * h)))


def appearance(frame, box):
    x1, y1, x2, y2 = context_box(box, frame.shape)
    if x1 >= x2 or y1 >= y2:
        return None
    hsv = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    # Valkoinen numerolappu ei yksin määritä vaatetuksen värituntomerkkiä.
    mask = np.where((hsv[:, :, 1] > 35) | (hsv[:, :, 2] < 190), 255, 0).astype(np.uint8)
    hist = cv2.calcHist([hsv], [0, 1, 2], mask, [8, 4, 4], [0, 180, 0, 256, 0, 256]).ravel()
    return (hist / hist.sum()).astype(np.float32) if hist.sum() else None


def appearance_distance(a, b):
    if a is None or b is None:
        return 0.5
    return float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))


@dataclass
class Observation:
    number: str
    confidence: float
    polygon: np.ndarray
    time: float
    frame: int
    track_id: int = 0
    association_quality: float = 1.0

    def serializable(self):
        return {'numero': self.number, 'ocr_luottamus': self.confidence,
                'videon_aika_s': self.time, 'ruutu': self.frame,
                'seuranta_id': self.track_id, 'laatikko': box_of(self.polygon),
                'tekstikorkeus_px': text_height(self.polygon),
                'liitoslaatu': self.association_quality}


@dataclass
class Track:
    id: int
    box: tuple
    last_visual: float
    last_update: float
    last_detection: float
    detection_center: np.ndarray
    histogram: np.ndarray | None
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(2))
    points: np.ndarray | None = None
    observations: dict[str, dict[int, Observation]] = field(default_factory=dict)
    review_reasons: set[str] = field(default_factory=set)
    evidence: dict = field(default_factory=dict)
    anchor_histogram: np.ndarray | None = None
    decision_details: dict = field(default_factory=dict)
    possible_parent_ids: set[int] = field(default_factory=set)
    boundary_events: list = field(default_factory=list)

    def add(self, observation):
        observation.track_id = self.id
        frames = self.observations.setdefault(observation.number, {})
        old = frames.get(observation.frame)
        if old is None or observation.confidence > old.confidence:
            frames[observation.frame] = observation

    def candidates(self, threshold, minimum_height=0):
        eligible = lambda o: (o.confidence >= threshold and text_height(o.polygon) >= minimum_height
                              and o.association_quality >= 0.4)
        return {n: sorted((o for o in frames.values() if eligible(o)), key=lambda o: o.time)
                for n, frames in self.observations.items()
                if any(eligible(o) for o in frames.values())}

    def decision(self, settings, interrupted=False):
        candidates = self.candidates(settings.confidence, settings.minimum_text_height)
        reasons = set(self.review_reasons)
        checks = []
        def check(name, measured, operator, limit, passed):
            checks.append({'ehto': name, 'mitattu': measured, 'vertailu': operator,
                           'raja': limit, 'tayttyy': bool(passed)})
        check('pysyvat_turvaestot', sorted(self.review_reasons), 'tyhja', [], not self.review_reasons)
        check('seuranta_valmis', interrupted, '==', False, not interrupted)
        if interrupted:
            reasons.add('keskeytetty_seuranta')
        if not candidates:
            confident = [o for frames in self.observations.values() for o in frames.values()
                         if o.confidence >= settings.confidence]
            large = [o for o in confident if text_height(o.polygon) >= settings.minimum_text_height]
            reasons.add('epavarman_rajaruudun_liitoslaatu' if large else
                        'liian_pieni_numero' if confident else 'matala_ocr_luottamus')
        confirmation = None
        weights = {n: sum(o.confidence * o.association_quality for o in observations)
                   for n, observations in candidates.items()}
        ranked = sorted(candidates, key=lambda n: weights[n], reverse=True)
        number = ranked[0] if ranked else None
        details = {n: {'kelvollisia_ruutuja': len(obs), 'painotettu_tuki': weights[n],
                       'keski_luottamus': sum(o.confidence for o in obs) / len(obs),
                       'keski_liitoslaatu': sum(o.association_quality for o in obs) / len(obs)}
                   for n, obs in candidates.items()}
        self.decision_details = {'vaihtoehdot': details, 'vahvin': number,
                                 'vahvistusruutuja': settings.confirmation_count,
                                 'aikaikkuna_s': settings.confirmation_window, 'ehdot': checks,
                                 'hylatyt_ruudut': [{'numero': o.number, 'ruutu': o.frame, 'aika_s': o.time,
                                     'ocr': o.confidence, 'korkeus_px': text_height(o.polygon),
                                     'liitoslaatu': o.association_quality,
                                     'ocr_raja': settings.confidence, 'kokoraja': settings.minimum_text_height,
                                     'liitoslaaturaja': .4}
                                    for frames in self.observations.values() for o in frames.values()
                                    if o.confidence < settings.confidence or text_height(o.polygon) < settings.minimum_text_height
                                    or o.association_quality < .4]}
        if len(candidates) > 1:
            if not settings.dominance_enabled:
                check('vahvoja_vaihtoehtoja_tiukassa_tilassa', len(candidates), '<=', 1, False)
                reasons.add('ristiriitaiset_numerot')
            else:
                best = details[number]
                share = weights[number] / sum(weights.values())
                count_share = len(candidates[number]) / sum(len(obs) for obs in candidates.values())
                ratio = weights[number] / max(weights[ranked[1]], 1e-9)
                self.decision_details.update(tukiosuus=share, ruutuosuus=count_share, tukisuhde=ratio)
                for label, value, threshold in [
                    ('painotettu_tukiosuus', share, settings.dominance_share),
                    ('ruutuosuus', count_share, settings.dominance_share),
                    ('tukisuhde', ratio, settings.dominance_ratio),
                    ('keski_ocr', best['keski_luottamus'], settings.dominance_confidence),
                    ('keski_liitoslaatu', best['keski_liitoslaatu'], settings.dominance_track_quality),
                    ('min_liitoslaatu', min(o.association_quality for o in candidates[number]), .4)]:
                    check(label, value, '>=', threshold, value >= threshold)
                for variant in ranked[1:]:
                    check('poikkeaman_ruudut:' + variant, len(candidates[variant]), '<=',
                          settings.dominance_max_alternative_frames,
                          len(candidates[variant]) <= settings.dominance_max_alternative_frames)
                if (share < settings.dominance_share or count_share < settings.dominance_share
                        or ratio < settings.dominance_ratio
                        or best['keski_luottamus'] < settings.dominance_confidence
                        or best['keski_liitoslaatu'] < settings.dominance_track_quality
                        or min(o.association_quality for o in candidates[number]) < 0.4
                        or any(len(candidates[n]) > settings.dominance_max_alternative_frames for n in ranked[1:])):
                    reasons.add('vahvimman_vaihtoehdon_tuki_ei_riita')
        if number is not None:
            observations = candidates[number]
            self.decision_details['kelvolliset_ajat_s'] = [o.time for o in observations]
            left = 0
            maximum_support = 0
            for right, observation in enumerate(observations):
                while observations[left].time < observation.time - settings.confirmation_window - 1e-9:
                    left += 1
                maximum_support = max(maximum_support, right-left+1)
                if confirmation is None and right - left + 1 >= settings.confirmation_count:
                    confirmation = observations[left:right + 1]
            check('ruututuki_aikaikkunassa', maximum_support, '>=', settings.confirmation_count,
                  maximum_support >= settings.confirmation_count)
            if confirmation is None:
                reasons.add('vahvistuksia_liian_vahan')
        else:
            check('kelvollisia_havaintoja', 0, '>=', settings.confirmation_count, False)
        self.decision_details['syyt'] = sorted(reasons)
        self.decision_details['estavat_ehdot'] = [c for c in checks if not c['tayttyy']]
        return number if not reasons else None, confirmation, sorted(reasons)


class BibTracker:
    def __init__(self, settings):
        self.settings = settings
        self.active = {}
        self.next_id = 1
        self.previous_gray = None
        self.scale = 1.0
        self.last_time = None
        self.association_events = []

    def _seed(self, track, gray, frame):
        x1, y1, x2, y2 = context_box(track.box, frame.shape)
        mask = np.zeros(gray.shape, np.uint8)
        cv2.rectangle(mask, (round(x1 * self.scale), round(y1 * self.scale)),
                      (round(x2 * self.scale), round(y2 * self.scale)), 255, -1)
        if self.settings.exclusion:
            a, b, c, d = self.settings.exclusion
            cv2.rectangle(mask, (round(a * self.scale), round(b * self.scale)),
                          (round(c * self.scale), round(d * self.scale)), 0, -1)
        track.points = cv2.goodFeaturesToTrack(gray, maxCorners=55, qualityLevel=0.02,
                                             minDistance=3, mask=mask, blockSize=3)

    def _flow(self, track, gray, frame, timestamp):
        dt = timestamp - track.last_update
        previous_box = np.array(track.box, dtype=float)
        track.box = tuple(previous_box + np.tile(track.velocity * dt, 2))
        successful = False
        if self.previous_gray is not None and track.points is not None and len(track.points) >= 5:
            try:
                new, status, _ = cv2.calcOpticalFlowPyrLK(self.previous_gray, gray, track.points, None,
                                                        winSize=(31, 31), maxLevel=4)
                back, backwards, _ = cv2.calcOpticalFlowPyrLK(gray, self.previous_gray, new, None,
                                                             winSize=(31, 31), maxLevel=4)
                good = (status.ravel() == 1) & (backwards.ravel() == 1)
                good &= np.linalg.norm(track.points[:, 0] - back[:, 0], axis=1) < 2.5
                old_points = track.points[good, 0] / self.scale
                new_points = new[good, 0] / self.scale
                if len(new_points) >= 5:
                    transform, inliers = cv2.estimateAffinePartial2D(old_points, new_points,
                                                                   method=cv2.RANSAC, ransacReprojThreshold=5)
                    if transform is not None and int(inliers.sum()) >= 5:
                        zoom = math.hypot(transform[0, 0], transform[1, 0])
                        corners = np.array([[previous_box[0], previous_box[1]],
                                            [previous_box[2], previous_box[3]]])
                        moved = corners @ transform[:, :2].T + transform[:, 2]
                        moved_box = tuple(np.r_[moved.min(axis=0), moved.max(axis=0)])
                        if 0.65 <= zoom <= 1.6 and appearance_distance(track.histogram, appearance(frame, moved_box)) < 0.65:
                            track.box = moved_box
                            if dt > 0:
                                flow_velocity = (center(moved_box) - center(previous_box)) / dt
                                track.velocity = 0.8 * track.velocity + 0.2 * flow_velocity
                            track.last_visual = timestamp
                            successful = True
            except cv2.error:
                pass
        track.last_update = timestamp
        track.points = None
        if successful:
            self._seed(track, gray, frame)

    def _groups(self, detections, timestamp, frame_index):
        groups = []
        for number, confidence, polygon in detections:
            if not math.isfinite(confidence):
                continue
            observation = Observation(number, confidence, np.asarray(polygon), timestamp, frame_index)
            box = box_of(polygon)
            if size(box).min() <= 1:
                continue
            if self.settings.exclusion and intersection(box, self.settings.exclusion) > 0:
                continue
            # Päällekkäiset OCR-tulkinnat kuuluvat samaan paikalliseen laatikkoon.
            group = next((g for g in groups if iou(g['box'], box) > 0.55), None)
            if group is None:
                groups.append({'box': box, 'observations': [observation]})
            else:
                group['observations'].append(observation)
        return groups

    def advance(self, frame, timestamp):
        """Seuraa liikettä myös OCR-näytteiden välisten videoruutujen kautta."""
        if timestamp == self.last_time:
            return []
        self.last_time = timestamp
        self.scale = min(1.0, 960 / frame.shape[1])
        gray = (cv2.cvtColor(cv2.resize(frame, None, fx=self.scale, fy=self.scale), cv2.COLOR_BGR2GRAY)
                if self.active else None)
        retired = []
        height, width = frame.shape[:2]
        for track in list(self.active.values()):
            self._flow(track, gray, frame, timestamp)
            outside = track.box[2] < 0 or track.box[0] >= width or track.box[3] < 0 or track.box[1] >= height
            if outside or timestamp - track.last_visual > self.settings.track_gap:
                retired.append(self.active.pop(track.id))
        self.previous_gray = gray
        return retired

    def update(self, frame, timestamp, frame_index, detections):
        retired = self.advance(frame, timestamp)
        if self.previous_gray is None:
            self.previous_gray = cv2.cvtColor(cv2.resize(frame, None, fx=self.scale, fy=self.scale), cv2.COLOR_BGR2GRAY)
        gray = self.previous_gray
        groups = self._groups(detections, timestamp, frame_index)
        for group in groups:
            group['histogram'] = appearance(frame, group['box'])
        pairs = []
        for track in self.active.values():
            for group_index, group in enumerate(groups):
                old_size, new_size = size(track.box), size(group['box'])
                ratios = new_size / old_size
                distance = float(np.linalg.norm(center(track.box) - center(group['box'])))
                gate = max(22, 1.6 * max(old_size[0], new_size[0]), 2.0 * max(old_size[1], new_size[1]))
                # Lyhyen peittymisen jälkeen sijaintiennusteen epävarmuus kasvaa.
                elapsed_without_ocr = timestamp - track.last_detection
                gate += min(150, elapsed_without_ocr * max(15, 0.35 * np.linalg.norm(track.velocity)))
                colour = appearance_distance(track.histogram, group['histogram'])
                anchor_colour = appearance_distance(track.anchor_histogram, group['histogram'])
                # Peittyminen voi kaventaa virtauslaatikkoa, ja OCR voi myöhemmin
                # rajata myös lapun logon. Palautuminen sallitaan vain liikkeen
                # suuntaan, sijainti- ja värirajojen sisällä; numerotekstiä ei verrata.
                delta = center(group['box']) - center(track.box)
                recovering = elapsed_without_ocr > 1.0 and np.dot(delta, track.velocity) > 0
                height_limit = 6 if recovering else 4
                if (distance > gate or ratios.min() < 0.2 or ratios[0] > 4
                        or ratios[1] > height_limit or colour > 0.55 or anchor_colour > 0.55
                        or ratios[0] < 0.45 or ratios[1] < 0.45):
                    continue
                cost = distance / gate + 0.25 * (1 - iou(track.box, group['box'])) + 0.5 * colour
                pairs.append((cost, track.id, group_index))
        # Yksi laatikko/seuranta ja yksi seuranta/laatikko. Tekstiä ei lueta kustannusfunktiossa.
        assigned_tracks, assigned_groups = set(), set()
        blocked_tracks, blocked_groups = set(), set()
        parent_ids = {}
        assignments = []
        for cost, track_id, group_index in sorted(pairs):
            if (track_id in assigned_tracks or group_index in assigned_groups
                    or track_id in blocked_tracks or group_index in blocked_groups):
                continue
            alternatives = [(c, t, g) for c, t, g in pairs
                            if t not in assigned_tracks and g not in assigned_groups
                            and t not in blocked_tracks and g not in blocked_groups
                            and ((t == track_id and g != group_index) or (g == group_index and t != track_id))]
            ambiguous = [(c, t, g) for c, t, g in alternatives if abs(c - cost) < 0.12]
            if ambiguous:
                affected_tracks = {track_id} | {t for _, t, _ in ambiguous}
                affected_groups = {group_index} | {g for _, _, g in ambiguous}
                ancestors = set(affected_tracks)
                for t in affected_tracks:
                    ancestors.update(self.active[t].possible_parent_ids)
                event = {'ruutu': frame_index, 'videon_aika_s': timestamp,
                         'ehto': 'liitoskustannusten_ero_alle_rajan', 'raja': 0.12,
                         'valittu': {'seuranta': track_id, 'ryhma': group_index, 'kustannus': cost},
                         'vaihtoehdot': [{'seuranta': t, 'ryhma': g, 'kustannus': c, 'ero': abs(c-cost)}
                                         for c,t,g in ambiguous],
                         'katkaistut_seurannat': sorted(affected_tracks),
                         'toiminto': 'erilliset_todistejaksot_ei_siirreta_havaintoja'}
                self.association_events.append(event)
                for t in affected_tracks:
                    previous = self.active.pop(t)
                    previous.boundary_events.append(event)
                    retired.append(previous)
                for g in affected_groups:
                    parent_ids[g] = ancestors
                blocked_tracks.update(affected_tracks)
                blocked_groups.update(affected_groups)
                continue
            assigned_tracks.add(track_id)
            assigned_groups.add(group_index)
            assignments.append((self.active[track_id], groups[group_index], max(0., 1. - cost / 2)))
        for group_index, group in enumerate(groups):
            if group_index not in assigned_groups:
                track = Track(self.next_id, group['box'], timestamp, timestamp, timestamp,
                              center(group['box']), group['histogram'])
                self.next_id += 1
                track.possible_parent_ids = set(parent_ids.get(group_index, ()))
                if group_index in blocked_groups:
                    track.boundary_events.append({'ruutu': frame_index, 'videon_aika_s': timestamp,
                        'toiminto': 'epavarma_aloitusruutu_ei_vahvistusaaneksi',
                        'mahdolliset_edeltajat': sorted(track.possible_parent_ids)})
                track.anchor_histogram = None if group['histogram'] is None else group['histogram'].copy()
                self.active[track.id] = track
                assignments.append((track, group, 0.0 if group_index in blocked_groups else 1.0))
        added = []
        for track, group, quality in assignments:
            dt = timestamp - track.last_detection
            if dt > 0:
                measured = (center(group['box']) - track.detection_center) / dt
                track.velocity = 0.4 * track.velocity + 0.6 * measured
                c = 0.3 * center(track.box) + 0.7 * center(group['box'])
                wh = 0.6 * size(track.box) + 0.4 * size(group['box'])
                track.box = tuple(np.r_[c - wh / 2, c + wh / 2])
            track.last_detection = track.last_visual = timestamp
            track.detection_center = center(group['box'])
            if track.histogram is None:
                track.histogram = group['histogram']
            elif group['histogram'] is not None:
                track.histogram = 0.8 * track.histogram + 0.2 * group['histogram']
            for observation in group['observations']:
                observation.association_quality = quality
                track.add(observation)
                added.append((track, observation))
            self._seed(track, gray, frame)
        self.previous_gray = gray
        return added, retired

    def finish(self):
        tracks = list(self.active.values())
        self.active.clear()
        return tracks
