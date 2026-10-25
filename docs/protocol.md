# Candidate protocol v1

Each candidate is one persistent subprocess. Read UTF-8 JSON objects, one per line, from stdin and write exactly one JSON response per request to stdout. Write diagnostic logs to stderr. The runner starts a fresh process for each run, so candidate state cannot carry between cases.

## System bundle

Place a `system.json` beside the program and its local resources:

```json
{
  "id": "my-tracker",
  "name": "My tracker",
  "version": "1.0",
  "command": ["{python}", "main.py"],
  "modes": ["ungrouped"],
  "description": "My fusion idea"
}
```

Commands are argument lists, never shell strings. `{python}` expands to the benchmark environment's interpreter. `{system_dir}` expands to the temporary executed bundle directory. A binary can use `./tracker`, and another language can use its installed runtime. Symlinks are rejected. The initial bundle limit is 256 MiB. Model weights and configuration must be included to be covered by the system hash. Pin external runtime dependencies yourself.

## Initialization

The runner sends `type: "init"`, `schema_version: 1`, task `mode`, coordinate conventions, evaluation interval, and public source descriptions. Sources declare their names, coverage and reporting intervals. Each observation carries its covariance.

Reply exactly:

```json
{"type":"ready","schema_version":1}
```

The included candidates also accept `reset` with the same initialization fields. The runner uses process replacement for reset between runs.

Coordinates are Cartesian 2D, x right and y up. Positions are meters, velocities meters per second, and timestamps integer milliseconds from a fixed origin. The internal Kalman state order is `[x, vx, y, vy]`, but that internal representation never appears in the public protocol.

No candidate receives the scenario seed, object count, trajectories, birth/death schedule, false-detection labels, or private object identities. The runner does not pre-create truth tracks or normalize association on a candidate's behalf.

## Steps

```json
{
  "type":"step","schema_version":1,"step_id":12,"time_ms":6000,
  "observations":[{
    "observation_id":"obs_opaque","sensor_id":"sensor_b",
    "measured_at_ms":4500,"arrived_at_ms":5900,
    "position_m":[23.1,8.2],"position_cov_m2":[[4.0,0.0],[0.0,4.0]]
  }]
}
```

Reports arrive only once, on the first tick at or after their arrival time. Within a request they remain in arrival order; opaque observation IDs break equal-arrival ties. Preserve the original measurement timestamp. Ticks with no observations still require a response. Reports that arrive beyond the 60 s horizon remain in the generated artifact but are never delivered or used to revise scored outputs.

```json
{
  "type":"tracks","schema_version":1,"step_id":12,"time_ms":6000,
  "tracks":[{"track_id":"track_7","position_m":[23.5,8.4],"velocity_mps":[1.3,0.6]}]
}
```

The response is a complete snapshot at the requested time, including active predicted tracks during gaps. An empty `tracks` array is valid. Track IDs must be persistent within a run and unique within a snapshot; their literal strings need not match truth IDs. Position is required and velocity optional. Coordinates must be finite JSON numbers, not numeric strings or booleans. Unknown fields are rejected in v1.

The default initialization timeout is 30 s, with 5 s per step including transport. `--timeout` changes the step limit. Each response is limited to 1 MiB and 1000 tracks. Invalid JSON, invalid schemas, wrong step/time, early EOF, duplicate IDs, and timeouts stop the run as failed. The runner never substitutes successful empty snapshots for invalid responses. Completed earlier snapshots remain unchanged. The subprocess group is terminated at the end.

## Grouped estimation control

Mode `grouped` is explicitly labeled **oracle association and filtered clutter**. Only genuine reports are delivered, with a run-local opaque `group_key` that groups reports from the same object. This isolates estimation from association. Ungrouped candidates never receive grouping keys. Both modes use observations from the same original sensor realization, with clutter removed only for the control.

The current implementation reuses the case's opaque grouping keys across repetitions of that case. Their scope is that case's replay and they carry no semantic information; candidates still reset every run.

## Reference policies

The Kalman candidate uses Stone Soup `ConstantVelocity`, `KalmanPredictor`, `LinearGaussian`, and `KalmanUpdater`. It performs Euclidean gated global nearest-neighbor assignment per public sensor/measurement-time scan, with a 12 m gate. Dummy assignments allow unmatched tracks. Tracks initialize from unmatched received positions with zero assumed velocity and a velocity prior variance of 25 (m/s)². Process noise diffusion is 0.15. Unobserved tracks expire after 5 s.

Newly delivered scan groups are processed in first-arrival order. Multiple sensors at the same measurement timestamp can each update a track. A scan older than the last accepted scan, or older than the expiry interval, is discarded. Snapshot prediction does not overwrite the measurement-time filter state. There is no retroactive smoothing or perfect reordering.

The nearest-report example uses only the Python standard library. It associates within 10 m, holds the last position without a velocity estimate, and expires after 3 s. Both candidates make their own association decisions and start without tracks.

## Isolation boundary

The candidate working directory contains only its executed system snapshot, not cases, truth, requests for future ticks, scores, or private manifests. Most inherited environment variables, including service credentials, are removed. Filesystem and network access are not security-sandboxed: a malicious program running as the same user could discover private files. This boundary is appropriate for cooperative local experiments, not adversarial submissions.
