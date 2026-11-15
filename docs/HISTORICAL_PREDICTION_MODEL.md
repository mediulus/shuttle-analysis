# Historical Prediction Model — Design

Status: **design only, nothing implemented.**

Given a route, a position on it and a time, the model predicts the seconds until
the bus reaches each of its next four stops. It learns typical travel times from
past trips, weather and campus activity, using gradient-boosted trees.

This is the *historical* term of the combined model in
[LIVE_PREDICTION.md](LIVE_PREDICTION.md). Community data enters here as features,
not as a separate third term:

ETA_predicted = w1 * (historical) + w2 * (current)

## Decisions

| Question | Decision |
| --- | --- |
| What is predicted | Travel time of each leg and dwell at each stop, summed into the four ETAs |
| Output | One time for each stop: the average the model expects |
| Algorithm | Gradient-boosted trees (scikit-learn) |
| Weather on simulated days | The simulator's own scenario, not real weather |
| Test data | Real trips only: every session the simulator was not calibrated on |

## Data

Dates are UTC.

| Data | Period | Size | Used for |
| --- | --- | --- | --- |
| Simulated trips, `trip simulation/generated/` | Nov 12, 2024 – Nov 11, 2026 | 15,513 trips, about 149,000 stop arrivals | Training |
| Real sessions the simulator was calibrated on (6) | Nov 5–11, 2026 | 268 stop arrivals | Training |
| Real sessions the simulator never saw: 4 held-out, Megan's `ff9db9e6`, April's 3 trial sessions | Nov 11–14, 2026 | 259 stop arrivals | Testing only |
| KBOS weather, `data/historical_weather/` | Nov 13, 2021 – Nov 12, 2026 | 52,339 observations | Features on real rows |
| Community events, `mit_comunity_events/` | 2019 – 2027 | Games, calendar, classes, practice | Features on real rows |

The simulator was calibrated only on the six training sessions, so nothing from
the test sessions reaches training.

**Rule for simulated rows.** A feature must describe the conditions that produced
the travel time:

- Conditions the simulator generated (weather scenario, holiday, break) come from
  its own `calendar.csv`.
- Conditions it did not model (temperature, wind, visibility, games, classes,
  practice) are left missing, so only real rows teach those effects.

## Training rows

One row is one bus driving one leg (leg model) or visiting one stop (dwell model).
Labels use the live model's definitions and the existing arrival and dwell
detectors, for real and simulated sessions alike:

```text
leg time  T_i = arrival at stop i − last time seen inside stop i−1
dwell     d_i = last time seen inside stop i − arrival at stop i
```

A dwell plus the leg after it always equals the exact arrival-to-arrival time. A
dwell that 30 s polling records as 0 is therefore still counted, inside the leg,
and the live model's 30 s dwell floor is not needed here.

Both models predict the average, because averages add up correctly across legs.
A middle value would not: 75% of real dwells are recorded as 0 s but the average
is 23 s, so a middle value would drop dwell from every sum.

## Features

Example: route 71342, leg 1 (Mass Ave @ Beacon St → 487 Comm. Ave.), Friday
Nov 6, 2026 at 5:58 PM Boston time. All values are real.

| Feature | Example | Real rows | Simulated rows |
| --- | --- | --- | --- |
| `route_id`, `leg_id` (categories) | 71342, leg 1 | Session metadata | Same |
| `leg_length_m` | 426 | Session metadata | Same |
| `minutes_since_midnight` | 1078 | Timestamp, Boston time | Same |
| `weekday` (Mon = 0) | 4 | Timestamp | Same |
| `is_holiday` | 0 | `academic_calendar.csv` | `calendar.csv` |
| `term_period` (category) | term | `academic_calendar.csv`: term, exams, IAP, break, summer | `calendar.csv`, no exams |
| Weather, six columns | See below | KBOS | Scenario |
| `home_game_starting_60min` | 2 | `sports_games.csv`, home games only | Missing |
| `home_game_ended_60min` | 0 | Same; assumes a game lasts 2 hours | Missing |
| `classes_ending_15min` | 0 (76 at 5:00 PM) | `class_meetings.csv`, in term only | Missing |
| `practice_block` | 1 | `practice_blocks.csv` | Missing |
| `is_synthetic` | 0 | 0 | 1 |

## Weather encoding

Weather needs no numeric encoding. It goes into the model as six plain columns,
and the trees learn from the training rows how many seconds each condition adds.
The only preparation is turning the weather station's shorthand into those columns.

### The six columns

| Column | Values | Kind |
| --- | --- | --- |
| `precip_type` | none, drizzle, rain, snow, ice | Label |
| `precip_intensity` | 0 none, 1 light, 2 moderate, 3 heavy | Ordered number |
| `low_visibility` | 1 in mist or fog, otherwise 0 | Yes/no |
| `wet_last_3h` | 1 if anything fell in the past 3 hours, otherwise 0 | Yes/no |
| `temperature_c` | As recorded | Number |
| `wind_speed_kmh` | As recorded | Number |

Humidity and pressure are not used.

### Real rows: reading the station's report

Each row uses the latest report from Boston Logan (KBOS) at or before the row's
start time. If that report is more than 2 hours old, all six columns are missing.
A later report is never used: at prediction time it would not exist yet.

The station writes dry weather in words and wet weather in a standard shorthand:

| The station writes | It means | What is stored |
| --- | --- | --- |
| Clear, Mostly Clear, Partly Cloudy, Mostly Cloudy, Overcast | Dry | `precip_type` = none, `precip_intensity` = 0 |
| `RA` | Rain | `precip_type` = rain |
| `DZ` | Drizzle | `precip_type` = drizzle |
| `SN` | Snow | `precip_type` = snow |
| `FZRA`, `FZDZ`, `PL` | Freezing rain, freezing drizzle, ice pellets | `precip_type` = ice |
| `-` in front | Light | `precip_intensity` = 1 |
| Nothing in front | Moderate | `precip_intensity` = 2 |
| `+` in front | Heavy | `precip_intensity` = 3 |
| `BR`, `FG` | Mist, fog | `low_visibility` = 1 |

A mix takes the most severe type: ice, then snow, then rain, then drizzle.
Anything else, such as haze or thunder without rain, counts as dry.

| The station writes | It means | `precip_type` | `precip_intensity` | `low_visibility` |
| --- | --- | --- | --- | --- |
| Mostly Clear | Dry | none | 0 | 0 |
| `BR` | Mist | none | 0 | 1 |
| `-RA` | Light rain | rain | 1 | 0 |
| `-RA BR` | Light rain and mist | rain | 1 | 1 |
| `+RA BR` | Heavy rain and mist | rain | 3 | 1 |
| `-SN` | Light snow | snow | 1 | 0 |
| `-RASN` | Light rain and snow mixed | snow | 1 | 0 |
| `-FZRA` | Light freezing rain | ice | 1 | 0 |

A real example:

```text
Leg starting Friday Nov 6, 2026 at 5:58 PM Boston time (22:58 UTC)

Station reports (UTC)    temp °C   wind km/h
21:54   -RA               17.22      9.26
22:54   +RA BR            18.33     11.11    ← latest before 22:58, used
23:11   RA BR             18.33     11.11    ← later, ignored

Stored:  precip_type = rain     precip_intensity = 3    low_visibility = 1
         wet_last_3h = 1        temperature_c = 18.33   wind_speed_kmh = 11.11
```

### Simulated rows

The simulator gives each service date one scenario for the whole day. Look it up
in `calendar.csv` by the session's service date.

| Simulator scenario | `precip_type` | `precip_intensity` | `wet_last_3h` |
| --- | --- | --- | --- |
| clear | none | 0 | 0 |
| rain | rain | 2 | 1 |
| heavy_rain | rain | 3 | 1 |
| snow | snow | 2 | 1 |

`low_visibility`, `temperature_c` and `wind_speed_kmh` are missing.

### How gradient boosting uses the columns

The model is a few hundred small trees. Each tree asks a few yes/no questions
about a row and adds or subtracts seconds. The weather columns go straight into
those questions:

| Kind of column | Question a tree can ask |
| --- | --- |
| Label | "Is `precip_type` snow or ice?" (is the label in this group) |
| Ordered number | "Is `precip_intensity` at least 2?" (is the value above this cut point) |
| Missing value | Each question also learns which branch rows with a missing value take |

```text
One tree (illustrative numbers):

Is precip_type snow or ice?
├─ yes → +25 s
└─ no  → Is precip_intensity at least 2?
         ├─ no  → −2 s
         └─ yes → Is it after 4 PM?
                  ├─ no  → +6 s
                  └─ yes → +14 s     ← the 5:58 PM heavy-rain leg above
```

- **The numbers only carry order.** A tree only asks whether a value is above a
  cut point, so storing intensity as 0, 10, 20, 30 would give the same model.
  Nothing is scaled, and labels are never turned into numbers.
- **The seconds are learned, not set.** Training picks the questions and the
  seconds that best fit past trips. Nobody writes "rain adds 12%" by hand.

## Making a prediction

```text
Input: route, position x along the route (m), time t

1. Find the next four stops s1..s4 and the share of the current leg left, r / L1.
2. Build one feature row for each upcoming leg and stop; predict T_i and d_i.
   Each row uses the time the bus is predicted to get there, starting from t.
3. ETA(s1) = T1 · (r / L1)
   ETA(sk) = ETA(s(k−1)) + d(k−1) + Tk          for k = 2..4
   Bus inside a stop area: first add max(0, d − time already spent).
```

## Training and evaluation

- **Training.** Simulated and real training rows together. Real rows get extra
  weight. The weight and the number of trees are chosen by leaving out one real
  training session at a time.
- **Baseline.** The average leg time and dwell for each leg and hour of the week,
  from the same rows. The model has to beat it.
- **Test.** Replay the real test sessions and score them with the existing
  checkpoint evaluator ([ETA_EVALUATION.md](ETA_EVALUATION.md)), so the results
  line up with the live model and Passio on the same pairs.
- **Reported.** MAE and bias by stops ahead.

## Moving to real data

The feature code does not change. As real rows accumulate, simulated rows are
down-weighted and then dropped, and `is_synthetic` goes with them.

## Limits and open items

- **The first version mostly relearns the simulator.** Over 99% of training rows
  are simulated, so the model mainly recovers the settings in `assumptions.json`.
  Game, class, temperature, wind and visibility effects rest on 268 real arrivals
  and are not expected to help yet.
- **Weather stops at Nov 12, 2026 19:54 UTC.** Re-run the scraper before testing
  on Nov 13–14. It currently writes to `data/data/`, not where the file is committed.
- **Megan's Nov 13–14 rows are on `main` only.** Where historical data and live
  trial data are stored is undecided.
- **Games have no venue,** and 1,416 of 5,637 have no start time and are skipped.
- **New dependency:** `scikit-learn`.
