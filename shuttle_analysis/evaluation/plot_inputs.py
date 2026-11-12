"""Load evaluated sessions and keep route-specific plot inputs separate."""

import csv
import json

from ..processing.shared.routes import analysis_route_ids, route_snapshot


def route_views(root, session_id=None, route_id=None):
    """Return (snapshot, error rows, filename suffix) for each selected route."""
    base = root / "results/evaluation/passio/errors"
    files = [base / f"passio_errors_{session_id}.csv"] if session_id else sorted(base.glob("passio_errors_*.csv"))
    if not files:
        raise ValueError("Run evaluation first: no error CSVs found")
    snapshots, rows = [], []
    for path in files:
        sid = path.stem.removeprefix("passio_errors_")
        snapshots.append(json.loads((root / "data/sessions" / f"{sid}.json").read_text()))
        with path.open(newline="", encoding="utf-8") as file:
            rows.extend(csv.DictReader(file))
    available = list(dict.fromkeys(rid for snapshot in snapshots for rid in analysis_route_ids(snapshot)))
    selected = [str(route_id)] if route_id is not None else available
    views = []
    for rid in selected:
        matching = [s for s in snapshots if rid in analysis_route_ids(s)]
        if not matching:
            raise ValueError(f"Route {rid} is absent from the evaluated sessions")
        reference = matching[0]["metadata"]["stop_metadata"]
        for snapshot in matching[1:]:
            raw = snapshot["metadata"]["stop_metadata"]
            if (raw["routePoints"][rid] != reference["routePoints"][rid]
                    or raw["routes"][rid] != reference["routes"][rid]):
                raise ValueError(f"Route {rid} geometry/order differs; use --session-id")
        suffix = session_id or "all"
        if rid != "71342":
            suffix = f"route_{rid}_{suffix}"
        views.append((route_snapshot(matching[0], rid),
                      [r for r in rows if r["route_id"] == rid], suffix))
    return views
