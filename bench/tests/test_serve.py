"""The viewer's server: the viewer and the results, on this machine only, and nothing else in bench/."""
from __future__ import annotations

import threading
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

import serve


@pytest.fixture
def base() -> Iterator[str]:
    server = serve.server(port=0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def status(url: str) -> int:
    try:
        return urllib.request.urlopen(url, timeout=5).status
    except urllib.error.HTTPError as error:
        return error.code


def test_the_viewer_is_served_and_the_root_leads_to_it(base: str) -> None:
    assert status(f"{base}/viewer/") == 200
    assert urllib.request.urlopen(f"{base}/", timeout=5).url == f"{base}/viewer/"


@pytest.mark.parametrize("path", ["/.env", "/bench.toml", "/config.py", "/viewer/../.env", "/%2e%2e/bench/.env",
                                  "/results/"])
def test_nothing_but_the_viewer_and_result_files_is_served(base: str, path: str) -> None:
    # bench/.env holds the key: it, the code and folder listings stay off the server.
    assert status(base + path) == 404


def test_it_listens_on_this_machine_only() -> None:
    server = serve.server(port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
