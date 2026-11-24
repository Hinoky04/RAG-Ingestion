"""The delivered pipeline remains the repository's reference implementation."""
import hashlib
import json
from pathlib import Path


def test_pipeline_files_match_confirmed_final_submission():
    root = Path(__file__).parents[1]
    manifest = json.loads((root / "docs/submission_baseline.json").read_text(encoding="utf-8"))
    for entry in manifest["pipeline_files"]:
        path = root / entry["path"]
        assert path.is_file(), entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["path"]
