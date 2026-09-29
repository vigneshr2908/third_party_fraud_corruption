"""Smoke tests: the package imports, the CLI parses, the config is coherent."""
from __future__ import annotations

import pytest

from apnd import __model_id__, __version__
from apnd.cli import build_parser
from apnd.logging_setup import setup_logging
from apnd.settings import load_settings


def test_package_metadata():
    assert __version__
    assert __model_id__ == "APND-001"


def test_package_version_matches_config():
    """Code version and model version move together, by design."""
    s = load_settings()
    assert s.project.model_version == __version__
    assert s.project.model_id == __model_id__


def test_cli_parser_builds():
    args = build_parser().parse_args(["check"])
    assert args.command == "check"


def test_cli_config_show_key():
    args = build_parser().parse_args(["config-show", "--key", "run.scale"])
    assert args.key == "run.scale"


def test_cli_requires_a_command():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_logging_writes_json_lines(tmp_path):
    log = setup_logging(level="DEBUG", run_id="testrun", log_dir=tmp_path)
    log.info("smoke", extra={"phase": "A1"})
    assert list(tmp_path.glob("*.jsonl")), "no JSON log file written"


@pytest.mark.parametrize("key", [
    "project.model_id", "run.scale", "run.random_seed", "run.environment",
    "paths.outputs", "paths.manifests", "analysis.alert_capacity_k",
    "data.source_row_counts.psr_master", "data.domain_keep_threshold",
    "neo4j.database",
])
def test_critical_parameters_present(key):
    """Guards against a config key being edited away without anyone noticing."""
    assert load_settings().get(key) is not None, f"missing critical parameter: {key}"


def test_secrets_are_not_in_config():
    """Credentials must never appear in config/. They come from the environment."""
    raw_text = str(load_settings().raw).lower()
    for forbidden in ("password:", "bolt://", "secret", "apikey", "api_key"):
        assert forbidden not in raw_text, f"possible credential in config: {forbidden}"