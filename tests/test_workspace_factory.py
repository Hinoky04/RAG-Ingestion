from src.workspace.factory import create_workspace_store


def test_workspace_factory_requires_postgres_dsn():
    try:
        create_workspace_store(database_url=None)
    except RuntimeError as exc:
        assert "WORKSPACE_DATABASE_URL" in str(exc)
    else:  # pragma: no cover - defensive branch
        raise AssertionError("Expected missing PostgreSQL DSN to raise RuntimeError")
