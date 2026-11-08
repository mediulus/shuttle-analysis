"""Small routes check visit matching separately from reusable error arithmetic."""

import copy
import csv
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from shuttle_analysis.evaluation.eta_evaluator import evaluate, summarize
from shuttle_analysis.evaluation.prediction_matching import match_predictions
from shuttle_analysis.evaluation.evaluate_passio import (
    evaluate_session, summarize_checkpoints, save_csv, RESULT_FIELDS, ROOT,
)
from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from shuttle_analysis.storage import CSVStorage
from tests.test_arrival_detector import snapshot, observation


def shift(timestamp, seconds):
    return (datetime.fromisoformat(timestamp) + timedelta(seconds=seconds)).isoformat()


def samples():
    points = [(40, 0), (100, 0), (180, 0), (200, 100), (200, 180),
              (100, 200), (0, 180), (0, 100), (0, 20), (40, 0), (100, 0)]
    return [observation(x, i * 30, y=y) for i, (x, y) in enumerate(points)]


def prediction(checkpoint, target, age=5, error=20):
    return {
        'session_id': 'test', 'bus_id': 'bus', 'route_id': 'r', 'stop_id': target['stop_id'],
        'prediction_observed_at': shift(checkpoint['estimated_arrival_at'], -age),
        'predicted_arrival_at': shift(target['estimated_arrival_at'], error),
        'trip_id': 'trip', 'passio_stop_position': target['route_stop_position'],
        'outdated': 0, 'out_of_service': 0,
    }


class EvaluatorTests(unittest.TestCase):
    def test_errors_means_and_input_preservation(self):
        actual = '2026-11-08T10:00:00+00:00'
        pairs = [{'estimated_arrival_at': actual, 'predicted_arrival_at': shift(actual, e)}
                 for e in [30, -10, 0]]
        original = copy.deepcopy(pairs)
        results = evaluate(pairs)
        self.assertEqual([r['error_seconds'] for r in results], [30, -10, 0])
        self.assertAlmostEqual(summarize(results)['mae_seconds'], 40 / 3)
        self.assertAlmostEqual(summarize(results)['mean_error_seconds'], 20 / 3)
        self.assertEqual(pairs, original)
        self.assertEqual(summarize([]), {'count': 0, 'mae_seconds': None, 'mean_error_seconds': None})

    def test_timezone_offsets_compare_same_instant(self):
        result, = evaluate([{'predicted_arrival_at': '2026-11-08T05:00:00-05:00',
                             'estimated_arrival_at': '2026-11-08T10:00:00+00:00'}])
        self.assertEqual(result['error_seconds'], 0)


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.observations = samples()
        self.arrivals = ArrivalDetector(snapshot()).detect(self.observations)
        self.checkpoint, self.target = self.arrivals[:2]

    def match(self, predictions, observations=None, arrivals=None):
        return match_predictions(snapshot(), observations or self.observations,
                                 arrivals or self.arrivals, predictions)

    def test_one_through_four_stops_and_loop_boundary(self):
        predictions = [prediction(self.checkpoint, target) for target in self.arrivals[1:5]]
        pairs, coverage = self.match(predictions)
        selected = [r for r in pairs if r['checkpoint_at'] == self.checkpoint['estimated_arrival_at']]
        self.assertEqual([r['stops_ahead'] for r in selected], [1, 2, 3, 4])
        self.assertEqual([r['stop_id'] for r in selected], ['2', '3', '4', '0'])
        self.assertEqual([r['error_seconds'] for r in evaluate(selected)], [20] * 4)
        summary = summarize_checkpoints(evaluate(pairs), coverage)
        for row in summary:
            self.assertEqual(row['checkpoints'], sum(row[k] for k in
                ['count', 'no_target_arrival', 'no_prediction', 'ambiguous_prediction']))

    def test_latest_prediction_before_checkpoint_and_age_limit(self):
        old = prediction(self.checkpoint, self.target, age=30, error=-100)
        latest = prediction(self.checkpoint, self.target, age=1, error=20)
        future = prediction(self.checkpoint, self.target, age=-1, error=0)
        pairs, _ = self.match([old, future, latest])
        pair, = [p for p in pairs if p['checkpoint_at'] == self.checkpoint['estimated_arrival_at']]
        self.assertEqual(pair['predicted_arrival_at'], latest['predicted_arrival_at'])
        self.assertTrue(self.match([old])[0])
        self.assertEqual(self.match([prediction(self.checkpoint, self.target, age=30.1)])[0], [])
        self.assertEqual(self.match([future])[0], [])

    def test_predicted_time_does_not_select_a_later_loop(self):
        # A terrible prediction is still compared to the next supported visit.
        bad = prediction(self.checkpoint, self.target, error=3600)
        pairs, _ = self.match([bad])
        self.assertEqual(pairs[0]['estimated_arrival_at'], self.target['estimated_arrival_at'])
        self.assertEqual(evaluate(pairs)[0]['error_seconds'], 3600)

    def test_ambiguous_entries_skipped_but_identical_duplicates_allowed(self):
        first = prediction(self.checkpoint, self.target)
        other = prediction(self.checkpoint, self.target, error=40)
        pairs, coverage = self.match([first, other])
        self.assertEqual(pairs, [])
        self.assertTrue(any(r['status'] == 'ambiguous_prediction' for r in coverage))
        self.assertEqual(len(self.match([first, copy.deepcopy(first)])[0]), 1)

    def test_flags_and_identity_filtering(self):
        for field, value in [('outdated', 1), ('out_of_service', '1'), ('outdated', None),
                             ('session_id', 'other'), ('route_id', 'other'), ('bus_id', 'other')]:
            p = prediction(self.checkpoint, self.target)
            p[field] = value
            self.assertEqual(self.match([p])[0], [])

    def test_missing_target_does_not_match_next_loop(self):
        # Remove C's first visit; later arrival at B is already a full loop away.
        arrivals = [r for r in self.arrivals if r is not self.target]
        pairs, coverage = self.match([prediction(self.checkpoint, self.target)], arrivals=arrivals)
        self.assertEqual(pairs, [])
        first, = [r for r in coverage if r['checkpoint_at'] == self.checkpoint['estimated_arrival_at']
                   and r['stops_ahead'] == 1]
        self.assertEqual(first['status'], 'no_target_arrival')

    def test_missing_first_visit_is_not_replaced_by_same_stop_next_loop(self):
        observations = self.observations + [observation(180, 330), observation(200, 360, y=100)]
        arrivals = ArrivalDetector(snapshot()).detect(observations)
        arrivals = [r for r in arrivals if r['estimated_arrival_at'] != self.target['estimated_arrival_at']]
        pairs, coverage = self.match([prediction(self.checkpoint, self.target)],
                                     observations=observations, arrivals=arrivals)
        self.assertEqual(pairs, [])
        first, = [r for r in coverage if r['checkpoint_at'] == self.checkpoint['estimated_arrival_at']
                   and r['stops_ahead'] == 1]
        self.assertEqual(first['status'], 'no_target_arrival')

    def test_failed_request_splits_matching_history(self):
        observations = self.observations + [observation(0, 70, error='Timeout')]
        # Even supplying old arrival records cannot bridge the failed GPS request.
        pairs, _ = self.match([prediction(self.checkpoint, self.target)], observations=observations)
        self.assertEqual(pairs, [])

    def test_invalid_settings(self):
        with self.assertRaises(ValueError):
            match_predictions(snapshot(), [], [], [], max_stops=5)
        with self.assertRaises(ValueError):
            match_predictions(snapshot(), [], [], [], max_age_seconds=-1)

    def test_runner_writes_results_without_changing_inputs(self):
        self.assertEqual(ROOT, Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            storage = CSVStorage('test', root / 'data')
            storage.save_session_metadata(snapshot()['metadata'])
            for obs in self.observations:
                storage.save_observation(obs)
            p = prediction(self.checkpoint, self.target)
            timestamp = p['prediction_observed_at']
            storage.save_observation({
                'request_type': 'eta', 'route_id': 'r', 'stop_id': p['stop_id'], 'error': None,
                'request_started_at': timestamp, 'request_finished_at': timestamp,
                'response_received_at': timestamp,
                'data': {'ETAs': {p['stop_id']: [{
                    'busId': 'bus', 'routeId': 'r', 'stopId': p['stop_id'],
                    'arrivalTimestamp': datetime.fromisoformat(p['predicted_arrival_at']).timestamp(),
                    'outdated': 0, 'OOS': 0,
                }]}},
            })
            originals = {f: f.read_bytes() for f in (root / 'data').rglob('*') if f.is_file()}
            results, coverage, summary = evaluate_session('test', root / 'data')
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]['error_seconds'], 20)
            output = root / 'results/errors.csv'
            save_csv(results, output, RESULT_FIELDS)
            save_csv(results, output, RESULT_FIELDS)
            with output.open(newline='') as file:
                self.assertEqual(len(list(csv.DictReader(file))), 1)
            self.assertTrue(all(f.read_bytes() == content for f, content in originals.items()))


if __name__ == '__main__':
    unittest.main()
