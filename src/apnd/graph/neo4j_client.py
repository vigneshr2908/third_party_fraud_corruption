"""
Neo4j connection handling.

Design decision
---------------
Credentials come from environment variables, never from config/. config/ is
committed; .env is not. A password in a YAML file is a finding in any bank
security review, and it is the kind of thing that ends up in a public repository.

Neo4j is optional. Setting `neo4j.enabled: false` in config/base.yaml lets the
whole pipeline run on NetworkX alone, so a Neo4j problem never blocks analysis.
Neo4j is there for investigator-style Cypher queries and demonstration; NetworkX
remains the analytics engine.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from apnd.logging_setup import get_logger
from apnd.settings import Settings, get_settings

log = get_logger(__name__)


class Neo4jConfigurationError(RuntimeError):
    """Raised when Neo4j is enabled but not configured."""


class Neo4jClient:
    """Thin wrapper over the official driver.

    Usage::

        with Neo4jClient() as client:
            client.health_check()
            rows = client.run("MATCH (n) RETURN count(n) AS n")
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        cfg = self.settings.neo4j
        self.enabled = cfg.enabled
        self.database = cfg.database
        self.uri = os.environ.get(cfg.uri_env_var)
        self.user = os.environ.get(cfg.user_env_var)
        self.password = os.environ.get(cfg.password_env_var)
        self._driver: Any = None

    # ------------------------------------------------------------- lifecycle
    def connect(self) -> None:
        if not self.enabled:
            log.info("Neo4j disabled in configuration; skipping connection")
            return

        missing = [
            var for var, val in (
                (self.settings.neo4j.uri_env_var, self.uri),
                (self.settings.neo4j.user_env_var, self.user),
                (self.settings.neo4j.password_env_var, self.password),
            ) if not val
        ]
        if missing:
            raise Neo4jConfigurationError(
                "Neo4j is enabled but these environment variables are not set: "
                f"{', '.join(missing)}. Copy .env.example to .env and fill it in, "
                "or set neo4j.enabled: false in config/base.yaml."
            )

        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover
            raise Neo4jConfigurationError(
                "The neo4j package is not installed. Run: pip install -e '.[graph]'"
            ) from exc

        self._driver = GraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
            connection_timeout=self.settings.neo4j.connection_timeout_seconds,
            max_connection_lifetime=self.settings.neo4j.max_connection_lifetime_seconds,
        )
        log.info("Neo4j driver created", extra={"uri": self.uri, "database": self.database})

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self) -> Neo4jClient:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    # ----------------------------------------------------------------- usage
    @contextmanager
    def session(self) -> Iterator[Any]:
        if self._driver is None:
            self.connect()
        if self._driver is None:
            raise Neo4jConfigurationError("Neo4j is disabled; no session available")
        session = self._driver.session(database=self.database)
        try:
            yield session
        finally:
            session.close()

    def run(self, query: str, **params: Any) -> list[dict[str, Any]]:
        with self.session() as session:
            return [dict(record) for record in session.run(query, **params)]

    def health_check(self) -> dict[str, Any]:
        """Verify the database answers, and report what is in it.

        Reports, never raises: a health check that crashes the CLI defeats its
        own purpose.
        """
        if not self.enabled:
            return {"enabled": False, "reachable": False,
                    "detail": "Neo4j disabled in configuration"}
        try:
            rows = self.run("RETURN 1 AS ok")
            nodes = self.run("MATCH (n) RETURN count(n) AS node_count")
            rels = self.run("MATCH ()-[r]->() RETURN count(r) AS rel_count")
            return {
                "enabled": True,
                "reachable": bool(rows and rows[0].get("ok") == 1),
                "database": self.database,
                "node_count": nodes[0]["node_count"] if nodes else None,
                "relationship_count": rels[0]["rel_count"] if rels else None,
            }
        except Exception as exc:
            log.warning("Neo4j health check failed", extra={"error": str(exc)})
            return {"enabled": True, "reachable": False, "detail": str(exc)}