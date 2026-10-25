"""Score semantics and eligibility, independent of the web display."""

from copy import deepcopy
from math import sqrt
from pathlib import Path

import pytest

from fusion_bench import benchmark, server
from fusion_bench.schema import BenchmarkRequest
from fusion_bench.storage import digest, encode, read_json
from fusion_bench.systems import load_systems


@pytest.mark.parametrize(
    "error,reference,expected",
    [(0, 10, 100), (10, 10, 0), (25, 10, 0), (5, 10, 50), (sqrt(50), sqrt(50), 0)],
)
def test_points_have_fixed_anchors(error, reference, expected):
    assert benchmark.points(error, reference) == expected


@pytest.mark.parametrize(
    "error,reference", [(float("nan"), 10), (-1, 10), (1, 0), (1, float("inf"))]
)
def test_invalid_score_inputs_rejected(error, reference):
    with pytest.raises(ValueError):
        benchmark.points(error, reference)


@pytest.fixture(scope="module")
def suite_store(tmp_path_factory):
    root = tmp_path_factory.mktemp("fixed-suite")
    return root, benchmark.prepare_suite(root)


def test_suite_is_repeatable_and_complete(suite_store):
    root, suite = suite_store
    assert benchmark.prepare_suite(root) == suite
    assert len(suite["cases"]) == 28
    benchmark.validate_suite(suite, root)
    assert all(c["manifest"]["config"]["partition"] == "evaluation" for c in suite["cases"])


@pytest.mark.parametrize("change", ["fingerprint", "tuning", "reference", "duplicate", "code"])
def test_suite_drift_is_rejected(suite_store, change):
    root, original = suite_store
    suite = deepcopy(original)
    if change == "fingerprint":
        suite["timeout_s"] = 100
    elif change == "tuning":
        suite["cases"][0]["manifest"]["config"]["partition"] = "tuning"
    elif change == "reference":
        suite["cases"][0]["empty_gospa_m"] += 1
    elif change == "duplicate":
        suite["cases"][0] = suite["cases"][1]
    else:
        suite["implementation_sha256"] = "changed"
    if change != "fingerprint":
        suite["suite_id"] = digest(
            encode({k: v for k, v in suite.items() if k != "suite_id"}).encode()
        )
    with pytest.raises(ValueError):
        benchmark.validate_suite(suite, root)


@pytest.fixture
def scoring_fixture(suite_store, monkeypatch):
    root, suite = suite_store
    spec = load_systems()["nearest"][0].model_dump()
    system = {"spec": spec, "system_hash": "preserved"}
    slots, details = [], {}
    for attempt in range(3):
        for index, case in enumerate(suite["cases"]):
            manifest = case["manifest"]
            run_id = f"{attempt:01x}{index:015x}"
            slots.append({"case_id": manifest["case_id"], "attempt": attempt, "run_id": run_id})
            # Clean scenario earns 100/50/0 across attempts. All other scenarios earn 0.
            error = case["empty_gospa_m"]
            if manifest["config"]["scenario"] == "clean":
                error *= attempt / 2
            summary = dict(
                mean_gospa_m=error,
                matched_states=0,
                eligible_states=121,
                missed_states=121,
                false_states=0,
                identity_switches=0,
                position_rmse_m=None,
                scored_ticks=121,
                expected_ticks=121,
            )
            run = dict(
                run_id=run_id,
                status="complete",
                case_id=manifest["case_id"],
                system=spec,
                system_hash="preserved",
                mode="ungrouped",
                scoring=manifest["scoring"],
                evaluator_sha256=manifest["evaluator_sha256"],
                environment=suite["environment"],
                timeout_s=5.0,
                init_timeout_s=30.0,
                successful_steps=121,
                config=manifest["config"],
                summary=summary,
            )
            details[run_id] = {
                "result": run,
                "outputs": [{"step_id": i, "time_ms": i * 500} for i in range(121)],
                "timing": [{"latency_ms": 1.0}] * 121,
            }
    # Focus these tests on eligibility and arithmetic. Disk integrity has its own tests.
    monkeypatch.setattr(benchmark, "verify", lambda *args: None)
    original_read = benchmark.read_json
    monkeypatch.setattr(
        benchmark,
        "read_json",
        lambda path: {"hashes": {}}
        if Path(path).parent.parent.name == "runs"
        else original_read(path),
    )
    monkeypatch.setattr(benchmark, "run_detail", lambda run_id, root: deepcopy(details[run_id]))
    return root, suite, system, slots, details


def test_equal_scenario_weight_and_repeat_range(scoring_fixture):
    root, suite, system, slots, _ = scoring_fixture
    result = benchmark.score_system(suite, system, slots, root)
    assert result["score"] == pytest.approx(50 / 7)
    assert result["attempt_scores"] == pytest.approx([100 / 7, 50 / 7, 0])
    assert result["range"] == pytest.approx({"min": 0, "max": 100 / 7})
    assert result["scenarios"][0]["score"] == 50
    assert len(result["runs"]) == 84


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate_slot",
        "duplicate_run",
        "unfilled",
        "failed",
        "prefix",
        "grouped",
        "version",
        "budget",
    ],
)
def test_ineligible_runs_never_get_headline(scoring_fixture, change):
    root, suite, system, slots, details = scoring_fixture
    run = details[slots[0]["run_id"]]["result"]
    if change == "missing":
        slots.pop()
    elif change == "duplicate_slot":
        slots[-1] = slots[0]
    elif change == "duplicate_run":
        slots[-1]["run_id"] = slots[0]["run_id"]
    elif change == "unfilled":
        slots[-1]["run_id"] = None
    elif change == "failed":
        run["status"] = "failed"
    elif change == "prefix":
        details[slots[0]["run_id"]]["outputs"].pop()
    elif change == "grouped":
        run["mode"] = "grouped"
    elif change == "version":
        run["system_hash"] = "another-version"
    else:
        run["timeout_s"] = 50
    with pytest.raises(ValueError):
        benchmark.score_system(suite, system, slots, root)


def test_candidate_is_preserved_and_failure_has_no_score(tmp_path, monkeypatch):
    original_prepare = benchmark.prepare_suite
    monkeypatch.setattr(benchmark, "prepare_suite", lambda root: original_prepare(root))
    calls = []

    def fail(case_id, system_id, **kwargs):
        assert kwargs["system_source"] != load_systems()[system_id][1]
        assert (kwargs["system_source"] / "system.json").exists()
        calls.append(case_id)
        return {
            "run_id": "failed-run",
            "case_id": case_id,
            "status": "failed",
            "failure": "timeout",
        }

    monkeypatch.setattr(benchmark, "run_candidate", fail)
    report = benchmark.run_benchmark(["nearest"], root=tmp_path)
    assert len(calls) == 1
    assert report["status"] == "failed"
    assert report["systems"][0]["result"] is None
    folder = tmp_path / "benchmarks/evaluations" / report["evaluation_id"]
    plan = read_json(folder / "plan.json")
    assert all(slot["run_id"] is None for slot in plan["systems"][0]["slots"])
    assert len(plan["systems"][0]["slots"]) == 84


def test_benchmark_launch_releases_lock_after_failure(tmp_path, monkeypatch):
    import threading
    from unittest.mock import Mock

    monkeypatch.setenv("FUSION_DATA", str(tmp_path))
    monkeypatch.setattr(server, "execution_lock", threading.Lock())
    worker = Mock()
    monkeypatch.setattr(server.threading, "Thread", worker)
    monkeypatch.setattr(server, "run_benchmark", Mock(side_effect=RuntimeError("disk full")))
    job = server.launch_benchmark(BenchmarkRequest(system_ids=["nearest"]))
    assert job["requested"] == 84
    worker.call_args.kwargs["target"]()
    assert not server.execution_lock.locked()
    saved = read_json(tmp_path / "jobs" / f"{job['job_id']}.json")
    assert saved["status"] == "failed" and saved["error"] == "disk full"
