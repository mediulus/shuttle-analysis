# Live Prediction Model — Design Summary

Status: **replay and evaluation implemented** in `live_prediction_model/`. Not yet hooked into the live collector; no TomTom data yet.

Every 30 seconds, the model takes each bus's live GPS position, the last bus's travel time and dwell at each stop, and TomTom's travel time for each leg, and outputs the predicted time in seconds until the bus reaches each of its next 1–4 stops.

## Goal

Predict when each active shuttle will arrive at its next 1–4 stops. These
predictions use only live data. Later they become the *current* term of the
combined model:

```text
ETA_predicted = w1 * (historical) + w2 * (current) + w3 * (community)
```

This folder covers only the **current** term. The historical and community
terms, and the weights w1–w3, come later, once there is data to fit them on.

## Update frequency

- Predictions update **every 30 seconds**, in step with the Passio vehicle poll.
  The bus's position drives most of the change in an ETA, and in 30 seconds a
  bus can cover a whole leg.
- TomTom traffic is still requested **every 5 minutes**. Between requests, each
  prediction uses the latest stored value and records how old it is.

## Inputs

| Source | Interval | Used for |
| --- | --- | --- |
| Passio vehicles (existing collector) | 30 s | Bus position along the route, and stop arrivals and dwell |
| Passio ETAs (existing collector) | 30 s | Comparison only, not a model input |
| TomTom routing (`live_traffic.py`) | 5 min | Travel time for each leg, with traffic |
| Session metadata | Once per session | Route shape, stops and their order, each stop's distance along the route |


## Definitions
x        bus position along the route loop (m)
s1..s4   next four stops, at positions p1..p4
Li       length of leg i (s(i-1) → si)  = pi - p(i-1)
r        distance left on the current leg = p1 - x

## Per-leg travel time
T_last     = last bus's travel time on leg i
             = arrival(si) - last time inside s(i-1)
T_tomtom   = latest TomTom travel time for leg i (refreshed every 5 min)
             TomTom follows the shuttle's route shape; leg times are read off its time along the loop
             skipped if older than 15 min, or if TomTom's leg length differs >25% from the shuttle's
T_fallback = Li / default_speed,  default_speed ≈ 5 m/s

T_i = Σ (w_s · T_s) / Σ w_s        over available sources s ∈ {last, tomtom, fallback}
t1  = T1 · (r / L1)                 partial current leg

## Dwell
d_i = last recorded dwell at stop si
      → else 30 s
If the bus is inside the stop area:  d = max(0, d_i - time already spent)

## ETA
ETA(s1) = t1
ETA(s2) = t1 + d1 + T2
ETA(s3) = t1 + d1 + T2 + d2 + T3
ETA(s4) = t1 + d1 + T2 + d2 + T3 + d3 + T4

## Run
```bash
# Collect TomTom leg times every 5 min (needs TOMTOM_API_KEY in .env) -> data/traffic_legs.csv
.venv/bin/python live_data_collection/collection/live_traffic.py
# All real sessions, scored against Passio on the same checkpoint/target pairs
.venv/bin/python -m live_prediction_model.evaluate_live
# Other settings (defaults: weights 0.45 / 0.45 / 0.1, 5 m/s, 30 s dwell)
.venv/bin/python -m live_prediction_model.evaluate_live --w-fallback 0 --default-speed-mps 4
# Simulated days instead of real sessions
.venv/bin/python -m live_prediction_model.evaluate_live --sim-day 2026-11-10
```
Outputs: `results/evaluation/live/` (errors, coverage, summaries, `live_vs_passio_all.csv`).
`--save-predictions` also writes every prediction.

## Open questions
- Live output: save to CSV in `results/`, or print only?
