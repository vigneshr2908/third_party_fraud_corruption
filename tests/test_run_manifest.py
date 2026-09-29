"""Tests for the run manifest - the reproducibility artefact."""
from __future__ import annotations

import json

from apnd.run_manifest import RunManifest, file_sha256, package_versions

REQUIRED_REPRO_FIELDS = (
    "git_sha", "git_branch", "config_files", "config_hash", "random_seed",
    "scale", "environment", "python_version", "platform", "package_versions",
)


def test_manifest_records_every_reproducibility_field():
    with RunManifest(phase="T_test", description="unit test") as mf:
        mf.add_parameter("alpha", 0.05)
        mf.add_metric("rows", 10)
    d = mf.to_dict()
    for key in REQUIRED_REPRO_FIELDS:
        assert key in d["reproducibility"], f"manifest missing field: {key}"
    assert d["status"] == "succeeded"
    assert d["parameters"]["alpha"] == 0.05
    assert d["metrics"]["rows"] == 10
    _cleanup(mf)


def test_manifest_written_to_disk():
    mf = RunManifest(phase="T_written")
    path = mf.close()
    assert path.exists()
    assert json.loads(path.read_text())["phase"] == "T_written"
    path.unlink()


def test_manifest_records_failure():
    """A crashed phase must be as traceable as a successful one."""
    mf = RunManifest(phase="T_failure")
    try:
        with mf:
            raise ValueError("deliberate")
    except ValueError:
        pass
    assert mf.status == "failed"
    assert any("deliberate" in n for n in mf.notes)
    _cleanup(mf)


def test_input_hashing(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("hello")
    mf = RunManifest(phase="T_hash")
    mf.add_input(f)
    assert mf.inputs[0]["sha256"] == file_sha256(f)
    assert mf.inputs[0]["size_bytes"] == 5


def test_output_records_shape(tmp_path):
    f = tmp_path / "out.csv"
    f.write_text("a,b\n1,2\n")
    mf = RunManifest(phase="T_out")
    mf.add_output(f, rows=1, cols=2)
    assert mf.outputs[0]["rows"] == 1
    assert mf.outputs[0]["cols"] == 2
    assert "sha256" in mf.outputs[0]


def test_package_versions_includes_tracked_packages():
    versions = package_versions()
    assert "pandas" in versions
    assert "numpy" in versions


def _cleanup(mf: RunManifest) -> None:
    out = mf.settings.path("manifests") / f"{mf.phase}_{mf.run_id}.json"
    if out.exists():
        out.unlink()