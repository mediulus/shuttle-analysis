"""Combined ETA: weighted average of the historical and live predictions."""

import unittest

from combined_prediction import combine


def row(stop_id, seconds, observed='2026-11-05T00:00:00+00:00'):
    return {'session_id': 'test', 'bus_id': 'bus', 'route_id': 'r', 'stop_id': stop_id,
            'route_stop_position': stop_id, 'prediction_observed_at': observed,
            'predicted_seconds': seconds, 'predicted_arrival_at': '', 'leg_sources': 'x'}


class CombineTests(unittest.TestCase):
    def test_equal_weights_average_matching_rows(self):
        combined = combine([row('1', 100), row('2', 300)], [row('1', 60), row('3', 500)])
        # Stop 2 has no live row and stop 3 has no historical row, so only stop 1 is combined.
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]['predicted_seconds'], 80.0)
        self.assertEqual(combined[0]['predicted_arrival_at'], '2026-11-05T00:01:20+00:00')

    def test_weights_need_not_sum_to_one(self):
        combined = combine([row('1', 100)], [row('1', 60)], w_historical=3, w_current=1)
        self.assertEqual(combined[0]['predicted_seconds'], 90.0)


if __name__ == '__main__':
    unittest.main()
