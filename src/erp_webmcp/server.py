from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .odata import ODataError
from .service import SemanticToolService


class Application:
    def __init__(self, model_path: Path, web_root: Path) -> None:
        self.service = SemanticToolService(str(model_path))
        self.web_root = web_root.resolve()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "ERPWebMCP/0.1"

    @property
    def app(self) -> Application:
        return self.server.app  # type: ignore[attr-defined]

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._json(200, self.app.service.health())
            return
        relative = "index.html" if path == "/" else unquote(path.lstrip("/"))
        target = (self.app.web_root / relative).resolve()
        if self.app.web_root not in target.parents and target != self.app.web_root:
            self._json(403, {"error": "forbidden path"})
            return
        if not target.is_file():
            self._json(404, {"error": "not found"})
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        prefix = "/api/tools/"
        if not path.startswith(prefix):
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 16_384:
                raise ValueError("request body is too large")
            arguments = json.loads(self.rfile.read(length).decode("utf-8"))
            result = self.app.service.execute(unquote(path[len(prefix) :]), arguments)
            self._json(200, result)
        except KeyError as exc:
            self._json(404, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except ODataError as exc:
            self._json(502, {"error": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def create_server(host: str, port: int, app: Application) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), RequestHandler)
    server.app = app  # type: ignore[attr-defined]
    return server


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Serve the ERP WebMCP research prototype")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--model", default=str(project_root / "semantic_model" / "sap_sd_order_flow.json")
    )
    parser.add_argument("--web-root", default=str(project_root / "web"))
    args = parser.parse_args()
    app = Application(Path(args.model), Path(args.web_root))
    server = create_server(args.host, args.port, app)
    print(f"Serving ERP WebMCP prototype at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
