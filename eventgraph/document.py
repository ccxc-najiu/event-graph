"""Versioned JSON definitions shared by import, layout, and future editors."""

import json
from math import isfinite
from typing import Any

from .errors import ValidationError
from .flows import TableFlow, UnconfiguredFlow
from .graph import EventGraph
from .models import Connection, Event, FlowEvent, Result, TimeWindow
from .content import NodeContent, check_description


def _json_content(value: object, path: str) -> object:
    """Copy JSON-native content without coercing keys, tuples or Python objects."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and isfinite(value):
        return value
    if type(value) is list:
        return [_json_content(item, f"{path}[{i}]") for i, item in enumerate(value)]
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: _json_content(item, f"{path}.{key}") for key, item in value.items()}
    raise ValidationError(f"{path}: content must be JSON-native to import or export")


def _copy_content(value: object, path: str) -> object:
    try:
        return _json_content(value, path)
    except RecursionError as exc:
        raise ValidationError(f"{path}: content is cyclic or too deeply nested") from exc


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


def _flow(value: Any, path: str, *, legacy: bool = False):
    required = ("type",) if legacy else ("type", "description")
    data = _object(value, path, {"type", "description", "cases", "default", "input_domain"}, required)
    description = check_description(data.get("description", "根据关联结果查表，确定本次事件的输出。"))
    if data["type"] == "unconfigured" and not legacy:
        _object(data, path, {"type", "description"}, required)
        return UnconfiguredFlow(description)
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
    return TableFlow(cases, default=default, input_domain=domain, description=description)


def graph_from_dict(value: dict) -> EventGraph:
    """Read version 2 content definitions and legacy version 1 flow definitions."""
    data = _object(value, "$", {"version", "events", "results", "connections"}, ("version", "events"))
    if type(data["version"]) is not int or data["version"] not in (1, 2):
        raise ValidationError("$.version: expected integer 1 or 2")
    events = []
    for i, item in enumerate(_array(data["events"], "$.events")):
        path = f"$.events[{i}]"
        fields = {"flow"} if data["version"] == 1 else {"type", "content"}
        required = ("id",) if data["version"] == 1 else ("id", "content")
        row = _object(item, path, {"id", "description", "roles", "locations", "time"} | fields, required)
        window = _object(row.get("time", {}), f"{path}.time", {"start", "end"})
        try:
            time = TimeWindow(window.get("start"), window.get("end"))
        except (ValidationError, OverflowError) as exc:
            raise ValidationError(f"{path}.time: {exc}") from exc
        event_class = Event
        if data["version"] == 1:
            content = NodeContent("尚未配置节点内容。")
            if "flow" in row:
                event_class, content = FlowEvent, _flow(row["flow"], f"{path}.flow", legacy=True)
        else:
            kind = row.get("type", "event")
            if kind not in ("event", "flow"):
                raise ValidationError(f"{path}.type: expected 'event' or 'flow'")
            if kind == "flow":
                event_class = FlowEvent
                content = _flow(row["content"], f"{path}.content")
            else:
                raw = _object(row["content"], f"{path}.content", {"description", "data"}, ("description",))
                content = NodeContent(check_description(raw["description"]),
                                      _copy_content(raw.get("data"), f"{path}.content.data"))
        events.append(event_class(
            _string(row["id"], f"{path}.id"),
            tuple(_ids(row.get("roles", []), f"{path}.roles")),
            content,
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

    Custom event classes and Python content need an application-specific codec;
    they must never silently lose behavior during a JSON round trip.
    """
    events = []
    for event in sorted(graph.events.values(), key=lambda e: e.id):
        row = {
            "id": event.id, "description": event.description,
            "roles": list(event.roles), "locations": sorted(event.locations),
            "time": {"start": event.time.start, "end": event.time.end},
        }
        if type(event) not in (Event, FlowEvent):
            raise ValidationError(f"event {event.id}: custom event class cannot be exported")
        row["type"] = "flow" if type(event) is FlowEvent else "event"
        flow = event.content
        if type(event) is Event:
            if type(event.content) is not NodeContent:
                raise ValidationError(f"event {event.id}: custom Python content cannot be exported")
            row["content"] = {"description": check_description(event.content.description),
                              "data": _copy_content(event.content.data, f"event {event.id}.content.data")}
        elif type(flow) is TableFlow:
            row["content"] = {
                "type": "table",
                "description": check_description(flow.description),
                "cases": [{"inputs": sorted(key), "outputs": sorted(value)}
                          for key, value in sorted(flow.cases.items(), key=lambda item: sorted(item[0]))],
                "default": None if flow.default is None else sorted(flow.default),
                "input_domain": None if flow.input_domain is None else sorted(map(sorted, flow.input_domain)),
            }
        elif type(flow) is UnconfiguredFlow:
            row["content"] = {"type": "unconfigured", "description": check_description(flow.description)}
        else:
            raise ValidationError(f"event {event.id}: custom Python flow cannot be exported")
        events.append(row)
    return {
        "version": 2,
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
