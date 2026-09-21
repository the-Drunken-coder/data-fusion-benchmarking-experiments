# ADR 0001: Keep candidate execution independent of evaluation

Status: accepted through the product interview.

## Context

The workbench must evaluate imported systems and ideas developed within this repository, including deterministic, AI, and hybrid approaches. Convenience must not give an in-repository candidate private simulation state or evaluator assistance.

## Decision

Every candidate uses the same persistent JSON Lines subprocess interface. The runner snapshots its local system bundle and executes that copy in a temporary directory. Public observation messages use an explicit allowlist. Ground truth and evaluator mappings remain in separate private case artifacts.

Python and Stone Soup implement the benchmark and conventional reference, while a React/TypeScript interface reads saved runs and requests experiments through a localhost API. The UI never implements scoring. The benchmark is usable from a CLI without the UI.

## Tradeoff

A subprocess interface adds serialization and packaging compared with importing a Python tracker directly. It provides a clear boundary for other languages and system architectures, and keeps reference candidates subject to the same information limits. It does not provide adversarial-code security; stronger isolation is deferred until that becomes a product requirement.

## Consequences

Developing a system in this repository does not change its access privileges. New report families can introduce explicit versioned input contracts and separate benchmarks later. The initial implementation stays focused on numeric tracking and avoids production integration, distributed execution, and a plugin framework.
