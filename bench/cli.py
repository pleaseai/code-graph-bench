"""cgbench — command-line entry point."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from bench.goldset import load_corpus, load_graph_config, load_retrieval_tasks

app = typer.Typer(
    add_completion=False,
    help="Apples-to-apples benchmark for agent code-intelligence tools.",
)
console = Console()


@app.command()
def fetch(
    repo: list[str] = typer.Option(None, "--repo", "-r", help="Repo name(s); default all."),
) -> None:
    """Clone pinned repo snapshots into checkouts/."""
    from bench.fetch import fetch_all

    result = fetch_all(repo or None)
    for name, shas in result.items():
        for sha, path in shas.items():
            console.print(f"[green]ok[/] {name}@{sha[:12]} -> {path}")


@app.command()
def goldset() -> None:
    """Validate gold-set integrity against the corpus and print a summary."""
    corpus = load_corpus()
    table = Table(title="Gold-set summary")
    for col in ("repo", "lang", "tier", "retr. queries", "categories", "graph: tc/mh/sq"):
        table.add_column(col)

    problems: list[str] = []
    for spec in corpus.repos:
        try:
            tasks = load_retrieval_tasks(spec.name)
        except FileNotFoundError:
            problems.append(f"{spec.name}: missing retrieval gold")
            tasks = []
        cats: dict[str, int] = {}
        for t in tasks:
            cats[t.category] = cats.get(t.category, 0) + 1
            if not t.relevant:
                problems.append(f"{spec.name}: query with no relevant targets: {t.query!r}")
        graph_summary = "-"
        if spec.has_graph:
            try:
                g = load_graph_config(spec.name)
                graph_summary = f"{len(g.test_commits)}/{len(g.multi_hop_tasks)}/{len(g.search_queries)}"
            except FileNotFoundError:
                problems.append(f"{spec.name}: graph.sha set but graph gold missing")
        table.add_row(
            spec.name, spec.language, spec.tier, str(len(tasks)),
            ", ".join(f"{k}:{v}" for k, v in sorted(cats.items())), graph_summary,
        )
    console.print(table)
    if problems:
        console.print("\n[red]Problems:[/]")
        for p in problems:
            console.print(f"  - {p}")
        raise typer.Exit(1)
    console.print("\n[green]Gold-set OK[/]")


@app.command()
def run(
    arm: str = typer.Argument(..., help="a | b | c | d | perf"),
    repo: list[str] = typer.Option(None, "--repo", "-r"),
    tool: list[str] = typer.Option(None, "--tool", "-t", help="semble | crg | codegraph"),
    k: int = typer.Option(10, "--k", help="top-k for retrieval."),
) -> None:
    """Run a benchmark arm."""
    arm = arm.lower()
    if arm == "a":
        from bench.runners.arm_a_retrieval import run_arm_a

        run_arm_a(repos=repo or None, tools=tool or None, k=k)
    elif arm == "perf":
        from bench.runners.perf import run_perf

        run_perf(repos=repo or None, tools=tool or None)
    elif arm == "b":
        from bench.runners.arm_b_graph import run_arm_b

        run_arm_b(repos=repo or None, tools=tool or None)
    elif arm == "c":
        from bench.runners.arm_c_combined import run_arm_c

        run_arm_c(repos=repo or None)
    elif arm == "d":
        from bench.runners.arm_d_agent import run_arm_d

        run_arm_d(repos=repo or None, tools=tool or None)
    else:
        raise typer.BadParameter("arm must be one of: a, b, c, d, perf")


@app.command()
def report(
    arm: str = typer.Option(None, "--arm", help="Filter to one arm."),
) -> None:
    """Render results/*.json into markdown tables."""
    from bench.report import render

    render(arm=arm)


if __name__ == "__main__":
    app()
