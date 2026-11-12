#!/usr/bin/env python3
"""Display-compare server: two full-screen pages (one per display) share one state over
Server-Sent Events, and the Innoview's hardware settings are changed over DDC through
BetterDisplay. Only the secondary display is ever written to; the reference is never touched.

Run: python3 -I tools/compare/server.py [--port 8659]
"""
import json, os, queue, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SAVES = os.path.join(ROOT, "local", "compare-saves.json")
SECONDARY = "Innoview"                      # the only display this server writes to
VCP = {"preset": "0x14", "r": "0x16", "g": "0x18", "b": "0x1A", "bright": "0x10", "contrast": "0x12"}
LIMITS = {"preset": {5, 11}, "r": range(0, 101), "g": range(0, 101), "b": range(0, 101),
          "bright": range(0, 101), "contrast": range(0, 101)}

clients, clients_lock = [], threading.Lock()
# The UI never waits for the monitor: state["innoview"] is the *desired* setting and updates at
# once. A single worker writes only what differs from what was last written, always the latest
# value, so ten quick key presses become one DDC write.
pending = threading.Condition()
applied = {}
state = {"pattern": "white", "panel": True, "labels": True, "flip": 0, "showing": "B",
         "innoview": {}, "A": None, "saves": [], "message": ""}

def ddc(op, key, value=None):
    args = ["betterdisplaycli", op, f"--name={SECONDARY}", "--ddc", f"--vcp={VCP[key]}"]
    if value is not None: args.append(f"--value={value}")
    out = subprocess.run(args, capture_output=True, text=True, timeout=10).stdout.strip()
    return out

def read_secondary():
    vals = {}
    for k in VCP:
        try: vals[k] = int(ddc("get", k))
        except (ValueError, subprocess.SubprocessError): vals[k] = None
    return vals

def write_secondary(values):
    """values: subset of VCP keys. Gains only apply in the User preset, so writing a gain selects it."""
    clean = {}
    for k, v in values.items():
        if k not in VCP: continue
        v = int(v)
        if v not in LIMITS[k]: raise ValueError(f"{k}={v} out of range")
        clean[k] = v
    if any(k in clean for k in ("r", "g", "b")) and "preset" not in clean:
        clean["preset"] = 11
    with pending:
        state["innoview"] = {**state["innoview"], **clean}
        pending.notify()

def ddc_worker():
    while True:
        with pending:
            while not (todo := {k: v for k, v in state["innoview"].items() if v is not None and applied.get(k) != v}):
                pending.wait()
        state["busy"] = True
        for k in ("preset", "r", "g", "b", "bright", "contrast"):
            if k in todo:
                try:
                    ddc("set", k, todo[k]); applied[k] = todo[k]
                except subprocess.SubprocessError as e:
                    state["message"] = f"DDC {k}: {e}"; applied[k] = todo[k]
        with pending:
            more = any(v is not None and applied.get(k) != v for k, v in state["innoview"].items())
        if not more:
            state["busy"] = False; broadcast()

def load_saves():
    try: state["saves"] = json.load(open(SAVES))
    except (OSError, ValueError): state["saves"] = []

def store_saves():
    os.makedirs(os.path.dirname(SAVES), exist_ok=True)
    json.dump(state["saves"], open(SAVES, "w"), indent=2)

def broadcast():
    data = "data: " + json.dumps(state) + "\n\n"
    with clients_lock:
        for q in list(clients): q.put(data)

def settings_only(s): return {k: s[k] for k in ("preset", "r", "g", "b", "bright") if s.get(k) is not None}

def apply_action(body):
    a = body.get("action")
    if a == "ui":
        for k in ("pattern", "panel", "labels", "flip"):
            if k in body: state[k] = body[k]
    elif a == "set":
        write_secondary(body["values"]); state["showing"] = "B"; state["B"] = settings_only(state["innoview"])
    elif a == "nudge":
        cur = state["innoview"]; key, step = body["key"], int(body["step"])
        base = cur.get(key) if cur.get(key) is not None else 50
        write_secondary({key: max(0, min(100, base + step))})
        state["showing"] = "B"; state["B"] = settings_only(state["innoview"])
    elif a == "saveA":
        state["A"] = settings_only(state["innoview"]); state["message"] = "saved current as A"
    elif a == "toggleAB":
        if not state.get("A"): state["message"] = "nothing saved as A yet"; return
        target = "A" if state["showing"] == "B" else "B"
        if target == "B" and not state.get("B"): return
        write_secondary(state[target]); state["showing"] = target
    elif a == "save":
        entry = {"name": body.get("name") or time.strftime("%H:%M:%S"), **settings_only(state["innoview"])}
        state["saves"].append(entry); store_saves(); state["message"] = f"saved '{entry['name']}'"
    elif a == "load":
        e = state["saves"][int(body["index"])]
        write_secondary(settings_only(e)); state["showing"] = "B"; state["B"] = settings_only(state["innoview"])
    elif a == "delete":
        del state["saves"][int(body["index"])]; store_saves()
    elif a == "original":
        write_secondary({"preset": 5}); state["showing"] = "B"; state["B"] = settings_only(state["innoview"])

def flipper():
    while True:
        period = state.get("flip") or 0
        if period and state.get("A") and state.get("B"):
            try:
                target = "A" if state["showing"] == "B" else "B"
                write_secondary(state[target]); state["showing"] = target; broadcast()
            except Exception as e: state["message"] = f"flip: {e}"
            time.sleep(max(1.0, float(period)))
        else:
            time.sleep(0.25)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send(200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html; charset=utf-8")
        if path == "/events":
            self.send_response(200); self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store"); self.end_headers()
            q = queue.Queue(); q.put("data: " + json.dumps(state) + "\n\n")
            with clients_lock: clients.append(q)
            try:
                while True:
                    try: msg = q.get(timeout=15)
                    except queue.Empty: msg = ": ping\n\n"
                    self.wfile.write(msg.encode()); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError): pass
            finally:
                with clients_lock: clients.remove(q)
            return
        self.send(404, '{"error":"not found"}')

    def do_POST(self):
        if urlparse(self.path).path != "/api":
            return self.send(404, '{"error":"not found"}')
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            state["message"] = ""
            apply_action(body)
            broadcast()
            self.send(200, json.dumps({"ok": True}))
        except Exception as e:
            state["message"] = f"error: {e}"; broadcast()
            self.send(400, json.dumps({"ok": False, "error": str(e)}))

def main():
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8659
    load_saves()
    state["innoview"] = read_secondary(); state["B"] = settings_only(state["innoview"])
    applied.update(state["innoview"])
    threading.Thread(target=flipper, daemon=True).start()
    threading.Thread(target=ddc_worker, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"compare server on http://127.0.0.1:{port}  (writes only to '{SECONDARY}')", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    main()
