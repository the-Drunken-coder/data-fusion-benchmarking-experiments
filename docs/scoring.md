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

No single combined accuracy score or universal winner is produced. A system can have lower position error while generating more false tracks. Grouped control and exploratory cases remain explicitly identified.
