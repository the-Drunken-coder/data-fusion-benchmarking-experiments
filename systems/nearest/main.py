"""Minimal external candidate using only the Python standard library."""

import json
import math
import sys


def main():
    tracks, next_id, mode = {}, 0, "ungrouped"
    for line in sys.stdin:
        message = json.loads(line)
        if message["type"] in ("init", "reset"):
            tracks, next_id, mode = {}, 0, message["mode"]
            response = {"type": "ready", "schema_version": 1}
        else:
            now = message["time_ms"]
            tracks = {
                key: value for key, value in tracks.items() if now - value["measured"] <= 3000
            }
            scan_used = {}
            for obs in message["observations"]:
                if now - obs["measured_at_ms"] > 3000:
                    continue
                if mode == "grouped" and any(
                    value["group_key"] == obs["group_key"]
                    and value["measured"] > obs["measured_at_ms"]
                    for value in tracks.values()
                ):
                    continue
                used = scan_used.setdefault((obs["sensor_id"], obs["measured_at_ms"]), set())
                choices = []
                for key, value in tracks.items():
                    if key in used or obs["measured_at_ms"] < value["measured"]:
                        continue
                    distance = math.dist(value["position_m"], obs["position_m"])
                    if (mode == "grouped" and value["group_key"] == obs["group_key"]) or (
                        mode == "ungrouped" and distance < 10
                    ):
                        choices.append((distance, key))
                if choices:
                    key = min(choices)[1]
                else:
                    next_id += 1
                    key = f"n{next_id}"
                tracks[key] = {
                    "position_m": obs["position_m"],
                    "measured": obs["measured_at_ms"],
                    "group_key": obs.get("group_key"),
                }
                used.add(key)
            response = {
                "type": "tracks",
                "schema_version": 1,
                "step_id": message["step_id"],
                "time_ms": now,
                "tracks": [
                    {"track_id": key, "position_m": value["position_m"]}
                    for key, value in sorted(tracks.items())
                ],
            }
        print(json.dumps(response, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
