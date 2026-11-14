#!/usr/bin/env python3
"""Generate simulated trips, keeping them separate from the real data."""
import argparse
import csv
import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from calibration import calibrate
from model import DEFAULT_SETTINGS, dump_json, day_context, write_day
from shuttle_analysis.route_config import PROJECT_ROUTE_IDS


MANIFEST_FIELDS = ['service_date', 'route_id', 'session_id', 'data_dir', 'gps_requests',
                   'eta_requests', 'gps_failures', 'eta_failures', 'stale_fixes',
                   'missing_bus_fixes', 'trips', 'truth_arrivals', 'first_observed_at',
                   'last_observed_at', 'synthetic']


def date_range(cfg):
    start, end = date.fromisoformat(cfg['start_date']), date.fromisoformat(cfg['end_date'])
    if end < start:
        raise ValueError('end_date precedes start_date')
    if cfg['poll_seconds'] <= 0 or cfg['poll_seconds'] > 60:
        raise ValueError('poll_seconds must be in (0, 60] for the existing detector')
    return start, end


def run(cfg, output, real_dir, calibration_dir=None):
    start, end = date_range(cfg)
    output, real_dir = Path(output).resolve(), Path(real_dir).resolve()
    # Even an explicit CLI path cannot put synthetic output in the real collection.
    if not output.is_relative_to(HERE) or output == HERE:
        raise ValueError('Simulation output must be a new subdirectory of trip simulation')
    if output == real_dir or output.is_relative_to(real_dir) or real_dir.is_relative_to(output):
        raise ValueError('Synthetic and real data locations must not overlap')
    if output.exists():
        raise FileExistsError(f'{output} already exists; choose a new --output directory')
    output.mkdir(parents=True)
    dump_json(output / 'assumptions.json', cfg)
    if calibration_dir:
        calibration_dir = Path(calibration_dir)
        report = json.loads((calibration_dir / 'calibration.json').read_text())
        raw = json.loads((calibration_dir / 'route_metadata.json').read_text())
        (output / 'calibration').mkdir()
        for name in ['calibration.json', 'route_metadata.json']:
            shutil.copyfile(calibration_dir / name, output / 'calibration' / name)
    else:
        report, raw = calibrate(real_dir, output / 'calibration', cfg)
    totals = {key: 0 for key in ['sessions', 'trips', 'gps_requests', 'eta_requests', 'truth_arrivals']}
    per_route = {rid: dict(totals) for rid in PROJECT_ROUTE_IDS}
    with (output / 'manifest.csv').open('w', newline='') as file, \
         (output / 'calendar.csv').open('w', newline='') as context_file:
        manifest = csv.DictWriter(file, fieldnames=MANIFEST_FIELDS)
        manifest.writeheader()
        calendar_writer = csv.DictWriter(context_file, fieldnames=['date', 'weekday', 'holiday',
            'academic_break', 'weather_scenario', 'day_factor', 'weather_is_observed'])
        calendar_writer.writeheader()
        day = start
        number = 0
        while day <= end:
            context = day_context(day, cfg)
            calendar_writer.writerow(context)
            for rid in PROJECT_ROUTE_IDS:
                folder = output / 'data' / str(day) / rid
                row = write_day(folder, day, rid, raw, report['profiles'][rid], context, cfg)
                if row:
                    row['data_dir'] = str(folder.relative_to(output))
                    manifest.writerow(row)
                    totals['sessions'] += 1
                    per_route[rid]['sessions'] += 1
                    for key in ['trips', 'gps_requests', 'eta_requests', 'truth_arrivals']:
                        totals[key] += row[key]
                        per_route[rid][key] += row[key]
            number += 1
            if number % 30 == 0 or day == end:
                file.flush()
                context_file.flush()
                print(f'{number} service dates through {day}: {totals["trips"]:,} trips, '
                      f'{totals["eta_requests"]:,} ETA requests', flush=True)
            day += timedelta(days=1)
    summary = {'synthetic': True, 'complete': True, 'start_service_date': str(start),
               'end_service_date': str(end), 'calendar_days': (end - start).days + 1,
               'seed': cfg['seed'], 'totals': totals, 'routes': per_route,
               'calibration_sessions': report['training_sessions'],
               'held_out_real_sessions': report['held_out_sessions'],
               'note': 'Scenario data, not reconstructed historical observations or actual Passio forecasts.'}
    dump_json(output / 'summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=HERE / 'assumptions.json')
    parser.add_argument('--output', type=Path, default=HERE / 'generated')
    parser.add_argument('--real-data', type=Path, default=HERE.parent / 'data')
    parser.add_argument('--calibration-dir', type=Path, help='Reuse saved travel and stop-time estimates')
    parser.add_argument('--start-date', help='Override the first inclusive service date')
    parser.add_argument('--end-date', help='Override the last inclusive service date')
    args = parser.parse_args()
    cfg = {**DEFAULT_SETTINGS, **json.loads(args.config.read_text())}
    for name in ('start_date', 'end_date'):
        if getattr(args, name):
            cfg[name] = getattr(args, name)
    run(cfg, args.output, args.real_data, args.calibration_dir)


if __name__ == '__main__':
    main()
