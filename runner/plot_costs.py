#!/usr/bin/env python3
"""plot_costs.py — chart the per-loop cost log that run_loop.py writes (the COST_LOG YAML).

Reads the YAML sequence of run records and renders two panels:
  1) stacked token breakdown per loop (input-uncached / cached / output / thought / tool), with a
     red mark on any loop that did NOT push (i.e. spent tokens but persisted nothing);
  2) cumulative tokens over time, plus cumulative est_cost on a second axis if the records have it.
Also prints a summary. Saves a PNG; pass --show to also open a window.

Usage:
  python3 runner/plot_costs.py                                  # $COST_LOG or runner/cost_log.yaml -> runner/cost_charts.png
  python3 runner/plot_costs.py --log path.yaml --out charts.png --show
"""
from __future__ import annotations

import argparse
import os
import sys


def _load(path: str) -> list[dict]:
    try:
        import yaml
    except ImportError:
        sys.exit("needs PyYAML to read the log:  pip install pyyaml")
    if not os.path.exists(path):
        sys.exit(f"no cost log at {path} — run a loop with COST_LOG set first")
    rows = yaml.safe_load(open(path, encoding="utf-8")) or []
    if not isinstance(rows, list) or not rows:
        sys.exit(f"{path} has no run records yet")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.environ.get("COST_LOG") or "runner/cost_log.yaml")
    ap.add_argument("--out", default="runner/cost_charts.png")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    rows = _load(args.log)

    try:
        import matplotlib
        if not args.show:
            matplotlib.use("Agg")            # headless: just write the PNG
        import matplotlib.pyplot as plt
    except ImportError:
        sys.exit("needs matplotlib to draw:  pip install matplotlib")

    n = len(rows)
    x = list(range(1, n + 1))

    def col(k):
        return [int(r.get(k, 0) or 0) for r in rows]

    inp, cached = col("input_tokens"), col("cached_tokens")
    out, thought, tool = col("output_tokens"), col("thought_tokens"), col("tool_tokens")
    total = col("total_tokens")
    pushed = [bool(r.get("pushed")) for r in rows]
    costs = [r.get("est_cost") for r in rows]
    has_cost = any(c is not None for c in costs)
    cost_vals = [float(c or 0) for c in costs]
    uncached = [max(i - c, 0) for i, c in zip(inp, cached)]   # input minus its cached portion

    print(f"runs:          {n}")
    print(f"total tokens:  {sum(total):,}  (avg {sum(total) // n:,}/loop)")
    print(f"pushed:        {sum(pushed)}/{n}" + ("" if all(pushed) else "  <- some loops spent tokens but didn't push"))
    if has_cost:
        print(f"est cost:      {sum(cost_vals):.2f}  (avg {sum(cost_vals) / n:.3f}/loop)")

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(max(8, n * 0.5), 8))
    step = max(1, n // 20)   # keep x-ticks readable when there are many loops

    bottoms = [0] * n
    for label, vals, color in [
        ("input (uncached)", uncached, "#4c78a8"),
        ("cached", cached, "#9ecae9"),
        ("output", out, "#f58518"),
        ("thought", thought, "#e45756"),
        ("tool", tool, "#54a24b"),
    ]:
        a1.bar(x, vals, bottom=bottoms, label=label, color=color)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    for xi, p, t in zip(x, pushed, total):
        if not p:
            a1.text(xi, t, "✗", ha="center", va="bottom", color="red", fontsize=10, fontweight="bold")
    a1.set_title("Tokens per loop — stacked breakdown (✗ = did not push)")
    a1.set_xlabel("loop #"); a1.set_ylabel("tokens"); a1.legend(fontsize=8, ncol=5)
    a1.set_xticks(x[::step])

    cum_tok, s = [], 0
    for t in total:
        s += t
        cum_tok.append(s)
    a2.plot(x, cum_tok, marker="o", color="#4c78a8", label="cumulative tokens")
    a2.set_xlabel("loop #"); a2.set_ylabel("cumulative tokens", color="#4c78a8")
    a2.set_xticks(x[::step]); a2.set_title("Cumulative consumption")
    if has_cost:
        a2b = a2.twinx()
        cum_cost, s = [], 0.0
        for c in cost_vals:
            s += c
            cum_cost.append(s)
        a2b.plot(x, cum_cost, marker="s", color="#54a24b", label="cumulative est_cost")
        a2b.set_ylabel("cumulative est_cost", color="#54a24b")

    fig.tight_layout()
    fig.savefig(args.out, dpi=120)
    print(f"saved {args.out}")
    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
