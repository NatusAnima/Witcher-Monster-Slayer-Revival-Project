"""Minimal S2 cell geometry (quadratic projection, as in the S2 library) for the spawn service.

The 1.1.116 client asks for monsters, herbs and quest nodes by level-14 S2 cell ids
(GetLocationsByCell 40, LoadCells 88). Only the conversions the server needs are here:
cell id <-> (face, i, j), cell corners and centre, and the leaf cell of a point.
"""
from __future__ import annotations

import math

MAX_LEVEL = 30
POS_BITS = 2 * MAX_LEVEL + 1
SWAP_MASK, INVERT_MASK = 1, 2
POS_TO_IJ = ((0, 1, 3, 2), (0, 2, 3, 1), (3, 2, 0, 1), (3, 1, 0, 2))
IJ_TO_POS = ((0, 1, 3, 2), (0, 3, 1, 2), (2, 3, 1, 0), (2, 1, 3, 0))
POS_TO_ORIENTATION = (SWAP_MASK, 0, 0, INVERT_MASK | SWAP_MASK)


def level(cell_id: int) -> int:
    if not 0 < cell_id < 1 << 64 or cell_id >> POS_BITS > 5:
        raise ValueError("not an S2 cell id")
    trailing = (cell_id & -cell_id).bit_length() - 1
    if trailing % 2:
        raise ValueError("not an S2 cell id")
    return MAX_LEVEL - trailing // 2


def to_face_ij(cell_id: int) -> tuple[int, int, int, int]:
    """Face, i, j at the cell's own level, and that level."""
    lvl = level(cell_id)
    face = cell_id >> POS_BITS
    orientation = face & SWAP_MASK
    i = j = 0
    for k in range(1, lvl + 1):
        pos = (cell_id >> (POS_BITS - 2 * k)) & 3
        ij = POS_TO_IJ[orientation][pos]
        i, j = (i << 1) | (ij >> 1), (j << 1) | (ij & 1)
        orientation ^= POS_TO_ORIENTATION[pos]
    return face, i, j, lvl


def from_face_ij(face: int, i: int, j: int, lvl: int = MAX_LEVEL) -> int:
    """Cell id at level lvl for leaf coordinates i, j in [0, 2**30)."""
    orientation = face & SWAP_MASK
    bits = 0
    for k in range(1, MAX_LEVEL + 1):
        ij = (((i >> (MAX_LEVEL - k)) & 1) << 1) | ((j >> (MAX_LEVEL - k)) & 1)
        pos = IJ_TO_POS[orientation][ij]
        bits = (bits << 2) | pos
        orientation ^= POS_TO_ORIENTATION[pos]
    leaf = (face << POS_BITS) | (bits << 1) | 1
    lsb = 1 << (2 * (MAX_LEVEL - lvl))
    return (leaf & -lsb) | lsb


def _st_to_uv(s: float) -> float:
    return (4 * s * s - 1) / 3 if s >= 0.5 else (1 - 4 * (1 - s) * (1 - s)) / 3


def _uv_to_st(u: float) -> float:
    return 0.5 * math.sqrt(1 + 3 * u) if u >= 0 else 1 - 0.5 * math.sqrt(1 - 3 * u)


def _face_uv_to_xyz(face: int, u: float, v: float) -> tuple[float, float, float]:
    return ((1, u, v), (-u, 1, v), (-u, -v, 1), (-1, -v, -u), (v, -1, -u), (v, u, -1))[face]


def _xyz_to_latlng(x: float, y: float, z: float) -> tuple[float, float]:
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


def _st_to_latlng(face: int, s: float, t: float) -> tuple[float, float]:
    return _xyz_to_latlng(*_face_uv_to_xyz(face, _st_to_uv(s), _st_to_uv(t)))


def corners(cell_id: int) -> list[tuple[float, float]]:
    """The four (lat, lng) corners in S2 vertex order."""
    face, i, j, lvl = to_face_ij(cell_id)
    size = 1 << lvl
    return [_st_to_latlng(face, (i + di) / size, (j + dj) / size) for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1))]


def center(cell_id: int) -> tuple[float, float]:
    face, i, j, lvl = to_face_ij(cell_id)
    size = 1 << lvl
    return _st_to_latlng(face, (i + 0.5) / size, (j + 0.5) / size)


def neighbors(cell_id: int) -> list[int]:
    """Touching cells, including diagonals and wrapping across cube faces."""
    face, i, j, lvl = to_face_ij(cell_id)
    size = 1 << lvl
    return sorted({cell_of(*_st_to_latlng(face, (i + di + 0.5) / size, (j + dj + 0.5) / size), lvl)
                   for di in (-1, 0, 1) for dj in (-1, 0, 1)} - {cell_id})


def cell_of(lat: float, lng: float, lvl: int) -> int:
    phi, theta = math.radians(lat), math.radians(lng)
    x, y, z = math.cos(phi) * math.cos(theta), math.cos(phi) * math.sin(theta), math.sin(phi)
    axis = max(range(3), key=lambda k: abs((x, y, z)[k]))
    face = axis + (3 if (x, y, z)[axis] < 0 else 0)
    u, v = (lambda: (y / x, z / x), lambda: (-x / y, z / y), lambda: (-x / z, -y / z),
            lambda: (z / x, y / x), lambda: (z / y, -x / y), lambda: (-y / z, -x / z))[face]()
    limit = (1 << MAX_LEVEL) - 1
    i = min(limit, max(0, int(_uv_to_st(u) * (1 << MAX_LEVEL))))
    j = min(limit, max(0, int(_uv_to_st(v) * (1 << MAX_LEVEL))))
    return from_face_ij(face, i, j, lvl)
