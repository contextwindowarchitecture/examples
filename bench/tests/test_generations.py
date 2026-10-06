"""What OpenRouter recorded about each call, kept beside the call. No network: the fetch is replaced."""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import generations
from test_checks import write

REPLY = {
    "id": "gen-1", "created_at": "2026-10-02T22:13:12.053Z", "model": "vendor/model-20260813", "provider_name": "SomeHost",
    "latency": 812, "generation_time": 3861, "moderation_latency": None, "tokens_prompt": 288, "tokens_completion": 230,
    "native_tokens_prompt": 1512, "native_tokens_completion": 226, "native_tokens_reasoning": 178, "native_tokens_cached": 1152,
    "finish_reason": "stop", "native_finish_reason": "completed", "streamed": True, "cancelled": False, "total_cost": 0.002652,
    "cache_discount": 0.0011, "upstream_inference_cost": 0, "service_tier": None, "data_region": "global",
    "provider_responses": [{"endpoint_id": "65367950", "id": "chatcmpl-1", "provider_name": "OtherHost", "status": 429, "latency": 90},
                           {"endpoint_id": "75367950", "id": "chatcmpl-2", "provider_name": "SomeHost", "status": 200, "latency": 812}],
    # What a run has no use for, and so does not keep.
    "workspace_id": "ws-secret", "request_id": "req-secret", "upstream_id": "up-secret", "user_agent": "OpenAI/Python", "app_id": 7,
}


def responded(run: Path, job: str, call: int, body: dict[str, Any]) -> Path:
    path = run / job / "calls" / f"{call}.response.json"
    write(path, body)
    return path


def test_each_calls_stats_are_kept_beside_it_without_what_names_the_account(tmp_path: Path) -> None:
    response = responded(tmp_path, "vendor-model/01-docs-qa/01-answer/after/1", 1, {"id": "gen-1", "choices": [{"index": 0}]})
    asked = []
    fetched, missing = generations.gather(tmp_path, "sk-or-real", fetch=lambda id, key: asked.append((id, key)) or REPLY, out=io.StringIO())
    assert (fetched, missing, asked) == (1, 0, [("gen-1", "sk-or-real")])
    kept = json.loads(response.with_name("1.generation.json").read_text())
    assert (kept["latency"], kept["generation_time"], kept["tokens_prompt"], kept["native_tokens_prompt"]) == (812, 3861, 288, 1512)
    # Each host tried, in order: the one that refused and the one that answered.
    assert kept["attempts"] == [{"provider_name": "OtherHost", "status": 429, "latency": 90},
                                {"provider_name": "SomeHost", "status": 200, "latency": 812}]
    assert set(kept) == {*generations.KEPT, "attempts"}
    written = response.with_name("1.generation.json").read_text()
    assert not any(secret in written for secret in ("ws-secret", "req-secret", "up-secret", "sk-or-real", "65367950", "chatcmpl"))


def test_what_a_run_already_holds_is_not_fetched_again_and_what_openrouter_lacks_is_reported(tmp_path: Path) -> None:
    held = responded(tmp_path, "vendor-model/01-docs-qa/01-answer/after/1", 1, {"id": "gen-1", "choices": [{"index": 0}]})
    write(held.with_name("1.generation.json"), {"latency": 1})
    gone = responded(tmp_path, "vendor-model/01-docs-qa/01-answer/after/1", 2, {"id": "gen-2", "choices": [{"index": 0}]})
    responded(tmp_path, "vendor-model/01-docs-qa/01-answer/after/1", 3, {"error": {"message": "rate limited"}})  # never answered: no id
    # An error can carry an id too, and OpenRouter keeps no stats for it: there was no generation.
    responded(tmp_path, "vendor-model/01-docs-qa/01-answer/after/1", 4, {"id": "gen-4", "error": {"message": "Upstream error", "code": 502}})
    asked = []
    out = io.StringIO()
    fetched, missing = generations.gather(tmp_path, "key", fetch=lambda id, key: asked.append(id), out=out)
    assert (fetched, missing, asked) == (0, 1, ["gen-2"])
    assert not gone.with_name("2.generation.json").exists() and json.loads(held.with_name("1.generation.json").read_text()) == {"latency": 1}
    assert "1 not there" in out.getvalue()
