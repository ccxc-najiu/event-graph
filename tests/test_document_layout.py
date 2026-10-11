import copy
import json
from math import dist, isfinite
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from eventgraph import (
    Connection, FlowEvent, EventGraph, Flow, History, InputKind, Result, TableFlow,
    TimeWindow, UndefinedInput, ValidationError, analyze_graph, dumps_graph,
    graph_from_dict, graph_to_dict, layout_graph, loads_graph,
)

ROOT = Path(__file__).resolve().parents[1]


def document(names=("a", "b"), links=(), windows=None):
    windows = windows or {}
    return {
        "version": 1,
        "events": [{"id": name, "time": windows.get(name, {})} for name in names],
        "results": [{"id": f"{name}.out", "event_id": name} for name in names],
        "connections": [{"source_result": f"{a}.out", "target_event": b, "kind": kind}
                        for a, b, kind in links],
    }


class DocumentTests(unittest.TestCase):
    def test_roundtrip_preserves_rules_and_execution(self):
        graph = EventGraph()
        graph.append(
            events=[FlowEvent("a", ("person",), TableFlow(default={"a.out"}),
                          TimeWindow(0, 4), frozenset({"school"}), "入学"),
                    FlowEvent("b", ("person",), TableFlow(
                        {frozenset({"a.out"}): {"b.out"}}, default=set(),
                        input_domain=[set(), {"a.out"}],
                    ))],
            results=[Result("a.out", "a", ("person",)), Result("b.out", "b", ("person",))],
            connections=[Connection("a.out", "b", InputKind.RELATED, "person")],
        )
        text = dumps_graph(graph)
        restored = loads_graph(text)
        self.assertEqual(dumps_graph(restored), text)
        self.assertIn("入学", text)
        history = History()
        restored.execute("a", history, participants={"person": "alice"}, time=1, location="school")
        execution = restored.execute("b", history, participants={"person": "alice"}, time=2, location="school")
        self.assertEqual([r.result_id for r in execution.results], ["b.out"])

    def test_omitted_flow_is_editable_but_never_invents_results(self):
        data = document()
        before = copy.deepcopy(data)
        graph = graph_from_dict(data)
        self.assertEqual(data, before)
        self.assertNotIn("flow", graph_to_dict(graph)["events"][0])
        history = History()
        with self.assertRaises(UndefinedInput):
            graph.execute("a", history, participants={}, time=0, location="any")
        self.assertEqual(history.executions, ())

    def test_invalid_json_is_rejected(self):
        for text in ('{"version":1,"version":1,"events":[]}', '{', '[]',
                     '{"version":true,"events":[]}', '{"version":3,"events":[]}',
                     '{"version":1,"events":[],"surprise":0}',
                     '{"version":1,"events":[{"id":"a","time":{"end":NaN}}]}',
                     '{"version":1,"events":[{"id":"a","time":{"end":1e400}}]}'):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                loads_graph(text)

    def test_malformed_fields_and_unknown_references(self):
        variants = []
        for key, value in (("id", 3), ("roles", "person"), ("roles", ["p", "p"]),
                           ("description", {}), ("time", None), ("time", {"start": 3, "end": 1}),
                           ("time", {"start": True}), ("flow", {"type": "python"}),
                           ("flow", {"type": "table", "default": "a.out"})):
            data = document()
            data["events"][0][key] = value
            variants.append(data)
        for section, row in (("events", {"id": "a"}),
                             ("results", {"id": "bad", "event_id": "missing"}),
                             ("connections", {"source_result": "missing", "target_event": "a", "kind": "related"}),
                             ("connections", {"source_result": "a.out", "target_event": "b", "kind": "related", "target_role": "missing"})):
            data = document()
            data[section].append(row)
            variants.append(data)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                graph_from_dict(data)

    def test_duplicate_cases_and_undeclared_rules_rejected(self):
        for flow in (
            {"type": "table", "cases": [{"inputs": [], "outputs": []}] * 2},
            {"type": "table", "default": ["missing"]},
            {"type": "table", "input_domain": [[], []], "default": []},
            {"type": "table", "cases": []},
        ):
            data = document()
            data["events"][0]["flow"] = flow
            with self.subTest(flow=flow), self.assertRaises(ValidationError):
                graph_from_dict(data)

    def test_custom_flow_not_silently_lost(self):
        class Custom(Flow):
            def resolve(self, inputs):
                return frozenset()
        graph = EventGraph()
        graph.append(events=[FlowEvent("a", (), Custom())])
        with self.assertRaisesRegex(ValidationError, "custom Python flow"):
            dumps_graph(graph)

    def test_sample_and_empty_graph_roundtrip(self):
        for text in ((ROOT / "examples/events.json").read_text(), '{"version":1,"events":[]}'):
            graph = loads_graph(text)
            self.assertEqual(graph_to_dict(graph), graph_to_dict(loads_graph(dumps_graph(graph))))


class OrderingTests(unittest.TestCase):
    def test_related_feedback_does_not_force_order(self):
        graph = graph_from_dict(document(links=[("a", "b", "related"), ("b", "a", "related")]))
        relations = analyze_graph(graph)
        self.assertEqual(dict(relations.ranks), {"a": 0, "b": 0})
        self.assertEqual({(link.source, link.target) for link in relations.links}, {("a", "b"), ("b", "a")})

    def test_trigger_with_optional_reverse_influence(self):
        graph = graph_from_dict(document(links=[("a", "b", "trigger"), ("b", "a", "related")]))
        self.assertLess(analyze_graph(graph).ranks["a"], analyze_graph(graph).ranks["b"])

    def test_trigger_cycles_and_self_dependency_rejected(self):
        for names, links in (
            (("a",), [("a", "a", "trigger")]),
            (("a", "b"), [("a", "b", "trigger"), ("b", "a", "trigger")]),
            (("a", "b", "c"), [("a", "b", "trigger"), ("b", "c", "trigger"), ("c", "a", "trigger")]),
        ):
            with self.subTest(links=links), self.assertRaisesRegex(ValidationError, "precedence cycle"):
                graph_from_dict(document(names, links))

    def test_window_overlap_touch_and_unbounded(self):
        cases = [
            ({"a": {"end": 2}, "b": {"start": 3}}, {"a": 0, "b": 1}),
            ({"a": {"end": 2}, "b": {"start": 2}}, {"a": 0, "b": 0}),
            ({"a": {"start": 0, "end": 10}, "b": {"start": 4, "end": 15}}, {"a": 0, "b": 0}),
            ({"a": {"start": 0}, "b": {"end": 10}}, {"a": 0, "b": 0}),
            ({"a": {"start": 0, "end": 0}, "b": {"start": 0, "end": 0}}, {"a": 0, "b": 0}),
        ]
        for windows, expected in cases:
            with self.subTest(windows=windows):
                graph = graph_from_dict(document(windows=windows))
                self.assertEqual(dict(analyze_graph(graph).ranks), expected)

    def test_window_and_trigger_conflict_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "precedence cycle"):
            graph_from_dict(document(links=[("b", "a", "trigger")],
                                     windows={"a": {"end": 1}, "b": {"start": 2}}))

    def test_long_chain_temporal_conflict_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "precedence cycle"):
            graph_from_dict(document(("a", "b", "c"), [("a", "b", "trigger"), ("b", "c", "trigger")],
                                     {"a": {"start": 8}, "c": {"end": 4}}))

    def test_failed_mutation_preserves_graph_and_schema_cache(self):
        graph = graph_from_dict(document(links=[("a", "b", "trigger")]))
        before = dumps_graph(graph)
        revision, schema = graph.revision, graph.schema("a")
        with self.assertRaisesRegex(ValidationError, "precedence cycle"):
            graph.append(connections=[Connection("b.out", "a", InputKind.TRIGGER)],
                         content_updates={"a": graph.events["a"].content})
        self.assertEqual(dumps_graph(graph), before)
        self.assertEqual(graph.revision, revision)
        self.assertIs(graph.schema("a"), schema)

    def test_replacement_cycle_rolls_back(self):
        graph = graph_from_dict(document(links=[("a", "b", "trigger")]))
        before = dumps_graph(graph)
        with self.assertRaisesRegex(ValidationError, "precedence cycle"):
            graph.replace_result(
                "b.out", Result("b.new", "b"),
                connections=[Connection("b.new", "a", InputKind.TRIGGER)],
                content_updates={"a": graph.events["a"].content, "b": graph.events["b"].content},
            )
        self.assertEqual(dumps_graph(graph), before)

    def test_sparse_order_matches_explicit_pairwise_reference(self):
        rng = random.Random(812)
        for _ in range(80):
            names = [f"n{i}" for i in range(12)]
            windows = {}
            for name in names:
                start = rng.randrange(-5, 10)
                windows[name] = {"start": start if rng.random() > .2 else None,
                                 "end": start + rng.randrange(0, 10) if rng.random() > .2 else None}
            links = [(a, b, "trigger") for a in names for b in names if a != b and rng.random() < .018]
            edges = {(a, b) for a, b, _ in links}
            edges.update((a, b) for a in names for b in names
                         if windows[a]["end"] is not None and windows[b]["start"] is not None
                         and windows[a]["end"] < windows[b]["start"])
            ranks = {}
            while len(ranks) < len(names):
                ready = [n for n in names if n not in ranks and all(a in ranks for a, b in edges if b == n)]
                if not ready:
                    break
                for n in ready:
                    ranks[n] = max((ranks[a] + 1 for a, b in edges if b == n), default=0)
            data = document(names, links, windows)
            if len(ranks) != len(names):
                with self.assertRaisesRegex(ValidationError, "precedence cycle"):
                    graph_from_dict(data)
            else:
                self.assertEqual(dict(analyze_graph(graph_from_dict(data)).ranks), ranks)

    def test_deep_cycle_has_no_recursion_limit(self):
        names = [f"n{i}" for i in range(1200)]
        links = [(names[i], names[(i + 1) % len(names)], "trigger") for i in range(len(names))]
        with self.assertRaisesRegex(ValidationError, "precedence cycle"):
            graph_from_dict(document(names, links))


class LayoutTests(unittest.TestCase):
    def assert_spaced(self, layout):
        points = list(layout.positions.values())
        for i, a in enumerate(points):
            self.assertTrue(all(map(isfinite, (a.x, a.y, a.z))))
            for b in points[i + 1:]:
                self.assertGreaterEqual(dist((a.x, a.y, a.z), (b.x, b.y, b.z)) + 1e-8, layout.node_spacing)

    def test_fork_merge_and_time_constraints(self):
        graph = loads_graph((ROOT / "examples/events.json").read_text())
        layout = layout_graph(graph)
        self.assert_spaced(layout)
        for connection in graph.connections:
            if connection.kind is InputKind.TRIGGER:
                source = graph.results[connection.source_result].event_id
                self.assertLess(layout.positions[source].y, layout.positions[connection.target_event].y)
        for a in graph.events.values():
            for b in graph.events.values():
                if a.time.end is not None and b.time.start is not None and a.time.end < b.time.start:
                    self.assertLess(layout.positions[a.id].y, layout.positions[b.id].y)
        self.assertEqual(len(layout.to_dict()["links"]), len(graph.connections))

    def test_many_unordered_nodes_have_separation_and_depth(self):
        layout = layout_graph(graph_from_dict(document([f"node{i:03}" for i in range(100)])))
        self.assert_spaced(layout)
        self.assertGreater(len({p.z for p in layout.positions.values()}), 1)
        self.assertEqual({p.y for p in layout.positions.values()}, {0})

    def test_deterministic_after_json_array_permutation(self):
        data = json.loads((ROOT / "examples/events.json").read_text())
        original = layout_graph(graph_from_dict(data)).to_dict()
        for key in ("events", "results", "connections"):
            data[key].reverse()
        self.assertEqual(layout_graph(graph_from_dict(data)).to_dict(), original)

    def test_append_retains_existing_positions(self):
        data = document(("a", "b", "c"), [("a", "b", "trigger"), ("a", "c", "trigger")])
        previous = layout_graph(graph_from_dict(data))
        data["events"].append({"id": "new"})
        data["connections"].append({"source_result": "a.out", "target_event": "new", "kind": "trigger"})
        updated = layout_graph(graph_from_dict(data), previous=previous)
        for name in previous.positions:
            self.assertEqual(updated.positions[name], previous.positions[name])
        self.assert_spaced(updated)

    def test_changed_ranks_can_resolve_previous_seat_collisions(self):
        previous = layout_graph(graph_from_dict(document(links=[("a", "b", "trigger")])))
        current = layout_graph(graph_from_dict(document()), previous=previous)
        self.assert_spaced(current)
        self.assertEqual(current.positions["a"], previous.positions["a"])
        self.assertEqual(current.positions["b"].rank, 0)

    def test_new_predecessor_updates_y_but_preserves_xz(self):
        previous = layout_graph(graph_from_dict(document()))
        data = document(("a", "b", "root"), [("root", "a", "trigger"), ("root", "b", "trigger")])
        current = layout_graph(graph_from_dict(data), previous=previous)
        for name in ("a", "b"):
            old, new = previous.positions[name], current.positions[name]
            self.assertEqual((old.x, old.z), (new.x, new.z))
            self.assertGreater(new.y, old.y)

    def test_empty_graph_and_readonly_outputs(self):
        empty = layout_graph(graph_from_dict(document(())))
        self.assertEqual(empty.to_dict()["nodes"], [])
        layout = layout_graph(graph_from_dict(document()))
        with self.assertRaises(TypeError):
            layout.positions["a"] = layout.positions["b"]
        with self.assertRaises(TypeError):
            layout.relations.ranks["a"] = 99
        json.dumps(layout.to_dict(), allow_nan=False)

    def test_bad_options_rejected(self):
        graph = graph_from_dict(document())
        for options in ({"node_spacing": 0}, {"layer_spacing": 1}, {"node_spacing": True},
                        {"node_spacing": float("nan")}, {"sweeps": -1}, {"sweeps": True},
                        {"layer_spacing": float("inf")}, {"previous": {}},
                        {"node_spacing": 4, "previous": layout_graph(graph)}):
            with self.subTest(options=options), self.assertRaises(ValidationError):
                layout_graph(graph, **options)

    def test_scale_does_not_change_arrangement(self):
        graph = loads_graph((ROOT / "examples/events.json").read_text())
        base = layout_graph(graph)
        scaled = layout_graph(graph, node_spacing=30, layer_spacing=50)
        for name, p in base.positions.items():
            q = scaled.positions[name]
            for left, right in zip((p.x, p.y, p.z), (q.x, q.y, q.z)):
                self.assertAlmostEqual(left * 10, right)

    def test_overflow_rejected_without_nonfinite_output(self):
        graph = graph_from_dict(document(("a", "b", "c"), [("a", "b", "trigger"), ("b", "c", "trigger")]))
        with self.assertRaisesRegex(ValidationError, "overflow"):
            layout_graph(graph, node_spacing=1e308, layer_spacing=1e308)

    def test_cli_export_and_source_protection(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            output = Path(folder) / "layout.json"
            source.write_text(json.dumps(document()))
            before = source.read_bytes()
            result = subprocess.run([sys.executable, "-m", "eventgraph", str(source), "-o", str(output)],
                                    cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads(output.read_text())["layout"]["nodes"]), 2)
            rejected = subprocess.run([sys.executable, "-m", "eventgraph", str(source), "-o", str(source)],
                                      cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(source.read_bytes(), before)
            source.write_text('{"version":7,"events":[]}')
            output.unlink()
            rejected = subprocess.run([sys.executable, "-m", "eventgraph", str(source), "-o", str(output)],
                                      cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
