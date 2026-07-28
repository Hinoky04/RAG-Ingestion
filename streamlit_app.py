from __future__ import annotations

import json
import os
import re
from pathlib import Path

import streamlit as st

from src.indexing.chroma_store import DEFAULT_CHROMA_DIR
from src.indexing.embedder import DEFAULT_MODEL_NAME
from src.retrieval.searcher import search
from src.workspace.service import WorkspaceService


DEFAULT_TOP_K = 3
DATASET_OPTIONS = {
    "Clean PDF": {
        "collection": "daythree_demo_clean",
        "clients": {"Client A": "client_a", "Client B": "client_b"},
    },
    "DOCX": {
        "collection": "daythree_demo_docx",
        "clients": {"Client A": "client_a", "Client B": "client_b"},
    },
    "Messy PDF": {
        "collection": "daythree_demo_messy",
        "clients": {"Client A": "client_a"},
    },
    "Public Reference": {
        "collection": "daythree_demo_public",
        "clients": {"Public Reference": "public_reference"},
    },
}
WORKSPACE_STATUSES = ["registered", "validated", "low_confidence", "indexed", "failed"]
KNOWN_CLIENT_IDS = [
    "maybank",
    "cimb",
    "public_bank",
    "standard_chartered",
    "hsbc",
    "hong_leong",
    "client_a",
    "client_b",
    "public_reference",
]


def setup_local_model_env() -> None:
    os.environ.setdefault("HF_HOME", ".cache/huggingface")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1240px;
            padding-top: 2.5rem;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.5rem;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 999px;
            padding: 0.4rem 0.9rem;
        }
        .stButton button {
            border-radius: 999px;
            font-weight: 600;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 16px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def read_text_if_exists(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def read_json_if_exists(path_value: str | None):
    text = read_text_if_exists(path_value)
    if not text:
        return None
    return json.loads(text)


def chunk_display_id(document, index: int) -> str:
    return f"{short_review_prefix(document)}-C{index:02d}"


def block_display_id(document, index: int) -> str:
    return f"{short_review_prefix(document)}-B{index:03d}"


def review_label(document) -> str:
    return f"{document.display_id} | {document.file_name} | {document.status}"


def set_selected_document(document_id: str) -> None:
    st.session_state["selected_document_id"] = document_id


def selected_document_id() -> str | None:
    return st.session_state.get("selected_document_id")


def normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def compact_token(value: str, length: int = 8) -> str:
    token = normalize_token(value).replace("_", "")
    return (token[:length] or "unknown").upper()


def short_review_prefix(document) -> str:
    # Short ids read better in review tables than the full display id.
    client = compact_token(document.client_id, length=6)
    doc_type = compact_token(document.document_type, length=5)
    suffix = document.document_id.split("_")[-1][-4:].upper()
    return f"{client}-{doc_type}-{suffix}"


def infer_upload_metadata(file_name: str) -> tuple[str, str]:
    # Keep this as an editable prefill. File-name inference is useful, but it
    # should not lock the operator into a wrong client or document type.
    name = normalize_token(Path(file_name).stem)
    file_type = Path(file_name).suffix.lower()

    client_id = "unknown"
    for known in KNOWN_CLIENT_IDS:
        if name.startswith(known):
            client_id = known
            break

    if "guidance" in name:
        document_type = "guidance_page"
    elif any(token in name for token in ["dispute", "fraud", "stolen", "unauthorized", "unauthorised", "report"]):
        document_type = "guidance_page"
    elif "faq" in name:
        document_type = "faq_page"
    elif "form" in name or "dispute" in name and file_type == ".pdf":
        document_type = "dispute_form"
    elif file_type == ".pdf":
        document_type = "pdf_document"
    elif file_type == ".docx":
        document_type = "docx_document"
    else:
        document_type = "unknown"

    return client_id, document_type


def render_workspace_tab(service: WorkspaceService) -> None:
    stats = service.workspace.stats()
    stat_columns = st.columns(4)
    stat_columns[0].metric("Total", stats.get("total", 0))
    stat_columns[1].metric("Validated", stats.get("validated", 0))
    stat_columns[2].metric("Needs Attention", stats.get("low_confidence", 0) + stats.get("failed", 0))
    stat_columns[3].metric("Indexed", stats.get("indexed", 0))

    # Split intake, tracking, and inspection so the page does not feel like one
    # long mixed workflow.
    upload_tab, history_tab, inspect_tab = st.tabs(["Upload", "History", "Inspect"])
    with upload_tab:
        render_upload_page(service)
    with history_tab:
        render_history_page(service)
    with inspect_tab:
        render_inspection_page(service)


def render_upload_page(service: WorkspaceService) -> None:
    with st.container(border=True):
        st.subheader("Upload")
        uploaded_file = st.file_uploader("Add PDF or DOCX", type=["pdf", "docx"])
        inferred_client = "unknown"
        inferred_type = "unknown"
        if uploaded_file is not None:
            inferred_client, inferred_type = infer_upload_metadata(uploaded_file.name)
        form_columns = st.columns(3)
        client_id = form_columns[0].text_input("Client ID", value=inferred_client)
        document_type = form_columns[1].text_input("Document Type", value=inferred_type)
        version = form_columns[2].text_input("Version", value="v1")

        if st.button("Save To Workspace", use_container_width=True, disabled=uploaded_file is None):
            if uploaded_file is None:
                st.warning("Choose a file first.")
            else:
                saved_path = service.save_uploaded_file(
                    file_name=uploaded_file.name,
                    file_bytes=uploaded_file.getvalue(),
                    client_id=client_id.strip() or "unknown",
                    document_type=document_type.strip() or "unknown",
                )
                record = service.register_path(
                    file_path=saved_path,
                    client_id=client_id.strip() or "unknown",
                    document_type=document_type.strip() or "unknown",
                    version=version.strip() or "v1",
                )
                set_selected_document(record.document_id)
                try:
                    service.ingest_document(record.document_id)
                except Exception as exc:
                    st.warning(f"Registered {record.file_name}, but automatic parsing failed: {exc}")
                else:
                    st.success(f"Registered and validated {record.file_name}")
                st.rerun()


def render_history_page(service: WorkspaceService) -> None:
    filter_columns = st.columns([2, 1])
    selected_status = filter_columns[0].selectbox("Status Filter", options=["all", *WORKSPACE_STATUSES], index=0)
    documents = service.workspace.list_documents(None if selected_status == "all" else selected_status)

    rows = [
        {
            "display_id": document.display_id,
            "file_name": document.file_name,
            "client_id": document.client_id,
            "document_type": document.document_type,
            "status": document.status,
            "parser": document.parser_name or "-",
            "updated_at": document.updated_at.isoformat(timespec="seconds"),
        }
        for document in documents
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    if not documents:
        st.info(f"No workspace documents for status `{selected_status}`.")
        return

    selection = filter_columns[1].selectbox(
        "Select",
        options=documents,
        format_func=review_label,
    )
    if st.button("Open Details", use_container_width=True):
        set_selected_document(selection.document_id)
        st.rerun()


def render_inspection_page(service: WorkspaceService) -> None:
    documents = service.workspace.list_documents()
    if not documents:
        st.info("No workspace documents yet.")
        return

    current_id = selected_document_id()
    current_document = next((item for item in documents if item.document_id == current_id), None)
    selection = st.selectbox(
        "Document",
        options=documents,
        index=documents.index(current_document) if current_document in documents else 0,
        format_func=review_label,
    )
    if current_id != selection.document_id:
        set_selected_document(selection.document_id)
    render_document_detail(service, selection.document_id)


def render_document_detail(service: WorkspaceService, document_id: str) -> None:
    document = service.workspace.get_document(document_id)
    if document is None:
        st.error("Document not found.")
        return

    with st.container(border=True):
        st.subheader("Automation Detail")
        st.caption(f"Display ID: {document.display_id}")
        meta_columns = st.columns(5)
        meta_columns[0].metric("Status", document.status)
        meta_columns[1].metric("Client", document.client_id)
        meta_columns[2].metric("Type", document.document_type)
        meta_columns[3].metric("Parser", document.parser_name or "-")
        meta_columns[4].metric("File Type", document.file_type)
        st.caption(document.source_path)

        action_columns = st.columns([1, 1])
        if action_columns[0].button("Parse / Validate", key=f"parse-{document.document_id}", use_container_width=True):
            try:
                service.ingest_document(document.document_id)
            except Exception as exc:
                st.error(f"Parse failed: {exc}")
            else:
                st.success("Document parsed and validated automatically.")
                st.rerun()

        collection_name = action_columns[1].text_input("Collection", value="workspace_automation", key=f"collection-{document.document_id}")
        if st.button("Index Validated Document", key=f"index-{document.document_id}", use_container_width=True):
            try:
                indexed_count = service.index_document(
                    document_id=document.document_id,
                    collection_name=collection_name.strip() or "workspace_automation",
                    persist_dir=DEFAULT_CHROMA_DIR,
                    model_name=DEFAULT_MODEL_NAME,
                )
            except Exception as exc:
                st.error(f"Index failed: {exc}")
            else:
                st.success(f"Indexed {indexed_count} chunk(s).")
                st.rerun()

        if document.error_message:
            st.error(document.error_message)

        # Keep the raw JSON for debugging, but show chunk/block tables first
        # because they are easier to review than nested payloads.
        preview_tabs = st.tabs(["Summary", "Markdown", "Chunks", "Blocks", "JSON"])
        markdown_text = read_text_if_exists(document.artifacts.get("markdown"))
        db_chunks = service.workspace.list_chunks(document.document_id)
        chunk_payload = db_chunks or read_json_if_exists(document.artifacts.get("chunks")) or []
        json_text = read_text_if_exists(document.artifacts.get("document_json"))
        json_payload = read_json_if_exists(document.artifacts.get("document_json")) or {}

        with preview_tabs[0]:
            validation_summary = service.workspace.get_latest_validation_summary(document.document_id)
            summary_rows = [
                {"field": "display_id", "value": document.display_id},
                {"field": "internal_document_id", "value": document.document_id},
                {"field": "file_name", "value": document.file_name},
                {"field": "client_id", "value": document.client_id},
                {"field": "document_type", "value": document.document_type},
                {"field": "status", "value": document.status},
                {"field": "parser", "value": document.parser_name or "-"},
                {"field": "collection", "value": document.collection_name or "-"},
                {"field": "updated_at", "value": document.updated_at.isoformat(timespec="seconds")},
            ]
            st.dataframe(summary_rows, use_container_width=True, hide_index=True)
            if validation_summary:
                st.markdown("**Latest Automation Run**")
                st.json(validation_summary)
        with preview_tabs[1]:
            st.code(markdown_text or "No Markdown artifact yet.", language="markdown")
        with preview_tabs[2]:
            if not chunk_payload:
                st.info("No chunk artifact yet.")
            else:
                rows = []
                for index, chunk in enumerate(chunk_payload, start=1):
                    rows.append(
                        {
                            "chunk_id": chunk.get("chunk_id", "-"),
                            "chunk_display_id": chunk_display_id(document, index),
                            "chunk_index": chunk.get("chunk_index", index),
                            "section": chunk.get("section_path", "Unknown Section"),
                            "page_start": chunk.get("page_start"),
                            "page_end": chunk.get("page_end"),
                            "indexed_at": chunk.get("indexed_at"),
                            "text_preview": str(chunk.get("text_preview") or chunk.get("text", ""))[:220],
                        }
                    )
                st.dataframe(rows, use_container_width=True, hide_index=True)
        with preview_tabs[3]:
            block_payload = json_payload.get("blocks", [])
            if not block_payload:
                st.info("No block data yet.")
            else:
                rows = []
                for index, block in enumerate(block_payload, start=1):
                    rows.append(
                        {
                            "block_display_id": block_display_id(document, index),
                            "block_type": block.get("block_type", "unknown"),
                            "page": block.get("page_number"),
                            "heading_level": block.get("heading_level"),
                            "text_preview": str(block.get("text", ""))[:220],
                        }
                    )
                st.dataframe(rows, use_container_width=True, hide_index=True)
        with preview_tabs[4]:
            st.code(json_text or "No canonical JSON artifact yet.", language="json")


def render_result(index: int, result) -> None:
    with st.container(border=True):
        st.markdown(f"**Result {index}**")
        st.caption(f"{result.client_id} - {result.file_name} - {result.section_path}")
        st.markdown(f"`{result.citation}`")
        st.markdown(result.text)


def render_retrieval_tab() -> None:
    st.subheader("Retrieval Validation")
    selected_dataset = st.selectbox("Dataset", options=list(DATASET_OPTIONS), index=0)
    dataset_config = DATASET_OPTIONS[selected_dataset]
    client_options = dataset_config["clients"]
    selected_client = st.selectbox("Client", options=list(client_options), index=0)
    query = st.text_area("Question", value="When must a refund be escalated?", height=90)

    if st.button("Retrieve", type="primary", use_container_width=False):
        if not query.strip():
            st.warning("Enter a question first.")
            return

        persist_dir = str(DEFAULT_CHROMA_DIR)
        if not Path(persist_dir).exists():
            st.error(f"Chroma path does not exist: {persist_dir}")
            return

        with st.spinner("Retrieving relevant chunks..."):
            try:
                results = search(
                    query=query.strip(),
                    collection_name=str(dataset_config["collection"]),
                    persist_dir=persist_dir,
                    model_name=DEFAULT_MODEL_NAME,
                    top_k=DEFAULT_TOP_K,
                    client_id=client_options[selected_client],
                    document_type=None,
                )
            except Exception as exc:
                st.error(f"Search failed: {exc}")
                return

        if not results:
            st.info("No matching chunks found.")
            return

        for index, result in enumerate(results, start=1):
            render_result(index, result)


def main() -> None:
    setup_local_model_env()
    st.set_page_config(page_title="RAG Workspace", layout="wide")
    inject_styles()

    st.title("Local-First RAG Automation Workspace")
    service = WorkspaceService()
    st.caption(f"{service.workspace.backend_name} control plane: `{service.workspace.location_label}`")

    workspace_tab, retrieval_tab = st.tabs(["Ingestion Automation", "Retrieval Validation"])
    with workspace_tab:
        render_workspace_tab(service)
    with retrieval_tab:
        render_retrieval_tab()


if __name__ == "__main__":
    main()
