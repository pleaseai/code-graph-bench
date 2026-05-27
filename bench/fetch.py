"""Clone pinned repo snapshots into checkouts/<repo>@<sha>/.

Each repo is cloned once per distinct SHA it is pinned at (retrieval SHA and
graph SHA may differ). Uses a shallow fetch-by-SHA, falling back to a full
clone + checkout when the server refuses an arbitrary-SHA fetch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from bench.goldset import RepoSpec, load_corpus
from bench.paths import CHECKOUTS_DIR, checkout_path


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def _is_checked_out(dest: Path, sha: str) -> bool:
    if not (dest / ".git").exists():
        return False
    try:
        head = _run(["git", "rev-parse", "HEAD"], cwd=dest).stdout.strip()
        return head == sha
    except subprocess.CalledProcessError:
        return False


def clone_at_sha(url: str, sha: str, dest: Path) -> Path:
    """Clone `url` at exactly `sha` into `dest` (idempotent)."""
    if _is_checked_out(dest, sha):
        return dest
    if dest.exists():
        # Stale/partial — start clean for determinism.
        _run(["rm", "-rf", str(dest)])
    dest.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q"], cwd=dest)
    _run(["git", "remote", "add", "origin", url], cwd=dest)
    try:
        _run(["git", "fetch", "--depth", "1", "origin", sha], cwd=dest)
        _run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=dest)
    except subprocess.CalledProcessError:
        # Server refused arbitrary-SHA fetch: full fetch then checkout.
        _run(["git", "fetch", "-q", "origin"], cwd=dest)
        _run(["git", "checkout", "-q", sha], cwd=dest)
    return dest


def shas_for(spec: RepoSpec) -> list[str]:
    """Distinct SHAs to materialize for a repo."""
    shas = [spec.retrieval_sha]
    if spec.graph_sha and spec.graph_sha not in shas:
        shas.append(spec.graph_sha)
    return shas


def fetch_repo(spec: RepoSpec) -> dict[str, Path]:
    """Materialize all pinned snapshots for one repo. Returns {sha: path}."""
    out: dict[str, Path] = {}
    for sha in shas_for(spec):
        dest = checkout_path(spec.name, sha)
        clone_at_sha(spec.url, sha, dest)
        out[sha] = dest
    return out


def fetch_all(repos: list[str] | None = None) -> dict[str, dict[str, Path]]:
    corpus = load_corpus()
    CHECKOUTS_DIR.mkdir(parents=True, exist_ok=True)
    targets = corpus.repos if not repos else [corpus.get(r) for r in repos]
    return {spec.name: fetch_repo(spec) for spec in targets}
