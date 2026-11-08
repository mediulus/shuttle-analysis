# Stop dwell detection

`DwellDetector` measures the time observed inside a stop area. It does not predict
future dwell, establish engine idle, or require the bus to be motionless.

## Use

```python
from shuttle_analysis.processing.dwell.dwell_detector import DwellDetector
from shuttle_analysis.storage import CSVStorage

storage = CSVStorage("your-session-id", "data")
detector = DwellDetector(storage.read_session_metadata())
dwells = detector.detect(storage.read_observations("vehicles"))
```

The constructor and `detect(observations)` interface match `ArrivalDetector`.
Both use the same route setup, stop placements, 30 m radius, GPS validation,
route matching, and reset rules. Boston Daytime is the default supported route;
other routes need reviewed stop segments. Silber Way is excluded by default.

## Rules

1. After a reliable earlier fix outside the area, observe the bus inside it.
   This starts a visit at the same time as a `near_stop` arrival. Both geographic and along-route distances
   must be within the radius.
2. Update the last-inside time while the bus remains in that area.
3. On the first reliable observation outside, output the visit.
4. Calculate `observed_dwell_seconds = last_inside_at - estimated_arrival_at`.

Each record contains all eight arrival fields, plus `last_inside_at`,
`first_outside_at`, and `observed_dwell_seconds`. Times are ISO timestamps and
identifiers are strings, just as in arrival output. Dwell records use
`arrival_method="near_stop"`.

For example, first inside at 10:00:30, last inside at 10:01:30, and first outside
at 10:02:00 gives **60 seconds of observed dwell**. The exit timestamp is evidence
that the visit ended; it is not used as the exact departure time.

One inside observation gives zero seconds of observed dwell, not proof of zero
actual dwell. Passing between samples produces an arrival but no dwell record.
Starting inside, ending before exit, or losing reliable data during a visit
produces no completed dwell record. Missing buses, failed requests, invalid or
unmatched fixes, route changes, stale/out-of-service records, and gaps over 60
seconds reset history. Duplicate timestamps are ignored. A stop is counted once
per bus and loop, including brief reentry, consistently with arrivals.

Each `detect()` call processes a supplied batch from scratch; state is not
retained between calls. Results are emitted when the exit is observed.

The result measures time in an area. GPS sampling and positioning errors mean it
is not an exact measure of stopped time. No interpolation or extra timing rule
is applied.

## CSV output

After collection, run:

```bash
.venv/bin/python -m shuttle_analysis.processing.dwell.review_dwells --session-id <session-id>
```

Omit `--session-id` to process all saved snapshots in `data/sessions/`. The runner writes
`results/dwell/dwells_<session_id>.csv`. Rerunning replaces only that derived CSV and
leaves collected inputs unchanged.

Dwell output is a separate analysis. It is not currently used to select ETA
checkpoints or calculate prediction errors. See [ETA_EVALUATION.md](ETA_EVALUATION.md).
