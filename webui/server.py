"""webui/server.py - a small local web server for the StockWise UI. Standard library only.

Serves the single-page app in webui/static/ and a JSON API (see api.py). It listens
on 127.0.0.1 only, rejects requests whose Host header is not localhost (DNS
rebinding) and requires JSON content for every write (blocks cross-site forms).
"""
import json
import os
import re
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import database as db
from c_bridge import StockWiseError
from webui import api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
ASSETS = os.path.join(ROOT, "assets")
MAX_BODY = 1_000_000

# Explicit types: on Windows the registry can map .js or .svg to the wrong type.
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".json": "application/json", ".ico": "image/x-icon"}


def csv(value):
    return [v for v in (value or "").split(",") if v]


def _int_arg(q, name):
    return None if q.get(name) in (None, "") else api.to_int(q[name], name)


# (method, path pattern, handler(conn, query, body, *path_args) -> dict)
ROUTES = [
    ("GET", r"/api/bootstrap", lambda c, q, b: api.bootstrap()),
    ("GET", r"/api/summary", lambda c, q, b: api.summary(c)),
    ("GET", r"/api/dashboard", lambda c, q, b: api.dashboard(c)),
    ("GET", r"/api/products", lambda c, q, b: api.products_view(
        c, q.get("q", ""), csv(q.get("categories")), q.get("min"), q.get("max"))),
    ("POST", r"/api/products", lambda c, q, b: api.add_product(c, b)),
    ("PUT", r"/api/products/(\d+)", lambda c, q, b, pid: api.update_product(c, int(pid), b)),
    ("DELETE", r"/api/products/(\d+)", lambda c, q, b, pid: api.delete_product(c, int(pid))),
    ("GET", r"/api/transactions", lambda c, q, b: api.transactions_view(c, _int_arg(q, "product_id"))),
    ("POST", r"/api/transactions", lambda c, q, b: api.record_transaction(c, b)),
    ("GET", r"/api/restock", lambda c, q, b: api.restock_view(c)),
    ("GET", r"/api/restock/plan", lambda c, q, b: api.restock_plan(c, q.get("budget", 0))),
    ("POST", r"/api/restock/order", lambda c, q, b: api.restock_order(c, (b or {}).get("budget"))),
    ("GET", r"/api/routes", lambda c, q, b: api.routes_view(q.get("from", 0), q.get("to", 0))),
    ("GET", r"/api/search", lambda c, q, b: api.search_view(c, q)),
    ("GET", r"/api/sort", lambda c, q, b: api.sort_view(
        c, q.get("key", "name"), q.get("algo", "merge"), q.get("desc") == "1")),
    ("GET", r"/api/lab/search", lambda c, q, b: api.lab_search(c, q)),
    ("GET", r"/api/lab/sort", lambda c, q, b: api.lab_sort(c, q)),
    ("GET", r"/api/lab/scaling", lambda c, q, b: api.lab_scaling()),
    ("GET", r"/api/lab/hash", lambda c, q, b: api.lab_hash(c, q)),
    ("GET", r"/api/lab/heap", lambda c, q, b: api.lab_heap(c, q)),
    ("GET", r"/api/lab/avl", lambda c, q, b: api.lab_avl(c, q)),
    ("GET", r"/api/lab/trie", lambda c, q, b: api.lab_trie(c, q)),
    ("GET", r"/api/lab/edge", lambda c, q, b: api.lab_edge()),
    ("POST", r"/api/lab/knapsack", lambda c, q, b: api.lab_knapsack(b)),
]
ROUTES = [(m, re.compile("^" + p + "$"), fn) for m, p, fn in ROUTES]


class Handler(BaseHTTPRequestHandler):
    server_version = "StockWise"
    protocol_version = "HTTP/1.1"

    # ---- plumbing
    def log_message(self, fmt, *args):
        if getattr(self.server, "verbose", False):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_bytes(self, status, body, content_type, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        self.send_bytes(status, json.dumps(payload).encode("utf-8"), "application/json")

    def host_ok(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1")

    # ---- dispatch
    def handle_any(self, method):
        if not self.host_ok():
            return self.send_json(403, {"error": "forbidden host"})
        url = urlparse(self.path)
        if method == "GET" and not url.path.startswith("/api/"):
            return self.serve_static(url.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.close_connection = True  # the unread body would corrupt the next request
            return self.send_json(413, {"error": "request too large"})
        raw = self.rfile.read(length) if length else b""  # always consume the body (keep-alive)
        body = None
        if method in ("POST", "PUT", "DELETE"):
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                return self.send_json(415, {"error": "send JSON"})
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return self.send_json(400, {"error": "invalid JSON"})
        query = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        path_known = False
        for route_method, pattern, fn in ROUTES:
            m = pattern.match(url.path)
            if not m:
                continue
            path_known = True
            if route_method != method:
                continue
            try:
                with self.server.lock:  # one SQLite connection, one request at a time
                    result = fn(self.server.conn, query, body, *m.groups())
                return self.send_json(200, result)
            except ValueError as exc:  # bad input, including database constraint messages
                return self.send_json(400, {"error": str(exc)})
            except StockWiseError as exc:
                return self.send_json(500, {"error": str(exc)})
            except Exception as exc:  # keep serving; show the cause in the console and the page
                traceback.print_exc()
                return self.send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
        self.send_json(405 if path_known else 404, {"error": "not found"})

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    def do_PUT(self):
        self.handle_any("PUT")

    def do_DELETE(self):
        self.handle_any("DELETE")

    # ---- static files
    def serve_static(self, path):
        if path in ("/", "/index.html"):
            base, rel = STATIC, "index.html"
        elif path.startswith("/static/"):
            base, rel = STATIC, path[len("/static/"):]
        elif path.startswith("/assets/"):
            base, rel = ASSETS, path[len("/assets/"):]
        else:
            return self.send_json(404, {"error": "not found"})
        full = os.path.realpath(os.path.join(base, *rel.split("/")))
        if not full.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(full):
            return self.send_json(404, {"error": "not found"})
        with open(full, "rb") as fh:
            data = fh.read()
        kind = MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        self.send_bytes(200, data, kind, cache="no-cache")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets two programs share one port, so a second copy would
    # "start" and silently never receive requests. Keep it off there.
    allow_reuse_address = not sys.platform.startswith("win")

    def __init__(self, address, conn, verbose=False):
        super().__init__(address, Handler)
        self.conn, self.verbose, self.lock = conn, verbose, threading.Lock()


def make_server(db_path=None, port=8765, verbose=False):
    """Open the database (seeding sample data on first use) and bind to the first free
    port from `port` upwards. Returns a server; call serve_forever() on it."""
    conn = db.connect(db_path or db.DEFAULT_DB)
    db.init_db(conn)
    last_error = None
    for candidate in range(port, port + 20):
        try:
            return Server(("127.0.0.1", candidate), conn, verbose)
        except OSError as exc:  # port busy
            last_error = exc
    raise OSError(f"no free port between {port} and {port + 19}: {last_error}")
