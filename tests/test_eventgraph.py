import unittest

from eventgraph import (
    Connection, Event, EventGraph, Flow, History, InputKind, MissingFlowUpdate,
    NotEnabled, Result, TableFlow, TimeWindow, UndefinedInput, ValidationError,
)


def constant(*outputs):
    return TableFlow(default=outputs)


def school_graph():
    graph = EventGraph()
    graph.append(
        events=[
            Event("admission", ("first", "second", "examiner"), constant("pass", "fail", "examined")),
            Event("final", ("student",), constant("high")),
            Event("job", ("applicant",), TableFlow({frozenset({"high"}): {"hired"}}, default={"rejected"})),
        ],
        results=[
            Result("pass", "admission", ("first",)),
            Result("fail", "admission", ("second",)),
            Result("examined", "admission", ("examiner",)),
            Result("high", "final", ("student",)),
            Result("hired", "job", ("applicant",)),
            Result("rejected", "job", ("applicant",)),
        ],
        connections=[
            Connection("pass", "final", InputKind.TRIGGER, "student"),
            Connection("high", "job", InputKind.RELATED, "applicant"),
        ],
    )
    return graph


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.graph = school_graph()
        self.history = History()

    def admission(self):
        return self.graph.execute(
            "admission", self.history,
            participants={"first": "alice", "second": "bob", "examiner": "teacher"},
            time=1, location="school",
        )

    def final(self):
        return self.graph.execute(
            "final", self.history, participants={"student": "alice"}, time=2, location="school"
        )

    def snapshot(self):
        return (dict(self.graph.events), dict(self.graph.results), self.graph.connections, self.graph.revision)

    def test_shared_event_records_and_role_scoped_prerequisite(self):
        execution = self.admission()
        self.assertEqual(len(execution.results), 3)
        self.assertEqual({r.result_id for r in self.history.for_actor("alice")}, {"pass"})
        self.assertEqual({r.result_id for r in self.history.for_actor("bob")}, {"fail"})
        self.assertEqual(self.history.experiences("alice"), self.history.experiences("bob"))
        self.final()
        with self.assertRaises(NotEnabled):
            self.graph.execute("final", self.history, participants={"student": "bob"}, time=3, location="school")
        self.assertEqual({r.result_id for r in self.history.for_actor("bob")}, {"fail"})

    def test_optional_related_input_does_not_gate_job(self):
        execution = self.graph.execute("job", self.history, participants={"applicant": "bob"}, time=1, location="office")
        self.assertEqual(execution.inputs, frozenset())
        self.assertEqual({r.result_id for r in execution.results}, {"rejected"})

    def test_only_declared_inputs_reach_flow(self):
        self.admission()
        self.final()
        execution = self.graph.execute("job", self.history, participants={"applicant": "alice"}, time=3, location="office")
        self.assertEqual(execution.inputs, frozenset({"high"}))
        self.assertEqual({r.result_id for r in execution.results}, {"hired"})

    def test_checking_enabled_does_not_execute(self):
        self.assertTrue(self.graph.is_enabled("job", self.history, participants={"applicant": "bob"}, time=1, location="office"))
        self.assertEqual(self.history.executions, ())

    def test_append_event_with_old_result_as_trigger(self):
        self.graph.append(
            events=[Event("retry", ("student",), constant("retried"))],
            results=[Result("retried", "retry", ("student",))],
            connections=[Connection("fail", "retry", InputKind.TRIGGER, "student")],
        )
        self.admission()
        self.assertTrue(self.graph.is_enabled("retry", self.history, participants={"student": "bob"}, time=2, location="school"))

    def test_append_updates_consumer_and_preserves_unaffected_event(self):
        untouched = self.graph.events["admission"]
        flow = TableFlow({frozenset({"experience"}): {"hired"}, frozenset({"high"}): {"hired"}, frozenset({"high", "experience"}): {"hired"}}, default={"rejected"})
        report = self.graph.append(
            events=[Event("work", ("worker",), constant("experience"))],
            results=[Result("experience", "work", ("worker",))],
            connections=[Connection("experience", "job", InputKind.RELATED, "applicant")],
            flow_updates={"job": flow},
        )
        self.assertEqual(report.updated_events, frozenset({"job"}))
        self.assertIs(self.graph.events["admission"], untouched)
        self.assertEqual(self.graph.schema("job").related_items, frozenset({"high", "experience"}))
        self.graph.execute("work", self.history, participants={"worker": "bob"}, time=1, location="workshop")
        result = self.graph.execute("job", self.history, participants={"applicant": "bob"}, time=2, location="office")
        self.assertEqual({r.result_id for r in result.results}, {"hired"})

    def test_missing_consumer_update_rolls_back_whole_append(self):
        before = self.snapshot()
        with self.assertRaises(MissingFlowUpdate):
            self.graph.append(
                events=[Event("work", (), constant("experience"))],
                results=[Result("experience", "work")],
                connections=[Connection("experience", "job", InputKind.RELATED)],
            )
        self.assertEqual(self.snapshot(), before)

    def test_adding_output_requires_source_flow_update(self):
        before = self.snapshot()
        with self.assertRaises(MissingFlowUpdate):
            self.graph.append(results=[Result("pending", "admission", ("first",))])
        self.assertEqual(self.snapshot(), before)

    def test_explicitly_reusing_flow_acknowledges_new_trigger(self):
        report = self.graph.append(
            connections=[Connection("pass", "job", InputKind.TRIGGER, "applicant")],
            flow_updates={"job": self.graph.events["job"].flow},
        )
        self.assertEqual(report.updated_events, frozenset({"job"}))
        self.assertFalse(self.graph.is_enabled("job", self.history, participants={"applicant": "alice"}, time=1, location="office"))

    def test_replacement_removes_edges_and_preserves_history_snapshot(self):
        self.admission()
        self.final()
        report = self.graph.replace_result(
            "high", Result("excellent", "final", ("student",)),
            connections=[Connection("excellent", "job", InputKind.RELATED, "applicant")],
            flow_updates={
                "final": constant("excellent"),
                "job": TableFlow({frozenset({"excellent"}): {"hired"}}, default={"rejected"}),
            },
        )
        self.assertEqual(report.removed_results, frozenset({"high"}))
        self.assertNotIn("high", self.graph.results)
        self.assertFalse(any(c.source_result == "high" for c in self.graph.connections))
        self.assertIn("high", {r.result_id for r in self.history.for_actor("alice")})
        self.assertEqual(self.graph.schema("job").related_items, frozenset({"excellent"}))
        self.assertEqual(self.graph.inputs_for("job", self.history, participants={"applicant": "alice"}, time=3, location="office"), frozenset())

    def test_replacement_without_target_update_is_atomic(self):
        before = self.snapshot()
        with self.assertRaises(MissingFlowUpdate):
            self.graph.replace_result("high", Result("excellent", "final", ("student",)), flow_updates={"final": constant("excellent")})
        self.assertEqual(self.snapshot(), before)

    def test_retired_result_ids_cannot_be_reused(self):
        self.graph.replace_result(
            "high", Result("excellent", "final", ("student",)),
            flow_updates={"final": constant("excellent"), "job": constant("rejected")},
        )
        with self.assertRaises(ValidationError):
            self.graph.append(results=[Result("high", "final", ("student",))], flow_updates={"final": constant("excellent")})

    def test_dangling_and_overlapping_connections_are_rejected(self):
        for connection in [Connection("missing", "job", InputKind.RELATED), Connection("high", "job", InputKind.TRIGGER)]:
            before = self.snapshot()
            with self.assertRaises(ValidationError):
                self.graph.append(connections=[connection], flow_updates={"job": constant("hired")})
            self.assertEqual(self.snapshot(), before)

    def test_invalid_output_update_rolls_back(self):
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.graph.append(flow_updates={"job": constant("not-declared")})
        self.assertEqual(self.snapshot(), before)

    def test_expanded_related_domain_requires_coverage(self):
        old_table = TableFlow({frozenset(): {"rejected"}, frozenset({"high"}): {"hired"}})
        self.graph.append(flow_updates={"job": old_table})
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.graph.append(
                connections=[Connection("fail", "job", InputKind.RELATED, "applicant")],
                flow_updates={"job": old_table},
            )
        self.assertEqual(self.snapshot(), before)

    def test_no_future_history_as_input(self):
        self.admission()
        self.final()
        inputs = self.graph.inputs_for("job", self.history, participants={"applicant": "alice"}, time=1, location="office")
        self.assertEqual(inputs, frozenset())

    def test_duplicate_execution_and_backdating_do_not_append(self):
        self.graph.execute("job", self.history, participants={"applicant": "bob"}, time=2, location="office", execution_id="one")
        before = self.history.executions
        for time, execution_id in [(3, "one"), (1, "two")]:
            with self.assertRaises(ValidationError):
                self.graph.execute("job", self.history, participants={"applicant": "bob"}, time=time, location="office", execution_id=execution_id)
            self.assertEqual(self.history.executions, before)

    def test_unknown_roles_and_wrong_bindings_fail(self):
        with self.assertRaises(ValidationError):
            self.graph.append(results=[Result("extra", "admission", ("unknown",))], flow_updates={"admission": constant("extra")})
        with self.assertRaises(ValidationError):
            self.graph.execute("job", self.history, participants={"wrong": "bob"}, time=1, location="office")

    def test_views_cannot_be_mutated(self):
        with self.assertRaises(TypeError):
            self.graph.events["job"] = self.graph.events["job"]
        self.admission()
        with self.assertRaises(TypeError):
            self.history.executions[0].participants["first"] = "bob"


class SemanticsTests(unittest.TestCase):
    def test_time_location_and_world_level_result(self):
        graph = EventGraph()
        graph.append(
            events=[
                Event("quake", (), constant("damaged"), TimeWindow(3, 3), frozenset({"city"})),
                Event("repair", ("worker",), constant("repaired")),
            ],
            results=[Result("damaged", "quake"), Result("repaired", "repair", ("worker",))],
            connections=[Connection("damaged", "repair", InputKind.TRIGGER)],
        )
        history = History()
        for time, location in [(2, "city"), (3, "other")]:
            self.assertFalse(graph.is_enabled("quake", history, participants={}, time=time, location=location))
        graph.execute("quake", history, participants={}, time=3, location="city")
        self.assertTrue(graph.is_enabled("repair", history, participants={"worker": "alice"}, time=4, location="city"))

    def test_independent_event_order_yields_same_consumer_inputs(self):
        graph = EventGraph()
        graph.append(
            events=[Event("a", ("person",), constant("ra")), Event("b", ("person",), constant("rb")), Event("c", ("person",), constant("rc"))],
            results=[Result("ra", "a", ("person",)), Result("rb", "b", ("person",)), Result("rc", "c", ("person",))],
            connections=[Connection("ra", "c", InputKind.RELATED), Connection("rb", "c", InputKind.RELATED)],
        )
        observed = []
        for order in [("a", "b"), ("b", "a")]:
            history = History()
            for time, event in enumerate(order):
                graph.execute(event, history, participants={"person": "alice"}, time=time, location="any")
            observed.append(graph.execute("c", history, participants={"person": "alice"}, time=2, location="any").inputs)
        self.assertEqual(observed[0], observed[1])
        self.assertEqual(observed[0], frozenset({"ra", "rb"}))

    def test_custom_flow_cannot_write_undeclared_result(self):
        class BadFlow(Flow):
            def resolve(self, inputs):
                return frozenset({"illegal"})
        graph = EventGraph()
        graph.append(events=[Event("bad", (), BadFlow())])
        history = History()
        with self.assertRaises(ValidationError):
            graph.execute("bad", history, participants={}, time=0, location="any")
        self.assertEqual(history.executions, ())

    def test_explicit_domain_violation_has_no_history_side_effect(self):
        graph = EventGraph()
        graph.append(
            events=[Event("a", (), constant("ra")), Event("b", (), TableFlow({frozenset(): {"rb"}}, input_domain=[set()]))],
            results=[Result("ra", "a"), Result("rb", "b")],
            connections=[Connection("ra", "b", InputKind.RELATED)],
        )
        history = History()
        graph.execute("a", history, participants={}, time=0, location="any")
        with self.assertRaises(UndefinedInput):
            graph.execute("b", history, participants={}, time=1, location="any")
        self.assertEqual(len(history.executions), 1)

    def test_no_exponential_enumeration_when_default_exists(self):
        flow = constant("out")
        flow.validate(frozenset(f"r{i}" for i in range(1000)), frozenset({"out"}))
        self.assertEqual(flow.resolve(frozenset({"r500"})), frozenset({"out"}))

    def test_empty_outcome_and_defensive_copy(self):
        cases = {frozenset(): set()}
        flow = TableFlow(cases)
        cases[frozenset()].add("unexpected")
        graph = EventGraph()
        graph.append(events=[Event("empty", ("person",), flow)])
        history = History()
        graph.execute("empty", history, participants={"person": "alice"}, time=0, location="any")
        self.assertEqual(history.for_actor("alice"), ())
        self.assertEqual(len(history.experiences("alice")), 1)

    def test_invalid_windows_and_string_collections(self):
        for arguments in [(3, 2), (float("nan"), None), (None, float("inf"))]:
            with self.assertRaises(ValidationError):
                TimeWindow(*arguments)
        with self.assertRaises(ValidationError):
            TableFlow(default="not-a-set")


if __name__ == "__main__":
    unittest.main()
