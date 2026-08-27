"""
ACL Blog Agent - knowledge base: build, load, and retrieve from
the FAISS + BM25 hybrid index of scraped/ingested blog content.

Retrieval uses a three-stage pipeline:
1. FAISS (semantic cosine similarity) + BM25 (keyword exact match)
2. Score-merge the two candidate sets
3. Cross-encoder rerank to produce the final top-K

Style and fact chunks are retrievable separately so the generation
prompt gets clean, purpose-matched context.
"""
from __future__ import annotations

import json
import pickle
import re
import time
from typing import Any, Optional

import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

from acl_agent.config import (
    BM25_PATH,
    BM25_WEIGHT,
    BLOG_KB_LIMIT,
    BLOG_URL,
    CHUNKS_PATH,
    EMBEDDING_MODEL,
    HYBRID_CANDIDATE_K,
    HYBRID_FACT_TOP_K,
    HYBRID_STYLE_TOP_K,
    INDEX_PATH,
    MANIFEST_PATH,
    RERANKER_MODEL,
    SEMANTIC_WEIGHT,
    logger,
)
from acl_agent.models import KnowledgeChunk
from acl_agent.scraping import chunk_text, scrape_blog_content, scrape_blog_list

_embedding_model: Optional[SentenceTransformer] = None
_reranker: Optional[CrossEncoder] = None
_faiss_index: Optional[faiss.Index] = None
_bm25_index: Optional[BM25Okapi] = None
_knowledge_chunks: list[dict[str, Any]] = []
_bm25_corpus_tokens: list[list[str]] = []


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _normalize_scores(scores: np.ndarray) -> np.ndarray:
    min_s = scores.min()
    max_s = scores.max()
    if max_s - min_s < 1e-9:
        return np.zeros_like(scores)
    return (scores - min_s) / (max_s - min_s)


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        logger.info("Loading reranker model: %s", RERANKER_MODEL)
        _reranker = CrossEncoder(RERANKER_MODEL)
    return _reranker


def build_knowledge_base(
    urls: Optional[list[tuple[str, str]]] = None,
) -> dict[str, int]:
    global _embedding_model
    global _faiss_index
    global _bm25_index
    global _knowledge_chunks
    global _bm25_corpus_tokens

    raw_chunks: list[KnowledgeChunk] = []

    if urls:
        logger.info(
            "Building knowledge base from %s explicit URL(s) "
            "(%s tagged as style references).",
            len(urls),
            sum(1 for _, source_type in urls if source_type == "style"),
        )
        blog_links = urls
    else:
        logger.info(
            "Building knowledge base from %s",
            BLOG_URL,
        )
        blog_links = [
            (url, "article")
            for url in scrape_blog_list(
                BLOG_URL,
                limit=BLOG_KB_LIMIT,
            )
        ]

    for position, (url, source_type) in enumerate(
        blog_links,
        start=1,
    ):
        try:
            blog = scrape_blog_content(url)

            if not blog["content"]:
                continue

            chunks = chunk_text(
                blog["content"]
            )

            for chunk_index, chunk in enumerate(
                chunks
            ):
                raw_chunks.append(
                    KnowledgeChunk(
                        chunk_id=(
                            f"blog-{position}-"
                            f"chunk-{chunk_index}"
                        ),
                        text=chunk,
                        title=blog["title"],
                        url=blog["url"],
                        source_type=source_type,
                    )
                )

            logger.info(
                "Indexed %s: %s chunks (source_type=%s)",
                blog["title"],
                len(chunks),
                source_type,
            )

        except Exception as error:
            logger.warning(
                "Skipping %s: %s",
                url,
                error,
            )

    if not raw_chunks:
        raise RuntimeError(
            "No content was indexed."
        )

    _embedding_model = SentenceTransformer(
        EMBEDDING_MODEL
    )

    embeddings = _embedding_model.encode(
        [chunk.text for chunk in raw_chunks],
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    embeddings = np.asarray(
        embeddings,
        dtype="float32",
    )

    _faiss_index = faiss.IndexFlatIP(
        embeddings.shape[1]
    )

    _faiss_index.add(embeddings)

    _bm25_corpus_tokens = [
        _tokenize(chunk.text) for chunk in raw_chunks
    ]
    _bm25_index = BM25Okapi(_bm25_corpus_tokens)

    _knowledge_chunks = [
        chunk.model_dump()
        for chunk in raw_chunks
    ]

    faiss.write_index(
        _faiss_index,
        str(INDEX_PATH),
    )

    with open(BM25_PATH, "wb") as f:
        pickle.dump(_bm25_index, f)

    CHUNKS_PATH.write_text(
        json.dumps(
            _knowledge_chunks,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "embedding_model": EMBEDDING_MODEL,
                "reranker_model": RERANKER_MODEL,
                "documents": len(blog_links),
                "chunks": len(_knowledge_chunks),
                "retrieval": "hybrid_semantic_bm25_reranked",
                "created_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(),
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "documents": len(blog_links),
        "chunks": len(_knowledge_chunks),
    }


def load_knowledge_base() -> bool:
    global _embedding_model
    global _faiss_index
    global _bm25_index
    global _knowledge_chunks
    global _bm25_corpus_tokens

    if not (
        INDEX_PATH.exists()
        and CHUNKS_PATH.exists()
    ):
        logger.warning(
            "Saved knowledge base not found."
        )
        return False

    _embedding_model = SentenceTransformer(
        EMBEDDING_MODEL
    )

    _faiss_index = faiss.read_index(
        str(INDEX_PATH)
    )

    _knowledge_chunks = json.loads(
        CHUNKS_PATH.read_text(
            encoding="utf-8"
        )
    )

    if BM25_PATH.exists():
        with open(BM25_PATH, "rb") as f:
            _bm25_index = pickle.load(f)
        _bm25_corpus_tokens = [
            _tokenize(c["text"]) for c in _knowledge_chunks
        ]
        logger.info(
            "Loaded BM25 index (%s chunks).",
            len(_knowledge_chunks),
        )
    else:
        logger.warning(
            "BM25 index not found; hybrid retrieval "
            "will fall back to semantic only."
        )
        _bm25_corpus_tokens = [
            _tokenize(c["text"]) for c in _knowledge_chunks
        ]
        if _knowledge_chunks:
            _bm25_index = BM25Okapi(_bm25_corpus_tokens)

    logger.info(
        "Loaded %s knowledge chunks.",
        len(_knowledge_chunks),
    )

    return True


def retrieve_hybrid(
    query: str,
    top_k: Optional[int] = None,
    source_type: Optional[str] = None,
) -> str:
    """
    Three-stage retrieval: FAISS + BM25 merge -> cross-encoder rerank.

    Returns formatted context string (backward compatible with
    the old retrieve_context signature).
    """
    if (
        _embedding_model is None
        or _faiss_index is None
        or not _knowledge_chunks
    ):
        return ""

    if top_k is None:
        top_k = HYBRID_STYLE_TOP_K

    candidate_k = min(
        HYBRID_CANDIDATE_K,
        len(_knowledge_chunks),
    )

    # --- Stage 1: FAISS (semantic) ---
    query_embedding = _embedding_model.encode(
        [query],
        normalize_embeddings=True,
    )
    query_embedding = np.asarray(
        query_embedding, dtype="float32"
    )
    faiss_scores, faiss_indices = _faiss_index.search(
        query_embedding, candidate_k
    )
    faiss_scores = faiss_scores[0]
    faiss_indices = faiss_indices[0]

    # --- Stage 2: BM25 (keyword) ---
    bm25_scores = np.zeros(len(_knowledge_chunks))
    if _bm25_index is not None:
        query_tokens = _tokenize(query)
        raw_bm25 = np.asarray(
            _bm25_index.get_scores(query_tokens)
        )
        bm25_scores = raw_bm25

    # --- Stage 3: Merge + deduplicate ---
    merged: dict[int, float] = {}
    faiss_norm = _normalize_scores(faiss_scores)
    bm25_norm = _normalize_scores(bm25_scores)

    for idx, score in zip(faiss_indices, faiss_norm):
        if idx < 0:
            continue
        merged[idx] = (
            merged.get(idx, 0.0)
            + SEMANTIC_WEIGHT * float(score)
        )

    top_bm25 = np.argsort(bm25_norm)[::-1][:candidate_k]
    for idx in top_bm25:
        if idx < 0 or bm25_norm[idx] <= 0:
            continue
        merged[idx] = (
            merged.get(idx, 0.0)
            + BM25_WEIGHT * float(bm25_norm[idx])
        )

    if source_type:
        merged = {
            idx: s for idx, s in merged.items()
            if _knowledge_chunks[idx]["source_type"] == source_type
        }

    if not merged:
        return ""

    sorted_candidates = sorted(
        merged.items(), key=lambda x: -x[1]
    )[: min(top_k * 3, len(merged))]

    candidate_texts = [
        _knowledge_chunks[idx]["text"]
        for idx, _ in sorted_candidates
    ]
    candidate_indices = [idx for idx, _ in sorted_candidates]

    # --- Stage 4: Cross-encoder rerank ---
    reranker = _get_reranker()
    pairs = [(query, text) for text in candidate_texts]
    rerank_scores = reranker.predict(pairs)

    reranked = sorted(
        zip(candidate_indices, rerank_scores),
        key=lambda x: -float(x[1]),
    )[:top_k]

    results: list[str] = []
    for idx, rerank_score in reranked:
        chunk = _knowledge_chunks[idx]
        results.append(
            "\n".join(
                [
                    "--- REFERENCE ---",
                    f"Title: {chunk['title']}",
                    f"URL: {chunk.get('url', '')}",
                    f"Relevance: {float(rerank_score):.3f}",
                    f"Content: {chunk['text']}",
                ]
            )
        )

    return "\n\n".join(results)


def retrieve_context(
    query: str,
    top_k: int = 5,
    source_type: Optional[str] = None,
) -> str:
    """
    Backward-compatible wrapper. Uses hybrid retrieval
    with appropriate defaults per source_type.
    """
    if source_type == "style":
        k = HYBRID_STYLE_TOP_K
    elif source_type == "fact" or source_type == "article":
        k = HYBRID_FACT_TOP_K
    else:
        k = top_k

    return retrieve_hybrid(
        query=query,
        top_k=k,
        source_type=source_type,
    )
