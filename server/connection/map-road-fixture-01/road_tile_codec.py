#!/usr/bin/env python3
"""Build a synthetic road FeatureTile for a bounded 1.1.116 renderer probe.

This is a narrow wire-compatible subset, not an OSM importer or a complete map
implementation. It intentionally uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FEATURE_TYPES = (
    ("Segment", 2),
    ("Road", 33),
    ("LocalRoad", 530),
    ("ArterialRoad", 531),
    ("Highway", 532),
    ("ControlledAccessHighway", 8513),
    ("Footpath", 34),
)
TILE_NAME = "tiles/@1,2,3z"
TILE_COORDINATES = (1, 2, 3)  # Deliberately invented test values.
VERSION_ID = "lab-road-fixture-01"


def _varint(value: int) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < (1 << 64):
        raise ValueError("varint value must be an unsigned 64-bit integer")
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _tag(field_number: int, wire_type: int) -> bytes:
    if not 1 <= field_number < (1 << 29) or wire_type not in (0, 1, 2, 5):
        raise ValueError("invalid protobuf field tag")
    return _varint((field_number << 3) | wire_type)


def _varint_field(field_number: int, value: int) -> bytes:
    return _tag(field_number, 0) + _varint(value)


def _bytes_field(field_number: int, payload: bytes) -> bytes:
    return _tag(field_number, 2) + _varint(len(payload)) + payload


def _string_field(field_number: int, value: str) -> bytes:
    return _bytes_field(field_number, value.encode("utf-8"))


def _zigzag64(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not -(1 << 63) <= value < (1 << 63):
        raise ValueError("sint64 value is outside its valid range")
    return (value << 1) ^ (value >> 63)


def _packed_sint64_field(field_number: int, values: tuple[int, ...]) -> bytes:
    packed = b"".join(_varint(_zigzag64(value)) for value in values)
    return _bytes_field(field_number, packed)


def _tile_coordinates() -> bytes:
    x, y, zoom = TILE_COORDINATES
    return _varint_field(1, x) + _varint_field(2, y) + _varint_field(3, zoom)


def _vertex_offsets(points: tuple[tuple[int, int], ...]) -> bytes:
    if len(points) < 2:
        raise ValueError("a road line needs at least two points")
    if any(not (0 <= x <= 4096 and 0 <= y <= 4096) for x, y in points):
        raise ValueError("test points must lie within the 4096-unit tile")
    x_offsets, y_offsets = [], []
    previous_x = previous_y = 0
    for x, y in points:
        x_offsets.append(x - previous_x)
        y_offsets.append(y - previous_y)
        previous_x, previous_y = x, y
    return _packed_sint64_field(1, tuple(x_offsets)) + _packed_sint64_field(2, tuple(y_offsets))


def _road_feature(feature_type: int, points: tuple[tuple[int, int], ...]) -> bytes:
    line = _bytes_field(1, _vertex_offsets(points))  # Line.vertex_offsets
    geometry = _bytes_field(2, line)  # Geometry.lines
    feature = _varint_field(2, feature_type) + _bytes_field(3, geometry)
    if feature_type == 2:  # SegmentInfo is defined for Segment features.
        feature += _bytes_field(6, _bytes_field(1, b""))  # road_info, not private
    return feature


def build_road_probe_tile() -> bytes:
    """Return one invented tile with a separate line for each candidate road type."""
    features = []
    first_y = 384
    for index, (_name, feature_type) in enumerate(FEATURE_TYPES):
        y = first_y + index * 512
        points = ((128, y), (2048, y + 64), (3968, y))
        features.append(_bytes_field(3, _road_feature(feature_type, points)))

    # Provider text is explicit test attribution, not an OSM attribution claim.
    provider = _bytes_field(5, _string_field(1, "Synthetic LAB road fixture"))
    tile = _string_field(1, TILE_NAME)
    tile += _bytes_field(2, _tile_coordinates())
    tile += b"".join(features)
    tile += provider
    tile += _string_field(9, VERSION_ID)
    return tile


def manifest() -> dict[str, object]:
    raw = build_road_probe_tile()
    return {
        "status": "SYNTHETIC_ROAD_TILE_NOT_RENDERER_VALIDATED",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "tile_coordinates": "invented (1,2,3); no device or location input",
        "feature_types": [{"name": name, "enum_value": value} for name, value in FEATURE_TYPES],
        "feature_count": len(FEATURE_TYPES),
        "local_geometry_scale": 4096,
        "terrain": "not included; the separate flat terrain fixture remains unchanged",
        "provider": "Synthetic LAB road fixture",
        "scope": "FeatureTile/Feature/Geometry/Line/Vertex2DList subset only",
        "client_execution": False,
        "rendering_verified": False,
        "osm_source_data": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = build_road_probe_tile()
    if args.output:
        if args.output.exists():
            raise SystemExit("Choose a fresh output path.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(raw)
    print(json.dumps(manifest(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
