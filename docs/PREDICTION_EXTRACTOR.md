# Passio prediction extraction

`PredictionExtractor` unpacks saved ETA responses into individual records. It
uses Passio's predictions; it does not calculate new ETAs or match arrivals.

```python
from shuttle_analysis.processing.predictions.prediction_extractor import PredictionExtractor
from shuttle_analysis.storage import CSVStorage

storage = CSVStorage("your-session-id", "data")
extractor = PredictionExtractor(storage.read_session_metadata())
predictions = extractor.extract(storage.read_observations("eta"))
```

## Rules

Read observations in request-start order. For each successful response, read each
list under `data["ETAs"][stop_id]` and emit one record per bus prediction.
Keep predictions from every route in the session, including repeated polls of
the same upcoming visit. Do not remove predictions because their arrival time
is already past; matching and filtering belong to evaluation.

Skip failed requests, empty responses, malformed entries, missing bus/route IDs,
conflicting stop IDs, and missing or invalid arrival timestamps. Observations
from another session raise an error. Non-ETA observations are ignored.

## Output

| Field | Meaning |
| --- | --- |
| `session_id` | Collection session shared with arrival and dwell records |
| `bus_id` | Passio `busId`, as a string |
| `route_id` | Prediction's `routeId`, as a string |
| `stop_id` | Stop key under `ETAs`, as a string |
| `prediction_observed_at` | Response receipt time, converted to UTC |
| `predicted_arrival_at` | `arrivalTimestamp` Unix seconds, converted to UTC |
| `trip_id` | Optional Passio `tripId`, as a string |
| `passio_stop_position` | Optional `theStop.position`, as a string |
| `outdated` | Original Passio flag, or None if absent |
| `out_of_service` | Original Passio `OOS` flag, or None if absent |

Times use UTC ISO strings, consistent with collection and arrival records.
Receipt time is when we observed the prediction, not its creation time.
Missing optional fields are None in Python and empty cells in CSV.

Use `arrivalTimestamp`, not rounded display text such as `"1-2 min"` or
`secondsSpent`. Stale and out-of-service predictions remain available with their
original flags so evaluation can choose a filtering rule explicitly. Flags are
preserved as supplied, so values can be integers or strings.

`passio_stop_position` is deliberately different from arrival output's
`route_stop_position`: repeated physical stops can have different Passio
positions. The extractor does not infer which occurrence or loop a prediction
belongs to. Trip IDs alone do not establish a full loop either.

One estimated arrival can match predictions collected at several upstream checkpoints. Matching
must identify the same bus, route, stop, session, and intended visit before
calculating `predicted_arrival_at - estimated_arrival_at`. The separate
[evaluation pipeline](ETA_EVALUATION.md) performs this matching using stop checkpoints
and continuous GPS history. Extraction retains all polls; the evaluator selects
one usable prediction per checkpoint/target pair, requiring both flags to be 0.

## CSV output

```bash
.venv/bin/python -m shuttle_analysis.processing.predictions.review_predictions --session-id <session-id>
```

Omit `--session-id` to process all saved snapshots in `data/sessions/`. The runner reads both the
legacy and route-aware ETA CSV schemas through `CSVStorage`, then writes
`results/predictions/predictions_<session_id>.csv`. Rerunning replaces only that derived
output. Run after collection; raw inputs remain unchanged.
