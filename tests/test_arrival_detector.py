"""Behavioral checks for the basic route-segment arrival detector."""

import csv
import json
import math
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from shuttle_analysis.processing.shared.route_geometry import distance, project
from shuttle_analysis.processing.arrivals.review_arrivals import detect_session, save_arrivals
from shuttle_analysis.storage import CSVStorage


def coord(x, y=0):
    return math.degrees(y / 6_371_000), math.degrees(x / 6_371_000)


def snapshot():
    shape = [coord(0), coord(200), coord(200, 200), coord(0, 200), coord(0)]
    locations = [coord(0), coord(100), coord(200, 100), coord(100, 200), coord(0, 100)]
    stops = {str(i): {'id': str(i), 'latitude': p[0], 'longitude': p[1]}
             for i, p in enumerate(locations)}
    return {'session_id': 'test', 'metadata': {
        'route_id': 'r', 'stop_segments': {'1': 0, '2': 0, '3': 1, '4': 2, '5': 3, '6': 3},
        'stop_metadata': {
            'routePoints': {'r': [[{'lat': p[0], 'lng': p[1]} for p in shape]]},
            'routes': {'r': ['Route', 'blue', *[[str(i+1), str(i), 0] for i in range(5)], ['6', '0', 1]]},
            'stops': stops,
        },
    }}


def observation(x, seconds, y=0, route='r', error=None):
    timestamp = (datetime(2026, 11, 5, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()
    point = coord(x, y)
    return {'request_type': 'vehicles', 'request_started_at': timestamp,
            'request_finished_at': timestamp, 'response_received_at': timestamp if not error else None,
            'stop_id': None, 'error': error,
            'data': None if error else {'buses': {'device': [{'busId': 'bus', 'routeId': route,
                    'latitude': point[0], 'longitude': point[1], 'outdated': 0, 'outOfService': 0}]}}}


class ArrivalTests(unittest.TestCase):
    def arrivals(self, observations):
        return ArrivalDetector(snapshot()).detect(observations)

    def test_projection_and_distance(self):
        lateral, fraction = project(coord(100, 20), coord(0), coord(200))
        self.assertAlmostEqual(lateral, 20, places=4)
        self.assertAlmostEqual(fraction, .5, places=4)
        self.assertEqual(project(coord(0), coord(0), coord(0)), (0, 0))
        self.assertAlmostEqual(distance(coord(0), coord(200)), 200, places=4)

    def test_one_sample_pass_counts_without_dwell(self):
        arrivals = self.arrivals([observation(40, 0), observation(100, 30), observation(160, 60)])
        arrival, = [a for a in arrivals if a['stop_id'] == '1']
        self.assertEqual(arrival['estimated_arrival_at'], observation(100, 30)['response_received_at'])
        self.assertEqual(arrival['previous_observed_at'], observation(40, 0)['response_received_at'])
        self.assertEqual(arrival['arrival_method'], 'near_stop')

    def test_dwell_and_reentry_do_not_duplicate_a_visit(self):
        points = [40, 80, 100, 99, 101, 160, 140, 120, 100, 160]
        arrivals = self.arrivals([observation(x, i*30) for i, x in enumerate(points)])
        arrival, = [a for a in arrivals if a['stop_id'] == '1']
        self.assertEqual(arrival['estimated_arrival_at'], observation(80, 30)['response_received_at'])

    def test_pass_between_samples_is_identified(self):
        arrivals = self.arrivals([observation(40, 0), observation(160, 30)])
        arrival, = [a for a in arrivals if a['stop_id'] == '1']
        self.assertEqual(arrival['arrival_method'], 'between_samples')
        self.assertEqual(arrival['previous_observed_at'], observation(40, 0)['response_received_at'])

    def test_starting_inside_does_not_invent_an_arrival(self):
        arrivals = self.arrivals([observation(100, 0), observation(110, 30), observation(160, 60)])
        self.assertFalse(any(a['stop_id'] == '1' for a in arrivals))

    def test_gaps_failures_missing_buses_and_route_changes_reset_history(self):
        missing = observation(0, 15)
        missing['data'] = {'buses': {}}
        for middle in [observation(0, 15, error='Timeout'), observation(0, 15, route='other'), missing]:
            arrivals = self.arrivals([observation(40, 0), middle, observation(100, 30)])
            self.assertFalse(any(a['stop_id'] == '1' for a in arrivals))
        self.assertEqual(self.arrivals([observation(40, 0), observation(100, 120)]), [])

    def test_bad_vehicle_records_are_skipped(self):
        for field, value in [('latitude', 'nan'), ('busId', None), ('outdated', 1)]:
            sample = observation(100, 0)
            sample['data']['buses']['device'][0][field] = value
            self.assertEqual(self.arrivals([sample]), [])

    def test_context_resolves_ties_but_startup_ambiguity_is_skipped(self):
        snap = snapshot()
        raw = snap['metadata']['stop_metadata']
        for point in raw['routePoints']['r'][0]:
            point['lat'] *= 2
            point['lng'] *= .1
        for stop in raw['stops'].values():
            stop['latitude'] *= 2
            stop['longitude'] *= .1
        detector = ArrivalDetector(snap)
        self.assertIsNone(detector._route_position(coord(10, 200), None))
        progress = detector._route_position(coord(10, 150), {'progress': 120})
        self.assertAlmostEqual(progress, 170, places=3)

    def test_large_jumps_are_not_matched(self):
        detector = ArrivalDetector(snapshot())
        self.assertIsNone(detector._route_position(coord(200, 100), {'progress': 400}))
        self.assertIsNone(detector._route_position(coord(1000, 1000), None))

    def test_repeated_loops_produce_separate_arrivals(self):
        locations = [(40, 0), (100, 0), (180, 0), (200, 100), (200, 180),
                     (100, 200), (0, 180), (0, 100), (0, 20), (40, 0), (100, 0), (180, 0)]
        arrivals = self.arrivals([observation(x, i*30, y=y) for i, (x, y) in enumerate(locations)])
        self.assertEqual(len([a for a in arrivals if a['stop_id'] == '1']), 2)

    def test_loop_boundary_is_one_physical_arrival(self):
        arrivals = self.arrivals([observation(0, 0, y=60), observation(0, 30, y=10),
                                  observation(10, 60), observation(60, 90)])
        arrival, = [a for a in arrivals if a['stop_id'] == '0']
        self.assertEqual(arrival['route_stop_position'], '6')

    def test_bad_stop_configuration_and_wrong_session_raise(self):
        snap = snapshot()
        snap['metadata']['stop_segments']['2'] = 999
        with self.assertRaises(ValueError):
            ArrivalDetector(snap)
        sample = observation(100, 0)
        sample['session_id'] = 'other'
        with self.assertRaises(ValueError):
            self.arrivals([sample])

    def test_csv_runner_preserves_collected_inputs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            storage = CSVStorage('test', root / 'data')
            storage.save_session_metadata(snapshot()['metadata'])
            for index, position in enumerate([40, 100, 160]):
                storage.save_observation(observation(position, index * 30))
            originals = {path: path.read_bytes() for path in (root / 'data').rglob('*') if path.is_file()}
            arrivals = detect_session('test', root / 'data')
            output = root / 'results/arrivals/arrivals_test.csv'
            save_arrivals(arrivals, output)
            save_arrivals(arrivals, output)
            with output.open(newline='') as file:
                self.assertEqual(len(list(csv.DictReader(file))), 1)
            self.assertTrue(all(path.read_bytes() == contents for path, contents in originals.items()))

    def test_saved_wrong_section_example(self):
        root = Path(__file__).resolve().parents[1]
        session_id = 'ab79b498-0da0-445a-ab7a-b51333629e8e'
        if not (root / 'data/sessions' / f'{session_id}.json').exists():
            self.skipTest('Local research session not present')
        arrivals = detect_session(session_id, root / 'data')
        visits = [a for a in arrivals if a['bus_id'] == '3009'
                  and '2026-11-05T22:11' <= a['estimated_arrival_at'] <= '2026-11-05T22:14:30']
        self.assertEqual([a['stop_id'] for a in visits], ['979'])
        self.assertFalse(any(a['stop_id'] == '3042' for a in arrivals))


if __name__ == '__main__':
    unittest.main()
