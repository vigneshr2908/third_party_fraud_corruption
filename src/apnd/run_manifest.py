"""
Run manifest - the reproducibility artefact.

Design decision
---------------
The first question an independent validator asks is "reproduce this result".
Answering it needs more than the code: it needs the exact commit, the exact
parameter set, the seed, the library versions and the checksums of the inputs
and outputs. A notebook that produced a number six weeks ago cannot answer that.

Every pipeline phase opens a RunManifest, records what it consumed and produced,
and closes it. The manifest lands in outputs/manifests/ as JSON and is the
evidence that links a result back to the code and configuration that made it.
Failures are recorded too, so a crashed run is as traceable as a successful one.

This is the single largest difference between a portfolio script and something a
bank's Model Risk Management function will accept.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import platform
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apnd.settings import REPO_ROOT, Settings, get_settings

TRACKED_PACKAGES = (
    "pandas", "numpy", "scipy", "statsmodels", "scikit-learn",
    "networkx", "duckdb", "pyarrow", "pandera", "splink", "neo4j",
)


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def git_sha() -> str | None:
    return _git("rev-parse", "HEAD")


def git_branch() -> str | None:
    return _git("rev-parse", "--abbrev-ref", "HEAD")


def git_is_dirty() -> bool | None:
    status = _git("status", "--porcelain")
    return None if status is None else bool(status)


def package_versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    out: dict[str, str] = {}
    for pkg in TRACKED_PACKAGES:
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "not installed"
    return out


def file_sha256(path: str | Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class RunManifest:
    """Records everything needed to reproduce one phase of the pipeline."""

    phase: str
    description: str = ""
    settings: Settings = field(default_factory=get_settings)

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    finished_at: str | None = None
    status: str = "running"

    inputs: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------- recording
    def add_input(self, path: str | Path, role: str = "input") -> None:
        p = Path(path)
        entry: dict[str, Any] = {"path": str(p), "role": role, "exists": p.exists()}
        if p.exists() and p.is_file():
            entry["sha256"] = file_sha256(p)
            entry["size_bytes"] = p.stat().st_size
        self.inputs.append(entry)

    def add_output(self, path: str | Path, rows: int | None = None,
                   cols: int | None = None) -> None:
        p = Path(path)
        entry: dict[str, Any] = {"path": str(p), "exists": p.exists()}
        if rows is not None:
            entry["rows"] = rows
        if cols is not None:
            entry["cols"] = cols
        if p.exists() and p.is_file():
            entry["sha256"] = file_sha256(p)
            entry["size_bytes"] = p.stat().st_size
        self.outputs.append(entry)

    def add_parameter(self, key: str, value: Any) -> None:
        self.parameters[key] = value

    def add_metric(self, key: str, value: Any) -> None:
        self.metrics[key] = value

    def add_note(self, text: str) -> None:
        self.notes.append(text)

    # --------------------------------------------------------------- closing
    def to_dict(self) -> dict[str, Any]:
        s = self.settings
        return {
            "run_id": self.run_id,
            "phase": self.phase,
            "description": self.description,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "model": {
                "model_id": s.project.model_id,
                "model_version": s.project.model_version,
                "owner_function": s.project.owner_function,
            },
            "reproducibility": {
                "git_sha": git_sha(),
                "git_branch": git_branch(),
                "git_working_tree_dirty": git_is_dirty(),
                "config_files": list(s.config_files),
                "config_hash": s.config_hash,
                "random_seed": s.run.random_seed,
                "scale": s.run.scale,
                "environment": s.run.environment,
                "python_version": sys.version.split()[0],
                "platform": platform.platform(),
                "executed_by": getpass.getuser(),
                "package_versions": package_versions(),
            },
            "parameters": self.parameters,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "metrics": self.metrics,
            "notes": self.notes,
        }

    def close(self, status: str = "succeeded") -> Path:
        self.status = status
        self.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
        manifest_dir = self.settings.path("manifests")
        out = manifest_dir / f"{self.phase}_{self.run_id}.json"
        out.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return out

    # ------------------------------------------------------------ context mgr
    def __enter__(self) -> RunManifest:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.add_note(f"FAILED: {exc_type.__name__}: {exc}")
            self.close(status="failed")
            return False
        self.close(status="succeeded")
        return True