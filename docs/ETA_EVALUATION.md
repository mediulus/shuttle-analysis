# ETA evaluation

The evaluation pipeline has three small modules; separate plotting scripts read
its saved results:

- `prediction_matching.py`: choose predictions and connect checkpoints to target visits.
- `eta_evaluator.py`: subtract paired timestamps and calculate averages.
- `evaluate_passio.py`: read saved inputs and write result CSVs.

The evaluator uses no Passio fields or route geometry. A future regression model
can supply the same paired timestamp records to `evaluate()` and `summarize()`.

## Checkpoints and matching

For A → B → C → D → E, an observed arrival at A is a four-stops-ahead checkpoint
for E. The runner evaluates one, two, three, and four stops ahead.

1. Read predictions and detect arrivals from the saved session. Evaluation uses
   the snapshot's primary route; default snapshots analyze Boston Daytime even
   when collection also recorded Saferide.
2. Reuse GPS matching to divide each bus's history into continuous stretches.
   A failed request, missing bus, route change, bad fix, or long gap breaks the
   stretch, using the existing detector's rules. Never match across these breaks.
3. Starting at an observed checkpoint arrival, follow later arrivals in route
   order within the same stretch. Count steps using the full route stop list,
   including stops whose arrival detection is disabled. Missing target arrivals
   are skipped, rather than substituted with a later loop's visit.
4. For each supported target visit, select the latest prediction received at or
   before the checkpoint, no more than 30 seconds earlier. Require matching
   session, bus, route, and physical stop. Require both service flags to be 0
   (integer or string); unknown flags are not assumed usable.
5. If different predictions share that latest receipt time, skip the ambiguous
   case. Identical duplicates do not create additional results.

Predicted arrival time is not used to choose the target visit. Even a prediction
hours off is compared to the same next supported visit, avoiding a rule that
would make poor predictions appear accurate by choosing a different loop.
The working assumption is that Passio supplies the next downstream visit for
that bus/stop. This is not independently verified by trip IDs or Passio stop
positions. Those fields are not treated as proof of visit identity. Manual
validation of this assumption and the GPS-derived arrivals remains necessary.

The duplicate first/end stop is represented by its ending occurrence, matching
the arrival detector. Silber Way uses outbound segment 114 after 487 Comm. Ave.
and can supply both checkpoints and target arrivals. Other route tables require
reviewed stop placements.

Checkpoint time is an estimated arrival, possibly a crossing between GPS samples.
It need not be the exact instant the bus reaches the boarding point. Both
checkpoint and target supporting observation times/methods are retained. A crossing
checkpoint is allowed; its timestamp is the later GPS observation, just as in
arrival detection. The matcher does not interpolate an exact stop-crossing time.

## Generic evaluator

```python
from shuttle_analysis.evaluation.eta_evaluator import evaluate, summarize

pairs = [{
    "predicted_arrival_at": "2026-11-08T10:03:00+00:00",
    "estimated_arrival_at": "2026-11-08T10:02:30+00:00",
}]
results = evaluate(pairs)  # Adds error_seconds=30, absolute_error_seconds=30.
summary = summarize(results)  # count, mae_seconds, mean_error_seconds.
```

Positive error means the prediction was later than estimated arrival; negative
means earlier. All inputs should use timezone-aware ISO timestamps. Extra
identity/model fields pass through unchanged. Empty groups have count 0 and
None for means, represented as empty CSV cells.

## Results

Analyze a session after stopping collection so the raw inputs are stable.


```bash
.venv/bin/python -m shuttle_analysis.evaluation.evaluate_passio
# Or process only one session:
.venv/bin/python -m shuttle_analysis.evaluation.evaluate_passio --session-id <session-id>
```

The runner reads saved raw observations and regenerates arrivals/predictions in
memory. It does not depend on possibly outdated derived CSVs or alter raw data.
Without `--session-id`, it processes snapshots in `data/sessions/`. It writes
these files under `results/evaluation/passio/`:

- `errors/passio_errors_<session_id>.csv`: one selected prediction per checkpoint/target
  pair, identities, checkpoint and target times, and signed/absolute error.
- `coverage/passio_coverage_<session_id>.csv`: four rows per observed checkpoint, with
  status `matched`, `no_target_arrival`, `no_prediction`, or `ambiguous_prediction`.
- `summaries/passio_summary_<session_id>.csv`: error averages and coverage counts by stops ahead.
- `summaries/passio_summary_all.csv`: pooled summary when running all saved sessions.

The error CSV columns are:

| Fields | Meaning |
| --- | --- |
| `session_id`, `bus_id`, `route_id` | Collection session and bus/route identity |
| `stop_id`, `route_stop_position` | Target physical stop and route occurrence |
| `checkpoint_stop_id`, `checkpoint_route_stop_position` | Upstream checkpoint identity |
| `checkpoint_at`, `checkpoint_previous_observed_at` | Checkpoint estimated arrival and its preceding accepted observation |
| `checkpoint_arrival_method` | `near_stop` or `between_samples` at the checkpoint |
| `stops_ahead` | Number of route steps from checkpoint to target |
| `prediction_observed_at`, `predicted_arrival_at` | When the prediction was received and what arrival time it predicted |
| `estimated_arrival_at`, `target_previous_observed_at` | Target estimated arrival and its preceding accepted observation |
| `arrival_method` | Target arrival method |
| `error_seconds`, `absolute_error_seconds` | Signed and absolute timestamp difference |

IDs are strings; times are timezone-aware ISO timestamps. CSV cells are text,
so scripts convert numeric columns when reading them. Coverage rows contain the
checkpoint/target identities, checkpoint times/method, stops ahead, and `status`.
Each summary row contains `stops_ahead`, `checkpoints`, `no_target_arrival`,
`no_prediction`, `ambiguous_prediction`, `count`, `mae_seconds`, and
`mean_error_seconds`. Here `count` is the number matched, and the four status
counts (including matched) sum to `checkpoints`.

A no-target row means no supported target arrival was available in that
continuous stretch. Coverage is relative to detected checkpoints, not all real
bus visits. The result count is evaluated checkpoint/target pairs, not a count
of independent buses or trips. Each target visit can appear in several different
stops-ahead groups; do not pool them and claim independent samples.

Rerunning replaces derived evaluation outputs. Summary means weight selected
pairs equally, not sessions equally. A `--session-id` run updates that session's
summary and does not replace the all-sessions summary.

For a future model comparison, use the same checkpoint/target pairs and only
information available by the checkpoint to generate model predictions. Compare
models on their shared evaluated pairs. Split regression training/test data by
collection time or trips, rather than randomly splitting repeated observations
from the same visit. These evaluation CSVs are not a training-data generator.

## Plots

After evaluation, run:

```bash
.venv/bin/python -m shuttle_analysis.evaluation.plot_evaluation
```

The script reads `results/evaluation/passio/summaries/passio_summary_all.csv`
and saves a three-panel figure as `passio_summary_all.png` and `passio_summary_all.pdf` in
`results/evaluation/passio/plots/`. The panels show mean absolute error, mean
signed error, and stacked checkpoint coverage.
Error axes use seconds. Negative signed error means an earlier prediction.
Point labels show evaluated pair counts; empty groups have missing error values,
not zero error. No confidence intervals or independent-trip claims are made.

For a session or another model's summary with the same columns:

```bash
.venv/bin/python -m shuttle_analysis.evaluation.plot_evaluation --summary results/evaluation/passio/summaries/passio_summary_<session-id>.csv
```

Use `--output-dir <folder>` to choose another plot directory.
`plot_summary(rows, output)` can also be called directly. Plotting reads derived
summaries only and does not rerun collection or evaluation. It requires
Matplotlib, listed in `requirements.txt`. Rerunning replaces only the figure
files. Counts and means are those of the input summary; models should be compared
on the same checkpoint/target pairs.

## Error at each stop by stops away

```bash
.venv/bin/python -m shuttle_analysis.evaluation.plot_stop_errors
# Optional: one session
.venv/bin/python -m shuttle_analysis.evaluation.plot_stop_errors --session-id <session-id>
```

The chart summarizes each stop at each prediction distance. Each row identifies a
target stop by route number, name, and ID. The four columns show predictions
selected 1, 2, 3, and 4 stops before that target. Each cell shows mean absolute
error in minutes and its evaluated comparison count. Lower values mean smaller
errors. Grey cells mean no data, rather than zero error.

The default chart pools all per-session error CSVs, weighting comparisons equally.
Route identity and saved route order must agree; otherwise select one session.
It writes `passio_stop_mae_all.png` and `.pdf` in
`results/evaluation/passio/plots/stops/`. A session selection uses its ID in the
filename. No raw observations or evaluation CSVs are modified. The repeated
boundary stop is one row labeled 1/11; Silber Way is evaluated like other stops.
Counts can differ by column, and comparisons can share a target visit. These are
descriptive errors against GPS-estimated arrivals, not verified ground truth.

## Route stop map

```bash
.venv/bin/python -m shuttle_analysis.evaluation.plot_stop_map
# Optional: one session
.venv/bin/python -m shuttle_analysis.evaluation.plot_stop_map --session-id <session-id>
```

The script uses saved route coordinates and evaluation error CSVs. It writes
`passio_stop_map_all.html`, `.png`, and `.pdf` in
`results/evaluation/passio/plots/maps/` (or a session-specific basename).
The HTML is self-contained, works offline, and has a selector for all horizons
or 1, 2, 3, and 4 stops ahead. The PNG/PDF show the pooled view. No background
map tiles, API requests, or new dependencies are used.

Stop numbers follow the saved route order. The map key includes each number,
stop ID, name, mean absolute error in minutes, and evaluated comparison count.
The repeated first/end stop is shown once as 1/11. Colors have a fixed scale
across the five views: darker means larger error, grey means no evaluated data.
Silber Way uses the same coloring rules as other stops; it is grey only when
the selected view has no evaluated comparisons.

The pooled view mixes prediction distances and is descriptive. Compare stops at
the same stops-ahead setting and consider sample counts before calling a stop
worse. These are errors against GPS estimates, not verified ground truth.
The saved stop coordinates are shown as supplied, including any placement offset
from the route. Route shape and order must agree across pooled sessions;
otherwise use separate session maps.

## Keeping figures current

Evaluation regenerates its CSVs but does not automatically regenerate plots.
Run the plotting commands again after evaluation. The overall plot reads the
selected summary; the stop chart and map pool the per-session error CSVs by
default. Running evaluation for one session leaves other sessions' CSVs and the
all-session summary unchanged. To refresh a consistent all-session view, rerun
evaluation without `--session-id`, then rerun all three plotting commands.

Stop and map plots retain no-data cells instead of inventing zero error. The
1–4-stop checkpoint policy is fixed in the command-line runner; the matching
function exposes `max_stops` and `max_age_seconds` for deliberate code-level
experiments. Checkpoint distances must be less than one full route loop.
