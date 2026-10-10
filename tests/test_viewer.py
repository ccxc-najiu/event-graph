from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

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


if __name__ == '__main__':
    unittest.main()
