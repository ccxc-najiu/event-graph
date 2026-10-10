"""Generate renderer-independent JSON geometry: python -m eventgraph scene.json."""

import argparse
import json
from pathlib import Path
import sys

from .document import graph_to_dict, loads_graph
from .errors import ValidationError
from .layout import layout_graph


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse event JSON and generate a 3D layout.")
    parser.add_argument("source", type=Path, help="version 1 event JSON")
    parser.add_argument("-o", "--output", type=Path, help="write geometry JSON (default: stdout)")
    parser.add_argument("--node-spacing", type=float, default=3.0)
    parser.add_argument("--layer-spacing", type=float, default=5.0)
    args = parser.parse_args()
    try:
        if args.output and args.source.resolve() == args.output.resolve():
            raise ValidationError("output must not overwrite source JSON")
        graph = loads_graph(args.source.read_text(encoding="utf-8"))
        layout = layout_graph(graph, node_spacing=args.node_spacing, layer_spacing=args.layer_spacing)
        text = json.dumps({"graph": graph_to_dict(graph), "layout": layout.to_dict()},
                          ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    except (OSError, UnicodeError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
