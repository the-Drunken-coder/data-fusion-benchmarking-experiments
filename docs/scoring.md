# Experiment and scoring rules

Every case lasts 60 s, evaluated at 500 ms intervals including time zero and the final tick. All living truth objects are eligible, including before first detection, during gaps, and outside sensor coverage. The declared region is `[-500, -500, 500, 500]` meters; generated objects stay inside it. No difficult interval is silently removed.

## Generation

The seven scenarios cover a clean single object, overlapping sensors, crossing paths, births/deaths, missed reports plus clutter and outage, delayed out-of-sequence delivery, and turns. Sensors measure the world at measurement time, add independent Gaussian position errors, probabilistic detection, and Poisson clutter where configured. Sensor A updates every 1 s; B every 1.5 s. Delayed cases use delays between 0 and 4.5 s. Independent random streams control world generation, each sensor, and opaque identifiers.

World state is piecewise constant velocity. Default clean noise is 0.2 m with certain detection. Other default noise is 2 m. The noisy scenario has detection probability 0.65, mean clutter 0.5 per sensor scan, and an 8 s outage on B beginning at 30 s. Other non-clean scenarios have detection probability 0.93. These are deliberately controlled conditions, not claims about a particular real sensor.

Observation files are hashed and preserved, then replayed to all compared systems. Case format 2 derives the case ID from the complete canonical manifest excluding the ID itself, including configuration, scoring, package versions, generator/evaluator code hashes, and every artifact hash. Generation reconstructs this descriptor before reusing an existing case. Execution verifies the descriptor against both the requested ID and the manifest ID, and rejects changed, missing, or extra files. Timings are measured separately and are not expected to reproduce exactly. Tuning and evaluation use disjoint seed ranges. The included baseline's fixed settings were not tuned against held-out results.

Advanced experiments can provide a `sensors` list through `fusion generate --config FILE`. Each source independently configures coverage bounds, update interval, isotropic position noise with declared covariance, detection probability, Poisson clutter rate, maximum delivery delay, and outage start/duration. Per-sensor settings and global sensor overrides cannot be mixed. Future outage schedules remain private; candidate initialization exposes only source names, coverage, and nominal reporting intervals.

## GOSPA

Use Stone Soup 1.9.1 `GOSPAMetric`, Euclidean position distance, p = 2, c = 10 m, α = 2. Each tick reports distance in meters and localization, missed-object, and false-track contributions in m². A missing or false object contributes 50 m². Distance equals the square root of the sum of contributions at that tick.

The run's `mean_gospa_m` is the arithmetic mean of tick distances. Component summaries are arithmetic means in m²; the square root of their sum is not generally the arithmetic mean distance. A completely empty truth/estimate tick has zero distance and components. This explicit empty-set case is handled locally because Stone Soup requires at least one timestamped state.

## Identity and position

Use the sequence-aware CLEAR MOT procedure: retain each previous tick's truth/track pair if both objects remain present and their Euclidean distance is strictly below 10 m. Apply Hungarian assignment to the remaining objects, then retain pairs within that gate. Sorted IDs make equal-cost tie resolution reproducible. Identity switches count changed candidate IDs for a truth object matched in consecutive ticks. Reacquisition after an unmatched gap is not counted as a switch under this definition.

The procedure follows [Stone Soup's CLEAR MOT implementation](https://stonesoup.readthedocs.io/en/v1.9.1/_modules/stonesoup/dataassociator/clearmot.html). It is implemented locally to avoid a reproduced 1.9.1 edge case: the upstream associator creates zero-duration `TimeRange` objects for single-tick matches, which its interval class rejects. Tests cover those cases, exact identity swaps, and carrying forward a valid match when another neighbor is closer.

Position RMSE is the square root of the mean squared Euclidean error over CLEAR MOT matched states. Always report the matched-state count, eligible-state count, and coverage with it. No matches produce `null`, not zero. MOTA is `1 - (misses + false states + identity switches) / eligible states`; MOTP is mean matched Euclidean distance in meters. No eligible states produce unavailable MOTA. Velocity RMSE is reported only for matched states whose candidates supply velocity, together with that sample count. Uncertainty scoring is unavailable.

Saved per-tick records contain separate GOSPA and CLEAR MOT associations, misses, false tracks, and identity switches. The web player shows recorded snapshots without recomputing or smoothing them.

## Runtime, failures, and aggregation

The runner measures request-to-response wall-clock latency, including serialization and pipe transport, separately from initialization, simulation generation, and scoring. Report median, p95, and maximum latency, delivered and acknowledged observations, timeouts, invalid outputs, and completion. Acknowledgement means a valid response was received; the runner cannot prove every observation was used internally.

On failure, score only the validated prefix and label its scope as partial. Expected tick count remains the full horizon, and comparison refuses failed runs. Invalid responses never become empty successful snapshots. The GUI may display partial values for diagnosis, with failed status visible.

Multi-run comparisons require the same case and repetition counts for each system version. Aggregates pool matched squared errors for RMSE, sum identity/missed/false counts, and weight mean GOSPA by scored tick count. Per-scenario aggregates and the standard deviation of run-level mean GOSPA are reported separately. The overall standard deviation mixes scenario and seed differences; it is not a confidence interval or an estimate of model randomness alone. Repeat identical cases to investigate a stochastic candidate's variability.

## Versioned benchmark points

`fusion benchmark nearest kalman` and the web benchmark action run Numeric tracking v1: ungrouped tracking, all seven default scenarios, evaluation seeds 1000–1003, and three complete attempts per system. Each attempt contains 28 cases, for 84 runs per system. The existing two-seed experiment suite and arbitrary `compare` selections do not award benchmark points.

For each case, the reference error is the mean GOSPA of a tracker returning no tracks over its complete truth timeline. With the fixed parameters above, each tick contributes `sqrt(50 * living_object_count)` meters to that reference. Each run earns:

```text
points = 100 * max(0, 1 - mean_gospa_m / empty_tracker_mean_gospa_m)
```

Perfect reconstruction earns 100. An empty tracker earns 0; worse errors also earn 0. Clipping happens for each run before averaging. Raw GOSPA remains visible to distinguish scores tied at the floor. These points are not percent accuracy and do not include identity continuity, velocity, uncertainty, runtime, or cost. Identity counts and measured response latency are displayed separately. Cost is unavailable.

Each scenario is the mean of its four case scores. An attempt is the mean of its seven scenario scores. The headline averages three attempt scores. Display rounding never affects aggregation. The attempt minimum and maximum describe three repeated complete suites, not a confidence interval or a guarantee of future behavior. Deterministic saved-output scoring does not imply deterministic candidate behavior.

An evaluation records its expected case/attempt slots before executing, snapshots each candidate once, and executes that preserved version for every run. Every slot must contain a distinct complete run with the correct case, system version, task, evaluator, environment, response budgets, and 121-step timeline. Missing, failed, duplicate, or incompatible runs prevent a headline for that system. Failures stop that system's evaluation, preserve diagnostic runs, and allow other selected systems to finish. A retry creates a new evaluation; the UI keeps both. There is no best-attempt selection.

The suite fingerprint binds the complete case manifests and artifact hashes, seeds, scoring implementation, runner, dependencies/environment, formula, repeat count, and budgets. Suite files are immutable by application convention. New generation or implementation changes produce a different fingerprint, even under the same human-readable family name. The matrix displays one fingerprint at a time; it never compares different definitions. Re-scoring also rejects implementation/environment drift. The initial budgets are 5 seconds per step and 30 seconds for initialization.

Definitions are stored under `.fusion/benchmarks/suites/`. Each evaluation preserves its plan, system snapshots, report, and hashes under `.fusion/benchmarks/evaluations/`. Run artifacts remain in the ordinary run store and open in synchronized playback. System bundle hashes cannot pin an external service or dependencies outside the bundle; authors must preserve those separately.

A benchmark score describes this suite. A system can improve its score while regressing on one scenario or identity continuity, so the matrix and raw details remain part of the result. Grouped control, tuning, and exploratory cases cannot earn this headline score.
