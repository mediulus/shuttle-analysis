#!/usr/bin/env python3
"""Run existing processors on one synthetic service day; write only local results."""
import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from shuttle_analysis.evaluation.evaluate_passio import evaluate_session, save_csv, RESULT_FIELDS, CHECKPOINT_FIELDS, SUMMARY_FIELDS
from shuttle_analysis.processing.arrivals.review_arrivals import detect_session as arrivals, save_arrivals
from shuttle_analysis.processing.dwell.review_dwells import detect_session as dwells, save_dwells
from shuttle_analysis.processing.predictions.review_predictions import extract_session, save_predictions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=HERE / 'generated')
    parser.add_argument('--day', required=True)
    parser.add_argument('--route-id', choices=['71342', '70113'])
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    if not dataset.is_relative_to(HERE):
        parser.error('Select a dataset under trip simulation')
    with (dataset / 'manifest.csv').open(newline='') as file:
        selected = [r for r in csv.DictReader(file) if r['service_date'] == args.day
                    and (not args.route_id or r['route_id'] == args.route_id)]
    if not selected:
        parser.error('No service for this date/route in the manifest')
    for row in selected:
        sid, data_dir = row['session_id'], dataset / row['data_dir']
        output = dataset / 'results' / args.day / row['route_id']
        save_arrivals(arrivals(sid, data_dir), output / 'arrivals.csv')
        save_dwells(dwells(sid, data_dir), output / 'dwells.csv')
        save_predictions(extract_session(sid, data_dir), output / 'predictions.csv')
        errors, coverage, summary = evaluate_session(sid, data_dir)
        save_csv(errors, output / 'errors.csv', RESULT_FIELDS)
        save_csv(coverage, output / 'coverage.csv', [*CHECKPOINT_FIELDS, 'status'])
        save_csv(summary, output / 'summary.csv', SUMMARY_FIELDS)
        print(f'{sid}: {len(errors)} evaluated predictions; results in {output}')


if __name__ == '__main__':
    main()
