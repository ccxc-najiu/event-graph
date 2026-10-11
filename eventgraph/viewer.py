"""Offline local viewer. It reads definitions but never writes source files."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from .document import graph_to_dict, loads_graph
from .errors import ValidationError
from .layout import layout_graph, spread_canopy

WEB = Path(__file__).with_name("web")
MAX_BYTES = 2 * 1024 * 1024
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/renderer.js": ("renderer.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def scene_from_json(text: str) -> dict:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValidationError("JSON 文件不能超过 2 MiB")
    graph = loads_graph(text)
    if len(graph.events) > 3000 or len(graph.connections) > 12000:
        raise ValidationError("当前查看器最多支持 3,000 个事件、12,000 条连接")
    return {"graph": graph_to_dict(graph), "layout": spread_canopy(layout_graph(graph, node_spacing=5.0)).to_dict()}


def make_handler(initial_scene: dict, name: str = "事件图谱"):
    """Each server owns a read-only initial scene; imports are request-local."""
    initial = json.dumps({**initial_scene, "name": name}, ensure_ascii=False).encode()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body: bytes, content_type="application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status, message):
            self._send(status, json.dumps({"error": message}, ensure_ascii=False).encode())

        def _local(self):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if host not in allowed or (origin is not None and origin != f"http://{host}"):
                self._error(403, "仅允许本地查看器访问")
                return False
            return True

        def do_GET(self):
            if not self._local():
                return
            path = urlsplit(self.path).path
            if path == "/api/scene":
                self._send(200, initial)
            elif path in ASSETS:
                filename, content_type = ASSETS[path]
                self._send(200, (WEB / filename).read_bytes(), content_type)
            else:
                self._error(404, "未找到资源")

        def do_POST(self):
            if not self._local():
                return
            if urlsplit(self.path).path != "/api/layout":
                self._error(404, "未找到资源")
                return
            if self.headers.get_content_type() != "application/json":
                self._error(415, "请提供 JSON 文件")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 0 < length <= MAX_BYTES:
                self._error(413, "JSON 文件大小应在 1 字节到 2 MiB 之间")
                return
            try:
                self.connection.settimeout(15)
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValidationError("JSON 数据不完整")
                scene = scene_from_json(data.decode("utf-8"))
            except (ValidationError, UnicodeError, TimeoutError) as exc:
                self._error(400, str(exc))
                return
            self._send(200, json.dumps(scene, ensure_ascii=False, allow_nan=False).encode())

        def log_message(self, format, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Run the local electric-blue 3D event viewer.")
    parser.add_argument("source", type=Path, help="event JSON file")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        scene = scene_from_json(args.source.read_text(encoding="utf-8"))
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(scene, args.source.stem))
    except (OSError, ValueError, UnicodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"EventGraph: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
