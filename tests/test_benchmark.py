import json
import sys
from pathlib import Path

import pytest

from fusion_bench.evaluate import evaluate
from fusion_bench.generate import SCORING, generate
from fusion_bench.report import compare
from fusion_bench.runner import requests, run_candidate
from fusion_bench.schema import CaseConfig, Snapshot
from fusion_bench.storage import read_json, read_lines, write_json


def truth(time, positions):
    return {
        "time_ms": time,
        "objects": [
            {"truth_id": key, "position_m": position, "velocity_mps": [0, 0]}
            for key, position in positions.items()
        ],
    }


def output(time, positions):
    return {
        "type": "tracks",
        "schema_version": 1,
        "step_id": time // 500,
        "time_ms": time,
        "tracks": [
            {"track_id": key, "position_m": position} for key, position in positions.items()
        ],
    }


@pytest.mark.parametrize(
    "actual,estimated,expected",
    [
        ({"a": [0, 0]}, {"x": [0, 0]}, (0, 0, 0, 0)),
        ({"a": [0, 0]}, {}, (50**0.5, 0, 50, 0)),
        ({}, {"x": [0, 0]}, (50**0.5, 0, 0, 50)),
        ({"a": [0, 0]}, {"x": [0, 0], "y": [0, 0]}, (50**0.5, 0, 0, 50)),
        ({"a": [0, 0]}, {"x": [3, 4]}, (5, 25, 0, 0)),
        ({}, {}, (0, 0, 0, 0)),
    ],
)
def test_hand_calculated_gospa(actual, estimated, expected):
    result = evaluate([truth(0, actual)], [output(0, estimated)], SCORING)
    values = result["ticks"][0]["gospa"]
    assert [
        values[key] for key in ("distance", "localisation", "missed", "false")
    ] == pytest.approx(expected)
    if not actual or not estimated:
        assert result["summary"]["position_rmse_m"] is None


def test_identity_swaps_are_not_hidden_by_perfect_positions():
    frames = [truth(t, {"a": [0, 0], "b": [30, 0]}) for t in (0, 500)]
    correct = [output(t, {"x": [0, 0], "y": [30, 0]}) for t in (0, 500)]
    swapped = [correct[0], output(500, {"y": [0, 0], "x": [30, 0]})]
    assert evaluate(frames, correct, SCORING)["summary"]["identity_switches"] == 0
    result = evaluate(frames, swapped, SCORING)["summary"]
    assert result["identity_switches"] == 2
    assert result["mean_gospa_m"] == 0
    assert result["mota"] == 0.5


def test_previous_association_survives_a_closer_neighbor():
    frames = [truth(t, {"a": [0, 0], "b": [4, 0]}) for t in (0, 500)]
    outputs = [output(0, {"x": [0, 0], "y": [4, 0]}), output(500, {"x": [3, 0], "y": [1, 0]})]
    result = evaluate(frames, outputs, SCORING)
    assert result["summary"]["identity_switches"] == 0
    assert result["ticks"][1]["matches"][0]["track_id"] == "x"


def test_generation_is_reproducible_private_and_causal(tmp_path):
    config = CaseConfig(scenario="delayed", seed=202)
    left, right = generate(config, tmp_path / "left"), generate(config, tmp_path / "right")
    assert left == right
    path = tmp_path / "left" / "cases" / left["case_id"]
    init = read_json(path / "public/init.json")
    observations = read_lines(path / "public/observations.jsonl")
    assert any(
        a["measured_at_ms"] > b["measured_at_ms"] for a, b in zip(observations, observations[1:])
    )
    messages = list(requests(init, observations, list(range(0, 60001, 500))))
    delivered = []
    for message in messages:
        for obs in message["observations"]:
            assert obs["arrived_at_ms"] <= message["time_ms"]
            assert obs["measured_at_ms"] <= obs["arrived_at_ms"]
            assert set(obs) == {
                "observation_id",
                "sensor_id",
                "measured_at_ms",
                "arrived_at_ms",
                "position_m",
                "position_cov_m2",
            }
            delivered.append(obs["observation_id"])
    assert len(delivered) == len(set(delivered))
    assert "seed" not in json.dumps(init) and "truth_" not in json.dumps(messages)
    assert any(not message["observations"] for message in messages)
    mapping = read_json(path / "private/mapping.json")
    grouped = read_lines(path / "public/grouped-observations.jsonl")
    keys = {}
    for obs in grouped:
        assert mapping[obs["observation_id"]] is not None
        keys.setdefault(mapping[obs["observation_id"]], set()).add(obs["group_key"])
    assert all(len(value) == 1 for value in keys.values())


@pytest.mark.parametrize(
    "tracks",
    [
        [{"track_id": "a", "position_m": [float("inf"), 0]}],
        [{"track_id": "a", "position_m": [0, 0]}] * 2,
    ],
)
def test_invalid_snapshots_rejected(tracks):
    with pytest.raises(ValueError):
        Snapshot.model_validate(
            dict(type="tracks", schema_version=1, step_id=0, time_ms=0, tracks=tracks)
        )


def make_candidate(root: Path, body: str):
    folder = root / "systems" / "fixture"
    folder.mkdir(parents=True)
    write_json(
        folder / "system.json",
        {
            "id": "fixture",
            "name": "Fixture",
            "version": "test",
            "command": [sys.executable, "main.py"],
        },
    )
    (folder / "main.py").write_text(body)


@pytest.mark.parametrize(
    "behavior,field",
    [
        ('print("not json", flush=True)', "invalid_outputs"),
        ("time.sleep(0.5)", "timeouts"),
        (
            'print(json.dumps(dict(type="tracks",schema_version=1,step_id=999,time_ms=m["time_ms"],tracks=[])),flush=True)',
            "invalid_outputs",
        ),
    ],
)
def test_protocol_failures_stay_failed(tmp_path, behavior, field):
    make_candidate(
        tmp_path,
        'import json,sys,time\nfor line in sys.stdin:\n m=json.loads(line)\n if m["type"]=="init": print(json.dumps(dict(type="ready",schema_version=1)),flush=True)\n else: '
        + behavior
        + "\n",
    )
    case = generate(CaseConfig(scenario="clean"), tmp_path)
    result = run_candidate(case["case_id"], "fixture", root=tmp_path, timeout=0.1)
    assert result["status"] == "failed" and result[field] == 1
    assert result["summary"]["scored_ticks"] == 0
    assert result["summary"]["position_rmse_m"] is None
    assert not compare([result])["comparable"]


def test_exact_replay_and_no_retroactive_revisions(tmp_path):
    case = generate(CaseConfig(scenario="delayed"), tmp_path)
    first = run_candidate(case["case_id"], "nearest", root=tmp_path)
    path = tmp_path / "runs" / first["run_id"]
    original = (path / "outputs.jsonl").read_bytes()
    second = run_candidate(case["case_id"], "nearest", root=tmp_path)
    other = tmp_path / "runs" / second["run_id"]
    assert first["status"] == second["status"] == "complete"
    assert original == (other / "outputs.jsonl").read_bytes()
    assert original == (path / "outputs.jsonl").read_bytes()
    assert (path / "requests.jsonl").read_bytes() == (other / "requests.jsonl").read_bytes()
    assert first["summary"] == second["summary"]
    assert not (path / "system" / "private").exists()


def test_fixed_conditions_cannot_be_changed_silently():
    with pytest.raises(ValueError, match="exploratory"):
        CaseConfig(noise_m=8)


def test_case_tampering_detected(tmp_path):
    case = generate(CaseConfig(scenario="clean"), tmp_path)
    path = tmp_path / "cases" / case["case_id"] / "public/observations.jsonl"
    path.write_text("")
    with pytest.raises(ValueError, match="Artifact changed"):
        run_candidate(case["case_id"], "nearest", root=tmp_path)


def test_reference_uses_both_sensors_without_truth_initialization():
    import importlib.util
    from fusion_bench.storage import ROOT

    spec = importlib.util.spec_from_file_location("baseline", ROOT / "systems/kalman/main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tracker = module.Tracker("ungrouped")
    assert tracker.tracks == {}
    observations = [
        {
            "sensor_id": sensor,
            "measured_at_ms": 0,
            "position_m": [x, 0],
            "position_cov_m2": [[1, 0], [0, 1]],
        }
        for sensor, x in [("a", 0), ("b", 2)]
    ]
    result = tracker.step({"time_ms": 0, "observations": observations})
    assert len(result) == 1
    assert result[0]["position_m"] == pytest.approx([1, 0])
    tracker.step({"time_ms": 2000, "observations": [dict(observations[0], measured_at_ms=1500)]})
    tracker.step({"time_ms": 3000, "observations": [dict(observations[0], measured_at_ms=1000)]})
    assert tracker.dropped == 1


def test_slow_input_consumer_cannot_bypass_timeout(tmp_path):
    from fusion_bench.runner import CandidateProcess

    script = tmp_path / "sleep.py"
    script.write_text("import time; time.sleep(5)")
    with (tmp_path / "err.log").open("wb") as err, (tmp_path / "out.bin").open("wb") as out:
        process = CandidateProcess([sys.executable, str(script)], tmp_path, err, out)
        try:
            with pytest.raises(TimeoutError):
                process.exchange({"data": "x" * 2_000_000}, 0.05)
        finally:
            process.close()


def test_task_modes_and_evaluator_versions_cannot_be_compared(tmp_path):
    case = generate(CaseConfig(scenario="clean"), tmp_path)
    run = run_candidate(case["case_id"], "nearest", root=tmp_path)
    assert not compare([run, dict(run, mode="grouped")])["comparable"]
    assert not compare([run, dict(run, evaluator_sha256="different")])["comparable"]


def test_partitions_cannot_reuse_seeds():
    with pytest.raises(ValueError, match="reserved"):
        CaseConfig(partition="evaluation", seed=100)


def test_local_api_rejects_cross_origin_launches():
    from fastapi.testclient import TestClient
    from fusion_bench.server import app

    with TestClient(app) as client:
        assert (
            client.post(
                "/api/experiments", json={}, headers={"Origin": "https://example.org"}
            ).status_code
            == 403
        )
        assert client.get("/api/runs/not-a-run").status_code == 404


def test_restart_recovers_abandoned_jobs_without_invalidating_live_cli(tmp_path, monkeypatch):
    import os
    from fastapi.testclient import TestClient
    from fusion_bench.server import app

    monkeypatch.setenv("FUSION_DATA", str(tmp_path))
    write_json(tmp_path / "jobs/live.json", {"status": "running", "owner_pid": os.getpid()})
    write_json(tmp_path / "jobs/abandoned.json", {"status": "running"})
    with TestClient(app):
        assert read_json(tmp_path / "jobs/live.json")["status"] == "running"
        assert read_json(tmp_path / "jobs/abandoned.json")["status"] == "failed"


def test_per_sensor_settings_and_outage_schedule_remain_private(tmp_path):
    from fusion_bench.schema import SensorConfig

    sensor = SensorConfig(
        sensor_id="custom",
        interval_ms=2000,
        detection_probability=1,
        noise_m=1,
        outage_start_ms=10000,
        outage_ms=4000,
        max_delay_ms=2000,
    )
    case = generate(CaseConfig(scenario="clean", kind="exploratory", sensors=[sensor]), tmp_path)
    folder = tmp_path / "cases" / case["case_id"]
    observations = read_lines(folder / "public/observations.jsonl")
    assert all(obs["measured_at_ms"] % 2000 == 0 for obs in observations)
    assert not any(10000 <= obs["measured_at_ms"] < 14000 for obs in observations)
    assert all(0 <= obs["arrived_at_ms"] - obs["measured_at_ms"] <= 2000 for obs in observations)
    assert all(obs["position_cov_m2"] == [[1, 0], [0, 1]] for obs in observations)
    init = read_json(folder / "public/init.json")
    assert set(init["sources"][0]) == {"sensor_id", "interval_ms", "coverage_m"}


def test_import_preserves_a_snapshot_when_original_source_changes(tmp_path):
    from fusion_bench.storage import ROOT
    from fusion_bench.systems import register

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    spec = read_json(ROOT / "systems/nearest/system.json")
    spec["id"] = "imported-nearest"
    write_json(bundle / "system.json", spec)
    source = (ROOT / "systems/nearest/main.py").read_bytes()
    (bundle / "main.py").write_bytes(source)
    workspace = tmp_path / "workspace"
    assert register(bundle, workspace) == "imported-nearest"
    (bundle / "main.py").write_text("raise RuntimeError('source changed')")
    case = generate(CaseConfig(scenario="clean"), workspace)
    result = run_candidate(case["case_id"], "imported-nearest", root=workspace)
    assert result["status"] == "complete"
    assert (workspace / "runs" / result["run_id"] / "system/main.py").read_bytes() == source
