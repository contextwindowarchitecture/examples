"""Running the suite: where a run's results go. The model is replaced by one fixed reply, so no provider is called."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import evals
import providers


def test_a_run_writes_its_results_where_out_says(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A run against some other model, such as the benchmark's, stays out of evals/results/: the suite checks every
    # folder there against its committed report.
    suite = json.loads(evals.CASES.read_text(encoding="utf-8"))
    suite["cases"] = [case for case in suite["cases"] if case["id"] == "export-backup"]
    (tmp_path / "cases.json").write_text(json.dumps(suite), encoding="utf-8")
    monkeypatch.setattr(evals, "CASES", tmp_path / "cases.json")
    monkeypatch.setattr(evals, "RESULTS", tmp_path / "results")
    monkeypatch.setenv("DOCS_QA_STORE", str(tmp_path / "store.sqlite"))
    monkeypatch.setattr(providers, "chat", lambda *args: providers.Reply("Export it from Settings [help:data-export@6#2]."))
    out = tmp_path / "out"
    assert evals.main(["run", "--provider", "openai", "--model", "vendor/model", "--out", str(out)]) == 0
    assert json.loads((out / "meta.json").read_text(encoding="utf-8"))["model"] == "vendor/model"
    assert (out / "export-backup" / "turn-1" / "payload.json").exists()
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["result"] == "1 of 1 cases passed"
    assert not (tmp_path / "results").exists()


def test_out_and_label_name_the_same_folder_so_only_one_is_allowed(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        evals.main(["run", "--out", "somewhere", "--label", "something"])
    assert "not allowed with argument" in capsys.readouterr().err
