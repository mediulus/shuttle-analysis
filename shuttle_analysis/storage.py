import csv
import json
from pathlib import Path


OBSERVATION_FILES = {
    "eta": "eta_predictions.csv",
    "vehicles": "bus_positions.csv",
}
CSV_FIELDS = [
    "session_id",
    "request_started_at",
    "request_finished_at",
    "response_received_at",
    "stop_id",
    "data",
    "error",
]
ROUTE_ETA_FILE = "eta_predictions_by_route.csv"
ROUTE_CSV_FIELDS = ["session_id", "route_id", *CSV_FIELDS[1:]]


class CSVStorage:
    """Append raw collection observations to CSV files for one session.

    Store one row per API request, preserving complete decoded responses as
    JSON strings. Route ETA observations to eta_predictions.csv and vehicle
    observations to bus_positions.csv. Do not filter buses, interpret API
    fields, detect arrivals, or calculate prediction errors here.

    Original CSV columns, in order:
        session_id, request_started_at, request_finished_at,
        response_received_at, stop_id, data, error.

    ETA observations with an explicit requested route_id go into
    eta_predictions_by_route.csv with route_id after session_id. Original
    files are not migrated or rewritten; readers support both ETA formats.

    A session ID identifies one collection run and is shared across its ETA
    and vehicle rows. The caller supplies it; storage does not generate a new
    ID for each observation. Save a session's route/stop metadata and
    configuration separately as a JSON snapshot.
    """

    def __init__(self, session_id, data_dir="data"):
        """Configure the session ID and output directory without writing rows.

        Args:
            session_id: A nonempty string identifying the collection run.
                The caller should generate a unique ID for each new run.
            data_dir: Directory containing the collection CSV files.

        Existing files and observations must be preserved. Directory
        creation and header handling belong to the first write operation.

        Raises:
            ValueError: If session_id is not a nonempty string.
        """
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")

        self.session_id = session_id
        self.data_dir = Path(data_dir)

    def _metadata_path(self):
        invalid_component = self.session_id in (".", "..") or any(
            separator in self.session_id for separator in ("/", "\\")
        )
        if invalid_component:
            raise ValueError("session_id must be a single filename component")
        return self.data_dir / "sessions" / f"{self.session_id}.json"

    def _observation_path(self, request_type):
        if request_type not in OBSERVATION_FILES:
            raise ValueError(f"Unknown request type: {request_type!r}")
        return self.data_dir / OBSERVATION_FILES[request_type]

    def read_session_metadata(self):
        """Load this session's complete snapshot without modifying it."""
        snapshot = json.loads(self._metadata_path().read_text(encoding="utf-8"))
        if snapshot["session_id"] != self.session_id:
            raise ValueError("Snapshot session ID does not match requested session")
        return snapshot

    def read_observations(self, request_type):
        """Load collector-shaped observations for this session from a CSV.

        Decode JSON data, restore empty optional cells as None, and attach
        session_id plus source_ref identifying the file and logical CSV row
        (header is row 1). Keep failed requests for discontinuity handling.
        ETA reads combine the original and route-aware files when present;
        route_id is restored for rows in the new format.
        This is a read-only operation; malformed JSON or missing fields raise.
        """
        legacy_path = self._observation_path(request_type)
        paths = [legacy_path]
        if request_type == "eta":
            route_path = self.data_dir / ROUTE_ETA_FILE
            paths = [path for path in (legacy_path, route_path) if path.exists()]
            if not paths:
                paths = [legacy_path]
        observations = []
        for path in paths:
            observations.extend(self._read_observation_file(path, request_type))
        return observations

    def _read_observation_file(self, path, request_type):
        """Restore one schema while retaining the exact source filename/row."""
        observations = []
        with path.open(newline="", encoding="utf-8") as file:
            for row_number, row in enumerate(csv.DictReader(file), 2):
                if row["session_id"] != self.session_id:
                    continue
                observation = {
                    "session_id": self.session_id,
                    "request_type": request_type,
                    "request_started_at": row["request_started_at"],
                    "request_finished_at": row["request_finished_at"],
                    "response_received_at": row["response_received_at"] or None,
                    "stop_id": row["stop_id"] or None,
                    "data": json.loads(row["data"]),
                    "error": row["error"] or None,
                    "source_ref": {"file": path.name, "csv_row": row_number},
                }
                if "route_id" in row:
                    observation["route_id"] = row["route_id"]
                observations.append(observation)
        return observations

    def save_session_metadata(self, metadata):
        """Save metadata to data_dir/sessions/<session_id>.json once.

        Args:
            metadata: A JSON-serializable dictionary containing collection
                settings, the complete stop/route response, and timestamps
                bracketing that metadata request.

        Add this storage's session ID to the snapshot. Create the sessions
        directory if needed. Refuse to overwrite an existing snapshot and
        propagate serialization and file errors. The session ID must be a
        single filename component. Return the saved file's Path.
        """
        path = self._metadata_path()
        snapshot = {"session_id": self.session_id, "metadata": metadata}
        serialized = json.dumps(snapshot, indent=2, allow_nan=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as file:
            file.write(serialized + "\n")
        return path

    def save_observation(self, observation):
        """Append one timestamped observation with this storage's session ID.

        Args:
            observation: A dictionary returned by Collector.collect_once(),
                containing request_type, stop_id, request_started_at,
                request_finished_at, response_received_at, data, and error.

        Select eta_predictions_by_route.csv for ETA observations with
        route_id; otherwise use the original eta_predictions.csv. Vehicle
        observations use bus_positions.csv. The destination identifies the
        request type, so it is not repeated as a CSV column.

        Serialize data using JSON, preserving complete responses including
        empty results and API diagnostics. Represent failed-request data=None
        as JSON null. Write None in the other observation fields as an empty
        CSV cell. Preserve timestamps as supplied UTC ISO 8601 strings.

        Create the output directory if missing. Append to existing files;
        write a header only for a new or empty file. Reject unknown request
        types and incompatible existing headers before appending. Propagate
        serialization and file errors so the caller cannot mistake a failed
        write for a saved observation. Leave actual_arrivals.csv untouched.

        Returns:
            None.
        """
        path = self._observation_path(observation["request_type"])
        row = {field: observation[field] for field in CSV_FIELDS[1:]}
        row["session_id"] = self.session_id
        row["data"] = json.dumps(row["data"], allow_nan=False)
        fieldnames = CSV_FIELDS
        if observation["request_type"] == "eta" and observation.get("route_id") is not None:
            route_id = str(observation["route_id"])
            if not route_id.strip():
                raise ValueError("route_id must not be empty")
            path = self.data_dir / ROUTE_ETA_FILE
            fieldnames = ROUTE_CSV_FIELDS
            row["route_id"] = route_id

        self.data_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a+", newline="", encoding="utf-8") as file:
            file.seek(0)
            header = next(csv.reader(file), None)
            if header is not None and header != fieldnames:
                raise ValueError(f"Incompatible CSV header in {path}")

            file.seek(0, 2)
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if header is None:
                writer.writeheader()
            writer.writerow(row)
