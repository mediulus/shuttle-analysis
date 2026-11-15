"""Historical model: weather columns, features, labels, ETA assembly and training.

Route (800 m loop): stop IDs 1..4, 0 at route positions 2..6, at 100, 300,
500, 700 and 800 m along the loop.
"""

import csv
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from historical_prediction_model import model
from historical_prediction_model.community import AcademicCalendar, Classes, Games, Practice, SimCalendar
from historical_prediction_model.features import FeatureBuilder
from historical_prediction_model.labels import route_labels
from historical_prediction_model.predictor import HistoricalPredictor
from historical_prediction_model.weather import Weather, decode, simulated
from tests.test_arrival_detector import observation, snapshot


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def write(path, fields, rows):
    with path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(fields)
        writer.writerows(rows)
    return path


def weather_file(folder, reports):
    rows = [['2026-11-12T20:10:33+00:00', f'{time}+00:00', temp, 90, wind, 101000, text]
            for time, temp, wind, text in reports]
    return write(folder / 'weather.csv', ['collected_at_utc', 'observed_at', 'temperature_c', 'humidity_pct',
                                         'wind_speed_kmh', 'pressure_pa', 'description'], rows)


def builder(folder, reports=()):
    """A FeatureBuilder reading small fixture files instead of the real data."""
    calendar = write(folder / 'calendar.csv', ['start_date', 'end_date', 'term', 'category'], [
        ['2026-09-09', '2026-09-09', 'Fall 2026', 'term_start'],
        ['2026-11-11', '2026-11-11', 'Fall 2026', 'holiday'],
        ['2026-12-10', '2026-12-10', 'Fall 2026', 'term_end'],
        ['2026-12-14', '2026-12-18', 'Fall 2026', 'exams'],
        ['2027-01-04', '2027-01-04', 'IAP 2027', 'term_start'],
        ['2027-01-29', '2027-01-29', 'IAP 2027', 'term_end'],
        ['2027-02-01', '2027-02-01', 'Spring 2027', 'term_start'],
        ['2027-05-11', '2027-05-11', 'Spring 2027', 'term_end'],
    ])
    sim = write(folder / 'sim.csv', ['date', 'holiday', 'academic_break', 'weather_scenario'], [
        ['2026-11-06', '', '', 'heavy_rain'],
        ['2026-07-04', 'Independence Day', 'summer', 'clear'],
        ['2026-12-28', '', 'winter', 'snow'],
    ])
    games = write(folder / 'games.csv', ['date', 'start_time', 'home_away'], [
        ['2026-11-06', '18:30', 'home'], ['2026-11-06', '18:30', 'home'],
        ['2026-11-06', '12:30', 'away'], ['2026-11-06', '', 'home'],
    ])
    classes = write(folder / 'classes.csv', ['weekday', 'end'], [
        ['Fri', '17:00'], ['Fri', '17:00'], ['Fri', '12:00'], ['Wed', '10:00'],
    ])
    practice = write(folder / 'practice.csv', ['date', 'start_time', 'end_time'], [['2026-11-06', '17:00', '19:00']])
    return FeatureBuilder(Weather(weather_file(folder, reports)), AcademicCalendar(calendar), SimCalendar(sim),
                          Games(games), Classes(classes), Practice(practice))


class WeatherTests(unittest.TestCase):
    def test_station_shorthand_maps_to_type_intensity_and_visibility(self):
        cases = {
            'Mostly Clear': ('none', 0, 0), 'Overcast': ('none', 0, 0), 'HZ': ('none', 0, 0),
            'BR': ('none', 0, 1), 'FG': ('none', 0, 1),
            '-RA': ('rain', 1, 0), 'RA': ('rain', 2, 0), '+RA BR': ('rain', 3, 1), '-TSRA': ('rain', 1, 0),
            '-DZ': ('drizzle', 1, 0), '-SN': ('snow', 1, 0), 'SN FZFG': ('snow', 2, 1),
            '-RASN': ('snow', 1, 0), '-FZRA': ('ice', 1, 0), 'PL': ('ice', 2, 0), '-RAPL BR': ('ice', 1, 1),
            '': (None, None, None),
        }
        for description, expected in cases.items():
            self.assertEqual(decode(description), expected, description)

    def test_latest_report_at_or_before_the_time_is_used(self):
        with TemporaryDirectory() as folder:
            weather = Weather(weather_file(Path(folder), [
                ('2026-11-06T21:54:00', 17.22, 9.26, '-RA'),
                ('2026-11-06T22:54:00', 18.33, 11.11, '+RA BR'),
                ('2026-11-06T23:11:00', 18.33, 11.11, 'RA BR'),
            ]))
        self.assertEqual(weather.at(utc('2026-11-06T22:58:00')), {
            'precip_type': 'rain', 'precip_intensity': 3, 'low_visibility': 1, 'wet_last_3h': 1,
            'temperature_c': 18.33, 'wind_speed_kmh': 11.11})
        # Before the first report, and more than two hours after the last one.
        for when in ('2026-11-06T21:00:00', '2026-11-07T01:12:00'):
            self.assertEqual(set(weather.at(utc(when)).values()), {None})

    def test_wet_last_3h_remembers_rain_that_has_stopped(self):
        with TemporaryDirectory() as folder:
            weather = Weather(weather_file(Path(folder), [
                ('2026-11-06T10:00:00', 10, 5, '-RA'), ('2026-11-06T11:00:00', 10, 5, 'Overcast'),
                ('2026-11-06T12:00:00', 10, 5, 'Clear'), ('2026-11-06T14:00:00', 10, 5, 'Clear'),
            ]))
        soon = weather.at(utc('2026-11-06T12:30:00'))
        self.assertEqual((soon['precip_type'], soon['wet_last_3h']), ('none', 1))
        self.assertEqual(weather.at(utc('2026-11-06T14:30:00'))['wet_last_3h'], 0)

    def test_simulated_scenario_leaves_unmodelled_columns_missing(self):
        self.assertEqual(simulated('heavy_rain'), {
            'precip_type': 'rain', 'precip_intensity': 3, 'low_visibility': None, 'wet_last_3h': 1,
            'temperature_c': None, 'wind_speed_kmh': None})
        self.assertEqual(simulated('clear')['wet_last_3h'], 0)
        self.assertEqual(set(simulated(None).values()), {None})


class FeatureTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.features = builder(Path(folder.name), [('2026-11-06T22:54:00', 18.33, 11.11, '+RA BR')])

    def test_real_row_for_a_friday_evening(self):
        row = self.features.conditions(utc('2026-11-06T22:58:00'))  # 5:58 PM in Boston
        expected = {'minutes_since_midnight': 1078, 'weekday': 4, 'is_holiday': 0, 'term_period': 'term',
                    'precip_type': 'rain', 'precip_intensity': 3, 'home_game_starting_60min': 2,
                    'home_game_ended_60min': 0, 'classes_ending_15min': 0, 'practice_block': 1, 'is_synthetic': 0}
        self.assertEqual({name: row[name] for name in expected}, expected)
        self.assertEqual(self.features.conditions(utc('2026-11-06T21:50:00'))['classes_ending_15min'], 2)
        self.assertEqual(self.features.conditions(utc('2026-11-07T02:00:00'))['home_game_ended_60min'], 2)

    def test_after_midnight_belongs_to_the_evening_before(self):
        row = self.features.conditions(utc('2026-11-07T06:00:00'))  # 1 AM Saturday in Boston
        self.assertEqual((row['weekday'], row['minutes_since_midnight']), (4, 60))

    def test_term_periods_and_holidays(self):
        periods = {'2026-11-06': 'term', '2026-12-15': 'exams', '2026-12-22': 'break', '2027-01-10': 'IAP',
                   '2027-06-15': 'summer', '2026-09-01': None}
        for day, expected in periods.items():
            self.assertEqual(self.features.conditions(utc(f'{day}T17:00:00'))['term_period'], expected, day)
        holiday = self.features.conditions(utc('2026-11-11T15:00:00'))  # Wednesday 10 AM, Veterans Day
        self.assertEqual((holiday['is_holiday'], holiday['classes_ending_15min']), (1, 0))
        self.assertEqual(self.features.conditions(utc('2026-11-04T15:00:00'))['classes_ending_15min'], 1)

    def test_simulated_row_uses_the_simulator_calendar_and_nothing_it_did_not_model(self):
        row = self.features.conditions(utc('2026-11-06T22:58:00'), synthetic=True)
        self.assertEqual((row['is_holiday'], row['term_period'], row['precip_type'], row['precip_intensity'],
                          row['is_synthetic']), (0, 'term', 'rain', 3, 1))
        for name in ('temperature_c', 'low_visibility', 'home_game_starting_60min', 'classes_ending_15min',
                     'practice_block'):
            self.assertIsNone(row[name], name)
        summer = self.features.conditions(utc('2026-07-04T16:00:00'), synthetic=True)
        self.assertEqual((summer['is_holiday'], summer['term_period']), (1, 'summer'))
        self.assertEqual(self.features.conditions(utc('2026-12-28T16:00:00'), synthetic=True)['term_period'], 'break')

    def test_leg_and_dwell_rows_name_what_they_describe(self):
        when = utc('2026-11-06T22:58:00')
        leg = self.features.leg('71342', ('2', '3'), 426.3, when)
        self.assertEqual((leg['route_id'], leg['leg_id'], leg['leg_length_m']), ('71342', '71342:2>3', 426.3))
        self.assertEqual(self.features.dwell('71342', '3', when)['stop_position'], '71342:3')


class LabelTests(unittest.TestCase):
    # Dwells at stop 1 for one extra sample, stops at 2, crosses 3 between samples, stops at 4.
    POINTS = [(40, 0), (100, 0), (105, 0), (160, 0), (200, 40), (200, 100), (200, 160),
              (140, 200), (60, 200), (0, 180), (0, 100), (0, 40)]

    def labels(self, samples):
        labels = route_labels(snapshot(), samples)
        legs = {(row['from_position'], row['to_position']): row['seconds'] for row in labels['leg']}
        dwells = {row['stop_position']: row['seconds'] for row in labels['dwell']}
        return legs, dwells

    def test_dwell_plus_next_leg_is_the_arrival_to_arrival_time(self):
        legs, dwells = self.labels([observation(x, i * 30, y=y) for i, (x, y) in enumerate(self.POINTS)])
        # Arrivals at 30 s, 150 s, 240 s (crossed) and 300 s.
        self.assertEqual(dwells, {'2': 30.0, '3': 0.0, '4': 0.0, '5': 0.0})
        self.assertEqual(legs, {('2', '3'): 90.0, ('3', '4'): 90.0, ('4', '5'): 60.0})
        self.assertEqual(dwells['2'] + legs[('2', '3')], 150 - 30)

    def test_a_gap_breaks_the_chain_of_legs(self):
        samples = [observation(x, i * 30, y=y) for i, (x, y) in enumerate(self.POINTS)]
        samples[4] = observation(0, 120, error='timeout')
        legs, _ = self.labels(samples)
        self.assertNotIn(('2', '3'), legs)
        self.assertIn(('4', '5'), legs)


class Stub:
    """Leg time is length / 5 m/s and every dwell is 10 s; rows only record what was asked."""

    name = 'stub'
    inside_share = {'r:2': 0.5}

    def predict(self, target, rows):
        return [rows[0]['leg_length_m'] / 5 if target == 'leg' else 10.0]

    def leg(self, route_id, leg, length_m, when, synthetic=False):
        self.asked.append(('leg', leg, when))
        return {'leg_length_m': length_m}

    def dwell(self, route_id, position, when, synthetic=False):
        self.asked.append(('dwell', position, when))
        return {'stop_position': f'{route_id}:{position}'}


class PredictorTests(unittest.TestCase):
    def setUp(self):
        self.stub = Stub()
        self.stub.asked = []
        self.predictor = HistoricalPredictor(snapshot(), self.stub, self.stub)
        self.start = datetime(2026, 11, 5, tzinfo=timezone.utc)

    def test_etas_add_the_partial_leg_then_dwell_and_leg_for_each_stop(self):
        rows = self.predictor.predict([observation(40, 0)])
        # 60 m left of a 100 m leg at 5 m/s: 12 s. Then 10 s dwell + 200 m / 5 m/s for each stop.
        self.assertEqual([row['predicted_seconds'] for row in rows], [12.0, 62.0, 112.0, 162.0])
        self.assertEqual([row['stop_id'] for row in rows], ['1', '2', '3', '4'])
        self.assertEqual({row['leg_sources'] for row in rows}, {'stub', 'stub;stub', 'stub;stub;stub', 'stub;stub;stub;stub'})

    def test_each_row_is_asked_for_the_time_the_bus_gets_there(self):
        self.predictor.predict([observation(40, 0)])
        after = lambda seconds: self.start + timedelta(seconds=seconds)
        self.assertEqual(self.stub.asked[:5], [
            ('leg', ('6', '2'), after(0)),      # on this leg now
            ('dwell', '2', after(12)),          # reaches stop 1 after 12 s
            ('leg', ('2', '3'), after(22)),     # leaves after a 10 s dwell
            ('dwell', '3', after(62)),
            ('leg', ('3', '4'), after(72)),
        ])

    def test_time_and_place_matches_the_replay_and_handles_a_bus_at_a_stop(self):
        replay = self.predictor.predict([observation(40, 0)])
        direct = self.predictor.predict_at(40, self.start)
        self.assertEqual([row['predicted_seconds'] for row in direct], [row['predicted_seconds'] for row in replay])
        # At stop 1 (100 m), where only half of all visits are seen inside the stop area:
        # the 10 s average dwell means 20 s for a bus that is inside, then the whole 200 m leg.
        self.assertEqual(self.predictor.predict_at(100, self.start)[0]['predicted_seconds'], 60.0)

    def test_a_bus_first_seen_past_a_stop_is_at_the_start_of_its_leg(self):
        # Stop 1 (100 m) is crossed between samples; the bus is first seen at 160 m.
        # Leg labels are timed from that point, so the whole 40 s leg time is still ahead,
        # not 140 m / 200 m of it.
        rows = self.predictor.predict([observation(40, 0), observation(160, 30), observation(200, 60, y=30)])
        first = lambda seconds: next(row for row in rows
                                     if row['prediction_observed_at'] == observation(0, seconds)['response_received_at'])
        self.assertEqual((first(30)['stop_id'], first(30)['predicted_seconds']), ('2', 40.0))
        # Halfway from there to the stop (70 m of 140 m left), half the leg time is left.
        self.assertEqual(first(60)['predicted_seconds'], 20.0)


class ModelTests(unittest.TestCase):
    @staticmethod
    def labels():
        """Leg 2>3 takes 60 s and leg 3>4 takes 120 s, plus 40 s in the afternoon; dwell is always 20 s."""
        rows = {'leg': [], 'dwell': []}
        for i in range(1200):
            synthetic = int(i % 6 != 0)
            session = f'sim-{i % 3}' if synthetic else f'real-{i % 2}'
            afternoon = i % 2
            at = (datetime(2026, 11, 2 + i % 5, 22 if afternoon else 15, tzinfo=timezone.utc)
                  + timedelta(minutes=i % 50)).isoformat()
            leg = ('2', '3') if i % 4 < 2 else ('3', '4')
            base = {'session_id': session, 'route_id': 'r', 'at': at, 'synthetic': synthetic}
            rows['leg'].append({**base, 'from_position': leg[0], 'to_position': leg[1], 'length_m': 200.0,
                                'seconds': (60 if leg == ('2', '3') else 120) + 40 * afternoon + i % 3})
            rows['dwell'].append({**base, 'stop_position': leg[0], 'seconds': 20.0, 'seen_inside': i % 4 != 3})
        rows['leg'][1]['seconds'] = 5000.0  # One extreme value, clipped in training.
        return rows

    def test_training_learns_leg_and_time_of_day_and_survives_saving(self):
        with TemporaryDirectory() as folder, mock.patch.object(model, 'REAL_ROW_WEIGHTS', (1, 5)), \
                mock.patch.object(model, 'TREE_COUNTS', (20, 100)):
            features = builder(Path(folder))
            boosted, baseline, report = model.train(self.labels(), features, log=lambda message: None)
            model.save(boosted, baseline, {'training_sessions': ['real-0', 'real-1'], **report}, Path(folder))
            boosted, baseline, details = model.load(Path(folder))
        morning, afternoon = utc('2026-11-04T15:10:00'), utc('2026-11-04T22:10:00')
        ask = lambda estimator, leg, when: estimator.predict('leg', [features.leg('r', leg, 200.0, when)])[0]
        for estimator in (boosted, baseline):
            self.assertAlmostEqual(ask(estimator, ('2', '3'), morning), 61, delta=8)
            self.assertAlmostEqual(ask(estimator, ('2', '3'), afternoon), 101, delta=8)
            self.assertAlmostEqual(ask(estimator, ('3', '4'), afternoon), 161, delta=8)
            self.assertAlmostEqual(estimator.predict('dwell', [features.dwell('r', '2', morning)])[0], 20, delta=1)
        self.assertEqual(details['leg']['rows_clipped_at_cap'], 1)
        self.assertEqual((details['leg']['real_rows'], details['leg']['simulated_rows']), (200, 1000))
        self.assertIn(details['leg']['real_row_weight'], (1, 5))
        self.assertIn(details['leg']['trees'], (20, 100))
        # A leg the model has never seen still gets a finite, non-negative answer.
        self.assertGreaterEqual(ask(boosted, ('9', '9'), morning), 0)


if __name__ == '__main__':
    unittest.main()
