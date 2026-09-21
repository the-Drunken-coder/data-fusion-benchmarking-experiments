# Fusion Lab

A local workbench for developing, importing, and comparing data fusion systems. The comparison table leads into synchronized playback of the actual world, sensor reports, and candidate tracks. The initial benchmark measures two-dimensional numeric tracking. No paid service, GPU, database server, or Atlas deployment is needed.

## Start

Install Python dependencies with [uv](https://docs.astral.sh/uv/) and the interface with pnpm. Python 3.12 is selected by `.python-version`; both dependency sets have lockfiles.

```sh
uv sync --frozen
pnpm --dir web install --frozen-lockfile
pnpm --dir web build
uv run fusion serve
```

Open [Fusion Lab](http://127.0.0.1:8840). Expand **Run an experiment**, select the systems, and run a case or the fixed suite. Results persist in `.fusion/` across restarts. Use `FUSION_DATA=/absolute/directory` for a separate workspace.

The fixed suite contains seven scenarios and two seeds per partition. Tuning uses 100 and 101; held-out evaluation uses 1000 and 1001. Seeds below 1000 are reserved for tuning. Freeze candidate settings before evaluating the held-out cases. There is no automatic tuning.

## Commands

```sh
# Generate a fixed case. The JSON result includes its case_id.
uv run fusion generate --scenario crossing --seed 100

# Replace CASE_ID with that result's case_id.
uv run fusion run CASE_ID nearest
uv run fusion run CASE_ID kalman

# Replace the identifiers with run_id values printed by those commands.
uv run fusion compare RUN_ID_1 RUN_ID_2

# Execute both included candidates on all seven scenarios, with two tuning seeds.
uv run fusion demo

# Adjustable conditions are explicitly labeled exploratory.
uv run fusion generate --scenario noisy --seed 102 --objects 8 --noise 4 --outage-ms 12000

# Per-sensor coverage, reporting intervals, noise, clutter, delays, and outages.
uv run fusion generate --config examples/custom-sensors.json

# Separate estimation control. Never compare its scores with ungrouped tracking.
uv run fusion run CASE_ID kalman --mode grouped

# Import a local system bundle.
uv run fusion register /absolute/path/to/system-folder
```

`compare` refuses incomplete runs, mixed task modes, different scoring implementations, and unmatched case sets or repetition counts. For multi-case comparisons, pass every run ID from each system. Output includes aggregate and per-scenario results, plus variability across runs. The web table compares runs on the selected exact case; suite-wide aggregates are available through the CLI.

## Build a system

Start with `systems/nearest/`, a standard-library example, or `systems/kalman/`, the conventional reference. Each system is an ordinary persistent program that receives and returns JSON Lines. It does not import the benchmark. Add a uniquely named folder under `systems/` for work developed in this repository, or register an external folder using the command above.

The runner snapshots the entire bundle before executing that copy. Code and bundled model changes produce a new system hash. Python, compiled programs, and other local runtimes can participate through the same contract. A system is responsible for its interpretation, association, filtering, and estimation.

Read [the protocol](docs/protocol.md), [scoring and experiment rules](docs/scoring.md), and [architecture decisions](docs/adr/0001-independent-candidates.md).

## Artifacts

Each case contains public initialization and observation files, separately stored private truth and observation mappings, and a manifest of seeds, configuration, versions, code fingerprints, and SHA-256 hashes.

Each run contains the executed system snapshot, public requests, validated track snapshots, raw stdout, stderr, measured timings, per-tick associations and metrics, an aggregate result, a text summary, and `trajectory.svg`. Failures preserve whatever valid output arrived and are explicitly marked failed. Files are never reused for another run. This is an append-only application convention, not filesystem write protection against users or hostile programs.

## Validation

```sh
uv run pytest -q
uv run ruff check src systems tests
pnpm --dir web build
```

Fixtures cover GOSPA penalties, identity swaps, association continuity, deterministic generation and replay, hidden-field exclusion, delayed delivery, protocol failures, blocked-input timeouts, artifact tampering, both-sensor updates, and comparison boundaries. See [the implementation verification record](docs/verification.md) for executed commands and actual results.

## Current limits

- The world is a controlled numeric experiment, not a validated physical camera or radar simulation. Images, descriptive reports, semantic scoring, and production integrations remain future work.
- Replay is causal lockstep. Measured response latency does not establish real-time throughput, queue behavior, or physical sensor realism.
- The Kalman reference initiates immediately from unmatched detections. This intentionally simple policy produces false tracks in clutter. It drops stale scans rather than smoothing past estimates.
- Candidates run as local subprocesses with a clean environment and temporary working directory. This is not a sandbox for hostile code. Only run trusted systems. There are no paid-service integrations.
- System bundles currently have a 256 MiB limit. Large model packages need that limit raised and sufficient local resources; a shipped large-model candidate is not included. Executables or dependencies outside the bundle must be pinned separately by the system author.
- Runs execute serially through the UI. There are no user accounts, remote workers, visual system editor, or experiment cancellation control. Stop the server to end its session; unfinished jobs are reported as interrupted on the next startup.
- Velocity scoring is available only where a candidate provides velocity. Uncertainty scoring is not implemented.
- The web UI exposes per-case comparisons and synchronized playback. The CLI additionally computes suite-level and per-scenario aggregates.
