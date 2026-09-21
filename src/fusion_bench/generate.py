"""Controlled Cartesian scenarios; no claims about camera, radar, or RF physics."""

import tempfile
from pathlib import Path

import numpy as np

from .schema import CaseConfig, Observation
from .storage import (
    data_root,
    digest,
    encode,
    environment,
    hashes,
    read_json,
    verify,
    write_json,
    write_lines,
)

GENERATOR_VERSION = 1
TICK_MS = 500
HORIZON_MS = 60000
SCORING = {
    "version": 1,
    "gospa_p": 2,
    "gospa_c_m": 10.0,
    "gospa_alpha": 2,
    "identity_gate_m": 10.0,
    "eligibility": "All living objects at every evaluation tick",
    "roi_m": [-500, -500, 500, 500],
    "horizon_ms": HORIZON_MS,
    "tick_ms": TICK_MS,
}


def world_state(obj: dict, time_ms: int) -> dict | None:
    if not obj["birth_ms"] <= time_ms < obj["death_ms"]:
        return None
    seconds = (time_ms - obj["birth_ms"]) / 1000
    turn = obj.get("turn_after_s", float("inf"))
    before = np.array(obj["velocity_mps"])
    after = np.array(obj.get("after_velocity_mps", obj["velocity_mps"]))
    point = np.array(obj["position_m"]) + before * min(seconds, turn)
    if seconds > turn:
        point += after * (seconds - turn)
    return {
        "truth_id": obj["truth_id"],
        "position_m": point.tolist(),
        "velocity_mps": (after if seconds > turn else before).tolist(),
    }


def generate(config: CaseConfig, root: Path | None = None) -> dict:
    root = root or data_root()
    identity = {
        "config": config.model_dump(),
        "generator_version": GENERATOR_VERSION,
        "scoring": SCORING,
        "environment": environment(),
        "generator_sha256": digest(Path(__file__).read_bytes()),
        "evaluator_sha256": digest(Path(__file__).with_name("evaluate.py").read_bytes()),
    }
    case_id = digest(encode(identity).encode())[:16]
    destination = root / "cases" / case_id
    if destination.exists():
        manifest = read_json(destination / "manifest.json")
        verify(destination, manifest["hashes"])
        return manifest
    root.joinpath("cases").mkdir(parents=True, exist_ok=True)
    world_seed, sensor_seed, identifier_seed = np.random.SeedSequence(config.seed).spawn(3)
    world_rng = np.random.default_rng(world_seed)
    id_rng = np.random.default_rng(identifier_seed)
    count = config.object_count or (
        1 if config.scenario == "clean" else 4 if config.scenario == "overlap" else 2
    )
    objects = []
    for i in range(count):
        point = [10.0, 12.0 + i * 12] if count <= 4 else [10.0, 5.0 + i * 4]
        velocity = [1.2, 0.0]
        if config.scenario in ("crossing", "noisy", "delayed"):
            point = [10.0, 10.0 if i % 2 == 0 else 55.0 + (i // 2) * 5]
            velocity = [1.2, 0.75 if i % 2 == 0 else -0.75]
        point = (np.array(point) + world_rng.uniform(-1, 1, 2)).tolist()
        obj = {
            "truth_id": f"truth_{i}",
            "position_m": point,
            "velocity_mps": velocity,
            "birth_ms": 15000 if config.scenario == "lifecycle" and i % 2 else 0,
            "death_ms": 45000 if config.scenario == "lifecycle" and i % 2 == 0 else HORIZON_MS + 1,
        }
        if config.scenario == "turning":
            obj.update(turn_after_s=30, after_velocity_mps=[0.2, 1.0 if i % 2 == 0 else -0.4])
        objects.append(obj)
    noise = (
        config.noise_m
        if config.noise_m is not None
        else (0.2 if config.scenario == "clean" else 2.0)
    )
    detection = (
        config.detection_probability
        if config.detection_probability is not None
        else (0.65 if config.scenario == "noisy" else 1.0 if config.scenario == "clean" else 0.93)
    )
    outage = (
        config.outage_ms
        if config.outage_ms is not None
        else (8000 if config.scenario == "noisy" else 0)
    )
    sensors = [
        {"sensor_id": "sensor_a", "interval_ms": 1000, "coverage_m": [-20, -50, 100, 150]},
        {"sensor_id": "sensor_b", "interval_ms": 1500, "coverage_m": [20, -50, 140, 150]},
    ][: 1 if config.scenario == "clean" else 2]
    for sensor in sensors:
        sensor.update(
            noise_m=noise,
            detection_probability=detection,
            clutter_per_scan=0.5 if config.scenario == "noisy" else 0,
            max_delay_ms=4500 if config.scenario == "delayed" else 0,
            outage_start_ms=30000,
            outage_ms=outage if sensor["sensor_id"] == "sensor_b" else 0,
        )
    if config.sensors is not None:
        sensors = [sensor.model_dump() for sensor in config.sensors]
    sensor_rngs = [np.random.default_rng(seed) for seed in sensor_seed.spawn(len(sensors))]
    observations, mapping = [], {}
    groups = {obj["truth_id"]: "g_" + id_rng.bytes(10).hex() for obj in objects}
    for sensor, rng in zip(sensors, sensor_rngs):
        noise = sensor["noise_m"]
        detection = sensor["detection_probability"]
        for measured in range(0, HORIZON_MS + 1, sensor["interval_ms"]):
            if (
                sensor["outage_start_ms"]
                <= measured
                < sensor["outage_start_ms"] + sensor["outage_ms"]
            ):
                continue
            states = [state for obj in objects if (state := world_state(obj, measured))]
            rng.shuffle(states)
            reports = []
            x0, y0, x1, y1 = sensor["coverage_m"]
            for state in states:
                x, y = state["position_m"]
                if x0 <= x <= x1 and y0 <= y <= y1 and rng.random() < detection:
                    reports.append((np.array([x, y]) + rng.normal(0, noise, 2), state["truth_id"]))
            clutter = rng.poisson(sensor["clutter_per_scan"])
            for _ in range(clutter):
                reports.append((rng.uniform([x0, y0], [x1, y1]), None))
            rng.shuffle(reports)
            for point, truth_id in reports:
                delay = (
                    int(rng.integers(0, sensor["max_delay_ms"] + 1))
                    if sensor["max_delay_ms"]
                    else 0
                )
                oid = "obs_" + id_rng.bytes(12).hex()
                observation = Observation(
                    observation_id=oid,
                    sensor_id=sensor["sensor_id"],
                    measured_at_ms=measured,
                    arrived_at_ms=measured + delay,
                    position_m=point.tolist(),
                    position_cov_m2=((noise**2, 0), (0, noise**2)),
                )
                observations.append(observation.model_dump(exclude_none=True))
                mapping[oid] = truth_id
    # IDs supply an independent, opaque tie-break rather than per-object scan order.
    observations.sort(key=lambda obs: (obs["arrived_at_ms"], obs["observation_id"]))
    truth = [
        {
            "time_ms": time,
            "objects": [state for obj in objects if (state := world_state(obj, time))],
        }
        for time in range(0, HORIZON_MS + 1, TICK_MS)
    ]
    public = {
        "type": "init",
        "schema_version": 1,
        "mode": "ungrouped",
        "coordinates": {
            "frame": "Cartesian 2D; x right, y up",
            "position_unit": "m",
            "velocity_unit": "m/s",
            "time_unit": "integer ms since simulation origin",
        },
        "tick_ms": TICK_MS,
        "sources": [
            {key: sensor[key] for key in ("sensor_id", "interval_ms", "coverage_m")}
            for sensor in sensors
        ],
        "output": {
            "snapshot": "All active tracks at requested time",
            "position_required": True,
            "velocity_optional": True,
        },
    }
    grouped = [
        dict(obs, group_key=groups[mapping[obs["observation_id"]]])
        for obs in observations
        if mapping[obs["observation_id"]] is not None
    ]
    with tempfile.TemporaryDirectory(dir=root / "cases", prefix=".generating-") as temp:
        path = Path(temp)
        write_json(path / "public" / "init.json", public)
        write_lines(path / "public" / "observations.jsonl", observations)
        write_lines(path / "public" / "grouped-observations.jsonl", grouped)
        write_lines(path / "private" / "truth.jsonl", truth)
        write_json(path / "private" / "mapping.json", mapping)
        write_json(path / "private" / "world.json", objects)
        manifest = dict(
            identity,
            case_id=case_id,
            observation_count=len(observations),
            delivered_count=sum(o["arrived_at_ms"] <= HORIZON_MS for o in observations),
            random_streams=["world", *[f"sensor/{i}" for i in range(len(sensors))], "identifiers"],
            hashes=hashes(path),
        )
        write_json(path / "manifest.json", manifest)
        path.rename(destination)
    return manifest
