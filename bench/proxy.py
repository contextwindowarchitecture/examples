"""A local HTTP server between the examples and OpenRouter, which records every call.

    http://127.0.0.1:<port>/<job>/chat/completions  ->  https://openrouter.ai/api/v1/chat/completions

Each job's example gets OPENAI_BASE_URL=http://127.0.0.1:<port>/<job> and a dummy key, so the key never reaches an
example, and <job>, the job's folder under the run, says whose call each one is however many run at once. The proxy
sends the request body upstream exactly as the example sent it, with the real key, and hands back what came back.

For every call it writes <job>/calls/<n>.request.json and <n>.response.json, and a line in calls.jsonl: the model asked
for, the model and host that answered, tokens, cost, latency and every attempt. The key is never written.

A 429 or 5xx is retried, after the host's Retry-After or with a doubling wait. Free models share upstream rate limits,
and their 429s carry no Retry-After. The examples never stream, so a reply is read whole.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

UPSTREAM = "https://openrouter.ai/api/v1"
RETRIED = {429, 500, 502, 503, 504}
ATTEMPTS = 6
FIRST_WAIT, LONGEST_WAIT = 5.0, 60.0  # seconds
TIMEOUT = 600.0  # seconds for one attempt: a reasoning model can think for minutes
SEGMENT = re.compile(r"[A-Za-z0-9_.-]+")


class Proxy:
    def __init__(self, run: Path, key: str, *, upstream: str = UPSTREAM, attempts: int = ATTEMPTS,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.run, self.key, self.upstream, self.attempts, self.sleep = run, key, upstream, attempts, sleep
        self.spent = 0.0  # dollars, as OpenRouter charged them
        self._lock = threading.Lock()
        self._calls: dict[str, int] = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))

    def __enter__(self) -> Proxy:
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        return self

    def __exit__(self, *exception: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    def base_url(self, job: str | Path) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/{Path(job).as_posix()}"

    def forward(self, job: str, body: bytes) -> tuple[int, bytes]:
        """Send one call upstream, retrying, record it, and return what the example gets back."""
        attempts = []
        started = time.monotonic()
        for attempt in range(1, self.attempts + 1):
            began = time.monotonic()
            status, retry_after, reply = self._post(body)
            attempts.append({"status": status, "ms": round((time.monotonic() - began) * 1000)})
            if status not in RETRIED or attempt == self.attempts:
                break
            self.sleep(retry_after if retry_after is not None else min(FIRST_WAIT * 2 ** (attempt - 1), LONGEST_WAIT))
        self._record(job, body, status, reply, attempts, round((time.monotonic() - started) * 1000))
        return status, reply

    def _post(self, body: bytes) -> tuple[int, float | None, bytes]:
        request = urllib.request.Request(f"{self.upstream}/chat/completions", data=body, method="POST",
                                         headers={"Authorization": f"Bearer {self.key}",
                                                  "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.status, None, response.read()
        except urllib.error.HTTPError as error:
            retry_after = error.headers.get("Retry-After")
            return error.code, float(retry_after) if retry_after and retry_after.isdigit() else None, error.read()
        except (OSError, http.client.HTTPException) as error:  # refused, timed out, or dropped without a response
            reason = getattr(error, "reason", None) or error
            return 502, None, json.dumps({"error": {"message": f"cannot reach OpenRouter: {reason}"}}).encode()

    def _record(self, job: str, body: bytes, status: int, reply: bytes, attempts: list[dict[str, int]], ms: int) -> None:
        with self._lock:
            number = self._calls[job] = self._calls.get(job, 0) + 1
        calls = self.run / job / "calls"
        calls.mkdir(parents=True, exist_ok=True)
        (calls / f"{number}.request.json").write_bytes(body)
        (calls / f"{number}.response.json").write_bytes(reply)
        answered = _object(reply)
        usage = answered.get("usage") or {}
        error = answered.get("error") or {}
        line = {"job": job, "call": number, "status": status, "model": _object(body).get("model"),
                "answered_by": answered.get("model"),
                "host": answered.get("provider") or (error.get("metadata") or {}).get("provider_name"),
                "tokens": {"prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens"),
                           "reasoning": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                           "cached": (usage.get("prompt_tokens_details") or {}).get("cached_tokens")},
                "cost": usage.get("cost") or 0, "ms": ms, "attempts": attempts,
                "request_sha256": hashlib.sha256(body).hexdigest(), "error": error.get("message")}
        with self._lock:
            self.spent += line["cost"]
            with (self.run / "calls.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(line, ensure_ascii=False) + "\n")


def _handler(proxy: Proxy) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            job = self.path.removesuffix("/chat/completions").strip("/")
            # A job is a folder under the run: plain segments only, so no request can write anywhere else.
            if not self.path.endswith("/chat/completions") or not all(
                    SEGMENT.fullmatch(part) and part not in (".", "..") for part in job.split("/")):
                self.send_error(404)
                return
            status, reply = proxy.forward(job, self.rfile.read(int(self.headers.get("Content-Length", 0))))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args: Any) -> None:
            pass  # calls.jsonl is the log

    return Handler


def _object(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
