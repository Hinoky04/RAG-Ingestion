from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.representation.schemas import DocumentRecord
from src.workspace.models import WorkspaceDocument

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None
    dict_row = None


SCHEMA_PATH = Path(__file__).parents[2] / "db" / "schema.sql"


class PostgreSQLWorkspace:
    """PostgreSQL repository for document records and artifacts."""

    def __init__(self, dsn: str) -> None:
        if psycopg is None:
            raise RuntimeError("PostgreSQL support requires `psycopg[binary]`.")
        self.dsn = dsn
        self._init_db()

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _init_db(self) -> None:
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
            self._replace_documents_status_constraint(cursor)

    def _replace_documents_status_constraint(self, cursor) -> None:
        allowed = ("registered", "review_ready", "approved", "validated", "low_confidence", "indexed", "failed")
        existing = cursor.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'documents'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE 'CHECK ((status = ANY (%'
            """
        ).fetchall()
        for row in existing:
            cursor.execute(f'ALTER TABLE documents DROP CONSTRAINT IF EXISTS "{row["conname"]}"')
        values_sql = ", ".join(f"'{value}'" for value in allowed)
        cursor.execute(
            f"""
            ALTER TABLE documents
            ADD CONSTRAINT documents_status_check
            CHECK (status IN ({values_sql}))
            """
        )

    def upsert_document(self, record: DocumentRecord, status: str = "registered") -> str:
        now = datetime.now(timezone.utc)
        with self.connect() as connection, connection.cursor() as cursor:
            existing = cursor.execute(
                "SELECT document_id, created_at FROM documents WHERE source_path = %s",
                (record.source_path,),
            ).fetchone()
            document_id = str(existing["document_id"]) if existing else record.document_id
            created_at = existing["created_at"] if existing else now

            cursor.execute(
                """
                INSERT INTO documents (
                    document_id, source_path, file_name, file_type, checksum, document_type,
                    version, status, parser_name, parser_version, collection_name, error_message,
                    metadata_json, created_at, updated_at, indexed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL, NULL, %s::jsonb, %s, %s, NULL)
                ON CONFLICT (document_id) DO UPDATE SET
                    source_path = EXCLUDED.source_path,
                    file_name = EXCLUDED.file_name,
                    file_type = EXCLUDED.file_type,
                    checksum = EXCLUDED.checksum,
                    document_type = EXCLUDED.document_type,
                    version = EXCLUDED.version,
                    status = EXCLUDED.status,
                    error_message = NULL,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    document_id, record.source_path, record.file_name, record.file_type,
                    record.checksum, record.document_type, record.version, status,
                    json.dumps({}), created_at, now,
                ),
            )
            cursor.execute(
                "UPDATE document_versions SET is_current = false WHERE document_id = %s",
                (document_id,),
            )
            cursor.execute(
                """
                INSERT INTO document_versions (
                    document_id, version_label, source_hash, status, is_current, metadata_json, created_at
                ) VALUES (%s, %s, %s, %s, true, %s::jsonb, %s)
                ON CONFLICT (document_id, source_hash) DO UPDATE SET
                    version_label = EXCLUDED.version_label,
                    status = EXCLUDED.status,
                    is_current = true,
                    metadata_json = EXCLUDED.metadata_json
                """,
                (document_id, record.version, record.checksum, status, json.dumps({"source_path": record.source_path}), now),
            )
        return document_id

    def record_ingestion_success(
        self,
        document_id: str,
        parser_name: str,
        parser_version: str,
        artifacts: dict[str, str],
        status: str = "validated",
        validation_summary: dict | None = None,
        validation_events: list[dict] | None = None,
        chunks: list[dict] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE documents
                   SET status = %s, parser_name = %s, parser_version = %s,
                       error_message = NULL, updated_at = %s, indexed_at = NULL
                   WHERE document_id = %s""",
                (status, parser_name, parser_version, now, document_id),
            )
            for artifact_type, artifact_path in artifacts.items():
                meta, summary = self._artifact_info(artifact_path)
                cursor.execute(
                    """
                    INSERT INTO artifacts (document_id, artifact_type, artifact_path, artifact_meta, artifact_summary, created_at)
                    VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                    ON CONFLICT (document_id, artifact_type) DO UPDATE SET
                        artifact_path = EXCLUDED.artifact_path,
                        artifact_meta = EXCLUDED.artifact_meta,
                        artifact_summary = EXCLUDED.artifact_summary,
                        created_at = EXCLUDED.created_at
                    """,
                    (document_id, artifact_type, artifact_path, json.dumps(meta), json.dumps(summary), now),
                )
            self._replace_chunks(cursor, document_id, chunks or [], now)
            cursor.execute(
                """UPDATE document_versions
                   SET parser_name = %s, parser_version = %s, status = %s
                   WHERE document_id = %s AND is_current = true""",
                (parser_name, parser_version, status, document_id),
            )
            run = cursor.execute(
                """INSERT INTO processing_runs (document_id, run_status, parser_name, parser_version, validation_summary, created_at)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s) RETURNING run_id""",
                (document_id, status, parser_name, parser_version, json.dumps(validation_summary or {}), now),
            ).fetchone()
            self._insert_validation_events(cursor, document_id, run["run_id"], validation_events or [])

    def record_ingestion_failure(self, document_id: str, error_message: str) -> None:
        now = datetime.now(timezone.utc)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE documents SET status = 'failed', error_message = %s, updated_at = %s WHERE document_id = %s",
                (error_message, now, document_id),
            )
            run = cursor.execute(
                """INSERT INTO processing_runs (document_id, run_status, validation_summary, created_at)
                   VALUES (%s, 'failed', %s::jsonb, %s) RETURNING run_id""",
                (document_id, json.dumps({"error_message": error_message}), now),
            ).fetchone()
            self._insert_validation_events(cursor, document_id, run["run_id"], [{
                "severity": "error", "event_code": "INGESTION_FAILED", "event_message": error_message,
            }])

    def mark_indexed(self, document_id: str, collection_name: str) -> None:
        now = datetime.now(timezone.utc)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE documents SET status = 'indexed', collection_name = %s, indexed_at = %s, updated_at = %s
                   WHERE document_id = %s""",
                (collection_name, now, now, document_id),
            )
            cursor.execute("UPDATE chunks SET indexed_at = %s WHERE document_id = %s", (now, document_id))
            cursor.execute(
                """INSERT INTO processing_runs (document_id, run_status, validation_summary, created_at)
                   VALUES (%s, 'indexed', %s::jsonb, %s)""",
                (document_id, json.dumps({"collection_name": collection_name}), now),
            )

    def mark_approved(self, document_id: str) -> None:
        now = datetime.now(timezone.utc)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE documents
                   SET status = 'approved', error_message = NULL, updated_at = %s
                   WHERE document_id = %s""",
                (now, document_id),
            )
            cursor.execute(
                """UPDATE document_versions
                   SET status = 'approved'
                   WHERE document_id = %s AND is_current = true""",
                (document_id,),
            )
            cursor.execute(
                """INSERT INTO processing_runs (document_id, run_status, validation_summary, created_at)
                   VALUES (%s, 'approved', %s::jsonb, %s)""",
                (document_id, json.dumps({"action": "manual_approval"}), now),
            )

    def mark_unindexed(self, document_id: str, status: str = "approved") -> None:
        now = datetime.now(timezone.utc)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE documents
                   SET status = %s, collection_name = NULL, indexed_at = NULL, updated_at = %s
                   WHERE document_id = %s""",
                (status, now, document_id),
            )
            cursor.execute("UPDATE chunks SET indexed_at = NULL WHERE document_id = %s", (document_id,))
            cursor.execute(
                """UPDATE document_versions
                   SET status = %s
                   WHERE document_id = %s AND is_current = true""",
                (status, document_id),
            )
            cursor.execute(
                """INSERT INTO processing_runs (document_id, run_status, validation_summary, created_at)
                   VALUES (%s, %s, %s::jsonb, %s)""",
                (document_id, status, json.dumps({"action": "removed_from_index"}), now),
            )

    def delete_document(self, document_id: str) -> None:
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM documents WHERE document_id = %s", (document_id,))

    def list_documents(self, status: str | None = None) -> list[WorkspaceDocument]:
        query = "SELECT * FROM documents"
        params: list[str] = []
        if status:
            query += " WHERE status = %s"
            params.append(status)
        query += " ORDER BY updated_at DESC, file_name ASC"
        with self.connect() as connection, connection.cursor() as cursor:
            rows = cursor.execute(query, params).fetchall()
            return [self._row_to_document(cursor, row) for row in rows]

    def get_document(self, document_id: str) -> WorkspaceDocument | None:
        with self.connect() as connection, connection.cursor() as cursor:
            row = cursor.execute("SELECT * FROM documents WHERE document_id = %s", (document_id,)).fetchone()
            return self._row_to_document(cursor, row) if row else None

    def get_document_by_checksum(self, checksum: str) -> WorkspaceDocument | None:
        with self.connect() as connection, connection.cursor() as cursor:
            row = cursor.execute(
                "SELECT * FROM documents WHERE checksum = %s ORDER BY updated_at DESC LIMIT 1",
                (checksum,),
            ).fetchone()
            return self._row_to_document(cursor, row) if row else None

    def list_documents_by_filename(self, file_name: str) -> list[WorkspaceDocument]:
        with self.connect() as connection, connection.cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM documents WHERE file_name = %s ORDER BY created_at ASC, updated_at ASC",
                (file_name,),
            ).fetchall()
            return [self._row_to_document(cursor, row) for row in rows]

    def stats(self) -> dict[str, int]:
        with self.connect() as connection, connection.cursor() as cursor:
            rows = cursor.execute("SELECT status, COUNT(*) AS count FROM documents GROUP BY status").fetchall()
        result = {str(row["status"]): int(row["count"]) for row in rows}
        result["total"] = sum(result.values())
        return result

    def get_latest_validation_summary(self, document_id: str) -> dict | None:
        with self.connect() as connection, connection.cursor() as cursor:
            run = cursor.execute(
                """SELECT run_id, run_status, parser_name, parser_version, validation_summary, created_at
                   FROM processing_runs WHERE document_id = %s ORDER BY run_id DESC LIMIT 1""",
                (document_id,),
            ).fetchone()
            if not run:
                return None
            events = cursor.execute(
                "SELECT severity, event_code, event_message, event_meta FROM validation_events WHERE run_id = %s ORDER BY event_id",
                (run["run_id"],),
            ).fetchall()
        return {
            "run_status": run["run_status"],
            "parser": " ".join(part for part in [run["parser_name"], run["parser_version"]] if part),
            "created_at": run["created_at"].isoformat(timespec="seconds"),
            "summary": run["validation_summary"] or {},
            "events": [dict(event) for event in events],
        }

    def list_chunks(self, document_id: str) -> list[dict]:
        with self.connect() as connection, connection.cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM chunks WHERE document_id = %s ORDER BY chunk_index", (document_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def _artifact_info(self, artifact_path: str) -> tuple[dict, dict]:
        path = Path(artifact_path)
        meta = {"path": artifact_path, "exists": path.exists(), "suffix": path.suffix.lower()}
        if not path.exists():
            return meta, {}
        meta["size_bytes"] = path.stat().st_size
        if path.suffix.lower() != ".json":
            return meta, {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return meta | {"json_read_error": str(exc)}, {}
        if isinstance(payload, list):
            return meta, {"item_count": len(payload)}
        if isinstance(payload, dict):
            return meta, {"block_count": len(payload.get("blocks", []))}
        return meta, {}

    def _replace_chunks(self, cursor, document_id: str, chunks: list[dict], now: datetime) -> None:
        cursor.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
        for index, chunk in enumerate(chunks, start=1):
            cursor.execute(
                """INSERT INTO chunks (
                    chunk_id, document_id, chunk_index, section_path, page_start, page_end,
                    text_preview, source_block_ids, metadata_json, created_at, indexed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, NULL)""",
                (
                    chunk["chunk_id"], document_id, chunk.get("chunk_index", index), chunk.get("section_path"),
                    chunk.get("page_start"), chunk.get("page_end"), chunk.get("text_preview", ""),
                    json.dumps(chunk.get("source_block_ids", [])), json.dumps(chunk.get("metadata_json", {})), now,
                ),
            )

    def _insert_validation_events(self, cursor, document_id: str, run_id: int, events: list[dict]) -> None:
        for event in events:
            cursor.execute(
                """INSERT INTO validation_events (document_id, run_id, severity, event_code, event_message, event_meta)
                   VALUES (%s, %s, %s, %s, %s, %s::jsonb)""",
                (
                    document_id, run_id, event.get("severity", "info"), event.get("event_code", "VALIDATION_EVENT"),
                    event.get("event_message", ""), json.dumps(event.get("event_meta", {})),
                ),
            )

    def _row_to_document(self, cursor, row: dict) -> WorkspaceDocument:
        artifact_rows = cursor.execute(
            "SELECT artifact_type, artifact_path FROM artifacts WHERE document_id = %s", (row["document_id"],)
        ).fetchall()
        return WorkspaceDocument(
            document_id=str(row["document_id"]), source_path=str(row["source_path"]), file_name=str(row["file_name"]),
            file_type=str(row["file_type"]), checksum=str(row["checksum"]), document_type=str(row["document_type"]),
            version=str(row["version"]), status=str(row["status"]), parser_name=row["parser_name"],
            parser_version=row["parser_version"], collection_name=row["collection_name"], error_message=row["error_message"],
            created_at=row["created_at"], updated_at=row["updated_at"], indexed_at=row["indexed_at"],
            artifacts={str(item["artifact_type"]): str(item["artifact_path"]) for item in artifact_rows},
        )
