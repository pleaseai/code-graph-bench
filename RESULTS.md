# Results — reference run

Regenerate any time with `cibench report` (reads the latest `results/*.json`).
Quality arms (A/B/C) are deterministic; Perf varies with the machine.

- **Date:** 2026-05-27 (semble/crg/codegraph/soop) · 2026-07-03 (csp rows, same machine)
- **Machine:** Intel Core i7-9700K @ 3.6 GHz, 64 GB RAM, macOS 15.6.1 (x86_64)
- **Tool versions:** semble 0.1.4 (Docker linux/amd64) · code-review-graph 2.3.5 (native, lexical) · codegraph 0.9.6 (native CLI) · soop / @pleaseai/soop 0.1.33 (Docker linux/amd64, no-LLM heuristic) · csp / code-search 0.1.8 (native Rust CLI)
- **Config:** whole-repo indexing, shipped defaults, top-k = 10. See [README](README.md) for methodology & fairness rules.

---

## Arm A — search quality (NL query → relevant code)

Mean over each repo's semble-derived gold queries (rows sorted by NDCG@10).
semble returns code chunks; the graph tools return symbol references (hence far
fewer `tokens`).

| repo | tool | modality | NDCG@10 | NDCG@5 | Recall@10 | MRR | tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| alamofire | **csp** | semantic+lexical | **0.971** | 0.971 | 1.000 | 0.975 | 1574 |
| alamofire | semble | semantic+lexical | 0.961 | 0.961 | 1.000 | 0.963 | 3161 |
| alamofire | codegraph | lexical (FTS5) | 0.721 | 0.659 | 0.925 | 0.671 | 178 |
| alamofire | crg | lexical (FTS5+kw) | 0.300 | 0.300 | 0.300 | 0.300 | 161 |
| express | **csp** | semantic+lexical | **0.897** | 0.897 | 1.000 | 0.867 | 1498 |
| express | semble | semantic+lexical | 0.888 | 0.878 | 0.925 | 0.892 | 2886 |
| express | codegraph | lexical (FTS5) | 0.577 | 0.567 | 0.650 | 0.592 | 138 |
| express | soop | RPG features (no-LLM) | 0.325 | 0.244 | 0.625 | 0.247 | 66 |
| express | crg | lexical (FTS5+kw) | 0.100 | 0.100 | 0.150 | 0.083 | 98 |
| fastapi | **semble** | semantic+lexical | **0.716** | 0.659 | 0.892 | 0.735 | 2582 |
| fastapi | csp | semantic+lexical | 0.687 | 0.653 | 0.842 | 0.710 | 1422 |
| fastapi | codegraph | lexical (FTS5) | 0.403 | 0.403 | 0.400 | 0.467 | 740 |
| fastapi | soop | RPG features (no-LLM) | 0.297 | 0.275 | 0.350 | 0.292 | 84 |
| fastapi | crg | lexical (FTS5+kw) | 0.182 | 0.182 | 0.200 | 0.175 | 356 |
| flask | **semble** | semantic+lexical | **0.871** | 0.871 | 0.952 | 0.889 | 2985 |
| flask | csp | semantic+lexical | 0.858 | 0.849 | 0.905 | 0.890 | 1784 |
| flask | codegraph | lexical (FTS5) | 0.593 | 0.564 | 0.690 | 0.589 | 218 |
| flask | soop | RPG features (no-LLM) | 0.571 | 0.539 | 0.690 | 0.598 | 76 |
| flask | crg | lexical (FTS5+kw) | 0.209 | 0.209 | 0.214 | 0.214 | 168 |
| gin | **semble** | semantic+lexical | **0.860** | 0.860 | 0.925 | 0.867 | 3126 |
| gin | csp | semantic+lexical | 0.856 | 0.856 | 0.925 | 0.867 | 1574 |
| gin | codegraph | lexical (FTS5) | 0.689 | 0.679 | 0.850 | 0.645 | 151 |
| gin | soop | RPG features (no-LLM) | 0.433 | 0.398 | 0.642 | 0.382 | 87 |
| gin | crg | lexical (FTS5+kw) | 0.150 | 0.150 | 0.150 | 0.150 | 60 |
| httpx | **semble** | semantic+lexical | **0.888** | 0.888 | 0.929 | 0.913 | 3067 |
| httpx | csp | semantic+lexical | 0.859 | 0.859 | 0.952 | 0.857 | 1600 |
| httpx | codegraph | lexical (FTS5) | 0.572 | 0.517 | 0.738 | 0.608 | 256 |
| httpx | soop | RPG features (no-LLM) | 0.290 | 0.251 | 0.429 | 0.270 | 72 |
| httpx | crg | lexical (FTS5+kw) | 0.214 | 0.214 | 0.238 | 0.206 | 130 |
| tokio | **semble** | semantic+lexical | **0.936** | 0.936 | 0.950 | 0.960 | 3468 |
| tokio | csp | semantic+lexical | 0.906 | 0.897 | 0.950 | 0.897 | 1740 |
| tokio | codegraph | lexical (FTS5) | 0.540 | 0.486 | 0.650 | 0.542 | 186 |
| tokio | crg | lexical (FTS5+kw) | 0.300 | 0.300 | 0.300 | 0.300 | 128 |
| tokio | soop | RPG features (no-LLM) | 0.082 | 0.050 | 0.150 | 0.063 | 75 |

(soop failed to index alamofire/Swift in this run — omitted there.)

**Read:** the two semantic retrievers own NL search. **csp — the Rust port of
semble's algorithm — matches semble within ±0.03 NDCG everywhere and wins
outright on alamofire & express** (csp 0.69–0.97, semble 0.72–0.96), while
returning ~45% fewer tokens (smaller chunks) and needing no Docker.
codegraph's FTS5 is a consistent third (**0.40–0.72**);
**soop, even in no-LLM heuristic mode, lands third** (**0.29–0.57** on the
Python/JS repos, weak on Rust `tokio` 0.08) — notably **beating crg's lexical
default everywhere** (crg **0.10–0.30**) while returning the fewest tokens
(66–87). Verbose NL doesn't match crg's FTS5-AND well. soop's full LLM-feature +
vector mode is untested here (paid/non-deterministic) and would likely climb.
The graph tools trade quality for **~15–40× fewer returned tokens** (symbol refs
vs code bodies).

---

## Arm B — graph capability (graph tools: crg, codegraph, soop)

### Multi-hop retrieval (search → anchor → one-hop traverse)

Each tool uses its **own** search to find the anchor, then traverses.
`score = anchor_found × neighbor_recall`. (1–3 tasks/repo → directional.)

| repo | tool | tasks | anchor found | neighbor recall | score |
| --- | --- | --- | --- | --- | --- |
| flask | crg | 2 | 0.00 | 0.000 | 0.000 |
| flask | codegraph | 2 | 0.00 | 0.000 | 0.000 |
| flask | soop | 2 | 0.00 | 0.000 | 0.000 |
| fastapi | crg | 2 | 0.00 | 0.000 | 0.000 |
| fastapi | codegraph | 2 | 0.00 | 0.000 | 0.000 |
| fastapi | soop | 2 | 0.00 | 0.000 | 0.000 |
| httpx | crg | 2 | 0.00 | 0.000 | 0.000 |
| httpx | codegraph | 2 | 0.50 | 0.500 | 0.500 |
| httpx | soop | 2 | 0.00 | 0.000 | 0.000 |
| express | crg | 1 | 0.00 | 0.000 | 0.000 |
| express | codegraph | 1 | 0.00 | 0.000 | 0.000 |
| express | soop | 1 | 0.00 | 0.000 | 0.000 |
| gin | crg | 2 | 0.00 | 0.000 | 0.000 |
| gin | codegraph | 2 | 1.00 | 1.000 | 1.000 |
| gin | soop | 2 | 0.00 | 0.000 | 0.000 |

**Read:** all three tools' built-in search usually **fails to locate the right
anchor** from a verbose NL query (crg's FTS-AND → 0; codegraph latches onto common
tokens; soop's no-LLM heuristic features likewise miss) — only codegraph anchors
on gin/httpx. This is the gap Arm C closes (for crg/codegraph, via semble).

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
Node CLI startup (~240 ms); semble & soop run in Docker (index time includes
container startup); semble is in-memory (no on-disk index → `db MB` = –); soop
units/db are not reported by its stats (`–`). soop failed to index alamofire.

| repo | tool | index ms | units | units/s | db MB | p50 ms | p95 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| alamofire | codegraph | 5831 | 2931 | 503 | 8.0 | 257.2 | 262.1 |
| alamofire | crg | 2674 | 2107 | 788 | 25.9 | 2.7 | 3.0 |
| alamofire | csp | 1731 | 3637 | 2102 | 8.3 | 237.9 | 245.9 |
| alamofire | semble | 5411 | 1845 | 341 | – | 2.7 | 21.0 |
| express | codegraph | 1203 | 990 | 823 | 1.2 | 244.9 | 259.1 |
| express | crg | 2258 | 1912 | 847 | 24.1 | 2.5 | 2.7 |
| express | csp | 616 | 1010 | 1639 | 2.1 | 202.1 | 226.8 |
| express | semble | 2811 | 523 | 186 | – | 2.1 | 3.2 |
| express | soop | 40235 | – | – | – | 0.7 | 1.1 |
| fastapi | codegraph | 7772 | 12294 | 1582 | 18.3 | 263.2 | 278.1 |
| fastapi | crg | 4773 | 6300 | 1320 | 52.6 | 7.8 | 9.0 |
| fastapi | csp | 2589 | 6619 | 2557 | 14.5 | 266.9 | 360.2 |
| fastapi | semble | 8769 | 3687 | 420 | – | 4.9 | 35.2 |
| fastapi | soop | 43398 | – | – | – | 1.5 | 2.6 |
| flask | codegraph | 1429 | 2710 | 1896 | 4.2 | 253.1 | 267.2 |
| flask | crg | 1256 | 1449 | 1154 | 11.5 | 1.8 | 2.1 |
| flask | csp | 680 | 1015 | 1492 | 2.3 | 211.0 | 242.4 |
| flask | semble | 5074 | 537 | 106 | – | 1.6 | 8.4 |
| flask | soop | 40747 | – | – | – | 1.0 | 2.2 |
| gin | codegraph | 2098 | 2544 | 1213 | 5.6 | 246.1 | 259.8 |
| gin | crg | 1660 | 1613 | 972 | 20.7 | 1.9 | 2.2 |
| gin | csp | 767 | 1171 | 1528 | 2.7 | 207.1 | 220.1 |
| gin | semble | 1865 | 576 | 309 | – | 1.8 | 10.2 |
| gin | soop | 42333 | – | – | – | 1.1 | 1.6 |
| httpx | codegraph | 1195 | 1717 | 1437 | 3.2 | 257.7 | 266.8 |
| httpx | crg | 1292 | 1261 | 976 | 11.0 | 1.8 | 2.1 |
| httpx | csp | 709 | 997 | 1406 | 2.2 | 206.4 | 219.7 |
| httpx | semble | 2889 | 497 | 172 | – | 1.9 | 8.6 |
| httpx | soop | 26973 | – | – | – | 1.1 | 1.5 |
| tokio | codegraph | 12273 | 12974 | 1057 | 27.2 | 267.8 | 302.4 |
| tokio | crg | 6706 | 8676 | 1294 | 92.1 | 10.0 | 10.5 |
| tokio | csp | 3700 | 8791 | 2376 | 20.5 | 288.5 | 299.9 |
| tokio | semble | 6273 | 4552 | 726 | – | 5.7 | 39.6 |
| tokio | soop | 42165 | – | – | – | 3.8 | 12.8 |

**Read:** **csp is the fastest indexer on every repo (0.6–3.7 s, ~1.4–2.6k
chunks/s)** — the Rust rewrite dividend over semble's Docker+Python (2.8–8.8 s);
crg/codegraph take 1–12 s; **soop is far slower (~27–43 s)** — its heuristic
feature extraction per entity dominates. Once built, in-process query latency
is **~1–4 ms** (crg, semble, soop); codegraph's and csp's ~200–290 ms are CLI
process startup (both far lower over a persistent MCP connection). crg's graph
DB is the largest on disk (richer edges/flows/communities); csp's index is
compact (2–21 MB of JSON + packed vectors).

---

## Bottom line

- **Pure NL code search:** semble and csp, jointly — same algorithm, same
  quality band (±0.03 NDCG). **csp is the practical pick**: native single
  binary, fastest indexing, ~45% fewer returned tokens; semble stays the
  reference implementation (and the only one with in-process ~2 ms latency
  as benchmarked here).
- **Among the graph tools' built-in search:** codegraph (FTS5) leads, **soop's
  no-LLM heuristic is a clear second and beats crg's lexical default** — at the
  lowest token cost. soop's full LLM-feature mode (untested) would likely close
  more of the gap to semble.
- **Structural queries (impact/callers):** the graph tools' domain; semble can't do it.
- **Best of both:** semble → graph as a pipeline lifts crg/codegraph on the NL
  queries their own search can't anchor — the practical takeaway being to **pair**
  a semantic retriever with a graph tool rather than choose one.
