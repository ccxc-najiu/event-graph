"""Versioned JSON definitions shared by import, layout, and future editors."""

import json
from typing import Any

from .errors import ValidationError
from .flows import TableFlow, UnconfiguredFlow
from .graph import EventGraph
from .models import Connection, Event, Result, TimeWindow


def _object(value: Any, path: str, allowed: set[str], required=()) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{path}: expected an object")
    missing = set(required) - value.keys()
    extra = value.keys() - allowed
    if missing or extra:
        raise ValidationError(f"{path}: missing fields {sorted(missing)}, unknown fields {sorted(extra, key=str)}")
    return value


def _array(value: Any, path: str) -> list:
    if not isinstance(value, list):
        raise ValidationError(f"{path}: expected an array")
    return value


def _string(value: Any, path: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValidationError(f"{path}: expected {'a' if empty else 'a non-empty'} string")
    return value


def _ids(value: Any, path: str) -> list[str]:
    result = [_string(item, f"{path}[{i}]") for i, item in enumerate(_array(value, path))]
    if len(result) != len(set(result)):
        raise ValidationError(f"{path}: duplicate IDs")
    return result


def _flow(value: Any, path: str) -> TableFlow:
    data = _object(value, path, {"type", "cases", "default", "input_domain"}, ("type",))
    if data["type"] != "table":
        raise ValidationError(f"{path}.type: only 'table' is supported")
    cases = {}
    for i, item in enumerate(_array(data.get("cases", []), f"{path}.cases")):
        at = f"{path}.cases[{i}]"
        row = _object(item, at, {"inputs", "outputs"}, ("inputs", "outputs"))
        key = frozenset(_ids(row["inputs"], f"{at}.inputs"))
        if key in cases:
            raise ValidationError(f"{at}.inputs: duplicate input combination")
        cases[key] = _ids(row["outputs"], f"{at}.outputs")
    default = data.get("default")
    if default is not None:
        default = _ids(default, f"{path}.default")
    domain = data.get("input_domain")
    if domain is not None:
        domain = [_ids(item, f"{path}.input_domain[{i}]")
                  for i, item in enumerate(_array(domain, f"{path}.input_domain"))]
        if len(domain) != len({frozenset(item) for item in domain}):
            raise ValidationError(f"{path}.input_domain: duplicate input combination")
    return TableFlow(cases, default=default, input_domain=domain)


def graph_from_dict(value: dict) -> EventGraph:
    """Parse definitions without mutating input. Omitted flows are non-executable."""
    data = _object(value, "$", {"version", "events", "results", "connections"}, ("version", "events"))
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValidationError("$.version: expected integer 1")
    events = []
    for i, item in enumerate(_array(data["events"], "$.events")):
        path = f"$.events[{i}]"
        row = _object(item, path, {"id", "description", "roles", "locations", "time", "flow"}, ("id",))
        window = _object(row.get("time", {}), f"{path}.time", {"start", "end"})
        try:
            time = TimeWindow(window.get("start"), window.get("end"))
        except (ValidationError, OverflowError) as exc:
            raise ValidationError(f"{path}.time: {exc}") from exc
        events.append(Event(
            _string(row["id"], f"{path}.id"),
            tuple(_ids(row.get("roles", []), f"{path}.roles")),
            _flow(row["flow"], f"{path}.flow") if "flow" in row else UnconfiguredFlow(),
            time,
            frozenset(_ids(row.get("locations", []), f"{path}.locations")),
            _string(row.get("description", ""), f"{path}.description", empty=True),
        ))
    results = []
    for i, item in enumerate(_array(data.get("results", []), "$.results")):
        path = f"$.results[{i}]"
        row = _object(item, path, {"id", "event_id", "recipient_roles", "description"}, ("id", "event_id"))
        results.append(Result(
            _string(row["id"], f"{path}.id"),
            _string(row["event_id"], f"{path}.event_id"),
            tuple(_ids(row.get("recipient_roles", []), f"{path}.recipient_roles")),
            _string(row.get("description", ""), f"{path}.description", empty=True),
        ))
    connections = []
    for i, item in enumerate(_array(data.get("connections", []), "$.connections")):
        path = f"$.connections[{i}]"
        row = _object(item, path, {"source_result", "target_event", "kind", "target_role"},
                      ("source_result", "target_event", "kind"))
        kind = _string(row["kind"], f"{path}.kind")
        if kind not in ("trigger", "related"):
            raise ValidationError(f"{path}.kind: expected 'trigger' or 'related'")
        role = row.get("target_role")
        connections.append(Connection(
            _string(row["source_result"], f"{path}.source_result"),
            _string(row["target_event"], f"{path}.target_event"), kind,
            None if role is None else _string(role, f"{path}.target_role"),
        ))
    graph = EventGraph()
    graph.append(events=events, results=results, connections=connections)
    return graph


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str):
    raise ValidationError(f"non-finite JSON number: {value}")


def loads_graph(text: str) -> EventGraph:
    """Read strict JSON: reject duplicate keys, NaN, Infinity, and unknown fields."""
    if not isinstance(text, str):
        raise ValidationError("JSON input must be text")
    try:
        data = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise ValidationError(f"invalid JSON: {exc}") from exc
    return graph_from_dict(data)


def graph_to_dict(graph: EventGraph) -> dict:
    """Export current definitions, not executions, revision history, or retired IDs.

    Custom Python flows cannot be silently serialized as table rules.
    """
    events = []
    for event in sorted(graph.events.values(), key=lambda e: e.id):
        row = {
            "id": event.id, "description": event.description,
            "roles": list(event.roles), "locations": sorted(event.locations),
            "time": {"start": event.time.start, "end": event.time.end},
        }
        flow = event.flow
        if type(flow) is TableFlow:
            row["flow"] = {
                "type": "table",
                "cases": [{"inputs": sorted(key), "outputs": sorted(value)}
                          for key, value in sorted(flow.cases.items(), key=lambda item: sorted(item[0]))],
                "default": None if flow.default is None else sorted(flow.default),
                "input_domain": None if flow.input_domain is None else sorted(map(sorted, flow.input_domain)),
            }
        elif type(flow) is not UnconfiguredFlow:
            raise ValidationError(f"event {event.id}: custom Python flow cannot be exported")
        events.append(row)
    return {
        "version": 1,
        "events": events,
        "results": [
            {"id": r.id, "event_id": r.event_id, "recipient_roles": list(r.recipient_roles),
             "description": r.description}
            for r in sorted(graph.results.values(), key=lambda r: r.id)
        ],
        "connections": [
            {"source_result": c.source_result, "target_event": c.target_event,
             "kind": c.kind.value, "target_role": c.target_role}
            for c in sorted(graph.connections, key=lambda c: (c.source_result, c.target_event))
        ],
    }


def dumps_graph(graph: EventGraph) -> str:
    return json.dumps(graph_to_dict(graph), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
