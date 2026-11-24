"""Exercise the submitted Streamlit pages against a disposable PostgreSQL DB."""

import os
from pathlib import Path
import pytest


@pytest.mark.integration
@pytest.mark.parametrize("navigation_key,page", [
    ("nav-overview", "Overview"),
    ("nav-upload-history", "Upload & history"),
    ("nav-result-review", "Result review"),
    ("nav-retrieval-validation", "Retrieval"),
])
def test_submission_page_navigation(monkeypatch, navigation_key, page):
    dsn = os.environ.get("RAG_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set RAG_TEST_DATABASE_URL to an empty disposable database")
    from psycopg.conninfo import conninfo_to_dict
    assert conninfo_to_dict(dsn).get("dbname", "").endswith("_test")
    monkeypatch.setenv("WORKSPACE_DATABASE_URL", dsn)
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"), default_timeout=20)
    app.run()
    assert not app.exception
    app.button(key=navigation_key).click().run()
    assert not app.exception
    assert not app.error
    assert app.session_state["active_page"] == page
