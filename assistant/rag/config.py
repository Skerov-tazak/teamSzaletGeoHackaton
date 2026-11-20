"""Central configuration for the RAG module. Override paths with env vars."""
from __future__ import annotations

import os
from pathlib import Path

ASSISTANT_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = ASSISTANT_DIR.parent


def _default_metodyki() -> Path:
    for cand in (REPO_DIR / "metodyki", REPO_DIR.parent / "field-under-pressure-materials" / "metodyki"):
        if cand.is_dir():
            return cand
    return REPO_DIR / "metodyki"


METODYKI_DIR = Path(os.getenv("METODYKI_DIR", _default_metodyki()))
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", ASSISTANT_DIR / "data"))
PROCESSED_DIR = DATA_DIR / "processed"
INDEX_DIR = DATA_DIR / "index"

DOCS_JSON = PROCESSED_DIR / "docs.json"
PAGES_JSONL = PROCESSED_DIR / "pages.jsonl"
SECTIONS_JSON = PROCESSED_DIR / "sections.json"
CHUNKS_JSONL = PROCESSED_DIR / "chunks.jsonl"
RISK_JSON = PROCESSED_DIR / "risk_conditions.json"
BM25_PKL = INDEX_DIR / "bm25.pkl"
EMB_CACHE = INDEX_DIR / "emb_cache.npz"

EXCEL_FILE = METODYKI_DIR / "ryzyka_zebrane.xlsx"
EXCEL_DOC_ID = "ryzyka_zebrane"
EXCEL_TITLE = "Zestawienie warunków ryzyka chorób i szkodników (ryzyka_zebrane.xlsx)"

# --- PDF parsing ---
HEADER_FOOTER_FRAC = 0.07       # top/bottom band treated as running head/foot
PAGE_NUM_FRAC = 0.12            # lone numbers in this band = printed page number
HEADER_REPEAT_FRAC = 0.30       # line must repeat on >= 30% of pages
MIN_WORDS_PAGE = 30
TABLE_MIN_RULES = 8             # prefilter: >= N horizontal and vertical rules
TABLE_MAX_EMPTY = 0.60

# --- Headings ---
HEADING_SIZE_RATIO = 1.15       # fallback detector (no TOC)
HEADING_MAX_CHARS = 120

# --- Chunking ---
CHUNK_TARGET_MIN_WORDS = 180
CHUNK_TARGET_MAX_WORDS = 280
CHUNK_MAX_TOKENS = 450
OVERLAP_MAX_WORDS = 50
SMALL_SECTION_WORDS = 60
TABLE_MAX_TOKENS = 420

# --- Embeddings ---
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "sdadas/mmlw-retrieval-roberta-base")
QUERY_PREFIX = "zapytanie: "
EMBED_BATCH = 32
EMBED_MAX_SEQ = 512

# --- Qdrant ---
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "guides_mmlw_v1")
UPSERT_BATCH = 192

# --- BM25 ---
BM25_STEMMER = os.getenv("RAG_BM25_STEMMER", "stempel")   # "stempel" | "trunc6"

# --- Search / fusion ---
CANDIDATES = 30
RRF_K = 60
RRF_WEIGHT_DENSE = 1.0
RRF_WEIGHT_BM25 = 1.0
LEGAL_PENALTY = 0.5
CROP_EXPANSION = {
    "pszenica": ["pszenica", "zboza"],
    "zboza": ["zboza", "pszenica"],
}
