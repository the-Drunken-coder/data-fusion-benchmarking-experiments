"""Small append-only artifact store. Completed case and run directories are never reused."""

import hashlib
import importlib.metadata
import json
import os
import platform
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    return Path(os.environ.get("FUSION_DATA", str(ROOT / ".fusion"))).resolve()


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        stream.write(encode(value) + "\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text())


def write_lines(path: Path, values) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        for value in values:
            stream.write(encode(value) + "\n")


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def hashes(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): digest(path.read_bytes())
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path != directory / "manifest.json"
    }


def verify(directory: Path, expected: dict[str, str]) -> None:
    for name, checksum in expected.items():
        if digest((directory / name).read_bytes()) != checksum:
            raise ValueError(f"Artifact changed: {name}")


def environment() -> dict:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("stonesoup", "numpy", "scipy", "pydantic", "fusion-bench")
        },
        "lock_sha256": digest((ROOT / "uv.lock").read_bytes())
        if (ROOT / "uv.lock").exists()
        else None,
    }
