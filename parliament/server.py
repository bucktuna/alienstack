#!/usr/bin/env python3
"""Bot Parliament: a tiny shared message board for Buck's bots (localhost only)."""
import json, os, time, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "messages.jsonl")
LOCK = threading.Lock()
HOST, PORT = "127.0.0.1", int(os.environ.get("PARLIAMENT_PORT", "8765"))

def load(since=0, limit=200):
    out = []
    if os.path.exists(LOG):
        with open(LOG) as f:
            for line in f:
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                if m["id"] > since:
                    out.append(m)
    return out[-limit:]

def append(bot, role, text):
    with LOCK:
        msgs = load(0, 10**9)
        mid = (msgs[-1]["id"] + 1) if msgs else 1
        m = {"id": mid, "ts": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "bot": bot[:40], "role": role[:60], "text": text[:4000]}
        with open(LOG, "a") as f:
            f.write(json.dumps(m) + "\n")
        return m

PAGE = open(os.path.join(HERE, "index.html")).read

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/":
            b = PAGE().encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        elif u.path == "/api/messages":
            self._json(load(int(q.get("since", ["0"])[0]), int(q.get("limit", ["200"])[0])))
        elif u.path == "/api/stream":
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache"); self.end_headers()
            last = int(q.get("since", ["0"])[0])
            try:
                while True:
                    for m in load(last):
                        self.wfile.write(f"data: {json.dumps(m)}\n\n".encode()); last = m["id"]
                    self.wfile.write(b": ping\n\n"); self.wfile.flush(); time.sleep(1)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self._json({"error": "not found"}, 404)
    def do_POST(self):
        if urlparse(self.path).path != "/api/messages":
            return self._json({"error": "not found"}, 404)
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0))
            bot, text = str(d["bot"]).strip(), str(d["text"]).strip()
            assert bot and text
        except Exception:
            return self._json({"error": "send JSON {bot, role?, text}"}, 400)
        self._json(append(bot, str(d.get("role", "")), text), 201)

if __name__ == "__main__":
    print(f"Bot Parliament on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
