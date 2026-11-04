"""Bounded, daily placement schedules and the nemeton spots. No coordinates or file contents are logged."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time

import s2cells

DEFAULT = dict(maxPoints=24, spacingMeters=50, exclusions=[], preferred=[])
MAX_VERSIONS = 128
MAX_NEMETON_PINS = 512
MAX_NEMETON_REMOVED = 4096


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


def nemeton_pins(value, cell_level):
    """The dashboard's nemeton document, checked and normalised: a pin stands at exact coordinates and names its cell, one
    pin to a cell; a removed cell has no nemeton. A pin wins over a removal of its own cell (moving a nemeton inside it)."""
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "pins", "removed"} or type(value["schemaVersion"]) is not int \
            or value["schemaVersion"] != 1:
        raise ValueError("nemeton pins schema")
    pins, removed = value["pins"], value["removed"]
    if not isinstance(pins, list) or len(pins) > MAX_NEMETON_PINS or not isinstance(removed, list) or len(removed) > MAX_NEMETON_REMOVED:
        raise ValueError("nemeton pins count")
    rows, cells, ids = [], set(), set()
    for row in pins:
        if not isinstance(row, dict) or not {"id", "lat", "lng"} <= set(row) <= {"id", "lat", "lng", "cell"}:
            raise ValueError("nemeton pin fields")
        if not isinstance(row["id"], str) or not 1 <= len(row["id"]) <= 48 or row["id"] in ids \
                or any(not (c.isascii() and (c.isalnum() or c in "-_")) for c in row["id"]):
            raise ValueError("nemeton pin id")
        for coordinate, bound in (("lat", 85), ("lng", 180)):
            n = row[coordinate]
            if type(n) not in (int, float) or not math.isfinite(n) or abs(n) > bound:
                raise ValueError("nemeton pin coordinates")
        cell = s2cells.cell_of(row["lat"], row["lng"], cell_level)
        if cell in cells:
            raise ValueError("two nemeton pins in one cell")
        cells.add(cell); ids.add(row["id"])
        rows.append(dict(id=row["id"], lat=round(row["lat"], 6), lng=round(row["lng"], 6), cell=str(cell)))
    gone = set()
    for text in removed:
        if not isinstance(text, str) or not text.isascii() or not text.isdigit() or len(text) > 20 \
                or s2cells.level(int(text)) != cell_level:
            raise ValueError("removed nemeton cell")
        gone.add(int(text))
    return dict(schemaVersion=1, pins=rows, removed=[str(c) for c in sorted(gone - cells)])


class NemetonPins:
    """The dashboard's pins and removals (world/nemeton-pins.json, written by the admin API), read again whenever the file
    changes. A damaged file keeps the last good one, as the placement schedule does."""

    def __init__(self, path: Path | None, cell_level: int):
        self.path, self.cell_level = path, cell_level
        self.lock = threading.Lock()
        self.revision, self.error = "missing", False
        self.pins, self.removed = {}, set()
        self.refresh()

    def refresh(self):
        if self.path is None:
            return
        with self.lock:
            try:
                raw = self.path.read_bytes() if self.path.exists() else None
                digest = hashlib.sha256(raw).hexdigest() if raw is not None else "missing"
                if digest != self.revision:
                    if raw is not None and len(raw) > 1024 * 1024:
                        raise ValueError("nemeton pins size")
                    value = nemeton_pins(json.loads(raw), self.cell_level) if raw is not None else dict(pins=[], removed=[])
                    self.pins = {int(row["cell"]): row for row in value["pins"]}
                    self.removed = {int(cell) for cell in value["removed"]}
                    self.revision = digest
                self.error = False
            except (OSError, ValueError, TypeError):
                self.error = True

    def pin(self, cell_id):
        with self.lock:
            return self.pins.get(cell_id)

    def is_removed(self, cell_id):
        with self.lock:
            return cell_id in self.removed


class NemetonSpots:
    """Where each cell's nemeton stands, once decided: world/nemeton-spots.json, written only by the placement service.
    A spot is drawn from the map, the dashboard's numbers and this code, and any of those can change, so the first answer is
    kept (a cell's "no nemeton" too). Without a path nothing is kept and each answer is drawn again."""

    def __init__(self, path: Path | None):
        self.path = path
        self.lock = threading.Lock()
        self.cells, self.dirty = {}, False
        if path is None or not path.exists():
            return
        try:
            value = json.loads(path.read_bytes())
            if value["schemaVersion"] != 1:
                raise ValueError("nemeton spots schema")
            self.cells = {int(cell): spot for cell, spot in value["cells"].items()}
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            # Writes are atomic, so this is outside damage: keep the file for a person to look at and start again.
            try:
                os.replace(path, path.with_name(path.name + ".damaged"))
            except OSError:
                pass

    def get(self, cell_id):
        """(whether the cell is decided, its spot or None)."""
        with self.lock:
            return cell_id in self.cells, self.cells.get(cell_id)

    def put(self, cell_id, spot):
        if self.path is None:
            return
        with self.lock:
            self.cells[cell_id] = spot
            self.dirty = True

    def flush(self):
        with self.lock:
            if not self.dirty:
                return
            body = json.dumps({"schemaVersion": 1, "cells": {str(c): s for c, s in sorted(self.cells.items())}},
                              separators=(",", ":")).encode()
            temporary = self.path.with_name(self.path.name + ".tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(temporary, "wb") as file:
                    file.write(body)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.path)
                self.dirty = False
            except OSError:
                pass  # still in memory; the next new spot tries again
