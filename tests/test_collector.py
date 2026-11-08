"""Offline checks for route switching and append-only route-aware storage."""

import csv
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

import requests

from shuttle_analysis.collection.collector import Collector, collection_routes, main
from shuttle_analysis.collection.passio_api import PassioAPI
from shuttle_analysis.storage import CSVStorage, CSV_FIELDS, ROUTE_CSV_FIELDS


def stop_metadata():
    return {"routes": {
        "71342": ["Boston Daytime", "blue", ["1", "979", 0], ["2", "991", 0], ["3", "979", 1]],
        "70113": ["Saferide Boston East", "red", ["1", "979", 0], ["2", "973", 0]],
        "45010": ["Saferide Cambridge All", "yellow", ["1", "3048", 0]],
        "73992": ["Tech Shuttle NW", "black", ["1", "999", 0]],
    }, "stops": {}, "routePoints": {}}


def vehicles(*route_ids):
    return {"buses": {str(index): [{"busId": index, "routeId": route_id,
                                 "outdated": 0, "outOfService": 0}]
                      for index, route_id in enumerate(route_ids)}}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def configured_collector(self, api, storage=None):
        routes = collection_routes(stop_metadata(), 71342)
        return Collector(api, routes["71342"]["stop_ids"], storage=storage, routes=routes)

    def test_metadata_discovers_saferide_and_deduplicates_occurrences(self):
        routes = collection_routes(stop_metadata(), 71342)
        self.assertEqual(list(routes), ["71342", "70113", "45010"])
        self.assertEqual(routes["71342"]["stop_ids"], ["979", "991"])
        with self.assertRaises(ValueError):
            collection_routes(stop_metadata(), "missing")

    def test_api_route_override_does_not_mutate_client(self):
        api = PassioAPI()
        with patch("shuttle_analysis.collection.passio_api.requests.get") as get:
            api.get_etas(979, route_id="70113")
            self.assertEqual(get.call_args.kwargs["params"]["routeId"], "70113")
            api.get_etas(979)
            self.assertEqual(get.call_args.kwargs["params"]["routeId"], 71342)
        self.assertEqual(api.route_id, 71342)

    def test_daytime_switches_to_saferide_based_on_assignments(self):
        api = Mock()
        api.get_vehicles.side_effect = [vehicles("71342"), vehicles("70113")]
        collector = self.configured_collector(api)
        first = collector.collect_once()
        second = collector.collect_once()
        self.assertEqual(api.method_calls, [
            call.get_vehicles(), call.get_etas("979", route_id="71342"), call.get_etas("991", route_id="71342"),
            call.get_vehicles(), call.get_etas("979", route_id="70113"), call.get_etas("973", route_id="70113"),
        ])
        self.assertEqual(first[1]["route_id"], "71342")
        self.assertEqual(second[1]["route_id"], "70113")

    def test_overlapping_service_polls_each_route_stop_pair_once(self):
        api = Mock()
        api.get_vehicles.return_value = vehicles("71342", "70113", "70113", "45010", "73992")
        observations = self.configured_collector(api).collect_once()
        self.assertEqual(len(observations), 6)
        self.assertEqual(api.get_vehicles.call_count, 1)
        self.assertEqual(api.get_etas.call_args_list, [
            call("979", route_id="71342"), call("991", route_id="71342"),
            call("979", route_id="70113"), call("973", route_id="70113"),
            call("3048", route_id="45010"),
        ])

    def test_no_active_service_only_collects_gps(self):
        api = Mock()
        api.get_vehicles.return_value = vehicles("73992")
        observations = self.configured_collector(api).collect_once()
        self.assertEqual(len(observations), 1)
        api.get_etas.assert_not_called()

    def test_flagged_vehicles_do_not_activate_route(self):
        response = vehicles("70113", "45010")
        response["buses"]["0"][0]["outdated"] = 1
        response["buses"]["1"][0]["outOfService"] = 1
        api = Mock()
        api.get_vehicles.return_value = response
        self.configured_collector(api).collect_once()
        api.get_etas.assert_not_called()

    def test_gps_failure_reuses_previous_routes(self):
        api = Mock()
        api.get_vehicles.side_effect = [vehicles("70113"), requests.Timeout("offline")]
        collector = self.configured_collector(api)
        collector.collect_once()
        failed_cycle = collector.collect_once()
        self.assertIn("Timeout", failed_cycle[0]["error"])
        self.assertEqual([obs["route_id"] for obs in failed_cycle[1:]], ["70113", "70113"])

    def test_startup_gps_failure_or_malformed_response_polls_all_configured_routes(self):
        for response in (None, {"buses": []}, {"buses": {"bad": None}}):
            api = Mock()
            api.get_vehicles.return_value = response
            observations = self.configured_collector(api).collect_once()
            self.assertEqual({obs["route_id"] for obs in observations[1:]}, {"71342", "70113", "45010"})

    def test_failed_eta_is_recorded_without_stopping_other_routes(self):
        api = Mock()
        api.get_vehicles.return_value = vehicles("71342", "70113")
        api.get_etas.side_effect = [requests.Timeout("slow"), {}, {}, {}]
        observations = self.configured_collector(api).collect_once()
        self.assertEqual(len(observations), 5)
        self.assertEqual(observations[1]["route_id"], "71342")
        self.assertIsNone(observations[1]["data"])
        self.assertEqual(observations[-1]["route_id"], "70113")

    def test_legacy_single_route_order_and_storage_failure(self):
        api = Mock()
        collector = Collector(api, [979])
        observations = collector.collect_once()
        self.assertEqual(api.method_calls, [call.get_etas(979), call.get_vehicles()])
        self.assertNotIn("route_id", observations[0])
        storage = Mock()
        storage.save_observation.side_effect = OSError("disk full")
        with self.assertRaises(OSError):
            self.configured_collector(api, storage).collect_once()

    def test_both_csv_schemas_round_trip_without_rewriting_legacy(self):
        with TemporaryDirectory() as directory:
            storage = CSVStorage("session", directory)
            api = Mock()
            api.get_etas.return_value = {"ETAs": {"979": []}}
            api.get_vehicles.return_value = vehicles("71342", "70113")
            Collector(api, [979], storage=storage).collect_once()
            legacy = Path(directory) / "eta_predictions.csv"
            original = legacy.read_bytes()
            api.get_etas.side_effect = [requests.Timeout("slow"), {}, {}, {}]
            self.configured_collector(api, storage).collect_once()
            self.assertEqual(legacy.read_bytes(), original)
            route_file = Path(directory) / "eta_predictions_by_route.csv"
            with legacy.open(newline="") as file:
                self.assertEqual(next(csv.reader(file)), CSV_FIELDS)
            with route_file.open(newline="") as file:
                self.assertEqual(next(csv.reader(file)), ROUTE_CSV_FIELDS)
            observations = storage.read_observations("eta")
            self.assertEqual(len(observations), 5)
            self.assertNotIn("route_id", observations[0])
            self.assertEqual(observations[1]["route_id"], "71342")
            self.assertIsNone(observations[1]["data"])
            self.assertEqual(observations[-1]["route_id"], "70113")
            self.assertEqual(observations[-1]["source_ref"]["file"], route_file.name)
            route_file.write_text("wrong,header\n")
            with self.assertRaises(ValueError):
                storage.save_observation(observations[-1])
            self.assertEqual(route_file.read_text(), "wrong,header\n")

    def test_script_startup_saves_configuration_and_collects_saferide(self):
        with TemporaryDirectory() as directory:
            api = Mock(system_id=94, route_id=71342, timeout=10, url="https://example.invalid")
            api.get_stops.return_value = stop_metadata()
            api.get_vehicles.return_value = vehicles("70113")
            api.get_etas.return_value = {"ETAs": {}}
            def temporary_storage(session_id, data_dir):
                self.assertEqual(data_dir, Path(__file__).resolve().parents[1] / "data")
                return CSVStorage(session_id, directory)
            with patch("shuttle_analysis.collection.passio_api.PassioAPI", return_value=api), \
                 patch("shuttle_analysis.storage.CSVStorage", side_effect=temporary_storage), \
                 patch("time.sleep", side_effect=KeyboardInterrupt):
                main()
            snapshot_path, = (Path(directory) / "sessions").glob("*.json")
            snapshot = json.loads(snapshot_path.read_text())
            self.assertEqual(set(snapshot["metadata"]["eta_routes"]), {"71342", "70113", "45010"})
            rows = CSVStorage(snapshot["session_id"], directory).read_observations("eta")
            self.assertEqual([row["route_id"] for row in rows], ["70113", "70113"])


if __name__ == "__main__":
    unittest.main()
