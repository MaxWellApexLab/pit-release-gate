"""Regenerate docs/assets/demo_bias.png from the shipped fixed-seed demo.

The chart hardcodes nothing: it runs `run_demo` (the same call the CLI makes)
and plots the systematic size-coefficient bias of naive early release vs the
graded gate for each planted signal type. `tests/test_reproduces_paper.py`
pins the underlying numbers.
"""
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pit_release_gate import run_demo

OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "assets"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    res = run_demo(verbose=False)["signals"]
    order = ["clean", "composition", "mild_leak", "strong_leak"]
    labels = ["Clean", "Composition\n(obs. selection)", "Mild leak", "Strong leak"]
    naive = [res[k]["policies"]["naive"]["bias_mean"] for k in order]
    gated = [res[k]["policies"]["gated"]["bias_mean"] for k in order]
    comp = [res[k]["policies"]["gated"]["comp_mean"] for k in order]

    fig, ax = plt.subplots(figsize=(8.6, 4.2), dpi=150)
    x = range(len(order))
    w = 0.38
    ax.bar([i - w / 2 for i in x], naive, w, label="naive early release",
           color="#c0392b", alpha=0.85)
    ax.bar([i + w / 2 for i in x], gated, w, label="graded gate",
           color="#2471a3", alpha=0.9)
    ax.axhline(0, color="black", lw=0.8)
    for i, (g, c) in enumerate(zip(gated, comp)):
        ax.annotate(f"releases at {c:.0%}", (i + w / 2, g),
                    textcoords="offset points", xytext=(0, -14),
                    ha="center", fontsize=8, color="#2471a3")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("systematic bias of released signal\n(size-coefficient, signed)")
    ax.set_title("Known-ground-truth demo: the gate withholds only the signals that need it",
                 fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "demo_bias.png", facecolor="white")
    print("wrote", OUT / "demo_bias.png")
    for k, n, g, c in zip(order, naive, gated, comp):
        print(f"  {k:<12} naive {n:+.3f}  gated {g:+.3f}  at {c:.0%}")


if __name__ == "__main__":
    main()
