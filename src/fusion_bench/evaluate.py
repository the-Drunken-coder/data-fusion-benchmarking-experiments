"""Stone Soup position-only GOSPA and the documented sequence-aware CLEAR MOT procedure."""

from datetime import datetime, timedelta
from math import sqrt

import numpy as np
from scipy.optimize import linear_sum_assignment
from stonesoup.measures import Euclidean
from stonesoup.metricgenerator.ospametric import GOSPAMetric
from stonesoup.types.state import State

ORIGIN = datetime(2000, 1, 1)


def timestamp(time_ms: int) -> datetime:
    return ORIGIN + timedelta(milliseconds=time_ms)


def clear_matches(truth: dict, tracks: dict, previous: dict, gate: float) -> dict:
    """Carry valid prior pairs forward, then Hungarian-match the remaining positions.

    This follows Stone Soup's CLEAR MOT procedure without constructing TimeRanges,
    which reject singleton associations in the pinned 1.9.1 release.
    """

    def distance(truth_id, track_id):
        return float(
            np.linalg.norm(np.array(truth[truth_id]["position_m"]) - tracks[track_id]["position_m"])
        )

    current = {
        tid: kid
        for tid, kid in sorted(previous.items())
        if tid in truth and kid in tracks and distance(tid, kid) < gate
    }
    unmatched_truth = sorted(set(truth) - set(current))
    unmatched_tracks = sorted(set(tracks) - set(current.values()))
    if unmatched_truth and unmatched_tracks:
        costs = np.array(
            [[distance(tid, kid) for kid in unmatched_tracks] for tid in unmatched_truth]
        )
        rows, columns = linear_sum_assignment(costs)
        for i, j in zip(rows, columns):
            if costs[i, j] < gate:
                current[unmatched_truth[i]] = unmatched_tracks[j]
    return current


def evaluate(truth: list[dict], outputs: list[dict], scoring: dict) -> dict:
    """Score only validated snapshots. A caller must label any incomplete prefix as partial."""
    truth_by_time = {frame["time_ms"]: frame["objects"] for frame in truth}
    gospa = GOSPAMetric(p=scoring["gospa_p"], c=scoring["gospa_c_m"], measure=Euclidean())
    ticks, previous = [], {}
    total_squared = total_distance = total_velocity_squared = 0.0
    matched = eligible = missed = false = switches = velocity_count = 0
    for frame in outputs:
        time_ms = frame["time_ms"]
        time = timestamp(time_ms)
        true = sorted(truth_by_time[time_ms], key=lambda item: item["truth_id"])
        estimated = sorted(frame["tracks"], key=lambda item: item["track_id"])
        true_by_id = {obj["truth_id"]: obj for obj in true}
        estimated_by_id = {obj["track_id"]: obj for obj in estimated}
        if true or estimated:
            metric, assignment = gospa.compute_gospa_metric(
                [State(obj["position_m"], timestamp=time) for obj in estimated],
                [State(obj["position_m"], timestamp=time) for obj in true],
            )
            components = {key: float(value) for key, value in metric.value.items()}
        else:
            components = dict(distance=0.0, localisation=0.0, missed=0.0, false=0.0)
            assignment = []
        current = clear_matches(true_by_id, estimated_by_id, previous, scoring["identity_gate_m"])
        matches = []
        for truth_id, track_id in sorted(current.items()):
            distance = float(
                np.linalg.norm(
                    np.array(true_by_id[truth_id]["position_m"])
                    - estimated_by_id[track_id]["position_m"]
                )
            )
            switched = truth_id in previous and previous[truth_id] != track_id
            matches.append(
                {
                    "truth_id": truth_id,
                    "track_id": track_id,
                    "distance_m": distance,
                    "identity_switch": switched,
                }
            )
            total_squared += distance**2
            total_distance += distance
            switches += int(switched)
            if estimated_by_id[track_id].get("velocity_mps") is not None:
                error = (
                    np.array(true_by_id[truth_id]["velocity_mps"])
                    - estimated_by_id[track_id]["velocity_mps"]
                )
                total_velocity_squared += float(error @ error)
                velocity_count += 1
        previous = current
        matched += len(matches)
        eligible += len(true)
        missed += len(true) - len(matches)
        false += len(estimated) - len(matches)
        ticks.append(
            {
                "time_ms": time_ms,
                "gospa": components,
                "matches": matches,
                "missed_ids": sorted(set(true_by_id) - set(current)),
                "false_ids": sorted(set(estimated_by_id) - set(current.values())),
                "gospa_matches": [
                    {"truth_id": true[i]["truth_id"], "track_id": estimated[int(j)]["track_id"]}
                    for i, j in enumerate(assignment)
                    if j >= 0
                ],
            }
        )
    summary = {
        "mean_gospa_m": float(np.mean([tick["gospa"]["distance"] for tick in ticks]))
        if ticks
        else None,
        "gospa_components_mean_m2": {
            key: float(np.mean([tick["gospa"][key] for tick in ticks])) if ticks else None
            for key in ("localisation", "missed", "false")
        },
        "position_rmse_m": sqrt(total_squared / matched) if matched else None,
        "matched_states": matched,
        "eligible_states": eligible,
        "coverage": matched / eligible if eligible else None,
        "missed_states": missed,
        "false_states": false,
        "identity_switches": switches,
        "mota": 1 - (missed + false + switches) / eligible if eligible else None,
        "motp_m": total_distance / matched if matched else None,
        "velocity_rmse_mps": sqrt(total_velocity_squared / velocity_count)
        if velocity_count
        else None,
        "velocity_matched_states": velocity_count,
        "uncertainty_metric": None,
        "scored_ticks": len(ticks),
        "expected_ticks": len(truth),
    }
    return {
        "summary": summary,
        "ticks": ticks,
        "scoring": scoring,
        "identity_method": "CLEAR MOT procedure; previous-frame continuity; strict distance < gate; switches between consecutive matched frames",
    }
