# code-graph-bench

An independent, **apples-to-apples** benchmark for three code-intelligence tools
built to cut an AI agent's code-exploration token cost:

| Tool | Lang | What it is | Search modality |
|---|---|---|---|
| [**semble**](https://github.com/MinishLab/semble) | Python | Code **search** library (chunks) | semantic + lexical (static embeddings + BM25 + RRF) |
| [**code-review-graph**](https://github.com/tirth8205/code-review-graph) (crg) | Python | Code **graph** for review / blast-radius | lexical (FTS5 + keyword) by default |
| [**codegraph**](https://github.com/colbymchenry/codegraph) | TypeScript | Code **knowledge graph** for agents | lexical (FTS5) |

Each project benchmarks itself, its own way, on its own data — so the headline
numbers (semble NDCG@10 0.854 · crg 38–528× token reduction & 100% impact recall ·
codegraph 57% fewer tokens) **cannot be put in one table**. This repo measures all
three on the **same corpus, same gold set, same harness**.

## What it answers

The three tools overlap only partially. semble is a pure semantic **retriever**;
the two graph tools add **structural** queries (callers/callees/impact/trace) that
semble has no notion of. So we measure along separate, honest axes — and one of
them tests whether **semble + a graph tool** beats either alone:

| Arm | Tools | Question | Cost |
|---|---|---|---|
| **A. Search** | semble, crg, codegraph | NL query → relevant code? | free / deterministic |
| **B. Graph** | crg, codegraph | blast-radius & multi-hop accuracy? | free / deterministic |
| **C. Combined** | semble→crg, semble→codegraph | does semble as anchor-finder help the graph tools? | free / deterministic |
| **D. Agent E2E** *(opt-in)* | all + no-tool | real agent tokens/cost/time/tool-calls? | **paid** (Claude API) |
| **Perf** *(cross-cutting)* | all | index time, query latency, footprint | free |

## Headline findings (this corpus)

- **Search (Arm A).** semble's semantic retrieval dominates NL queries
  (NDCG@10 **0.72–0.94** across 7 repos); codegraph's FTS5 is a solid second
  (**0.40–0.69**); crg's default lexical search is weakest on verbose NL
  (**0.15–0.30**). The graph tools return **far fewer tokens** per query
  (60–740 vs semble's ~2,500–3,500) because they return symbol references, not
  code bodies.
- **Graph (Arm B).** crg reproduces its **~100% impact recall** claim
  (blast-radius). But both graph tools' *built-in* search fails to locate the
  right **anchor** from a verbose NL query (crg's FTS-AND → 0 hits; codegraph
  latches onto common tokens like "Flask").
- **Combined (Arm C) — the point of this benchmark.** Using semble to localize
  the query, then letting the graph tool resolve the symbol there and traverse,
  **fixes the anchor problem where it was broken** (flask & express: anchor-found
  0.00 → 1.00, neighbor-recall up to 0.00 → 1.00) — but can **regress** where the
  graph tool's own search already nailed it (gin/httpx codegraph). Net: semble is
  a strong **complement** on hard NL cases, not a universal replacement.

> Full tables (all arms, with per-repo numbers and interpretation) are in
> [**RESULTS.md**](RESULTS.md). They come from the committed reference run in
> [`results/`](results/); regenerate with `cgbench report`. Multi-hop tasks are
> few per repo (1–3), so Arm B/C are directional, not precise.

## Corpus & gold set

5 **dual-labeled** core repos — `flask, fastapi, httpx, express, gin` — have **both**
semble retrieval labels and crg graph/impact labels, plus `tokio, alamofire` (Rust/Swift)
for retrieval-only language breadth. See [`bench/corpus.json`](bench/corpus.json).

Gold labels are **reused from upstream** (both MIT, attributed in
[`bench/goldset/SOURCES.md`](bench/goldset/SOURCES.md)):

- **retrieval** (`bench/goldset/retrieval/*.json`) — semble's `{query, relevant,
  secondary, category}` annotations (categories: semantic / architecture / symbol).
- **graph** (`bench/goldset/graph/*.yaml`) — crg's `test_commits` (git-derived
  blast-radius), `multi_hop_tasks`, `search_queries`, `entry_points`.

semble and crg pinned each repo at **different commits**, so each repo is cloned
once per SHA under `checkouts/<repo>@<sha>/`; each gold set is only evaluated on
its own snapshot.

## How tools are run (and why it's fair)

All three index the **whole repo root** (same input), so hit paths are
repo-root-relative and directly comparable. Tools run in their **shipped default
mode**, not tuned. Because two tools have x86_64-macOS wheel gaps, runtimes differ:

- **semble** → **Docker (linux/amd64)**. semble needs `tree-sitter-language-pack
  <1.8.0`, which has **no x86_64-macOS wheel or sdist**, so it can't run natively
  on Intel Macs. The image ([`docker/semble.Dockerfile`](docker/semble.Dockerfile))
  pins the correct wheel and bakes the embedding model in (offline). Its index
  time includes container startup.
- **crg** → **native** isolated venv (`.venv-crg`), **lexical** mode. This is
  faithful to crg's *own* eval (`build → post-process → hybrid_search`, **no
  embeddings**), which is also offline and avoids the torch x86_64-mac gap.
- **codegraph** → **native** CLI (bundled Node). FTS5-only by design. Its query
  latency is measured as **CLI wall time, so it includes Node startup** (~240 ms)
  — unlike semble/crg's in-process latency. Flagged in Perf; quality metrics
  unaffected.

Every tool is reached through one uniform adapter interface
([`bench/adapters/base.py`](bench/adapters/base.py)) that returns normalized
`Hit`s, so the metric/matching code is identical across tools.

## Metrics

Ported verbatim from the upstream tools so numbers stay comparable to their
self-reports: **NDCG@k / Recall@k / MRR** from semble
([`bench/metrics.py`](bench/metrics.py)), **precision/recall/F1** from crg's
`scorer`, multi-hop `score = anchor_found × neighbor_recall` from crg. Returned
**tokens** = payload chars ÷ 4 (semble: code body; graph tools: symbol reference).
Hit↔target matching ([`bench/matching.py`](bench/matching.py)) is path + line-span
overlap + symbol name.

## Setup

```bash
# harness (orchestrator only)
uv venv && uv pip install -e ".[dev]"

# isolated tool runtimes
uv venv .venv-crg     --python 3.13 && uv pip install --python .venv-crg "code-review-graph"
npm i -g @colbymchenry/codegraph
docker build --platform linux/amd64 -f docker/semble.Dockerfile -t cgbench-semble:latest .

cgbench goldset          # validate the gold set
cgbench fetch            # clone pinned snapshots into checkouts/
```

## Run

```bash
cgbench run a            # Arm A — search quality (all repos / tools)
cgbench run b            # Arm B — graph: multi-hop + impact accuracy
cgbench run c            # Arm C — combined: semble anchor → graph traverse
cgbench run perf         # Perf — index time / latency / footprint
cgbench run a --repo flask --tool semble   # filter repo / tool

cgbench report           # render latest results/*.json as markdown tables

# Arm D is opt-in and spends Claude API credits:
cgbench run d --confirm --budget 2 --model sonnet
```

## Reproducibility

Pinned SHAs + CPU-only embeddings + cold-index-once + median-of-N query latency
make Arm A/B/C **deterministic** (re-running yields identical quality numbers).
Perf varies run to run; record your machine (CPU/RAM/OS) alongside results. The
reference run in `results/` was produced on x86_64 macOS 15.

## Limitations & roadmap

- **crg semantic mode.** crg *can* use embeddings (`[embeddings]`, local
  all-MiniLM-L6-v2) but that needs torch, which has no x86_64-mac/py3.13 wheel.
  A `cgbench-crg` Docker image (linux/amd64, embeddings) would let crg's NL
  retrieval compete fairly — currently crg is reported in its lexical default.
- **Multi-hop sample size** is small (1–3 tasks/repo); treat Arm B/C as directional.
- **Perf** does not yet capture peak RSS or incremental-update time.
- **codegraph latency** includes Node process startup (CLI), not in-process.
- **Arm D** (live agent A/B) is implemented but unrun here (costs money); semble's
  MCP-in-Docker entrypoint is a TODO.

## Attribution

Gold-set labels © their projects (MinishLab/semble, tirth8205/code-review-graph),
both MIT, redistributed with attribution. Harness code MIT.
