#!/usr/bin/env python3
"""Polygon clipping, triangulation and Area encoding for 1.1.116 FeatureTiles.

Area wire format recovered from Area.WriteTo/.cctor in the 1.1.116 client:
  2 vertex_offsets (Vertex2DList, packed zigzag x/y deltas across all rings)
  3 type (0 TriangleFan, 1 IndexedTriangles, 2 TriangleStrip)
  4 triangle_indices (packed int32, indices into the vertex list)
  5 z_order (int32)
  6 loop_breaks (packed int32, exclusive end index of each ring)
  7 has_external_edges (bool)
  8 internal_edges (packed int32, vertex i whose edge to the next ring vertex is internal)
Shape.Area appends the final vertex count to loop_breaks when it is missing and links
each ring's last vertex back to its first.

The triangulator is a Python port of mapbox/earcut 2.2.4.
Source: https://github.com/mapbox/earcut/tree/v2.2.4

ISC License

Copyright (c) 2016, Mapbox

Permission to use, copy, modify, and/or distribute this software for any purpose
with or without fee is hereby granted, provided that the above copyright notice
and this permission notice appear in all copies.
THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS
OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER
TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF
THIS SOFTWARE.
"""
from __future__ import annotations

import math

from road_tile_codec import _bytes_field, _packed_sint64_field, _varint, _varint_field

EXTENT = 4096


# --------------------------------------------------------------------------- clipping

def _clip_edge(points, inside, intersect):
    if not points:
        return points
    out = []
    previous = points[-1]
    previous_inside = inside(previous)
    for current in points:
        current_inside = inside(current)
        if current_inside:
            if not previous_inside:
                out.append(intersect(previous, current))
            out.append(current)
        elif previous_inside:
            out.append(intersect(previous, current))
        previous, previous_inside = current, current_inside
    return out


def _x_cut(boundary):
    def cut(a, b):
        t = (boundary - a[0]) / (b[0] - a[0])
        return (boundary, a[1] + t * (b[1] - a[1]))
    return cut


def _y_cut(boundary):
    def cut(a, b):
        t = (boundary - a[1]) / (b[1] - a[1])
        return (a[0] + t * (b[0] - a[0]), boundary)
    return cut


def clip_ring(ring, extent: int = EXTENT):
    """Sutherland-Hodgman clip of one closed ring (without repeated end point) to the tile."""
    points = list(ring)
    points = _clip_edge(points, lambda p: p[0] >= 0, _x_cut(0))
    points = _clip_edge(points, lambda p: p[0] <= extent, _x_cut(extent))
    points = _clip_edge(points, lambda p: p[1] >= 0, _y_cut(0))
    points = _clip_edge(points, lambda p: p[1] <= extent, _y_cut(extent))
    return points


def _ring_area(ring) -> float:
    total = 0.0
    for index, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(index + 1) % len(ring)]
        total += x0 * y1 - x1 * y0
    return total / 2


def tidy_ring(ring, extent: int = EXTENT):
    """Round to integer tile units, drop repeats and collinear-degenerate rings."""
    out = []
    for x, y in ring:
        point = (max(0, min(extent, round(x))), max(0, min(extent, round(y))))
        if not out or out[-1] != point:
            out.append(point)
    while len(out) > 1 and out[0] == out[-1]:
        out.pop()
    if len(out) < 3 or abs(_ring_area(out)) < 1:
        return None
    return out


def ring_bbox_outside(ring, extent: int = EXTENT) -> bool:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return max(xs) < 0 or min(xs) > extent or max(ys) < 0 or min(ys) > extent


def clip_polygon(rings, extent: int = EXTENT):
    """Clip an outer ring and its holes; return tidy integer rings, outer first, or None."""
    if not rings or ring_bbox_outside(rings[0], extent):
        return None
    outer = tidy_ring(clip_ring(rings[0], extent), extent)
    if outer is None:
        return None
    result = [outer]
    for hole in rings[1:]:
        if ring_bbox_outside(hole, extent):
            continue
        clipped = tidy_ring(clip_ring(hole, extent), extent)
        if clipped is not None:
            result.append(clipped)
    return result


# ------------------------------------------------------------------------ earcut port

class _Node:
    __slots__ = ("i", "x", "y", "prev", "next", "z", "prev_z", "next_z", "steiner")

    def __init__(self, i, x, y):
        self.i, self.x, self.y = i, x, y
        self.prev = self.next = None
        self.z = 0
        self.prev_z = self.next_z = None
        self.steiner = False


def earcut(data, hole_indices=None, dim=2):
    """Triangulate a flat coordinate list; returns vertex indices, three per triangle."""
    has_holes = bool(hole_indices)
    outer_len = hole_indices[0] * dim if has_holes else len(data)
    outer_node = _linked_list(data, 0, outer_len, dim, True)
    triangles = []
    if outer_node is None or outer_node.next is outer_node.prev:
        return triangles
    min_x = min_y = inv_size = 0
    if has_holes:
        outer_node = _eliminate_holes(data, hole_indices, outer_node, dim)
    if len(data) > 80 * dim:
        min_x = max_x = data[0]
        min_y = max_y = data[1]
        for i in range(dim, outer_len, dim):
            x, y = data[i], data[i + 1]
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x), max(max_y, y)
        inv_size = max(max_x - min_x, max_y - min_y)
        inv_size = 32767 / inv_size if inv_size != 0 else 0
    _earcut_linked(outer_node, triangles, dim, min_x, min_y, inv_size, 0)
    return triangles


def _linked_list(data, start, end, dim, clockwise):
    last = None
    if clockwise == (_signed_area(data, start, end, dim) > 0):
        for i in range(start, end, dim):
            last = _insert_node(i, data[i], data[i + 1], last)
    else:
        for i in range(end - dim, start - 1, -dim):
            last = _insert_node(i, data[i], data[i + 1], last)
    if last is not None and _equals(last, last.next):
        _remove_node(last)
        last = last.next
    return last


def _filter_points(start, end=None):
    if start is None:
        return start
    if end is None:
        end = start
    p = start
    while True:
        again = False
        if not p.steiner and (_equals(p, p.next) or _area(p.prev, p, p.next) == 0):
            _remove_node(p)
            p = end = p.prev
            if p is p.next:
                break
            again = True
        else:
            p = p.next
        if not again and p is end:
            break
    return end


def _earcut_linked(ear, triangles, dim, min_x, min_y, inv_size, pass_):
    if ear is None:
        return
    if not pass_ and inv_size:
        _index_curve(ear, min_x, min_y, inv_size)
    stop = ear
    while ear.prev is not ear.next:
        prev, nxt = ear.prev, ear.next
        if _is_ear_hashed(ear, min_x, min_y, inv_size) if inv_size else _is_ear(ear):
            triangles.extend((prev.i // dim, ear.i // dim, nxt.i // dim))
            _remove_node(ear)
            ear = nxt.next
            stop = nxt.next
            continue
        ear = nxt
        if ear is stop:
            if not pass_:
                _earcut_linked(_filter_points(ear), triangles, dim, min_x, min_y, inv_size, 1)
            elif pass_ == 1:
                ear = _cure_local_intersections(_filter_points(ear), triangles, dim)
                _earcut_linked(ear, triangles, dim, min_x, min_y, inv_size, 2)
            elif pass_ == 2:
                _split_earcut(ear, triangles, dim, min_x, min_y, inv_size)
            break


def _tri_bbox(a, b, c):
    return (min(a.x, b.x, c.x), min(a.y, b.y, c.y), max(a.x, b.x, c.x), max(a.y, b.y, c.y))


def _is_ear(ear):
    a, b, c = ear.prev, ear, ear.next
    if _area(a, b, c) >= 0:
        return False
    x0, y0, x1, y1 = _tri_bbox(a, b, c)
    p = c.next
    while p is not a:
        if (x0 <= p.x <= x1 and y0 <= p.y <= y1
                and _point_in_triangle(a.x, a.y, b.x, b.y, c.x, c.y, p.x, p.y)
                and _area(p.prev, p, p.next) >= 0):
            return False
        p = p.next
    return True


def _is_ear_hashed(ear, min_x, min_y, inv_size):
    a, b, c = ear.prev, ear, ear.next
    if _area(a, b, c) >= 0:
        return False
    x0, y0, x1, y1 = _tri_bbox(a, b, c)
    min_z = _z_order(x0, y0, min_x, min_y, inv_size)
    max_z = _z_order(x1, y1, min_x, min_y, inv_size)

    def blocks(n):
        return (x0 <= n.x <= x1 and y0 <= n.y <= y1 and n is not a and n is not c
                and _point_in_triangle(a.x, a.y, b.x, b.y, c.x, c.y, n.x, n.y)
                and _area(n.prev, n, n.next) >= 0)

    p, n = ear.prev_z, ear.next_z
    while p is not None and p.z >= min_z and n is not None and n.z <= max_z:
        if blocks(p):
            return False
        p = p.prev_z
        if blocks(n):
            return False
        n = n.next_z
    while p is not None and p.z >= min_z:
        if blocks(p):
            return False
        p = p.prev_z
    while n is not None and n.z <= max_z:
        if blocks(n):
            return False
        n = n.next_z
    return True


def _cure_local_intersections(start, triangles, dim):
    p = start
    while True:
        a, b = p.prev, p.next.next
        if (not _equals(a, b) and _intersects(a, p, p.next, b)
                and _locally_inside(a, b) and _locally_inside(b, a)):
            triangles.extend((a.i // dim, p.i // dim, b.i // dim))
            _remove_node(p)
            _remove_node(p.next)
            p = start = b
        p = p.next
        if p is start:
            break
    return _filter_points(p)


def _split_earcut(start, triangles, dim, min_x, min_y, inv_size):
    a = start
    while True:
        b = a.next.next
        while b is not a.prev:
            if a.i != b.i and _is_valid_diagonal(a, b):
                c = _split_polygon(a, b)
                a = _filter_points(a, a.next)
                c = _filter_points(c, c.next)
                _earcut_linked(a, triangles, dim, min_x, min_y, inv_size, 0)
                _earcut_linked(c, triangles, dim, min_x, min_y, inv_size, 0)
                return
            b = b.next
        a = a.next
        if a is start:
            break


def _eliminate_holes(data, hole_indices, outer_node, dim):
    queue = []
    for index, hole in enumerate(hole_indices):
        start = hole * dim
        end = hole_indices[index + 1] * dim if index < len(hole_indices) - 1 else len(data)
        node = _linked_list(data, start, end, dim, False)
        if node is None:
            continue
        if node is node.next:
            node.steiner = True
        queue.append(_get_leftmost(node))
    queue.sort(key=lambda node: node.x)
    for hole in queue:
        outer_node = _eliminate_hole(hole, outer_node)
    return outer_node


def _eliminate_hole(hole, outer_node):
    bridge = _find_hole_bridge(hole, outer_node)
    if bridge is None:
        return outer_node
    bridge_reverse = _split_polygon(bridge, hole)
    _filter_points(bridge_reverse, bridge_reverse.next)
    return _filter_points(bridge, bridge.next)


def _find_hole_bridge(hole, outer_node):
    p = outer_node
    hx, hy = hole.x, hole.y
    qx = -math.inf
    m = None
    while True:
        if hy <= p.y and hy >= p.next.y and p.next.y != p.y:
            x = p.x + (hy - p.y) * (p.next.x - p.x) / (p.next.y - p.y)
            if hx >= x > qx:
                qx = x
                m = p if p.x < p.next.x else p.next
                if x == hx:
                    return m
        p = p.next
        if p is outer_node:
            break
    if m is None:
        return None
    stop = m
    mx, my = m.x, m.y
    tan_min = math.inf
    p = m
    while True:
        if (hx >= p.x >= mx and hx != p.x and _point_in_triangle(
                hx if hy < my else qx, hy, mx, my, qx if hy < my else hx, hy, p.x, p.y)):
            tan = abs(hy - p.y) / (hx - p.x)
            if _locally_inside(p, hole) and (tan < tan_min or (tan == tan_min and (
                    p.x > m.x or (p.x == m.x and _sector_contains_sector(m, p))))):
                m = p
                tan_min = tan
        p = p.next
        if p is stop:
            break
    return m


def _sector_contains_sector(m, p):
    return _area(m.prev, m, p.prev) < 0 and _area(p.next, m, m.next) < 0


def _index_curve(start, min_x, min_y, inv_size):
    p = start
    while True:
        if p.z == 0:
            p.z = _z_order(p.x, p.y, min_x, min_y, inv_size)
        p.prev_z = p.prev
        p.next_z = p.next
        p = p.next
        if p is start:
            break
    p.prev_z.next_z = None
    p.prev_z = None
    _sort_linked(p)


def _sort_linked(lst):
    in_size = 1
    while True:
        p = lst
        lst = tail = None
        num_merges = 0
        while p is not None:
            num_merges += 1
            q = p
            p_size = 0
            for _ in range(in_size):
                p_size += 1
                q = q.next_z
                if q is None:
                    break
            q_size = in_size
            while p_size > 0 or (q_size > 0 and q is not None):
                if p_size != 0 and (q_size == 0 or q is None or p.z <= q.z):
                    e, p = p, p.next_z
                    p_size -= 1
                else:
                    e, q = q, q.next_z
                    q_size -= 1
                if tail is not None:
                    tail.next_z = e
                else:
                    lst = e
                e.prev_z = tail
                tail = e
            p = q
        tail.next_z = None
        in_size *= 2
        if num_merges <= 1:
            return lst


def _spread(v):
    v = (v | (v << 8)) & 0x00FF00FF
    v = (v | (v << 4)) & 0x0F0F0F0F
    v = (v | (v << 2)) & 0x33333333
    return (v | (v << 1)) & 0x55555555


def _z_order(x, y, min_x, min_y, inv_size):
    return _spread(int((x - min_x) * inv_size)) | (_spread(int((y - min_y) * inv_size)) << 1)


def _get_leftmost(start):
    p = leftmost = start
    while True:
        if p.x < leftmost.x or (p.x == leftmost.x and p.y < leftmost.y):
            leftmost = p
        p = p.next
        if p is start:
            return leftmost


def _point_in_triangle(ax, ay, bx, by, cx, cy, px, py):
    return ((cx - px) * (ay - py) >= (ax - px) * (cy - py)
            and (ax - px) * (by - py) >= (bx - px) * (ay - py)
            and (bx - px) * (cy - py) >= (cx - px) * (by - py))


def _is_valid_diagonal(a, b):
    return (a.next.i != b.i and a.prev.i != b.i and not _intersects_polygon(a, b)
            and ((_locally_inside(a, b) and _locally_inside(b, a) and _middle_inside(a, b)
                  and (_area(a.prev, a, b.prev) or _area(a, b.prev, b)))
                 or (_equals(a, b) and _area(a.prev, a, a.next) > 0 and _area(b.prev, b, b.next) > 0)))


def _area(p, q, r):
    return (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y)


def _equals(p1, p2):
    return p1.x == p2.x and p1.y == p2.y


def _sign(value):
    return (value > 0) - (value < 0)


def _on_segment(p, q, r):
    return min(p.x, r.x) <= q.x <= max(p.x, r.x) and min(p.y, r.y) <= q.y <= max(p.y, r.y)


def _intersects(p1, q1, p2, q2):
    o1 = _sign(_area(p1, q1, p2))
    o2 = _sign(_area(p1, q1, q2))
    o3 = _sign(_area(p2, q2, p1))
    o4 = _sign(_area(p2, q2, q1))
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_segment(p1, p2, q1):
        return True
    if o2 == 0 and _on_segment(p1, q2, q1):
        return True
    if o3 == 0 and _on_segment(p2, p1, q2):
        return True
    if o4 == 0 and _on_segment(p2, q1, q2):
        return True
    return False


def _intersects_polygon(a, b):
    p = a
    while True:
        if (p.i != a.i and p.next.i != a.i and p.i != b.i and p.next.i != b.i
                and _intersects(p, p.next, a, b)):
            return True
        p = p.next
        if p is a:
            return False


def _locally_inside(a, b):
    if _area(a.prev, a, a.next) < 0:
        return _area(a, b, a.next) >= 0 and _area(a, a.prev, b) >= 0
    return _area(a, b, a.prev) < 0 or _area(a, a.next, b) < 0


def _middle_inside(a, b):
    p = a
    inside = False
    px, py = (a.x + b.x) / 2, (a.y + b.y) / 2
    while True:
        if (((p.y > py) != (p.next.y > py)) and p.next.y != p.y
                and px < (p.next.x - p.x) * (py - p.y) / (p.next.y - p.y) + p.x):
            inside = not inside
        p = p.next
        if p is a:
            return inside


def _split_polygon(a, b):
    a2 = _Node(a.i, a.x, a.y)
    b2 = _Node(b.i, b.x, b.y)
    an, bp = a.next, b.prev
    a.next, b.prev = b, a
    a2.next, an.prev = an, a2
    b2.next, a2.prev = a2, b2
    bp.next, b2.prev = b2, bp
    return b2


def _insert_node(i, x, y, last):
    p = _Node(i, x, y)
    if last is None:
        p.prev = p.next = p
    else:
        p.next = last.next
        p.prev = last
        last.next.prev = p
        last.next = p
    return p


def _remove_node(p):
    p.next.prev = p.prev
    p.prev.next = p.next
    if p.prev_z is not None:
        p.prev_z.next_z = p.next_z
    if p.next_z is not None:
        p.next_z.prev_z = p.prev_z


def _signed_area(data, start, end, dim):
    total = 0
    j = end - dim
    for i in range(start, end, dim):
        total += (data[j] - data[i]) * (data[i + 1] + data[j + 1])
        j = i
    return total


# ----------------------------------------------------------------------- encoding

def _packed_int32(field: int, values) -> bytes:
    payload = b"".join(_varint(v) for v in values)
    return _bytes_field(field, payload)


def _on_same_border(a, b, extent: int = EXTENT) -> bool:
    return ((a[0] == b[0] and a[0] in (0, extent)) or (a[1] == b[1] and a[1] in (0, extent)))


def encode_area(rings, z_order: int = 0, extent: int = EXTENT,
                external_edges: bool = True) -> bytes | None:
    """Encode tidy integer rings (outer first) as an IndexedTriangles Area message.

    With external_edges=False the area carries no boundary flags, so the client builds
    only the fill mesh and no outline along the shore.
    """
    flat, breaks, vertices = [], [], []
    for ring in rings:
        vertices.extend(ring)
        for x, y in ring:
            flat.extend((x, y))
        breaks.append(len(vertices))
    holes = breaks[:-1]
    triangles = earcut(flat, holes)
    if not triangles:
        return None
    x_offsets, y_offsets = [], []
    previous_x = previous_y = 0
    for x, y in vertices:
        x_offsets.append(x - previous_x)
        y_offsets.append(y - previous_y)
        previous_x, previous_y = x, y
    internal = []
    start = 0
    for end in breaks:
        for index in range(start, end):
            following = index + 1 if index + 1 < end else start
            if _on_same_border(vertices[index], vertices[following], extent):
                internal.append(index)
        start = end
    area = _bytes_field(2, _packed_sint64_field(1, tuple(x_offsets)) +
                        _packed_sint64_field(2, tuple(y_offsets)))
    area += _varint_field(3, 1)  # IndexedTriangles
    area += _packed_int32(4, triangles)
    if z_order:
        area += _varint_field(5, z_order)
    area += _packed_int32(6, breaks)
    if external_edges:
        area += _varint_field(7, 1)  # has_external_edges
        if internal:
            area += _packed_int32(8, internal)
    return area


def encode_extruded_area(area: bytes, min_z: int = 0, max_z: int = 0) -> bytes:
    """ExtrudedArea {1 area, 2 min_z, 3 max_z}; equal heights make the client use 10 m."""
    out = _bytes_field(1, area)
    if min_z:
        out += _varint_field(2, min_z)
    if max_z:
        out += _varint_field(3, max_z)
    return out
