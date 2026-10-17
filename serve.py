"""Local web server for the Bipbop webpage + tutor.

Serves the built React app (web/dist) and a tiny JSON API. Standard library
only, so it runs with any Python -- you do not need the project's virtualenv.

    python serve.py                 # http://127.0.0.1:8000
    python serve.py --port 9000
    python serve.py --no-browser    # don't open a browser window

Why a server at all? Two reasons:
  * browsers only allow camera access on https:// or http://localhost, so a
    plain double-clicked .html file cannot use the webcam;
  * the song lookup runs here, so your free LLM key (if you set one) never has
    to be embedded in JavaScript where anyone could read it.

API:
    GET /api/songs                 -> built-in songs + whether AI lookup is on
    GET /api/lesson?title=NAME&refresh=1
                                   -> a lesson (built-in, cached, or via LLM)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import tutor

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB_SRC = os.path.join(ROOT, "web")        # the React/Vite project (source)
WEB_DIR = os.path.join(WEB_SRC, "dist")    # the built app we actually serve


class Handler(SimpleHTTPRequestHandler):
    # Serve files out of web/ and keep the console quieter
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write("  api %s\n" % (fmt % args))

    # ---------------------------------------------------------------- helpers
    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with memoryview(body) as mv:
            self.wfile.write(mv)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/songs":
            return self._json({"songs": tutor.list_songs(), "llm": tutor.llm_status()})
        if parsed.path == "/api/lesson":
            return self._lesson(parse_qs(parsed.query))
        if parsed.path == "/api/health":
            return self._json({"ok": True, "llm": tutor.available_providers()})
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def _lesson(self, query):
        title = (query.get("title") or [""])[0].strip()
        refresh = (query.get("refresh") or ["0"])[0] not in ("", "0", "false")
        if not title:
            return self._json({"error": "no song title given"}, 400)
        try:
            lesson = tutor.find_lesson(title, refresh=refresh)
        except LookupError as exc:
            return self._json({"error": str(exc)}, 404)
        except Exception as exc:  # never take the page down over a bad lookup
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        return self._json({"lesson": lesson.to_dict()})

    def end_headers(self):
        # The page is a local tool: never let the browser serve a stale copy
        if self.path and self.path.endswith((".js", ".css", ".html", "/")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Serve the Bipbop web app")
    ap.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="interface to bind (default 127.0.0.1, local only)")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser")
    args = ap.parse_args(argv)

    if not os.path.isdir(WEB_DIR):
        print(f"error: the built frontend was not found at {WEB_DIR}", file=sys.stderr)
        print("build it once first:", file=sys.stderr)
        print("  cd web", file=sys.stderr)
        print("  npm install", file=sys.stderr)
        print("  npm run build", file=sys.stderr)
        return 1

    port = args.port
    server = None
    for candidate in range(port, port + 20):  # find a free port if it's taken
        try:
            server = ThreadingHTTPServer((args.host, candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        print(f"error: no free port in {port}..{port + 19}", file=sys.stderr)
        return 1

    url = f"http://{args.host}:{port}/"
    status = tutor.llm_status()
    print("Bipbop web app")
    print(f"  open:  {url}")
    print(f"  files: {WEB_DIR}")
    if status["enabled"]:
        print(f"  song lookup: ready via {', '.join(status['available'])}")
    else:
        print(f"  song lookup: built-in songs only. {status['hint']}")
    if status.get("local_only"):
        print("  note: only a local Ollama model is available; small models can get "
              "melodies wrong.")
    print("  press Ctrl+C to stop")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
