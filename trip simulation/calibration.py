"""Estimate travel and stop times from our real data, saving newer days for comparison."""
import csv
import io
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from model import dump_json, LOCAL
from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from shuttle_analysis.processing.dwell.dwell_detector import DwellDetector
from shuttle_analysis.processing.shared.routes import route_snapshot
from shuttle_analysis.processing.shared.vehicle_positions import matched_positions
from shuttle_analysis.route_config import PROJECT_ROUTE_IDS


def read_rows(path):
    """Read a complete snapshot while the collector may still be appending rows."""
    with path.open('rb') as file:
        data = file.read(path.stat().st_size)
    if data and not data.endswith(b'\n'):
        data = data[:data.rfind(b'\n') + 1]
    return list(csv.DictReader(io.StringIO(data.decode())))


def median(values, fallback):
    return statistics.median(values) if values else fallback


def slim_metadata(snapshot):
    raw = snapshot['metadata']['stop_metadata']
    stop_ids = {str(sid) for rid in PROJECT_ROUTE_IDS for _, sid, _ in raw['routes'][rid][2:]}
    return {'routes': {rid: raw['routes'][rid] for rid in PROJECT_ROUTE_IDS},
            'routePoints': {rid: raw['routePoints'][rid] for rid in PROJECT_ROUTE_IDS},
            'stops': {key: value for key, value in raw['stops'].items() if str(value['id']) in stop_ids}}


def calibrate(real_dir, output_dir, cfg):
    real_dir, output_dir = Path(real_dir), Path(output_dir)
    rows = read_rows(real_dir / 'bus_positions.csv')
    snapshots = {}
    for path in sorted((real_dir / 'sessions').glob('*.json')):
        blob = path.read_bytes()
        snapshot = json.loads(blob)
        if snapshot['metadata'].get('synthetic'):
            continue
        snapshots[snapshot['session_id']] = snapshot
    groups = defaultdict(list)
    all_dates = set()
    for row in rows:
        if row['session_id'] not in snapshots:
            continue
        timestamp = datetime.fromisoformat(row['request_started_at'])
        all_dates.add(timestamp.astimezone(LOCAL).date())
        groups[row['session_id']].append(row)
    dates = sorted(all_dates)
    if len(dates) <= cfg['holdout_latest_local_dates']:
        raise ValueError('Not enough real collection dates to reserve the requested holdout')
    cutoff = dates[-cfg['holdout_latest_local_dates']]
    training, heldout, splits = [], [], []
    for sid, session_rows in groups.items():
        local_dates = [datetime.fromisoformat(r['request_started_at']).astimezone(LOCAL).date() for r in session_rows]
        reserved = max(local_dates) >= cutoff
        (heldout if reserved else training).append(sid)
        splits.append({'session_id': sid, 'role': 'held_out_real_evaluation' if reserved else 'calibration',
                       'first_local_date': str(min(local_dates)), 'last_local_date': str(max(local_dates)),
                       'gps_requests': len(session_rows)})
    if not training:
        raise ValueError('No calibration sessions remain')
    pools = {rid: {'speeds': [], 'edges': defaultdict(list), 'dwell': defaultdict(list)} for rid in PROJECT_ROUTE_IDS}
    total_gps = failed_gps = 0
    for sid in sorted(training):
        observations = []
        for row in groups[sid]:
            total_gps += 1
            failed_gps += bool(row['error'])
            observations.append({**row, 'request_type': 'vehicles', 'error': row['error'] or None,
                                 'response_received_at': row['response_received_at'] or None,
                                 'data': json.loads(row['data'])})
        for rid in PROJECT_ROUTE_IDS:
            selected = route_snapshot(snapshots[sid], rid)
            detector = ArrivalDetector(selected)
            pool = pools[rid]
            runs, fix_runs = {}, {}
            for bus, _, timestamp, progress, previous in matched_positions(observations, detector):
                if previous is None:
                    runs[bus] = runs.get(bus, 0) + 1
                fix_runs[(bus, timestamp.isoformat())] = runs[bus]
                if previous:
                    dt = (timestamp - previous['time']).total_seconds()
                    delta = progress - previous['progress']
                    near = min(min(abs(progress % detector.length - stop['progress'] % detector.length),
                                   detector.length - abs(progress % detector.length - stop['progress'] % detector.length))
                               for stop in detector.stops) < 30
                    if dt > 0 and delta >= 10 and not near and 0.5 <= delta / dt <= 15:
                        pool['speeds'].append(delta / dt)
            dwells = DwellDetector(selected).detect(observations)
            spans = {(v['bus_id'], v['estimated_arrival_at']): v['observed_dwell_seconds'] for v in dwells}
            for dwell in dwells:
                if 0 <= dwell['observed_dwell_seconds'] <= 180:
                    pool['dwell'][dwell['route_stop_position']].append(dwell['observed_dwell_seconds'])
            visits = defaultdict(list)
            for arrival in detector.detect(observations):
                key = (arrival['bus_id'], arrival['estimated_arrival_at'])
                run = fix_runs.get(key)
                if run is not None:
                    visits[(arrival['bus_id'], run)].append(arrival)
            stop_order = {stop['position']: i for i, stop in enumerate(detector.stops)}
            for visits_in_run in visits.values():
                visits_in_run.sort(key=lambda v: v['estimated_arrival_at'])
                for first, second in zip(visits_in_run, visits_in_run[1:]):
                    a, b = stop_order[first['route_stop_position']], stop_order[second['route_stop_position']]
                    if (b - a) % len(stop_order) != 1:
                        continue
                    elapsed = (datetime.fromisoformat(second['estimated_arrival_at'])
                               - datetime.fromisoformat(first['estimated_arrival_at'])).total_seconds()
                    road = (detector.stops[b]['progress'] - detector.stops[a]['progress']) % detector.length
                    stationary_proxy = max(0, spans.get((first['bus_id'], first['estimated_arrival_at']), 0)
                                           - 60 / cfg['fallback_speed_mps'])
                    running = elapsed - stationary_proxy
                    if running > 0 and 0.5 <= road / running <= 15 and elapsed < 1800:
                        pool['edges'][second['route_stop_position']].append(running)
    eta_counts = {rid: [0, 0] for rid in PROJECT_ROUTE_IDS}
    for name in ('eta_predictions.csv', 'eta_predictions_by_route.csv'):
        path = real_dir / name
        if not path.exists():
            continue
        eta_rows = read_rows(path)
        for row in eta_rows:
            if row['session_id'] not in training:
                continue
            rid = row.get('route_id') or '71342'
            if rid in eta_counts:
                eta_counts[rid][0] += 1
                eta_counts[rid][1] += bool(row['error'])
    base_snapshot = snapshots[sorted(training)[0]]
    raw = slim_metadata(base_snapshot)
    profiles = {}
    for rid in PROJECT_ROUTE_IDS:
        detector = ArrivalDetector(route_snapshot({'session_id': 'calibration', 'metadata': {
            'route_id': rid, 'stop_metadata': raw}}, rid))
        pool = pools[rid]
        speed = median(pool['speeds'], cfg['fallback_speed_mps'])
        edges = []
        previous_progress = 0.0
        for stop in detector.stops:
            position = stop['position']
            road = stop['progress'] - previous_progress
            travel_pool = pool['edges'][position]
            count = len(travel_pool)
            weight = count / (count + cfg['edge_shrinkage_samples'])
            expected = weight * median(travel_pool, road / speed) + (1 - weight) * road / speed
            # Stop-area spans are noisy proxies; subtract nominal traversal time.
            dwell_pool = [max(0.0, span - 60 / speed) for span in pool['dwell'][position]]
            dw_weight = len(dwell_pool) / (len(dwell_pool) + cfg['edge_shrinkage_samples'])
            dwell_mean = dw_weight * median(dwell_pool, cfg['fallback_dwell_seconds']) + (1 - dw_weight) * cfg['fallback_dwell_seconds']
            edges.append({'stop_id': stop['id'], 'position': position, 'progress_m': stop['progress'],
                          'distance_m': road, 'mean_running_seconds': expected,
                          'running_samples_seconds': travel_pool, 'running_sample_count': count,
                          'mean_dwell_seconds': dwell_mean, 'dwell_samples_seconds': dwell_pool})
            previous_progress = stop['progress']
        requests, failures = eta_counts[rid]
        profiles[rid] = {'name': raw['routes'][rid][0], 'route_length_m': detector.length,
                         'median_moving_speed_mps': speed, 'moving_speed_sample_count': len(pool['speeds']),
                         'moving_speeds_mps': pool['speeds'], 'stops': edges,
                         'gps_failure_probability': min(.08, failed_gps / max(1, total_gps)),
                         'eta_failure_probability': min(.08, failures / max(1, requests)),
                         'eta_calibration_requests': requests,
                         'eta_failure_fallback_used': requests == 0}
        if not requests:
            profiles[rid]['eta_failure_probability'] = .02
    report = {'training_sessions': sorted(training),
              'held_out_sessions': sorted(heldout), 'holdout_cutoff_local_date': str(cutoff),
              'session_split': splits, 'profiles': profiles,
              'limitations': ['Only a few November 2026 dates inform empirical priors.',
                             'Stop-area dwell estimates are sampling-dependent proxies.',
                             'ETA error behavior is assumed, not fitted to Passio residuals.',
                             'Route shapes and 2025–26 service rules are extrapolated backward.']}
    output_dir.mkdir(parents=True, exist_ok=True)
    dump_json(output_dir / 'calibration.json', report)
    dump_json(output_dir / 'route_metadata.json', raw)
    return report, raw
