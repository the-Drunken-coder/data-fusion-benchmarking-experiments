"""Inspectable local reports and conservative comparisons of matching experiments."""

import os
from collections import Counter, defaultdict
from math import sqrt
from pathlib import Path

import numpy as np

from .storage import data_root, encode, read_json, read_lines, verify


def trajectory_plot(destination: Path, truth: list[dict], outputs: list[dict]) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(data_root() / "cache" / "matplotlib"))
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    figure, axis = plt.subplots(figsize=(8, 5))
    for frames, field, id_field, style, label in (
        (truth, "objects", "truth_id", "-", "Truth"),
        (outputs, "tracks", "track_id", "--", "Estimate"),
    ):
        points = defaultdict(list)
        for frame in frames:
            for obj in frame[field]:
                points[obj[id_field]].append(obj["position_m"])
        for index, values in enumerate(points.values()):
            values = np.asarray(values)
            axis.plot(
                values[:, 0],
                values[:, 1],
                style,
                alpha=0.8,
                color="#176452" if field == "objects" else "#b5612d",
                label=label if index == 0 else None,
            )
    axis.set(xlabel="x (m)", ylabel="y (m)", title="Recorded trajectories")
    axis.set_aspect("equal", adjustable="datalim")
    axis.grid(alpha=0.2)
    if axis.lines:
        axis.legend()
    figure.tight_layout()
    figure.savefig(destination, metadata={"Date": None})
    plt.close(figure)


def aggregate(runs: list[dict]) -> dict:
    summaries = [run["summary"] for run in runs]
    matched = sum(s["matched_states"] for s in summaries)
    eligible = sum(s["eligible_states"] for s in summaries)
    ticks = sum(s["scored_ticks"] for s in summaries)
    result = {
        key: sum(s[key] for s in summaries)
        for key in (
            "matched_states",
            "eligible_states",
            "missed_states",
            "false_states",
            "identity_switches",
        )
    }
    result.update(
        run_count=len(runs),
        mean_gospa_m=sum(s["mean_gospa_m"] * s["scored_ticks"] for s in summaries) / ticks
        if ticks
        else None,
        position_rmse_m=sqrt(
            sum((s["position_rmse_m"] or 0) ** 2 * s["matched_states"] for s in summaries) / matched
        )
        if matched
        else None,
        coverage=matched / eligible if eligible else None,
        run_gospa_std_m=float(np.std([s["mean_gospa_m"] for s in summaries]))
        if summaries
        else None,
    )
    return result


def compare(runs: list[dict]) -> dict:
    """Refuse rankings across different streams, task modes, scoring rules, or failed runs."""
    reasons = []
    if not runs:
        return {"comparable": False, "reasons": ["No runs selected"], "systems": []}
    if len({run["run_id"] for run in runs}) != len(runs):
        reasons.append("The same run cannot count as multiple repetitions")
    if any(run["status"] != "complete" for run in runs):
        reasons.append("Selection contains failed or incomplete runs")
    if len({run["mode"] for run in runs}) != 1:
        reasons.append("Oracle grouped control and ungrouped tracking are different tasks")
    if len({(run.get("evaluator_sha256"), encode(run["scoring"])) for run in runs}) != 1:
        reasons.append("Evaluator implementation or scoring rules differ")
    groups = defaultdict(list)
    for run in runs:
        groups[(run["system"]["id"], run["system_hash"])].append(run)
    case_multisets = [
        Counter((run["case_id"], run["case_hash"]) for run in values) for values in groups.values()
    ]
    if any(value != case_multisets[0] for value in case_multisets):
        reasons.append("Systems do not have the same cases and repetition counts")
    systems = []
    if not reasons:
        for (system_id, checksum), values in groups.items():
            scenarios = defaultdict(list)
            for run in values:
                scenarios[run["config"]["scenario"]].append(run)
            systems.append(
                {
                    "system_id": system_id,
                    "system_hash": checksum,
                    "summary": aggregate(values),
                    "per_scenario": {key: aggregate(value) for key, value in scenarios.items()},
                }
            )
    return {
        "comparable": not reasons,
        "reasons": reasons,
        "systems": systems,
        "runs": [
            {"run_id": run["run_id"], "status": run["status"], "failure": run["failure"]}
            for run in runs
        ],
    }


def load_run(run_id: str, root: Path | None = None) -> dict:
    path = (root or data_root()) / "runs" / run_id
    if (path / "manifest.json").exists():
        verify(path, read_json(path / "manifest.json")["hashes"])
    return read_json(path / "result.json")


def run_detail(run_id: str, root: Path | None = None) -> dict:
    root = root or data_root()
    path = root / "runs" / run_id
    result = load_run(run_id, root)
    case = root / "cases" / result["case_id"]
    return {
        "result": result,
        "truth": read_lines(case / "private" / "truth.jsonl"),
        "outputs": read_lines(path / "outputs.jsonl") if (path / "outputs.jsonl").exists() else [],
        "requests": read_lines(path / "requests.jsonl"),
        "metrics": read_json(path / "metrics.json") if (path / "metrics.json").exists() else None,
        "timing": read_lines(path / "timing.jsonl") if (path / "timing.jsonl").exists() else [],
    }
