# Results — reference run

Regenerate any time with `cgbench report` (reads the latest `results/*.json`).
Quality arms (A/B/C) are deterministic; Perf varies with the machine.

- **Date:** 2026-05-27
- **Machine:** Intel Core i7-9700K @ 3.6 GHz, 64 GB RAM, macOS 15.6.1 (x86_64)
- **Tool versions:** semble 0.1.4 (Docker linux/amd64) · code-review-graph 2.3.5 (native, lexical) · codegraph 0.9.6 (native CLI)
- **Config:** whole-repo indexing, shipped defaults, top-k = 10. See [README](README.md) for methodology & fairness rules.

---

## Arm A — search quality (NL query → relevant code)

Mean over each repo's semble-derived gold queries. semble returns code chunks;
crg/codegraph return symbol references (hence far fewer `tokens`).

| repo | tool | modality | NDCG@10 | NDCG@5 | Recall@10 | MRR | tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| alamofire | **semble** | semantic+lexical | **0.961** | 0.961 | 1.000 | 0.963 | 3161 |
| alamofire | codegraph | lexical (FTS5) | 0.721 | 0.659 | 0.925 | 0.671 | 178 |
| alamofire | crg | lexical (FTS5+kw) | 0.300 | 0.300 | 0.300 | 0.300 | 161 |
| express | **semble** | semantic+lexical | **0.888** | 0.878 | 0.925 | 0.892 | 2894 |
| express | codegraph | lexical (FTS5) | 0.577 | 0.567 | 0.650 | 0.592 | 138 |
| express | crg | lexical (FTS5+kw) | 0.100 | 0.100 | 0.150 | 0.083 | 98 |
| fastapi | **semble** | semantic+lexical | **0.716** | 0.659 | 0.892 | 0.735 | 2582 |
| fastapi | codegraph | lexical (FTS5) | 0.403 | 0.403 | 0.400 | 0.467 | 740 |
| fastapi | crg | lexical (FTS5+kw) | 0.182 | 0.182 | 0.200 | 0.175 | 356 |
| flask | **semble** | semantic+lexical | **0.871** | 0.871 | 0.952 | 0.889 | 2985 |
| flask | codegraph | lexical (FTS5) | 0.593 | 0.564 | 0.690 | 0.589 | 218 |
| flask | crg | lexical (FTS5+kw) | 0.209 | 0.209 | 0.214 | 0.214 | 168 |
| gin | **semble** | semantic+lexical | **0.860** | 0.860 | 0.925 | 0.867 | 3126 |
| gin | codegraph | lexical (FTS5) | 0.689 | 0.679 | 0.850 | 0.645 | 151 |
| gin | crg | lexical (FTS5+kw) | 0.150 | 0.150 | 0.150 | 0.150 | 60 |
| httpx | **semble** | semantic+lexical | **0.888** | 0.888 | 0.929 | 0.913 | 3067 |
| httpx | codegraph | lexical (FTS5) | 0.572 | 0.517 | 0.738 | 0.608 | 256 |
| httpx | crg | lexical (FTS5+kw) | 0.214 | 0.214 | 0.238 | 0.206 | 130 |
| tokio | **semble** | semantic+lexical | **0.936** | 0.936 | 0.950 | 0.960 | 3468 |
| tokio | codegraph | lexical (FTS5) | 0.540 | 0.486 | 0.650 | 0.542 | 186 |
| tokio | crg | lexical (FTS5+kw) | 0.300 | 0.300 | 0.300 | 0.300 | 128 |

**Read:** semble's semantic retrieval wins NL search on every repo
(NDCG@10 **0.72–0.96**), codegraph's FTS5 is a consistent second (**0.40–0.72**),
crg's default lexical search trails (**0.10–0.30**) — verbose NL queries don't
match its FTS5-AND well. The graph tools trade quality for **~15–25× fewer
returned tokens** (symbol refs vs code bodies).

---

## Arm B — graph capability (graph tools only)

### Multi-hop retrieval (search → anchor → one-hop traverse)

Each tool uses its **own** search to find the anchor, then traverses.
`score = anchor_found × neighbor_recall`. (1–3 tasks/repo → directional.)

| repo | tool | tasks | anchor found | neighbor recall | score |
| --- | --- | --- | --- | --- | --- |
| flask | crg | 2 | 0.00 | 0.000 | 0.000 |
| flask | codegraph | 2 | 0.00 | 0.000 | 0.000 |
| fastapi | crg | 2 | 0.00 | 0.000 | 0.000 |
| fastapi | codegraph | 2 | 0.00 | 0.000 | 0.000 |
| httpx | crg | 2 | 0.00 | 0.000 | 0.000 |
| httpx | codegraph | 2 | 0.50 | 0.500 | 0.500 |
| express | crg | 1 | 0.00 | 0.000 | 0.000 |
| express | codegraph | 1 | 0.00 | 0.000 | 0.000 |
| gin | crg | 2 | 0.00 | 0.000 | 0.000 |
| gin | codegraph | 2 | 1.00 | 1.000 | 1.000 |

**Read:** both tools' built-in lexical search usually **fails to locate the right
anchor** from a verbose NL query (crg's FTS-AND → 0; codegraph latches onto common
tokens). This is the gap Arm C closes.

### Impact accuracy (blast-radius, crg methodology)

| repo | tool | commit | predicted | actual | P | R | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| flask | crg | fbb6f0bc | 27 | 10 | 0.37 | 1.00 | 0.54 |
| flask | crg | a29f88ce | 4 | 4 | 1.00 | 1.00 | 1.00 |
| fastapi | crg | fa3588c3 | 1 | 2 | 1.00 | 0.50 | 0.67 |
| fastapi | crg | 0227991a | 1 | 1 | 1.00 | 1.00 | 1.00 |
| httpx | crg | ae1b9f66 | 3 | 35 | 1.00 | 0.09 | 0.16 |
| httpx | crg | b55d4635 | 4 | 4 | 1.00 | 1.00 | 1.00 |
| express | crg | 925a1dff | 2 | 1 | 0.50 | 1.00 | 0.67 |
| express | crg | b4ab7d65 | 1 | 1 | 1.00 | 1.00 | 1.00 |
| gin | crg | 052d1a79 | 10 | 5 | 0.50 | 1.00 | 0.67 |
| gin | crg | 472d086a | 5 | 2 | 0.40 | 1.00 | 0.57 |
| gin | crg | 5c00df8a | 2 | 2 | 1.00 | 1.00 | 1.00 |

**Read:** reproduces crg's pattern — **recall ≈ 1.0** (over-predicts to never miss
an affected file), precision lower on multi-file commits. The one outlier
(httpx ae1b9f66, R=0.09) is a 35-file ground-truth commit where crg under-predicted.

---

## Arm C — combined (semble anchor → graph traverse)

`baseline` = the graph tool's own pipeline (= Arm B); `combined` = semble localizes
the query, the graph tool resolves the symbol there (via its own index) and traverses.

| repo | graph tool | anchor found B→C | neighbor recall B→C | Δ found | Δ recall |
| --- | --- | --- | --- | --- | --- |
| flask | crg | 0.00 → **1.00** | 0.000 → **1.000** | +1.00 | +1.000 |
| flask | codegraph | 0.00 → **1.00** | 0.000 → **1.000** | +1.00 | +1.000 |
| fastapi | crg | 0.00 → 0.00 | 0.000 → 0.000 | +0.00 | +0.000 |
| fastapi | codegraph | 0.00 → 0.00 | 0.000 → **0.500** | +0.00 | +0.500 |
| httpx | crg | 0.00 → 0.00 | 0.000 → 0.000 | +0.00 | +0.000 |
| httpx | codegraph | 0.50 → 0.00 | 0.500 → 0.000 | **-0.50** | **-0.500** |
| express | crg | 0.00 → **1.00** | 0.000 → 0.000 | +1.00 | +0.000 |
| express | codegraph | 0.00 → **1.00** | 0.000 → **0.333** | +1.00 | +0.333 |
| gin | crg | 0.00 → **0.50** | 0.000 → 0.000 | +0.50 | +0.000 |
| gin | codegraph | 1.00 → 0.50 | 1.000 → 0.500 | **-0.50** | **-0.500** |

**Read — the central result.** Where the graph tool's own search *failed*
(flask, express, gin/crg), semble as anchor-finder **recovers anchor discovery**
(several 0.00 → 1.00). Where it *already worked* (gin & httpx for codegraph),
semble's chunk-granularity localization can be **less precise and regress**.
So semble is a strong **complement on hard NL queries**, not a blanket upgrade.
(express/crg: anchor found but crg's `callers_of` on the resolved node didn't
return the curated neighbor — a traversal-naming detail.)

---

## Perf — speed & footprint

Cold index time, query latency, index size. **Caveats:** codegraph p50 includes
Node CLI startup (~240 ms); semble runs in Docker (index time includes container
startup); semble is in-memory (no on-disk index → `db MB` = –).

| repo | tool | index ms | units | units/s | db MB | p50 ms | p95 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| alamofire | codegraph | 5573 | 2931 | 526 | 8.0 | 245.3 | 252.3 |
| alamofire | crg | 2148 | 2107 | 981 | 25.9 | 2.7 | 3.0 |
| alamofire | semble | 5163 | 1845 | 357 | – | 3.7 | 25.0 |
| express | codegraph | 964 | 990 | 1027 | 1.2 | 241.3 | 266.7 |
| express | crg | 2038 | 1912 | 938 | 24.1 | 2.4 | 2.9 |
| express | semble | 2991 | 523 | 175 | – | 2.2 | 3.7 |
| fastapi | codegraph | 7524 | 12294 | 1634 | 18.3 | 265.8 | 299.4 |
| fastapi | crg | 4735 | 6300 | 1330 | 52.6 | 7.8 | 8.7 |
| fastapi | semble | 7432 | 3687 | 496 | – | 11.8 | 63.6 |
| flask | codegraph | 1373 | 2710 | 1973 | 4.2 | 240.5 | 253.9 |
| flask | crg | 1358 | 1449 | 1067 | 11.5 | 1.8 | 2.0 |
| flask | semble | 4204 | 537 | 128 | – | 1.8 | 8.4 |
| gin | codegraph | 1720 | 2544 | 1479 | 5.6 | 239.9 | 251.5 |
| gin | crg | 1648 | 1613 | 979 | 20.7 | 2.1 | 2.3 |
| gin | semble | 1843 | 576 | 312 | – | 1.6 | 10.2 |
| httpx | codegraph | 1449 | 1717 | 1185 | 3.2 | 249.7 | 271.0 |
| httpx | crg | 1294 | 1261 | 975 | 11.0 | 1.8 | 2.1 |
| httpx | semble | 2858 | 497 | 174 | – | 1.9 | 9.0 |
| tokio | codegraph | 11949 | 12974 | 1086 | 27.2 | 261.8 | 270.6 |
| tokio | crg | 7037 | 8676 | 1233 | 92.1 | 9.5 | 10.1 |
| tokio | semble | 6170 | 4552 | 738 | – | 5.6 | 36.2 |

**Read:** all three index a repo in **1–12 s**. In-process query latency is
**~2 ms** (crg) and **~2–12 ms** (semble); codegraph's ~240 ms is dominated by CLI
process startup (it would be far lower over a persistent MCP connection). crg's
graph DB is the largest on disk (richer edges/flows/communities).

---

## Bottom line

- **Pure NL code search:** semble, clearly. Best NDCG@10 everywhere.
- **Structural queries (impact/callers):** the graph tools' domain; semble can't do it.
- **Best of both:** semble → graph as a pipeline lifts the graph tools on the NL
  queries their own search can't anchor — the practical takeaway being to **pair**
  a semantic retriever with a graph tool rather than choose one.
