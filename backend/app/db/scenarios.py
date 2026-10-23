"""SQLite persistence for immutable scenario inputs and result snapshots."""
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


def database_path() -> Path:
    return Path(os.environ.get("EWASTE_SCENARIO_DB", Path(__file__).resolve().parents[3] / "data" / "scenarios.sqlite3"))


def _connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE IF NOT EXISTS scenario_runs (
        run_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, scenario_type TEXT NOT NULL,
        label TEXT NOT NULL, created_at TEXT NOT NULL, dataset_version TEXT NOT NULL,
        parameters_json TEXT NOT NULL, criteria_weights_json TEXT NOT NULL, results_json TEXT NOT NULL
    )""")
    return connection


def save_run(group_id, scenario_type, label, dataset_version, parameters, criteria_weights, results):
    run_id = str(uuid.uuid4())
    created = datetime.now(UTC).isoformat()
    with _connect() as db:
        db.execute("INSERT INTO scenario_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, group_id, scenario_type, label, created, dataset_version,
             json.dumps(parameters, sort_keys=True), json.dumps(criteria_weights, sort_keys=True),
             json.dumps(results, sort_keys=True)))
    return get_run(run_id)


def get_run(run_id):
    with _connect() as db:
        row = db.execute("SELECT * FROM scenario_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return {"run_id": row["run_id"], "group_id": row["group_id"], "scenario_type": row["scenario_type"],
        "label": row["label"], "created_at": row["created_at"], "dataset_version": row["dataset_version"],
        "parameters": json.loads(row["parameters_json"]), "criteria_weights": json.loads(row["criteria_weights_json"]),
        "results": json.loads(row["results_json"])}


def list_runs(group_id=None):
    with _connect() as db:
        if group_id:
            ids = db.execute("SELECT run_id FROM scenario_runs WHERE group_id = ? ORDER BY created_at", (group_id,)).fetchall()
        else:
            ids = db.execute("SELECT run_id FROM scenario_runs ORDER BY created_at").fetchall()
    return [get_run(row["run_id"]) for row in ids]
