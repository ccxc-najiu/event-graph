from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from math import hypot

from eventgraph import loads_graph
from eventgraph.layout import layout_graph, spread_canopy

from eventgraph import ValidationError
from eventgraph.viewer import MAX_BYTES, make_handler, scene_from_json


class Request:
    def __init__(self, data):
        self.input = BytesIO(data)
        self.output = bytearray()

    def makefile(self, mode, *args):
        return self.input

    def sendall(self, data):
        self.output.extend(data)

    def settimeout(self, value):
        pass


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.source = '{"version":1,"events":[{"id":"initial"}]}'
        self.scene = scene_from_json(self.source)
        self.handler = make_handler(self.scene, 'test')

    def request(self, path, *, method='GET', body=b'', headers=None):
        merged = {'Host': '127.0.0.1:8765', 'Content-Length': str(len(body))}
        if method == 'POST':
            merged['Content-Type'] = 'application/json'
        merged.update(headers or {})
        raw = f'{method} {path} HTTP/1.0\r\n' + ''.join(f'{key}: {value}\r\n' for key, value in merged.items())
        connection = Request(raw.encode() + b'\r\n' + body)
        self.handler(connection, ('127.0.0.1', 1000), SimpleNamespace(server_port=8765))
        head, data = bytes(connection.output).split(b'\r\n\r\n', 1)
        status = int(head.split()[1])
        return status, head.decode(), data

    def test_page_assets_and_scene(self):
        for path in ('/', '/app.js', '/renderer.js', '/styles.css', '/api/scene'):
            with self.subTest(path=path):
                status, headers, data = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn('Content-Security-Policy:', headers)
                self.assertIn(f'Content-Length: {len(data)}', headers)
                self.assertTrue(data)
        scene = json.loads(self.request('/api/scene')[2])
        self.assertEqual(scene['layout']['nodes'][0]['id'], 'initial')

    def test_import_is_request_local_and_preserves_initial_scene(self):
        before = json.dumps(self.scene, sort_keys=True)
        document = {'version':1,'events':[{'id':'a'},{'id':'b'}],
                    'results':[{'id':'ra','event_id':'a'},{'id':'rb','event_id':'b'}],
                    'connections':[{'source_result':'ra','target_event':'b','kind':'related'},
                                   {'source_result':'rb','target_event':'a','kind':'related'}]}
        status, _, data = self.request('/api/layout', method='POST', body=json.dumps(document).encode())
        self.assertEqual(status, 200)
        scene = json.loads(data)
        self.assertEqual(len(scene['layout']['links']), 2)
        self.assertEqual({p['rank'] for p in scene['layout']['nodes']}, {0})
        self.assertEqual(before, json.dumps(self.scene, sort_keys=True))
        self.assertEqual(json.loads(self.request('/api/scene')[2])['graph']['events'][0]['id'], 'initial')

    def test_invalid_import_and_resource_limits(self):
        for body in (b'{', b'{"version":1,"version":1,"events":[]}', b'\xff', b'{"version":9,"events":[]}'):
            with self.subTest(body=body):
                status, _, data = self.request('/api/layout', method='POST', body=body)
                self.assertEqual(status, 400)
                self.assertIn('error', json.loads(data))
        status, _, _ = self.request('/api/layout', method='POST', headers={'Content-Length':str(MAX_BYTES+1)})
        self.assertEqual(status, 413)
        with self.assertRaises(ValidationError):
            scene_from_json(' '*(MAX_BYTES+1))
        with self.assertRaisesRegex(ValidationError, '3,000'):
            scene_from_json(json.dumps({'version':1,'events':[{'id':str(i)} for i in range(3001)]}))

    def test_routes_and_local_origin(self):
        for path in ('/../document.py', '/%2e%2e/document.py', '/api/missing'):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request('/api/layout', method='POST', body=b'{}',
                                      headers={'Content-Type':'text/plain'})[0], 415)
        for headers in ({'Host':'example.com:8765'}, {'Origin':'https://example.com'}, {'Origin':'null'}):
            self.assertEqual(self.request('/api/scene', headers=headers)[0], 403)
        self.assertEqual(self.request('/api/scene', headers={'Origin':'http://127.0.0.1:8765'})[0], 200)

    def test_branching_example_uses_real_layout(self):
        path = Path(__file__).resolve().parents[1] / 'examples/branching.json'
        scene = scene_from_json(path.read_text())
        self.assertEqual(len(scene['layout']['nodes']), 28)
        self.assertEqual(len(scene['layout']['links']), 36)
        self.assertEqual(len(scene['graph']['connections']), 36)
        positions = {p['id']:p for p in scene['layout']['nodes']}
        for link in scene['layout']['links']:
            if link['kind'] == 'trigger':
                self.assertLess(positions[link['source']]['y'], positions[link['target']]['y'])


    def test_spread_canopy_preserves_constraints_and_opens_crown(self):
        source = (Path(__file__).resolve().parents[1] / 'examples/branching.json').read_text(encoding='utf-8')
        original = layout_graph(loads_graph(source), node_spacing=5.0)
        spread = spread_canopy(original)
        self.assertIs(spread.relations, original.relations)
        self.assertEqual(spread.to_dict(), spread_canopy(spread).to_dict())
        old_extent = sum(p.x*p.x + p.z*p.z for p in original.positions.values())
        new_extent = sum(p.x*p.x + p.z*p.z for p in spread.positions.values())
        self.assertGreater(new_extent, old_extent * 2)
        for name, point in spread.positions.items():
            self.assertEqual(point.y, original.positions[name].y)
            self.assertEqual(point.rank, original.positions[name].rank)
            if point.rank:
                self.assertGreaterEqual(hypot(point.x, point.z), 5 - 1e-9)
            for other_name, other in spread.positions.items():
                if name != other_name:
                    self.assertGreaterEqual(hypot(point.x-other.x,point.y-other.y,point.z-other.z),5-1e-9)

    def test_related_proximity_shortens_vines_without_collapsing_crown(self):
        source = (Path(__file__).resolve().parents[1] / 'examples/branching.json').read_text(encoding='utf-8')
        base = layout_graph(loads_graph(source), node_spacing=5.0)
        before = spread_canopy(base, related_proximity=False)
        after = spread_canopy(base)
        pairs = {tuple(sorted((link.source, link.target))) for link in base.relations.links
                 if link.kind.value == 'related' and link.source != link.target}
        def length(layout):
            return sum(hypot(layout.positions[a].x-layout.positions[b].x,
                             layout.positions[a].y-layout.positions[b].y,
                             layout.positions[a].z-layout.positions[b].z) for a, b in pairs)
        self.assertLess(length(after), length(before) * .75)
        for name, point in after.positions.items():
            old = before.positions[name]
            self.assertEqual((point.y, point.rank), (old.y, old.rank))
            radius = hypot(old.x, old.z)
            self.assertGreaterEqual(hypot(point.x, point.z), radius * .8 - 1e-9)
            self.assertLessEqual(hypot(point.x, point.z), radius * 1.2 + 1e-9)
        self.assertEqual(after.positions['origin'], before.positions['origin'])
        self.assertIs(after.relations, base.relations)

    def test_proximity_ignores_duplicate_reverse_and_self_links(self):
        from dataclasses import replace
        from eventgraph.layout import Relations
        source = (Path(__file__).resolve().parents[1] / 'examples/branching.json').read_text(encoding='utf-8')
        base = layout_graph(loads_graph(source), node_spacing=5.0)
        related = [link for link in base.relations.links if link.kind.value == 'related']
        extras = tuple(related) + tuple(replace(link, source=link.target, target=link.source)
                                       for link in related) + (replace(related[0], target=related[0].source),)
        duplicated = replace(base, relations=Relations(base.relations.ranks, base.relations.links + extras))
        self.assertEqual(spread_canopy(base).positions, spread_canopy(duplicated).positions)
        self.assertEqual(len(spread_canopy(duplicated).relations.links), len(duplicated.relations.links))
        triggers = tuple(link for link in base.relations.links if link.kind.value == 'trigger')
        no_related = replace(base, relations=Relations(base.relations.ranks, triggers))
        self.assertEqual(spread_canopy(no_related).positions,
                         spread_canopy(no_related, related_proximity=False).positions)

    def test_proximity_preserves_cross_layer_related_constraints(self):
        data = {'version': 1, 'events': [{'id': str(i), 'time': {'start': i, 'end': i}} for i in range(9)],
                'results': [{'id': f'r{i}', 'event_id': str(i)} for i in range(9)],
                'connections': [{'source_result': f'r{i}', 'target_event': str((i+4)%9), 'kind': 'related'}
                                for i in range(9)]}
        graph = loads_graph(json.dumps(data))
        a = spread_canopy(layout_graph(graph, node_spacing=5, layer_spacing=5))
        b = spread_canopy(layout_graph(graph, node_spacing=10, layer_spacing=10))
        for name, point in a.positions.items():
            scaled = b.positions[name]
            self.assertEqual((scaled.x, scaled.y, scaled.z), (point.x*2, point.y*2, point.z*2))
            self.assertEqual(point.rank, int(name))
            self.assertGreaterEqual(hypot(point.x, point.z), 5-1e-9)
        self.assertEqual(a.to_dict(), spread_canopy(a).to_dict())

    def test_canopy_layout_is_independent_of_document_order(self):
        data = json.loads((Path(__file__).resolve().parents[1] / 'examples/branching.json').read_text(encoding='utf-8'))
        scene = scene_from_json(json.dumps(data))
        for key in ('events', 'results', 'connections'):
            data[key].reverse()
        self.assertEqual(scene['layout'], scene_from_json(json.dumps(data))['layout'])

    def test_canopy_empty_singleton_and_related_only_roots(self):
        for count in (0, 1, 12):
            events = [{'id':str(i)} for i in range(count)]
            graph = loads_graph(json.dumps({'version':1,'events':events}))
            spread = spread_canopy(layout_graph(graph, node_spacing=5.0))
            self.assertEqual(len(spread.positions),count)
            if count > 1:
                self.assertTrue(all(hypot(p.x,p.z)>=5-1e-9 for p in spread.positions.values()))
        data = {'version':1,'events':[{'id':'a'},{'id':'b'}],
                'results':[{'id':'ra','event_id':'a'},{'id':'rb','event_id':'b'}],
                'connections':[{'source_result':'ra','target_event':'b','kind':'related'},
                               {'source_result':'rb','target_event':'a','kind':'related'}]}
        scene = scene_from_json(json.dumps(data))
        self.assertEqual(len(scene['layout']['links']),2)
        self.assertTrue(all(hypot(p['x'],p['z'])>=5-1e-9 for p in scene['layout']['nodes']))


if __name__ == '__main__':
    unittest.main()
