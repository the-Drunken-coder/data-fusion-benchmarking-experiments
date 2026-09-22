"""An ordinary JSONL candidate. No imports from the benchmark package or truth access."""

import json
import sys
from collections import OrderedDict
from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import linear_sum_assignment
from stonesoup.models.measurement.linear import LinearGaussian
from stonesoup.models.transition.linear import (
    CombinedLinearGaussianTransitionModel,
    ConstantVelocity,
)
from stonesoup.predictor.kalman import KalmanPredictor
from stonesoup.types.detection import Detection
from stonesoup.types.hypothesis import SingleHypothesis
from stonesoup.types.state import GaussianState
from stonesoup.updater.kalman import KalmanUpdater

ORIGIN = datetime(2000, 1, 1)
GATE_M = 12.0
EXPIRY_MS = 5000


class Tracker:
    def __init__(self, mode):
        self.mode = mode
        self.predictor = KalmanPredictor(
            CombinedLinearGaussianTransitionModel([ConstantVelocity(0.15), ConstantVelocity(0.15)])
        )
        self.updater = KalmanUpdater()
        self.tracks = {}
        self.next_id = 0
        self.last_scan_ms = -1
        self.dropped = 0

    def step(self, message):
        now = message["time_ms"]
        # Public scan groups are processed in first-arrival order, never globally sorted by time.
        scans = OrderedDict()
        for obs in message["observations"]:
            scans.setdefault((obs["sensor_id"], obs["measured_at_ms"]), []).append(obs)
        for (_, measured), observations in scans.items():
            if measured < self.last_scan_ms or now - measured > EXPIRY_MS:
                self.dropped += len(observations)
                continue
            self.last_scan_ms = measured
            self.tracks = {
                key: value
                for key, value in self.tracks.items()
                if measured - value["last_seen"] <= EXPIRY_MS
            }
            when = ORIGIN + timedelta(milliseconds=measured)
            keys = sorted(self.tracks)
            predictions = {
                key: self.predictor.predict(self.tracks[key]["state"], timestamp=when)
                for key in keys
            }
            pairs = []
            if self.mode == "grouped":
                groups = {value["group_key"]: key for key, value in self.tracks.items()}
                pairs = [
                    (groups[obs["group_key"]], j)
                    for j, obs in enumerate(observations)
                    if obs["group_key"] in groups
                ]
            elif keys and observations:
                costs = np.array(
                    [
                        [
                            np.linalg.norm(
                                predictions[key].state_vector[[0, 2], 0] - obs["position_m"]
                            )
                            for obs in observations
                        ]
                        for key in keys
                    ]
                )
                # Dummy columns allow each track to remain unmatched without stealing a valid match.
                gated = np.where(costs < GATE_M, costs, 1e6)
                expanded = np.concatenate([gated, np.full((len(keys), len(keys)), GATE_M)], axis=1)
                rows, cols = linear_sum_assignment(expanded)
                pairs = [
                    (keys[i], j)
                    for i, j in zip(rows, cols)
                    if j < len(observations) and costs[i, j] < GATE_M
                ]
            used = set()
            for key, j in pairs:
                obs = observations[j]
                model = LinearGaussian(
                    ndim_state=4, mapping=[0, 2], noise_covar=obs["position_cov_m2"]
                )
                detection = Detection(obs["position_m"], timestamp=when, measurement_model=model)
                state = self.updater.update(SingleHypothesis(predictions[key], detection))
                self.tracks[key].update(state=state, last_seen=measured)
                used.add(j)
            for j, obs in enumerate(observations):
                if j in used:
                    continue
                self.next_id += 1
                x, y = obs["position_m"]
                cov = np.diag(
                    [obs["position_cov_m2"][0][0], 25.0, obs["position_cov_m2"][1][1], 25.0]
                )
                cov[0, 2] = cov[2, 0] = obs["position_cov_m2"][0][1]
                self.tracks[f"k{self.next_id}"] = {
                    "state": GaussianState([x, 0, y, 0], cov, timestamp=when),
                    "last_seen": measured,
                    "group_key": obs.get("group_key"),
                }
        self.tracks = {
            key: value
            for key, value in self.tracks.items()
            if now - value["last_seen"] <= EXPIRY_MS
        }
        output = []
        for key, value in sorted(self.tracks.items()):
            # Predict a snapshot without overwriting the measurement-time filter state.
            predicted = self.predictor.predict(
                value["state"], timestamp=ORIGIN + timedelta(milliseconds=now)
            )
            vector = predicted.state_vector[:, 0]
            output.append(
                {
                    "track_id": key,
                    "position_m": vector[[0, 2]].tolist(),
                    "velocity_mps": vector[[1, 3]].tolist(),
                }
            )
        return output


def main():
    tracker = None
    for line in sys.stdin:
        message = json.loads(line)
        if message["type"] in ("init", "reset"):
            tracker = Tracker(message["mode"])
            response = {"type": "ready", "schema_version": 1}
        elif message["type"] == "step" and tracker is not None:
            response = {
                "type": "tracks",
                "schema_version": 1,
                "step_id": message["step_id"],
                "time_ms": message["time_ms"],
                "tracks": tracker.step(message),
            }
        else:
            raise ValueError("Expected init before step")
        print(json.dumps(response, allow_nan=False), flush=True)
    if tracker is not None:
        print(f"Discarded {tracker.dropped} stale observations", file=sys.stderr)


if __name__ == "__main__":
    main()
