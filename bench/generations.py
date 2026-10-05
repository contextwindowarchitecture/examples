"""What OpenRouter recorded about each call of a run: the time to its first token, how long it generated, its tokens by
OpenRouter's own count and by the model's, and the hosts it tried. run.py fetches it when a run ends.

    uv run --env-file .env generations.py results/<run-id>     # what the run does not hold yet

Every response the proxy kept carries the id OpenRouter gave the generation, and GET /generation?id=<id> returns its
stats. Nothing is sent to a model and nothing is charged. The examples do not stream, and the harness changes nothing
they send, so this is where a time to first token comes from: OpenRouter streams from the host whatever the client
asked for, and times it.

Each call's stats go to <job>/calls/<n>.generation.json, beside its request and response: the fields in KEPT, and each
host tried with its status. The reply also names the account's workspace and the request, which a run has no use for
and does not keep. The key is never written. OpenRouter does not say how long it keeps a generation's stats, so they
are fetched as soon as the run ends; a call it has none for yet is reported, and fetching again picks it up.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TextIO

import config
from proxy import RETRIED, UPSTREAM

KEPT = ("created_at", "model", "provider_name", "latency", "generation_time", "moderation_latency", "tokens_prompt",
        "tokens_completion", "native_tokens_prompt", "native_tokens_completion", "native_tokens_reasoning",
        "native_tokens_cached", "finish_reason", "native_finish_reason", "streamed", "cancelled", "total_cost",
        "cache_discount", "upstream_inference_cost", "service_tier", "data_region")
ATTEMPTS = 4
WORKERS = 4  # at a time: these are reads, and a run has thousands of them


def fetch(id: str, key: str, upstream: str = UPSTREAM, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any] | None:
    """A generation's stats, or None when OpenRouter has none for it: not yet, or no longer."""
    request = urllib.request.Request(f"{upstream}/generation?id={urllib.parse.quote(id)}", headers={"Authorization": f"Bearer {key}"})
    for attempt in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response).get("data")
        except urllib.error.HTTPError as error:
            if error.code not in RETRIED or attempt == ATTEMPTS - 1:
                return None
        except OSError:
            if attempt == ATTEMPTS - 1:
                return None
        sleep(2 ** attempt)
    return None


def kept(data: dict[str, Any]) -> dict[str, Any]:
    """What a run keeps of a generation's stats: its timings, counts and costs, and each host tried, in order."""
    attempts = [{name: tried.get(name) for name in ("provider_name", "status", "latency")} for tried in data.get("provider_responses") or []]
    return {**{name: data.get(name) for name in KEPT}, "attempts": attempts}


def gather(run: Path, key: str, *, fetch: Callable[[str, str], dict[str, Any] | None] = fetch,
           out: TextIO = sys.stdout) -> tuple[int, int]:
    """Fetch the stats of every answered call the run holds none for. Returns how many it fetched, and how many
    OpenRouter had none for."""
    pending = []
    for response in sorted(run.rglob("calls/*.response.json")):
        beside = response.with_name(response.name.replace(".response.json", ".generation.json"))
        id = _object(response).get("id")
        if id and not beside.exists():
            pending.append((id, beside))

    def one(id: str, beside: Path) -> bool:
        data = fetch(id, key)
        if data:
            beside.write_text(json.dumps(kept(data), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return bool(data)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        found = list(pool.map(lambda pair: one(*pair), pending))
    fetched, missing = sum(found), len(found) - sum(found)
    print(f"generations: {fetched} fetched" + (f", {missing} not there; fetch again with generations.py {run}" if missing else ""), file=out)
    return fetched, missing


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", help="a run's folder, such as results/<run-id>")
    run = Path(parser.parse_args(argv).run)
    key_env = config.load(run / "bench.toml").key_env
    if not os.environ.get(key_env):
        print(f"{key_env} is not set: run it with uv run --env-file .env generations.py {run}", file=sys.stderr)
        return 2
    _, missing = gather(run, os.environ[key_env])
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
