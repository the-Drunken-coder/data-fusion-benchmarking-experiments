# Data fusion benchmarking

A setting for developing and comparing data fusion systems through repeatable experiments. The first version focuses on reconstructing moving objects from imperfect numeric sensor observations.

## Language

**Ground truth**:
The simulated world's actual objects, identities, states, and lifetimes. Ground truth is private to the benchmark and unavailable to the candidate.

**Observation**:
A sensor report about what it detected at a particular measurement time. An observation can be inaccurate or a false detection, and can arrive after it was measured.
_Avoid_: Truth, track

**Track**:
A candidate's estimate of an object's state, with an identity that persists across successive estimates. A track can be mistaken, duplicated, or missing even when the underlying object exists.
_Avoid_: Observation, true object

**Fusion system**:
A complete system that combines observations into estimates about the world. It may use deterministic methods, AI models, large models, or a combination, and may be developed within this project or imported from elsewhere.
_Avoid_: Model when referring to the complete system

**System version**:
A preserved definition of a fusion system, including its code, settings, and any model artifacts it uses. A run identifies the version tested, so subsequent changes do not redefine past results.

**Candidate**:
A fusion system participating in an evaluation.
_Avoid_: Evaluator

**Benchmark**:
A defined task with test cases and scoring rules for evaluating fusion systems. A comparison establishes performance on that benchmark, not superiority at every fusion task.

**Fixed benchmark**:
A benchmark whose test cases and scoring rules stay unchanged within a version. Runs belong to the same comparison only when their evaluation conditions are compatible.

**Experiment**:
A comparison or investigation of fusion systems under specified conditions. An experiment can contain multiple runs to examine different scenarios or variation between attempts.

**Exploratory experiment**:
An experiment with user-adjustable conditions, such as object count, sensor quality, or missing reports. Its results describe those conditions and are not automatically results on the fixed benchmark.

**Scenario**:
A test situation defining a simulated world and the conditions under which sensors observe it.

**Run**:
One candidate's attempt to reconstruct a world from a particular recorded observation stream using a specified system version.

**Synchronized playback**:
A view of saved runs aligned to the same simulation time, showing ground truth, available observations, and each candidate's estimates. Playback reveals what happened in the recorded runs without rerunning the candidates.

**Ungrouped numeric tracking**:
The primary task, in which a candidate receives numeric observations and must determine which belong to the same object while estimating object states.

**Grouped estimation control**:
A separate task in which false detections are removed and observations are explicitly grouped by their true object. It measures estimation with oracle association and filtered clutter, so its results are not directly comparable to ungrouped numeric tracking.
