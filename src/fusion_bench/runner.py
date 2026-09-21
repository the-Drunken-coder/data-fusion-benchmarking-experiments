"""Causal lockstep subprocess runner with bounded protocol reads and immutable snapshots."""

import json
import os
import select
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .evaluate import evaluate
from .schema import Mode, Observation, Snapshot
from .storage import (
    data_root,
    digest,
    encode,
    environment,
    hashes,
    read_json,
    read_lines,
    verify,
    write_json,
    write_lines,
)
from .systems import load_systems, snapshot_system

MAX_LINE_BYTES = 1024 * 1024


class ProtocolError(Exception):
    pass


class CandidateProcess:
    def __init__(self, command: list[str], cwd: Path, stderr, stdout_log):
        env = {
            key: value
            for key, value in os.environ.items()
            if key in ("PATH", "SYSTEMROOT", "LANG", "LC_ALL", "TMPDIR")
        }
        env.update(
            PYTHONHASHSEED="0",
            PYTHONUNBUFFERED="1",
            OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1",
            HOME=str(cwd),
            MPLCONFIGDIR=str(cwd / ".mpl"),
        )
        self.process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            start_new_session=True,
            bufsize=0,
        )
        os.set_blocking(self.process.stdin.fileno(), False)
        self.stdout_log = stdout_log
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b""
        self.request_written = False

    def exchange(self, message: dict, timeout: float) -> tuple[dict, float, str]:
        start = time.perf_counter()
        self.request_written = False
        try:
            pending = memoryview((encode(message) + "\n").encode())
            while pending:
                remaining = timeout - (time.perf_counter() - start)
                if (
                    remaining <= 0
                    or not select.select([], [self.process.stdin], [], max(0, remaining))[1]
                ):
                    raise TimeoutError(f"Candidate exceeded {timeout:g} s request/response timeout")
                try:
                    written = os.write(self.process.stdin.fileno(), pending)
                    pending = pending[written:]
                except BlockingIOError:
                    continue
            self.request_written = True
        except BrokenPipeError as error:
            raise ProtocolError("Candidate exited before reading the request") from error
        while b"\n" not in self.buffer:
            remaining = timeout - (time.perf_counter() - start)
            if remaining <= 0 or not self.selector.select(max(0, remaining)):
                raise TimeoutError(f"Candidate exceeded {timeout:g} s response timeout")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise ProtocolError("Candidate closed stdout without a response")
            self.stdout_log.write(chunk)
            self.stdout_log.flush()
            self.buffer += chunk
            if len(self.buffer) > MAX_LINE_BYTES:
                raise ProtocolError("Candidate output exceeded 1 MiB limit")
        line, self.buffer = self.buffer.split(b"\n", 1)
        latency = (time.perf_counter() - start) * 1000
        if self.buffer.strip():
            raise ProtocolError("Candidate emitted more than one response for a request")
        try:
            text = line.decode("utf-8")

            def reject_constant(value):
                raise ValueError(f"Non-finite JSON number: {value}")

            value = json.loads(text, parse_constant=reject_constant)
            if not isinstance(value, dict):
                raise ValueError("Response must be an object")
        except (UnicodeError, ValueError) as error:
            raise ProtocolError(f"Invalid JSON response: {error}") from error
        return value, latency, text

    def close(self):
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait()
        self.selector.close()
        self.process.stdin.close()
        self.process.stdout.close()


def requests(init: dict, observations: list[dict], times: list[int]):
    """Export an explicit observation allowlist; never serialize simulator objects."""
    index = 0
    for step_id, tick in enumerate(times):
        batch = []
        while index < len(observations) and observations[index]["arrived_at_ms"] <= tick:
            obs = observations[index]
            fields = (
                "observation_id",
                "sensor_id",
                "measured_at_ms",
                "arrived_at_ms",
                "position_m",
                "position_cov_m2",
            )
            visible = {key: obs[key] for key in fields}
            if init["mode"] == "grouped":
                visible["group_key"] = obs["group_key"]
            batch.append(Observation.model_validate(visible).model_dump(exclude_none=True))
            index += 1
        yield {
            "type": "step",
            "schema_version": 1,
            "step_id": step_id,
            "time_ms": tick,
            "observations": batch,
        }


def run_candidate(
    case_id: str,
    system_id: str,
    mode: Mode = "ungrouped",
    *,
    root: Path | None = None,
    timeout: float = 5.0,
    init_timeout: float = 30.0,
) -> dict:
    root = root or data_root()
    spec, source = load_systems(root)[system_id]
    if mode not in spec.modes:
        raise ValueError(f"{system_id} does not support {mode} mode")
    case = root / "cases" / case_id
    manifest = read_json(case / "manifest.json")
    verify(case, manifest["hashes"])
    evaluator_hash = digest(Path(__file__).with_name("evaluate.py").read_bytes())
    if manifest.get("evaluator_sha256", evaluator_hash) != evaluator_hash:
        raise ValueError("Evaluator changed since this case was generated; regenerate the case")
    run_id = uuid.uuid4().hex[:16]
    destination = root / "runs" / run_id
    destination.mkdir(parents=True, exist_ok=False)
    version_hash = snapshot_system(source, destination / "system")
    filename = "observations.jsonl" if mode == "ungrouped" else "grouped-observations.jsonl"
    observations = read_lines(case / "public" / filename)
    truth = read_lines(case / "private" / "truth.jsonl")
    init = read_json(case / "public" / "init.json")
    init["mode"] = mode
    if mode == "grouped":
        init["control_label"] = "Oracle association and filtered clutter"
    request_list = list(requests(init, observations, [frame["time_ms"] for frame in truth]))
    write_json(destination / "init.json", init)
    write_lines(destination / "requests.jsonl", request_list)
    result = {
        "run_id": run_id,
        "case_id": case_id,
        "system": spec.model_dump(),
        "system_hash": version_hash,
        "mode": mode,
        "status": "running",
        "owner_pid": os.getpid(),
        "failure": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": manifest["config"],
        "case_hash": digest(encode(manifest["hashes"]).encode()),
        "scoring": manifest["scoring"],
        "environment": environment(),
        "evaluator_sha256": evaluator_hash,
        "timeout_s": timeout,
        "init_timeout_s": init_timeout,
        "observations_delivered": 0,
        "observations_acknowledged": 0,
        "timeouts": 0,
        "invalid_outputs": 0,
        "successful_steps": 0,
    }
    write_json(destination / "result.json", result)
    outputs, timings = [], []
    candidate = None
    try:
        # Only the source snapshot is placed in the candidate working directory.
        # This is isolation for cooperative programs, not a hostile-code sandbox.
        with tempfile.TemporaryDirectory(prefix="fusion-candidate-") as temp:
            cwd = Path(temp)
            import shutil

            shutil.copytree(destination / "system", cwd / "system")
            command = [
                part.replace("{python}", sys.executable).replace(
                    "{system_dir}", str(cwd / "system")
                )
                for part in spec.command
            ]
            result["command_template"] = spec.command
            with (
                (destination / "stderr.log").open("wb") as stderr,
                (destination / "outputs.jsonl").open("x") as output_log,
                (destination / "raw-responses.jsonl").open("x") as raw_log,
                (destination / "stdout.bin").open("xb") as stdout_log,
            ):
                candidate = CandidateProcess(command, cwd / "system", stderr, stdout_log)
                try:
                    ack, elapsed, raw = candidate.exchange(init, init_timeout)
                    raw_log.write(raw + "\n")
                    if (
                        ack != {"type": "ready", "schema_version": 1}
                        or type(ack.get("schema_version")) is not int
                    ):
                        raise ProtocolError("Expected ready response after init")
                    result["initialization_ms"] = elapsed
                    for request in request_list:
                        try:
                            response, elapsed, raw = candidate.exchange(request, timeout)
                        finally:
                            if candidate.request_written:
                                result["observations_delivered"] += len(request["observations"])
                        raw_log.write(raw + "\n")
                        raw_log.flush()
                        try:
                            snapshot = Snapshot.model_validate(response)
                        except ValueError as error:
                            raise ProtocolError(str(error)) from error
                        if (
                            snapshot.step_id != request["step_id"]
                            or snapshot.time_ms != request["time_ms"]
                        ):
                            raise ProtocolError("Response step_id/time_ms does not match request")
                        value = snapshot.model_dump(exclude_none=True)
                        output_log.write(encode(value) + "\n")
                        output_log.flush()
                        outputs.append(value)
                        timings.append(
                            {
                                "step_id": request["step_id"],
                                "time_ms": request["time_ms"],
                                "latency_ms": elapsed,
                                "observations": len(request["observations"]),
                            }
                        )
                        result["observations_acknowledged"] += len(request["observations"])
                        result["successful_steps"] += 1
                    result["status"] = "complete"
                finally:
                    candidate.close()
    except (TimeoutError, ProtocolError, OSError) as error:
        result["status"] = "failed"
        result["failure"] = str(error)
        result["timeouts"] = int(isinstance(error, TimeoutError))
        result["invalid_outputs"] = int(isinstance(error, ProtocolError))
    write_lines(destination / "timing.jsonl", timings)
    try:
        metrics = evaluate(truth, outputs, manifest["scoring"])
    except Exception as error:
        result.update(status="failed", failure=f"Evaluator failed: {error}")
        metrics = evaluate(truth, [], manifest["scoring"])
    write_json(destination / "metrics.json", metrics)
    result["summary"] = metrics["summary"]
    latencies = [tick["latency_ms"] for tick in timings]
    result["latency_ms"] = {
        "median": float(np.median(latencies)) if latencies else None,
        "p95": float(np.percentile(latencies, 95)) if latencies else None,
        "max": max(latencies) if latencies else None,
    }
    result["summary_scope"] = (
        "full run" if result["status"] == "complete" else "partial valid prefix; not comparable"
    )
    from .report import trajectory_plot

    try:
        trajectory_plot(destination / "trajectory.svg", truth, outputs)
    except Exception as error:
        result["plot_error"] = str(error)
    write_json(destination / "result.json", result)
    (destination / "summary.txt").write_text(
        f"{spec.name} {spec.version}: {result['status']}\n"
        f"Case: {case_id}; mode: {mode}; scope: {result['summary_scope']}\n"
        f"Metrics: {encode(result['summary'])}\nLatency (ms): {encode(result['latency_ms'])}\n"
        f"Failure: {result['failure']}\n"
    )
    write_json(destination / "manifest.json", {"hashes": hashes(destination)})
    return result
