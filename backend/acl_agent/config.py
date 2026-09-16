"""
ACL Blog Agent - configuration.

All environment-driven settings and shared constants live here.
Every other module imports from this one for config values.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

ROOT_DIR = BASE_DIR.parent
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(ENV_PATH)

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
HF_API_KEY = (os.getenv("HF_API_KEY") or "").strip()

if OPENAI_API_KEY:
    LLM_PROVIDER = "openai"
    _default_model = "gpt-4o"
elif HF_API_KEY:
    LLM_PROVIDER = "huggingface"
    _default_model = "meta-llama/Llama-3.1-8B-Instruct"
else:
    raise RuntimeError(
        "No generation API key found. Add OPENAI_API_KEY or HF_API_KEY to .env."
    )

MODEL = os.getenv("MODEL", _default_model)

BRAND_NAME = os.getenv("BRAND_NAME", "")

BRAND_SITE = os.getenv("BRAND_SITE", "").rstrip("/")

BLOG_URL = os.getenv(
    "BLOG_URL",
    f"{BRAND_SITE}/blogs/news" if BRAND_SITE else "",
).rstrip("/")

BLOG_KB_LIMIT = int(
    os.getenv("BLOG_KB_LIMIT", "50")
)

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)

# How far the generated article is allowed to drift from the brief's
# target_word_count, as a fraction of the target (0.05 = +/-5%). Both
# under and over this band are hard validation errors - the article
# must land close to whatever word count the user asked for, not
# just clear a floor.
WORD_COUNT_TOLERANCE = float(
    os.getenv("WORD_COUNT_TOLERANCE", "0.05")
)

GENERATION_MODE = os.getenv(
    "GENERATION_MODE",
    "single",
).strip().lower()

PLAGIARISM_OVERLAP_THRESHOLD = float(
    os.getenv("PLAGIARISM_OVERLAP_THRESHOLD", "0.15")
)

INDEX_PATH = DATA_DIR / "knowledge.index"
CHUNKS_PATH = DATA_DIR / "knowledge_chunks.json"
BM25_PATH = DATA_DIR / "bm25_index.pkl"
MANIFEST_PATH = DATA_DIR / "ingestion_manifest.json"

# Hybrid RAG settings
RERANKER_MODEL = os.getenv(
    "RERANKER_MODEL",
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
)
HYBRID_CANDIDATE_K = int(
    os.getenv("HYBRID_CANDIDATE_K", "16")
)
HYBRID_STYLE_TOP_K = int(
    os.getenv("HYBRID_STYLE_TOP_K", "5")
)
HYBRID_FACT_TOP_K = int(
    os.getenv("HYBRID_FACT_TOP_K", "7")
)
SEMANTIC_WEIGHT = float(
    os.getenv("SEMANTIC_WEIGHT", "0.6")
)
BM25_WEIGHT = float(
    os.getenv("BM25_WEIGHT", "0.4")
)

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "*",
    ).split(",")
    if origin.strip()
]

CORS_ALLOW_CREDENTIALS = (
    ALLOWED_ORIGINS != ["*"]
)

# Humanization thresholds
HUMANIZATION_MIN_CONTRACTION_DENSITY = float(
    os.getenv("HUMANIZATION_MIN_CONTRACTION_DENSITY", "0.02")
)
HUMANIZATION_MAX_CONTRACTION_DENSITY = float(
    os.getenv("HUMANIZATION_MAX_CONTRACTION_DENSITY", "0.18")
)
HUMANIZATION_MIN_SENTENCE_VARIANCE = float(
    os.getenv("HUMANIZATION_MIN_SENTENCE_VARIANCE", "0.25")
)
HUMANIZATION_MAX_REPEAT_STARTER_PCT = float(
    os.getenv("HUMANIZATION_MAX_REPEAT_STARTER_PCT", "0.30")
)
HUMANIZATION_MAX_FILLER_COUNT = int(
    os.getenv("HUMANIZATION_MAX_FILLER_COUNT", "3")
)

# SERP analysis
SERP_RESULTS_COUNT = int(
    os.getenv("SERP_RESULTS_COUNT", "5")
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

logger = logging.getLogger("acl-blog-agent")

if LLM_PROVIDER == "openai":
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
else:
    from huggingface_hub import InferenceClient

    client = InferenceClient(api_key=HF_API_KEY)

logger.info(
    "Generation provider: %s (model=%s)",
    LLM_PROVIDER,
    MODEL,
)
