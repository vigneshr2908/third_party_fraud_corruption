"""
Configuration loading and validation.

Design decision
---------------
Every parameter the pipeline uses is loaded from config/*.yaml through this
module. No threshold, weight or rate is written into src/. Two reasons, both of
them model-risk reasons rather than style preferences:

1. An independent validator must be able to read the parameters without reading
   the code. A hard-coded 0.85 buried in a function is a validation finding.
2. A parameter change must appear as a config diff in version control, so the
   run manifest can record exactly which parameter set produced which output.

Config files are DISCOVERED, not listed. A1 ships base.yaml alone; later phases
drop in their own file (entity_resolution.yaml at A6, rules.yaml at A8,
scoring.yaml at A12) and this module needs no edit. Files load in sorted order
and deep-merge, so a later file can extend an earlier one.

The merged config is hashed on load and that hash goes into every run manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Repository root: this file is src/apnd/settings.py, so the root is 3 levels up
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

# base.yaml must exist; everything else is optional and phase-owned.
REQUIRED_CONFIG_FILES = ("base.yaml",)


# --------------------------------------------------------------------------- #
# Validated models for the sections the code depends on. Sections not modelled
# here are still available as plain dictionaries via Settings.raw - validation is
# applied where a wrong value would silently corrupt a result.
# --------------------------------------------------------------------------- #
class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    short_name: str
    model_id: str
    model_version: str
    owner_function: str
    methodology_owner: str
    validator: str


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    scale: float = Field(gt=0.0, le=1.0)
    random_seed: int = Field(ge=0)
    environment: str
    strict_mode: bool = True

    @field_validator("environment")
    @classmethod
    def _known_environment(cls, v: str) -> str:
        allowed = {"development", "validation", "production"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {sorted(allowed)}, got {v!r}")
        return v


class PathsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    data_raw: str
    data_interim: str
    data_processed: str
    data_external: str
    outputs: str
    manifests: str
    figures: str
    reports: str


class Neo4jConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    uri_env_var: str
    user_env_var: str
    password_env_var: str
    database: str
    connection_timeout_seconds: int = 30
    max_connection_lifetime_seconds: int = 3600
    enabled: bool = True


class AnalysisConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    alert_capacity_k: int = Field(gt=0)
    minutes_per_alert_review: int = Field(gt=0)
    expected_base_rate: float = Field(gt=0.0, lt=1.0)


class Settings:
    """Merged, validated view of every configuration file present.

    Access validated sections as attributes (``settings.run.scale``) and anything
    else through ``settings.raw`` or :meth:`get`.
    """

    def __init__(self, raw: dict[str, Any], config_hash: str,
                 config_files: tuple[str, ...] = ()) -> None:
        self.raw = raw
        self.config_hash = config_hash
        self.config_files = config_files

        self.project = ProjectConfig(**raw["project"])
        self.run = RunConfig(**raw["run"])
        self.paths = PathsConfig(**raw["paths"])
        self.neo4j = Neo4jConfig(**raw["neo4j"])
        self.analysis = AnalysisConfig(**raw["analysis"])

        self._validate_composite_weights()

    # ----------------------------------------------------------------- helpers
    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Fetch a nested value, e.g. ``settings.get("run.scale")``."""
        node: Any = self.raw
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, key: str) -> Path:
        """Absolute path for a configured directory, created if absent."""
        rel = getattr(self.paths, key)
        p = REPO_ROOT / rel
        p.mkdir(parents=True, exist_ok=True)
        return p

    def scaled(self, source_count: int) -> int:
        """Scale a source cardinality by run.scale, never below 1."""
        return max(1, round(source_count * self.run.scale))

    def is_domain(self, cardinality: int) -> bool:
        """True when a dimension domain is small enough to keep at full size."""
        return cardinality <= int(self.get("data.domain_keep_threshold", 50))

    # -------------------------------------------------------------- validation
    def _validate_composite_weights(self) -> None:
        """Composite components must sum to 1.0 once scoring.yaml exists (A12).

        Inert until that file is added. It lives here rather than in the scoring
        module because a weight set that does not sum to one produces a ranking
        that looks fine and is wrong - it has to fail at load time, before any
        pipeline work begins.
        """
        comps = self.get("composite_score.components", {})
        if not comps:
            return
        total = sum(float(c.get("weight", 0.0)) for c in comps.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"composite_score component weights must sum to 1.0, got {total:.6f}. "
                f"Check config/scoring.yaml."
            )
        for name, comp in comps.items():
            inputs = comp.get("inputs", {})
            if inputs:
                s = sum(float(v) for v in inputs.values())
                if abs(s - 1.0) > 1e-9:
                    raise ValueError(
                        f"composite_score.components.{name}.inputs must sum to 1.0, "
                        f"got {s:.6f}."
                    )

    def summary(self) -> dict[str, Any]:
        return {
            "model_id": self.project.model_id,
            "model_version": self.project.model_version,
            "environment": self.run.environment,
            "scale": self.run.scale,
            "random_seed": self.run.random_seed,
            "alert_capacity_k": self.analysis.alert_capacity_k,
            "config_files": list(self.config_files),
            "config_hash": self.config_hash,
        }


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _deep_merge(base: dict, incoming: dict) -> dict:
    out = dict(base)
    for k, v in incoming.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _apply_env_overrides(raw: dict) -> dict:
    """Allow a small, explicit set of environment overrides.

    Only these keys can be overridden from the environment. Anything else must be
    a config change, so that it is visible in version control.
    """
    overrides = {
        "APND_SCALE": ("run", "scale", float),
        "APND_SEED": ("run", "random_seed", int),
        "APND_ENVIRONMENT": ("run", "environment", str),
        "APND_ALERT_CAPACITY_K": ("analysis", "alert_capacity_k", int),
    }
    for env_key, (section, key, cast) in overrides.items():
        val = os.environ.get(env_key)
        if val is not None:
            raw.setdefault(section, {})[key] = cast(val)
    return raw


def _hash_config(raw: dict) -> str:
    """Stable SHA-256 of the fully merged configuration."""
    payload = json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_settings(config_dir: Path | None = None) -> Settings:
    """Discover, merge, validate and hash every configuration file present."""
    cdir = Path(config_dir) if config_dir else CONFIG_DIR
    if not cdir.exists():
        raise FileNotFoundError(f"Configuration directory not found: {cdir}")

    for required in REQUIRED_CONFIG_FILES:
        if not (cdir / required).exists():
            raise FileNotFoundError(f"Required configuration file missing: {cdir / required}")

    files = sorted(p for p in cdir.glob("*.yaml") if p.is_file())
    merged: dict[str, Any] = {}
    for fpath in files:
        with fpath.open("r", encoding="utf-8") as fh:
            content = yaml.safe_load(fh) or {}
        if not isinstance(content, dict):
            raise ValueError(f"{fpath} must contain a YAML mapping at the top level")
        merged = _deep_merge(merged, content)

    merged = _apply_env_overrides(merged)
    return Settings(merged, _hash_config(merged), tuple(f.name for f in files))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide cached settings. Use this everywhere in the pipeline."""
    return load_settings()