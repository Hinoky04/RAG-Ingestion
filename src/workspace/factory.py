from __future__ import annotations

import os

from src.workspace.base import WorkspaceStore
from src.workspace.postgres_workspace import PostgreSQLWorkspace


def create_workspace_store(
    database_url: str | None = None,
) -> WorkspaceStore:
    dsn = database_url or os.getenv("WORKSPACE_DATABASE_URL")
    if not dsn:
        raise RuntimeError("PostgreSQL workspace requires WORKSPACE_DATABASE_URL to be set.")
    return PostgreSQLWorkspace(dsn)
