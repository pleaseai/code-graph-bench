#!/usr/bin/env node
/**
 * Standalone soop (RPG) worker — run with Node (NOT Bun).
 *
 * soop's SQLite layer uses better-sqlite3 under Node and bun:sqlite under Bun,
 * but its SemanticCache hard-requires better-sqlite3 (unsupported by Bun). So we
 * run under Node, where the bundled better-sqlite3 native addon loads, and keep
 * the cache (pointed at a writable /tmp dir so the repo mount can stay read-only).
 *
 * soop runs in free / deterministic / offline mode: RPGEncoder with
 * `semantic.useLLM = false` (heuristic features, no LLM/API) — soop's "no-LLM
 * floor", analogous to running crg lexically, not its full LLM-feature mode.
 *
 * Imports the published `@pleaseai/soop` (SOOP_IMPORT to override).
 * Runs in a linux/amd64 container (soop's native tree-sitter backend has no
 * x86_64-macOS build).
 *
 * Stdin: JSON job. Stdout: JSON result.
 *   {op:"search",  repo_path, queries[], k, runs}
 *   {op:"multihop", repo_path, tasks:[...]}
 *   {op:"combined", repo_path, tasks:[...], anchor_hits:{task_id:[{file,start_line,end_line}]}}
 */

import { readFileSync } from "node:fs";
import { performance } from "node:perf_hooks";

const SOOP_IMPORT = process.env.SOOP_IMPORT ?? "@pleaseai/soop";
const CACHE_DIR = process.env.SOOP_CACHE_DIR ?? "/tmp/rpgcache";

const INCLUDE = [
  "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx", "**/*.py",
  "**/*.go", "**/*.rs", "**/*.swift", "**/*.java", "**/*.rb",
];

// soop logs to stdout and ignores setLogLevel here, so we frame our payload
// with a sentinel the adapter splits on.
const SENTINEL = "__CGBENCH_JSON__";
function emit(obj) {
  process.stdout.write("\n" + SENTINEL + JSON.stringify(obj));
}

// RPG node enumeration (rpg.getNodes() is async; ids look like
// "src/flask/sansio/app.py:function:_make_timedelta:52").
async function allNodes(rpg) {
  const nodes = await rpg.getNodes();
  return Array.isArray(nodes) ? nodes : [];
}

function nodeName(n) {
  return String(n.metadata?.name ?? n.name ?? String(n.id).split(":")[2] ?? "");
}

function nodeQualified(n) {
  return String(n.metadata?.qualifiedName ?? n.id ?? "");
}

function nodeToHit(node, rank) {
  const m = node.metadata ?? {};
  return {
    file_path: m.path ?? null,
    start_line: m.startLine ?? null,
    end_line: m.endLine ?? null,
    symbol: m.qualifiedName ?? null,
    name: m.name ?? node.name ?? null,
    score: 1 / (rank + 1),
    n_chars: String((m.qualifiedName ?? "") + " " + (node.feature?.description ?? "")).length,
  };
}

async function main() {
  const job = JSON.parse(readFileSync(0, "utf-8"));
  const soop = await import(SOOP_IMPORT);
  const { RPGEncoder, SearchNode, ExploreRPG, setLogLevel } = soop;
  // soop logs progress to stdout — silence it so stdout carries only our JSON.
  try { setLogLevel?.(0); } catch { /* ignore */ }

  const t0 = performance.now();
  const encoder = new RPGEncoder(job.repo_path, {
    include: INCLUDE,
    respectGitignore: true,
    maxDepth: 12,
    semantic: { useLLM: false },
    cache: { enabled: true, cacheDir: CACHE_DIR },
  });
  const enc = await encoder.encode();
  const indexMs = performance.now() - t0;
  const rpg = enc.rpg;
  const stats = { entities: enc.entitiesExtracted ?? null, files: enc.filesProcessed ?? null };

  if (job.op === "multihop") {
    const search = new SearchNode(rpg);
    const explorer = new ExploreRPG(rpg);
    const rows = [];
    for (const task of job.tasks) {
      const suffix = String(task.anchor_qualified_suffix).toLowerCase();
      const bare = suffix.split("::").pop().split(".").pop();
      const expected = (task.expected_neighbor_names ?? []).map((e) => e.toLowerCase());
      const res = await search.query({ mode: "auto", featureTerms: [task.nl_query] });
      let anchor = null, rank = -1;
      res.nodes.forEach((n, i) => {
        if (anchor) return;
        const qn = String(n.metadata?.qualifiedName ?? "").toLowerCase();
        const nm = String(n.metadata?.name ?? n.name ?? "").toLowerCase();
        if (qn.endsWith(suffix) || nm === bare) { anchor = n; rank = i; }
      });
      if (!anchor) {
        rows.push({ task_id: task.id, anchor_found: false, anchor_rank: -1,
          neighbor_count: 0, expected_count: expected.length, matched_count: 0,
          neighbor_recall: 0, score: 0 });
        continue;
      }
      const direction = task.traversal_pattern === "callees_of" ? "downstream" : "upstream";
      const trav = await explorer.traverse({
        startNode: anchor.id, edgeType: "dependency", maxDepth: 1, direction,
      });
      const names = new Set(trav.nodes.map((n) =>
        String(n.metadata?.name ?? n.name ?? "").toLowerCase()));
      const matched = expected.filter((e) => names.has(e)).length;
      const recall = expected.length ? matched / expected.length : 0;
      rows.push({ task_id: task.id, anchor_found: true, anchor_rank: rank,
        neighbor_count: trav.nodes.length, expected_count: expected.length,
        matched_count: matched, neighbor_recall: +recall.toFixed(3), score: +recall.toFixed(3) });
    }
    emit({ index_ms: indexMs, stats, rows });
    return;
  }

  if (job.op === "combined") {
    const explorer = new ExploreRPG(rpg);
    const NEAR_MARGIN = 80;
    const nodes = await allNodes(rpg);
    const rows = [];
    for (const task of job.tasks) {
      const suffix = String(task.anchor_qualified_suffix).toLowerCase();
      const bare = suffix.split("::").pop().split(".").pop();
      const expected = (task.expected_neighbor_names ?? []).map((e) => e.toLowerCase());
      const candidates = [];
      const seen = new Set();
      for (const hit of job.anchor_hits?.[task.id] ?? []) {
        const inFile = nodes
          .filter((n) => (n.metadata?.path ?? "") === hit.file
            && n.metadata?.startLine != null && n.metadata?.endLine != null)
          .map((n) => {
            const lo = hit.start_line, hi = hit.end_line;
            let gap = 0;
            if (lo != null && hi != null) {
              if (n.metadata.endLine < lo) gap = lo - n.metadata.endLine;
              else if (n.metadata.startLine > hi) gap = n.metadata.startLine - hi;
            }
            return { n, gap, span: n.metadata.endLine - n.metadata.startLine };
          })
          .filter((c) => c.gap <= NEAR_MARGIN)
          .sort((a, b) => a.gap - b.gap || a.span - b.span);
        for (const c of inFile) {
          const key = nodeQualified(c.n);
          if (!seen.has(key)) { seen.add(key); candidates.push(c.n); }
        }
        if (candidates.length >= task.k) break;
      }
      let anchor = null, rank = -1;
      candidates.slice(0, task.k).forEach((n, i) => {
        if (anchor) return;
        const qn = nodeQualified(n).toLowerCase();
        const nm = nodeName(n).toLowerCase();
        if (nm === bare || qn.endsWith(suffix)) { anchor = n; rank = i; }
      });
      if (!anchor && candidates.length) anchor = candidates[0];
      if (!anchor) {
        rows.push({ task_id: task.id, anchor_found: false, anchor_rank: -1,
          neighbor_count: 0, expected_count: expected.length, matched_count: 0,
          neighbor_recall: 0, score: 0, neighbor_names: [] });
        continue;
      }
      const direction = task.traversal_pattern === "callees_of" ? "downstream" : "upstream";
      const trav = await explorer.traverse({
        startNode: anchor.id, edgeType: "dependency", maxDepth: 1, direction,
      });
      const names = new Set(trav.nodes.map((n) => nodeName(n).toLowerCase()));
      const matched = expected.filter((e) => names.has(e)).length;
      const recall = expected.length ? matched / expected.length : 0;
      const found = rank >= 0;
      rows.push({ task_id: task.id, anchor_found: found, anchor_rank: rank,
        neighbor_count: trav.nodes.length, expected_count: expected.length,
        matched_count: matched, neighbor_recall: +recall.toFixed(3),
        score: found ? +recall.toFixed(3) : 0, neighbor_names: [...names].sort() });
    }
    emit({ index_ms: indexMs, stats, rows });
    return;
  }

  // op === "search"
  const search = new SearchNode(rpg);
  const runs = Math.max(1, job.runs ?? 5);
  const k = job.k ?? 10;
  const results = [];
  for (const q of job.queries) {
    const latencies = [];
    let hits = null;
    for (let i = 0; i < runs; i++) {
      const s = performance.now();
      const res = await search.query({ mode: "auto", featureTerms: [q] });
      latencies.push(performance.now() - s);
      if (i === 0) hits = res.nodes.slice(0, k).map((n, idx) => nodeToHit(n, idx));
    }
    results.push({ query: q, latencies_ms: latencies, hits });
  }
  emit({ index_ms: indexMs, stats, results });
}

main().catch((e) => {
  process.stderr.write(String(e?.stack ?? e));
  process.exit(1);
});
