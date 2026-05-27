# Gold-set sources & attribution

All gold-set labels are **redistributed from upstream projects, both MIT-licensed.**
They are copied verbatim (then loaded through `bench/goldset/schema.py`) so that
this benchmark stays reproducible even if upstream changes.

## `retrieval/<repo>.json` — search relevance labels

- **Source:** [MinishLab/semble](https://github.com/MinishLab/semble) — `benchmarks/annotations/<repo>.json`
- **License:** MIT
- **Format:** `[{ "query", "relevant": [path...], "secondary": [path...], "category" }]`
  where `category ∈ {semantic, architecture, symbol}`.
- **Pinned to:** the `revision` recorded in semble's `benchmarks/repos.json` for each
  repo (see `bench/corpus.json` → `retrieval.sha`). Labels are file-path-level.

## `graph/<repo>.yaml` — impact / multi-hop / search labels

- **Source:** [tirth8205/code-review-graph](https://github.com/tirth8205/code-review-graph) — `code_review_graph/eval/configs/<repo>.yaml`
- **License:** MIT
- **Contains:** `test_commits` (git-derived blast-radius ground truth),
  `search_queries` (query → expected qualified name), `multi_hop_tasks`
  (NL query → anchor + expected graph neighbors), `entry_points`.
- **Pinned to:** the config's `commit` field (see `bench/corpus.json` → `graph.sha`).

## Why two SHAs per repo

semble and code-review-graph pinned each repo at **different commits**, so the
retrieval snapshot and the graph snapshot are cloned separately under
`checkouts/<repo>@<sha>/`. Each gold-set is only ever evaluated against its own
snapshot.
