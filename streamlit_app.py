from __future__ import annotations

import json
import os
import re
from html import escape
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

from src.indexing.chroma_store import DEFAULT_CHROMA_DIR, DEFAULT_COLLECTION_NAME
from src.indexing.embedder import DEFAULT_MODEL_NAME
from src.retrieval.searcher import search
from src.workspace.service import WorkspaceService


DEFAULT_COLLECTION = DEFAULT_COLLECTION_NAME
STATUS_LABELS = {
    "registered": "Registered",
    "review_ready": "Ready for review",
    "approved": "Approved for indexing",
    "validated": "Approved for indexing",
    "low_confidence": "Needs attention",
    "indexed": "Indexed",
    "failed": "Failed",
}

UPLOAD_VERSION_PATTERN = re.compile(r"^[1-9]\d*(?:\.\d+)?$")


def setup_local_model_env() -> None:
    os.environ.setdefault("HF_HOME", ".cache/huggingface")


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');

        :root {
            --ink: #14213d;
            --blue: #2357d9;
            --blue-soft: #edf3ff;
            --mist: #f4f7fb;
            --line: #dce4ef;
            --muted: #69768c;
            --green: #13795b;
            --amber: #ad6400;
            --red: #c83a3a;
        }

        .stApp { background: var(--mist); color: var(--ink); font-family: 'Manrope', sans-serif; }
        [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer { display: none !important; }
        .block-container { max-width: 1160px; padding: 1.35rem 2rem 3.5rem; }
        h1, h2, h3 { font-family: 'Manrope', sans-serif !important; color: var(--ink); letter-spacing: -0.035em; }
        h1 { font-size: 2.15rem !important; font-weight: 800 !important; margin-bottom: 0.15rem !important; }
        h2 { font-size: 1.35rem !important; font-weight: 750 !important; }
        h3 { font-size: 0.98rem !important; font-weight: 750 !important; }
        code, .mono { font-family: 'DM Mono', monospace; }
        .eyebrow { color: var(--blue); font-size: 0.72rem; font-weight: 800; letter-spacing: 0.11em; text-transform: uppercase; }
        .subtle { color: var(--muted); font-size: 0.92rem; }
        .metric-card { align-items: center; background: #fff; border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 1px 2px rgba(20,33,61,.035); box-sizing: border-box; display: flex; gap: .85rem; min-height: 112px; padding: 1rem; width: 100%; }
        .metric-icon { align-items: center; border-radius: 10px; display: flex; flex: 0 0 48px; height: 48px; justify-content: center; width: 48px; }
        .metric-icon svg { height: 24px; width: 24px; }
        .metric-documents .metric-icon { background:#eef3ff; color:#2c5bd8; }
        .metric-ready .metric-icon { background:#edf8f0; color:#18834f; }
        .metric-indexed .metric-icon { background:#f2efff; color:#7452d6; }
        .metric-attention .metric-icon { background:#fff5e8; color:#c16a00; }
        .metric-content { min-width: 0; }
        .metric-label { color: var(--muted); font-size: 0.68rem; font-weight: 800; letter-spacing: 0.09em; text-transform: uppercase; }
        .metric-value { color: var(--ink); font-size: 1.55rem; font-weight: 800; letter-spacing: -0.05em; line-height: 1.12; margin-top: 0.08rem; }
        .metric-note { color: var(--muted); font-size: 0.73rem; margin-top: 0.18rem; white-space: nowrap; }
        .status { border-radius: 999px; display: inline-block; font-size: 0.7rem; font-weight: 800; padding: 0.27rem 0.58rem; }
        .status-registered { background: #eef2f7; color: #536174; }
        .status-review_ready { background: #eef4ff; color: #2255be; }
        .status-approved { background: #e8f0ff; color: #1748c2; }
        .status-validated { background: #e8f0ff; color: #2255be; }
        .status-low_confidence { background: #fff3db; color: var(--amber); }
        .status-indexed { background: #e5f6ef; color: var(--green); }
        .status-failed { background: #fdebec; color: var(--red); }
        .queue-row { border-bottom: 1px solid var(--line); padding: 0.7rem 0; }
        .queue-row:last-child { border-bottom: 0; padding-bottom: 0; }
        .queue-file { color: var(--ink); font-family: 'DM Mono', monospace; font-size: 0.77rem; font-weight: 500; }
        .queue-meta { color: var(--muted); font-size: 0.74rem; margin-top: 0.18rem; }
        .state-row { align-items: center; border-bottom: 1px solid var(--line); display: flex; font-size: 0.84rem; justify-content: space-between; padding: 0.65rem 0; }
        .state-row:last-child { border-bottom: 0; padding-bottom: 0; }
        .state-count { color: var(--blue); font-family: 'DM Mono', monospace; font-weight: 700; }
        .history-heading { color: var(--muted); font-size: 0.68rem; font-weight: 800; letter-spacing: 0.07em; text-transform: uppercase; }
        .history-value { color: var(--ink); font-size: 0.78rem; padding-top: 0.42rem; }
        .history-file { color: var(--ink); font-family: 'DM Mono', monospace; font-size: 0.78rem; font-weight: 500; }
        .history-meta { color: var(--muted); font-size: 0.72rem; margin-top: 0.16rem; }
        .history-row { min-height: 64px; padding: 0.4rem 0; }
        .history-row-rule { background: var(--line); height: 1px; margin: 0; }
        .st-key-document-history-list { border-top: 1px solid var(--line); margin-top: 0.65rem; padding-top: 0.7rem; }
        .history-empty-inline { align-items: center; border-top: 1px solid var(--line); color: var(--muted); display: flex; font-size: 0.9rem; gap: 0.45rem; min-height: 54px; padding: 0.9rem 0; }
        .history-empty-inline strong { color: var(--ink); font-weight: 750; }
        .duplicate-notice { border-left: 3px solid var(--blue); color: var(--muted); font-size: 0.82rem; line-height: 1.5; margin: 0.1rem 0 1rem; padding: 0.55rem 0 0.55rem 0.8rem; }
        .duplicate-notice strong { color: var(--ink); font-weight: 800; }
        .empty-state { background:#f8faff; border:1px dashed #c9d6e9; border-radius:10px; color:var(--muted); padding:1rem 1.1rem; }
        .empty-state-title { color:var(--ink); font-size:.9rem; font-weight:800; }
        .empty-state-copy { font-size:.8rem; line-height:1.5; margin-top:.22rem; }
        .review-empty { border-top: 1px solid var(--line); padding: 1.15rem 0 0.35rem; }
        .review-empty-title { color: var(--ink); font-size: 0.95rem; font-weight: 750; }
        .review-empty-copy { color: var(--muted); font-size: 0.84rem; margin-top: 0.28rem; }
        .st-key-result-review-shell { background: rgba(255, 255, 255, 0.76); border: 1px solid #d7e0ec; border-radius: 12px; box-shadow: 0 1px 2px rgba(20, 33, 61, 0.035); padding: 1.45rem 1.55rem 1.2rem; }
        .st-key-result-review-shell > [data-testid="stVerticalBlockBorderWrapper"] { background: transparent !important; border: 0 !important; box-shadow: none !important; padding: 0 !important; }
        .artifact-value { color: var(--blue); font-size: 1.3rem; font-weight: 800; }
        .artifact-label { color: var(--muted); font-size: 0.73rem; margin-top: 0.12rem; }
        .artifact-meta { color: var(--muted); font-size: 0.8rem; margin: 0.9rem 0 0.7rem; }
        .artifact-meta strong { color: var(--blue); font-weight: 800; }
        .artifact-meta-value { color: #35506f; font-family: 'DM Mono', monospace; font-size: 0.82rem; font-weight: 650; }
        .artifact-location-list { border-top: 1px solid var(--line); margin-top: 0.8rem; padding-top: 0.75rem; }
        .artifact-location-row { display: grid; gap: 0.2rem; margin-top: 0.55rem; }
        .artifact-location-label { color: var(--muted); font-size: 0.7rem; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; }
        .artifact-location-value { color: #35506f; font-family: 'DM Mono', monospace; font-size: 0.76rem; overflow-wrap: anywhere; }
        .document-meta { color: var(--muted); font-size: 0.78rem; margin-top: 0.38rem; }
        .document-status { display: flex; justify-content: flex-end; padding-top: 0.35rem; }
        .validation-panel { border-left: 3px solid var(--line); margin-bottom: 0.85rem; padding: 0.65rem 0.8rem; }
        .validation-panel.passed { background: #f7fbf8; border-color: #5c9a73; }
        .validation-panel.attention { background: #fffaf0; border-color: #c78a2b; }
        .validation-panel.failed { background: #fff7f7; border-color: #c75a61; }
        .validation-panel-title { color: var(--ink); font-size: 0.88rem; font-weight: 800; }
        .validation-panel-copy { color: var(--muted); font-size: 0.76rem; margin-top: 0.16rem; }
        .validation-key { color: var(--muted); font-size: 0.71rem; font-weight: 750; letter-spacing: 0.04em; text-transform: uppercase; }
        .validation-value { color: var(--ink); font-size: 0.82rem; margin-top: 0.18rem; }
        .validation-summary-line { align-items: baseline; display: flex; flex-wrap: wrap; gap: 0.32rem 1rem; padding: 0.05rem 0 0.7rem; }
        .validation-summary-item { color: var(--muted); font-size: 0.77rem; }
        .validation-summary-item strong { color: var(--ink); font-weight: 750; }
        .validation-grid-label { color: var(--ink); font-size: 0.77rem; font-weight: 800; }
        .validation-grid-value { color: var(--muted); font-size: 0.76rem; margin-top: 0.14rem; }
        .validation-grid-rule { background: var(--line); height: 1px; margin: 0.7rem 0; }
        .chunk-summary { background: var(--blue-soft); border: 1px solid #d8e4fb; border-radius: 999px; color: #48617f; display: inline-flex; font-size: 0.78rem; font-weight: 650; margin-bottom: 0.8rem; padding: 0.38rem 0.68rem; }
        .chunk-evidence { border-bottom: 1px solid var(--line); padding: 0.8rem 0; }
        .chunk-evidence:last-child { border-bottom: 0; }
        .chunk-section { color: var(--ink); font-size: 0.86rem; font-weight: 750; }
        .chunk-id { color: var(--muted); font-family: 'DM Mono', monospace; font-size: 0.68rem; margin-top: 0.14rem; }
        .chunk-meta { color: var(--muted); font-size: 0.73rem; margin-top: 0.24rem; }
        .chunk-preview { color: var(--ink); font-size: 0.79rem; line-height: 1.55; margin-top: 0.46rem; }
        .chunk-full-text { background: #f3f6fb; border: 1px solid #d5dfed; border-radius: 8px; color: var(--ink); font-family: 'DM Mono', monospace; font-size: 0.75rem; line-height: 1.6; margin-top: 0.35rem; max-height: 340px; overflow: auto; padding: 0.8rem 0.9rem; white-space: pre-wrap; }
        .chunk-full-text a, .retrieval-text a { color:var(--blue); text-decoration:underline; text-underline-offset:2px; }
        [class*="st-key-chunk-results-"] { background: #fff; border: 1px solid #d5dfed; border-radius: 12px; box-shadow: 0 1px 2px rgba(20,33,61,.035); padding: 0.7rem 0.8rem; }
        [class*="st-key-chunk-results-"]::-webkit-scrollbar, .chunk-full-text::-webkit-scrollbar { width: 9px; }
        [class*="st-key-chunk-results-"]::-webkit-scrollbar-thumb, .chunk-full-text::-webkit-scrollbar-thumb { background: #bdcadc; border: 2px solid #f7f9fc; border-radius: 999px; }
        [class*="st-key-chunk-results-"]::-webkit-scrollbar-track, .chunk-full-text::-webkit-scrollbar-track { background: #f7f9fc; }
        [class*="st-key-chunk-evidence-"] { background: #fff; border-color: #d8e1ed !important; border-radius: 10px !important; box-shadow: 0 1px 2px rgba(20,33,61,.025); margin-bottom: 0.65rem; }
        [class*="st-key-chunk-evidence-"] [data-testid="stExpander"] details { background:#f5f8fd; border:1px solid #ccd8ea; border-radius:8px; overflow:hidden; }
        [class*="st-key-chunk-evidence-"] [data-testid="stExpander"] summary { color:var(--ink); font-size:.79rem; font-weight:750; padding:.68rem .82rem; }
        [class*="st-key-chunk-evidence-"] [data-testid="stExpander"] summary:hover { background:#edf3fb; }
        [class*="st-key-chunk-evidence-"] [data-testid="stExpander"] details[open] summary { background:#edf3fb; border-bottom:1px solid #d8e2f0; }
        .chunk-row-gap { height: 0.85rem; }
        .overview-action-row { align-items: center; display: flex; min-height: 64px; padding: 0.45rem 0; }
        .overview-file { color: var(--ink); font-family: 'DM Mono', monospace; font-size: 0.79rem; font-weight: 500; }
        .overview-meta { color: var(--muted); font-size: 0.73rem; margin-top: 0.2rem; }
        .overview-column-heading { color: var(--muted); font-size: 0.66rem; font-weight: 800; letter-spacing: 0.07em; text-transform: uppercase; }
        .overview-column-value { color: var(--ink); font-size: 0.77rem; }
        .overview-row-rule { background: var(--line); height: 1px; margin: 0; }
        .st-key-overview-recent-list { background: #fff; border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 1px 2px rgba(20,33,61,.035); margin-left:-1.25rem; margin-right:-1.25rem; padding: 0.2rem 1rem 0.6rem; width:calc(100% + 2.5rem); }
        .overview-list-header { align-items:center; display:flex; justify-content:space-between; padding:.85rem 0 .55rem; }
        .overview-list-title { color:var(--ink); font-size:1rem; font-weight:800; }
        .st-key-overview-recent-list > [data-testid="stVerticalBlockBorderWrapper"] { background: transparent !important; border: 0 !important; box-shadow: none !important; padding: 0 !important; }
        .stButton > button { background: #fff; border: 1px solid #cfd9e8; border-radius: 8px; color: var(--ink); font-family: 'Manrope', sans-serif; font-weight: 750; }
        .stButton > button:hover { background: #f4f7fb; border-color: #aebfda; color: var(--ink); }
        .stButton > button:focus { border-color: #7f9ad0; box-shadow: 0 0 0 0.15rem rgba(35, 87, 217, 0.15); color: var(--ink); }
        .stButton > button:disabled { background: #eef2f7 !important; border-color: #dce4ef !important; color: #7f8ca1 !important; cursor: not-allowed !important; opacity: 1 !important; }
        [data-testid="stDownloadButton"] button { background: #fff !important; border: 1px solid #cfd9e8 !important; border-radius: 8px !important; color: var(--ink) !important; font-family: 'Manrope', sans-serif !important; font-weight: 750 !important; }
        [data-testid="stDownloadButton"] button:hover { background: #f4f7fb !important; border-color: #aebfda !important; color: var(--ink) !important; }
        .st-key-overview-history button, .st-key-overview-upload-source button { background: transparent !important; border-color: transparent !important; color: var(--blue) !important; font-size: 0.78rem !important; min-height: auto !important; padding: 0.35rem 0 !important; }
        .st-key-overview-history button:hover, .st-key-overview-upload-source button:hover { background: transparent !important; border-color: transparent !important; color: #1748c2 !important; text-decoration: underline; }
        .st-key-clear-history-filters button { background: transparent !important; border-color: transparent !important; color: var(--blue) !important; font-size: 0.78rem !important; min-height: auto !important; padding: 0 !important; }
        .st-key-clear-history-filters button:hover { background: transparent !important; border-color: transparent !important; color: #1748c2 !important; text-decoration: underline; }
        .st-key-open-history-from-review button { background: transparent !important; border-color: transparent !important; color: var(--blue) !important; font-size: 0.8rem !important; min-height: auto !important; padding: 0.35rem 0 !important; }
        .st-key-open-history-from-review button:hover { background: transparent !important; border-color: transparent !important; color: #1748c2 !important; text-decoration: underline; }
        [data-testid="stBaseButton-primary"] { background: var(--blue) !important; border-color: var(--blue) !important; color: #fff !important; }
        [data-testid="stBaseButton-primary"]:hover { background: #1748c2 !important; border-color: #1748c2 !important; color: #fff !important; }
        .st-key-nav-overview button, .st-key-nav-upload-history button, .st-key-nav-result-review button, .st-key-nav-retrieval-validation button { background: transparent !important; border: 0 !important; border-bottom: 3px solid transparent !important; border-radius: 0 !important; color: var(--muted) !important; font-size: 0.84rem !important; font-weight: 700 !important; min-height: 2.7rem !important; padding: 0.35rem 0 !important; }
        .st-key-nav-overview button:hover, .st-key-nav-upload-history button:hover, .st-key-nav-result-review button:hover, .st-key-nav-retrieval-validation button:hover { background: transparent !important; color: var(--ink) !important; }
        .st-key-nav-overview [data-testid="stBaseButton-primary"], .st-key-nav-upload-history [data-testid="stBaseButton-primary"], .st-key-nav-result-review [data-testid="stBaseButton-primary"], .st-key-nav-retrieval-validation [data-testid="stBaseButton-primary"] { background: transparent !important; border-bottom-color: #ef5b5b !important; color: var(--blue) !important; }
        .top-navigation { border-bottom: 1px solid var(--line); margin-bottom: 0.65rem; }
        [data-testid="stPopover"] > button, [data-testid="stPopover"] button { background: #fff !important; border: 1px solid #cfd9e8 !important; color: var(--ink) !important; }
        [data-testid="stPopoverBody"], [data-baseweb="popover"] { background: #fff !important; border: 1px solid #d5dfed !important; border-radius: 10px !important; box-shadow: 0 10px 28px rgba(20,33,61,.14) !important; color: var(--ink) !important; }
        [data-baseweb="popover"] > div, [data-baseweb="popover"] ul, [data-baseweb="popover"] li, [data-baseweb="popover"] [role="option"] { background: #fff !important; color: var(--ink) !important; }
        [data-testid="stPopoverBody"] *, [data-baseweb="popover"] * { color: var(--ink) !important; }
        [data-testid="stPopoverBody"] code, [data-baseweb="popover"] code { background: #f3f6fb !important; color: #35506f !important; }
        [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea, [data-baseweb="select"] > div { background: #fff !important; color: var(--ink) !important; border-color: #cfd9e8 !important; }
        [data-testid="stTextInput"] input::placeholder, [data-testid="stTextArea"] textarea::placeholder { color: #8591a5 !important; }
        [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea { caret-color: var(--ink) !important; }
        [data-testid="stTextInput"] [data-baseweb="input"] { border-color: #cfd9e8 !important; }
        [data-testid="stTextInput"] [data-baseweb="input"]:focus-within { border-color: #7f9ad0 !important; box-shadow: 0 0 0 0.15rem rgba(35, 87, 217, 0.12) !important; }
        [data-testid="stTextInput"] label p, [data-testid="stTextArea"] label p, [data-testid="stSelectbox"] label p { color: var(--muted) !important; font-weight: 700 !important; }
        [data-testid="stSelectbox"] [data-baseweb="select"] > div { cursor: pointer; transition: background 160ms ease, border-color 160ms ease, box-shadow 160ms ease; }
        [data-testid="stSelectbox"] [data-baseweb="select"] > div:hover { background: #f8faff !important; border-color: #aebfda !important; }
        [data-baseweb="menu"], [role="listbox"] { background: #fff !important; border: 1px solid #d5dfed !important; box-shadow: 0 10px 28px rgba(20,33,61,.14) !important; }
        [data-baseweb="menu"] [role="option"], [role="listbox"] [role="option"] { background: #fff !important; color: var(--ink) !important; }
        [data-baseweb="menu"] [role="option"] *, [role="listbox"] [role="option"] * { color: var(--ink) !important; }
        [data-baseweb="menu"] [role="option"]:hover, [data-baseweb="menu"] [aria-selected="true"], [role="listbox"] [role="option"]:hover, [role="listbox"] [aria-selected="true"] { background: #edf3ff !important; }
        [data-baseweb="popover"] li:hover, [data-baseweb="popover"] [aria-selected="true"] { background: #edf3ff !important; }
        [data-testid="stSelectbox"] svg { color: #7385a2 !important; fill: #7385a2 !important; transition: transform 160ms ease, color 160ms ease; }
        [data-testid="stSelectbox"] [aria-expanded="true"] svg { color: var(--blue) !important; fill: var(--blue) !important; transform: rotate(180deg); }
        [data-testid="stFileUploader"] { background: transparent; border: 0; padding: 0; }
        [data-testid="stFileUploaderDropzone"] { background: #fff !important; border: 1px dashed #b9c9e5 !important; border-radius: 10px !important; padding: 0.85rem 1.1rem !important; }
        [data-testid="stFileUploaderDropzone"] * { color: var(--ink) !important; }
        [data-testid="stFileUploaderDropzone"] button { background: #f4f7fb !important; border: 1px solid #cfd9e8 !important; color: var(--ink) !important; }
        [data-testid="stFileUploader"]:has([data-testid="stFileUploaderFile"]) [data-testid="stFileUploaderDropzone"] { background: #f5f7fa !important; border-color: #d8e0ec !important; opacity: 0.55; pointer-events: none; }
        [data-testid="stFileUploaderFileName"] { color: var(--ink) !important; }
        [data-testid="stFileUploaderFileErrorMessage"] { color: #bf3e45 !important; font-size: 0.78rem !important; font-weight: 650 !important; opacity: 1 !important; }
        [data-testid="stFileUploaderDeleteBtn"] { color: var(--ink) !important; }
        [data-testid="stFileUploaderDeleteBtn"]:hover { color: #bf3e45 !important; }
        .upload-version-label { color: var(--ink); font-size: 0.78rem; font-weight: 750; }
        .upload-version-helper { color: var(--muted); font-size: 0.72rem; line-height: 1.45; margin-top: 0.18rem; }
        .upload-version-error { color: var(--red); font-size: 0.86rem; font-weight: 750; line-height: 1.45; margin-top: 0.45rem; }
        .st-key-markdown-preview-content { background: #fff; border: 1px solid #d5dfed; border-radius: 12px; box-shadow: 0 1px 2px rgba(20,33,61,.035); margin: 0 0.75rem; padding: 0.7rem 0.85rem; }
        .st-key-markdown-preview-content h1 { font-size: 1.55rem !important; margin-bottom: 0.8rem !important; overflow-wrap: anywhere; }
        .st-key-markdown-preview-content li strong { color: var(--blue); font-weight: 800; }
        .st-key-markdown-preview-content li code { background: transparent !important; border: 0 !important; color: var(--ink) !important; font-family: inherit !important; font-size: inherit !important; padding: 0 !important; }
        [class*="st-key-chunk-results-"], [class*="st-key-chunk-results-"] [data-testid="stVerticalBlockBorderWrapper"], .st-key-markdown-preview-content [data-testid="stVerticalBlockBorderWrapper"] { overflow-y: scroll !important; scrollbar-gutter: stable; }
        [class*="st-key-chunk-results-"]::-webkit-scrollbar, .st-key-markdown-preview-content::-webkit-scrollbar { display: block; width: 11px; }
        [class*="st-key-chunk-results-"]::-webkit-scrollbar-thumb, .st-key-markdown-preview-content::-webkit-scrollbar-thumb { background: #aebfd5; border: 2px solid #f7f9fc; border-radius: 999px; }
        .st-key-upload-intake-card [data-testid="stTextInput"] { margin-top: 0 !important; }
        [class*="st-key-clear-chunk-search-"] button { background: transparent !important; border-color: transparent !important; color: var(--blue) !important; font-size: 0.78rem !important; min-height: auto !important; padding: 0.35rem 0 !important; }
        [class*="st-key-clear-chunk-search-"] button:hover { background: transparent !important; border-color: transparent !important; color: #1748c2 !important; text-decoration: underline; }
        .upload-submit-gap { height: 0.2rem; }
        .upload-history-gap { height: 2.65rem; }
        .st-key-upload-submit button:disabled { background: #eef2f7 !important; border-color: #dce4ef !important; color: #9aa7ba !important; cursor: not-allowed !important; opacity: 1 !important; }
        [data-testid="stCheckbox"] label, [data-testid="stCheckbox"] label p { color: var(--ink) !important; font-weight: 650 !important; }
        [data-testid="stCheckbox"] input:disabled + div, [data-testid="stCheckbox"] input:disabled + div + div, [data-testid="stCheckbox"] input:disabled ~ div, [data-testid="stCheckbox"] input:disabled ~ label { color: #7f8ca1 !important; opacity: 1 !important; }
        .st-key-history-delete-selected button:disabled { background: #eef2f7 !important; border-color: #dce4ef !important; color: #7f8ca1 !important; }
        .st-key-history-delete-confirm [data-testid="stCheckbox"] label, .st-key-history-delete-confirm [data-testid="stCheckbox"] label p { color: var(--ink) !important; }
        [data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
        .stTextInput input, .stTextArea textarea { border-radius: 8px; border-color: #cad5e5; }
        .stTabs [data-baseweb="tab-list"] { border-bottom: 1px solid var(--line); gap: 1.7rem; padding: 0.25rem 0 0.6rem; }
        .stTabs [data-baseweb="tab"] { color: var(--muted) !important; font-size: 0.84rem; font-weight: 700; padding: 0.35rem 0; }
        .stTabs [data-baseweb="tab"] * { color: inherit !important; }
        .stTabs [data-baseweb="tab"]:hover { color: var(--ink) !important; }
        .stTabs [aria-selected="true"] { color: var(--blue) !important; }
        .topbar { align-items: center; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; margin-bottom: 0.25rem; padding: 0.15rem 0 0.95rem; }
        .topbar-title { color: var(--ink); font-size: 1rem; font-weight: 800; letter-spacing: -0.02em; }
        .topbar-subtitle { color: var(--muted); font-size: 0.76rem; font-weight: 500; margin-left: 0.6rem; }
        .topbar-meta { color: var(--muted); font-size: 0.75rem; }
        .topbar-dot { color: var(--green); margin-right: 0.35rem; }
        .topbar-subtitle { display: none; }
        .topbar-meta { font-size: 0; }
        .topbar-meta::after { color: var(--muted); content: 'Local workspace'; font-size: 0.75rem; }
        .section-card { background: #fff; border: 1px solid var(--line); border-radius: 10px; padding: 1.1rem 1.2rem; }
        [data-testid="stException"] { background: #fff3f3 !important; border: 1px solid #efc7ca !important; color: #7f1d24 !important; }
        [data-testid="stException"] * { color: #7f1d24 !important; }
        .st-key-upload-intake-card, .st-key-document-history-card { background: rgba(255,255,255,0.86); border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 1px 2px rgba(20,33,61,0.03); padding: 1.25rem 1.35rem 1.15rem; }
        .st-key-upload-intake-card > [data-testid="stVerticalBlockBorderWrapper"], .st-key-document-history-card > [data-testid="stVerticalBlockBorderWrapper"] { background: transparent !important; border: 0 !important; box-shadow: none !important; padding: 0 !important; }
        .card-title { color: var(--ink); font-size: 1.15rem; font-weight: 800; letter-spacing: -0.025em; margin-top: 0.22rem; }
        .card-copy { color: var(--muted); font-size: 0.82rem; margin-top: 0.25rem; margin-bottom: 0.85rem; }
        .upload-info-strip { align-items: center; background: #f8faff; border: 1px solid var(--line); border-radius: 8px; color: var(--muted); display: flex; flex-wrap: wrap; font-size: 0.72rem; gap: 0.35rem 0.7rem; justify-content: flex-end; min-height: 38px; padding: 0.55rem 0.72rem; }
        .upload-info-strip strong { color: var(--ink); font-weight: 750; }
        .history-toolbar-gap { height: 0.15rem; }
        .history-card-footer { border-top: 1px solid var(--line); margin-top: 0.2rem; padding-top: 0.45rem; }
        .st-key-history-footer-link button { background: transparent !important; border: 0 !important; color: var(--blue) !important; font-size: 0.78rem !important; min-height: auto !important; padding: 0.25rem 0 !important; }
        .st-key-history-footer-link button:hover { background: transparent !important; color: #1748c2 !important; text-decoration: underline; }
        @media (max-width: 800px) { .block-container { padding: 1rem 1rem 2rem; } .st-key-overview-recent-list { margin-left:0; margin-right:0; width:100%; } }

        /* Commercial layout additions */
        .page-header { margin-bottom: 1.45rem; }
        .page-header .subtle { margin-top: .45rem; }
        .surface-card { background:#fff; border:1px solid var(--line); border-radius:14px; box-shadow:0 1px 2px rgba(20,33,61,.04); padding:1.25rem 1.35rem; }
        .surface-card + .surface-card { margin-top:1rem; }
        .section-title { color:var(--ink); font-size:1.04rem; font-weight:800; letter-spacing:-.02em; }
        .section-copy { color:var(--muted); font-size:.82rem; margin-top:.25rem; }
        .st-key-upload-intake-card, .st-key-document-history-card, .st-key-document-inspector-card, .st-key-retrieval-query-card { background:#fff; border:1px solid var(--line); border-radius:14px; box-shadow:0 1px 2px rgba(20,33,61,.04); padding:1.25rem 1.35rem; }
        .st-key-upload-intake-card, .st-key-document-history-card, .st-key-document-inspector-card { margin-left:-1.25rem; margin-right:-1.25rem; width:calc(100% + 2.5rem); }
        .st-key-retrieval-query-card [data-testid="stTextArea"] textarea { height:76px !important; min-height:76px !important; }
        .retrieval-field-label { color:var(--muted); font-size:.78rem; font-weight:750; margin-bottom:.35rem; }
        .retrieval-query-error { background: #fff4e5; border: 1px solid #f0c98b; border-left: 4px solid #d98219; border-radius: 9px; color: #7a4909; font-size: 0.86rem; font-weight: 700; margin-top: 1rem; padding: 0.78rem 0.9rem; }
        .action-success-notice { background: #e2f6e9; border: 1px solid #9fd6b3; border-left: 4px solid #218657; border-radius: 9px; color: #0c5c36; font-size: 0.9rem; font-weight: 800; line-height: 1.5; margin: 0.8rem 0 1rem; padding: 0.78rem 0.9rem; }
        .st-key-markdown-preview-content pre { background:#f8faff !important; border:1px solid var(--line) !important; border-radius:8px !important; color:var(--ink) !important; max-height:380px; overflow:auto !important; white-space:pre-wrap !important; }
        .st-key-markdown-preview-content pre code { color:var(--ink) !important; overflow-wrap:anywhere !important; white-space:pre-wrap !important; word-break:break-word !important; }
        .st-key-upload-intake-card [data-testid='stFileUploader'] { box-sizing:border-box !important; margin:0 !important; max-width:900px !important; min-width:0 !important; width:100% !important; }
        .st-key-upload-intake-card [data-testid='stFileUploaderDropzone'] { box-sizing:border-box !important; margin:0 !important; max-width:100% !important; min-width:0 !important; width:auto !important; }
        .st-key-upload-intake-card [data-testid='stFileUploaderDropzone'] > * { min-width:0 !important; }
        .upload-form-row { align-items:end; display:grid; grid-template-columns:minmax(220px, 360px) auto; gap:1rem; margin-top:.85rem; }
        .upload-constraints { color:var(--muted); font-size:.72rem; margin-top:.55rem; }
        .st-key-upload-intake-card > [data-testid="stVerticalBlockBorderWrapper"], .st-key-document-history-card > [data-testid="stVerticalBlockBorderWrapper"], .st-key-document-inspector-card > [data-testid="stVerticalBlockBorderWrapper"], .st-key-retrieval-query-card > [data-testid="stVerticalBlockBorderWrapper"] { background:transparent !important; border:0 !important; box-shadow:none !important; padding:0 !important; }
        .upload-info-strip { background:#f8faff; border:1px solid var(--line); border-radius:9px; color:var(--muted); font-size:.73rem; line-height:1.5; padding:.72rem .85rem; }
        .upload-info-strip strong { color:var(--ink); font-weight:750; }
        .document-title-row { align-items:center; display:flex; gap:.65rem; justify-content:space-between; }
        .document-title-row h2 { margin:0 !important; }
        .document-toolbar { border-top:1px solid var(--line); margin-top:1rem; padding-top:1rem; }
        .inspector-kicker { color:var(--blue); font-size:.68rem; font-weight:800; letter-spacing:.1em; text-transform:uppercase; }
        .result-tabs-spacer { height:.35rem; }
        .validation-audit { background:#fff; border:1px solid var(--line); border-radius:10px; overflow:hidden; }
        .validation-audit-row { display:grid; grid-template-columns: 180px 1fr; min-height:42px; border-bottom:1px solid var(--line); }
        .validation-audit-row:last-child { border-bottom:0; }
        .validation-audit-label { background:#f8faff; color:var(--muted); font-size:.69rem; font-weight:800; letter-spacing:.05em; padding:.72rem .85rem; text-transform:uppercase; }
        .validation-audit-value { color:var(--ink); font-size:.8rem; font-weight:650; overflow-wrap:anywhere; padding:.72rem .9rem; }
        @media (max-width:800px){ .validation-audit-row{grid-template-columns:1fr;} .validation-audit-label{padding-bottom:.25rem;} .validation-audit-value{padding-top:.25rem;} }
        .evidence-card { background:#fff; border:1px solid var(--line); border-radius:12px; padding:1rem 1.05rem; }
        .evidence-card + .evidence-card { margin-top:.8rem; }
        .evidence-title { color:var(--ink); font-size:.88rem; font-weight:800; }
        .evidence-meta { color:var(--muted); font-size:.7rem; margin-top:.18rem; }
        .evidence-preview { color:var(--ink); font-size:.79rem; line-height:1.6; margin-top:.6rem; }
        .artifact-panel { background:#fff; border:1px solid var(--line); border-radius:12px; padding:1rem 1.05rem; }
        .retrieval-scope { color:var(--muted); font-size:.72rem; }
        .retrieval-scope strong { color:var(--ink); }
        .retrieval-empty { background:#f8faff; border:1px dashed #c9d6e9; border-radius:12px; color:var(--muted); padding:1rem 1.1rem; }
        .retrieval-result { background:#fff; border:1px solid var(--line); border-radius:12px; box-shadow:0 1px 2px rgba(20,33,61,.03); padding:1rem 1.05rem; }
        .retrieval-result + .retrieval-result { margin-top:.85rem; }
        .retrieval-rank { color:var(--blue); font-size:.68rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
        .retrieval-file { color:var(--ink); font-size:.92rem; font-weight:800; margin-top:.16rem; }
        .retrieval-citation { color:var(--muted); font-size:.72rem; margin-top:.24rem; }
        [class*="st-key-download-source-retrieval-"] { margin-top:.08rem; }
        [class*="st-key-download-source-retrieval-"] [data-testid="stDownloadButton"] button { background:transparent !important; border:0 !important; border-radius:0 !important; color:var(--blue) !important; font-size:.92rem !important; font-weight:800 !important; justify-content:flex-start !important; min-height:auto !important; padding:.05rem 0 !important; text-decoration:underline !important; text-underline-offset:2px; }
        [class*="st-key-download-source-retrieval-"] [data-testid="stDownloadButton"] button:hover { background:transparent !important; color:#1748c2 !important; text-decoration-thickness:2px !important; }
        .score-pill { background:var(--blue-soft); border-radius:999px; color:var(--blue); display:inline-block; font-size:.72rem; font-weight:800; padding:.3rem .58rem; }
        .retrieval-text { color:var(--ink); font-size:.8rem; line-height:1.65; margin-top:.75rem; white-space:pre-wrap; }
        .st-key-markdown-source-code code { max-height:650px; overflow:auto; }
        @media (max-width: 800px) {
            .surface-card, .st-key-upload-intake-card, .st-key-document-history-card, .st-key-document-inspector-card, .st-key-retrieval-query-card { padding:1rem; }
            .st-key-upload-intake-card, .st-key-document-history-card, .st-key-document-inspector-card { margin-left:0; margin-right:0; width:100%; }
            .st-key-markdown-preview-content { margin-left:0; margin-right:0; }
            .document-title-row { align-items:flex-start; flex-direction:column; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def infer_document_type(file_name: str) -> str:
    return "document" if Path(file_name).suffix.lower() in {".pdf", ".docx"} else "unknown"


def read_text(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else None


def read_json(path_value: str | None):
    content = read_text(path_value)
    return json.loads(content) if content else None


def status_badge(status: str) -> str:
    label = STATUS_LABELS.get(status, status.replace("_", " ").title())
    return f'<span class="status status-{status}">{label}</span>'


def render_success_notice(message: str) -> None:
    st.markdown(f"<div class='action-success-notice'>{escape(message)}</div>", unsafe_allow_html=True)


def parser_display_name(parser_name: str | None) -> str:
    """Render parser identity without the stored implementation version."""

    name = (parser_name or "").strip()
    return re.sub(r"\s+v?\d+(?:\.\d+)*(?:[-+][\w.-]+)?$", "", name, flags=re.IGNORECASE) or "Unavailable"


def document_label(document) -> str:
    return f"{document.file_name} | {STATUS_LABELS.get(document.status, document.status)}"


def metric_card(label: str, value: str | int, note: str) -> None:
    tone = {
        "Documents": "documents",
        "Ready for review": "ready",
        "Indexed": "indexed",
        "Issues": "attention",
    }.get(label, "documents")
    icons = {
        "Documents": "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8'><path d='M6 3h9l3 3v15H6z'/><path d='M15 3v4h4M9 11h6M9 15h6'/></svg>",
        "Ready for review": "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8'><circle cx='12' cy='12' r='9'/><path d='m8.5 12 2.2 2.2 4.8-5'/></svg>",
        "Indexed": "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8'><ellipse cx='12' cy='5' rx='7' ry='3'/><path d='M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6'/></svg>",
        "Issues": "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8'><path d='M12 3 2.8 19h18.4z'/><path d='M12 9v4M12 16.5h.01'/></svg>",
    }
    st.markdown(
        f"<div class='metric-card metric-{tone}'><div class='metric-icon'>{icons[label]}</div>"
        f"<div class='metric-content'><div class='metric-label'>{label}</div><div class='metric-value'>{value}</div>"
        f"<div class='metric-note'>{note}</div></div></div>",
        unsafe_allow_html=True,
    )


def document_chunk_count(service: WorkspaceService, document_id: str) -> int:
    return len(service.workspace.list_chunks(document_id))


def format_updated(timestamp) -> str:
    return timestamp.strftime("%d %b %Y, %H:%M")


def overview_action_label(status: str) -> str:
    if status == "indexed":
        return "Open"
    if status == "registered":
        return "View"
    return "Review"


def overview_chunk_label(status: str, count: int) -> str:
    if status in {"review_ready", "approved", "validated", "indexed"}:
        return f"{count} validated chunks"
    return f"{count} chunks"


def normalize_search_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def validate_retrieval_query(query: str) -> str | None:
    cleaned = query.strip()
    if not cleaned:
        return "Enter a retrieval question before searching."
    if len(cleaned) < 5:
        return "Use a more specific question (at least 5 characters)."
    if len(cleaned) > 1_000:
        return "Keep the retrieval question under 1,000 characters."
    if not re.fullmatch(r"[\w\s.,;:!?()'\"/&%+\-–—，。！？、（）【】「」]+", cleaned):
        return "Use letters, numbers, spaces, and common punctuation only."
    contains_cjk = bool(re.search(r"[\u3400-\u9fff]", cleaned))
    english_terms = re.findall(r"[A-Za-z]{2,}", cleaned)
    if not contains_cjk and len(english_terms) < 2:
        return "Use a specific question with at least two words, for example: 'What is the refund policy?'"
    return None


URL_PATTERN = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
URL_TRAILING_PUNCTUATION = ".,;:!?)]}\"'"


def evidence_html(text: str) -> str:
    """Escape evidence text while rendering only verified HTTP(S) URLs as links."""

    rendered: list[str] = []
    cursor = 0
    for match in URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(URL_TRAILING_PUNCTUATION)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        start, end = match.span()
        rendered.append(escape(text[cursor:start]))
        rendered.append(
            f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(url)}</a>'
        )
        cursor = start + len(url)
    rendered.append(escape(text[cursor:]))
    return "".join(rendered)


def clear_chunk_search(search_key: str) -> None:
    st.session_state[search_key] = ""


def navigate_to(page: str) -> None:
    st.session_state["active_page"] = page


def open_document_history() -> None:
    navigate_to("Upload & history")


def duplicate_upload_notice(file_name: str) -> str:
    return (
        "This file has already been processed. "
        f"{file_name} matches an existing checksum. "
        "Open the existing result to review it, or use Re-process there only if you want a new processing run."
    )


def open_existing_result(document_id: str, notice: str) -> None:
    st.session_state["selected_document_id"] = document_id
    st.session_state["review_notice"] = notice
    st.session_state.pop("duplicate_document_id", None)
    st.session_state.pop("duplicate_notice", None)
    st.session_state["active_page"] = "Result review"


def render_source_download_button(service: WorkspaceService, document_id: str, key: str, label: str = "Download source") -> None:
    try:
        file_name, file_bytes, mime = service.source_download(document_id)
    except Exception as exc:
        st.caption(f"Source unavailable: {exc}")
        return
    st.download_button(label, data=file_bytes, file_name=file_name, mime=mime, key=key)


def render_navigation() -> str:
    pages = [
        ("Overview", "nav-overview"),
        ("Upload & history", "nav-upload-history"),
        ("Result review", "nav-result-review"),
        ("Retrieval validation", "nav-retrieval-validation"),
    ]
    page_names = [page for page, _ in pages]
    active_page = st.session_state.get("active_page", "Overview")
    if active_page not in page_names:
        active_page = "Overview"
        st.session_state["active_page"] = active_page
    columns = st.columns([0.9, 1.35, 1.2, 1.55], gap="small")
    for column, (page, key) in zip(columns, pages):
        column.button(
            page,
            key=key,
            type="primary" if page == active_page else "secondary",
            on_click=navigate_to,
            args=(page,),
        )
    st.markdown("<div class='top-navigation'></div>", unsafe_allow_html=True)
    return active_page


def render_topbar() -> None:
    st.markdown(
        "<div class='topbar'><span class='topbar-title'>RAG Ingestion</span>"
        "<span class='topbar-subtitle'>Local document pipeline</span>"
        "<span class='topbar-meta'><span class='topbar-dot'>●</span>Local PostgreSQL workspace</span></div>",
        unsafe_allow_html=True,
    )


def render_overview(service: WorkspaceService) -> None:
    stats = service.workspace.stats()
    documents = service.workspace.list_documents()
    ready = stats.get("review_ready", 0) + stats.get("approved", 0) + stats.get("validated", 0)
    attention = stats.get("low_confidence", 0) + stats.get("failed", 0)

    st.markdown("<div class='eyebrow'>Ingestion workspace</div>", unsafe_allow_html=True)
    st.title("Pipeline overview")
    st.markdown(
        "<p class='subtle'>A clear view of document intake, validation, indexing, and retrieval readiness.</p>",
        unsafe_allow_html=True,
    )

    columns = st.columns(4, gap="medium")
    with columns[0]:
        metric_card("Documents", stats.get("total", 0), "Total tracked documents")
    with columns[1]:
        metric_card("Ready for review", ready, "Ready for review or indexing")
    with columns[2]:
        metric_card("Indexed", stats.get("indexed", 0), "Available for retrieval")
    with columns[3]:
        metric_card("Issues", attention, "No warnings or failures" if attention == 0 else "Warnings or failures")

    st.markdown("<div style='height:1.45rem'></div>", unsafe_allow_html=True)
    if not documents:
        with st.container(border=True, key="overview-recent-list"):
            st.markdown("<div class='overview-list-title'>Recently updated documents</div>", unsafe_allow_html=True)
            st.markdown("<div class='review-empty'><div class='review-empty-title'>No document activity yet</div>"
                        "<div class='review-empty-copy'>Upload a PDF or DOCX to begin processing.</div></div>", unsafe_allow_html=True)
        return

    with st.container(border=True, key="overview-recent-list"):
        st.markdown("<div class='overview-list-title'>Recently updated documents</div>", unsafe_allow_html=True)

        header = st.columns([3.3, 0.7, 1.45, 1.1, 0.85], vertical_alignment="center")
        for column, label in zip(header, ["File", "Version", "Updated", "Status", ""]):
            column.markdown(f"<div class='overview-column-heading'>{label}</div>", unsafe_allow_html=True)

        recent = documents[:3]
        for index, item in enumerate(recent):
            count = document_chunk_count(service, item.document_id)
            row = st.columns([3.3, 0.7, 1.45, 1.1, 0.85], vertical_alignment="center")
            row[0].markdown(
                f"<div class='overview-action-row'><div><div class='overview-file'>{escape(item.file_name)}</div>"
                f"<div class='overview-meta'>{escape(item.file_type.upper())} &middot; "
                f"{overview_chunk_label(item.status, count)}</div></div></div>",
                unsafe_allow_html=True,
            )
            row[1].markdown(f"<div class='overview-column-value'>{escape(item.version)}</div>", unsafe_allow_html=True)
            row[2].markdown(f"<div class='overview-column-value'>{format_updated(item.updated_at)}</div>", unsafe_allow_html=True)
            row[3].markdown(f"<div class='overview-action-row'>{status_badge(item.status)}</div>", unsafe_allow_html=True)
            row[4].button(
                overview_action_label(item.status),
                key=f"overview-document-{item.document_id}",
                on_click=select_document_for_review,
                args=(item.document_id,),
            )
            if index < len(recent) - 1:
                st.markdown("<div class='overview-row-rule'></div>", unsafe_allow_html=True)

        history_action, _, upload_action = st.columns([1.7, 3.3, 1.35], vertical_alignment="center")
        history_action.button("View full document history ->", key="overview-history", on_click=open_document_history)
        upload_action.button("Upload new source ->", key="overview-upload-source", on_click=navigate_to, args=("Upload & history",))


def render_upload(service: WorkspaceService) -> None:
    with st.container(border=True, key="upload-intake-card"):
        st.markdown(
            "<div class='eyebrow'>New intake</div>"
            "<div class='section-title' style='margin-top:.45rem;'>Upload source</div>"
            "<div class='section-copy'>Add one PDF or DOCX. The original filename is preserved for traceability.</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:.85rem'></div>", unsafe_allow_html=True)
        uploaded_file = st.file_uploader(
            "Choose a PDF or DOCX",
            type=["pdf", "docx"],
            accept_multiple_files=False,
            label_visibility="collapsed",
        )
        if uploaded_file is None:
            st.session_state.pop("duplicate_document_id", None)
            st.session_state.pop("duplicate_notice", None)
        st.markdown(
            "<div class='upload-constraints'>Accepted formats: PDF, DOCX &nbsp;·&nbsp; Maximum size: 200MB &nbsp;·&nbsp; Processing stays local</div>",
            unsafe_allow_html=True,
        )
        version_info, version_input, action_col, _ = st.columns([1.25, 0.75, 1.15, 2.2], gap="small", vertical_alignment="center")
        version_info.markdown(
            "<div class='upload-version-label'>Version</div>"
            "<div class='upload-version-helper'>Suggested from previous uploads with the same filename. Use numbers only, for example 1 or 1.1.</div>",
            unsafe_allow_html=True,
        )
        suggested_version = "1"
        if uploaded_file is not None:
            suggested_version = service.suggested_version_for_filename(uploaded_file.name)
        upload_file_name = uploaded_file.name if uploaded_file is not None else None
        if st.session_state.get("upload-version-input-filename") != upload_file_name:
            st.session_state["upload-version-input"] = suggested_version
            st.session_state["upload-version-input-filename"] = upload_file_name
        with version_input:
            upload_version = st.text_input(
                "Version",
                label_visibility="collapsed",
                key="upload-version-input",
                disabled=uploaded_file is None,
            )
        normalized_version = upload_version.strip() or "1"
        version_is_valid = bool(UPLOAD_VERSION_PATTERN.fullmatch(normalized_version))
        if not version_is_valid:
            version_info.markdown(
                "<div class='upload-version-error'>Use 1 or 1.1 only.</div>",
                unsafe_allow_html=True,
            )
        with action_col:
            submit = st.button(
                "Register and process",
                key="upload-submit",
                disabled=uploaded_file is None,
                type="primary",
                use_container_width=False,
            )
        duplicate_document_id = st.session_state.get("duplicate_document_id")
        duplicate_notice = st.session_state.get("duplicate_notice")
        if duplicate_document_id and duplicate_notice:
            st.markdown(
                f"<div class='duplicate-notice'><strong>This file has already been processed.</strong> "
                f"{escape(duplicate_notice)}</div>",
                unsafe_allow_html=True,
            )
            st.button(
                "Open existing result",
                key="open-existing-result",
                on_click=open_existing_result,
                args=(duplicate_document_id, duplicate_notice),
            )
    if not submit or uploaded_file is None:
        return
    if not version_is_valid:
        return
    file_bytes = uploaded_file.getvalue()
    try:
        service.validate_upload(uploaded_file.name, file_bytes)
    except ValueError as exc:
        st.error(str(exc))
        return
    existing_document = service.find_document_by_checksum(file_bytes)
    if existing_document is not None:
        st.session_state["duplicate_document_id"] = existing_document.document_id
        st.session_state["duplicate_notice"] = duplicate_upload_notice(uploaded_file.name)
        st.rerun()

    with st.spinner("Registering, parsing, validating, and chunking the document..."):
        st.session_state.pop("duplicate_document_id", None)
        st.session_state.pop("duplicate_notice", None)
        saved_path = service.save_uploaded_file(uploaded_file.name, file_bytes, "document")
        record = service.register_path(saved_path, "document", normalized_version)
        st.session_state["selected_document_id"] = record.document_id
        try:
            service.ingest_document(record.document_id)
        except Exception as exc:
            st.error(f"Document registered, but processing failed: {exc}")
        else:
            st.session_state["document-action-notice"] = f"{record.file_name} is parsed and ready for inspection."
            st.session_state["active_page"] = "Result review"
            st.rerun()


def select_document_for_review(document_id: str) -> None:
    st.session_state["selected_document_id"] = document_id
    st.session_state["active_page"] = "Result review"


def clear_history_filters() -> None:
    st.session_state["history-search"] = ""
    st.session_state["history-view"] = "By time (newest)"


def selected_history_documents(documents) -> list[str]:
    return [
        item.document_id
        for item in documents
        if st.session_state.get(f"history-delete-{item.document_id}", False)
    ]


def clear_pending_history_delete() -> None:
    st.session_state.pop("history-delete-pending", None)


def clear_history_delete_mode() -> None:
    st.session_state["history-delete-mode"] = False
    clear_pending_history_delete()


@st.dialog("Delete selected documents?")
def confirm_history_delete_dialog(service: WorkspaceService, documents, pending_delete_ids: list[str]) -> None:
    pending_documents = [item for item in documents if item.document_id in pending_delete_ids]
    pending_names = ", ".join(item.file_name for item in pending_documents) or "selected documents"
    pending_file_names = {item.file_name for item in pending_documents}
    st.warning(
        f"This permanently removes {len(pending_delete_ids)} document(s), their workspace artifacts, and indexed vectors."
    )
    st.caption(pending_names)
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("Delete permanently", key="history-confirm-delete", type="primary", use_container_width=True):
        failures: list[str] = []
        for document_id in pending_delete_ids:
            try:
                service.delete_document(document_id, DEFAULT_CHROMA_DIR)
            except Exception as exc:
                failures.append(f"{document_id}: {exc}")
                continue
            st.session_state.pop(f"history-delete-{document_id}", None)
            if st.session_state.get("selected_document_id") == document_id:
                st.session_state.pop("selected_document_id", None)
        if failures:
            st.error("Delete failed for: " + " | ".join(failures))
            return
        if st.session_state.get("upload-version-input-filename") in pending_file_names:
            st.session_state.pop("upload-version-input", None)
            st.session_state.pop("upload-version-input-filename", None)
        clear_history_delete_mode()
        st.session_state["history-action-notice"] = f"Deleted {len(pending_delete_ids)} document(s) from the workspace."
        st.rerun()
    if cancel_col.button("Cancel", key="history-cancel-delete", use_container_width=True):
        clear_pending_history_delete()
        st.rerun()


def render_document_history(service: WorkspaceService) -> None:
    with st.container(border=True, key="document-history-card"):
        documents = service.workspace.list_documents()
        title_col, delete_col = st.columns([5, 1.35], vertical_alignment="top")
        with title_col:
            st.markdown(
                "<div class='eyebrow'>Document history</div>"
                "<div class='card-title'>Document history</div>"
                "<div class='card-copy'>Search, filter, review, or manage previously processed documents.</div>",
                unsafe_allow_html=True,
            )
        delete_mode = st.session_state.get("history-delete-mode", False)
        if documents:
            with delete_col:
                if delete_mode:
                    if st.button("Cancel deletion", key="history-cancel-delete-mode", use_container_width=True):
                        clear_history_delete_mode()
                        st.rerun()
                elif st.button("Delete documents", key="history-start-delete", use_container_width=True):
                    st.session_state["history-delete-mode"] = True
                    st.rerun()
        history_notice = st.session_state.pop("history-action-notice", None)
        if history_notice:
            render_success_notice(history_notice)
        if not documents:
            st.markdown(
                "<div class='history-empty-inline'><div><strong>No documents yet</strong><br>"
                "Upload a PDF or DOCX above to create your first processing record.</div></div>",
                unsafe_allow_html=True,
            )
            return

        controls = st.columns([2.4, 1], gap="medium")
        search_query = controls[0].text_input(
            "Search documents",
            placeholder="Search by filename",
            key="history-search",
        )
        view_options = ["By time (newest)", "Alphabetical (A-Z)", "Indexed", "Ready for review", "Failed"]
        selected_view = controls[1].selectbox("View documents by", view_options, key="history-view")
        status_filter = {
            "Ready for review": "review_ready",
            "Indexed": "indexed",
            "Failed": "failed",
        }.get(selected_view)
        normalized_query = search_query.strip().lower()
        visible = [
            item
            for item in documents
            if (status_filter is None or item.status == status_filter)
            and (not normalized_query or normalized_query in item.file_name.lower())
        ]
        if selected_view == "Alphabetical (A-Z)":
            visible.sort(key=lambda item: item.file_name.casefold())
        else:
            visible.sort(key=lambda item: item.updated_at, reverse=True)

        if not visible:
            if normalized_query:
                message = f"No documents match \"{escape(search_query.strip())}\"."
            elif selected_view in {"Indexed", "Ready for review", "Failed"}:
                message = f"No {selected_view.lower()} documents found."
            else:
                message = "No documents have been uploaded yet."
            empty_row = st.columns([6, 1], vertical_alignment="center")
            empty_row[0].markdown(
                f"<div class='history-empty-inline'><strong>{message}</strong></div>",
                unsafe_allow_html=True,
            )
            empty_row[1].button("Clear filters", key="clear-history-filters", on_click=clear_history_filters)
            return

        table_columns = [0.55, 2.75, 0.7, 1.2, 1.0, 0.8] if delete_mode else [3.3, 0.7, 1.2, 1.0, 0.8]
        table_headers = ["", "File", "Version", "Updated", "Status", "Actions"] if delete_mode else ["File", "Version", "Updated", "Status", "Actions"]
        if delete_mode:
            selected_ids = selected_history_documents(visible)
            delete_controls = st.columns([3.6, 1.45], vertical_alignment="center")
            delete_controls[0].markdown(
                f"<div class='subtle'>Selected: {len(selected_ids)} document(s).</div>",
                unsafe_allow_html=True,
            )
            if delete_controls[1].button(
                f"Delete selected ({len(selected_ids)})",
                key="history-delete-selected",
                disabled=not selected_ids,
                type="primary",
                use_container_width=True,
            ):
                confirm_history_delete_dialog(service, documents, selected_ids)
        header = st.columns(table_columns, vertical_alignment="center")
        for column, label in zip(header, table_headers):
            column.markdown(f"<div class='history-heading'>{label}</div>", unsafe_allow_html=True)
        with st.container(height=430, border=False, key="document-history-list"):
            for index, item in enumerate(visible):
                count = document_chunk_count(service, item.document_id) if not delete_mode else 0
                document_summary = overview_chunk_label(item.status, count) if not delete_mode else "Select to delete"
                row = st.columns(table_columns, vertical_alignment="center")
                data_columns = row
                if delete_mode:
                    row[0].checkbox(
                        "Select document",
                        key=f"history-delete-{item.document_id}",
                        label_visibility="collapsed",
                    )
                    data_columns = row[1:]
                data_columns[0].markdown(
                    f"<div class='history-row'><div class='history-file'>{escape(item.file_name)}</div>"
                    f"<div class='history-meta'>{escape(item.file_type.upper())} &middot; "
                    f"{document_summary}</div></div>",
                    unsafe_allow_html=True,
                )
                data_columns[1].markdown(f"<div class='history-value'>{escape(item.version)}</div>", unsafe_allow_html=True)
                data_columns[2].markdown(f"<div class='history-value'>{format_updated(item.updated_at)}</div>", unsafe_allow_html=True)
                data_columns[3].markdown(status_badge(item.status), unsafe_allow_html=True)
                data_columns[4].button(
                    "Review",
                    key=f"review-{item.document_id}",
                    on_click=select_document_for_review,
                    args=(item.document_id,),
                )
                if index < len(visible) - 1:
                    st.markdown("<div class='history-row-rule'></div>", unsafe_allow_html=True)



def render_upload_history(service: WorkspaceService) -> None:
    st.markdown("<div class='page-header'><div class='eyebrow'>Document registry</div>", unsafe_allow_html=True)
    st.title("Upload & history")
    st.markdown(
        "<p class='subtle'>Register a source, then review its processing result before explicitly indexing it.</p></div>",
        unsafe_allow_html=True,
    )
    render_upload(service)
    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    render_document_history(service)


@st.dialog("Index validated chunks?")
def confirm_document_index_dialog(service: WorkspaceService, document_id: str, chunk_count: int) -> None:
    st.markdown(f"Index **{chunk_count} validated chunks** from this document?")
    st.caption("Existing vectors for this document will be replaced in ChromaDB.")
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("Index and replace vectors", key=f"confirm-index-{document_id}", type="primary", use_container_width=True):
        try:
            count = service.index_document(document_id, DEFAULT_COLLECTION, DEFAULT_CHROMA_DIR)
        except Exception as exc:
            st.error(f"Indexing failed: {exc}")
            return
        st.session_state["document-action-notice"] = f"Indexed {count} chunks. Older vectors for this document were replaced."
        st.rerun()
    if cancel_col.button("Cancel", key=f"cancel-index-{document_id}", use_container_width=True):
        st.rerun()


def render_document_detail(service: WorkspaceService, document_id: str) -> None:
    document = service.workspace.get_document(document_id)
    if document is None:
        return
    review_notice = st.session_state.pop("review_notice", None)
    action_notice = st.session_state.pop("document-action-notice", None)
    if review_notice:
        st.markdown(
            f"<div class='duplicate-notice'><strong>Existing document opened.</strong> "
            f"{escape(review_notice)}</div>",
            unsafe_allow_html=True,
        )
    if action_notice:
        render_success_notice(action_notice)
    validation = service.workspace.get_latest_validation_summary(document.document_id)
    chunks = service.workspace.list_chunks(document.document_id)
    markdown_text = read_text(document.artifacts.get("markdown"))
    canonical_json = read_json(document.artifacts.get("document_json")) or {}
    chunk_artifact = read_json(document.artifacts.get("chunks")) or []
    full_chunk_text = {
        item.get("chunk_id"): item.get("text", "")
        for item in chunk_artifact
        if isinstance(item, dict)
    }

    with st.container(border=True, key="document-inspector-card"):
        st.markdown("<div class='inspector-kicker'>Document inspector</div>", unsafe_allow_html=True)
        name_col, status_col = st.columns([4.8, 1.2], vertical_alignment="center")
        name_col.markdown(f"<h2>{escape(document.file_name)}</h2>", unsafe_allow_html=True)
        status_col.markdown("<div class='document-status'>" + status_badge(document.status) + "</div>", unsafe_allow_html=True)
        index_note = "Indexed in ChromaDB" if document.status == "indexed" else "Not indexed"
        st.markdown(
            f"<div class='document-meta'>{escape(document.file_type.upper())} &middot; {escape(document.version)} &middot; "
            f"{escape(parser_display_name(document.parser_name))} &middot; {len(chunks)} validated chunks &middot; {index_note}</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<div class='document-toolbar'></div>", unsafe_allow_html=True)
        left_actions, spacer, right_action = st.columns([1.0, 4.4, 1.6], vertical_alignment="center")
        with left_actions:
            if st.button("Re-process", key=f"process-{document.document_id}"):
                try:
                    service.ingest_document(document.document_id)
                except Exception as exc:
                    st.error(f"Processing failed: {exc}")
                else:
                    st.session_state["document-action-notice"] = "Document re-processed. Review and approve again before indexing."
                    st.rerun()
        if document.status == "review_ready":
            if right_action.button("Approve for indexing", key=f"approve-{document.document_id}", type="primary"):
                try:
                    service.approve_document(document.document_id)
                except Exception as exc:
                    st.error(f"Approval failed: {exc}")
                else:
                    st.session_state["document-action-notice"] = "Document approved. You can index it now."
                    st.rerun()
        else:
            index_label = f"Index {len(chunks)} chunks" if chunks else "Index approved chunks"
            if right_action.button(
                index_label,
                key=f"index-{document.document_id}",
                disabled=document.status != "approved",
                type="primary",
            ):
                confirm_document_index_dialog(service, document.document_id, len(chunks))

    if document.error_message:
        st.error(document.error_message)

    tabs = st.tabs(["Summary", "Chunks", "Artifacts"])
    with tabs[0]:
        validation_summary = (validation or {}).get("summary", {})
        validation_events = (validation or {}).get("events", [])
        validation_run = (validation or {}).get("run_status") in {"review_ready", "approved", "validated", "low_confidence", "failed"}
        if document.status == "failed":
            panel_class, panel_title, panel_copy = "failed", "Validation failed", "This document cannot be indexed until processing succeeds."
        elif document.status == "low_confidence" or validation_events:
            panel_class, panel_title, panel_copy = "attention", "Validation requires attention", "Review the recorded warnings before deciding whether to re-process."
        elif document.status == "review_ready":
            panel_class, panel_title, panel_copy = "passed", "Awaiting manual review", "Automated parsing passed. Approve this document before indexing."
        elif document.status == "approved":
            panel_class, panel_title, panel_copy = "passed", "Approved for indexing", "Manual review is complete. This document can now be indexed into ChromaDB."
        else:
            panel_class, panel_title = "passed", "Validation passed"
            panel_copy = "This document has completed validation and indexing."
        st.markdown(
            f"<div class='validation-panel {panel_class}'><div class='validation-panel-title'>{panel_title}</div>"
            f"<div class='validation-panel-copy'>{panel_copy}</div></div>",
            unsafe_allow_html=True,
        )
        block_count = validation_summary.get("block_count", len(canonical_json.get("blocks", [])))
        artifact_presence = validation_summary.get("artifact_presence")
        artifact_value = "Not recorded" if not isinstance(artifact_presence, dict) else ("Available" if all(artifact_presence.values()) else "Incomplete")
        processing_status = "Failed" if document.status == "failed" else ("Not processed" if document.status == "registered" else "Completed")
        review_status = {
            "registered": "Not started",
            "review_ready": "Awaiting approval",
            "approved": "Approved for indexing",
            "validated": "Approved for indexing",
            "low_confidence": "Needs attention",
            "indexed": "Indexed",
            "failed": "Unavailable",
        }.get(document.status, document.status.replace("_", " ").title())
        validation_values = [
            ("Processing status", processing_status),
            ("Review status", review_status),
            ("Parser", parser_display_name(document.parser_name or (validation or {}).get("parser"))),
            ("Blocks", str(block_count)),
            ("Validated chunks", str(len(chunks))),
            ("Artifacts", artifact_value),
            ("Warnings / errors", str(len(validation_events)) if validation_run else "Not recorded"),
            ("Source", document.source_path),
            ("Checksum", document.checksum),
            ("Collection", document.collection_name or DEFAULT_COLLECTION),
        ]
        audit_rows = "".join(
            f"<div class='validation-audit-row'><div class='validation-audit-label'>{escape(label)}</div>"
            f"<div class='validation-audit-value'>{escape(value)}</div></div>"
            for label, value in validation_values
        )
        st.markdown(f"<div class='validation-audit'>{audit_rows}</div>", unsafe_allow_html=True)
        with st.expander("View raw validation JSON"):
            st.json(validation or {"status": "No processing run recorded."})

    with tabs[1]:
        search_key = f"chunk-search-{document.document_id}"
        st.markdown(
            f"<div class='chunk-summary'>{len(chunks)} validated chunks &middot; Search section names, chunk text, or technical IDs.</div>",
            unsafe_allow_html=True,
        )
        search_input, search_action = st.columns([5, 0.8], vertical_alignment="bottom")
        chunk_query = search_input.text_input(
            "Search chunks",
            placeholder="Enter a chunk number, or search section, text, or ID",
            key=search_key,
        )
        if chunk_query.strip():
            search_action.button("Clear search", key=f"clear-chunk-search-{document.document_id}", on_click=clear_chunk_search, args=(search_key,))
        normalized_query = normalize_search_text(chunk_query)
        if normalized_query.isdecimal():
            requested_chunk_number = int(normalized_query)
            visible_chunks = [
                item
                for item in chunks
                if str(item.get("chunk_index") or "").isdecimal()
                and int(item["chunk_index"]) == requested_chunk_number
            ]
        else:
            visible_chunks = [
                item for item in chunks
                if not normalized_query
                or normalized_query in normalize_search_text(str(item.get("section_path") or ""))
                or normalized_query in normalize_search_text(str(item.get("chunk_id") or ""))
                or normalized_query in normalize_search_text(full_chunk_text.get(item.get("chunk_id"), item.get("text_preview", "")))
            ]
        if not chunks:
            st.info("No chunks have been recorded for this document.")
        elif not visible_chunks:
            st.markdown(
                f"<div class='history-empty-inline'><strong>No chunks match “{escape(chunk_query.strip())}”.</strong></div>",
                unsafe_allow_html=True,
            )
        else:
            if normalized_query:
                st.caption(f"Showing {len(visible_chunks)} of {len(chunks)} validated chunks")
            with st.container(height=620, border=True, key=f"chunk-results-{document.document_id}"):
                for index, item in enumerate(visible_chunks, start=1):
                    full_text = full_chunk_text.get(item.get("chunk_id"), item.get("text_preview", ""))
                    preview = full_text.replace("\n", " ").strip()
                    if len(preview) > 220:
                        preview = preview[:217].rstrip() + "..."
                    page = item.get("page_start") if item.get("page_start") is not None else "—"
                    indexed = "Yes" if item.get("indexed_at") else "No"
                    chunk_number = int(item.get("chunk_index") or index)
                    with st.container(border=True, key=f"chunk-evidence-{document.document_id}-{item.get('chunk_id')}"):
                        st.markdown(
                            f"<div class='evidence-title'>Chunk {chunk_number:02d} &middot; {escape(item.get('section_path') or 'Untitled section')}</div>"
                            f"<div class='evidence-meta'>{escape(item.get('chunk_id') or '')} &nbsp;·&nbsp; Page {page} &nbsp;·&nbsp; Indexed {indexed}</div>"
                            f"<div class='evidence-preview'>{escape(preview)}</div>",
                            unsafe_allow_html=True,
                        )
                        with st.expander(f"View full chunk {chunk_number:02d}"):
                            st.markdown(f"<div class='chunk-full-text'>{evidence_html(full_text)}</div>", unsafe_allow_html=True)

    with tabs[2]:
        blocks = canonical_json.get("blocks", [])
        metadata = canonical_json.get("metadata", {})
        with st.container(border=True):
            st.markdown("#### Artifacts")
            st.caption("Review generated processing outputs or download the canonical JSON for auditing and debugging.")
            summary = st.columns(3)
            summary[0].markdown(f"<div class='artifact-value'>{len(blocks)}</div><div class='artifact-label'>Blocks</div>", unsafe_allow_html=True)
            summary[1].markdown(f"<div class='artifact-value'>{len(chunks)}</div><div class='artifact-label'>Validated chunks</div>", unsafe_allow_html=True)
            source_format = str(metadata.get("source_format") or document.file_type).upper()
            summary[2].markdown(f"<div class='artifact-value'>{escape(source_format)}</div><div class='artifact-label'>Source format</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='artifact-meta'><strong>Document ID</strong> "
                f"<span class='artifact-meta-value'>{escape(str(canonical_json.get('document_id', document.document_id)))}</span>"
                f" &nbsp;&middot;&nbsp; <strong>Parser</strong> "
                f"<span class='artifact-meta-value'>{escape(parser_display_name(document.parser_name))}</span></div>",
                unsafe_allow_html=True,
            )
            locations = (
                ("Markdown location", document.artifacts.get("markdown") or "Not generated"),
                ("Canonical JSON location", document.artifacts.get("document_json") or "Not generated"),
            )
            location_rows = "".join(
                f"<div class='artifact-location-row'><div class='artifact-location-label'>{escape(label)}</div>"
                f"<div class='artifact-location-value'>{escape(str(value))}</div></div>"
                for label, value in locations
            )
            st.markdown(f"<div class='artifact-location-list'>{location_rows}</div>", unsafe_allow_html=True)
            markdown_download, canonical_download = st.columns(2)
            markdown_download.download_button(
                "Download Markdown",
                data=markdown_text or "",
                file_name=f"{Path(document.file_name).stem}.md",
                mime="text/markdown",
                key=f"download-markdown-{document.document_id}",
                use_container_width=True,
            )
            canonical_download.download_button(
                "Download canonical JSON",
                data=json.dumps(canonical_json, indent=2, ensure_ascii=False),
                file_name=f"{Path(document.file_name).stem}-canonical.json",
                mime="application/json",
                key=f"download-canonical-{document.document_id}",
                use_container_width=True,
            )


def render_result_review(service: WorkspaceService) -> None:
    st.markdown("<div class='page-header'><div class='eyebrow'>Processing evidence</div>", unsafe_allow_html=True)
    st.title("Result review")
    st.markdown(
        "<p class='subtle'>Inspect traceable parser output and validated chunks before writing vectors to ChromaDB.</p></div>",
        unsafe_allow_html=True,
    )
    documents = service.workspace.list_documents()
    if not documents:
        with st.container(border=True, key="result-review-empty"):
            st.markdown(
                "<div class='empty-state-title'>No result to review yet</div>"
                "<div class='empty-state-copy'>Upload and process a PDF or DOCX before inspecting validation and chunks.</div>",
                unsafe_allow_html=True,
            )
            st.button("Upload a source →", key="upload-from-review-empty", on_click=navigate_to, args=("Upload & history",))
        return
    selected_id = st.session_state.get("selected_document_id")
    if selected_id not in {document.document_id for document in documents}:
        with st.container(border=True):
            st.markdown(
                "<div class='review-empty-title'>No document selected</div>"
                "<div class='review-empty-copy'>Choose a document from Upload &amp; history to inspect validation, chunks, and artifacts.</div>",
                unsafe_allow_html=True,
            )
            if st.button("Open document history →", key="open-history-from-review"):
                open_document_history()
                st.rerun()
        return
    render_document_detail(service, selected_id)


def render_retrieval(service: WorkspaceService) -> None:
    st.markdown("<div class='page-header'><div class='eyebrow'>Vector verification</div>", unsafe_allow_html=True)
    st.title("Retrieval validation")
    st.markdown(
        "<p class='subtle'>Query indexed chunks and inspect the returned source evidence. No answer is generated.</p></div>",
        unsafe_allow_html=True,
    )
    stats = service.workspace.stats()
    indexed_count = stats.get("indexed", 0)
    with st.container(border=True, key="retrieval-query-card"):
        st.markdown(
            "<div class='section-title'>Search indexed evidence</div>"
            "<div class='section-copy'>Ask a question grounded in an indexed document, then inspect the returned chunks and citations.</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:.75rem'></div>", unsafe_allow_html=True)
        scope_col, count_col = st.columns([2.4, 1], vertical_alignment="top")
        scope_col.markdown("<div class='retrieval-field-label'>Indexed collection</div>", unsafe_allow_html=True)
        scope_col.markdown(
            f"<div class='upload-info-strip'><strong>Collection:</strong> {escape(DEFAULT_COLLECTION)} &nbsp;·&nbsp; "
            f"<strong>Indexed documents:</strong> {indexed_count}</div>",
            unsafe_allow_html=True,
        )
        with count_col:
            st.markdown("<div class='retrieval-field-label'>Top results</div>", unsafe_allow_html=True)
            result_count = st.selectbox("Top results", [3, 5, 8], index=0, label_visibility="collapsed")
        question_col, _ = st.columns([4, 1])
        with question_col:
            query = st.text_area(
                "Retrieval question",
                placeholder="Ask a question whose answer appears in an indexed document.",
                height=76,
            )
        run = st.button("Run retrieval", type="primary", disabled=indexed_count == 0)
    if indexed_count == 0:
        st.markdown(
            "<div class='retrieval-empty'><strong>No indexed documents yet.</strong><br>Approve and index a reviewed document before verifying retrieval.</div>",
            unsafe_allow_html=True,
        )
    if not run:
        return
    query_error = validate_retrieval_query(query)
    if query_error:
        st.markdown(f"<div class='retrieval-query-error'>{escape(query_error)}</div>", unsafe_allow_html=True)
        return
    with st.spinner("Searching indexed chunks..."):
        try:
            results = search(query.strip(), DEFAULT_COLLECTION, DEFAULT_CHROMA_DIR, DEFAULT_MODEL_NAME, top_k=result_count)
        except Exception as exc:
            st.error(f"Retrieval failed: {exc}")
            return
    if not results:
        st.info("No chunks returned. Confirm that documents have been indexed into this collection.")
        return
    st.markdown(
        f"<div class='eyebrow' style='margin-top:1.5rem;'>{len(results)} returned results</div>"
        f"<h2>Evidence for “{escape(query.strip())}”</h2>",
        unsafe_allow_html=True,
    )
    for position, result in enumerate(results, start=1):
        with st.container(border=True):
            header, score = st.columns([5.85, 1], vertical_alignment="center")
            header.markdown(
                f"<div class='retrieval-rank'>Result {position:02d}</div>",
                unsafe_allow_html=True,
            )
            with header:
                render_source_download_button(
                    service,
                    result.document_id,
                    f"download-source-retrieval-{position}-{result.document_id}",
                    label=result.file_name,
                )
                st.markdown(f"<div class='retrieval-citation'>{escape(result.citation)}</div>", unsafe_allow_html=True)
            score.markdown(f"<div style='text-align:right'><span class='score-pill'>{result.score:.2f}</span></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='retrieval-text'>{evidence_html(result.text)}</div>", unsafe_allow_html=True)


def main() -> None:
    setup_local_model_env()
    st.set_page_config(page_title="RAG Ingestion", layout="wide", initial_sidebar_state="collapsed")
    inject_styles()
    service = WorkspaceService()
    render_topbar()
    active_page = render_navigation()
    if active_page == "Overview":
        render_overview(service)
    elif active_page == "Upload & history":
        render_upload_history(service)
    elif active_page == "Result review":
        render_result_review(service)
    else:
        render_retrieval(service)


if __name__ == "__main__":
    main()
