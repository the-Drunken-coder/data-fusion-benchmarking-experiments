import json
import threading
from unittest.mock import Mock

import pytest

from fusion_bench import cli, server
from fusion_bench.generate import generate
from fusion_bench.report import run_detail
from fusion_bench.runner import run_candidate
from fusion_bench.schema import CaseConfig, ExperimentRequest
from fusion_bench.storage import (
    case_identifier,
    hashes,
    load_case,
    read_json,
    verify,
    write_json,
)


def test_config_file_replaces_conflicting_flags(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FUSION_DATA", str(tmp_path))
    config = tmp_path / "config.json"
    write_json(config, {"scenario": "clean", "seed": 101})
    monkeypatch.setattr(
        "sys.argv", ["fusion", "generate", "--config", str(config), "--seed", "2000"]
    )
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["config"]["seed"] == 101
    assert result["config"]["partition"] == "tuning"
    assert load_case(tmp_path / "cases" / result["case_id"], result["case_id"]) == result


@pytest.fixture
def launch_context(tmp_path, monkeypatch):
    monkeypatch.setenv("FUSION_DATA", str(tmp_path))
    monkeypatch.setattr(server, "execution_lock", threading.Lock())
    worker = Mock()
    monkeypatch.setattr(server.threading, "Thread", worker)
    monkeypatch.setattr(server, "generate", lambda config: {"case_id": "case"})
    monkeypatch.setattr(
        server, "run_candidate", lambda *args: {"run_id": "run", "status": "complete"}
    )
    return ExperimentRequest(config=CaseConfig(), system_ids=["nearest"]), worker


@pytest.mark.parametrize("failure", ["initial_write", "thread_start"])
def test_failed_launch_releases_lock_and_allows_retry(
    launch_context, tmp_path, monkeypatch, failure
):
    request, worker = launch_context
    if failure == "initial_write":
        monkeypatch.setattr(server, "write_json", Mock(side_effect=OSError("disk full")))
    else:
        worker.return_value.start.side_effect = RuntimeError("cannot start worker")
    with pytest.raises((OSError, RuntimeError)):
        server.launch(request)
    assert not server.execution_lock.locked()
    if failure == "thread_start":
        assert read_json(next((tmp_path / "jobs").glob("*.json")))["status"] == "failed"

    monkeypatch.setattr(server, "write_json", write_json)
    worker.return_value.start.side_effect = None
    response = server.launch(request)
    assert response["status"] == "running"
    assert server.execution_lock.locked()
    worker.call_args.kwargs["target"]()
    assert not server.execution_lock.locked()
    assert read_json(tmp_path / "jobs" / f"{response['job_id']}.json")["status"] == "complete"


def test_launch_response_is_snapshot_even_if_worker_finishes_during_start(launch_context, tmp_path):
    request, worker = launch_context
    worker.return_value.start.side_effect = lambda: worker.call_args.kwargs["target"]()
    response = server.launch(request)
    assert response["status"] == "running"
    assert response["case_id"] is None
    assert response["run_ids"] == []
    persisted = read_json(tmp_path / "jobs" / f"{response['job_id']}.json")
    assert persisted["status"] == "complete"
    assert persisted["run_ids"] == ["run"]
    assert not server.execution_lock.locked()


def test_worker_releases_lock_even_when_final_status_write_fails(launch_context, monkeypatch):
    request, worker = launch_context
    server.launch(request)
    monkeypatch.setattr(server, "write_json", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        worker.call_args.kwargs["target"]()
    assert not server.execution_lock.locked()


@pytest.mark.parametrize(
    "mutation", ["config", "scoring", "metadata", "omitted_hash", "rewritten_hash", "new_id"]
)
def test_case_descriptor_tampering_rejected_before_execution(tmp_path, mutation):
    config = CaseConfig(scenario="clean")
    manifest = generate(config, tmp_path)
    original_id = manifest["case_id"]
    folder = tmp_path / "cases" / original_id
    manifest = read_json(folder / "manifest.json")
    if mutation == "config":
        manifest["config"]["seed"] = 101
    elif mutation == "scoring":
        manifest["scoring"]["gospa_c_m"] = 25
    elif mutation == "metadata":
        manifest["observation_count"] = 0
    else:
        (folder / "public/observations.jsonl").write_text("")
        if mutation == "omitted_hash":
            del manifest["hashes"]["public/observations.jsonl"]
        else:
            manifest["hashes"] = hashes(folder)
        if mutation == "new_id":
            manifest["case_id"] = case_identifier(manifest)
    write_json(folder / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Case identity changed"):
        run_candidate(original_id, "nearest", root=tmp_path)
    with pytest.raises(ValueError, match="Case identity changed"):
        generate(config, tmp_path)
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("mutation", ["extra_file", "missing_file", "omitted_hash"])
def test_verification_requires_complete_file_inventory(tmp_path, mutation):
    manifest = generate(CaseConfig(scenario="clean"), tmp_path)
    folder = tmp_path / "cases" / manifest["case_id"]
    if mutation == "extra_file":
        (folder / "unexpected.json").write_text("{}")
    elif mutation == "missing_file":
        (folder / "private/truth.jsonl").unlink()
    else:
        del manifest["hashes"]["private/truth.jsonl"]
    with pytest.raises(ValueError, match="Artifact changed"):
        verify(folder, manifest["hashes"])


def test_legacy_playback_remains_available_but_cannot_run_new_experiments(tmp_path):
    manifest = generate(CaseConfig(scenario="clean"), tmp_path)
    result = run_candidate(manifest["case_id"], "nearest", root=tmp_path)
    folder = tmp_path / "cases" / manifest["case_id"]
    # Represent an earlier case whose identity did not bind its complete descriptor.
    del manifest["case_format"]
    write_json(folder / "manifest.json", manifest)
    detail = run_detail(result["run_id"], tmp_path)
    assert detail["result"] == result
    assert detail["init"] == read_json(tmp_path / "runs" / result["run_id"] / "init.json")
    assert "seed" not in detail["init"]
    assert "truth" not in detail["init"]
    with pytest.raises(ValueError, match="regenerate"):
        run_candidate(manifest["case_id"], "nearest", root=tmp_path)
    manifest["config"]["seed"] = 101
    write_json(folder / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Case changed since this run"):
        run_detail(result["run_id"], tmp_path)
