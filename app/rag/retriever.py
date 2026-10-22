"""
app/rag/retriever.py
Retrieval step of the RAG pipeline.

Embeds the user query → searches ChromaDB → re-ranks by MMR
(Maximal Marginal Relevance) to reduce redundancy.

Public API:
    retrieve(query, project_id, top_k, filters, mmr_lambda) -> list[SearchResult]
"""
from __future__ import annotations

import numpy as np
from loguru import logger

from app.rag.embedder import get_embedder
from app.rag.vector_store import SearchResult, query as vs_query


def retrieve(
    question: str,
    project_id: int,
    top_k: int = 5,
    fetch_k: int = 20,
    filters: dict | None = None,
    mmr_lambda: float = 0.6,
) -> list[SearchResult]:
    """
    Retrieve top-k chunks most relevant to `question` within `project_id`.

    Steps
    -----
    1. Embed the question with the local embedding model
    2. Fetch `fetch_k` candidates from ChromaDB
    3. Re-rank with MMR to balance relevance vs diversity
    4. Return the top_k results

    Parameters
    ----------
    question    : natural language question
    project_id  : restrict retrieval to this project's collection
    top_k       : number of final results to return
    fetch_k     : candidate pool size before MMR (should be >> top_k)
    filters     : optional ChromaDB metadata filter dict
    mmr_lambda  : MMR trade-off: 1.0 = pure relevance, 0.0 = pure diversity

    Returns
    -------
    list[SearchResult] — length ≤ top_k, ordered by MMR score
    """
    embedder = get_embedder()
    query_vec = embedder.embed_query(question)

    # Fetch candidates from vector store
    candidates = vs_query(
        project_id=project_id,
        query_vector=query_vec,
        top_k=fetch_k,
        filters=filters,
    )

    if not candidates:
        logger.warning("No candidates found for project {} query", project_id)
        return []

    if len(candidates) <= top_k:
        return candidates

    # ── MMR re-ranking ────────────────────────────────────────────────────────
    return _mmr_rerank(query_vec, candidates, top_k, mmr_lambda)


def _mmr_rerank(
    query_vec: list[float],
    candidates: list[SearchResult],
    top_k: int,
    lambda_: float,
) -> list[SearchResult]:
    """
    Maximal Marginal Relevance re-ranking.

    Balances relevance (similarity to query) against diversity
    (dissimilarity to already-selected chunks).
    """
    if not candidates:
        return []

    q = np.array(query_vec, dtype=np.float32)
    # Embed candidate texts (we use distances as proxies; convert to similarities)
    # Chroma returns cosine *distance* in [0, 2]; convert to similarity [−1, 1]
    sims_to_query = [1.0 - r.score for r in candidates]

    selected_indices: list[int] = []
    remaining = list(range(len(candidates)))

    while len(selected_indices) < top_k and remaining:
        if not selected_indices:
            # Pick most relevant first
            best = max(remaining, key=lambda i: sims_to_query[i])
        else:
            # MMR: balance relevance vs similarity to already-selected
            def mmr_score(i: int) -> float:
                rel = sims_to_query[i]
                # Max similarity to any already-selected candidate
                max_sim = max(
                    _text_overlap(candidates[i].text, candidates[j].text)
                    for j in selected_indices
                )
                return lambda_ * rel - (1 - lambda_) * max_sim

            best = max(remaining, key=mmr_score)

        selected_indices.append(best)
        remaining.remove(best)

    return [candidates[i] for i in selected_indices]


def _text_overlap(a: str, b: str) -> float:
    """Jaccard overlap of word sets as a cheap diversity proxy."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)
