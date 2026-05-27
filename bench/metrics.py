"""Retrieval & impact metrics. NDCG/Recall/MRR ported from semble's
``benchmarks/metrics.py``; precision/recall/F1 from code-review-graph's
``eval/scorer.py``.
"""

from __future__ import annotations

import math

from bench.adapters.base import Hit
from bench.goldset.schema import RetrievalTask
from bench.matching import target_rank


def dcg(relevances: list[int]) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))


def ndcg_at_k(relevant_ranks: list[int], n_relevant: int, k: int) -> float:
    """NDCG@k with binary relevance, given 1-based ranks of relevant items."""
    if n_relevant == 0:
        return 0.0
    rels = [0] * k
    for r in relevant_ranks:
        if 1 <= r <= k:
            rels[r - 1] = 1
    ideal = dcg([1] * min(k, n_relevant))
    return dcg(rels) / ideal if ideal > 0 else 0.0


def recall_at_k(relevant_ranks: list[int], n_relevant: int, k: int) -> float:
    if n_relevant == 0:
        return 0.0
    return sum(1 for r in relevant_ranks if 1 <= r <= k) / n_relevant


def mrr(relevant_ranks: list[int]) -> float:
    ranks = [r for r in relevant_ranks if r and r > 0]
    return 1.0 / min(ranks) if ranks else 0.0


def evaluate_query(task: RetrievalTask, hits: list[Hit], ks=(5, 10)) -> dict:
    """Per-query retrieval metrics for one tool's hits."""
    targets = task.all_relevant
    ranks = [r for t in targets if (r := target_rank(hits, t)) is not None]
    n_rel = len(targets)
    out = {
        "query": task.query,
        "category": task.category,
        "n_relevant": n_rel,
        "mrr": mrr(ranks),
        "tokens": sum(h.n_chars for h in hits[: max(ks)]) / 4.0,
    }
    for k in ks:
        out[f"ndcg@{k}"] = ndcg_at_k(ranks, n_rel, k)
        out[f"recall@{k}"] = recall_at_k(ranks, n_rel, k)
    return out


# --------------------------------------------------------------------------- #
# Impact metrics (Arm B)
# --------------------------------------------------------------------------- #
def precision_recall_f1(predicted: set[str], actual: set[str]) -> dict:
    tp = len(predicted & actual)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(actual) if actual else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "predicted": len(predicted), "actual": len(actual), "tp": tp,
        "precision": precision, "recall": recall, "f1": f1,
    }
