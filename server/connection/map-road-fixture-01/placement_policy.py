"""Bounded, daily placement schedules. No coordinates or file contents are logged."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import threading
import time

DEFAULT = dict(maxPoints=24, spacingMeters=50, exclusions=[], preferred=[])
MAX_VERSIONS = 128


def policy(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT):
        raise ValueError("placement policy fields")
    for key, low, high in (("maxPoints", 8, 64), ("spacingMeters", 35, 120)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("placement policy bounds")
    for key, maximum in (("exclusions", 32), ("preferred", 64)):
        rows = value[key]
        if not isinstance(rows, list) or len(rows) > maximum:
            raise ValueError("placement control count")
        for row in rows:
            fields = {"id", "lat", "lng"} | ({"radiusMeters"} if key == "exclusions" else set())
            if not isinstance(row, dict) or set(row) != fields:
                raise ValueError("placement control fields")
            if not isinstance(row["id"], str) or not 1 <= len(row["id"]) <= 48 \
                    or any(not (c.isascii() and (c.isalnum() or c in "-_")) for c in row["id"]):
                raise ValueError("placement control id")
            for coordinate, bound in (("lat", 85), ("lng", 180)):
                n = row[coordinate]
                if type(n) not in (int, float) or not math.isfinite(n) or abs(n) > bound:
                    raise ValueError("placement coordinates")
            if key == "exclusions" and (type(row["radiusMeters"]) is not int or not 10 <= row["radiusMeters"] <= 1000):
                raise ValueError("placement radius")
        if len({row["id"] for row in rows}) != len(rows):
            raise ValueError("duplicate placement control")
    return copy.deepcopy(value)


def schedule(value):
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "versions"} or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ValueError("placement schedule schema")
    versions = value["versions"]
    if not isinstance(versions, list) or len(versions) > MAX_VERSIONS:
        raise ValueError("placement schedule history")
    previous = 0
    for row in versions:
        if not isinstance(row, dict) or set(row) != {"fromEpoch", "policy"} \
                or type(row["fromEpoch"]) is not int or not previous < row["fromEpoch"] <= 365000:
            raise ValueError("placement schedule order")
        policy(row["policy"])
        previous = row["fromEpoch"]
    return copy.deepcopy(value)


class PolicyStore:
    def __init__(self, path: Path | None):
        self.path = path
        self.lock = threading.RLock()
        self.value = {"schemaVersion": 1, "versions": []}
        self.revision = "missing"
        self.error = False
        self.refresh(initial=True)

    def refresh(self, initial=False):
        with self.lock:
            try:
                raw = self.path.read_bytes() if self.path and self.path.exists() else None
                if raw is None and self.revision != "missing":
                    raise ValueError("placement schedule disappeared")
                digest = hashlib.sha256(raw).hexdigest() if raw is not None else "missing"
                if digest != self.revision:
                    if len(raw) > 1024 * 1024:
                        raise ValueError("placement schedule size")
                    self.value = schedule(json.loads(raw))
                    self.revision = digest
                self.error = False
            except (OSError, ValueError, TypeError):
                self.error = True
                if initial:
                    raise ValueError("placement schedule unavailable or invalid") from None

    def at(self, epoch):
        with self.lock:
            for row in reversed(self.value["versions"]):
                if row["fromEpoch"] <= epoch:
                    return row["fromEpoch"], copy.deepcopy(row["policy"])
            return 0, copy.deepcopy(DEFAULT)

    def status(self):
        self.refresh()
        with self.lock:
            today = int(time.time() // 86400)
            effective_epoch, effective = self.at(today)
            versions = self.value["versions"]
            desired = versions[-1]["policy"] if versions else DEFAULT
            return dict(enabled=self.path is not None, revision=self.revision,
                        document=copy.deepcopy(desired), effective=effective,
                        effectiveEpoch=effective_epoch, nextEpoch=today + 1,
                        scheduledEpoch=versions[-1]["fromEpoch"] if versions and versions[-1]["fromEpoch"] > today else None,
                        status="invalid-retaining-last-good" if self.error else "ready",
                        historyCount=len(versions), historyLimit=MAX_VERSIONS)
