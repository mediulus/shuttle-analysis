"""Trip movement, service hours, and simple traffic/weather adjustments."""
import bisect
import csv
import gzip
import hashlib
import io
import json
import math
import random
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from shuttle_analysis.processing.arrivals.review_arrivals import ARRIVAL_FIELDS
from shuttle_analysis.storage import CSV_FIELDS, ROUTE_CSV_FIELDS

# Smaller implementation settings; the main assumptions are in assumptions.json.
DEFAULT_SETTINGS = {'version': '1.0',
 'timezone': 'America/New_York',
 'buses_per_route': 1,
 'edge_shrinkage_samples': 5,
 'fallback_speed_mps': 4.0,
 'fallback_dwell_seconds': 12.0,
 'day_log_sigma': 0.1,
 'trip_log_sigma': 0.12,
 'segment_log_sigma': 0.1,
 'gps_noise_meters': 3.0,
 'gps_outlier_probability': 0.001,
 'missing_bus_probability': 0.002,
 'stale_probability': 0.003,
 'outage_start_probability': 0.0005,
 'outage_seconds_range': [60, 180],
 'forecast_context_response': 0.5,
 'forecast_fractional_bias': -0.05,
 'forecast_noise_base_seconds': 15,
 'forecast_noise_fraction': 0.05,
 'forecast_trip_log_sigma': 0.08,
 'gzip_compresslevel': 3}


def rng_for(seed, *parts):
    digest = hashlib.sha256(':'.join(map(str, (seed, *parts))).encode()).digest()
    return random.Random(int.from_bytes(digest[:16], 'big'))


def dump_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


@contextmanager
def compressed_text(path, level=3):
    """Exclusive creation and fixed gzip metadata make seeded exports reproducible."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', compresslevel=level, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding='utf-8', newline='') as text:
                yield text


LOCAL = ZoneInfo('America/New_York')


def nth_weekday(year, month, weekday, n):
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def holiday_dates(year):
    """MIT recurring holidays plus an explicitly assumed year-end closure."""
    result = {}
    for month, day, name in [(1, 1, 'New Year'), (6, 19, 'Juneteenth'),
                             (7, 4, 'Independence Day'), (11, 11, 'Veterans Day'),
                             (12, 25, 'Christmas')]:
        actual = date(year, month, day)
        result[actual] = name
        observed = actual + timedelta(days=-1 if actual.weekday() == 5 else 1 if actual.weekday() == 6 else 0)
        result[observed] = name + ' (observed)'
    for month, weekday, n, name in [(1, 0, 3, 'MLK Day'), (2, 0, 3, 'Presidents Day'),
                                   (4, 0, 3, 'Patriots Day'), (9, 0, 1, 'Labor Day'),
                                   (10, 0, 2, 'Indigenous Peoples Day'), (11, 3, 4, 'Thanksgiving')]:
        result[nth_weekday(year, month, weekday, n)] = name
    last_may = date(year, 5, 31)
    result[last_may - timedelta(days=last_may.weekday())] = 'Memorial Day'
    result[nth_weekday(year, 11, 3, 4) + timedelta(days=1)] = 'Day after Thanksgiving'
    for day in range(24, 32):
        result.setdefault(date(year, 12, day), 'Assumed winter closing')
    result[date(year, 1, 2)] = 'Assumed winter closing'
    if year == 2025:
        result[date(2025, 12, 23)] = 'MIT special closing'
    return result


def holiday(day):
    # Include next year's New Year observation when it falls on December 31.
    return {**holiday_dates(day.year), **holiday_dates(day.year + 1)}.get(day, '')


def academic_break(day):
    if (day.month == 12 and day.day >= 20) or (day.month == 1 and day.day <= 4):
        return 'winter'
    thanksgiving = nth_weekday(day.year, 11, 3, 4)
    if thanksgiving <= day <= thanksgiving + timedelta(days=3):
        return 'thanksgiving'
    spring = nth_weekday(day.year, 3, 0, 4)
    if spring <= day <= spring + timedelta(days=6):
        return 'assumed_spring_break'
    if day.month in (6, 7, 8):
        return 'summer'
    if day.month == 1:
        return 'IAP_assumed_lower_demand'
    return ''


def service_window(day, route_id):
    """Apply the 2025–26 schedule to the entire synthetic period as an assumption."""
    if route_id == '71342':
        if holiday(day):
            return None
        if day.weekday() < 5:
            start, end = time(7, 30), time(17, 45)
        elif (day.weekday() == 5 and academic_break(day) not in ('summer', 'winter', 'thanksgiving', 'assumed_spring_break')
              and ((day.month == 9 and day > nth_weekday(day.year, 9, 0, 1))
                   or day.month in (10, 11, 12, 1, 2, 3, 4)
                   or (day.month == 5 and day.day <= 20))):
            start, end = time(9), time(18)
        else:
            return None
    elif route_id == '70113':
        if academic_break(day) in ('summer', 'winter', 'thanksgiving', 'assumed_spring_break'):
            return None
        start, end = time(18), time(1)
    else:
        raise ValueError('Only Boston Daytime and Boston East are supported')
    begin = datetime.combine(day, start, LOCAL).astimezone(timezone.utc)
    finish_day = day + timedelta(days=end <= start)
    finish = datetime.combine(finish_day, end, LOCAL).astimezone(timezone.utc)
    return begin, finish


def day_context(day, cfg):
    rng = rng_for(cfg['seed'], day, 'context')
    season = 'winter' if day.month in (12, 1, 2) else 'summer' if day.month in (6, 7, 8) else 'spring_fall'
    probabilities = cfg['weather_probabilities'][season]
    weather = rng.choices(list(probabilities), list(probabilities.values()))[0]
    sigma = cfg['day_log_sigma']
    return {'date': day.isoformat(), 'weekday': day.weekday(), 'holiday': holiday(day),
            'academic_break': academic_break(day), 'weather_scenario': weather,
            'day_factor': rng.lognormvariate(-sigma * sigma / 2, sigma),
            'weather_is_observed': False}


def traffic_factor(timestamp, context, cfg):
    local = timestamp.astimezone(LOCAL)
    hour = local.hour + local.minute / 60
    factor = 1.0
    if context['holiday']:
        factor *= cfg['holiday_multiplier']
    elif local.weekday() >= 5:
        factor *= cfg['weekend_multiplier']
    else:
        if 7 <= hour < 10:
            factor *= cfg['am_peak_multiplier']
        elif 16 <= hour < 19:
            factor *= cfg['pm_peak_multiplier']
        elif 19 <= hour < 21:
            factor *= cfg['evening_multiplier']
    if context['academic_break']:
        factor *= cfg['break_multiplier']
    return factor * cfg['weather_multipliers'][context['weather_scenario']]


class Trajectory:
    def __init__(self, start, finish, detector, profile, context, cfg, rng):
        self.phases, self.arrivals, self.trips = [], [], []
        self.detector, self.profile = detector, profile
        current = start.timestamp()
        origin = current
        loop = 0
        length = detector.length
        while current < finish.timestamp():
            trip_begin = current
            sigma = cfg['trip_log_sigma']
            trip_factor = rng.lognormvariate(-sigma * sigma / 2, sigma)
            speeds = profile['moving_speeds_mps']
            # A common empirical speed draw preserves correlation across a trip.
            if speeds:
                trip_factor *= max(.7, min(1.6, profile['median_moving_speed_mps'] / rng.choice(speeds)))
            previous = loop * length
            for stop in profile['stops']:
                progress = loop * length + stop['progress_m']
                samples = stop['running_samples_seconds']
                weight = len(samples) / (len(samples) + cfg['edge_shrinkage_samples'])
                # Blend a real adjacent-stop interval with a distance/speed prior.
                base = stop['mean_running_seconds']
                if samples:
                    base = (1 - weight) * base + weight * rng.choice(samples)
                sigma = cfg['segment_log_sigma']
                factor = traffic_factor(datetime.fromtimestamp(current, timezone.utc), context, cfg)
                running = base * context['day_factor'] * trip_factor * factor * rng.lognormvariate(-sigma * sigma / 2, sigma)
                incident = rng.uniform(*cfg['incident_seconds_range']) if rng.random() < cfg['incident_probability_per_segment'] else 0
                # Cap physical speed; unusual delays extend time, not road distance.
                running = max((progress - previous) / 15, running + incident, .1)
                self.phases.append((current, current + running, previous, progress, 'moving', loop))
                current += running
                dw = stop['dwell_samples_seconds']
                dw_weight = len(dw) / (len(dw) + cfg['edge_shrinkage_samples'])
                dwell = (rng.choice(dw) if dw and rng.random() < dw_weight else
                         rng.lognormvariate(math.log(max(1, stop['mean_dwell_seconds'])) - .5 * .5**2, .5))
                demand = .8 if context['academic_break'] else 1.0
                dwell = max(0.0, min(180.0, dwell * demand))
                arrived = current
                self.phases.append((current, current + max(.01, dwell), progress, progress, 'dwell', loop))
                current += max(.01, dwell)
                self.arrivals.append({'loop': loop, 'stop_id': stop['stop_id'], 'position': stop['position'],
                                      'arrival': arrived, 'departure': current, 'incident_seconds': incident})
                previous = progress
            self.trips.append({'loop': loop, 'start_epoch': trip_begin, 'end_epoch': current,
                               'duration_seconds': current - trip_begin, 'trip_factor': trip_factor})
            loop += 1
        self.starts = [p[0] for p in self.phases]
        self.start, self.end = origin, current

    def state(self, timestamp):
        index = max(0, min(len(self.phases) - 1, bisect.bisect_right(self.starts, timestamp) - 1))
        begin, end, a, b, phase, loop = self.phases[index]
        fraction = max(0, min(1, (timestamp - begin) / max(.001, end - begin)))
        return a + (b - a) * fraction, phase, timestamp - begin, loop

    def coordinate(self, progress):
        s = progress % self.detector.length
        cumulative, shape = self.detector.cumulative, self.detector.shape
        index = max(0, min(len(shape) - 2, bisect.bisect_right(cumulative, s) - 1))
        fraction = (s - cumulative[index]) / max(1e-9, cumulative[index + 1] - cumulative[index])
        a, b = shape[index], shape[index + 1]
        return a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction


def expected_seconds(progress, phase, elapsed_dwell, target, profile):
    """Integrate calibrated means from CURRENT position; never read future phases."""
    length = profile['route_length_m']
    current = progress % length
    destination = target['progress_m'] % length
    distance = (destination - current) % length
    if distance < 1e-6:
        return 0.0
    end = current + distance
    running = dwell = 0.0
    if phase == 'dwell':
        for stop in profile['stops']:
            if abs(stop['progress_m'] % length - current) <= 1e-6:
                dwell += max(0.0, stop['mean_dwell_seconds'] - elapsed_dwell)
                break
    for loop in (0, 1):
        previous = loop * length
        for stop in profile['stops']:
            s = loop * length + stop['progress_m']
            overlap = max(0.0, min(end, s) - max(current, previous))
            running += overlap / max(1e-9, s - previous) * stop['mean_running_seconds']
            if current + 1e-6 < s < end - 1e-6:
                dwell += stop['mean_dwell_seconds']
            previous = s
    return running + dwell


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='milliseconds')


def write_day(folder, service_day, rid, raw_metadata, profile, context, cfg):
    """Each folder is a stand-alone CSVStorage data directory, with gzip CSVs."""
    window = service_window(service_day, rid)
    if window is None:
        return None
    start, finish = window
    sid = f"sim-v1-{rid}-{service_day.isoformat()}-s{cfg['seed']}"
    bus_id = f'sim-bus-{rid}'
    rng = rng_for(cfg['seed'], service_day, rid, 'movement')
    observation_rng = rng_for(cfg['seed'], service_day, rid, 'observations')
    forecast_rng = rng_for(cfg['seed'], service_day, rid, 'forecasts')
    snapshot = {'session_id': sid, 'metadata': {'route_id': rid, 'stop_metadata': raw_metadata}}
    detector = ArrivalDetector(snapshot)
    trajectory = Trajectory(start, finish, detector, profile, context, cfg, rng)
    folder = Path(folder)
    level = cfg['gzip_compresslevel']
    # Preserve the precise API geometry/order used by the route detector.
    used_stop_ids = {str(sid) for _, sid, _ in raw_metadata['routes'][rid][2:]}
    route_raw = {'routes': {rid: raw_metadata['routes'][rid]},
                 'routePoints': {rid: raw_metadata['routePoints'][rid]},
                 'stops': {k: v for k, v in raw_metadata['stops'].items() if str(v['id']) in used_stop_ids}}
    metadata = {'session_id': sid, 'metadata': {
        'route_id': rid, 'system_id': 94, 'interval_seconds': cfg['poll_seconds'],
        'stop_ids': [s['stop_id'] for s in profile['stops']], 'stop_metadata': route_raw,
        'synthetic': True, 'simulation_version': cfg['version'], 'seed': cfg['seed'],
        'service_date': service_day.isoformat(), 'context': context,
        'scheduled_start_at': start.isoformat(), 'scheduled_end_at': finish.isoformat(),
        'actual_simulated_end_at': iso(trajectory.end),
        'forecast_kind': 'assumed_baseline_not_actual_Passio',
        'calibration_reference': '../../../../calibration/calibration.json'}}
    with compressed_text(folder / 'sessions' / f'{sid}.json.gz', level) as file:
        json.dump(metadata, file, separators=(',', ':'), allow_nan=False)
    gps_count = eta_count = gps_failures = eta_failures = stale_count = missing_count = 0
    outage_until = 0.0
    forecast_trip_factors = {}
    with compressed_text(folder / 'bus_positions.csv.gz', level) as gps_file, \
         compressed_text(folder / 'eta_predictions_by_route.csv.gz', level) as eta_file:
        gps = csv.DictWriter(gps_file, fieldnames=CSV_FIELDS)
        eta = csv.DictWriter(eta_file, fieldnames=ROUTE_CSV_FIELDS)
        gps.writeheader()
        eta.writeheader()
        tick = trajectory.start
        while tick <= trajectory.end:
            if observation_rng.random() < cfg['outage_start_probability']:
                outage_until = tick + observation_rng.uniform(*cfg['outage_seconds_range'])
            outage = tick < outage_until
            progress, phase, elapsed, loop = trajectory.state(tick + .1)
            lat, lon = trajectory.coordinate(progress)
            noise = cfg['gps_noise_meters']
            if observation_rng.random() < cfg['gps_outlier_probability']:
                noise = 65.0
            lat += observation_rng.gauss(0, noise) / 111195
            lon += observation_rng.gauss(0, noise) / (111195 * math.cos(math.radians(lat)))
            stale = observation_rng.random() < cfg['stale_probability']
            missing = observation_rng.random() < cfg['missing_bus_probability']
            gps_failure = outage or observation_rng.random() < profile['gps_failure_probability']
            bus = {'busId': bus_id, 'routeId': rid, 'route': profile['name'],
                   'latitude': round(lat, 8), 'longitude': round(lon, 8),
                   'outdated': int(stale), 'outOfService': 0}
            gps_payload = {'buses': {} if missing else {bus_id: [bus]}, 'synthetic': True}
            gps.writerow({'session_id': sid, 'request_started_at': iso(tick),
                          'request_finished_at': iso(tick + .1),
                          'response_received_at': '' if gps_failure else iso(tick + .1),
                          'stop_id': '', 'data': 'null' if gps_failure else json.dumps(gps_payload, separators=(',', ':')),
                          'error': 'Timeout: synthetic outage' if gps_failure else ''})
            gps_count += 1
            gps_failures += gps_failure
            stale_count += stale
            missing_count += missing
            if loop not in forecast_trip_factors:
                sigma = cfg['forecast_trip_log_sigma']
                forecast_trip_factors[loop] = forecast_rng.lognormvariate(-sigma * sigma / 2, sigma)
            for index, stop in enumerate(profile['stops']):
                requested = tick + .2 + .04 * index
                received = requested + .02
                failed = outage or observation_rng.random() < profile['eta_failure_probability']
                # Forecasts use only the latest available GPS state and calibrated means.
                baseline = expected_seconds(progress, phase, elapsed, stop, profile)
                visible_context = traffic_factor(datetime.fromtimestamp(requested, timezone.utc), context, cfg)
                baseline *= 1 + cfg['forecast_context_response'] * (visible_context - 1)
                baseline *= (1 + cfg['forecast_fractional_bias']) * forecast_trip_factors[loop]
                sigma = cfg['forecast_noise_base_seconds'] + cfg['forecast_noise_fraction'] * baseline
                predicted = max(0, baseline + forecast_rng.gauss(0, sigma))
                position = int(stop['position'])
                entry = {'busId': bus_id, 'routeId': rid, 'stopId': stop['stop_id'],
                         'arrivalTimestamp': round(received + predicted, 3),
                         'secondsSpent': round(predicted), 'eta': f'{max(0, round(predicted / 60))} min',
                         'tripId': f"{sid}-loop-{loop + int(loop * detector.length + stop['progress_m'] < progress - 1e-6)}",
                         'routeStopPosition': position,
                         'theStop': {'position': position}, 'outdated': int(stale), 'OOS': 0,
                         'busLatLng': [bus['latitude'], bus['longitude']]}
                payload = {'ETAs': {stop['stop_id']: [] if missing else [entry]}, 'synthetic': True}
                eta.writerow({'session_id': sid, 'route_id': rid, 'stop_id': stop['stop_id'],
                              'request_started_at': iso(requested), 'request_finished_at': iso(received),
                              'response_received_at': '' if failed else iso(received),
                              'data': 'null' if failed else json.dumps(payload, separators=(',', ':')),
                              'error': 'Timeout: synthetic request failure' if failed else ''})
                eta_count += 1
                eta_failures += failed
            tick += cfg['poll_seconds']
    # Truth is isolated from observations and from the forecast generator.
    with compressed_text(folder / 'ground_truth' / 'actual_arrivals.csv.gz', level) as file:
        writer = csv.DictWriter(file, fieldnames=ARRIVAL_FIELDS)
        writer.writeheader()
        for row in trajectory.arrivals:
            writer.writerow({'session_id': sid, 'bus_id': bus_id, 'route_id': rid,
                             'stop_id': row['stop_id'], 'route_stop_position': row['position'],
                             'estimated_arrival_at': iso(row['arrival']), 'previous_observed_at': '',
                             'arrival_method': 'simulation_truth'})
    with compressed_text(folder / 'ground_truth' / 'trips.csv.gz', level) as file:
        writer = csv.DictWriter(file, fieldnames=['session_id', 'bus_id', 'route_id', 'trip_id',
                                                 'started_at', 'finished_at', 'duration_seconds', 'synthetic'])
        writer.writeheader()
        for trip in trajectory.trips:
            writer.writerow({'session_id': sid, 'bus_id': bus_id, 'route_id': rid,
                             'trip_id': f"{sid}-loop-{trip['loop']}", 'started_at': iso(trip['start_epoch']),
                             'finished_at': iso(trip['end_epoch']), 'duration_seconds': round(trip['duration_seconds'], 3),
                             'synthetic': True})
    return {'service_date': str(service_day), 'route_id': rid, 'session_id': sid,
            'gps_requests': gps_count, 'eta_requests': eta_count, 'gps_failures': gps_failures,
            'eta_failures': eta_failures, 'stale_fixes': stale_count, 'missing_bus_fixes': missing_count,
            'trips': len(trajectory.trips), 'truth_arrivals': len(trajectory.arrivals),
            'first_observed_at': iso(trajectory.start), 'last_observed_at': iso(trajectory.end),
            'synthetic': True}
