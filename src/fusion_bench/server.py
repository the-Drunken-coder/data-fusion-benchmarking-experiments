"""Single-user local control plane. Candidate commands are registered on disk, never via HTTP."""

import threading
import uuid
import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .generate import generate
from .report import run_detail
from .runner import run_candidate
from .schema import SCENARIOS, CaseConfig, ExperimentRequest
from .storage import ROOT, data_root, read_json, write_json
from .systems import load_systems


@asynccontextmanager
async def lifespan(app: FastAPI):
    for path in (data_root() / "jobs").glob("*.json"):
        value = read_json(path)
        if value["status"] == "running" and not owner_alive(value):
            value.update(status="failed", error="Interrupted before experiment completion")
            write_json(path, value)
    for path in (data_root() / "runs").glob("*/result.json"):
        value = read_json(path)
        if value["status"] == "running" and not owner_alive(value):
            value.update(
                status="failed",
                failure="Interrupted before run completion",
                summary_scope="partial outputs retained; scoring unavailable",
            )
            write_json(path, value)
    yield


def owner_alive(value: dict) -> bool:
    owner = value.get("owner_pid")
    if not isinstance(owner, int) or owner <= 0:
        return False
    try:
        os.kill(owner, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


app = FastAPI(title="Fusion Lab", docs_url=None, redoc_url=None, lifespan=lifespan)
execution_lock = threading.Lock()


@app.middleware("http")
async def local_requests(request: Request, call_next):
    if request.url.hostname not in ("127.0.0.1", "localhost", "testserver"):
        return JSONResponse({"detail": "Local access only"}, status_code=403)
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Same-origin requests only"}, status_code=403)
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"detail": "JSON requests required"}, status_code=415)
    return await call_next(request)


def identifiers(value: str):
    if len(value) != 16 or any(character not in "0123456789abcdef" for character in value):
        raise HTTPException(404, "Not found")


@app.get("/api/catalog")
def catalog():
    root = data_root()
    cases = [read_json(path) for path in sorted((root / "cases").glob("*/manifest.json"))]
    runs = [read_json(path) for path in sorted((root / "runs").glob("*/result.json"))]
    jobs = [read_json(path) for path in sorted((root / "jobs").glob("*.json"))]
    return {
        "scenarios": list(SCENARIOS),
        "systems": [spec.model_dump() for spec, _ in load_systems().values()],
        "cases": cases,
        "runs": sorted(runs, key=lambda run: run["created_at"], reverse=True),
        "jobs": jobs,
    }


@app.get("/api/runs/{run_id}")
def detail(run_id: str):
    identifiers(run_id)
    try:
        return run_detail(run_id)
    except FileNotFoundError:
        raise HTTPException(404, "Run not found") from None


@app.get("/api/runs/{run_id}/trajectory.svg")
def plot(run_id: str):
    identifiers(run_id)
    path = data_root() / "runs" / run_id / "trajectory.svg"
    if not path.exists():
        raise HTTPException(404, "Plot is unavailable")
    return FileResponse(path, media_type="image/svg+xml", filename=f"{run_id}-trajectory.svg")


@app.post("/api/experiments", status_code=202)
def launch(request: ExperimentRequest):
    systems = load_systems()
    if len(set(request.system_ids)) != len(request.system_ids):
        raise HTTPException(422, "Select each system once")
    if any(
        system not in systems or request.mode not in systems[system][0].modes
        for system in request.system_ids
    ):
        raise HTTPException(422, "Selected system does not support this task")
    if request.suite and request.config.kind != "fixed":
        raise HTTPException(422, "The fixed suite cannot use exploratory overrides")
    if not execution_lock.acquire(blocking=False):
        raise HTTPException(409, "An experiment is already running")
    job_id = uuid.uuid4().hex[:16]
    path = data_root() / "jobs" / f"{job_id}.json"
    job = {
        "job_id": job_id,
        "status": "running",
        "run_ids": [],
        "case_id": None,
        "requested": len(request.system_ids) * (14 if request.suite else 1),
        "error": None,
        "owner_pid": os.getpid(),
    }
    write_json(path, job)

    def execute():
        try:
            failed = False
            seeds = (100, 101) if request.config.partition == "tuning" else (1000, 1001)
            configs = (
                [
                    CaseConfig(scenario=scenario, seed=seed, partition=request.config.partition)
                    for scenario in SCENARIOS
                    for seed in seeds
                ]
                if request.suite
                else [request.config]
            )
            for config in configs:
                case = generate(config)
                job["case_id"] = case["case_id"]
                write_json(path, job)
                for system in request.system_ids:
                    result = run_candidate(case["case_id"], system, request.mode)
                    failed |= result["status"] != "complete"
                    job["run_ids"].append(result["run_id"])
                    write_json(path, job)
            job["status"] = "failed" if failed else "complete"
        except Exception as error:
            job.update(status="failed", error=str(error))
        finally:
            write_json(path, job)
            execution_lock.release()

    threading.Thread(target=execute, daemon=True).start()
    return job


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    identifiers(job_id)
    try:
        return read_json(data_root() / "jobs" / f"{job_id}.json")
    except FileNotFoundError:
        raise HTTPException(404, "Job not found") from None


dist = ROOT / "web" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="web")
else:

    @app.get("/")
    def missing_build():
        return JSONResponse(
            {"detail": "Build the web interface with pnpm --dir web build"}, status_code=503
        )
