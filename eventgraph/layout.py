"""Renderer-independent, deterministic 3D layout for partially ordered events."""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite, sqrt
from types import MappingProxyType

from .errors import ValidationError
from .graph import EventGraph
from .models import InputKind
from .ordering import rank_events


@dataclass(frozen=True)
class Relation:
    source: str
    target: str
    result_id: str
    kind: InputKind
    target_role: str | None


@dataclass(frozen=True)
class Relations:
    ranks: Mapping[str, int]
    links: tuple[Relation, ...]

    def __post_init__(self):
        object.__setattr__(self, "ranks", MappingProxyType(dict(self.ranks)))
        object.__setattr__(self, "links", tuple(self.links))


def analyze_graph(graph: EventGraph) -> Relations:
    """Keep every business link; only triggers and separated windows set ranks."""
    links = tuple(
        Relation(graph.results[c.source_result].event_id, c.target_event,
                 c.source_result, c.kind, c.target_role)
        for c in sorted(graph.connections, key=lambda c: (c.source_result, c.target_event))
    )
    ranks = rank_events(graph.events, (
        (link.source, link.target) for link in links if link.kind is InputKind.TRIGGER
    ))
    return Relations(ranks, links)


@dataclass(frozen=True)
class Position:
    x: float
    y: float
    z: float
    rank: int


@dataclass(frozen=True)
class Layout:
    positions: Mapping[str, Position]
    relations: Relations
    node_spacing: float
    layer_spacing: float

    def __post_init__(self):
        object.__setattr__(self, "positions", MappingProxyType(dict(self.positions)))

    def to_dict(self) -> dict:
        """A JSON-safe geometry snapshot. Join nodes to source JSON by event ID."""
        return {
            "version": 1,
            "axis": "y",
            "node_spacing": self.node_spacing,
            "layer_spacing": self.layer_spacing,
            "nodes": [
                {"id": name, "rank": p.rank, "x": p.x, "y": p.y, "z": p.z}
                for name, p in sorted(self.positions.items())
            ],
            "links": [
                {"source": link.source, "target": link.target, "result_id": link.result_id,
                 "kind": link.kind.value, "target_role": link.target_role}
                for link in self.relations.links
            ],
        }


def _number(value: float, name: str) -> float:
    try:
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValidationError(f"{name} must be a positive finite number")
    return float(value)


def _point(slot: tuple[int, int], spacing: float) -> tuple[float, float]:
    q, r = slot
    return spacing * (q + r / 2), spacing * sqrt(3) / 2 * r


def _cell(x: float, z: float, spacing: float) -> tuple[int, int]:
    r = z / (spacing * sqrt(3) / 2)
    return round(x / spacing - r / 2), round(r)


def _ring(center: tuple[int, int], radius: int):
    if radius == 0:
        yield center
        return
    q, r = center[0] - radius, center[1] + radius
    for dq, dr in ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)):
        for _ in range(radius):
            yield q, r
            q, r = q + dq, r + dr


def _seat(x: float, z: float, occupied: set, spacing: float) -> tuple[int, int]:
    center = _cell(x, z, spacing)
    radius = 0
    while True:
        free = [slot for slot in _ring(center, radius) if slot not in occupied]
        if free:
            return min(free, key=lambda slot: (_distance(slot, x, z, spacing), slot))
        radius += 1


def _distance(slot: tuple[int, int], x: float, z: float, spacing: float) -> float:
    px, pz = _point(slot, spacing)
    return (px - x) ** 2 + (pz - z) ** 2


def layout_graph(
    graph: EventGraph, *, node_spacing: float = 3.0, layer_spacing: float = 5.0,
    sweeps: int = 6, previous: Layout | None = None,
) -> Layout:
    """Layered hexagonal packing with weighted neighbor attraction.

    Y encodes precedence rank, never physical time. Hexagonal seats guarantee
    center separation; barycentric relaxation favors short local connections.
    Existing X/Z positions stay fixed when a compatible previous layout is
    supplied, except when a changed rank would put two nodes in the same seat.
    This is a bounded heuristic, not a global crossing or beauty optimizer.
    """
    spacing = _number(node_spacing, "node_spacing")
    gap = _number(layer_spacing, "layer_spacing")
    if gap < spacing:
        raise ValidationError("layer_spacing must be at least node_spacing")
    if type(sweeps) is not int or not 0 <= sweeps <= 100:
        raise ValidationError("sweeps must be an integer between 0 and 100")
    if previous is not None and not isinstance(previous, Layout):
        raise ValidationError("previous must be a Layout")
    if previous is not None and previous.node_spacing != spacing:
        raise ValidationError("previous layout has a different node_spacing; omit it to relayout")
    relations = analyze_graph(graph)
    ranks = relations.ranks
    order = sorted(ranks, key=lambda name: (ranks[name], name))
    neighbors: dict[str, dict[str, float]] = {name: {} for name in order}
    for link in relations.links:
        if link.source == link.target:
            continue
        weight = 1.0 if link.kind is InputKind.TRIGGER else 0.25
        # Multiple ports between the same events do not dominate the geometry.
        for left, right in ((link.source, link.target), (link.target, link.source)):
            neighbors[left][right] = max(weight, neighbors[left].get(right, 0))
    occupied: dict[int, set[tuple[int, int]]] = defaultdict(set)
    slots: dict[str, tuple[int, int]] = {}
    fixed: set[str] = set()

    if previous is not None:
        existing = [name for name in order if name in previous.positions]
        existing.sort(key=lambda name: (previous.positions[name].rank != ranks[name], name))
        for name in existing:
            p = previous.positions[name]
            if not isfinite(p.x) or not isfinite(p.z):
                raise ValidationError("previous positions must be finite")
            slot = _seat(p.x / spacing, p.z / spacing, occupied[ranks[name]], 1.0)
            slots[name] = slot
            occupied[ranks[name]].add(slot)
            fixed.add(name)

    def target(name: str) -> tuple[float, float]:
        # A small origin pull keeps isolated components compact.
        x = z = 0.0
        total = 0.05
        for neighbor, weight in sorted(neighbors[name].items()):
            if neighbor in slots:
                px, pz = _point(slots[neighbor], 1.0)
                x += weight * px
                z += weight * pz
                total += weight
        return x / total, z / total

    for name in order:
        if name not in slots:
            x, z = target(name)
            slot = _seat(x, z, occupied[ranks[name]], 1.0)
            slots[name] = slot
            occupied[ranks[name]].add(slot)
    movable = [name for name in order if name not in fixed]
    for sweep in range(sweeps):
        moved = False
        for name in movable if sweep % 2 == 0 else reversed(movable):
            old = slots[name]
            occupied[ranks[name]].remove(old)
            x, z = target(name)
            candidate = _seat(x, z, occupied[ranks[name]], 1.0)
            if _distance(candidate, x, z, 1.0) + 1e-9 < _distance(old, x, z, 1.0):
                slots[name] = candidate
                moved = True
            occupied[ranks[name]].add(slots[name])
        if not moved:
            break
    positions = {}
    for name in sorted(slots):
        x, z = _point(slots[name], 1.0)
        x, z = x * spacing, z * spacing
        y = ranks[name] * gap
        if not all(map(isfinite, (x, y, z))):
            raise ValidationError("layout coordinates overflow; reduce spacing")
        positions[name] = Position(x, y, z, ranks[name])
    return Layout(positions, relations, spacing, gap)
