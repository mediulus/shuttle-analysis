"""Real saved route geometry with synthetic visits; no local collection required."""

import copy
import csv
import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from shuttle_analysis.evaluation.evaluate_passio import evaluate_session
from shuttle_analysis.evaluation.plot_inputs import route_views
from shuttle_analysis.evaluation.prediction_matching import match_predictions
from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from shuttle_analysis.processing.arrivals.review_arrivals import detect_session as arrivals_session
from shuttle_analysis.processing.dwell.dwell_detector import DwellDetector
from shuttle_analysis.processing.dwell.review_dwells import detect_session as dwell_session
from shuttle_analysis.processing.predictions.review_predictions import extract_session
from shuttle_analysis.processing.shared.routes import analysis_route_ids, route_snapshot
from shuttle_analysis.storage import CSVStorage
from tests.test_arrival_detector import observation
from tests.test_eta_evaluation import prediction


def saved_routes():
    return json.loads((Path(__file__).parent / 'fixtures/saferide_routes.json').read_text())


def samples(snapshot, route_id, indices, bus_id='bus'):
    route = ArrivalDetector(route_snapshot(snapshot, route_id))
    observations = []
    for index, segment in enumerate(indices):
        sample = observation(0, index * 5, route=route_id)
        vehicle = sample['data']['buses']['device'][0]
        vehicle['latitude'], vehicle['longitude'] = route.shape[segment]
        vehicle['busId'] = bus_id
        observations.append(sample)
    return observations


class SaferideTests(unittest.TestCase):
    def test_only_two_project_routes_are_selected(self):
        snapshot = saved_routes()
        snapshot['metadata']['stop_metadata']['routes']['999'] = ['Unselected route', 'grey']
        self.assertEqual(analysis_route_ids(snapshot), ['71342', '70113'])
        for rid in analysis_route_ids(snapshot):
            with self.subTest(route=rid):
                route = ArrivalDetector(route_snapshot(snapshot, rid))
                self.assertTrue(route.stops)
                self.assertEqual(len(route.occurrences), len(route.stops))
                self.assertTrue(all(a['progress'] < b['progress']
                                    for a, b in zip(route.stops, route.stops[1:])))

    def test_route_selection_does_not_mutate_or_inherit_primary_segments(self):
        snapshot = saved_routes()
        snapshot['metadata']['stop_segments'] = {'primary': 1}
        original = copy.deepcopy(snapshot)
        selected = route_snapshot(snapshot, '70113')
        self.assertNotIn('stop_segments', selected['metadata'])
        self.assertEqual(snapshot, original)
        self.assertEqual(analysis_route_ids(selected).count('70113'), 1)
        with self.assertRaisesRegex(ValueError, 'absent'):
            route_snapshot(snapshot, 'missing')

    def test_changed_geometry_or_stop_order_requires_new_review(self):
        for change in ('shape', 'order'):
            snapshot = route_snapshot(saved_routes(), '70113')
            raw = snapshot['metadata']['stop_metadata']
            if change == 'shape':
                point = raw['routePoints']['70113'][0][50]
                point['lat'] = str(float(point['lat']) + .00001)
            else:
                raw['routes']['70113'][3], raw['routes']['70113'][4] = (
                    raw['routes']['70113'][4], raw['routes']['70113'][3])
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'changed'):
                ArrivalDetector(snapshot)

    def test_boston_east_silber_way_uses_outbound_pass(self):
        snapshot = saved_routes()
        selected = route_snapshot(snapshot, '70113')
        outbound = samples(snapshot, '70113', [278, 281, 284, 285, 287])
        inbound = samples(snapshot, '70113', [320, 322, 324, 326])
        detector = ArrivalDetector(selected)
        self.assertEqual([v['stop_id'] for v in detector.detect(outbound)], ['3042'])
        self.assertEqual(detector.detect(inbound), [])
        self.assertEqual(len([s for s in detector.stops if s['id'] == '155171']), 1)
        self.assertEqual(detector.stops[-1]['position'], '12')

    def test_same_bus_and_stop_prediction_from_other_route_is_rejected(self):
        snapshot = saved_routes()
        selected = route_snapshot(snapshot, '70113')
        observations = samples(snapshot, '70113', list(range(220, 296, 3)))
        visits = ArrivalDetector(selected).detect(observations)
        correct = prediction(*visits[:2])
        correct['route_id'] = '70113'
        wrong = {**correct, 'route_id': '71342'}
        self.assertEqual(match_predictions(selected, observations, visits, [wrong])[0], [])
        pairs, _ = match_predictions(selected, observations, visits, [wrong, correct])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]['route_id'], '70113')

    def test_runners_process_multiple_routes_and_preserve_raw_inputs(self):
        snapshot = saved_routes()
        observations = samples(snapshot, '70113', list(range(220, 296, 3)), 'east')
        for sample in observations:
            sample['data']['buses']['unselected'] = [{'busId': 'other', 'routeId': '999',
                'latitude': 42.35, 'longitude': -71.10, 'outdated': 0, 'outOfService': 0}]
        visits = ArrivalDetector(route_snapshot(snapshot, '70113')).detect(observations)
        p = prediction(*visits[:2])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            storage = CSVStorage('test', root / 'data')
            storage.save_session_metadata(snapshot['metadata'])
            for sample in observations:
                storage.save_observation(sample)
            storage.save_observation({
                'request_type': 'eta', 'route_id': '70113', 'stop_id': p['stop_id'],
                'request_started_at': p['prediction_observed_at'],
                'request_finished_at': p['prediction_observed_at'],
                'response_received_at': p['prediction_observed_at'], 'error': None,
                'data': {'ETAs': {p['stop_id']: [{
                    'busId': 'east', 'routeId': '70113', 'stopId': p['stop_id'],
                    'arrivalTimestamp': datetime.fromisoformat(p['predicted_arrival_at']).timestamp(),
                    'outdated': 0, 'OOS': 0,
                }]}},
            })
            storage.save_observation({
                'request_type': 'eta', 'route_id': '999', 'stop_id': p['stop_id'],
                'request_started_at': p['prediction_observed_at'],
                'request_finished_at': p['prediction_observed_at'],
                'response_received_at': p['prediction_observed_at'], 'error': None,
                'data': {'ETAs': {p['stop_id']: [{
                    'busId': 'other', 'routeId': '999', 'stopId': p['stop_id'],
                    'arrivalTimestamp': datetime.fromisoformat(p['predicted_arrival_at']).timestamp(),
                    'outdated': 0, 'OOS': 0,
                }]}},
            })
            self.assertEqual({r['route_id'] for r in extract_session('test', root / 'data')}, {'70113'})
            originals = {f: f.read_bytes() for f in (root / 'data').rglob('*') if f.is_file()}
            self.assertEqual({v['route_id'] for v in arrivals_session('test', root / 'data')},
                             {'70113'})
            self.assertEqual({v['route_id'] for v in dwell_session('test', root / 'data')},
                             {'70113'})
            results, _, _ = evaluate_session('test', root / 'data')
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]['route_id'], '70113')
            self.assertEqual(results[0]['error_seconds'], 20)
            self.assertTrue(all(f.read_bytes() == content for f, content in originals.items()))

    def test_plot_inputs_separate_shared_stop_ids(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            storage = CSVStorage('test', root / 'data')
            storage.save_session_metadata(saved_routes()['metadata'])
            path = root / 'results/evaluation/passio/errors/passio_errors_test.csv'
            path.parent.mkdir(parents=True)
            with path.open('w', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=['route_id', 'stop_id'])
                writer.writeheader()
                writer.writerows([{'route_id': rid, 'stop_id': '3042'}
                                  for rid in ['71342', '70113']])
            views = route_views(root)
            self.assertEqual(len(views), 2)
            for snapshot, rows, suffix in views:
                rid = snapshot['metadata']['route_id']
                self.assertTrue(all(row['route_id'] == rid for row in rows))
                if rid == '70113':
                    self.assertEqual(suffix, 'route_70113_all')
                    self.assertEqual(len(rows), 1)
            self.assertEqual(len(route_views(root, route_id='70113')), 1)
            with self.assertRaisesRegex(ValueError, 'absent'):
                route_views(root, route_id='999')


if __name__ == '__main__':
    unittest.main()
