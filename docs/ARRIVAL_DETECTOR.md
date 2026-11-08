# Basic arrival detector

The detector uses saved GPS observations and the route's ordered segments.
It is an estimate based on collection times, not exact boarding-location ground truth.

## Files

- `processing/arrivals/arrival_detector.py`: load the route and detect arrivals.
- `processing/arrivals/review_arrivals.py`: read saved sessions and write result CSVs.
- `processing/shared/route_geometry.py`: coordinates, geographic distance, and segment projection.
- `processing/shared/route_matching.py`: choose a plausible distance along the route for a GPS point.
- `processing/shared/vehicle_positions.py`: shared GPS validation, history resets, and matched observations.
- `processing/shared/stop_segments.py`: stop IDs and chosen segments for Boston Daytime.

These paths are inside `shuttle_analysis/`. Arrival detection calls the shared
route matcher; dwell detection and checkpoint matching use the same matched
observation reader.

## The algorithm

1. Add segment lengths to give every route location a distance from the start.
2. Project each stop onto its configured segment to obtain its route position.
3. Read observations in time order and maintain the previous position for each bus.
4. For each GPS fix, choose the nearest route projection within 50 m. If there is
   history, consider only positions from 20 m behind to 500 m ahead of the previous
   position, accounting for wrapping around the loop. This is a fixed distance
   window; there is no speed-times-time calculation.
5. Skip unresolved matches: if two positions more than two stop radii apart along
   the route have lateral distances within 5 m, do not choose between them.
6. Record a visit when the bus is within 30 m both physically and along the route
   of a designated stop. Also record a forward crossing between observations, with
   `arrival_method="between_samples"`. No dwell is required.
7. Remember visited stop/loop pairs to avoid duplicate entries while a bus remains
   nearby or briefly re-enters. The same stop on the next loop can produce a new arrival.

Missing buses, failed requests, stale/out-of-service records, invalid coordinates,
unmatched positions, and gaps over 60 seconds reset that bus's history. Starting
inside an area does not establish an arrival: it is marked visited without emitting
an event. Route changes also reset history. Records without a bus ID are skipped.
Duplicate or nonincreasing receipt times do not produce another arrival. Vehicle
service flags of 0, missing, or None are accepted; other values are skipped.
Prediction evaluation uses a stricter rule and requires explicit zero flags.

The repeated start/end stop is represented by its ending occurrence, so one physical
loop-boundary arrival is not counted twice.

## Input and output

```python
from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from shuttle_analysis.storage import CSVStorage

storage = CSVStorage("your-session-id", "data")
detector = ArrivalDetector(storage.read_session_metadata())
arrivals = detector.detect(storage.read_observations("vehicles"))
```

Each returned dictionary contains only:

```text
session_id, bus_id, route_id, stop_id, route_stop_position,
estimated_arrival_at, previous_observed_at, arrival_method
```

`estimated_arrival_at` is the first recorded evidence of entering or passing the
stop: the current collection timestamp. `previous_observed_at` is the preceding
accepted observation. For a crossing between samples, the estimate can be late by
up to the sampling interval, apart from GPS/fix-age errors. `arrival_method` is
`near_stop` or `between_samples`, so an evaluator can separate those cases.

## Stop segments and limits

The default table assumes the saved 384-point Boston Daytime route and its known
stop order. Counts, spatial distance, and stop order are checked. If Passio changes
the shape, manually verify the segment table.
Silber Way (3042) is skipped by default because its correct route section remains
unresolved. Raw observations for it are still preserved.

For a different route or reviewed placements, supply a mapping such as
`stop_segments={"1": 0, "2": 45, ...}` to the constructor, or put that mapping in
the loaded metadata as `stop_segments`. Include every route occurrence. A custom
mapping must be reviewed: it does not inherit the default Silber Way exclusion.
The route must be one closed coordinate sequence with the first stop repeated last.

The fixed search window assumes roughly 30-second polling. Too much movement,
GPS ambiguity, or missing samples can cause missed arrivals. Stop-area entry may
precede reaching the boarding location. The simpler method has no lookahead or
attempt to recover skipped history. Manual validation is still needed.

## Run

```bash
.venv/bin/python -m shuttle_analysis.processing.arrivals.review_arrivals --session-id <session-id>
.venv/bin/python -m unittest discover -s tests -v
```

Omit `--session-id` to process all saved snapshots in `data/sessions/`. Output goes to
`results/arrivals/arrivals_<session_id>.csv`. Rerunning replaces that derived CSV, not the
collected inputs. Run after collection so the input session is stable.
`data/actual_arrivals.csv` is left unchanged. Saferide collection is enabled, but
its arrival processing still needs its own reviewed stop-segment configuration.

## Use in evaluation

The checkpoint matcher uses these arrivals twice: an upstream arrival sets the
prediction-selection time, and a downstream arrival supplies the target time.
It requires both visits to lie in continuous GPS history. It does not use dwell
records or Passio's `arrived` field. See [ETA_EVALUATION.md](ETA_EVALUATION.md).
