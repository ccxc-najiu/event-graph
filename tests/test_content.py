from dataclasses import dataclass
from types import SimpleNamespace
import unittest

from eventgraph import (
    Event, FlowEvent, EventGraph, History, MissingContentUpdate, MissingFlowUpdate,
    NodeContent, Result, TableFlow, UnconfiguredFlow, UndefinedInput, ValidationError,
    dumps_graph, graph_from_dict, graph_to_dict, loads_graph,
)
from eventgraph.viewer import scene_from_json


@dataclass(frozen=True)
class OutcomeContent:
    description: str
    result: str


@dataclass(frozen=True)
class OutcomeEvent(Event):
    def validate_content(self, related_ids, output_ids):
        if self.content.result not in output_ids:
            raise ValidationError("unknown outcome")

    def resolve(self, inputs):
        return frozenset({self.content.result})


class ContentTests(unittest.TestCase):
    def test_opaque_object_only_requires_description(self):
        content = SimpleNamespace(description="执行一段对话。", private=object())
        event = Event("dialogue", (), content)
        self.assertIs(event.content, content)
        self.assertFalse(hasattr(event, "flow"))
        graph = EventGraph()
        graph.append(events=[event])
        history = History()
        with self.assertRaises(UndefinedInput):
            graph.execute("dialogue", history, participants={}, time=0, location="any")
        self.assertEqual(history.executions, ())

    def test_description_is_required_and_one_line(self):
        for content in (None, object(), {"description": "字典不是内容对象。"},
                        SimpleNamespace(description=""), SimpleNamespace(description="  "),
                        SimpleNamespace(description=3), SimpleNamespace(description="a\nb")):
            with self.subTest(content=content), self.assertRaises(ValidationError):
                Event("bad", (), content)
        with self.assertRaises(ValidationError):
            TableFlow(default=(), description="")

    def test_derived_content_execution_and_atomic_updates(self):
        content = OutcomeContent("产生一个结果。", "out")
        graph = EventGraph()
        graph.append(events=[OutcomeEvent("a", (), content)], results=[Result("out", "a")])
        original, schema, revision = graph.events["a"], graph.schema("a"), graph.revision
        with self.assertRaises(ValidationError):
            graph.append(content_updates={"a": OutcomeContent("无效内容。", "missing")})
        self.assertIs(graph.events["a"], original)
        self.assertIs(graph.schema("a"), schema)
        self.assertEqual(graph.revision, revision)
        with self.assertRaises(MissingContentUpdate):
            graph.append(results=[Result("extra", "a")])
        graph.append(results=[Result("extra", "a")], content_updates={"a": content})
        self.assertIsInstance(graph.events["a"], OutcomeEvent)
        history = History()
        graph.execute("a", history, participants={}, time=0, location="any")
        graph.replace_result("out", Result("new", "a"),
                             content_updates={"a": OutcomeContent("产生新结果。", "new")})
        self.assertEqual(history.executions[0].results[0].result_id, "out")
        self.assertIsInstance(graph.events["a"], OutcomeEvent)
        with self.assertRaises(ValidationError):
            graph.append(results=[Result("out", "a")], content_updates={"a": graph.events["a"].content})

    def test_legacy_update_alias_and_invalid_description_rollback(self):
        graph = EventGraph()
        graph.append(events=[FlowEvent("a", (), TableFlow(default=()))])
        graph.append(flow_updates={"a": TableFlow(default=(), description="保留原有行为。")})
        revision = graph.revision
        self.assertIs(MissingFlowUpdate, MissingContentUpdate)
        for updates in ({"content_updates": {"a": object()}},
                        {"content_updates": {}, "flow_updates": {}}):
            with self.assertRaises(ValidationError):
                graph.append(**updates)
            self.assertEqual(graph.revision, revision)

    def test_content_roundtrip_and_copy_boundaries(self):
        data = {"version": 2, "events": [{"id": "a", "content": {
            "description": "展示一段文本。", "data": {"text": ["正文"], "type": "table"}}}]}
        graph = graph_from_dict(data)
        data["events"][0]["content"]["data"]["text"].append("修改")
        self.assertEqual(graph.events["a"].content.data["text"], ["正文"])
        exported = graph_to_dict(graph)
        self.assertEqual(exported["version"], 2)
        self.assertEqual(type(graph.events["a"]), Event)
        self.assertEqual(dumps_graph(loads_graph(dumps_graph(graph))), dumps_graph(graph))
        exported["events"][0]["content"]["data"]["text"].append("导出修改")
        self.assertEqual(graph.events["a"].content.data["text"], ["正文"])
        scene = scene_from_json(dumps_graph(graph))
        self.assertEqual(scene["graph"]["events"][0]["content"]["description"], "展示一段文本。")

    def test_flow_description_roundtrip_and_legacy_import(self):
        for content in (TableFlow(default=(), description="执行表格规则。"), UnconfiguredFlow("等待配置规则。")):
            graph = EventGraph()
            graph.append(events=[FlowEvent("a", (), content)])
            restored = loads_graph(dumps_graph(graph)).events["a"]
            self.assertIsInstance(restored, FlowEvent)
            self.assertEqual(restored.content.description, content.description)
        graph = graph_from_dict({"version": 1, "events": [
            {"id": "a", "flow": {"type": "table", "default": []}}, {"id": "b"}]})
        self.assertIsInstance(graph.events["a"], FlowEvent)
        self.assertIsInstance(graph.events["b"].content, NodeContent)
        self.assertTrue(graph.events["b"].content.description)

    def test_invalid_json_content_is_rejected(self):
        for content in (None, {}, {"description": ""}, {"description": "a\nb"},
                        {"description": "一句说明。", "data": float("inf")}):
            with self.subTest(content=content), self.assertRaises(ValidationError):
                graph_from_dict({"version": 2, "events": [{"id": "a", "content": content}]})
        with self.assertRaises(ValidationError):
            graph_from_dict({"version": 2, "events": [{"id": "a", "type": "flow", "content": {"type": "table", "default": []}}]})

    def test_custom_content_and_subclasses_are_not_silently_exported(self):
        for event in (Event("a", (), SimpleNamespace(description="自定义内容。")),
                      OutcomeEvent("a", (), OutcomeContent("自定义执行。", "out"))):
            graph = EventGraph()
            graph.append(events=[event], results=[Result("out", "a")])
            with self.assertRaises(ValidationError):
                dumps_graph(graph)
        for payload in (object(), {1: "key"}, (1, 2)):
            graph = EventGraph()
            graph.append(events=[Event("a", (), NodeContent("数据说明。", payload))])
            with self.assertRaises(ValidationError):
                dumps_graph(graph)
