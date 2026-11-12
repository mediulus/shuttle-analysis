# Trip simulation

We don't have two years of real shuttle data, so this folder simulates trips for
**Boston Daytime** and **Saferide Boston East** using the data we have and a few
assumptions about traffic and service hours.

The existing dataset covers **November 12, 2024–November 11, 2026**. It has about
15,500 trips. It stays in `generated/`, separate from the real data in the main
`data/` folder.

[See a visual example](simulation_example.png) of the service calendar, travel-time
adjustments, and a day of generated trips.

## How it works

1. **Estimate travel and stop times from our real data.** We use GPS observations
   to estimate bus speeds, travel times between stops, and time spent near stops.
   When a stop has very little data, we blend its estimate with the route average.
   We save the newest real collection days for comparing models later.
2. **Generate trips along the actual route shapes.** Trips vary in speed and dwell
   time. A slow trip tends to stay slow across several stops, rather than each
   segment changing independently.
3. **Adjust for conditions.** Rush hours, rain, snow, and occasional delays make
   trips slower. Weekends, holidays, and school breaks change traffic or service.
4. **Write GPS and ETA records.** GPS is sampled every 30 seconds, with a little
   noise and occasional missing records. ETA predictions use average travel times
   plus some error; they don't look ahead at when the simulated bus will arrive.

Weather and traffic effects are assumptions, not actual weather or traffic from
those dates. The ETA records have the same structure as Passio's, but they're
simulated predictions. This data can help us train and experiment; we should still
use real trips to judge whether a model improves.

## Main assumptions

Edit `assumptions.json` to change these:

| Condition | Effect on travel time |
| --- | --- |
| Morning rush, 7–10 a.m. | 22% longer |
| Afternoon rush, 4–7 p.m. | 30% longer |
| Evening, 7–9 p.m. | 8% longer |
| Weekends | 10% shorter |
| Holidays | 15% shorter, when service runs |
| Rain / heavy rain / snow | 12% / 25% / 45% longer |
| Occasional extra delay | 45–300 seconds |

The simulation uses one bus per route. Boston Daytime runs on weekdays and some
academic-year Saturdays. Boston East runs in the evening during the academic
season. Summer and major breaks don't include Boston East fixed-route trips.
We approximate break dates and apply the same service rules across both years.
A bus can finish its last loop after the scheduled end of service.

The saved data uses these settings; changing the assumptions file affects future
runs, not the data already generated.

## Files

| File | What it's for |
| --- | --- |
| `simulate.py` | Run the simulation |
| `model.py` | Bus movement, calendars, traffic, weather, and ETA calculations |
| `calibration.py` | Estimate starting travel and stop times from real data |
| `analyze.py` | Run our existing analysis on a simulated day |
| `visualize.py` | Draw the example image |
| `assumptions.json` | Main settings to adjust |
| `generated/` | The two-year dataset and saved settings |

Inside `generated/`, `summary.json` has the totals, `manifest.csv` lists the
available days/routes and their folders, and `calendar.csv` lists the assumed
conditions. `calibration/` holds the travel-time estimates used to make the data.

Each day and route has a folder like this:

```text
generated/data/2025-11-04/70113/
├── bus_positions.csv.gz
├── eta_predictions_by_route.csv.gz
├── sessions/                    # Session metadata
└── ground_truth/                # Simulated arrivals and trip durations
```

The CSV columns and JSON fields match the real collection. The `.gz` ending just
means the files are compressed to save space; `CSVStorage` reads them directly.
Synthetic session and bus IDs start with `sim-`, and metadata labels the data as
synthetic. Keep those labels when using real and simulated examples together.
The `ground_truth` files are labels, not information a prediction model should see.

## Commands

Run these from the project folder. Generate another dataset with the current
assumptions, using a new output name:

```bash
.venv/bin/python 'trip simulation/simulate.py' --output 'trip simulation/new_run'
```

For a shorter run:

```bash
.venv/bin/python 'trip simulation/simulate.py' \
  --start-date 2025-11-04 --end-date 2025-11-04 \
  --output 'trip simulation/one_day'
```

To reuse the saved travel-time estimates instead of reading the real data again,
add `--calibration-dir 'trip simulation/generated/calibration'`.

Analyze an existing simulated day:

```bash
.venv/bin/python 'trip simulation/analyze.py' --day 2025-11-04
```

That saves results inside `generated/results/`. Add `--route-id 70113` for Boston
East or `--route-id 71342` for Boston Daytime. The normal project commands still
analyze only the real collection.

For modeling, read both datasets with `CSVStorage`, build the same features, and
keep a column saying whether each example is real or simulated. There's no need
to put the fake observations into the real CSVs.

## Schedule references

We used MIT's [shuttle schedule](https://web.mit.edu/facilities/transportation/docs/MITShuttlesSummary.pdf),
[Boston Daytime information](https://web.mit.edu/facilities/transportation/shuttles/tech_shuttle.html),
[SafeRide information](https://web.mit.edu/facilities/transportation/shuttles/safe_ride.html),
and [holiday calendar](https://hr.mit.edu/holidays) as starting points. The speed
adjustments, weather probabilities, and extra delays are our project assumptions.

To redraw the visual: `.venv/bin/python 'trip simulation/visualize.py'`.
