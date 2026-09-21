# Implementation verification

Executed locally on 2026-09-21 with Python 3.12.13 and the locked dependencies. These are tuning results from a controlled numeric world, not evidence of performance on physical sensors or unseen datasets.

## Checks

```sh
MPLCONFIGDIR=/private/tmp/fusion-mpl .venv/bin/pytest -q
.venv/bin/ruff check src systems tests
pnpm --dir web build
MPLCONFIGDIR=/private/tmp/fusion-mpl .venv/bin/fusion demo
.venv/bin/fusion generate --config examples/custom-sensors.json
```

- All 25 tests passed. Dependency deprecation warnings were emitted by Matplotlib/pyparsing and Starlette/AnyIO.
- Ruff passed. Strict TypeScript checking and the Vite production build passed.
- The demo completed 28 runs: seven scenarios, two tuning seeds, and two systems. Every run's artifact hashes and saved trajectory plot were verified.
- Two executions produced byte-identical `requests.jsonl`, `outputs.jsonl`, and `metrics.json` for all 28 corresponding runs. Runtime measurements were excluded from that comparison.
- The per-sensor example generated successfully, including different reporting rates, coverage, noise, delivery delays, and an outage.

Focused tests exercise metric fixtures, identity changes, causal replay, hidden-field exclusion, protocol failures, timeouts including blocked input, artifact tampering, preserved imports, comparison boundaries, and interrupted-job recovery. The import test changes the original source after registration and verifies execution still uses the preserved copy. Recovery tests distinguish abandoned work from a live CLI process.

## Tuning suite results

Each system was scored on 14 runs containing 3,508 eligible truth states. RMSE uses matched states only; coverage and GOSPA must be considered alongside it. Counts below are state-level totals across all runs.

| Metric | Nearest report | Kalman baseline |
| --- | ---: | ---: |
| Mean GOSPA, lower is better | 5.258 m | 4.156 m |
| Matched-position RMSE | 3.122 m | 2.153 m |
| Matched coverage | 97.58% | 98.52% |
| Missed states | 85 | 52 |
| False states | 826 | 905 |
| Identity switches | 41 | 1 |

The Kalman baseline improves aggregate position and identity performance but creates more false states. On the noisy scenario, its mean GOSPA is worse: 13.495 m versus 11.567 m for nearest report. Immediate track initiation from clutter explains this limitation. These results do not establish a universally better system.

No held-out evaluation runs were used in this verification. The evaluation partition remains available for later experiments after candidate settings are frozen.

## Saved evidence

The local `.fusion/verification/demo.jsonl` records the 28 run IDs and their scenario, seed, system, and completion state. Cases and runs are retained under `.fusion/`; this generated evidence is intentionally excluded from Git.

The following comparison was also executed and saved as `.fusion/verification/clean-comparison.json`:

```sh
.venv/bin/fusion compare 5aaf5789a10b4ad9 1da2d31b71fd44f1
```

Those runs share clean tuning case `28c77fcb486d5934`, seed 100. To reproduce the full comparison from a fresh workspace, run `fusion demo` and use the newly printed run IDs; run IDs are unique execution identifiers.

## Browser verification

The production interface was exercised against the actual local server. Empty, loading, running, and completed states were observed. Both systems completed a grouped control and an exploratory noisy experiment launched through the interface. Selecting a different system preserved playback time; two simultaneous plots shared the same timestamp. Saved truth, reports, estimates, error details, and artifact links were inspected.

Desktop and 360-pixel-wide layouts were rendered. Narrow screens stack the playback plots and keep the comparison table in its own horizontal scroll area; the page itself had no horizontal overflow. Playback starts paused and advances only when requested. No browser console errors were observed during the exercised flows.

See [scoring rules](scoring.md) for units, matching policies, and aggregation limits, [the protocol](protocol.md) for candidate requirements, and [current limits](../README.md#current-limits) for the implementation boundary.
