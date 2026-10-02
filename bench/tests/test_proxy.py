"""The recording proxy, between an example and a stand-in for OpenRouter on localhost. Nothing leaves the machine."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import proxy

KEY = "sk-or-real-key"
JOB = "vendor-paid/01-docs-qa/01-answer/after/1"
# Compact, as the openai client sends it, and not ASCII: any re-encoding on the way would change these bytes.
REQUEST = '{"model":"vendor/paid","messages":[{"role":"user","content":"Why is the café closed?"}]}'.encode()


def answer(cost: float = 0.0012) -> bytes:
    return json.dumps({"id": "gen-1", "model": "vendor/paid", "provider": "SomeHost",
                       "choices": [{"message": {"role": "assistant", "content": "Because [help:x@1#0]."}}],
                       "usage": {"prompt_tokens": 120, "completion_tokens": 30, "cost": cost,
                                 "prompt_tokens_details": {"cached_tokens": 0},
                                 "completion_tokens_details": {"reasoning_tokens": 12}}}).encode()


HANG_UP = 0  # a queued reply that drops the connection instead of answering
RATE_LIMITED = json.dumps({"error": {"message": "Provider returned error", "code": 429,
                                     "metadata": {"provider_name": "SomeHost"}}}).encode()


class Upstream:
    """Stands in for OpenRouter: answers with the queued replies in turn, and keeps what it was sent."""

    def __init__(self) -> None:
        self.replies: list[tuple[int, dict[str, str], bytes]] = []
        self.received: list[dict[str, Any]] = []
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                upstream.received.append({"path": self.path, "authorization": self.headers["Authorization"],
                                          "body": body})
                status, headers, reply = upstream.replies.pop(0)
                if status == HANG_UP:
                    self.close_connection = True  # no response at all, as when a connection drops
                    return
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/api/v1"


@pytest.fixture
def upstream() -> Iterator[Upstream]:
    stand_in = Upstream()
    yield stand_in
    stand_in.server.shutdown()
    stand_in.server.server_close()


@pytest.fixture
def waits() -> list[float]:
    return []


@pytest.fixture
def running(tmp_path: Path, upstream: Upstream, waits: list[float]) -> Iterator[proxy.Proxy]:
    with proxy.Proxy(tmp_path, KEY, upstream=upstream.url, sleep=waits.append, attempts=3) as started:
        yield started


def call(running: proxy.Proxy, job: str = JOB, body: bytes = REQUEST) -> tuple[int, bytes]:
    """What an example's openai client does: POST to its base URL plus /chat/completions, with a dummy key."""
    request = urllib.request.Request(running.base_url(job) + "/chat/completions", data=body, method="POST",
                                     headers={"Authorization": "Bearer dummy", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def lines(run: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (run / "calls.jsonl").read_text(encoding="utf-8").splitlines()]


def test_a_call_goes_upstream_as_sent_with_the_real_key_and_comes_back_as_answered(running: proxy.Proxy,
                                                                                 upstream: Upstream) -> None:
    upstream.replies.append((200, {}, answer()))
    assert call(running) == (200, answer())
    [received] = upstream.received
    assert received == {"path": "/api/v1/chat/completions", "authorization": f"Bearer {KEY}", "body": REQUEST}


def test_each_call_is_recorded_with_who_answered_its_tokens_and_cost(running: proxy.Proxy, upstream: Upstream,
                                                                     tmp_path: Path) -> None:
    upstream.replies += [(200, {}, answer()), (200, {}, answer())]
    call(running)
    call(running)
    calls = tmp_path / JOB / "calls"
    assert (calls / "1.request.json").read_bytes() == REQUEST
    assert (calls / "1.response.json").read_bytes() == answer()
    first, second = lines(tmp_path)
    assert {key: first[key] for key in ("job", "call", "status", "model", "answered_by", "host", "tokens", "cost")} == {
        "job": JOB, "call": 1, "status": 200, "model": "vendor/paid", "answered_by": "vendor/paid", "host": "SomeHost",
        "tokens": {"prompt": 120, "completion": 30, "reasoning": 12, "cached": 0}, "cost": 0.0012}
    assert second["call"] == 2


def test_a_rate_limited_call_is_retried_with_backoff_and_every_attempt_recorded(running: proxy.Proxy, upstream: Upstream,
                                                                                waits: list[float], tmp_path: Path) -> None:
    upstream.replies += [(429, {}, RATE_LIMITED), (503, {}, b"{}"), (200, {}, answer())]
    assert call(running) == (200, answer())
    assert waits == [proxy.FIRST_WAIT, 2 * proxy.FIRST_WAIT]
    assert [attempt["status"] for attempt in lines(tmp_path)[0]["attempts"]] == [429, 503, 200]


def test_a_host_that_says_when_to_retry_is_waited_for(running: proxy.Proxy, upstream: Upstream,
                                                      waits: list[float]) -> None:
    upstream.replies += [(429, {"Retry-After": "7"}, RATE_LIMITED), (200, {}, answer())]
    call(running)
    assert waits == [7.0]


def test_a_call_that_keeps_failing_gives_the_example_the_last_error(running: proxy.Proxy, upstream: Upstream,
                                                                    tmp_path: Path) -> None:
    upstream.replies += [(429, {}, RATE_LIMITED)] * 3
    assert call(running) == (429, RATE_LIMITED)
    [line] = lines(tmp_path)
    assert (line["status"], line["host"], line["cost"], len(line["attempts"])) == (429, "SomeHost", 0, 3)
    assert running.spent == 0


def test_a_dropped_connection_is_retried_like_a_bad_gateway(running: proxy.Proxy, upstream: Upstream,
                                                           tmp_path: Path) -> None:
    upstream.replies += [(HANG_UP, {}, b""), (200, {}, answer())]
    assert call(running) == (200, answer())
    assert [attempt["status"] for attempt in lines(tmp_path)[0]["attempts"]] == [502, 200]


def test_spent_adds_up_what_every_call_cost(running: proxy.Proxy, upstream: Upstream) -> None:
    upstream.replies += [(200, {}, answer(cost=0.25)), (200, {}, answer(cost=0.5))]
    call(running)
    call(running, job="vendor-paid/02-account-aware/01-team-plan/1")
    assert running.spent == 0.75


def test_a_resumed_run_starts_from_what_it_had_spent(tmp_path: Path, upstream: Upstream) -> None:
    upstream.replies.append((200, {}, answer(cost=0.25)))
    with proxy.Proxy(tmp_path, KEY, upstream=upstream.url, spent=1.5) as resumed:
        call(resumed)
        assert resumed.spent == 1.75


def test_the_key_is_never_written(running: proxy.Proxy, upstream: Upstream, tmp_path: Path) -> None:
    upstream.replies += [(200, {}, answer()), (429, {}, RATE_LIMITED), (200, {}, answer())]
    call(running)
    call(running)
    assert all(KEY.encode() not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())


@pytest.mark.parametrize("job", ["../outside", "vendor-paid/../../outside", "vendor-paid/%2e%2e/%2e%2e/x", "vendor-paid//x"])
def test_a_job_path_outside_the_run_is_refused(running: proxy.Proxy, upstream: Upstream, tmp_path: Path,
                                               job: str) -> None:
    # Sent as a hostile client would, not through base_url(), which builds only clean paths.
    request = urllib.request.Request(running.base_url("x").removesuffix("/x") + f"/{job}/chat/completions",
                                     data=REQUEST, method="POST")
    try:
        status = urllib.request.urlopen(request, timeout=10).status
    except urllib.error.HTTPError as error:
        status = error.code
    assert status == 404 and upstream.received == [] and list(tmp_path.iterdir()) == []
