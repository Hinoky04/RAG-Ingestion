from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.representation.schemas import DocumentRecord
from src.workspace.models import WorkspaceDocument

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    psycopg = None
    dict_row = None


class PostgreSQLWorkspace:
    backend_name = "postgresql"

    def __init__(self, dsn: str) -> None:
        if psycopg is None:
            raise RuntimeError(
                "PostgreSQL backend requires `psycopg[binary]`. Install dependencies before using the workspace."
            )
        self.dsn = dsn
        self.location_label = dsn
        self._init_db()

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _init_db(self) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        email TEXT UNIQUE,
                        display_name TEXT,
                        role TEXT NOT NULL DEFAULT 'viewer',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );

                    CREATE TABLE IF NOT EXISTS clients (
                        client_id TEXT PRIMARY KEY,
                        client_name TEXT NOT NULL,
                        owner_user_id TEXT REFERENCES users(user_id),
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );

                    CREATE TABLE IF NOT EXISTS user_client_access (
                        user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                        client_id TEXT NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
                        permission TEXT NOT NULL DEFAULT 'viewer',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (user_id, client_id)
                    );

                    CREATE TABLE IF NOT EXISTS documents (
                        document_id TEXT PRIMARY KEY,
                        source_path TEXT NOT NULL UNIQUE,
                        file_name TEXT NOT NULL,
                        file_type TEXT NOT NULL,
                        checksum TEXT NOT NULL,
                        client_id TEXT NOT NULL REFERENCES clients(client_id),
                        document_type TEXT NOT NULL,
                        version TEXT NOT NULL,
                        access_scope TEXT NOT NULL,
                        status TEXT NOT NULL,
                        parser_name TEXT,
                        parser_version TEXT,
                        collection_name TEXT,
                        error_message TEXT,
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        approved_at TIMESTAMPTZ,
                        indexed_at TIMESTAMPTZ
                    );

                    CREATE TABLE IF NOT EXISTS document_versions (
                        version_id BIGSERIAL PRIMARY KEY,
                        document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                        version_label TEXT NOT NULL,
                        source_hash TEXT NOT NULL,
                        parser_name TEXT,
                        parser_version TEXT,
                        chunking_version TEXT,
                        status TEXT NOT NULL,
                        is_current BOOLEAN NOT NULL DEFAULT true,
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(document_id, version_label, source_hash)
                    );

                    CREATE TABLE IF NOT EXISTS artifacts (
                        artifact_id BIGSERIAL PRIMARY KEY,
                        document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                        artifact_type TEXT NOT NULL,
                        artifact_path TEXT NOT NULL,
                        artifact_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
                        artifact_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(document_id, artifact_type)
                    );

                    CREATE TABLE IF NOT EXISTS chunks (
                        chunk_id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                        chunk_index INTEGER NOT NULL,
                        section_path TEXT,
                        page_start INTEGER,
                        page_end INTEGER,
                        text_preview TEXT NOT NULL,
                        source_block_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL,
                        indexed_at TIMESTAMPTZ,
                        UNIQUE(document_id, chunk_index)
                    );

                    CREATE TABLE IF NOT EXISTS processing_runs (
                        run_id BIGSERIAL PRIMARY KEY,
                        document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                        run_status TEXT NOT NULL,
                        parser_name TEXT,
                        parser_version TEXT,
                        validation_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS validation_events (
                        event_id BIGSERIAL PRIMARY KEY,
                        document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                        run_id BIGINT REFERENCES processing_runs(run_id) ON DELETE SET NULL,
                        severity TEXT NOT NULL,
                        event_code TEXT NOT NULL,
                        event_message TEXT NOT NULL,
                        event_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );

                    CREATE INDEX IF NOT EXISTS idx_documents_client_status
                        ON documents (client_id, status);

                    CREATE INDEX IF NOT EXISTS idx_documents_metadata_json
                        ON documents USING GIN (metadata_json);

                    CREATE INDEX IF NOT EXISTS idx_artifacts_meta_json
                        ON artifacts USING GIN (artifact_meta);

                    CREATE INDEX IF NOT EXISTS idx_chunks_document
                        ON chunks (document_id, chunk_index);

                    CREATE INDEX IF NOT EXISTS idx_chunks_metadata_json
                        ON chunks USING GIN (metadata_json);

                    CREATE INDEX IF NOT EXISTS idx_runs_validation_json
                        ON processing_runs USING GIN (validation_summary);
                    """
                )
                # Old local databases may still contain the review-gate table.
                # The current workflow uses automated validation instead.
                cursor.execute("DROP TABLE IF EXISTS reviews")
                cursor.execute("ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS artifact_summary JSONB NOT NULL DEFAULT '{}'::jsonb")
                cursor.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb")
                cursor.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ")
                # Migrate old review statuses into the automation status model
                # without deleting previously parsed artifacts.
                cursor.execute(
                    """
                    UPDATE documents d
                    SET status = CASE
                            WHEN EXISTS (
                                SELECT 1
                                FROM artifacts a
                                WHERE a.document_id = d.document_id
                                  AND a.artifact_type = 'chunks'
                            )
                            THEN 'validated'
                            ELSE 'low_confidence'
                        END,
                        updated_at = now()
                    WHERE d.status IN ('review_pending', 'approved', 'rejected')
                    """
                )
                cursor.execute(
                    """
                    UPDATE document_versions v
                    SET status = d.status
                    FROM documents d
                    WHERE v.document_id = d.document_id
                      AND v.is_current = true
                      AND v.status IN ('review_pending', 'approved', 'rejected')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO clients (client_id, client_name, metadata_json)
                    SELECT DISTINCT client_id, client_id, '{"source":"migration_backfill"}'::jsonb
                    FROM documents
                    ON CONFLICT (client_id) DO NOTHING
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO document_versions (
                        document_id, version_label, source_hash, parser_name, parser_version,
                        chunking_version, status, is_current, metadata_json, created_at
                    )
                    SELECT
                        document_id,
                        version,
                        checksum,
                        parser_name,
                        parser_version,
                        NULL,
                        status,
                        true,
                        jsonb_build_object('source_path', source_path, 'file_type', file_type, 'source', 'migration_backfill'),
                        created_at
                    FROM documents
                    ON CONFLICT (document_id, version_label, source_hash) DO NOTHING
                    """
                )
                # Existing artifact rows may predate the chunks table. Backfill
                # lightweight chunk metadata from saved chunk JSON files.
                self._backfill_chunks_from_artifacts(cursor)
            connection.commit()

    def upsert_document(self, record: DocumentRecord, status: str = "registered") -> str:
        timestamp = datetime.now(timezone.utc)
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO clients (client_id, client_name, metadata_json)
                    VALUES (%s, %s, %s::jsonb)
                    ON CONFLICT (client_id) DO UPDATE SET
                        client_name = EXCLUDED.client_name
                    """,
                    (record.client_id, record.client_id, json.dumps({"source": "workspace_ingestion"})),
                )
                existing = cursor.execute(
                    "SELECT document_id, created_at FROM documents WHERE source_path = %s",
                    (record.source_path,),
                ).fetchone()
                document_id = record.document_id if existing is None else str(existing["document_id"])
                created_at = timestamp if existing is None else existing["created_at"]

                cursor.execute(
                    """
                    INSERT INTO documents (
                        document_id, source_path, file_name, file_type, checksum, client_id, document_type,
                        version, access_scope, status, parser_name, parser_version, collection_name,
                        error_message, metadata_json, created_at, updated_at, approved_at, indexed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL, NULL, %s::jsonb, %s, %s, NULL, NULL)
                    ON CONFLICT (document_id) DO UPDATE SET
                        source_path = EXCLUDED.source_path,
                        file_name = EXCLUDED.file_name,
                        file_type = EXCLUDED.file_type,
                        checksum = EXCLUDED.checksum,
                        client_id = EXCLUDED.client_id,
                        document_type = EXCLUDED.document_type,
                        version = EXCLUDED.version,
                        access_scope = EXCLUDED.access_scope,
                        status = EXCLUDED.status,
                        error_message = NULL,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        document_id,
                        record.source_path,
                        record.file_name,
                        record.file_type,
                        record.checksum,
                        record.client_id,
                        record.document_type,
                        record.version,
                        record.access_scope,
                        status,
                        json.dumps({}),
                        created_at,
                        timestamp,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE document_versions
                    SET is_current = false
                    WHERE document_id = %s AND is_current = true
                    """,
                    (document_id,),
                )
                cursor.execute(
                    """
                    INSERT INTO document_versions (
                        document_id, version_label, source_hash, parser_name, parser_version,
                        chunking_version, status, is_current, metadata_json, created_at
                    ) VALUES (%s, %s, %s, NULL, NULL, NULL, %s, true, %s::jsonb, %s)
                    ON CONFLICT (document_id, version_label, source_hash) DO UPDATE SET
                        status = EXCLUDED.status,
                        is_current = true,
                        metadata_json = EXCLUDED.metadata_json
                    """,
                    (
                        document_id,
                        record.version,
                        record.checksum,
                        status,
                        json.dumps({"source_path": record.source_path, "file_type": record.file_type}),
                        timestamp,
                    ),
                )
            connection.commit()
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
        timestamp = datetime.now(timezone.utc)
        summary = validation_summary or {}
        events = validation_events or []
        chunk_rows = chunks or []
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE documents
                    SET status = %s, parser_name = %s, parser_version = %s, error_message = NULL, updated_at = %s
                    WHERE document_id = %s
                    """,
                    (status, parser_name, parser_version, timestamp, document_id),
                )
                for artifact_type, artifact_path in artifacts.items():
                    artifact_meta, artifact_summary = self._artifact_json_info(artifact_path)
                    cursor.execute(
                        """
                        INSERT INTO artifacts (
                            document_id, artifact_type, artifact_path, artifact_meta, artifact_summary, created_at
                        )
                        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                        ON CONFLICT (document_id, artifact_type) DO UPDATE SET
                            artifact_path = EXCLUDED.artifact_path,
                            artifact_meta = EXCLUDED.artifact_meta,
                            artifact_summary = EXCLUDED.artifact_summary,
                            created_at = EXCLUDED.created_at
                        """,
                        (
                            document_id,
                            artifact_type,
                            artifact_path,
                            json.dumps(artifact_meta),
                            json.dumps(artifact_summary),
                            timestamp,
                        ),
                    )
                self._replace_chunks(cursor, document_id, chunk_rows, timestamp)
                cursor.execute(
                    """
                    UPDATE document_versions
                    SET parser_name = %s,
                        parser_version = %s,
                        status = %s,
                        metadata_json = metadata_json || %s::jsonb
                    WHERE document_id = %s AND is_current = true
                    """,
                    (
                        parser_name,
                        parser_version,
                        status,
                        json.dumps({"artifact_types": sorted(artifacts)}),
                        document_id,
                    ),
                )
                run_row = cursor.execute(
                    """
                    INSERT INTO processing_runs (
                        document_id, run_status, parser_name, parser_version, validation_summary, created_at
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    RETURNING run_id
                    """,
                    (document_id, status, parser_name, parser_version, json.dumps(summary), timestamp),
                ).fetchone()
                self._insert_validation_events(cursor, document_id, run_row["run_id"], events)
            connection.commit()

    def record_ingestion_failure(self, document_id: str, error_message: str) -> None:
        timestamp = datetime.now(timezone.utc)
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE documents
                    SET status = %s, error_message = %s, updated_at = %s
                    WHERE document_id = %s
                    """,
                    ("failed", error_message, timestamp, document_id),
                )
                run_row = cursor.execute(
                    """
                    INSERT INTO processing_runs (
                        document_id, run_status, parser_name, parser_version, validation_summary, created_at
                    ) VALUES (%s, %s, NULL, NULL, %s::jsonb, %s)
                    RETURNING run_id
                    """,
                    (document_id, "failed", json.dumps({"error_message": error_message}), timestamp),
                ).fetchone()
                self._insert_validation_events(
                    cursor,
                    document_id,
                    run_row["run_id"],
                    [
                        {
                            "severity": "error",
                            "event_code": "INGESTION_FAILED",
                            "event_message": error_message,
                            "event_meta": {},
                        }
                    ],
                )
            connection.commit()

    def mark_indexed(self, document_id: str, collection_name: str) -> None:
        timestamp = datetime.now(timezone.utc)
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE documents
                    SET status = %s, collection_name = %s, indexed_at = %s, updated_at = %s
                    WHERE document_id = %s
                    """,
                    ("indexed", collection_name, timestamp, timestamp, document_id),
                )
                cursor.execute(
                    """
                    INSERT INTO processing_runs (
                        document_id, run_status, parser_name, parser_version, validation_summary, created_at
                    )
                    SELECT document_id, %s, parser_name, parser_version, %s::jsonb, %s
                    FROM documents
                    WHERE document_id = %s
                    """,
                    ("indexed", json.dumps({"collection_name": collection_name}), timestamp, document_id),
                )
                cursor.execute(
                    """
                    UPDATE chunks
                    SET indexed_at = %s
                    WHERE document_id = %s
                    """,
                    (timestamp, document_id),
                )
            connection.commit()

    def list_documents(self, status: str | None = None) -> list[WorkspaceDocument]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                query = """
                    SELECT d.*
                    FROM documents d
                """
                params: list[str] = []
                if status is not None:
                    query += " WHERE d.status = %s"
                    params.append(status)
                query += " ORDER BY d.updated_at DESC, d.file_name ASC"
                rows = cursor.execute(query, params).fetchall()
                return [self._row_to_document(connection, row) for row in rows]

    def get_document(self, document_id: str) -> WorkspaceDocument | None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    SELECT d.*
                    FROM documents d
                    WHERE d.document_id = %s
                    """,
                    (document_id,),
                ).fetchone()
                if row is None:
                    return None
                return self._row_to_document(connection, row)

    def stats(self) -> dict[str, int]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    "SELECT status, COUNT(*) AS count FROM documents GROUP BY status"
                ).fetchall()
        stats = {str(row["status"]): int(row["count"]) for row in rows}
        stats["total"] = sum(stats.values())
        return stats

    def get_latest_validation_summary(self, document_id: str) -> dict | None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                run = cursor.execute(
                    """
                    SELECT run_id, run_status, parser_name, parser_version, validation_summary, created_at
                    FROM processing_runs
                    WHERE document_id = %s
                    ORDER BY created_at DESC, run_id DESC
                    LIMIT 1
                    """,
                    (document_id,),
                ).fetchone()
                if run is None:
                    return None
                events = cursor.execute(
                    """
                    SELECT severity, event_code, event_message, event_meta, created_at
                    FROM validation_events
                    WHERE run_id = %s
                    ORDER BY event_id ASC
                    """,
                    (run["run_id"],),
                ).fetchall()
        return {
            "run_status": run["run_status"],
            "parser": f"{run['parser_name'] or '-'} {run['parser_version'] or ''}".strip(),
            "created_at": run["created_at"].isoformat(timespec="seconds"),
            "summary": run["validation_summary"] or {},
            "events": [
                {
                    "severity": event["severity"],
                    "event_code": event["event_code"],
                    "event_message": event["event_message"],
                    "event_meta": event["event_meta"],
                    "created_at": event["created_at"].isoformat(timespec="seconds"),
                }
                for event in events
            ],
        }

    def list_chunks(self, document_id: str) -> list[dict]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    SELECT
                        chunk_id, chunk_index, section_path, page_start, page_end,
                        text_preview, source_block_ids, metadata_json, created_at, indexed_at
                    FROM chunks
                    WHERE document_id = %s
                    ORDER BY chunk_index ASC
                    """,
                    (document_id,),
                ).fetchall()
        return [
            {
                "chunk_id": row["chunk_id"],
                "chunk_index": row["chunk_index"],
                "section_path": row["section_path"],
                "page_start": row["page_start"],
                "page_end": row["page_end"],
                "text_preview": row["text_preview"],
                "source_block_ids": row["source_block_ids"],
                "metadata_json": row["metadata_json"],
                "created_at": row["created_at"].isoformat(timespec="seconds"),
                "indexed_at": row["indexed_at"].isoformat(timespec="seconds") if row["indexed_at"] else None,
            }
            for row in rows
        ]

    def _artifact_json_info(self, artifact_path: str) -> tuple[dict, dict]:
        # Store only a small summary in PostgreSQL. The full artifact remains
        # on disk so large parser outputs do not bloat the control database.
        path = Path(artifact_path)
        meta = {
            "path": artifact_path,
            "exists": path.exists(),
            "suffix": path.suffix.lower(),
        }
        if path.exists():
            meta["size_bytes"] = path.stat().st_size

        if path.suffix.lower() != ".json" or not path.exists():
            return meta, {}

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return meta | {"json_read_error": str(exc)}, {}

        if isinstance(payload, list):
            return meta | {"json_type": "array"}, {"item_count": len(payload)}
        if isinstance(payload, dict):
            return meta | {"json_type": "object"}, {
                "keys": sorted(payload.keys())[:30],
                "block_count": len(payload.get("blocks", [])) if isinstance(payload.get("blocks"), list) else None,
            }
        return meta | {"json_type": type(payload).__name__}, {}

    def _insert_validation_events(self, cursor, document_id: str, run_id: int, events: list[dict]) -> None:
        for event in events:
            cursor.execute(
                """
                INSERT INTO validation_events (
                    document_id, run_id, severity, event_code, event_message, event_meta
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    document_id,
                    run_id,
                    event.get("severity", "info"),
                    event.get("event_code", "VALIDATION_EVENT"),
                    event.get("event_message", ""),
                    json.dumps(event.get("event_meta", {})),
                ),
            )

    def _replace_chunks(self, cursor, document_id: str, chunks: list[dict], timestamp: datetime) -> None:
        # Re-parse should replace chunk metadata for the current document so
        # stale chunk ids do not remain attached to a newer parser run.
        cursor.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
        for index, chunk in enumerate(chunks, start=1):
            cursor.execute(
                """
                INSERT INTO chunks (
                    chunk_id, document_id, chunk_index, section_path, page_start, page_end,
                    text_preview, source_block_ids, metadata_json, created_at, indexed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, NULL)
                """,
                (
                    chunk["chunk_id"],
                    document_id,
                    int(chunk.get("chunk_index") or index),
                    chunk.get("section_path"),
                    chunk.get("page_start"),
                    chunk.get("page_end"),
                    chunk.get("text_preview", ""),
                    json.dumps(chunk.get("source_block_ids", [])),
                    json.dumps(chunk.get("metadata_json", {})),
                    timestamp,
                ),
            )

    def _backfill_chunks_from_artifacts(self, cursor) -> None:
        rows = cursor.execute(
            """
            SELECT a.document_id, a.artifact_path
            FROM artifacts a
            LEFT JOIN chunks c ON c.document_id = a.document_id
            WHERE a.artifact_type = 'chunks'
            GROUP BY a.document_id, a.artifact_path
            HAVING COUNT(c.chunk_id) = 0
            """
        ).fetchall()
        timestamp = datetime.now(timezone.utc)
        for row in rows:
            path = Path(str(row["artifact_path"]))
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, list):
                continue
            chunks = []
            for index, item in enumerate(payload, start=1):
                if not isinstance(item, dict) or not item.get("chunk_id"):
                    continue
                chunks.append(
                    {
                        "chunk_id": item.get("chunk_id"),
                        "chunk_index": index,
                        "section_path": item.get("section_path"),
                        "page_start": item.get("page_start"),
                        "page_end": item.get("page_end"),
                        "text_preview": str(item.get("text", ""))[:500],
                        "source_block_ids": item.get("source_block_ids", []),
                        "metadata_json": item.get("metadata", {}),
                    }
                )
            self._replace_chunks(cursor, str(row["document_id"]), chunks, timestamp)

    def _row_to_document(self, connection, row: dict) -> WorkspaceDocument:
        with connection.cursor() as cursor:
            artifact_rows = cursor.execute(
                "SELECT artifact_type, artifact_path FROM artifacts WHERE document_id = %s",
                (row["document_id"],),
            ).fetchall()
        artifacts = {str(item["artifact_type"]): str(item["artifact_path"]) for item in artifact_rows}
        return WorkspaceDocument(
            document_id=str(row["document_id"]),
            source_path=str(row["source_path"]),
            file_name=str(row["file_name"]),
            file_type=str(row["file_type"]),
            checksum=str(row["checksum"]),
            client_id=str(row["client_id"]),
            document_type=str(row["document_type"]),
            version=str(row["version"]),
            access_scope=str(row["access_scope"]),
            status=str(row["status"]),
            parser_name=row["parser_name"],
            parser_version=row["parser_version"],
            collection_name=row["collection_name"],
            error_message=row["error_message"],
            created_at=row["created_at"] or datetime.now(timezone.utc),
            updated_at=row["updated_at"] or datetime.now(timezone.utc),
            approved_at=row["approved_at"],
            indexed_at=row["indexed_at"],
            artifacts=artifacts,
        )
