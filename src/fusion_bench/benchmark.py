"""Fixed benchmark membership, preserved candidates, and auditable reconstruction points."""

from collections import Counter
from datetime import datetime, timezone
from math import isfinite, sqrt
from pathlib import Path
from statistics import mean
from typing import Callable
import uuid
import os

import numpy as np

from .generate import SCORING, generate
from .report import aggregate, run_detail
from .runner import run_candidate
from .schema import SCENARIOS, CaseConfig
from .storage import (
    data_root,
    digest,
    encode,
    environment,
    hashes,
    load_case,
    read_json,
    read_lines,
    verify,
    write_json,
)
from .systems import load_systems, snapshot_system

SEEDS = (1000, 1001, 1002, 1003)
ATTEMPTS = 3
TIMEOUT = 5.0
INIT_TIMEOUT = 30.0


def points(error: float, reference: float) -> float:
    """Normalize against an empty tracker; floor worse-than-empty runs at zero."""
    if not isfinite(error) or error < 0 or not isfinite(reference) or reference <= 0:
        raise ValueError("Score requires a finite nonnegative error and positive reference")
    return 100 * max(0.0, 1 - error / reference)


def prepare_suite(root: Path) -> dict:
    cases = []
    for scenario in SCENARIOS:
        for seed in SEEDS:
            manifest = generate(
                CaseConfig(scenario=scenario, seed=seed, partition="evaluation"), root
            )
            truth = read_lines(root / "cases" / manifest["case_id"] / "private/truth.jsonl")
            reference = mean(sqrt(50 * len(frame["objects"])) for frame in truth)
            points(0, reference)
            cases.append({"manifest": manifest, "empty_gospa_m": reference})
    definition = {
        "name": "Numeric tracking v1",
        "version": 1,
        "mode": "ungrouped",
        "attempts": ATTEMPTS,
        "seeds": list(SEEDS),
        "scenarios": list(SCENARIOS),
        "formula": "mean_scenarios(mean_cases(100*max(0,1-mean_gospa/empty_gospa)))",
        "timeout_s": TIMEOUT,
        "init_timeout_s": INIT_TIMEOUT,
        "implementation_sha256": digest(Path(__file__).read_bytes()),
        "runner_sha256": digest(Path(__file__).with_name("runner.py").read_bytes()),
        "environment": environment(),
        "cases": cases,
    }
    suite_id = digest(encode(definition).encode())
    suite = {**definition, "suite_id": suite_id}
    path = root / "benchmarks/suites" / f"{suite_id}.json"
    if path.exists():
        if read_json(path) != suite:
            raise ValueError("Saved benchmark definition changed")
    else:
        write_json(path, suite)
    return suite


def validate_suite(suite: dict, root: Path) -> None:
    definition = {key: value for key, value in suite.items() if key != "suite_id"}
    if digest(encode(definition).encode()) != suite["suite_id"]:
        raise ValueError("Benchmark fingerprint does not match its definition")
    if (
        suite["implementation_sha256"] != digest(Path(__file__).read_bytes())
        or suite["runner_sha256"] != digest(Path(__file__).with_name("runner.py").read_bytes())
        or suite["environment"] != environment()
    ):
        raise ValueError("Benchmark implementation or environment changed; create a new evaluation")
    expected = Counter((scenario, seed) for scenario in SCENARIOS for seed in SEEDS)
    actual = Counter(
        (c["manifest"]["config"]["scenario"], c["manifest"]["config"]["seed"])
        for c in suite["cases"]
    )
    if (
        actual != expected
        or suite["attempts"] != ATTEMPTS
        or suite["mode"] != "ungrouped"
        or suite["timeout_s"] != TIMEOUT
        or suite["init_timeout_s"] != INIT_TIMEOUT
    ):
        raise ValueError("Benchmark membership or execution budget changed")
    for case in suite["cases"]:
        manifest = case["manifest"]
        folder = root / "cases" / manifest["case_id"]
        if load_case(folder, manifest["case_id"]) != manifest:
            raise ValueError("Benchmark case changed")
        config = manifest["config"]
        expected_config = CaseConfig(
            scenario=config["scenario"], seed=config["seed"], partition="evaluation"
        ).model_dump()
        if config != expected_config or manifest["scoring"] != SCORING:
            raise ValueError("Only fixed evaluation cases with the declared scoring are eligible")
        truth = read_lines(folder / "private/truth.jsonl")
        if [frame["time_ms"] for frame in truth] != list(range(0, 60001, 500)):
            raise ValueError("Benchmark truth timeline is incomplete")
        reference = mean(sqrt(50 * len(frame["objects"])) for frame in truth)
        if case["empty_gospa_m"] != reference:
            raise ValueError("Empty-tracker reference changed")


def score_system(suite: dict, system: dict, slots: list[dict], root: Path) -> dict:
    """Require every declared case/attempt exactly once before returning any headline."""
    validate_suite(suite, root)
    cases = {case["manifest"]["case_id"]: case for case in suite["cases"]}
    expected = Counter((attempt, case_id) for attempt in range(ATTEMPTS) for case_id in cases)
    if Counter((slot["attempt"], slot["case_id"]) for slot in slots) != expected:
        raise ValueError("Missing or duplicate benchmark case/attempt slots")
    ids = [slot.get("run_id") for slot in slots]
    if None in ids or len(set(ids)) != len(ids):
        raise ValueError("Every required slot needs a distinct completed run")
    records, runs, latencies = [], [], []
    for slot in slots:
        run_id = slot["run_id"]
        folder = root / "runs" / run_id
        verify(folder, read_json(folder / "manifest.json")["hashes"])
        detail = run_detail(run_id, root)
        run = detail["result"]
        manifest = cases[slot["case_id"]]["manifest"]
        if (
            run["status"] != "complete"
            or run["case_id"] != slot["case_id"]
            or run["system_hash"] != system["system_hash"]
            or run["system"] != system["spec"]
            or run["mode"] != "ungrouped"
            or run["scoring"] != manifest["scoring"]
            or run["evaluator_sha256"] != manifest["evaluator_sha256"]
            or run["environment"] != suite["environment"]
            or run["timeout_s"] != suite["timeout_s"]
            or run["init_timeout_s"] != suite["init_timeout_s"]
        ):
            raise ValueError(f"Run {run_id} is not eligible for this benchmark/system version")
        ticks = run["summary"]
        timeline = [(i, i * 500) for i in range(121)]
        if (
            [(f["step_id"], f["time_ms"]) for f in detail["outputs"]] != timeline
            or ticks["scored_ticks"] != 121
            or ticks["expected_ticks"] != 121
            or run["successful_steps"] != 121
        ):
            raise ValueError(f"Run {run_id} has an incomplete timeline")
        value = points(ticks["mean_gospa_m"], cases[slot["case_id"]]["empty_gospa_m"])
        records.append(
            {
                **slot,
                "scenario": run["config"]["scenario"],
                "seed": run["config"]["seed"],
                "score": value,
                "mean_gospa_m": ticks["mean_gospa_m"],
            }
        )
        runs.append(run)
        latencies.extend(tick["latency_ms"] for tick in detail["timing"])
    attempts = [
        mean(
            mean(
                row["score"]
                for row in records
                if row["attempt"] == attempt and row["scenario"] == scenario
            )
            for scenario in SCENARIOS
        )
        for attempt in range(ATTEMPTS)
    ]
    scenarios = [
        {
            "scenario": scenario,
            "score": mean(row["score"] for row in records if row["scenario"] == scenario),
            "mean_gospa_m": mean(
                row["mean_gospa_m"] for row in records if row["scenario"] == scenario
            ),
        }
        for scenario in SCENARIOS
    ]
    return {
        "score": mean(attempts),
        "attempt_scores": attempts,
        "range": {"min": min(attempts), "max": max(attempts)},
        "scenarios": scenarios,
        "runs": records,
        "summary": aggregate(runs),
        "latency_p95_ms": float(np.percentile(latencies, 95)),
    }


def run_benchmark(
    system_ids: list[str],
    *,
    root: Path | None = None,
    evaluation_id: str | None = None,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    root = root or data_root()
    systems = load_systems(root)
    if (
        not system_ids
        or len(set(system_ids)) != len(system_ids)
        or any(s not in systems or "ungrouped" not in systems[s][0].modes for s in system_ids)
    ):
        raise ValueError("Select distinct systems supporting ungrouped tracking")
    evaluation_id = evaluation_id or uuid.uuid4().hex[:16]
    folder = root / "benchmarks/evaluations" / evaluation_id
    folder.mkdir(parents=True, exist_ok=False)
    report = {
        "evaluation_id": evaluation_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "suite_id": None,
        "name": "Numeric tracking v1",
        "systems": [],
        "error": None,
        "owner_pid": os.getpid(),
    }
    write_json(folder / "report.json", report)
    try:
        suite = prepare_suite(root)
        report["suite_id"] = suite["suite_id"]
        for system_id in system_ids:
            spec, source = systems[system_id]
            checksum = snapshot_system(source, folder / "systems" / system_id)
            report["systems"].append(
                {
                    "spec": spec.model_dump(),
                    "system_hash": checksum,
                    "status": "running",
                    "error": None,
                    "result": None,
                    "slots": [
                        {"case_id": c["manifest"]["case_id"], "attempt": a, "run_id": None}
                        for a in range(ATTEMPTS)
                        for c in suite["cases"]
                    ],
                }
            )
        write_json(
            folder / "plan.json", {"suite_id": suite["suite_id"], "systems": report["systems"]}
        )
        write_json(folder / "report.json", report)
        for system in report["systems"]:
            try:
                for slot in system["slots"]:
                    run = run_candidate(
                        slot["case_id"],
                        system["spec"]["id"],
                        root=root,
                        timeout=TIMEOUT,
                        init_timeout=INIT_TIMEOUT,
                        system_source=folder / "systems" / system["spec"]["id"],
                    )
                    slot["run_id"] = run["run_id"]
                    write_json(folder / "report.json", report)
                    if progress:
                        progress(run)
                    if run["status"] != "complete":
                        raise ValueError(f"Run {run['run_id']} failed: {run['failure']}")
                system["result"] = score_system(suite, system, system["slots"], root)
                system["status"] = "complete"
            except Exception as error:
                system.update(status="failed", error=str(error), result=None)
            write_json(folder / "report.json", report)
        report["status"] = (
            "complete" if all(s["status"] == "complete" for s in report["systems"]) else "failed"
        )
    except Exception as error:
        report.update(status="failed", error=str(error))
        for system in report["systems"]:
            if system["status"] == "running":
                system.update(status="failed", error=str(error), result=None)
    write_json(folder / "report.json", report)
    write_json(folder / "manifest.json", {"hashes": hashes(folder)})
    return report
