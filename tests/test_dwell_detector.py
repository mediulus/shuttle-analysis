"""Small stop visits verify dwell timing and agreement with arrivals."""

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from shuttle_analysis.processing.dwell.dwell_detector import DwellDetector
from shuttle_analysis.processing.dwell.review_dwells import detect_session, save_dwells, ROOT
from shuttle_analysis.storage import CSVStorage
from tests.test_arrival_detector import snapshot, observation


class DwellTests(unittest.TestCase):
    def dwells(self, samples):
        return DwellDetector(snapshot()).detect(samples)

    def test_completed_visit_matches_arrival_and_measures_inside_span(self):
        samples = [observation(x, i * 30) for i, x in enumerate([40, 80, 100, 110, 160])]
        dwell, = self.dwells(samples)
        arrival, = ArrivalDetector(snapshot()).detect(samples)
        self.assertEqual({key: dwell[key] for key in arrival}, arrival)
        self.assertEqual(dwell['observed_dwell_seconds'], 60)
        self.assertEqual(dwell['last_inside_at'], samples[3]['response_received_at'])
        self.assertEqual(dwell['first_outside_at'], samples[4]['response_received_at'])

    def test_single_inside_sample_is_zero_not_thirty_seconds(self):
        dwell, = self.dwells([observation(40, 0), observation(100, 30), observation(160, 60)])
        self.assertEqual(dwell['observed_dwell_seconds'], 0)

    def test_incomplete_start_inside_and_between_samples_are_omitted(self):
        for samples in [
            [observation(40, 0), observation(100, 30)],
            [observation(100, 0), observation(110, 30), observation(160, 60)],
            [observation(40, 0), observation(160, 30)],
        ]:
            self.assertEqual(self.dwells(samples), [])

    def test_missing_or_unreliable_data_does_not_close_visit(self):
        missing = observation(100, 60)
        missing['data'] = {'buses': {}}
        invalid = observation(100, 60)
        invalid['data']['buses']['device'][0]['latitude'] = 'nan'
        stale = observation(100, 60)
        stale['data']['buses']['device'][0]['outdated'] = 1
        for middle in [missing, invalid, stale, observation(100, 60, error='Timeout'),
                       observation(100, 60, route='other')]:
            samples = [observation(40, 0), observation(100, 30), middle, observation(160, 90)]
            self.assertEqual(self.dwells(samples), [])
        self.assertEqual(self.dwells([observation(40, 0), observation(100, 30), observation(160, 120)]), [])

    def test_reentry_does_not_duplicate_visit(self):
        samples = [observation(x, i * 30) for i, x in enumerate([40, 100, 140, 120, 100, 160])]
        self.assertEqual(len(self.dwells(samples)), 1)

    def test_loop_boundary_visit_and_next_loop(self):
        locations = [(0, 60), (0, 10), (10, 0), (60, 0), (100, 0),
                     (180, 0), (200, 100), (200, 180), (100, 200),
                     (0, 180), (0, 100), (0, 10), (10, 0), (60, 0)]
        samples = [observation(x, i * 30, y=y) for i, (x, y) in enumerate(locations)]
        visits = [d for d in self.dwells(samples) if d['stop_id'] == '0']
        self.assertEqual(len(visits), 2)
        self.assertEqual([v['observed_dwell_seconds'] for v in visits], [30, 30])

    def test_csv_runner_preserves_inputs_and_replaces_derived_output(self):
        self.assertEqual(ROOT, Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            storage = CSVStorage('test', root / 'data')
            storage.save_session_metadata(snapshot()['metadata'])
            for i, x in enumerate([40, 100, 110, 160]):
                storage.save_observation(observation(x, i * 30))
            originals = {p: p.read_bytes() for p in (root / 'data').rglob('*') if p.is_file()}
            dwells = detect_session('test', root / 'data')
            output = root / 'results/dwell/dwells_test.csv'
            save_dwells(dwells, output)
            save_dwells(dwells, output)
            with output.open(newline='') as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 1)
            self.assertEqual(float(rows[0]['observed_dwell_seconds']), 30)
            self.assertTrue(all(p.read_bytes() == content for p, content in originals.items()))

    def test_buses_are_tracked_separately(self):
        samples = [observation(x, i * 30) for i, x in enumerate([40, 100, 110, 160])]
        for i, sample in enumerate(samples):
            second = dict(observation([40, 40, 100, 160][i], i * 30)['data']['buses']['device'][0])
            second['busId'] = 'second'
            sample['data']['buses']['other'] = [second]
        self.assertEqual({d['bus_id']: d['observed_dwell_seconds'] for d in self.dwells(samples)},
                         {'bus': 30, 'second': 0})


if __name__ == '__main__':
    unittest.main()
