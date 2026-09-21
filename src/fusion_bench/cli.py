"""Command-line entry points use the same generation and execution path as the UI."""

import argparse
from pathlib import Path

from .generate import generate
from .report import compare, load_run
from .runner import run_candidate
from .schema import SCENARIOS, CaseConfig
from .storage import encode, read_json
from .systems import register


def main():
    parser = argparse.ArgumentParser(prog="fusion")
    commands = parser.add_subparsers(dest="action", required=True)
    case = commands.add_parser("generate")
    case.add_argument(
        "--config", type=Path, help="Complete JSON case configuration; replaces flags"
    )
    case.add_argument("--scenario", choices=SCENARIOS, default="crossing")
    case.add_argument("--seed", type=int)
    case.add_argument("--partition", choices=["tuning", "evaluation"], default="tuning")
    case.add_argument("--objects", type=int)
    case.add_argument("--noise", type=float)
    case.add_argument("--detection-probability", type=float)
    case.add_argument("--outage-ms", type=int)
    run = commands.add_parser("run")
    run.add_argument("case_id")
    run.add_argument("system_id")
    run.add_argument("--mode", choices=["ungrouped", "grouped"], default="ungrouped")
    run.add_argument("--timeout", type=float, default=5.0)
    comparison = commands.add_parser("compare")
    comparison.add_argument("run_ids", nargs="+")
    imported = commands.add_parser("register")
    imported.add_argument("directory", type=Path)
    demo = commands.add_parser("demo")
    demo.add_argument("--seeds")
    demo.add_argument("--scenarios", default=",".join(SCENARIOS))
    demo.add_argument("--partition", choices=["tuning", "evaluation"], default="tuning")
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8840)
    args = parser.parse_args()
    if args.action == "generate":
        custom = any(
            value is not None
            for value in [args.objects, args.noise, args.detection_probability, args.outage_ms]
        )
        config = CaseConfig(
            scenario=args.scenario,
            seed=args.seed
            if args.seed is not None
            else (100 if args.partition == "tuning" else 1000),
            partition=args.partition,
            kind="exploratory" if custom else "fixed",
            object_count=args.objects,
            noise_m=args.noise,
            detection_probability=args.detection_probability,
            outage_ms=args.outage_ms,
        )
        if args.config:
            config = CaseConfig.model_validate(read_json(args.config))
        print(encode(generate(config)))
    elif args.action == "run":
        if args.timeout <= 0:
            parser.error("Timeout must be positive")
        result = run_candidate(args.case_id, args.system_id, args.mode, timeout=args.timeout)
        print(encode(result))
        if result["status"] != "complete":
            raise SystemExit(1)
    elif args.action == "compare":
        result = compare([load_run(run_id) for run_id in args.run_ids])
        print(encode(result))
        if not result["comparable"]:
            raise SystemExit(1)
    elif args.action == "register":
        print(register(args.directory))
    elif args.action == "demo":
        results = []
        for scenario in args.scenarios.split(","):
            for seed in map(
                int,
                (args.seeds or ("100,101" if args.partition == "tuning" else "1000,1001")).split(
                    ","
                ),
            ):
                case = generate(CaseConfig(scenario=scenario, seed=seed, partition=args.partition))
                for system in ("nearest", "kalman"):
                    result = run_candidate(case["case_id"], system)
                    results.append(result)
                    print(
                        encode(
                            {
                                "run_id": result["run_id"],
                                "scenario": scenario,
                                "seed": seed,
                                "system": system,
                                "status": result["status"],
                            }
                        ),
                        flush=True,
                    )
        print(encode(compare(results)))
        if any(result["status"] != "complete" for result in results):
            raise SystemExit(1)
    elif args.action == "serve":
        import uvicorn

        uvicorn.run("fusion_bench.server:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
