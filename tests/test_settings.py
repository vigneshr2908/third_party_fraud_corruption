"""Tests for configuration loading and validation.

These are not decorative. The composite-weight test in particular guards the
single most damaging silent failure in this project: a weight set that does not
sum to one produces a ranking that looks fine and is wrong. It is inert until
config/scoring.yaml arrives at A12, and it is written now so the guard exists
before the thing it guards.
"""
from __future__ import annotations

import pytest
import yaml

from apnd.settings import Settings, load_settings


def _minimal_raw() -> dict:
    """The smallest configuration that Settings will accept."""
    return {
        "project": {"name": "t", "short_name": "t", "model_id": "T", "model_version": "0",
                    "owner_function": "x", "methodology_owner": "y", "validator": "z"},
        "run": {"scale": 0.1, "random_seed": 1, "environment": "development"},
        "paths": {"data_raw": "data/raw", "data_interim": "data/interim",
                  "data_processed": "data/processed", "data_external": "data/external",
                  "outputs": "outputs", "manifests": "outputs/manifests",
                  "figures": "outputs/figures", "reports": "outputs/reports"},
        "neo4j": {"uri_env_var": "A", "user_env_var": "B", "password_env_var": "C",
                  "database": "d"},
        "analysis": {"alert_capacity_k": 10, "minutes_per_alert_review": 10,
                     "expected_base_rate": 0.03},
    }


def test_settings_load():
    s = load_settings()
    assert s.project.model_id
    assert 0.0 < s.run.scale <= 1.0
    assert s.run.random_seed >= 0
    assert s.analysis.alert_capacity_k > 0


def test_config_files_discovered():
    """A1 ships base.yaml alone; later phases add their own without code changes."""
    s = load_settings()
    assert "base.yaml" in s.config_files


def test_config_hash_is_stable():
    a, b = load_settings(), load_settings()
    assert a.config_hash == b.config_hash
    assert len(a.config_hash) == 64


def test_dotted_get():
    s = load_settings()
    assert s.get("run.scale") is not None
    assert s.get("does.not.exist", "fallback") == "fallback"


def test_scaled_never_below_one():
    s = load_settings()
    assert s.scaled(87166) == max(1, round(87166 * s.run.scale))
    assert s.scaled(1) >= 1
    assert s.scaled(0) == 1


def test_domain_threshold():
    s = load_settings()
    assert s.is_domain(5) is True
    assert s.is_domain(5000) is False


def test_missing_config_directory_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "nowhere")


def test_missing_base_yaml_is_rejected(tmp_path):
    (tmp_path / "other.yaml").write_text("project: {}")
    with pytest.raises(FileNotFoundError, match=r"base\.yaml"):
        load_settings(tmp_path)


def test_composite_weight_breach_is_rejected():
    """A broken weight set must fail at load time, not after a pipeline run."""
    raw = _minimal_raw()
    raw["composite_score"] = {"components": {
        "inherent": {"weight": 0.30}, "behavioural": {"weight": 0.30},
        "network": {"weight": 0.30}}}          # sums to 0.90 - must be rejected
    with pytest.raises(ValueError, match=r"must sum to 1\.0"):
        Settings(raw, "deadbeef")


def test_composite_weights_accepted_when_valid():
    raw = _minimal_raw()
    raw["composite_score"] = {"components": {
        "inherent": {"weight": 0.30}, "behavioural": {"weight": 0.35},
        "network": {"weight": 0.35}}}
    assert Settings(raw, "deadbeef").config_hash == "deadbeef"


def test_invalid_environment_rejected():
    raw = yaml.safe_load("""
    project: {name: t, short_name: t, model_id: T, model_version: "0",
              owner_function: x, methodology_owner: y, validator: z}
    run: {scale: 0.1, random_seed: 1, environment: staging}
    paths: {data_raw: a, data_interim: b, data_processed: c, data_external: d,
            outputs: e, manifests: f, figures: g, reports: h}
    neo4j: {uri_env_var: A, user_env_var: B, password_env_var: C, database: d}
    analysis: {alert_capacity_k: 10, minutes_per_alert_review: 10, expected_base_rate: 0.03}
    """)
    with pytest.raises(ValueError):
        Settings(raw, "deadbeef")


def test_scale_out_of_range_rejected():
    raw = _minimal_raw()
    raw["run"]["scale"] = 1.5
    with pytest.raises(ValueError):
        Settings(raw, "deadbeef")