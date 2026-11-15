"""Train the historical model and save it in results/historical_model/.

Training rows are the simulated dataset plus the real sessions the simulator
was calibrated on. Every other real session is left for testing.

    .venv/bin/python -m historical_prediction_model.train
"""

import argparse

from .features import FeatureBuilder
from .labels import MODEL_DIR, session_labels, simulated_labels, training_sessions
from .model import save, train


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, help="Processes for reading the simulated data (default: all cores)")
    parser.add_argument("--rebuild-labels", action="store_true",
                        help="Re-read the simulated sessions instead of using the cached rows")
    args = parser.parse_args()
    labels = simulated_labels(args.jobs, args.rebuild_labels)
    sessions = training_sessions()
    for session_id in sessions:
        for target, rows in session_labels(session_id).items():
            labels[target].extend(rows)
    boosted, baseline, report = train(labels, FeatureBuilder())
    save(boosted, baseline, {"training_sessions": sessions, **report})
    print(f"Saved model to {MODEL_DIR}")


if __name__ == "__main__":
    main()
