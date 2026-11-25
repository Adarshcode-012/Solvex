import json
import sqlite3
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / 'memory' / 'data' / 'solve_jobs.sqlite3'
PROCESS_ID = uuid.uuid4().hex


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, snapshot TEXT NOT NULL)')
    return connection


def save(job_id, job):
    snapshot = {**job, 'process_id': PROCESS_ID}
    with _connect() as connection:
        connection.execute('INSERT OR REPLACE INTO jobs VALUES (?, ?)', (job_id, json.dumps(snapshot)))


def load(job_id):
    with _connect() as connection:
        row = connection.execute('SELECT snapshot FROM jobs WHERE id = ?', (job_id,)).fetchone()
    if row is None:
        return None
    job = json.loads(row[0])
    if job['status'] == 'running' and job['process_id'] != PROCESS_ID:
        return None
    return job
