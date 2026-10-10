"""Servidor falso con el formato de ESPN para la prueba de extremo a extremo (solo pruebas).

GET  /scoreboard?dates=YYYYMMDD → {"events": [...]} del día
POST /__event   (cuerpo: evento JSON) → crea/reemplaza el evento por id
"""
import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

EVENTS: dict[str, dict] = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.endswith("/scoreboard"):
            day = parse_qs(u.query).get("dates", [""])[0]
            evs = [e for e in EVENTS.values()
                   if datetime.strptime(e["date"], "%Y-%m-%dT%H:%MZ").strftime("%Y%m%d") == day]
            return self._send(200, {"events": evs})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        ev = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        EVENTS[str(ev["id"])] = ev
        self._send(200, {"ok": True})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 9911), Handler).serve_forever()
