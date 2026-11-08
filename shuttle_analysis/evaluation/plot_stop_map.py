"""Draw numbered route stops with ETA errors, without downloading map tiles."""

import argparse
import csv
import html
import io
import json
import math
from pathlib import Path

from matplotlib import colormaps
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.figure import Figure


ROOT = Path(__file__).resolve().parents[2]


def stop_errors(rows):
    """Return comparison count and mean absolute error for each target stop."""
    groups = {}
    for row in rows:
        groups.setdefault(row["stop_id"], []).append(float(row["absolute_error_seconds"]))
    return {stop: (len(errors), sum(errors) / len(errors)) for stop, errors in groups.items()}


def draw_map(snapshot, rows, title, scale):
    """Draw saved route geometry and a numbered stop key; colors use MAE minutes."""
    route_id = str(snapshot["metadata"]["route_id"])
    raw = snapshot["metadata"]["stop_metadata"]
    shape = raw["routePoints"][route_id][0]
    occurrences = raw["routes"][route_id][2:]
    records = {str(stop["id"]): stop for stop in raw["stops"].values()}
    origin_lat = min(float(p["lat"]) for p in shape)
    origin_lon = min(float(p["lng"]) for p in shape)

    def xy(lat, lon):
        return (6371 * math.radians(float(lon) - origin_lon) * math.cos(math.radians(origin_lat)),
                6371 * math.radians(float(lat) - origin_lat))

    figure = Figure(figsize=(14, 8), layout="constrained")
    axis, key = figure.subplots(1, 2, gridspec_kw={"width_ratios": [1, 1.25]})
    figure.suptitle(title, fontsize=17)
    x, y = zip(*(xy(p["lat"], p["lng"]) for p in shape))
    axis.plot(x, y, color="#32618c", linewidth=2, zorder=1)
    axis.set_aspect("equal")
    axis.set_xlabel("East (km from route extent)")
    axis.set_ylabel("North (km from route extent)")
    axis.set_title("Saved Passio route • north is up", fontsize=11)
    axis.margins(0.18)
    axis.grid(alpha=0.15)
    stats = stop_errors(rows)
    colors = colormaps["YlOrRd"]
    table_rows, table_colors = [], []
    seen = set()
    # Label offsets keep nearby Boston Daytime stops readable; coordinates stay fixed.
    offsets = {"979": (20, -23), "991": (-26, -16), "992": (28, 15),
               "969": (-24, 16), "968": (18, -19), "1002": (-17, 17),
               "3039": (-17, -20)}
    for position, stop_id, _ in occurrences:
        stop_id = str(stop_id)
        if stop_id in seen:
            continue
        seen.add(stop_id)
        numbers = "/".join(str(pos) for pos, sid, _ in occurrences if str(sid) == stop_id)
        stop = records[stop_id]
        count, mae = stats.get(stop_id, (0, None))
        color = colors(scale(mae / 60)) if mae is not None else "#d1d5db"
        point = xy(stop["latitude"], stop["longitude"])
        axis.scatter(*point, s=110, c=[color], edgecolors="#333333", zorder=3)
        axis.annotate(numbers, point, xytext=offsets.get(stop_id, (16, 16)),
                      textcoords="offset points", ha="center", fontsize=10, fontweight="bold",
                      bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "#32618c"},
                      arrowprops={"arrowstyle": "-", "color": "#555555"})
        table_rows.append([numbers, stop_id, stop["name"], f"{mae / 60:.2f}" if mae is not None else "—", str(count)])
        table_colors.append(color)
    key.axis("off")
    key.set_title("Stop key — MAE in minutes; n = evaluated pairs", fontsize=11)
    table = key.table(cellText=table_rows, colLabels=["No.", "Stop ID", "Stop name", "MAE", "n"],
                      colWidths=[0.08, 0.13, 0.54, 0.14, 0.08], cellLoc="left", loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2)
    for i, color in enumerate(table_colors, 1):
        table[i, 3].set_facecolor(color)
    bar = figure.colorbar(ScalarMappable(norm=scale, cmap=colors),
                         ax=axis, orientation="horizontal", shrink=0.8, pad=0.08)
    bar.set_label("Mean absolute error (minutes): darker = larger error")
    figure.supxlabel("Grey = no evaluated data. GPS-estimated arrivals; preliminary. Stop 1/11 is the same location.\nAll-horizons results mix prediction distances; use a stops-ahead view for a fairer comparison.", fontsize=10)
    return figure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", help="Map one evaluated session; otherwise combine sessions")
    args = parser.parse_args()
    base = ROOT / "results/evaluation/passio"
    files = [base / f"errors/passio_errors_{args.session_id}.csv"] if args.session_id else sorted((base / "errors").glob("passio_errors_*.csv"))
    if not files:
        parser.error("Run evaluation first: no error CSVs found")
    snapshots, rows = [], []
    for path in files:
        session_id = path.stem.removeprefix("passio_errors_")
        snapshots.append(json.loads((ROOT / "data/sessions" / f"{session_id}.json").read_text()))
        with path.open(newline="", encoding="utf-8") as file:
            rows.extend(csv.DictReader(file))
    snapshot = snapshots[0]
    route_id = str(snapshot["metadata"]["route_id"])
    raw = snapshot["metadata"]["stop_metadata"]
    for other in snapshots[1:]:
        other_raw = other["metadata"]["stop_metadata"]
        if (str(other["metadata"]["route_id"]) != route_id
                or other_raw["routePoints"][route_id] != raw["routePoints"][route_id]
                or other_raw["routes"][route_id] != raw["routes"][route_id]):
            parser.error("Route geometry/order differs across sessions; use --session-id")
    rows = [row for row in rows if row["route_id"] == route_id]
    views = [("All stops-ahead groups", rows)] + [(f"{n} stops ahead", [r for r in rows if int(r["stops_ahead"]) == n]) for n in range(1, 5)]
    maximum = max((mae / 60 for _, view in views for _, mae in stop_errors(view).values()), default=1)
    scale = Normalize(0, maximum or 1)
    output_dir = base / "plots/maps"
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"passio_stop_map_{args.session_id or 'all'}"
    sections = []
    route_name = raw["routes"][route_id][0]
    for i, (label, view) in enumerate(views):
        figure = draw_map(snapshot, view, f"{route_name} — {label}", scale)
        buffer = io.StringIO()
        figure.savefig(buffer, format="svg")
        svg = buffer.getvalue().split('<svg', 1)[1]
        sections.append(f'<section id="view-{i}" {"hidden" if i else ""}><svg{svg}</section>')
        if i == 0:
            for suffix in ("png", "pdf"):
                figure.savefig(output_dir / f"{name}.{suffix}", dpi=180)
    options = ''.join(f'<option value="{i}">{html.escape(label)}</option>' for i, (label, _) in enumerate(views))
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Route stop ETA errors</title><style>body{{font-family:system-ui;margin:20px;background:#f7f9fc}}section{{background:white}}svg{{width:100%;height:auto}}select{{font:inherit;padding:8px}}</style>
<h1>Route stops and ETA errors</h1><label>Prediction distance: <select id="distance">{options}</select></label>
<p>Offline map from saved route coordinates. Numbers follow route order; the key gives stop IDs and names. No background tiles are requested.</p>
{''.join(sections)}<script>document.getElementById('distance').addEventListener('change', function() {{ document.querySelectorAll('section').forEach((section, i) => section.hidden = i !== Number(this.value)); }});</script></html>'''
    (output_dir / f"{name}.html").write_text(page, encoding="utf-8")
    print(f"Saved interactive HTML, PNG, and PDF in {output_dir} ({name})")


if __name__ == "__main__":
    main()
