"""Compare paired arrival timestamps, independently of the prediction model."""

from datetime import datetime


def evaluate(pairs):
    """Return copies of paired records with signed and absolute errors in seconds."""
    results = []
    for pair in pairs:
        predicted = datetime.fromisoformat(pair["predicted_arrival_at"])
        actual = datetime.fromisoformat(pair["estimated_arrival_at"])
        error = (predicted - actual).total_seconds()
        results.append({**pair, "error_seconds": error, "absolute_error_seconds": abs(error)})
    return results


def summarize(results):
    """Summarize one group. Empty groups have no mean, rather than zero error."""
    count = len(results)
    return {
        "count": count,
        "mae_seconds": sum(row["absolute_error_seconds"] for row in results) / count if count else None,
        "mean_error_seconds": sum(row["error_seconds"] for row in results) / count if count else None,
    }
