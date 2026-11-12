"""Draw a simple explanation of the simulation using its saved settings and trips."""
import csv
import gzip
import json
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from matplotlib.figure import Figure
from matplotlib.colors import ListedColormap
from model import LOCAL, service_window

DATA = HERE / 'generated'
cfg = json.loads((DATA / 'assumptions.json').read_text())
blue, orange, muted = '#32618c', '#d87936', '#64748b'
figure = Figure(figsize=(13, 10), layout='constrained', facecolor='#fafbfc')
grid = figure.add_gridspec(2, 2, height_ratios=[1, 1.2])
calendar_axis = figure.add_subplot(grid[0, 0])
example_axis = figure.add_subplot(grid[0, 1])
trip_axis = figure.add_subplot(grid[1, :])
figure.suptitle('What the trip simulation does', fontsize=21, fontweight='bold')

# 1: A holiday changes which routes run.
days = [date(2025, 11, 10) + timedelta(days=i) for i in range(7)]
routes = ['71342', '70113']
windows = [[service_window(day, rid) for day in days] for rid in routes]
calendar_axis.imshow([[int(window is not None) for window in row] for row in windows],
                     cmap=ListedColormap(['#e5e7eb', '#d8e9f3']), vmin=0, vmax=1, aspect='auto')
calendar_axis.set_xticks(range(7), [day.strftime('%a\n%b %d') for day in days], fontsize=9)
calendar_axis.set_yticks([0, 1], ['Boston\nDaytime', 'Boston\nEast'], fontsize=10)
for row in range(2):
    for column in range(7):
        window = windows[row][column]
        text = 'OFF'
        if window:
            text = '9–6' if row == 0 and days[column].weekday() == 5 else '7:30–5:45' if row == 0 else '6–1'
        calendar_axis.text(column, row, text, ha='center', va='center', fontsize=8,
                           color=blue if window else muted, fontweight='bold')
calendar_axis.set_title('1. Decide when each route runs', loc='left', fontsize=14, pad=15)
calendar_axis.text(0, -.24, 'Nov 11 is a modeled holiday: Daytime is off.\nBlue = service; grey = no service. Times are local.',
                   transform=calendar_axis.transAxes, va='top', fontsize=10, color=muted)
calendar_axis.set_xticks([i - .5 for i in range(8)], minor=True)
calendar_axis.set_yticks([-.5, .5, 1.5], minor=True)
calendar_axis.grid(which='minor', color='white', linewidth=3)
calendar_axis.tick_params(which='minor', bottom=False, left=False)

# 2: These bars isolate the chosen factors, before random variation.
values = [5, 5 * cfg['pm_peak_multiplier'], 5 * cfg['weather_multipliers']['rain'],
          5 * cfg['pm_peak_multiplier'] * cfg['weather_multipliers']['rain']]
labels = ['Normal', 'Afternoon rush', 'Rain', 'Rush + rain']
bars = example_axis.barh(labels, values, color=[blue, '#dca66d', '#85aec7', orange], height=.58)
example_axis.invert_yaxis()
example_axis.set_xlim(0, 9)
example_axis.set_xlabel('Minutes to drive the same segment')
example_axis.set_title('2. Adjust a normal 5-minute drive', loc='left', fontsize=14, pad=15)
for bar, value in zip(bars, values):
    example_axis.text(value + .12, bar.get_y() + bar.get_height() / 2, f'{value:.2f}', va='center', fontsize=11)
example_axis.text(0, -.24, 'Example: 5 × 1.30 × 1.12 = 7.28 minutes.\nThese factors are assumptions we can change.',
                  transform=example_axis.transAxes, va='top', fontsize=10, color=muted)

# 3: Read actual generated trip durations rather than inventing example points.
sample_day = '2025-11-04'
with gzip.open(DATA / f'data/{sample_day}/71342/ground_truth/trips.csv.gz', 'rt', newline='') as file:
    trips = list(csv.DictReader(file))
with (DATA / 'calendar.csv').open(newline='') as file:
    context = next(row for row in csv.DictReader(file) if row['date'] == sample_day)
hours, durations = [], []
for trip in trips:
    local = datetime.fromisoformat(trip['started_at']).astimezone(LOCAL)
    hours.append(local.hour + local.minute / 60)
    durations.append(float(trip['duration_seconds']) / 60)
trip_axis.plot(hours, durations, marker='o', markersize=7, color=blue, linewidth=1.6)
trip_axis.axvspan(7, 10, color=orange, alpha=.12, label='Rush-hour window')
trip_axis.axvspan(16, 19, color=orange, alpha=.12)
profile = json.loads((DATA / 'calibration/calibration.json').read_text())['profiles']['71342']
normal = sum(stop['mean_running_seconds'] + stop['mean_dwell_seconds'] for stop in profile['stops']) / 60
trip_axis.axhline(normal, color=muted, linestyle='--', linewidth=1.2, label=f'Starting average: {normal:.1f} min')
trip_axis.set_xlim(7, 18.5)
trip_axis.set_ylim(0, max(durations) * 1.18)
trip_axis.set_xticks([8, 10, 12, 14, 16, 18], ['8 a.m.', '10 a.m.', 'Noon', '2 p.m.', '4 p.m.', '6 p.m.'])
trip_axis.set_ylabel('Full loop duration (minutes)')
trip_axis.set_xlabel('Time the trip started')
trip_axis.set_title('3. A day from the generated data — Boston Daytime, Nov 4, 2025',
                    loc='left', fontsize=14, pad=34)
trip_axis.text(0, 1.025, f"{len(trips)} trips; this day's randomly selected weather was {context['weather_scenario'].replace('_', ' ')}.",
               transform=trip_axis.transAxes, fontsize=10, color=muted)
trip_axis.legend(loc='upper right', frameon=False, fontsize=10)
trip_axis.grid(axis='y', alpha=.18)
for axis in [example_axis, trip_axis]:
    axis.spines[['top', 'right']].set_visible(False)
    axis.set_axisbelow(True)
figure.supxlabel('Simulated examples. Day, trip, and stop-to-stop variation also affect the final times.',
                  fontsize=11, color=muted)
output = HERE / 'simulation_example.png'
figure.savefig(output, dpi=160)
print(output)
