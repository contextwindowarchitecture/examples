"""Serve the viewer and the results, on this machine only.

    uv run serve.py                  # http://127.0.0.1:8765/
    uv run serve.py --port 9000
    python serve.py --host 0.0.0.0   # in a container, where the pod's network is the boundary (openshift/)

The viewer is static: it reads results/index.json, each run's summary.json and the job files under it. Only
viewer/ and results/ are served. bench/.env holds the key, so nothing else in bench/ is, and no folder is listed.
"""
from __future__ import annotations

import argparse
import functools
import posixpath
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from config import HERE

SERVED = ("viewer", "results")


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self._allowed():
            super().do_GET()

    def do_HEAD(self) -> None:
        if self._allowed():
            super().do_HEAD()

    def _allowed(self) -> bool:
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path in ("", "/"):
            self.send_response(302)
            self.send_header("Location", "/viewer/")
            self.end_headers()
            return False
        if posixpath.normpath(path).lstrip("/").split("/")[0] not in SERVED or ".." in path.split("/"):
            self.send_error(404)
            return False
        return True

    def list_directory(self, path: Any) -> None:
        self.send_error(404)  # a folder holds an index.html or nothing to show

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")  # a run being graded changes its files
        super().end_headers()

    def log_message(self, *args: Any) -> None:
        pass


def server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), functools.partial(Handler, directory=str(HERE)))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    with server(args.host, args.port) as running:
        print(f"http://{args.host}:{running.server_address[1]}/", flush=True)
        try:
            running.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
