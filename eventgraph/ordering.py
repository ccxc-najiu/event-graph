"""Sparse precedence constraints. Optional influences never impose an order."""

from bisect import bisect_left
from collections.abc import Iterable, Mapping
from heapq import heapify, heappop, heappush

from .errors import ValidationError
from .models import Event


def rank_events(
    events: Mapping[str, Event], triggers: Iterable[tuple[str, str]],
) -> dict[str, int]:
    """Longest-path ranks for trigger and strictly separated window constraints.

    A gate per distinct finite end time aggregates a prefix of finished windows.
    This represents every end(A) < start(B) constraint with O(V) edges rather
    than materializing O(V²) event pairs. Gates do not become visual nodes.
    """
    names = sorted(events)
    index = {name: i for i, name in enumerate(names)}
    ends = sorted({e.time.end for e in events.values() if e.time.end is not None})
    gates = {end: len(names) + i for i, end in enumerate(ends)}
    edges: list[dict[int, int]] = [{} for _ in range(len(names) + len(ends))]
    for source, target in triggers:
        edges[index[source]][index[target]] = 1
    for left, right in zip(ends, ends[1:]):
        edges[gates[left]][gates[right]] = 0
    for name in names:
        window = events[name].time
        if window.end is not None:
            edges[index[name]][gates[window.end]] = 1
        if window.start is not None:
            pos = bisect_left(ends, window.start) - 1
            if pos >= 0:
                edges[gates[ends[pos]]][index[name]] = 0

    indegree = [0] * len(edges)
    for outgoing in edges:
        for target in outgoing:
            indegree[target] += 1
    ready = [i for i, degree in enumerate(indegree) if degree == 0]
    heapify(ready)
    ranks = [0] * len(edges)
    count = 0
    while ready:
        source = heappop(ready)
        count += 1
        for target, distance in edges[source].items():
            ranks[target] = max(ranks[target], ranks[source] + distance)
            indegree[target] -= 1
            if indegree[target] == 0:
                heappush(ready, target)
    if count != len(edges):
        labels = names + [f"[window end ≤ {end}]" for end in ends]
        cycle = _find_cycle(edges)
        raise ValidationError("precedence cycle: " + " -> ".join(labels[i] for i in cycle))
    return {name: ranks[index[name]] for name in names}


def _find_cycle(edges: list[dict[int, int]]) -> list[int]:
    """Iterative DFS returns an actual cycle, not downstream blocked nodes."""
    done: set[int] = set()
    for root in range(len(edges)):
        if root in done:
            continue
        path = [root]
        active = {root: 0}
        stack = [iter(edges[root])]
        while stack:
            target = next(stack[-1], None)
            if target is None:
                stack.pop()
                done.add(path.pop())
                active.popitem()
            elif target in active:
                return path[active[target]:] + [target]
            elif target not in done:
                active[target] = len(path)
                path.append(target)
                stack.append(iter(edges[target]))
    return []
