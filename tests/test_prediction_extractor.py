"""Check extraction, UTC times, repeated predictions, and saved CSV inputs."""

import copy
import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shuttle_analysis.processing.predictions.prediction_extractor import PredictionExtractor
from shuttle_analysis.processing.predictions.review_predictions import extract_session, save_predictions, ROOT
from shuttle_analysis.storage import CSVStorage


def observation():
    return {
        'session_id': 'test', 'request_type': 'eta', 'stop_id': '979',
        'request_started_at': '2026-11-08T10:00:00+00:00',
        'request_finished_at': '2026-11-08T10:00:01+00:00',
        'response_received_at': '2026-11-08T10:00:01+00:00', 'error': None,
        'data': {'ETAs': {'979': [{
            'busId': 3009, 'routeId': '71342', 'stopId': '979',
            'arrivalTimestamp': 1794132180, 'eta': '3 min', 'etaUtc': 1,
            'tripId': 'trip', 'theStop': {'position': 1}, 'outdated': 0, 'OOS': 0,
        }]}},
    }


class PredictionTests(unittest.TestCase):
    def extract(self, observations):
        return PredictionExtractor({'session_id': 'test'}).extract(observations)

    def test_one_record_per_bus_and_repeated_poll_without_mutating_input(self):
        first = observation()
        other = copy.deepcopy(first['data']['ETAs']['979'][0])
        other.update(busId=17693, routeId='70113')
        first['data']['ETAs']['979'].append(other)
        second = observation()
        second['request_started_at'] = '2026-11-08T10:00:30+00:00'
        second['response_received_at'] = '2026-11-08T10:00:31+00:00'
        original = copy.deepcopy([second, first])
        records = self.extract([second, first])
        self.assertEqual([r['bus_id'] for r in records], ['3009', '17693', '3009'])
        self.assertEqual(records[1]['route_id'], '70113')
        self.assertEqual(records[0]['predicted_arrival_at'], '2026-11-08T10:03:00+00:00')
        self.assertEqual(records[0]['prediction_observed_at'], first['response_received_at'])
        self.assertEqual(records[0]['passio_stop_position'], '1')
        self.assertNotIn('route_stop_position', records[0])
        self.assertEqual([second, first], original)

    def test_flags_are_preserved_and_optional_fields_can_be_missing(self):
        obs = observation()
        entry = obs['data']['ETAs']['979'][0]
        entry.update(outdated=1, OOS='1')
        del entry['tripId'], entry['theStop']
        record, = self.extract([obs])
        self.assertEqual((record['outdated'], record['out_of_service']), (1, '1'))
        self.assertIsNone(record['trip_id'])
        self.assertIsNone(record['passio_stop_position'])

    def test_failed_empty_and_malformed_entries_are_skipped(self):
        for change in [None, {}, {'ETAs': {}}, {'ETAs': []}, {'ETAs': {'979': None}}]:
            obs = observation()
            obs['data'] = change
            self.assertEqual(self.extract([obs]), [])
        for field, value in [('busId', None), ('routeId', None), ('stopId', 'other'),
                             ('arrivalTimestamp', None), ('arrivalTimestamp', 'bad'),
                             ('arrivalTimestamp', float('nan')), ('arrivalTimestamp', True),
                             ('arrivalTimestamp', 1e100)]:
            obs = observation()
            obs['data']['ETAs']['979'][0][field] = value
            self.assertEqual(self.extract([obs]), [])
        obs = observation()
        obs['error'] = 'Timeout'
        self.assertEqual(self.extract([obs]), [])

    def test_wrong_session_raises_and_vehicle_observations_are_ignored(self):
        obs = observation()
        obs['session_id'] = 'other'
        with self.assertRaises(ValueError):
            self.extract([obs])
        obs['request_type'] = 'vehicles'
        self.assertEqual(self.extract([obs]), [])

    def test_receipt_offset_is_converted_to_utc(self):
        obs = observation()
        obs['response_received_at'] = '2026-11-08T05:00:01-05:00'
        record, = self.extract([obs])
        self.assertEqual(record['prediction_observed_at'], '2026-11-08T10:00:01+00:00')

    def test_csv_runner_reads_both_schemas_and_preserves_raw_files(self):
        self.assertEqual(ROOT, Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            storage = CSVStorage('test', root / 'data')
            storage.save_session_metadata({'route_id': '71342'})
            legacy = observation()
            storage.save_observation(legacy)
            routed = observation()
            routed['route_id'] = '71342'
            storage.save_observation(routed)
            originals = {p: p.read_bytes() for p in (root / 'data').rglob('*') if p.is_file()}
            records = extract_session('test', root / 'data')
            self.assertEqual(len(records), 2)
            output = root / 'results/predictions/predictions_test.csv'
            save_predictions(records, output)
            save_predictions(records, output)
            with output.open(newline='') as file:
                self.assertEqual(len(list(csv.DictReader(file))), 2)
            save_predictions([], output)
            with output.open(newline='') as file:
                self.assertEqual(list(csv.DictReader(file)), [])
            self.assertTrue(all(p.read_bytes() == content for p, content in originals.items()))


if __name__ == '__main__':
    unittest.main()
