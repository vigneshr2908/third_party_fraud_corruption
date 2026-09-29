"""
Structured logging.

Design decision
---------------
Logs are written as JSON lines, not free text. Two reasons:

1. Audit trail. When a validator or auditor asks what the pipeline did on a
   given run, grepping structured records beats reading prose.
2. Every record carries the run_id, so logs from a phase can be tied back to the
   manifest that describes it.

A human-readable console handler runs alongside the JSON file handler, because
nobody wants to read JSON while developing.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apnd.settings import REPO_ROOT

LOG_DIR = REPO_ROOT / "outputs" / "logs"
_CONFIGURED = False

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Readable single line for interactive use."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s  %(levelname)-8s  %(name)-28s  %(message)s",
            datefmt="%H:%M:%S",
        )


def setup_logging(level: str = "INFO", run_id: str | None = None,
                  log_dir: Path | None = None) -> logging.Logger:
    """Configure root logging once per process."""
    global _CONFIGURED

    root = logging.getLogger()
    if _CONFIGURED:
        return logging.getLogger("apnd")

    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(ConsoleFormatter())
    root.addHandler(console)

    directory = Path(log_dir) if log_dir else LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    file_handler = logging.FileHandler(directory / f"apnd_{stamp}.jsonl", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)

    if run_id:
        logging.setLogRecordFactory(_run_id_factory(logging.getLogRecordFactory(), run_id))

    logging.getLogger("neo4j").setLevel(logging.WARNING)

    _CONFIGURED = True
    return logging.getLogger("apnd")


def _run_id_factory(base_factory, run_id: str):
    def factory(*args, **kwargs):
        record = base_factory(*args, **kwargs)
        record.run_id = run_id
        return record
    return factory


def get_logger(name: str) -> logging.Logger:
    """Module-level logger: ``log = get_logger(__name__)``."""
    return logging.getLogger(f"apnd.{name}" if not name.startswith("apnd") else name)