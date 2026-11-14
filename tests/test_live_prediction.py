"""Live current-term predictions on the small square test route.

Route (800 m loop): stop IDs 1..4, 0 at route positions 2..6, at 100, 300,
500, 700 and 800 m along the loop.
"""

import csv
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from live_prediction_model.predictor import LivePredictor, Settings
from live_prediction_model.traffic import load_traffic
from shuttle_analysis.evaluation.prediction_matching import match_predictions
from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from tests.test_arrival_detector import snapshot, observation
from tests.test_eta_evaluation import samples as loop_samples


def with_second_bus(samples, positions):
    """Add bus 'second' at {sample index: (x, y)}; it is absent elsewhere."""
    for i, (x, y) in positions.items():
        record = dict(observation(x, i * 30, y=y)['data']['buses']['device'][0])
        record['busId'] = 'second'
        samples[i]['data']['buses']['other'] = [record]
    return samples


def at(predictions, bus_id, seconds):
    rows = [p for p in predictions if p['bus_id'] == bus_id
            and p['prediction_observed_at'] == observation(0, seconds)['response_received_at']]
    return {row['stop_id']: row for row in rows}


class LivePredictionTests(unittest.TestCase):
    def predict(self, samples, **kwargs):
        return LivePredictor(snapshot(), **kwargs).predict(samples)

    def test_fallback_only_partial_leg_then_dwell_and_legs(self):
        rows = at(self.predict([observation(40, 0)]), 'bus', 0)
        self.assertEqual([rows[s]['stops_away'] for s in ['1', '2', '3', '4']], [1, 2, 3, 4])
        # 60 m left of a 100 m leg at 5 m/s: 12 s. Then 30 s default dwell + 200 m / 5 m/s.
        self.assertAlmostEqual(rows['1']['predicted_seconds'], 12)
        self.assertAlmostEqual(rows['2']['predicted_seconds'], 12 + 30 + 40)
        self.assertAlmostEqual(rows['3']['predicted_seconds'], 82 + 30 + 40)
        self.assertEqual(rows['1']['leg_sources'], 'fallback')

    def test_last_bus_leg_time_and_dwell_are_blended(self):
        # Bus 1 passes stop 1 (inside only at 30 s, dwell 0) and reaches stop 2 at 120 s.
        points = [(40, 0), (100, 0), (160, 0), (200, 40), (200, 100)]
        samples = [observation(x, i * 30, y=y) for i, (x, y) in enumerate(points)]
        samples = with_second_bus(samples, {3: (40, 0), 4: (100, 0)})
        rows = at(self.predict(samples), 'second', 120)
        # T_last(2->3) = 120 - 30 = 90 s; fallback 40 s; weights 0.45 / 0.1.
        blended = (0.45 * 90 + 0.1 * 40) / 0.55
        self.assertAlmostEqual(rows['2']['predicted_seconds'], round(blended, 1))
        self.assertEqual(rows['2']['current_stop_position'], '2')
        self.assertTrue(rows['2']['leg_sources'].startswith('last+fallback'))

    def test_bus_inside_stop_adds_only_remaining_dwell(self):
        # Bus 1 dwells 60 s at stop 1 (known when it leaves at 120 s).
        points = [40, 100, 105, 110, 160]
        samples = [observation(x, i * 30) for i, x in enumerate(points)]
        samples += [observation(165, 150), observation(170, 180)]
        samples = with_second_bus(samples, {4: (40, 0), 5: (100, 0), 6: (100, 0)})
        rows = at(self.predict(samples), 'second', 180)
        # 40 s fallback for 200 m to stop 2, plus 60 - 30 s already spent.
        self.assertAlmostEqual(rows['2']['predicted_seconds'], 70)

    def test_tomtom_reading_is_used_after_it_arrives(self):
        reading = datetime.fromisoformat(observation(0, 30)['response_received_at'])
        predictor = LivePredictor(snapshot(), traffic={('6', '2'): [(reading, 100)]})
        rows = predictor.predict([observation(40, 0), observation(50, 30)])
        before, after = at(rows, 'bus', 0)['1'], at(rows, 'bus', 30)['1']
        self.assertEqual(before['leg_sources'].split(';')[0], 'fallback')
        self.assertEqual(after['leg_sources'].split(';')[0], 'tomtom+fallback')
        # 50 m left of 100 m: half of the blended leg time.
        self.assertAlmostEqual(after['predicted_seconds'], round((0.45 * 100 + 0.1 * 20) / 0.55 / 2, 1))

    def test_old_tomtom_reading_is_ignored(self):
        reading = datetime.fromisoformat(observation(0, -1000)['response_received_at'])
        rows = LivePredictor(snapshot(), traffic={('6', '2'): [(reading, 100)]}).predict([observation(40, 0)])
        self.assertEqual(at(rows, 'bus', 0)['1']['leg_sources'].split(';')[0], 'fallback')

    def test_traffic_loader_skips_legs_on_a_different_path(self):
        fields = ['collected_at_utc', 'route_id', 'from_position', 'to_position', 'length_m', 'travel_time_s']
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'traffic_legs.csv'
            with path.open('w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(fields)
                writer.writerow(['2026-11-05T00:00:00+00:00', 'r', '2', '3', '205', '50'])   # matches 200 m
                writer.writerow(['2026-11-05T00:00:00+00:00', 'r', '3', '4', '60', '50'])    # shortcut
                writer.writerow(['2026-11-05T00:00:00+00:00', 'other', '2', '3', '200', '9'])
            legs = LivePredictor(snapshot()).leg_lengths
            self.assertEqual(list(load_traffic('r', legs, path)), [('2', '3')])

    def test_predictions_never_use_later_observations(self):
        samples = loop_samples()
        full = self.predict(samples)
        for k in range(1, len(samples)):
            cutoff = samples[k - 1]['response_received_at']
            early = [p for p in full if p['prediction_observed_at'] <= cutoff]
            self.assertEqual(self.predict(samples[:k]), early)

    def test_weights_change_only_when_source_is_present(self):
        rows = at(self.predict([observation(40, 0)], settings=Settings(w_fallback=0)), 'bus', 0)
        # No other source yet, so the fallback is still used.
        self.assertAlmostEqual(rows['1']['predicted_seconds'], 12)

    def test_predictions_match_existing_checkpoint_evaluation(self):
        samples = loop_samples()
        predictions = self.predict(samples)
        arrivals = ArrivalDetector(snapshot()).detect(samples)
        pairs, coverage = match_predictions(snapshot(), samples, arrivals, predictions)
        self.assertTrue(pairs)
        self.assertNotIn('no_prediction', {row['status'] for row in coverage})
        self.assertTrue(all(p['prediction_observed_at'] == p['checkpoint_at'] for p in pairs))


if __name__ == '__main__':
    unittest.main()
