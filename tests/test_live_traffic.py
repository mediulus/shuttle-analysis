"""Per-leg TomTom times from one shape-guided loop, without network access."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live_data_collection" / "collection"))
import live_traffic  # noqa: E402

from tests.test_arrival_detector import snapshot  # noqa: E402


class LiveTrafficTests(unittest.TestCase):
    def test_leg_times_are_read_off_time_along_the_loop(self):
        # Square test route: 800 m loop, stops at 100, 300, 500, 700 and 800 (= 0) m.
        metadata = snapshot()["metadata"]
        route = live_traffic.route_stops(metadata["stop_metadata"], "r", metadata["stop_segments"])
        self.assertEqual([s["position"] for s in route["stops"]], ["2", "3", "4", "5", "6"])
        # TomTom: 1 s/m on the first 100 m, then 0.5 s/m (450 s for the 800 m loop).
        progress = [{"distanceInMeters": 0, "travelTimeInSeconds": 0},
                    {"distanceInMeters": 100, "travelTimeInSeconds": 100},
                    {"distanceInMeters": 800, "travelTimeInSeconds": 450}]
        response = mock.Mock()
        response.json.return_value = {"routes": [{"summary": {
            "lengthInMeters": 800, "travelTimeInSeconds": 450,
            "noTrafficTravelTimeInSeconds": 360, "trafficDelayInSeconds": 45}, "progress": progress}]}
        with mock.patch.object(live_traffic.requests, "post", return_value=response) as post:
            rows = live_traffic.fetch_legs("r", route, "2026-11-14T00:00:00+00:00")
        body = post.call_args.kwargs["json"]
        self.assertEqual(len(body["supportingPoints"]), len(route["shape"]))
        legs = {(r["from_position"], r["to_position"]): r for r in rows}
        self.assertEqual(len(rows), 5)
        self.assertEqual(legs[("2", "3")]["length_m"], 200)
        self.assertAlmostEqual(legs[("2", "3")]["travel_time_s"], 100)        # 200 m at 0.5 s/m
        self.assertAlmostEqual(legs[("6", "2")]["travel_time_s"], 100)        # first 100 m at 1 s/m
        self.assertAlmostEqual(sum(r["travel_time_s"] for r in rows), 450)
        self.assertAlmostEqual(legs[("2", "3")]["no_traffic_time_s"], 80)     # 100 * 360/450
        self.assertAlmostEqual(legs[("2", "3")]["traffic_delay_s"], 10)       # 100 * 45/450

    def test_loop_far_from_shuttle_length_is_rejected(self):
        metadata = snapshot()["metadata"]
        route = live_traffic.route_stops(metadata["stop_metadata"], "r", metadata["stop_segments"])
        response = mock.Mock()
        response.json.return_value = {"routes": [{"summary": {
            "lengthInMeters": 1200, "travelTimeInSeconds": 450,
            "noTrafficTravelTimeInSeconds": 360, "trafficDelayInSeconds": 0},
            "progress": [{"distanceInMeters": 0, "travelTimeInSeconds": 0},
                         {"distanceInMeters": 1200, "travelTimeInSeconds": 450}]}]}
        with mock.patch.object(live_traffic.requests, "post", return_value=response):
            with self.assertRaises(ValueError):
                live_traffic.fetch_legs("r", route, "2026-11-14T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
