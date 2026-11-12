# Saferide Boston East analysis

Collection and analysis include only these two routes:

| ID | Route |
| --- | --- |
| 71342 | Boston Daytime |
| 70113 | Saferide Boston East |

The collector requests ETAs only for these routes when their buses report active
service. GPS-failure fallback stays within the same two routes. Restart an existing
collector after changing the code so it loads the new configuration.

The GPS endpoint returns system-wide buses. Raw observations and metadata remain
intact, including older records of other routes. Arrival, dwell, prediction CSV
exports, ETA evaluation, and plots select only the two Boston routes. Shared stop
IDs never merge their histories.

## Boston East placements

`processing/shared/stop_segments.py` contains explicit assignments for Boston
East's saved 449-point shape. A geometry/order fingerprint prevents reuse after
an upstream change. These are preliminary geometry-based placements, not
field-verified boarding locations.

The shape ends about 33 m short of its start; analysis connects this small gap.
The repeated 120 Mass Ave stop is represented once, by its ending occurrence at
position 12. Actual API position labels are retained, including gaps. Silber Way
uses outbound segment 284 after 487 Commonwealth Ave; the nearby return pass does
not produce another arrival. Boston Daytime retains its existing table, including
Silber Way at segment 114.

Missing buses, failed GPS requests, route changes, ambiguous positions, or gaps
over 60 seconds reset history. Comparisons require same-route predictions received
at or before the checkpoint, at most 30 seconds old, with explicit fresh/in-service
flags. Earlier sessions collected Boston East GPS without its ETAs, so some
arrivals and dwells have no usable prediction comparisons. Missing evaluated data
stays missing rather than becoming zero error.

## Regenerate results

Prefer stopping collection before processing a stable session.

```bash
.venv/bin/python -m shuttle_analysis.processing.arrivals.review_arrivals
.venv/bin/python -m shuttle_analysis.processing.dwell.review_dwells
.venv/bin/python -m shuttle_analysis.processing.predictions.review_predictions
.venv/bin/python -m shuttle_analysis.evaluation.evaluate_passio
.venv/bin/python -m shuttle_analysis.evaluation.plot_evaluation
.venv/bin/python -m shuttle_analysis.evaluation.plot_stop_errors
.venv/bin/python -m shuttle_analysis.evaluation.plot_stop_map
```

Per-session errors and coverage contain only the selected routes. The pooled
summary combines them; use `passio_summary_by_route_all.csv` or individual
`passio_summary_route_<id>_all.csv` files for separate route comparisons.

All three plot commands accept `--route-id 70113` for Boston East or
`--route-id 71342` for Boston Daytime. Boston Daytime stop charts/maps retain their
existing filenames. Boston East uses `route_70113`, for example
`passio_stop_map_route_70113_all.html`. The stop chart and map also accept
`--session-id`; the summary plot accepts `--summary <path>`.

## Validation

The offline fixture contains only these two routes' public stop/shape metadata.
Tests cover route filtering, geometry changes, outbound Silber Way detection,
boundary deduplication, shared-stop prediction identity, preservation of raw
inputs, and separate plot inputs. Collector tests include unrelated routes to
verify that they are never selected for ETA polling.
