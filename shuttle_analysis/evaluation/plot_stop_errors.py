"""Show mean absolute error at each target stop, grouped by stops away."""

import argparse
from pathlib import Path

from matplotlib import colormaps
from matplotlib.figure import Figure

from .plot_inputs import route_views


ROOT = Path(__file__).resolve().parents[2]


def stop_means(rows, stop_ids):
    """Return MAE in minutes and comparison counts for each stop and horizon."""
    means, counts = [], []
    for stop_id in stop_ids:
        stop_means, stop_counts = [], []
        for ahead in range(1, 5):
            errors = [float(row["absolute_error_seconds"]) for row in rows
                      if row["stop_id"] == stop_id and int(row["stops_ahead"]) == ahead]
            stop_counts.append(len(errors))
            stop_means.append(sum(errors) / len(errors) / 60 if errors else float("nan"))
        means.append(stop_means)
        counts.append(stop_counts)
    return means, counts


def plot_stop_errors(rows, snapshot, output):
    """Save one stop-by-distance chart, labeled with names, IDs, and sample counts."""
    route_id = str(snapshot["metadata"]["route_id"])
    raw = snapshot["metadata"]["stop_metadata"]
    occurrences = raw["routes"][route_id][2:]
    records = {str(stop["id"]): stop for stop in raw["stops"].values()}
    stop_ids = list(dict.fromkeys(str(stop_id) for _, stop_id, _ in occurrences))
    labels = []
    for stop_id in stop_ids:
        numbers = "/".join(str(pos) for pos, sid, _ in occurrences if str(sid) == stop_id)
        labels.append(f'{numbers}. {records[stop_id]["name"]} (ID {stop_id})')
    rows = [row for row in rows if row["route_id"] == route_id]
    means, counts = stop_means(rows, stop_ids)
    figure = Figure(figsize=(13, max(8, len(stop_ids) * 0.5)), layout="constrained")
    axis = figure.subplots()
    colors = colormaps["YlOrRd"].copy()
    colors.set_bad("#e5e7eb")
    maximum = max((value for group, ns in zip(means, counts)
                   for value, n in zip(group, ns) if n), default=1) or 1
    chart = axis.imshow(means, aspect="auto", cmap=colors, vmin=0, vmax=maximum)
    axis.set_xticks(range(4), ["1 stop away", "2 stops away", "3 stops away", "4 stops away"])
    axis.set_yticks(range(len(labels)), labels)
    axis.set_title(f'{raw["routes"][route_id][0]}: mean absolute ETA error by stop', pad=18, fontsize=16)
    for i, (group, ns) in enumerate(zip(means, counts)):
        for j, (value, n) in enumerate(zip(group, ns)):
            text = f"{value:.2f} min\nn={n}" if n else "No data"
            axis.text(j, i, text, ha="center", va="center", fontsize=10,
                      color="white" if n and value > maximum * 0.6 else "black")
    axis.set_xticks([i - 0.5 for i in range(5)], minor=True)
    axis.set_yticks([i - 0.5 for i in range(len(labels) + 1)], minor=True)
    axis.grid(which="minor", color="white", linewidth=2)
    axis.tick_params(which="minor", bottom=False, left=False)
    figure.colorbar(chart, ax=axis, shrink=0.8, label="Mean absolute error (minutes)")
    figure.supxlabel("Each cell averages selected predictions at that stops-away checkpoint. Lower is better.\nn = evaluated pairs; grey = no data. Preliminary errors against GPS-estimated arrivals.", fontsize=10)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".png", ".pdf"):
        figure.savefig(output.with_suffix(suffix), dpi=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", help="Use one session; otherwise combine all evaluated sessions")
    parser.add_argument("--route-id", help="Plot one route; otherwise write a chart for every supported route")
    args = parser.parse_args()
    base = ROOT / "results/evaluation/passio"
    try:
        views = route_views(ROOT, args.session_id, args.route_id)
    except ValueError as error:
        parser.error(str(error))
    for snapshot, rows, suffix in views:
        output = base / "plots/stops" / f"passio_stop_mae_{suffix}.png"
        plot_stop_errors(rows, snapshot, output)
        print(f"Saved {output} and {output.with_suffix('.pdf')}")


if __name__ == "__main__":
    main()
