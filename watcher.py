"""Claude Terminal Completion Alarm - the watcher.

Run this in its own terminal. It listens on localhost for a "Claude finished"
signal (sent by notify.py, wired into Claude Code's Stop hook) and plays your
alarm until you press ENTER. Then it goes straight back to waiting.

    python watcher.py              start watching
    python watcher.py --hook       print the hook config to paste into Claude
    python watcher.py --test       trigger the alarm once, to check your audio
    python watcher.py --alarm X    use sound file X for this run only
"""

from __future__ import annotations

import json
import os
import queue
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from alarm import Alarm, AlarmError

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

DEFAULTS = {
    "alarm_file": "sounds/alarm.mp3",
    "loop_alarm": True,
    "host": "127.0.0.1",
    "port": 8787,
    "token": "",
}

# Labels that mean "Claude just started working" rather than "Claude is done".
# They only update the status line; they never ring.
WORKING_LABELS = {"working", "start", "started"}

events: "queue.Queue[str]" = queue.Queue()


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        print("[WARN] config.json not found, using defaults")
    except json.JSONDecodeError as exc:
        print("[WARN] config.json is not valid JSON (%s), using defaults" % exc)
    return cfg


def resolve_alarm(cfg: dict, override: str | None) -> str:
    path = override or cfg["alarm_file"]
    return path if os.path.isabs(path) else os.path.join(HERE, path)


# --------------------------------------------------------------------- server


class Server(ThreadingHTTPServer):
    """Refuses to share its port, so a second watcher fails loudly instead of
    silently stealing half the signals (Windows allows that by default)."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt":
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    token = ""

    def _reply(self, code: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _handle(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if self.token and params.get("token", [""])[0] != self.token:
            self._reply(403, "bad token")
            return

        if parsed.path.rstrip("/") == "/ping":
            self._reply(200, "pong")
            return

        events.put(params.get("label", ["done"])[0])
        self._reply(200, "ok")

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)  # body is ignored; the label is in the query
        self._handle()

    def log_message(self, *args) -> None:  # keep the console clean
        pass


def start_server(cfg: dict) -> Server:
    Handler.token = cfg.get("token", "")
    server = Server((cfg["host"], int(cfg["port"])), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ----------------------------------------------------------------- main loop


def ring(alarm_path: str, loop: bool, label: str) -> None:
    print("\n[DONE]  Claude finished (%s)." % label)
    alarm: Alarm | None = Alarm(alarm_path, loop=loop)
    try:
        alarm.start()
        print("[ALARM] Playing %s" % os.path.basename(alarm_path))
    except AlarmError as exc:
        print("[ALARM] %s" % exc)
        print("[ALARM] Put your sound file there, or set alarm_file in config.json.")
        alarm = None

    print("        Press ENTER to silence.")
    try:
        input()
    finally:
        if alarm:
            alarm.stop()
    print("[ALARM] Stopped.")

    while not events.empty():  # ignore anything that arrived mid-alarm
        events.get_nowait()


def watch(cfg: dict, alarm_path: str) -> int:
    try:
        server = start_server(cfg)
    except OSError as exc:
        print("[ERROR] Cannot listen on %s:%s (%s)" % (cfg["host"], cfg["port"], exc))
        print("        A watcher is probably already running.")
        return 1

    print("=" * 52)
    print(" CLAUDE TERMINAL COMPLETION ALARM")
    print(" listening on http://%s:%s" % (cfg["host"], cfg["port"]))
    print(" alarm file: %s" % alarm_path)
    if not os.path.isfile(alarm_path):
        print(" [WARN] that file does not exist yet - drop your mp3 in place")
    print(" Ctrl+C to quit the watcher")
    print("=" * 52)

    try:
        while True:
            print("\n[READY] Waiting for Claude...")
            while True:
                try:
                    label = events.get(timeout=0.5)  # timeout keeps Ctrl+C alive
                except queue.Empty:
                    continue
                if label in WORKING_LABELS:
                    print("[WORKING] Claude is working... monitoring.")
                    continue
                break
            ring(alarm_path, bool(cfg["loop_alarm"]), label)
    except (KeyboardInterrupt, EOFError):
        print("\n[EXIT] Watcher stopped.")
    finally:
        server.shutdown()
    return 0


# --------------------------------------------------------------------- extras


def print_hook(cfg: dict) -> None:
    def cmd(label: str) -> str:
        return '"%s" "%s" %s' % (sys.executable, os.path.join(HERE, "notify.py"), label)

    def entry(label: str) -> list:
        return [{"hooks": [{"type": "command", "command": cmd(label)}]}]

    snippet = {"hooks": {"Stop": entry("stop")}}
    print("Add this to .claude/settings.json in the project where you run Claude")
    print("(merge it with whatever is already in that file):\n")
    print(json.dumps(snippet, indent=2))
    print("\nOptional extras - add them inside the same \"hooks\" object:\n")
    print('  "UserPromptSubmit": %s' % json.dumps(entry("working")))
    print("      -> shows [WORKING] when you hand Claude a task (no alarm)\n")
    print('  "Notification": %s' % json.dumps(entry("needs-you")))
    print("      -> also rings when Claude pauses to ask you for permission")


def main(argv: list[str]) -> int:
    cfg = load_config()

    override = None
    if "--alarm" in argv:
        i = argv.index("--alarm")
        if i + 1 >= len(argv):
            print("[ERROR] --alarm needs a file path")
            return 1
        override = argv[i + 1]
    alarm_path = resolve_alarm(cfg, override)

    if "--hook" in argv:
        print_hook(cfg)
        return 0

    if "--test" in argv:
        events.put("self-test")

    return watch(cfg, alarm_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
