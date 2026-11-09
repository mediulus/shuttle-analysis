# MIT Shuttle Analysis

Collect Passio GO predictions and GPS observations, estimate arrivals and stop
dwell, and compare predictions with GPS-estimated arrivals at 1–4-stop checkpoints.
The project uses small Python modules and saved CSVs so each step can be inspected.

Collection follows reported active Boston Daytime and Saferide routes. Arrival,
dwell, and checkpoint evaluation currently default to Boston Daytime; other routes
need reviewed stop-to-segment mappings. The regression model is not implemented.

## Layout

| Directory | Purpose |
| --- | --- |
| `shuttle_analysis/collection/` | API requests, route selection, and polling |
| `shuttle_analysis/processing/shared/` | Geometry, route matching, GPS validation, and stop segments |
| `shuttle_analysis/processing/arrivals/` | Estimated arrivals and CSV runner |
| `shuttle_analysis/processing/dwell/` | Observed time near stops and CSV runner |
| `shuttle_analysis/processing/predictions/` | Individual Passio predictions and CSV runner |
| `shuttle_analysis/evaluation/` | Checkpoint matching, reusable error calculations, runners, and plots |
| `shuttle_analysis/storage.py` | Raw observation and session persistence |
| `data/` | Collected CSVs and session metadata |
| `results/` | Generated CSVs and figures |
| `tests/` | Offline tests |
| `docs/` | Architecture and implementation guides |

```text
results/
├── arrivals/
├── dwell/
├── predictions/
└── evaluation/
    └── passio/
        ├── errors/
        ├── coverage/
        ├── summaries/
        └── plots/
            ├── passio_summary_all.png / .pdf
            ├── stops/     # Stop-by-stops-away MAE chart
            └── maps/      # Numbered route map and stop key
```

## Setup and commands

Run from `Project-Work/`. The local environment is `.venv`; for a new setup:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

```bash
# Collect live data. Stop with Ctrl+C.
.venv/bin/python -m shuttle_analysis.collection.collector

# Export arrivals, dwell, and predictions from saved sessions.
.venv/bin/python -m shuttle_analysis.processing.arrivals.review_arrivals
.venv/bin/python -m shuttle_analysis.processing.dwell.review_dwells
.venv/bin/python -m shuttle_analysis.processing.predictions.review_predictions

# Evaluate selected predictions at 1–4-stop checkpoints.
.venv/bin/python -m shuttle_analysis.evaluation.evaluate_passio

# Plot overall error, bias, and coverage.
.venv/bin/python -m shuttle_analysis.evaluation.plot_evaluation

# Plot MAE at each named stop, with columns for 1–4 stops away.
.venv/bin/python -m shuttle_analysis.evaluation.plot_stop_errors

# Create an offline route map with stop numbers, IDs, names, and errors.
.venv/bin/python -m shuttle_analysis.evaluation.plot_stop_map

# Run offline tests.
.venv/bin/python -m unittest discover -s tests -v
```

The processing runners and evaluator accept `--session-id <session-id>`; without
it they process sessions with saved metadata in `data/sessions/`. The stop chart
and map also accept this option. The overall plot selects a summary using
`--summary <path>`, rather than `--session-id`.

Stop collection before analyzing a session. Evaluation reads raw observations
and generates arrivals and predictions in memory, so the three CSV exports are
optional for evaluation. Run evaluation before plotting. Plots read the saved
evaluation CSVs; regenerate them after updating evaluation results.

## Data and results

Collected data, generated results, and the virtual environment are excluded from
Git. A fresh clone includes empty `data/` and `results/` directories. Collect a
new session or copy your existing local data into `data/` before running analysis.
The tests use synthetic data; the optional local research-session test is skipped
when its saved session is absent.

Each collector start creates a new session ID and metadata snapshot. Observations
append to raw CSVs in `data/`. Route-aware ETA requests use
`eta_predictions_by_route.csv`; readers also support historical
`eta_predictions.csv`. System-wide GPS responses go into `bus_positions.csv`.

Processing and evaluation write only derived files in `results/`. Rerunning a
step replaces its output files. Raw collection files and the unused
`data/actual_arrivals.csv` are not rewritten by analysis.

Arrivals are GPS-based estimates, not independently verified arrival times.
Silber Way (3042) uses outbound segment 114, on the same side of Commonwealth
Avenue as 487 Comm. Ave., and participates in arrival/dwell detection and ETA evaluation. Dwell means observed time
inside a stop area, not engine idle or guaranteed stationary time.

## Guides

- [System architecture](docs/ARCHITECTURE.md)
- [Arrival detection](docs/ARRIVAL_DETECTOR.md)
- [Dwell detection](docs/DWELL_DETECTOR.md)
- [Passio prediction extraction](docs/PREDICTION_EXTRACTOR.md)
- [Checkpoint evaluation and plots](docs/ETA_EVALUATION.md)
