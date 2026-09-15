"""Serve the Phase 06 SPA and its explicit direct or local-gateway transport."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import ssl
import http.client
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ENV = {
    "SAP_USER",
    "SAP_PASSWORD",
    "SAP_CLIENT",
    "SAP_LANGUAGE",
    "SAP_ODATA_BASE_URL",
    "SAP_DELIVERY_ODATA_BASE_URL",
    "SAP_BILLING_ODATA_BASE_URL",
    "SAP_ODATA_CA_CERT",
    "SAP_ODATA_CERT_SHA256",
}
CATALOG_NAMES = {"A": "a-technical-tools.json", "B": "b-typed-tools.json", "C": "c-semantic-tools.json"}


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(".env file is missing")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_ENV or key in values:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def service_root(value: str, key: str) -> str:
    try:
        parsed = urlparse(value.strip())
    except ValueError as exc:
        raise RuntimeError(f"{key} must be an absolute HTTPS URL") from exc
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError(f"{key} must be an absolute HTTPS URL without credentials, query, or fragment")
    return value.strip().rstrip("/") + "/"


def load_runtime(env_path: Path, bindings: dict) -> dict:
    env = read_env(env_path)
    required = ["SAP_USER", "SAP_PASSWORD", *[service["runtime_selector"] for service in bindings["services"].values()]]
    missing = [key for key in required if not env.get(key, "").strip()]
    if missing:
        raise RuntimeError("missing required local runtime settings: " + ", ".join(sorted(set(missing))))
    services = {
        service_id: service_root(env[service["runtime_selector"]], service["runtime_selector"])
        for service_id, service in bindings["services"].items()
    }
    return {
        "model": {"id": bindings["model"]["id"], "version": bindings["model"]["version"]},
        "protocol": "odata-v2",
        "username": env["SAP_USER"],
        "password": env["SAP_PASSWORD"],
        "client": env.get("SAP_CLIENT", ""),
        "language": env.get("SAP_LANGUAGE", ""),
        "services": services,
    }


def load_gateway(env_path: Path, bindings: dict) -> dict:
    env = read_env(env_path)
    required = ["SAP_USER", "SAP_PASSWORD", "SAP_ODATA_CA_CERT", "SAP_ODATA_CERT_SHA256"]
    required.extend(service["runtime_selector"] for service in bindings["services"].values())
    missing = [key for key in required if not env.get(key, "").strip()]
    if missing:
        raise RuntimeError("missing local gateway settings: " + ", ".join(sorted(set(missing))))
    services = {
        service_id: service_root(env[service["runtime_selector"]], service["runtime_selector"])
        for service_id, service in bindings["services"].items()
    }
    ca_cert = Path(env["SAP_ODATA_CA_CERT"]).expanduser().resolve()
    if not ca_cert.is_file():
        raise RuntimeError("SAP_ODATA_CA_CERT file is missing")
    pin = env["SAP_ODATA_CERT_SHA256"].replace(":", "").replace(" ", "").lower()
    if len(pin) != 64 or any(char not in "0123456789abcdef" for char in pin):
        raise RuntimeError("SAP_ODATA_CERT_SHA256 must be a SHA-256 hex fingerprint")
    return {"services": services, "username": env["SAP_USER"], "password": env["SAP_PASSWORD"], "client": env.get("SAP_CLIENT", ""), "language": env.get("SAP_LANGUAGE", ""), "ca_cert": ca_cert, "cert_sha256": pin}


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def verify_hash(artifact: dict) -> bool:
    expected = artifact.get("artifactSha256")
    if not isinstance(expected, str):
        return False
    unsigned = {key: value for key, value in artifact.items() if key != "artifactSha256"}
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest() == expected


class Handler(SimpleHTTPRequestHandler):
    server_version = "Phase06Runtime/1.0"

    def __init__(self, request, client_address, server):
        super().__init__(request, client_address, server, directory=str(server.runtime_state["frontend_root"]))

    def log_message(self, _format: str, *_args: object) -> None:
        return

    @property
    def runtime(self) -> dict:
        return self.server.runtime_state  # type: ignore[attr-defined]

    def send_json(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", self.runtime["csp"])
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/odata/") and self.runtime["transport"] == "local-gateway":
            self.proxy_odata(path)
            return
        if path == "/runtime/config.json":
            self.send_json(self.runtime["config"])
            return
        if path == "/runtime/tool-catalog.json":
            self.send_json(self.runtime["catalog"])
            return
        if path == "/runtime/bindings.json":
            self.send_json(self.runtime["bindings"])
            return
        if path.startswith("/runtime/"):
            self.send_error(404)
            return
        relative = path.removeprefix("/") or "index.html"
        target = (self.runtime["frontend_root"] / relative).resolve()
        if self.runtime["frontend_root"] not in target.parents and target != self.runtime["frontend_root"]:
            self.send_error(404)
            return
        if not target.is_file():
            target = self.runtime["frontend_root"] / "index.html"
        if not target.is_file():
            self.send_error(404, "frontend build is missing")
            return
        self.path = "/" + target.relative_to(self.runtime["frontend_root"]).as_posix()
        super().do_GET()

    def proxy_odata(self, path: str) -> None:
        parts = path.removeprefix("/api/odata/").split("/")
        service_id = parts[0] if parts else ""
        service = self.runtime["gateway"]["services"].get(service_id)
        if not service or len(parts) < 2 or len(parts) > 3:
            self.send_error(404)
            return
        if parts[1] == "__next":
            token = parts[2] if len(parts) == 3 else ""
            target = self.runtime["next_urls"].pop(token, "")
            if not target:
                self.send_error(404)
                return
        else:
            if len(parts) != 2 or not parts[1] or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_" for char in parts[1]):
                self.send_error(400)
                return
            target = service + parts[1]
        parsed = urlparse(target)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        allowed = {"$select", "$filter", "$top", "$format", "sap-client", "sap-language"}
        if any(key not in allowed for key in query):
            self.send_error(400)
            return
        if parts[1] != "__next":
            incoming = dict(parse_qsl(urlparse(self.path).query, keep_blank_values=True))
            if any(key not in allowed for key in incoming):
                self.send_error(400)
                return
            query = incoming
            target = urlunparse(parsed._replace(query=urlencode(query)))
        try:
            payload, status, headers = self.runtime["gateway_request"](service_id, target)
        except Exception as error:
            print(f"phase06 gateway error: {type(error).__name__}: {error}", flush=True)
            self.send_error(502, "SAP gateway request failed")
            return
        if status < 200 or status >= 300:
            payload = json.dumps({"error": {"code": "SAP_UPSTREAM_ERROR", "message": "SAP 查詢失敗。"}}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        try:
            document = json.loads(payload.decode("utf-8"))
            next_url = document.get("d", {}).get("__next")
            if next_url:
                next_parsed = urlparse(next_url)
                root = urlparse(service)
                if next_parsed.scheme != root.scheme or next_parsed.netloc != root.netloc or not next_parsed.path.startswith(root.path):
                    raise ValueError("invalid next URL")
                token = secrets.token_urlsafe(24)
                self.runtime["next_urls"][token] = next_url
                while len(self.runtime["next_urls"]) > 256:
                    self.runtime["next_urls"].pop(next(iter(self.runtime["next_urls"])))
                document["d"]["__next"] = f"/api/odata/{service_id}/__next/{token}"
                payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_error(502, "invalid SAP OData response")
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)


def build_state(condition: str, frontend_root: Path, catalog_dir: Path, bindings_path: Path, env_path: Path, transport: str = "direct-browser") -> dict:
    if condition not in CATALOG_NAMES:
        raise RuntimeError("condition must be A, B, or C")
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    catalog = json.loads((catalog_dir / CATALOG_NAMES[condition]).read_text(encoding="utf-8"))
    if not verify_hash(bindings) or not verify_hash(catalog):
        raise RuntimeError("runtime artifact hash verification failed")
    if bindings["model"]["id"] != catalog["model"]["id"] or bindings["model"]["version"] != catalog["model"]["version"]:
        raise RuntimeError("catalog and runtime binding model versions differ")
    if transport == "local-gateway":
        gateway = load_gateway(env_path, bindings)
        config = {"model": {"id": bindings["model"]["id"], "version": bindings["model"]["version"]}, "protocol": "odata-v2", "transport": transport, "gateway_base_path": "/api/odata", "client": gateway["client"], "language": gateway["language"], "services": {service_id: f"/api/odata/{service_id}" for service_id in bindings["services"]}}
        selectors = "'self'"
    else:
        gateway = None
        config = load_runtime(env_path, bindings)
        config["transport"] = transport
        config["gateway_base_path"] = ""
        selectors = " ".join(config["services"].values())
    csp = f"default-src 'self'; connect-src 'self' {selectors}; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'self'"
    def gateway_request(service_id: str, target: str):
        parsed = urlparse(target)
        context = ssl.create_default_context(cafile=str(gateway["ca_cert"]))
        context.check_hostname = False
        connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, context=context, timeout=30)
        path = urlunparse(parsed._replace(scheme="", netloc=""))
        auth = base64.b64encode(f"{gateway['username']}:{gateway['password']}".encode()).decode()
        connection.request("GET", path, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
        response = connection.getresponse()
        peer = connection.sock.getpeercert(binary_form=True)
        fingerprint = hashlib.sha256(peer).hexdigest().lower()
        if fingerprint != gateway["cert_sha256"]:
            connection.close()
            raise RuntimeError("SAP certificate pin mismatch")
        body = response.read()
        headers = {"content-type": response.getheader("Content-Type", "application/json")}
        connection.close()
        return body, response.status, headers

    return {"config": config, "catalog": catalog, "bindings": bindings, "frontend_root": frontend_root.resolve(), "csp": csp, "transport": transport, "gateway": gateway, "gateway_request": gateway_request, "next_urls": {}}


def main() -> int:
    parser = argparse.ArgumentParser(prog="serve_phase06")
    parser.add_argument("--condition", choices=sorted(CATALOG_NAMES), required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--frontend-root", type=Path, default=ROOT / "frontend" / "dist")
    parser.add_argument("--catalog-dir", type=Path, default=ROOT / "build" / "phase-05")
    parser.add_argument("--bindings", type=Path, default=ROOT / "build" / "phase-06" / "runtime-bindings.json")
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    parser.add_argument("--transport", choices=["direct-browser", "local-gateway"], default="direct-browser")
    args = parser.parse_args()
    state = build_state(args.condition, args.frontend_root, args.catalog_dir, args.bindings, args.env, args.transport)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.runtime_state = state  # type: ignore[attr-defined]
    print(json.dumps({"condition": args.condition, "host": args.host, "port": args.port, "model": state["bindings"]["model"]}, ensure_ascii=False))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
