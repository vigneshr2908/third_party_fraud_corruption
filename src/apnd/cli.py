"""
Command-line entry point.

Design decision
---------------
Every phase runs through one CLI rather than a folder of ad-hoc scripts. A
reviewer can read this file and see everything the project does, and each
command opens a run manifest, so nothing executes without leaving an audit
record.

Phase commands are registered here as they are built. A1 ships `check` and
`config-show`.
"""
from __future__ import annotations

import argparse
import json
import sys

from apnd import __version__
from apnd.logging_setup import get_logger, setup_logging
from apnd.run_manifest import RunManifest, git_branch, git_is_dirty, git_sha, package_versions
from apnd.settings import CONFIG_DIR, REPO_ROOT, get_settings

log = get_logger(__name__)

CORE_PACKAGES = {"pandas", "numpy", "pyarrow"}


def cmd_check(args: argparse.Namespace) -> int:
    """Environment health check. Run first, and after any dependency change."""
    settings = get_settings()
    setup_logging(level=args.log_level)

    print("\n" + "=" * 74)
    print("  ENVIRONMENT CHECK")
    print("=" * 74)

    ok = True

    print("\n[ configuration ]")
    print(f"  model id / version   : {settings.project.model_id} v{settings.project.model_version}")
    print(f"  owner function       : {settings.project.owner_function}")
    print(f"  environment          : {settings.run.environment}")
    print(f"  scale                : {settings.run.scale}")
    print(f"  random seed          : {settings.run.random_seed}")
    print(f"  alert capacity (K)   : {settings.analysis.alert_capacity_k}")
    print(f"  config files loaded  : {', '.join(settings.config_files)}")
    print(f"  config hash          : {settings.config_hash[:16]}...")
    print(f"  config directory     : {CONFIG_DIR}")

    print("\n[ version control ]")
    sha, branch, dirty = git_sha(), git_branch(), git_is_dirty()
    print(f"  git sha              : {sha or 'NOT A GIT REPOSITORY'}")
    print(f"  git branch           : {branch or '-'}")
    print(f"  working tree         : {'DIRTY - commit before a recorded run' if dirty else 'clean'}")
    if sha is None:
        print("  WARNING: run manifests cannot record a commit outside a git repository")
        ok = False

    print("\n[ packages ]")
    for pkg, ver in package_versions().items():
        installed = ver != "not installed"
        print(f"  {'  ' if installed else '!!'} {pkg:<16} {ver}")
        if not installed and pkg in CORE_PACKAGES:
            ok = False

    print("\n[ directories ]")
    for key in ("data_raw", "data_interim", "data_processed", "outputs",
                "manifests", "figures", "reports"):
        p = settings.path(key)
        print(f"  {key:<16} {p.relative_to(REPO_ROOT)}")

    print("\n[ neo4j ]")
    try:
        from apnd.graph.neo4j_client import Neo4jClient
        status = Neo4jClient(settings).health_check()
        for k, v in status.items():
            print(f"  {k:<20} {v}")
        if status.get("enabled") and not status.get("reachable"):
            print("  NOTE: Neo4j is optional. NetworkX remains the analytics engine.")
    except Exception as exc:
        print(f"  health check error: {exc}")

    print("\n" + "=" * 74)
    print(f"  RESULT: {'READY' if ok else 'ATTENTION NEEDED - see items marked !!'}")
    print("=" * 74 + "\n")

    with RunManifest(phase="A1_environment_check",
                     description="Environment and configuration health check") as mf:
        mf.add_parameter("log_level", args.log_level)
        mf.add_metric("ready", ok)

    return 0 if ok else 1


def cmd_config_show(args: argparse.Namespace) -> int:
    """Print the merged configuration, or one dotted key from it."""
    settings = get_settings()
    if args.key:
        print(json.dumps(settings.get(args.key, "<key not found>"), indent=2, default=str))
    else:
        print(json.dumps(settings.raw if args.full else settings.summary(),
                         indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apnd",
        description="Third-Party Fraud & Corruption Network Detection",
    )
    parser.add_argument("--version", action="version", version=f"apnd {__version__}")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="environment and configuration health check")
    p_check.set_defaults(func=cmd_check)

    p_cfg = sub.add_parser("config-show", help="print merged configuration")
    p_cfg.add_argument("--key", help="dotted key, e.g. run.scale")
    p_cfg.add_argument("--full", action="store_true", help="print the entire merged config")
    p_cfg.set_defaults(func=cmd_config_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())