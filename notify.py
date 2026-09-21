"""Tell the watcher that Claude just finished a turn.

This is what Claude Code's Stop hook runs. It must be fast and must never
fail in a way that disturbs Claude, so every error is swallowed and we always
exit 0.

    python notify.py [label]
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULTS = {"host": "127.0.0.1", "port": 8787, "token": "", "url": ""}


def main() -> int:
    cfg = dict(DEFAULTS)
    try:
        with open(os.path.join(HERE, "config.json"), "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except Exception:
        pass

    label = sys.argv[1] if len(sys.argv) > 1 else "stop"
    # "url" lets you point at a remote watcher (see the RunPod section of the
    # README). Empty means "the watcher on this machine".
    base = cfg.get("url") or "http://%s:%s" % (cfg["host"], cfg["port"])
    query = {"label": label}
    if cfg.get("token"):
        query["token"] = cfg["token"]
    url = "%s/done?%s" % (base.rstrip("/"), urllib.parse.urlencode(query))

    try:
        req = urllib.request.Request(url, data=b"", method="POST")
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass  # watcher not running / unreachable - that is fine
    return 0


if __name__ == "__main__":
    sys.exit(main())
