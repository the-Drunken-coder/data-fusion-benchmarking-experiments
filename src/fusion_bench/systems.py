"""Explicit local system manifests; source snapshots are the executed version."""

import shutil
from pathlib import Path

from .schema import SystemSpec
from .storage import ROOT, data_root, digest, encode, read_json

SKIP = {".git", ".venv", "__pycache__", "node_modules", ".DS_Store"}


def system_files(directory: Path) -> list[Path]:
    files = []
    for path in sorted(directory.rglob("*")):
        if any(part in SKIP for part in path.relative_to(directory).parts):
            continue
        if path.is_symlink():
            raise ValueError("System bundles cannot contain symlinks")
        if path.is_file():
            files.append(path)
    if sum(path.stat().st_size for path in files) > 256 * 1024 * 1024:
        raise ValueError("System bundle exceeds the initial 256 MiB snapshot limit")
    return files


def load_systems(root: Path | None = None) -> dict:
    result = {}
    for parent in (ROOT / "systems", (root or data_root()) / "systems"):
        if not parent.exists():
            continue
        for manifest in sorted(parent.glob("*/system.json")):
            spec = SystemSpec.model_validate(read_json(manifest))
            if spec.id in result:
                raise ValueError(f"Duplicate system ID: {spec.id}")
            result[spec.id] = (spec, manifest.parent)
    return result


def snapshot_system(directory: Path, destination: Path) -> str:
    destination.mkdir(parents=True, exist_ok=False)
    values = {}
    for source in system_files(directory):
        relative = source.relative_to(directory)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        values[str(relative)] = digest(target.read_bytes())
    return digest(encode(values).encode())


def register(directory: Path, root: Path | None = None) -> str:
    root = root or data_root()
    directory = directory.resolve()
    spec = SystemSpec.model_validate(read_json(directory / "system.json"))
    if spec.id in load_systems(root):
        raise ValueError("System ID already exists; register a new ID for a new imported version")
    snapshot_system(directory, root / "systems" / spec.id)
    return spec.id
