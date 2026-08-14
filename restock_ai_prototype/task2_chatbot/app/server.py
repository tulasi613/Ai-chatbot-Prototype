"""
Web server: serves the chat UI and the JSON API from one origin (no CORS pain).

Uses Flask when it's installed, and falls back to the standard library's
http.server otherwise — so `python run.py` works on a bare Python 3.10+ install
with nothing to pip install.
"""
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import api, config

UI_DIR = config.BASE_DIR / "ui"


def _static(path):
    """Map a URL path to a file inside ui/. Returns (bytes, content_type) or None."""
    rel = "index.html" if path in ("/", "") else path.lstrip("/")
    target = (UI_DIR / rel).resolve()
    if not str(target).startswith(str(UI_DIR.resolve())) or not target.is_file():
        return None
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return target.read_bytes(), ctype


# ------------------------------------------------------------------ stdlib server
class _Handler(BaseHTTPRequestHandler):
    server_version = "RestockAI/1.0"

    def log_message(self, fmt, *args):
        if self.path.startswith("/api/"):
            print(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    def _send(self, status, payload=None, raw=None, ctype="application/json"):
        body = raw if raw is not None else json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            asset = _static(parsed.path)
            if asset:
                return self._send(200, raw=asset[0], ctype=asset[1])
            return self._send(404, raw=b"Not found", ctype="text/plain")

        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        status, payload = _safe(api.handle, "GET", parsed.path, params, {})
        self._send(status, payload)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "Body must be valid JSON"})
        status, payload = _safe(api.handle, "POST", parsed.path, {}, body)
        self._send(status, payload)


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception as exc:  # keep the demo alive and show the error in the UI
        import traceback

        traceback.print_exc()
        return 500, {"error": f"{type(exc).__name__}: {exc}"}


# ------------------------------------------------------------------ flask server
def _build_flask_app():
    from flask import Flask, Response, request

    flask_app = Flask(__name__, static_folder=None)

    @flask_app.route("/", defaults={"path": ""})
    @flask_app.route("/<path:path>")
    def catch_all(path):
        asset = _static("/" + path)
        if asset:
            return Response(asset[0], mimetype=asset[1])
        return Response("Not found", status=404, mimetype="text/plain")

    @flask_app.route("/api/<path:path>", methods=["GET", "POST", "OPTIONS"])
    def api_route(path):
        if request.method == "OPTIONS":
            return Response(status=204, headers={"Access-Control-Allow-Origin": "*"})
        body = request.get_json(silent=True) or {}
        params = request.args.to_dict()
        status, payload = _safe(api.handle, request.method, "/api/" + path, params, body)
        return Response(
            json.dumps(payload, default=str),
            status=status,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    return flask_app


def serve(host=None, port=None):
    host = host or config.HOST
    port = port or config.PORT
    url = f"http://{host}:{port}"

    try:
        flask_app = _build_flask_app()
        backend = "Flask"
    except ImportError:
        flask_app = None
        backend = "python http.server (Flask not installed)"

    print("\n  Smart Restock AI — customer chatbot")
    print(f"  server   : {backend}")
    print(f"  database : {db_label()}")
    print(f"  open     : {url}\n")

    if flask_app is not None:
        flask_app.run(host=host, port=port, debug=False, use_reloader=False)
    else:
        ThreadingHTTPServer((host, port), _Handler).serve_forever()


def db_label():
    from . import db

    ok, target = db.ping()
    return target if ok else f"UNAVAILABLE ({target})"
