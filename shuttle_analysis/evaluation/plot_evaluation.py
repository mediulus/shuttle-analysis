"""Plot error, bias, and coverage from an evaluation summary CSV."""

import argparse
import csv
import math
from pathlib import Path

from matplotlib.figure import Figure


ROOT = Path(__file__).resolve().parents[2]


def plot_summary(rows, output):
    """Save a three-panel figure as PNG and PDF. Empty means remain missing."""
    rows = sorted(rows, key=lambda row: int(row["stops_ahead"]))
    stops = [int(row["stops_ahead"]) for row in rows]
    counts = [int(row["count"]) for row in rows]
    mae = [float(row["mae_seconds"]) if row["mae_seconds"] not in (None, "") else float("nan") for row in rows]
    bias = [float(row["mean_error_seconds"]) if row["mean_error_seconds"] not in (None, "") else float("nan") for row in rows]
    figure = Figure(figsize=(13, 5.5), layout="constrained")
    axes = figure.subplots(1, 3)
    figure.suptitle("Shuttle ETA evaluation", fontsize=17)
    for axis in axes:
        axis.set_xlabel("Stops ahead")
        axis.set_xticks(stops)
        axis.set_axisbelow(True)
        axis.grid(axis="y", alpha=0.2)

    axes[0].plot(stops, mae, marker="o", color="#2166ac")
    axes[0].set_title("Mean absolute error")
    axes[0].set_ylabel("Seconds (lower is better)")
    largest_error = max((value for value in mae if math.isfinite(value)), default=0)
    axes[0].set_ylim(0, largest_error * 1.2 if largest_error > 0 else 1)
    for stop, error, count in zip(stops, mae, counts):
        if count:
            axes[0].annotate(f"n={count}", (stop, error), xytext=(0, 9),
                             textcoords="offset points", ha="center", fontsize=9)

    axes[1].bar(stops, bias, color="#b35806")
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("Mean signed error")
    axes[1].set_ylabel("Seconds (+ later prediction, − earlier)")

    bottom = [0] * len(rows)
    for field, label, color in [
        ("count", "Evaluated", "#2166ac"),
        ("no_target_arrival", "No target arrival", "#bdbdbd"),
        ("no_prediction", "No usable prediction", "#fdb863"),
        ("ambiguous_prediction", "Ambiguous prediction", "#b2182b"),
    ]:
        values = [int(row[field]) for row in rows]
        axes[2].bar(stops, values, bottom=bottom, label=label, color=color)
        bottom = [total + value for total, value in zip(bottom, values)]
    axes[2].set_ylim(0, max(bottom, default=0) * 1.1 or 1)
    axes[2].set_title("Checkpoint coverage")
    axes[2].set_ylabel("Checkpoint / target pairs")
    axes[2].legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), fontsize=8, frameon=False)
    figure.supxlabel("Errors use GPS-estimated arrivals; preliminary results. n = evaluated pairs, not independent trips.", fontsize=10)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".png", ".pdf"):
        figure.savefig(output.with_suffix(suffix), dpi=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=ROOT / "results/evaluation/passio/summaries/passio_summary_all.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results/evaluation/passio/plots")
    args = parser.parse_args()
    with args.summary.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        parser.error("The summary CSV contains no rows; run evaluation first")
    output = args.output_dir / args.summary.with_suffix(".png").name
    plot_summary(rows, output)
    print(f"Saved {output} and {output.with_suffix('.pdf')}")


if __name__ == "__main__":
    main()
